"""
economic_calendar.py – Calendrier économique gratuit via ForexFactory XML.
Filtre USD uniquement. Aucun filtre d'impact — tous les niveaux affichés.
Cache en mémoire 30 min pour éviter les 429 Too Many Requests de ForexFactory.
"""

import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from config import FF_WEEK_URL, FF_MONTH_URL

log = logging.getLogger(__name__)

HEADERS      = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
IMPACT_EMOJI = {"High": "🔴", "Medium": "🟡", "Low": "⚪", "Holiday": "🏦"}
TARGET       = {"USD"}
FLAG_MAP     = {"USD": "🇺🇸"}

# Cache données : {url: (fetched_at, events_list)}
_CACHE: dict[str, tuple[datetime, list]] = {}
CACHE_TTL = timedelta(minutes=30)

# Cache ban 429 : {url: retry_after_datetime}
_BAN: dict[str, datetime] = {}


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


def _tag(item, name: str) -> str:
    el = item.find(name)
    return el.text.strip() if el is not None and el.text else ""


def _parse(url: str) -> list:
    """Parse le flux ForexFactory XML avec cache 30 min pour éviter les 429."""
    now = datetime.now(timezone.utc)

    # Si encore banni par un 429 précédent, ne pas retenter
    if url in _BAN and now < _BAN[url]:
        wait = int((_BAN[url] - now).total_seconds())
        log.debug("Calendar: encore banni %ds, retour cache", wait)
        return _CACHE.get(url, (None, []))[1]

    # Retourne le cache si encore frais
    if url in _CACHE:
        fetched_at, cached_events = _CACHE[url]
        if now - fetched_at < CACHE_TTL:
            return cached_events

    events = _fetch_and_parse(url)

    if events is not None:
        _CACHE[url] = (now, events)
        _BAN.pop(url, None)
        return events

    # Si erreur réseau, utilise le cache périmé s'il existe
    if url in _CACHE:
        _, stale = _CACHE[url]
        log.warning("Calendar: using stale cache for %s", url)
        return stale

    return []


def _fetch_and_parse(url: str) -> list | None:
    """Fetch + parse XML. Retourne None si erreur réseau."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except requests.HTTPError as exc:
        if resp.status_code == 429:
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
    for item in root.findall(".//event"):
        currency = _tag(item, "country")
        if currency not in TARGET:
            continue
        impact = _tag(item, "impact")

        date_str = _tag(item, "date")
        try:
            date_obj = datetime.strptime(date_str, "%m-%d-%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                date_obj = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            except Exception:
                continue

        time_str = _tag(item, "time")
        if time_str and time_str.lower() not in ("all day", "tentative", ""):
            try:
                t = datetime.strptime(time_str.upper(), "%I:%M%p")
                date_obj = date_obj.replace(hour=t.hour, minute=t.minute)
            except Exception:
                pass

        events.append(EconEvent(
            date=date_obj,
            currency=currency,
            impact=impact,
            title=_tag(item, "title"),
            forecast=_tag(item, "forecast"),
            previous=_tag(item, "previous"),
            actual=_tag(item, "actual"),
        ))

    events.sort(key=lambda e: e.date)
    log.info("Calendar fetched %d USD events from %s", len(events), url)
    return events


def invalidate_cache() -> None:
    """Force un re-fetch au prochain appel (ex: après un event important)."""
    _CACHE.clear()


def get_week_events()  -> list: return _parse(FF_WEEK_URL)
def get_month_events() -> list: return _parse(FF_MONTH_URL)


def get_day_events() -> list:
    """Tous les événements USD du jour courant, sans filtre d'impact."""
    today  = datetime.now(timezone.utc).date()
    events = _parse(FF_WEEK_URL)
    return [e for e in events if e.date.date() == today]


def format_day_message(events: list) -> str:
    now = datetime.now(timezone.utc)

    if not events:
        return "<i>Aucun événement USD aujourd'hui.</i>"

    lines = []
    for e in events:
        time_s = e.date.strftime("%H:%M") if e.date.hour or e.date.minute else "All day"

        if e.is_past():
            status   = "✅"
            actual_s = f"  <b>Réel: {e.actual}</b>" if e.actual else "  <i>en attente</i>"
        else:
            delta = e.date - now
            mins  = int(delta.total_seconds() / 60)
            if mins < 60:
                status = f"⏰ dans {mins}min"
            else:
                h, m = divmod(mins, 60)
                status = f"⏰ dans {h}h{m:02d}"
            actual_s = ""

        fc_s   = f"  Prévu: <code>{e.forecast}</code>" if e.forecast else ""
        prev_s = f"  Préc: <code>{e.previous}</code>"  if e.previous else ""

        lines.append(
            f"{e.impact_emoji()} {e.flag()} <b>{e.title}</b>  "
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
            actual_s = f" → <b>{e.actual}</b>" if e.actual else ""
            fc_s     = f"  Prévu: {e.forecast}" if e.forecast else ""
            prev_s   = f"  Préc: {e.previous}" if e.previous else ""
            lines.append(
                f"{e.impact_emoji()} {e.flag()} <b>{e.title}</b>"
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
