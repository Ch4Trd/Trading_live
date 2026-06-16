"""
macro_engine.py
Moteur de push macro instantané — latence ~10-30s post-release.

Architecture :
  1. Poll ForexFactory XML toutes les POLL_INTERVAL secondes
  2. Mode "turbo" (5s) automatique quand un event HIGH arrive dans <3min
  3. Détecte l'apparition du champ <actual> → fire immédiatement
  4. Qualifie : HAWKISH / DOVISH / NEUTRE selon la déviation
  5. Analyse temporelle CT/MT/LT via historique JSON local (state machine)
  6. Push aux subscribers via bot.send_message (non-bloquant asyncio)

Performance : asyncio.Task indépendant — zéro impact sur les 25 autres commandes.
"""

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html import escape as _esc
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

POLL_INTERVAL      = 60      # secondes (mode normal) — réduit de 15→60s pour éviter les 429 FF
TURBO_INTERVAL     = 30      # secondes (event dans <3 min) — réduit de 5→30s
LOOKAHEAD_HOURS    = 12      # surveiller events dans les 12h
FIRED_TTL_HOURS    = 6       # oublier les events déclenchés après 6h
MAX_HISTORY        = 12      # garder les 12 dernières releases par event
HISTORY_FILE       = Path(__file__).parent / "macro_history.json"
FF_WEEK_URL        = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
FF_MONTH_URL       = "https://nfs.faireconomy.media/ff_calendar_thismonth.xml"
HEADERS            = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ── Catalogue des events HIGH à surveiller ────────────────────────────────────
# Clé : substring lowercase à matcher dans le titre FF
# usd_dir : "hawkish_if_high" = actual > forecast → USD haussier
#           "hawkish_if_low"  = actual > forecast → USD baissier (ex: chômage)

MACRO_CATALOG: dict[str, dict] = {
    "core cpi":               {"label": "Core CPI",          "type": "inflation",    "usd_dir": "hawkish_if_high"},
    "cpi":                    {"label": "CPI",               "type": "inflation",    "usd_dir": "hawkish_if_high"},
    "core pce":               {"label": "Core PCE",          "type": "inflation",    "usd_dir": "hawkish_if_high"},
    "pce":                    {"label": "PCE",               "type": "inflation",    "usd_dir": "hawkish_if_high"},
    "core ppi":               {"label": "Core PPI",          "type": "inflation",    "usd_dir": "hawkish_if_high"},
    "ppi":                    {"label": "PPI",               "type": "inflation",    "usd_dir": "hawkish_if_high"},
    "nonfarm payroll":        {"label": "NFP",               "type": "employment",   "usd_dir": "hawkish_if_high"},
    "nfp":                    {"label": "NFP",               "type": "employment",   "usd_dir": "hawkish_if_high"},
    "adp nonfarm":            {"label": "ADP NFP",           "type": "employment",   "usd_dir": "hawkish_if_high"},
    "jolts":                  {"label": "JOLTS",             "type": "employment",   "usd_dir": "hawkish_if_high"},
    "unemployment rate":      {"label": "Unemployment Rate", "type": "employment",   "usd_dir": "hawkish_if_low"},
    "initial jobless":        {"label": "Jobless Claims",    "type": "employment",   "usd_dir": "hawkish_if_low"},
    "jobless claims":         {"label": "Jobless Claims",    "type": "employment",   "usd_dir": "hawkish_if_low"},
    "fomc":                   {"label": "FOMC",              "type": "monetary",     "usd_dir": "hawkish_if_high"},
    "fed rate":               {"label": "Fed Rate",          "type": "monetary",     "usd_dir": "hawkish_if_high"},
    "interest rate decision": {"label": "Rate Decision",     "type": "monetary",     "usd_dir": "hawkish_if_high"},
    "gdp":                    {"label": "GDP",               "type": "growth",       "usd_dir": "hawkish_if_high"},
    "retail sales":           {"label": "Retail Sales",      "type": "consumption",  "usd_dir": "hawkish_if_high"},
    "ism manufacturing":      {"label": "ISM Mfg",           "type": "industry",     "usd_dir": "hawkish_if_high"},
    "ism services":           {"label": "ISM Services",      "type": "industry",     "usd_dir": "hawkish_if_high"},
    "michigan":               {"label": "Michigan",          "type": "sentiment",    "usd_dir": "hawkish_if_high"},
}

# ── Tables d'impact marché par qualification ───────────────────────────────────

_MARKET_IMPACT: dict[str, dict] = {
    "hawkish": {
        "💵 USD":     "📈 Haussier — taux élevés → carry favorable",
        "📈 Indices": "📉 Baissier — taux élevés → compression des multiples",
        "🥇 Or":      "📉 Baissier CT — USD fort = pression sur l'or",
        "📊 Bonds":   "📉 Baissier — yields ↑ → prix obligations ↓",
    },
    "dovish": {
        "💵 USD":     "📉 Baissier — pivot monétaire anticipé",
        "📈 Indices": "📈 Haussier — liquidités + taux bas → multiples ↑",
        "🥇 Or":      "📈 Haussier — USD faible + taux bas → or attractif",
        "📊 Bonds":   "📈 Haussier — yields ↓ → prix obligations ↑",
    },
    "neutral": {
        "💵 USD":     "➡️ Neutre — données conformes aux attentes",
        "📈 Indices": "➡️ Neutre — pas de surprise significative",
        "🥇 Or":      "➡️ Neutre",
        "📊 Bonds":   "➡️ Neutre",
    },
}

# ── Utilitaires ───────────────────────────────────────────────────────────────

def _parse_value(s: str) -> Optional[float]:
    """
    Parse les valeurs textuelles ForexFactory → float.
    Gère : '3.2%', '256K', '-15B', '1.234', '1.2M', 'N/A'.
    """
    if not s or s.strip() in ("", "—", "-", "N/A", "n/a", "Tentative"):
        return None
    s = s.strip().replace(",", "").replace(" ", "").replace("%", "")
    multipliers = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
    for suffix, mult in multipliers.items():
        if s.upper().endswith(suffix):
            try:
                return float(s[:-1]) * mult
            except ValueError:
                return None
    try:
        return float(s)
    except ValueError:
        return None


def _match_catalog(title: str) -> Optional[tuple[str, dict]]:
    """Matche un titre FF sur le catalogue. Tri par longueur de clé décroissant."""
    title_lower = title.lower()
    for key in sorted(MACRO_CATALOG.keys(), key=len, reverse=True):
        if key in title_lower:
            return key, MACRO_CATALOG[key]
    return None


def _event_uid(title: str, date_str: str) -> str:
    """UID déterministe pour identifier un event (title + date)."""
    return f"{title[:40].strip()}|{date_str[:10]}"


# ── Historique macro (state machine) ─────────────────────────────────────────

class MacroHistory:
    """
    Persiste les releases macro dans macro_history.json.
    Utilisé pour le calcul d'impact MT/LT.
    """

    def __init__(self):
        self._data: dict[str, list] = {}
        self._load()

    def _load(self):
        if HISTORY_FILE.exists():
            try:
                self._data = json.loads(HISTORY_FILE.read_text())
            except Exception:
                self._data = {}

    def _save(self):
        try:
            HISTORY_FILE.write_text(json.dumps(self._data, indent=2, default=str))
        except Exception as exc:
            log.warning("MacroHistory save error: %s", exc)

    def add(self, label: str, actual: float, forecast: Optional[float],
            previous: Optional[float], date_str: str, qualifier: str):
        """Ajoute une release. Dédoublonne par date (jour)."""
        key = label.lower()
        self._data.setdefault(key, [])
        # Ne pas dupliquer si même date
        if any(e.get("date", "")[:10] == date_str[:10] for e in self._data[key]):
            return
        self._data[key].append({
            "date":      date_str,
            "actual":    actual,
            "forecast":  forecast,
            "previous":  previous,
            "qualifier": qualifier,
        })
        self._data[key] = self._data[key][-MAX_HISTORY:]
        self._save()

    def get_recent(self, label: str, n: int = 6) -> list:
        """Retourne les n dernières releases du label donné."""
        return self._data.get(label.lower(), [])[-n:]

    def get_all_recent(self, n: int = 5) -> list:
        """Retourne les n releases les plus récentes toutes catégories confondues."""
        all_entries = []
        for label, entries in self._data.items():
            for e in entries:
                all_entries.append({**e, "_label": label})
        all_entries.sort(key=lambda x: x.get("date", ""), reverse=True)
        return all_entries[:n]


# ── Qualification de l'impact ─────────────────────────────────────────────────

def qualify_impact(
    catalog_entry: dict,
    actual: float,
    forecast: Optional[float],
    previous: Optional[float],
) -> dict:
    """
    Retourne un dict avec qualifier, label, deviation_str, surprise_emoji.
    Seuil de significativité : <0.5% de déviation → NEUTRE.
    """
    usd_dir   = catalog_entry.get("usd_dir", "hawkish_if_high")
    reference = forecast if forecast is not None else previous

    if reference is None:
        return {
            "qualifier":      "neutral",
            "label":          "NEUTRE ➡️",
            "deviation_abs":  0.0,
            "deviation_pct":  None,
            "deviation_str":  "N/A",
            "surprise_emoji": "➡️ CONFORME",
        }

    deviation_abs = actual - reference
    deviation_pct = (deviation_abs / abs(reference) * 100) if reference != 0 else None

    # Seuil de significativité
    is_significant = (deviation_pct is None) or (abs(deviation_pct) >= 0.5)

    if not is_significant:
        qualifier = "neutral"
    else:
        is_above = deviation_abs > 0
        if usd_dir == "hawkish_if_high":
            qualifier = "hawkish" if is_above else "dovish"
        else:  # hawkish_if_low
            qualifier = "dovish" if is_above else "hawkish"

    labels  = {"hawkish": "HAWKISH 🦅", "dovish": "DOVISH 🕊️", "neutral": "NEUTRE ➡️"}
    surprises = {
        "hawkish": "📈 SURPRISE HAUSSIÈRE",
        "dovish":  "📉 SURPRISE BAISSIÈRE",
        "neutral": "➡️ CONFORME AUX ATTENTES",
    }

    dev_str = f"{deviation_abs:+.4g}"
    if deviation_pct is not None:
        dev_str += f"  ({deviation_pct:+.1f}%)"

    return {
        "qualifier":      qualifier,
        "label":          labels[qualifier],
        "deviation_abs":  deviation_abs,
        "deviation_pct":  deviation_pct,
        "deviation_str":  dev_str,
        "surprise_emoji": surprises[qualifier],
    }


# ── Analyse temporelle CT / MT / LT ──────────────────────────────────────────

def compute_temporal(label: str, history: MacroHistory, qualifier: str) -> dict:
    """
    Court terme  : basé sur la déviation actuelle
    Moyen terme  : tendance des 3 dernières releases
    Long terme   : tendance des 6-10 dernières releases
    """
    st_map = {
        "hawkish": "💵 Spike USD haussier, sell indices, sell or",
        "dovish":  "💵 Pression USD, bid indices, bid or",
        "neutral": "Réaction limitée — données conformes",
    }
    st = st_map.get(qualifier, "")

    recent = history.get_recent(label, n=8)

    if len(recent) < 2:
        return {
            "st":          st,
            "mt":          "Historique insuffisant (première release ou données manquantes)",
            "lt":          "Historique insuffisant",
            "streak":      1,
            "trend_lines": [],
        }

    qualifiers = [r["qualifier"] for r in recent]

    # Streak : combien de fois consécutif le même qualifier en fin de liste
    streak = 1
    for i in range(len(qualifiers) - 2, -1, -1):
        if qualifiers[i] == qualifier:
            streak += 1
        else:
            break

    # Moyen terme (3 dernières)
    mt_q   = [r["qualifier"] for r in recent[-3:]]
    mt_hawk = mt_q.count("hawkish")
    mt_dove = mt_q.count("dovish")
    n_mt    = len(mt_q)
    if mt_hawk >= 2:
        mt = f"🔴 {mt_hawk}/{n_mt} releases HAWKISH récentes → pression maintenue sur USD"
    elif mt_dove >= 2:
        mt = f"🟢 {mt_dove}/{n_mt} releases DOVISH récentes → biais dovish installé"
    else:
        mt = "🟡 Données mixtes — pas de tendance forte sur 1-5 jours"

    # Long terme (toutes les releases disponibles)
    n_lt    = len(qualifiers)
    hawk_lt = qualifiers.count("hawkish")
    dove_lt = qualifiers.count("dovish")
    if hawk_lt >= n_lt * 0.6:
        lt = f"🔴 Biais HAWKISH cumulatif ({hawk_lt}/{n_lt} releases) — pression inflationniste persistante"
    elif dove_lt >= n_lt * 0.6:
        lt = f"🟢 Biais DOVISH cumulatif ({dove_lt}/{n_lt} releases) — désinflation structurelle en cours"
    else:
        neut_lt = n_lt - hawk_lt - dove_lt
        lt = f"🟡 Signal mixte LT ({hawk_lt}🦅 / {dove_lt}🕊️ / {neut_lt}➡️) — pas de tendance claire"

    # Lignes de tendance pour affichage
    trend_lines = []
    for r in recent[-5:]:
        q     = r.get("qualifier", "neutral")
        emoji = "🦅" if q == "hawkish" else ("🕊️" if q == "dovish" else "➡️")
        date_s   = r.get("date", "")[:7]
        actual_s = str(r.get("actual", "?"))
        fc_s     = str(r.get("forecast", "N/A"))
        trend_lines.append(f"  {date_s} : Réel=<b>{_esc(actual_s)}</b>  Prévu={_esc(fc_s)}  {emoji}")

    return {
        "st":          st,
        "mt":          mt,
        "lt":          lt,
        "streak":      streak,
        "trend_lines": trend_lines,
    }


# ── Formatage du message flash ────────────────────────────────────────────────

def format_macro_flash(
    event_title:  str,
    currency:     str,
    event_time:   datetime,
    actual_raw:   str,
    forecast_raw: str,
    previous_raw: str,
    catalog_entry: dict,
    impact:       dict,
    temporal:     dict,
) -> str:
    flag_map  = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "CAD": "🇨🇦", "JPY": "🇯🇵"}
    flag      = flag_map.get(currency, "🌐")
    time_str  = event_time.strftime("%H:%M UTC") if event_time else "??:??"
    qualifier = impact["qualifier"]

    lines = [
        f"⚡ <b>MACRO FLASH — {_esc(catalog_entry['label'])}</b>",
        "━" * 32,
        f"{flag} <b>{currency}</b>  🔴 HIGH IMPACT  |  {time_str}",
        "",
        f"Réel      : <b>{_esc(actual_raw)}</b>  {impact['surprise_emoji']}",
        f"Prévision : <code>{_esc(forecast_raw) if forecast_raw else 'N/A'}</code>",
        f"Précédent : <code>{_esc(previous_raw) if previous_raw else 'N/A'}</code>",
        f"Déviation : <b>{impact['deviation_str']}</b>",
        "",
        f"Qualification : <b>{impact['label']}</b>",
        "━" * 32,
        "",
        "📊 <b>IMPACT MARCHÉ IMMÉDIAT</b>",
    ]

    market = _MARKET_IMPACT.get(qualifier, _MARKET_IMPACT["neutral"])
    for asset_label, desc in market.items():
        lines.append(f"  {asset_label} : {desc}")

    lines += [
        "",
        "⏱ <b>ANALYSE TEMPORELLE</b>",
        f"  Court terme (0-30min) : {temporal['st']}",
        f"  Moyen terme (1-5j)    : {temporal['mt']}",
        f"  Long terme  (1-3M)    : {temporal['lt']}",
    ]

    if temporal["trend_lines"]:
        lines += [
            "",
            f"📈 <b>HISTORIQUE {catalog_entry['label'].upper()} (dernières releases)</b>",
        ] + temporal["trend_lines"]

    if temporal["streak"] >= 3:
        lines += [
            "",
            f"⚠️ <b>{temporal['streak']} releases consécutives {impact['label'].split()[0]}</b>",
            "   → Tendance directionnelle forte — biais renforcé",
        ]

    lines += [
        "",
        "━" * 32,
        "⚡ <b>tradingLIVE</b> | /analyze NQ | /analyze GOLD | /vix",
    ]
    return "\n".join(lines)


# ── MacroEngine : moteur principal ────────────────────────────────────────────

class MacroEngine:
    """
    Tâche asyncio qui poll ForexFactory XML et push les releases macro.
    Lancé via asyncio.create_task(macro_engine.run(bot, subs, market_subs)).
    """

    def __init__(self):
        self._running:     bool              = False
        self._turbo:       bool              = False
        # uid → "pending" | "fired"
        self._event_state: dict[str, str]   = {}
        # uid → datetime (pour le TTL)
        self._fired_at:    dict[str, datetime] = {}
        # uid → event_time (pour le calcul turbo)
        self._event_times: dict[str, datetime] = {}
        self.history = MacroHistory()
        # Cache local : {url: (fetched_at, root_element)}
        self._xml_cache: dict[str, tuple[datetime, object]] = {}
        self._xml_ban:   dict[str, datetime]                = {}
        self._XML_TTL = timedelta(seconds=55)  # légèrement sous POLL_INTERVAL

    # ── Cache XML ─────────────────────────────────────────────────────────────

    def _get_xml(self, url: str):
        """Retourne l'élément XML racine avec cache 55s + gestion ban 429."""
        now = datetime.now(timezone.utc)
        if url in self._xml_ban and now < self._xml_ban[url]:
            return self._xml_cache.get(url, (None, None))[1]
        if url in self._xml_cache:
            fetched_at, root = self._xml_cache[url]
            if now - fetched_at < self._XML_TTL:
                return root
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            self._xml_cache[url] = (now, root)
            self._xml_ban.pop(url, None)
            return root
        except requests.HTTPError as exc:
            if hasattr(exc, 'response') and exc.response is not None and exc.response.status_code == 429:
                retry = int(exc.response.headers.get("retry-after", 300))
                self._xml_ban[url] = now + timedelta(seconds=retry)
                log.warning("macro_engine 429 — ban %ds pour %s", retry, url)
            else:
                log.debug("macro_engine fetch [%s]: %s", url, exc)
            return self._xml_cache.get(url, (None, None))[1]
        except Exception as exc:
            log.debug("macro_engine fetch [%s]: %s", url, exc)
            return self._xml_cache.get(url, (None, None))[1]

    # ── Fetch + parse FF XML ──────────────────────────────────────────────────

    def _fetch_events(self) -> list[dict]:
        """Récupère et parse les events HIGH du calendrier FF avec cache 55s."""
        events = []
        for url in (FF_WEEK_URL, FF_MONTH_URL):
            root = self._get_xml(url)
            if root is None:
                continue

            for item in root.findall(".//event"):

                def _t(name: str) -> str:
                    el = item.find(name)
                    return el.text.strip() if el is not None and el.text else ""

                currency = _t("country")
                impact   = _t("impact")
                if impact != "High":
                    continue
                if currency not in ("USD", "EUR", "GBP", "CAD"):
                    continue

                title = _t("title")
                match = _match_catalog(title)
                if not match:
                    continue

                date_str  = _t("date")
                time_str  = _t("time")
                actual    = _t("actual")
                forecast  = _t("forecast")
                previous  = _t("previous")

                try:
                    date_obj = datetime.strptime(date_str, "%m-%d-%Y").replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                if time_str and time_str.lower() not in ("all day", "tentative", ""):
                    try:
                        t = datetime.strptime(time_str.upper(), "%I:%M%p")
                        date_obj = date_obj.replace(hour=t.hour, minute=t.minute)
                    except Exception:
                        pass

                events.append({
                    "uid":      _event_uid(title, date_str),
                    "title":    title,
                    "currency": currency,
                    "date":     date_obj,
                    "actual":   actual,
                    "forecast": forecast,
                    "previous": previous,
                    "catalog":  match[1],
                })
            break  # semaine courante suffit en priorité
        return events

    # ── Nettoyage TTL ─────────────────────────────────────────────────────────

    def _cleanup(self):
        now    = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=FIRED_TTL_HOURS)
        stale  = [uid for uid, ts in self._fired_at.items() if ts < cutoff]
        for uid in stale:
            self._event_state.pop(uid, None)
            self._fired_at.pop(uid, None)
            self._event_times.pop(uid, None)

    # ── Calcul intervalle adaptatif ───────────────────────────────────────────

    def _poll_interval(self) -> int:
        """Passe en mode turbo (5s) si un event arrive dans <3 minutes."""
        now = datetime.now(timezone.utc)
        for uid, event_time in self._event_times.items():
            if self._event_state.get(uid) == "pending":
                delta = (event_time - now).total_seconds()
                if -60 <= delta <= 180:
                    return TURBO_INTERVAL
        return POLL_INTERVAL

    # ── Vérification + déclenchement ─────────────────────────────────────────

    async def _check_releases(self, bot, breaking_subs: set, market_subs: set):
        now    = datetime.now(timezone.utc)
        events = await asyncio.get_running_loop().run_in_executor(None, self._fetch_events)

        for ev in events:
            uid        = ev["uid"]
            event_time = ev["date"]
            actual_raw = ev["actual"]

            # Hors fenêtre de surveillance
            delta_h = (event_time - now).total_seconds() / 3600
            if delta_h > LOOKAHEAD_HOURS or delta_h < -2:
                continue

            # Enregistrer le timing pour le mode turbo
            self._event_times[uid] = event_time

            # Nouveau event → pending
            if uid not in self._event_state:
                self._event_state[uid] = "pending"
                log.info("macro_engine: suivi [%s] @ %s UTC",
                         ev["title"], event_time.strftime("%H:%M"))

            # Actual apparu + state pending → FIRE
            if actual_raw and self._event_state.get(uid) == "pending":
                self._event_state[uid] = "fired"
                self._fired_at[uid]    = now
                log.info("macro_engine: FIRE [%s]  actual=%s", ev["title"], actual_raw)

                # Calcul impact
                actual_f   = _parse_value(actual_raw)
                forecast_f = _parse_value(ev["forecast"])
                previous_f = _parse_value(ev["previous"])

                if actual_f is None:
                    log.debug("macro_engine: actual non parseable [%s]", actual_raw)
                    continue

                impact   = qualify_impact(ev["catalog"], actual_f, forecast_f, previous_f)
                label    = ev["catalog"]["label"]
                temporal = compute_temporal(label, self.history, impact["qualifier"])

                # Sauvegarder dans l'historique
                self.history.add(
                    label, actual_f, forecast_f, previous_f,
                    now.isoformat(), impact["qualifier"],
                )

                # Formater le message
                msg_text = format_macro_flash(
                    event_title=ev["title"],
                    currency=ev["currency"],
                    event_time=event_time,
                    actual_raw=actual_raw,
                    forecast_raw=ev["forecast"],
                    previous_raw=ev["previous"],
                    catalog_entry=ev["catalog"],
                    impact=impact,
                    temporal=temporal,
                )

                # Envoyer à tous les subscribers (breaking + market)
                all_subs = breaking_subs | market_subs
                for chat_id in all_subs:
                    try:
                        await bot.send_message(
                            chat_id=int(chat_id),
                            text=msg_text,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                    except Exception as exc:
                        log.warning("macro_engine send [%s]: %s", chat_id, exc)

    # ── Boucle principale ─────────────────────────────────────────────────────

    async def run(self, bot, breaking_subscribers: set, market_subscribers: set):
        """
        Point d'entrée principal. Appeler via asyncio.create_task().
        Les sets subscribers sont passés par référence : toute mise à jour
        dans bot.py est automatiquement reflétée ici.
        """
        self._running = True
        log.info("MacroEngine démarré — poll=%ds / turbo=%ds", POLL_INTERVAL, TURBO_INTERVAL)

        # Délai initial pour laisser le bot finir son démarrage
        await asyncio.sleep(12)

        while self._running:
            try:
                await self._check_releases(bot, breaking_subscribers, market_subscribers)
                self._cleanup()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("MacroEngine error: %s", exc, exc_info=True)

            interval = self._poll_interval()
            await asyncio.sleep(interval)

        log.info("MacroEngine arrêté.")

    def stop(self):
        self._running = False


# ── Singleton global (importé par bot.py et analyze_command.py) ───────────────
macro_engine = MacroEngine()
