"""
market_filter.py – Filtrage ultra-rapide des news à fort impact marché.
Scoring par mots-clés pondérés, zéro appel API, latence < 1ms.

Score >= 8  → CRITICAL  (🔴 envoyé immédiatement)
Score 5-7   → HIGH      (🟠 envoyé immédiatement)
Score 2-4   → MEDIUM    (🟡 ignoré par le job temps réel)
Score <= 1  → LOW       (⚪ ignoré)

Seuil d'envoi : SEND_THRESHOLD = 5
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SEND_THRESHOLD = 5          # score minimum pour alerter
SEEN_FILE      = Path(__file__).parent / "market_seen.json"
MAX_SEEN       = 2000

# ── Mots-clés pondérés ────────────────────────────────────────────────────────
# Format : "keyword_lowercase" -> (score, emoji_catégorie)
# Un seul match suffit ; si plusieurs matchent, on prend le score max.

KEYWORD_SCORES: dict[str, tuple[int, str]] = {

    # ── CRITICAL (10) : décisions / chocs garantis ──
    "rate decision":           (10, "🏦"),
    "rate hike":               (10, "🏦"),
    "rate cut":                (10, "🏦"),
    "emergency rate":          (10, "🏦"),
    "fomc decision":           (10, "🏦"),
    "fomc statement":          (10, "🏦"),
    "nonfarm payroll":         (10, "📊"),
    "nfp":                     (10, "📊"),
    "bank failure":            (10, "📉"),
    "bank collapse":           (10, "📉"),
    "circuit breaker":         (10, "📉"),
    "trading halted":          (10, "📉"),
    "market crash":            (10, "📉"),
    "flash crash":             (10, "📉"),
    "war declared":            (10, "⚠️"),
    "nuclear":                 (10, "⚠️"),
    "default":                 (9,  "📉"),
    "sovereign default":       (10, "📉"),
    "cpi report":              (9,  "📊"),
    "inflation report":        (9,  "📊"),
    "gdp report":              (9,  "📊"),
    "gdp flash":               (9,  "📊"),
    "recession confirmed":     (10, "📉"),

    # ── HIGH (7-8) : news très market-moving ──
    "federal reserve":         (7,  "🏦"),
    "fomc":                    (7,  "🏦"),
    "jerome powell":           (7,  "🏦"),
    "fed chair":               (7,  "🏦"),
    "ecb rate":                (8,  "🏦"),
    "ecb decision":            (8,  "🏦"),
    "bank of england":         (7,  "🏦"),
    "boj":                     (7,  "🏦"),
    "bank of japan":           (7,  "🏦"),
    "rate guidance":           (7,  "🏦"),
    "quantitative tightening": (7,  "🏦"),
    "quantitative easing":     (7,  "🏦"),
    "tapering":                (7,  "🏦"),
    "tariff":                  (8,  "🔴"),
    "trade war":               (8,  "🔴"),
    "trade deal":              (7,  "🔴"),
    "sanctions":               (8,  "⚠️"),
    "oil embargo":             (8,  "🛢️"),
    "opec":                    (7,  "🛢️"),
    "opec+":                   (7,  "🛢️"),
    "oil output":              (7,  "🛢️"),
    "executive order":         (7,  "🔴"),
    "trump signs":             (7,  "🔴"),
    "trump announces":         (7,  "🔴"),
    "trump declares":          (8,  "🔴"),
    "trump orders":            (7,  "🔴"),
    "white house announces":   (7,  "🔴"),
    "earnings beat":           (7,  "💹"),
    "earnings miss":           (7,  "💹"),
    "earnings surprise":       (7,  "💹"),
    "revenue beat":            (6,  "💹"),
    "revenue miss":            (6,  "💹"),
    "profit warning":          (7,  "💹"),
    "guidance raised":         (6,  "💹"),
    "guidance lowered":        (7,  "💹"),
    "dow plunges":             (8,  "📉"),
    "nasdaq plunges":          (8,  "📉"),
    "s&p plunges":             (8,  "📉"),
    "dow surges":              (7,  "📈"),
    "nasdaq surges":           (7,  "📈"),
    "recession":               (7,  "📉"),
    "layoffs":                 (6,  "💼"),
    "mass layoffs":            (7,  "💼"),
    "bankruptcy":              (7,  "📉"),
    "ceasefire":               (7,  "⚠️"),
    "invasion":                (8,  "⚠️"),
    "missile":                 (7,  "⚠️"),
    "military strike":         (8,  "⚠️"),
    "attack on":               (7,  "⚠️"),
    "bitcoin etf":             (6,  "₿"),
    "crypto ban":              (8,  "₿"),
    "sec charges":             (6,  "⚖️"),
    "sec lawsuit":             (6,  "⚖️"),
    "antitrust":               (6,  "⚖️"),
    "nvidia earnings":         (7,  "💻"),
    "apple earnings":          (7,  "💻"),
    "microsoft earnings":      (7,  "💻"),
    "amazon earnings":         (7,  "💻"),
    "meta earnings":           (7,  "💻"),
    "google earnings":         (7,  "💻"),
    "tesla earnings":          (7,  "💻"),

    # ── MEDIUM (4-5) : données macro secondaires ──
    "unemployment rate":       (5,  "📊"),
    "jobs report":             (5,  "📊"),
    "jobless claims":          (4,  "📊"),
    "ism manufacturing":       (5,  "📊"),
    "ism services":            (4,  "📊"),
    "pmi":                     (4,  "📊"),
    "retail sales":            (5,  "📊"),
    "housing starts":          (4,  "📊"),
    "consumer confidence":     (4,  "📊"),
    "trade balance":           (4,  "📊"),
    "industrial production":   (4,  "📊"),
    "pcе":                     (5,  "📊"),
    "pce":                     (5,  "📊"),
    "core inflation":          (5,  "📊"),
    "producer price":          (4,  "📊"),
    "durable goods":           (4,  "📊"),
    "fed minutes":             (5,  "🏦"),
    "beige book":              (4,  "🏦"),
}

# ── Scoring ───────────────────────────────────────────────────────────────────

def score_article(title: str, summary: str = "") -> tuple[int, str]:
    """
    Retourne (score, emoji) pour un article.
    Score additif : meilleur keyword + bonus pour les keywords supplémentaires.
    Title match = score plein ; summary match = 60% du score.
    Score cap à 10.
    """
    title_low   = title.lower()
    summary_low = summary.lower()

    matches: list[tuple[int, str]] = []

    for kw, (score, emoji) in KEYWORD_SCORES.items():
        if kw in title_low:
            matches.append((score, emoji))
        elif kw in summary_low:
            matches.append((int(score * 0.6), emoji))

    if not matches:
        return 0, "📰"

    matches.sort(key=lambda x: -x[0])
    best_score, best_emoji = matches[0]

    # Bonus additif pour les matches supplémentaires (chaque bonus cap à 2 pts)
    bonus = sum(min(s, 2) for s, _ in matches[1:5])
    return min(best_score + bonus, 10), best_emoji


def is_market_moving(title: str, summary: str = "") -> bool:
    score, _ = score_article(title, summary)
    return score >= SEND_THRESHOLD


def get_impact_label(score: int) -> str:
    if score >= 9:
        return "CRITICAL"
    if score >= 7:
        return "HIGH"
    if score >= 5:
        return "MEDIUM-HIGH"
    return "LOW"


# ── Seen persistence ──────────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()).get("ids", []))
        except Exception:
            pass
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps({"ids": list(seen)[-MAX_SEEN:]}))


def article_uid(url: str, title: str) -> str:
    key = url or title[:80]
    return hashlib.md5(key.encode()).hexdigest()


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class MarketItem:
    title:     str
    source:    str
    url:       str
    published: Optional[datetime]
    score:     int   = 0
    emoji:     str   = "📰"
    summary:   str   = ""

    def uid(self) -> str:
        return article_uid(self.url, self.title)

    def time_str(self) -> str:
        if not self.published:
            return "--:--"
        return self.published.strftime("%H:%M")


# ── Fetch + filtre ────────────────────────────────────────────────────────────

# Feeds rapides — priorité vitesse (headline disponible en ~30s après publication)
MARKET_FEEDS: dict[str, str] = {
    "ForexLive":    "https://www.forexlive.com/feed/news",
    "Reuters":      "https://feeds.reuters.com/reuters/businessNews",
    "CNBC":         "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "MarketWatch":  "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
    "AP Business":  "https://feeds.apnews.com/rss/apf-business",
    "FXStreet":     "https://www.fxstreet.com/rss/news",
    "Investing.com":"https://www.investing.com/rss/news.rss",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 6   # agressif pour la vitesse


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _fetch_feed(source: str, url: str) -> list[MarketItem]:
    import requests
    import feedparser
    from datetime import timedelta

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        log.debug("Market feed [%s]: %s", source, exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    items  = []

    for entry in feed.entries[:20]:
        title   = re.sub(r"<[^>]+>", "", getattr(entry, "title", "")).strip()
        summary = re.sub(r"<[^>]+>", "", getattr(entry, "summary", "")).strip()
        link    = getattr(entry, "link", "").strip()
        pub     = _parse_date(entry)

        if not title:
            continue
        # Article sans date ou trop vieux → ignoré
        if not pub or pub < cutoff:
            continue

        score, emoji = score_article(title, summary)
        if score < SEND_THRESHOLD:
            continue

        items.append(MarketItem(
            title=title, source=source, url=link,
            published=pub, score=score, emoji=emoji,
            summary=summary[:150] if summary else "",
        ))

    return items


def fetch_market_news() -> list[MarketItem]:
    """Fetch + filtre depuis tous les feeds en parallèle."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_items: list[MarketItem] = []
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {
            pool.submit(_fetch_feed, src, url): src
            for src, url in MARKET_FEEDS.items()
        }
        for future in as_completed(futures):
            try:
                all_items.extend(future.result())
            except Exception:
                pass

    # Déduplique par titre (60 chars)
    seen_titles: set[str] = set()
    unique = []
    for item in all_items:
        key = item.title[:60].lower()
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(item)

    # Trie par score DESC puis date DESC
    unique.sort(key=lambda x: (
        -x.score,
        -(x.published.timestamp() if x.published else 0),
    ))
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


# ── Formatage alerte ──────────────────────────────────────────────────────────

def format_market_alert(item: MarketItem, tz: str = "UTC") -> str:
    from html import escape as _esc
    impact = get_impact_label(item.score)
    time_s = _fmt_time(item.published, tz)
    lines  = [
        f"{item.emoji} <b>{impact}</b>  <code>{time_s}</code>",
        f"<b>{_esc(item.title)}</b>",
        f"<i>{_esc(item.source)}</i>",
    ]
    if item.url:
        lines.append(f'<a href="{item.url}">🔗 Lire</a>  |  /deep /price')
    return "\n".join(lines)
