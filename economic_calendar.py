"""
economic_calendar.py – Calendrier économique gratuit via ForexFactory (JSON).
Filtre USD uniquement. Aucun filtre d'impact — tous les niveaux affichés.

Le feed XML est rate-limité agressivement par Cloudflare sur les IP datacenter
(429 quasi-permanent). On utilise le endpoint JSON qui passe, avec :
  - headers navigateur complets,
  - cache mémoire 30 min,
  - cache DISQUE persistant (survit aux redémarrages),
  - respect du header retry-after sur 429.
"""

import json
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from html import escape as _esc
from pathlib import Path
from config import FF_WEEK_URL, FF_MONTH_URL

log = logging.getLogger(__name__)

# Headers navigateur complets — indispensables pour passer Cloudflare
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.forexfactory.com/",
}
IMPACT_EMOJI = {"High": "🔴", "Medium": "🟡", "Low": "⚪", "Holiday": "🏦"}
TARGET       = {"USD"}
FLAG_MAP     = {"USD": "🇺🇸"}

# Cache données : {url: (fetched_at, events_list)}
# 10 min = compromis : assez frais pour macro_engine, assez doux pour éviter les 429.
_CACHE: dict[str, tuple[datetime, list]] = {}
CACHE_TTL = timedelta(minutes=10)

# Cache ban 429 : {url: retry_after_datetime}
_BAN: dict[str, datetime] = {}

# Cache disque persistant (survit aux restarts → /day jamais vide après 1 fetch)
_DISK_CACHE_DIR = Path(__file__).parent / ".calendar_cache"
_DISK_TTL = timedelta(hours=6)


@dataclass
class EconEvent:
    date:     datetime
    currency: str
    impact:   str
    title:    str
    forecast: str
    previous: str
    actual:   str

    def flag(self)         -> str:  return FLAG_MAP.get(self.currency, "🌐")
    def impact_emoji(self) -> str:  return IMPACT_EMOJI.get(self.impact, "⚪")
    def is_past(self)      -> bool: return self.date < datetime.now(timezone.utc)


# ── Cache disque ──────────────────────────────────────────────────────────────

def _disk_path(url: str) -> Path:
    name = "week" if "thisweek" in url else "month"
    return _DISK_CACHE_DIR / f"{name}.json"


def _save_disk(url: str, events: list) -> None:
    try:
        _DISK_CACHE_DIR.mkdir(exist_ok=True)
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "events": [
                {**asdict(e), "date": e.date.isoformat()} for e in events
            ],
        }
        _disk_path(url).write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:
        log.debug("Calendar disk save error: %s", exc)


def _load_disk(url: str, ignore_ttl: bool = False) -> list | None:
    try:
        p = _disk_path(url)
        if not p.exists():
            return None
        payload = json.loads(p.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        if not ignore_ttl and datetime.now(timezone.utc) - fetched_at > _DISK_TTL:
            return None
        events = []
        for d in payload["events"]:
            d = dict(d)
            d["date"] = datetime.fromisoformat(d["date"])
            events.append(EconEvent(**d))
        return events
    except Exception as exc:
        log.debug("Calendar disk load error: %s", exc)
        return None


# ── Fetch principal ───────────────────────────────────────────────────────────

def _parse(url: str) -> list:
    """Récupère les events FF (JSON) avec cache mémoire 30 min + disque 6h."""
    now = datetime.now(timezone.utc)

    # 1. Cache mémoire frais
    if url in _CACHE:
        fetched_at, cached = _CACHE[url]
        if now - fetched_at < CACHE_TTL:
            return cached

    # 2. Si banni par 429, sert le meilleur cache dispo (mémoire → disque)
    if url in _BAN and now < _BAN[url]:
        if url in _CACHE:
            return _CACHE[url][1]
        disk = _load_disk(url, ignore_ttl=True)
        if disk is not None:
            return disk
        return []

    # 3. Fetch réseau
    events = _fetch_and_parse(url)
    if events is not None:
        _CACHE[url] = (now, events)
        _BAN.pop(url, None)
        _save_disk(url, events)
        return events

    # 4. Échec réseau → cache mémoire périmé
    if url in _CACHE:
        log.warning("Calendar: cache mémoire périmé utilisé pour %s", url)
        return _CACHE[url][1]

    # 5. Dernier recours → cache disque (même périmé)
    disk = _load_disk(url, ignore_ttl=True)
    if disk is not None:
        log.warning("Calendar: cache disque utilisé pour %s", url)
        _CACHE[url] = (now, disk)
        return disk

    return []


def _fetch_and_parse(url: str) -> list | None:
    """Fetch JSON ForexFactory. Retourne None si erreur réseau."""
    resp = None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as exc:
        if resp is not None and resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", 300))
            _BAN[url] = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
            log.warning("Calendar 429 — ban %ds pour %s", retry_after, url)
        else:
            log.warning("Calendar HTTP error [%s]: %s", url, exc)
        return None
    except Exception as exc:
        log.warning("Calendar error [%s]: %s", url, exc)
        return None

    events = []
    for item in data:
        currency = (item.get("country") or "").strip()
        # On garde TOUTES les devises dans le cache (macro_engine en a besoin) ;
        # le filtre USD est appliqué dans les getters publics ci-dessous.
        date_raw = item.get("date") or ""
        try:
            # Format ISO avec offset, ex: "2026-06-18T14:00:00-04:00"
            dt = datetime.fromisoformat(date_raw)
            date_obj = dt.astimezone(timezone.utc)
        except Exception:
            continue

        events.append(EconEvent(
            date=date_obj,
            currency=currency,
            impact=(item.get("impact") or "").strip(),
            title=(item.get("title") or "").strip(),
            forecast=(item.get("forecast") or "").strip(),
            previous=(item.get("previous") or "").strip(),
            actual=(item.get("actual") or "").strip(),
        ))

    events.sort(key=lambda e: e.date)
    log.info("Calendar fetched %d events (all currencies) from %s", len(events), url)
    return events


def invalidate_cache() -> None:
    """Force un re-fetch au prochain appel (ex: après un event important)."""
    _CACHE.clear()


# ── Getters publics ───────────────────────────────────────────────────────────
# Cache partagé : economic_calendar ET macro_engine passent par _parse(),
# donc une seule requête FF par 30 min couvre les deux → moitié moins de 429.

def get_week_raw() -> list:
    """Tous les events de la semaine, TOUTES devises (pour macro_engine)."""
    return _parse(FF_WEEK_URL)


def get_month_raw() -> list:
    """Tous les events du mois, TOUTES devises (pour macro_engine)."""
    return _parse(FF_MONTH_URL)


def get_week_events() -> list:
    """Events USD de la semaine, tous impacts."""
    return [e for e in _parse(FF_WEEK_URL) if e.currency in TARGET]


def get_month_events() -> list:
    """Events USD du mois, tous impacts."""
    return [e for e in _parse(FF_MONTH_URL) if e.currency in TARGET]


def get_day_events() -> list:
    """Events USD du jour courant, tous impacts."""
    today = datetime.now(timezone.utc).date()
    return [
        e for e in _parse(FF_WEEK_URL)
        if e.currency in TARGET and e.date.date() == today
    ]


def format_day_message(events: list) -> str:
    now = datetime.now(timezone.utc)

    if not events:
        return "<i>Aucun événement USD aujourd'hui.</i>"

    lines = []
    for e in events:
        time_s = e.date.strftime("%H:%M") if e.date.hour or e.date.minute else "All day"

        if e.is_past():
            status   = "✅"
            actual_s = f"  <b>Réel: {_esc(e.actual)}</b>" if e.actual else "  <i>en attente</i>"
        else:
            delta = e.date - now
            mins  = int(delta.total_seconds() / 60)
            if mins < 60:
                status = f"⏰ dans {mins}min"
            else:
                h, m = divmod(mins, 60)
                status = f"⏰ dans {h}h{m:02d}"
            actual_s = ""

        fc_s   = f"  Prévu: <code>{_esc(e.forecast)}</code>" if e.forecast else ""
        prev_s = f"  Préc: <code>{_esc(e.previous)}</code>"  if e.previous else ""

        lines.append(
            f"{e.impact_emoji()} {e.flag()} <b>{_esc(e.title)}</b>  "
            f"<code>{time_s}</code>  {status}"
            f"{actual_s}{fc_s}{prev_s}"
        )

    return "\n".join(lines)


def format_week_message(events: list) -> str:
    if not events:
        return "<i>Aucun événement USD cette semaine.</i>"

    by_day: dict = {}
    for e in events:
        key = e.date.strftime("%A %d %B").upper()
        by_day.setdefault(key, []).append(e)

    lines = []
    for day, evts in by_day.items():
        lines.append(f"\n📅 <b>{day}</b>")
        for e in evts:
            actual_s = f" → <b>{_esc(e.actual)}</b>" if e.actual else ""
            fc_s     = f"  Prévu: {_esc(e.forecast)}" if e.forecast else ""
            prev_s   = f"  Préc: {_esc(e.previous)}" if e.previous else ""
            lines.append(
                f"{e.impact_emoji()} {e.flag()} <b>{_esc(e.title)}</b>"
                f"{actual_s}{fc_s}{prev_s}"
            )
    return "\n".join(lines)


def format_month_summary(events: list) -> str:
    past = [e for e in events if e.is_past()]
    if not past:
        return "Aucune donnée économique disponible."
    lines = []
    for e in past[-25:]:
        actual_s = f" Réel={e.actual}" if e.actual else ""
        fc_s     = f" Prévu={e.forecast}" if e.forecast else ""
        prev_s   = f" Préc={e.previous}" if e.previous else ""
        lines.append(
            f"[{e.date.strftime('%d/%m')}] {e.currency} {e.impact_emoji()} "
            f"{e.title}:{actual_s}{fc_s}{prev_s}"
        )
    return "\n".join(lines)
