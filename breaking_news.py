"""
breaking_news.py – Alertes breaking news haute importance.
Polling toutes les 90 secondes sur flux RSS spécialisés.
Filtre par mots-clés critiques (FOMC, missile, crash, Trump speech...).
Message court, envoyé immédiatement.
"""

import hashlib
import json
import logging
import re
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from html import escape as _esc
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT  = 8
MAX_AGE_MINUTES  = 10   # ignore articles plus vieux que 10 min
SEEN_FILE        = Path(__file__).parent / "breaking_seen.json"

# ── Flux RSS ultra-rapides ────────────────────────────────────────────────────

BREAKING_FEEDS = {
    "Reuters":      "https://feeds.reuters.com/reuters/businessNews",
    "AP Politics":  "https://feeds.apnews.com/rss/apf-politics",
    "AP Business":  "https://feeds.apnews.com/rss/apf-business",
    "CNBC":         "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "MarketWatch":  "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
    "ForexLive":    "https://www.forexlive.com/feed/news",
    "FXStreet":     "https://www.fxstreet.com/rss/news",
    "Politico":     "https://rss.politico.com/politics-news.xml",
    "The Hill":     "https://thehill.com/feed/",
    "BBC World":    "https://feeds.bbci.co.uk/news/world/rss.xml",
}

# ── Mots-clés HIGH IMPACT ─────────────────────────────────────────────────────
# Chaque sous-liste = un sujet. Un seul match suffit.

BREAKING_KEYWORDS: list[tuple[str, str]] = [
    # (emoji_catégorie, keyword)
    # Fed / Banques centrales
    ("🏦", "federal reserve"),
    ("🏦", "fomc"),
    ("🏦", "fed rate"),
    ("🏦", "rate decision"),
    ("🏦", "rate hike"),
    ("🏦", "rate cut"),
    ("🏦", "jerome powell"),
    ("🏦", "ecb rate"),
    ("🏦", "bank of england"),
    ("🏦", "boj rate"),
    ("🏦", "interest rate decision"),
    # Données macro
    ("📊", "nonfarm payroll"),
    ("📊", "nfp"),
    ("📊", "cpi report"),
    ("📊", "inflation report"),
    ("📊", "gdp report"),
    ("📊", "unemployment rate"),
    ("📊", "jobs report"),
    ("📊", "pcе"),
    ("📊", "ism manufacturing"),
    ("📊", "retail sales"),
    # Trump / POTUS
    ("🔴", "trump signs"),
    ("🔴", "trump announces"),
    ("🔴", "trump declares"),
    ("🔴", "trump orders"),
    ("🔴", "trump speech"),
    ("🔴", "trump says"),
    ("🔴", "executive order"),
    ("🔴", "tariff"),
    ("🔴", "trade war"),
    ("🔴", "white house announces"),
    # Géopolitique / Guerre
    ("⚠️", "missile"),
    ("⚠️", "nuclear"),
    ("⚠️", "military strike"),
    ("⚠️", "war declared"),
    ("⚠️", "invasion"),
    ("⚠️", "attack on"),
    ("⚠️", "explosion"),
    ("⚠️", "ceasefire"),
    ("⚠️", "sanctions"),
    ("⚠️", "nato"),
    # Marchés / Crash
    ("📉", "market crash"),
    ("📉", "circuit breaker"),
    ("📉", "trading halted"),
    ("📉", "stock market crash"),
    ("📉", "dow plunges"),
    ("📉", "nasdaq plunges"),
    ("📉", "flash crash"),
    ("📉", "bank collapse"),
    ("📉", "bank failure"),
    ("📉", "bankruptcy"),
    ("📉", "default"),
    ("📉", "recession"),
    ("📉", "emergency rate"),
    # Energie / Pétrole
    ("🛢️", "opec"),
    ("🛢️", "oil embargo"),
    ("🛢️", "oil price crash"),
    # Crypto / Tech majeur
    ("₿", "bitcoin crash"),
    ("₿", "crypto ban"),
    ("💻", "nvidia earnings"),
    ("💻", "apple earnings"),
    ("💻", "microsoft earnings"),
]

KEYWORD_MAP: dict[str, str] = {kw: emoji for emoji, kw in BREAKING_KEYWORDS}


def _get_emoji(title: str) -> str:
    low = title.lower()
    for kw, emoji in KEYWORD_MAP.items():
        if kw in low:
            return emoji
    return "🔴"


def _is_breaking(title: str, summary: str = "") -> bool:
    combined = (title + " " + summary).lower()
    return any(kw in combined for kw in KEYWORD_MAP)


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class BreakingItem:
    title:     str
    source:    str
    url:       str
    published: Optional[datetime]
    summary:   str = ""

    def uid(self) -> str:
        key = self.url or self.title[:80]
        return hashlib.md5(key.encode()).hexdigest()


# ── Détection événements FOMC/Fed ─────────────────────────────────────────────

_FOMC_PAIRS: list[tuple[str, ...]] = [
    ("fomc", "statement"),
    ("fomc", "decision"),
    ("fomc", "minutes"),
    ("fomc", "rate"),
    ("federal reserve", "decision"),
    ("federal reserve", "holds"),
    ("federal reserve", "cuts"),
    ("federal reserve", "raises"),
    ("federal reserve", "rate"),
    ("fed", "rate decision"),
    ("fed", "rate cut"),
    ("fed", "rate hike"),
    ("fed", "minutes"),
    ("powell", "press conference"),
    ("powell", "statement"),
    ("powell", "speech"),
    ("interest rate decision",),
    ("monetary policy statement",),
]


def is_fomc_announcement(title: str) -> bool:
    """Vrai si le titre correspond à une décision/minutes/discours Fed."""
    low = title.lower()
    for kws in _FOMC_PAIRS:
        if all(kw in low for kw in kws):
            return True
    return False


# ── Seen persistence ──────────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()).get("ids", []))
        except Exception:
            pass
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps({"ids": list(seen)[-1000:]}))


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _fetch_feed(source: str, url: str) -> list[BreakingItem]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        log.debug("Breaking feed error [%s]: %s", source, exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=MAX_AGE_MINUTES)
    items  = []

    for entry in feed.entries[:15]:
        title   = re.sub(r"<[^>]+>", "", getattr(entry, "title", "")).strip()
        summary = re.sub(r"<[^>]+>", "", getattr(entry, "summary", "")).strip()
        link    = getattr(entry, "link", "").strip()
        pub     = _parse_date(entry)

        if not title:
            continue
        # Article sans date ou trop vieux → ignoré
        if not pub or pub < cutoff:
            continue
        if not _is_breaking(title, summary):
            continue

        items.append(BreakingItem(title=title, source=source, url=link, published=pub, summary=summary[:400]))

    return items


def fetch_breaking_news() -> list[BreakingItem]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_items: list[BreakingItem] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_fetch_feed, src, url): src
            for src, url in BREAKING_FEEDS.items()
        }
        for future in as_completed(futures):
            try:
                all_items.extend(future.result())
            except Exception:
                pass

    # Déduplique
    seen_titles: set[str] = set()
    unique = []
    for item in all_items:
        key = item.title[:60].lower()
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(item)

    unique.sort(
        key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return unique


# ── Helper heure locale ───────────────────────────────────────────────────────

def _fmt_time(dt: Optional[datetime], tz_str: str = "UTC") -> str:
    if not dt:
        return "--:--"
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo(tz_str)).strftime("%H:%M %Z")
    except Exception:
        return dt.strftime("%H:%M UTC")


# ── Format ────────────────────────────────────────────────────────────────────

def format_breaking_alert(item: BreakingItem, tz: str = "UTC") -> str:
    emoji  = _get_emoji(item.title)
    time_s = _fmt_time(item.published, tz)
    lines  = [
        f"{emoji} <b>BREAKING</b>  <code>{time_s}</code>",
        f"<b>{_esc(item.title)}</b>",
        f"<i>{_esc(item.source)}</i>",
    ]
    if item.url:
        lines.append(f'<a href="{item.url}">🔗 Lire</a>  |  /deep /price')
    return "\n".join(lines)
