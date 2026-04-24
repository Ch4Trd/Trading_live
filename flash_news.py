"""
flash_news.py – Flash news financières classées par impact marché.
Sources RSS gratuites (ForexLive, FXStreet, Investing.com, Reuters, CNBC).
Scoring d'impact via Gemini (HIGH / MEDIUM / LOW).
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import feedparser
import requests

from ai_analyst import score_flash_impact

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 8

# ── Sources spécialisées flash / macro ────────────────────────────────────────
FLASH_FEEDS: dict[str, str] = {
    "ForexLive":    "https://www.forexlive.com/feed/news",
    "FXStreet":     "https://www.fxstreet.com/rss/news",
    "Reuters Mkts": "https://feeds.reuters.com/reuters/businessNews",
    "CNBC Markets": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "MarketWatch":  "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
    "Investing.com":"https://www.investing.com/rss/news.rss",
}

IMPACT_EMOJI = {
    "HIGH":   "🔴",
    "MEDIUM": "🟡",
    "LOW":    "⚪",
}

IMPACT_LABEL = {
    "HIGH":   "HIGH IMPACT",
    "MEDIUM": "MEDIUM IMPACT",
    "LOW":    "LOW IMPACT",
}


@dataclass
class FlashItem:
    title:     str
    source:    str
    url:       str
    published: Optional[datetime]
    impact:    str = "LOW"   # HIGH / MEDIUM / LOW

    def time_str(self) -> str:
        if not self.published:
            return "--:--"
        return self.published.strftime("%H:%M")

    def age_minutes(self) -> int:
        if not self.published:
            return 9999
        pub = self.published
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - pub
        return int(delta.total_seconds() / 60)


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _fetch_feed(source: str, url: str, max_age_hours: int) -> list[FlashItem]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        log.warning("Flash feed error [%s]: %s", source, exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    items  = []

    for entry in feed.entries[:15]:
        title = getattr(entry, "title", "").strip()
        link  = getattr(entry, "link",  "").strip()
        if not title or not link:
            continue
        title = re.sub(r"<[^>]+>", "", title).strip()
        pub   = _parse_date(entry)
        if pub and pub < cutoff:
            continue
        items.append(FlashItem(title=title, source=source, url=link, published=pub))

    return items


def fetch_flash_news(max_age_hours: int = 3) -> list[FlashItem]:
    """Récupère les flash news des dernières `max_age_hours` heures."""
    all_items: list[FlashItem] = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_fetch_feed, src, url, max_age_hours): src
            for src, url in FLASH_FEEDS.items()
        }
        for future in as_completed(futures):
            all_items.extend(future.result())

    # Déduplique par titre similaire
    seen: set[str] = set()
    unique = []
    for item in all_items:
        key = item.title[:60].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # Trie par date (plus récent en premier)
    unique.sort(
        key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    return unique[:40]


def score_and_sort(items: list[FlashItem]) -> list[FlashItem]:
    """Score l'impact via IA, avec fallback keyword si l'IA échoue."""
    if not items:
        return []

    headlines = [item.title for item in items]
    scores    = score_flash_impact(headlines)

    # Fallback keyword si l'IA n'a retourné que des LOW (quota/panne)
    ai_useful = any(s != "LOW" for s in scores)
    if not ai_useful:
        from market_filter import score_article
        for item in items:
            kw_score, _ = score_article(item.title)
            if kw_score >= 8:
                item.impact = "HIGH"
            elif kw_score >= 5:
                item.impact = "MEDIUM"
            else:
                item.impact = "LOW"
    else:
        for item, score in zip(items, scores):
            item.impact = score

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda x: (order[x.impact], x.age_minutes()))
    return items


# ── Formatage Telegram ────────────────────────────────────────────────────────

def format_flash_message(items: list[FlashItem], max_age_hours: int = 3) -> list[str]:
    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    total   = len(items)

    lines = [
        "⚡ <b>FLASH NEWS — tradingLIVE</b>",
        f"🕒 <i>{now_str} — {total} flash ({max_age_hours}h)</i>",
        "═" * 30,
        "",
    ]

    grouped: dict[str, list[FlashItem]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for item in items:
        grouped[item.impact].append(item)

    for level in ("HIGH", "MEDIUM", "LOW"):
        group = grouped[level]
        if not group:
            continue
        emoji = IMPACT_EMOJI[level]
        label = IMPACT_LABEL[level]
        lines.append(f"{emoji} <b>{label}</b>")
        lines.append("─" * 26)
        for item in group:
            lines.append(
                f"[{item.time_str()}] <a href=\"{item.url}\">{item.title}</a>"
                f"  <code>{item.source}</code>"
            )
        lines.append("")

    if not any(grouped.values()):
        lines.append("<i>Aucune flash news récente trouvée.</i>")

    lines.append("─" * 30)
    lines.append("⚡ <b>tradingLIVE</b> | /deep | /price | /week")

    # Split si trop long pour Telegram (4096 chars max)
    full_text = "\n".join(lines)
    if len(full_text) <= 4000:
        return [full_text]

    parts   = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > 3900:
            parts.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts
