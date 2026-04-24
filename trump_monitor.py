"""
trump_monitor.py – Surveillance des déclarations DIRECTES de Trump.
Sources (ordre de priorité) :
  1. Truth Social via Playwright stealth (nécessite navigateur sur IP résidentielle)
  2. Monitoring news RSS qui citent un post Truth Social de Trump
  3. Nitter RSS (@realDonaldTrump sur X/Twitter)
"""

import asyncio
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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 15
SEEN_FILE       = Path(__file__).parent / "trump_seen.json"
MAX_AGE_HOURS   = 3

# ── Sources Truth Social ──────────────────────────────────────────────────────
TRUTH_SOCIAL_ACCOUNT_ID = "107780257626128497"
TRUTH_SOCIAL_RSS        = "https://truthsocial.com/@realDonaldTrump.rss"
TRUTH_SOCIAL_API        = (
    f"https://truthsocial.com/api/v1/accounts/{TRUTH_SOCIAL_ACCOUNT_ID}/statuses"
)

# ── Sources Nitter (Twitter/X) ────────────────────────────────────────────────
NITTER_INSTANCES = [
    "https://nitter.privacyredirect.com",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.net",
    "https://nitter.cz",
    "https://nitter.rawbit.ninja",
]
TRUMP_TWITTER_HANDLE = "realDonaldTrump"

# ── Flux news qui couvrent rapidement les posts Truth Social de Trump ─────────
# Ces sources publient les posts Truth Social dans la minute qui suit.
NEWS_FEEDS_TRUMP: list[str] = [
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.foxnews.com/foxnews/politics",
    "https://feeds.foxnews.com/foxnews/latest",
    "https://news.yahoo.com/rss/",
    "https://feeds.bloomberg.com/politics/news.rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
    "https://feeds.washingtonpost.com/rss/politics",
    "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
]

# Patterns pour détecter un post Truth Social CITÉ dans un article de news
_TS_PATTERNS = [
    re.compile(r"Truth Social", re.IGNORECASE),
    re.compile(r"trump\s+(?:posted|wrote|said|declared|claimed|posted|shared)\s+on\s+(?:his\s+)?(?:social\s+media|truth)", re.IGNORECASE),
]
# Patterns pour extraire le contenu cité (guillemets après mention Truth Social)
_QUOTE_PATTERNS = [
    re.compile(r'[""]([\s\S]{15,400}?)["""]'),
    re.compile(r'(?:wrote|posted|said|stated)[:\s]+"([^"]{15,400})"'),
]

# ── Source labels affichés dans l'alerte ─────────────────────────────────────
SOURCE_LABELS = {
    "truth_social":      "📱 Truth Social",
    "truth_social_news": "📱 Truth Social (via news)",
    "twitter":           "🐦 Twitter / X",
}


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class TrumpItem:
    title:     str
    source:    str
    url:       str
    published: Optional[datetime]
    is_tweet:  bool = True

    def uid(self) -> str:
        key = self.url or self.title[:80]
        return hashlib.md5(key.encode()).hexdigest()

    def age_minutes(self) -> int:
        if not self.published:
            return 0
        pub = self.published
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - pub).total_seconds() / 60)


# ── Seen IDs persistence ──────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()).get("ids", []))
        except Exception:
            pass
    return set()


def save_seen(seen: set) -> None:
    ids = list(seen)[-500:]
    SEEN_FILE.write_text(json.dumps({"ids": ids}))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&amp;",  "&",  text)
    text = re.sub(r"&lt;",   "<",  text)
    text = re.sub(r"&gt;",   ">",  text)
    text = re.sub(r"&quot;", '"',  text)
    text = re.sub(r"&#39;",  "'",  text)
    text = re.sub(r"&nbsp;", " ",  text)
    return text.strip()


def _clean_post(text: str, max_len: int = 500) -> str:
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


# ── Fetch Truth Social — Playwright stealth ───────────────────────────────────

def _fetch_truth_playwright() -> list["TrumpItem"]:
    """
    Tente d'accéder à Truth Social via Playwright stealth.
    Fonctionne uniquement sur IP résidentielle — échoue rapidement sur IP datacenter.
    """
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    async def _run() -> list[TrumpItem]:
        items: list[TrumpItem] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            await Stealth().apply_stealth_async(context)
            page = await context.new_page()

            # Test rapide RSS (timeout court pour échouer vite sur IP datacenter)
            try:
                resp = await page.goto(TRUTH_SOCIAL_RSS, wait_until="commit", timeout=8000)
                # Si Cloudflare bloque immédiatement → abandon
                if resp.status in (403, 503):
                    log.debug("Truth Social Playwright: bloqué par Cloudflare (%d)", resp.status)
                    await browser.close()
                    return []
                await asyncio.sleep(4)
                raw_html = await page.content()
                if "<item>" in raw_html or "<entry>" in raw_html:
                    feed = feedparser.parse(raw_html)
                    for entry in feed.entries[:20]:
                        title   = _strip_html(getattr(entry, "title",   "")).strip()
                        summary = _strip_html(getattr(entry, "summary", "")).strip()
                        content = summary if len(summary) > len(title) else title
                        content = _clean_post(content)
                        link = getattr(entry, "link", "").strip()
                        pub  = _parse_date(entry)
                        if content and len(content) >= 5 and (not pub or pub >= cutoff):
                            items.append(TrumpItem(
                                title=content, source=SOURCE_LABELS["truth_social"],
                                url=link, published=pub, is_tweet=True,
                            ))
                    log.info("Truth Social Playwright RSS: %d posts", len(items))
            except Exception as exc:
                log.debug("Playwright RSS: %s", exc)

            await browser.close()
        return items

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.debug("Playwright sync wrapper: %s", exc)
        return []


# ── Fetch Truth Social — via news RSS (toujours disponible) ──────────────────

def _parse_news_feed(feed_url: str, cutoff: datetime) -> list["TrumpItem"]:
    """Parse un flux RSS et retourne les items mentionnant un post Truth Social de Trump."""
    items: list[TrumpItem] = []
    try:
        resp = requests.get(feed_url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return items
        feed = feedparser.parse(resp.content)

        for entry in feed.entries[:30]:
            title   = _strip_html(getattr(entry, "title",   "")).strip()
            summary = _strip_html(getattr(entry, "summary", "")).strip()
            full    = f"{title} {summary}"
            link    = getattr(entry, "link", "").strip()
            pub     = _parse_date(entry)

            if pub and pub < cutoff:
                continue
            if not any(p.search(full) for p in _TS_PATTERNS):
                continue
            if "trump" not in full.lower():
                continue

            # Extraire la citation si possible
            quoted = ""
            for qp in _QUOTE_PATTERNS:
                m = qp.search(full)
                if m:
                    quoted = m.group(1).strip()
                    break

            content = f'"{quoted}"' if quoted and len(quoted) > 15 else title
            content = _clean_post(content)
            if not content or len(content) < 5:
                continue

            items.append(TrumpItem(
                title=content,
                source=SOURCE_LABELS["truth_social_news"],
                url=link, published=pub, is_tweet=True,
            ))
    except Exception as exc:
        log.debug("News feed error [%s]: %s", feed_url, exc)
    return items


def _fetch_truth_social_news() -> list["TrumpItem"]:
    """
    Surveille les flux RSS de news en parallèle pour détecter les citations
    de posts Trump sur Truth Social (publiées dans la minute qui suit).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    all_items: list[TrumpItem] = []
    seen_content: set[str] = set()

    with ThreadPoolExecutor(max_workers=len(NEWS_FEEDS_TRUMP)) as pool:
        futures = {pool.submit(_parse_news_feed, url, cutoff): url for url in NEWS_FEEDS_TRUMP}
        for future in as_completed(futures):
            try:
                all_items.extend(future.result())
            except Exception:
                pass

    # Déduplique par contenu
    unique: list[TrumpItem] = []
    for item in all_items:
        key = item.title[:60].lower()
        if key not in seen_content:
            seen_content.add(key)
            unique.append(item)

    if unique:
        log.info("Truth Social (via news): %d mentions détectées", len(unique))
    return unique


# ── Fetch Nitter (Twitter/X) ──────────────────────────────────────────────────

def _fetch_nitter() -> list["TrumpItem"]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    for base in NITTER_INSTANCES:
        url = f"{base}/{TRUMP_TWITTER_HANDLE}/rss"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                continue

            # Vérifier que c'est bien un vrai feed RSS (pas une page de bot check)
            if not any(getattr(e, "title", "") for e in feed.entries[:3]):
                continue

            items = []
            for entry in feed.entries[:20]:
                title   = _strip_html(getattr(entry, "title",   "")).strip()
                summary = _strip_html(getattr(entry, "summary", "")).strip()
                content = summary if len(summary) > len(title) else title
                content = _clean_post(content)
                link    = getattr(entry, "link", "").strip()
                pub     = _parse_date(entry)

                if title.startswith("RT @") or title.startswith("R to @"):
                    continue
                if not content or len(content) < 5:
                    continue
                if pub and pub < cutoff:
                    continue

                items.append(TrumpItem(
                    title=content, source=SOURCE_LABELS["twitter"],
                    url=link, published=pub, is_tweet=True,
                ))

            if items:
                log.debug("Nitter OK via %s — %d tweets", base, len(items))
                return items

        except Exception as exc:
            log.debug("Nitter error [%s]: %s", base, exc)

    return []


# ── Main fetch ────────────────────────────────────────────────────────────────

def fetch_trump_updates() -> list["TrumpItem"]:
    """
    Récupère les posts DIRECTS de Trump (Truth Social + Twitter).
    Ordre de priorité :
      1. Playwright stealth → Truth Social direct
      2. News RSS → citations de posts Truth Social
      3. Nitter → Twitter/X
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_items: list[TrumpItem] = []

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_fetch_truth_playwright):    "playwright",
            pool.submit(_fetch_truth_social_news):   "news",
            pool.submit(_fetch_nitter):              "nitter",
        }
        for future in as_completed(futures):
            src = futures[future]
            try:
                result = future.result()
                all_items.extend(result)
            except Exception as exc:
                log.debug("Trump fetch [%s] error: %s", src, exc)

    # Déduplique par contenu (60 chars)
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


# ── Helpers heure locale ─────────────────────────────────────────────────────

def _fmt_time(dt: Optional[datetime], tz_str: str = "UTC") -> str:
    if not dt:
        return "--:--"
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo(tz_str)).strftime("%H:%M %Z")
    except Exception:
        return dt.strftime("%H:%M UTC")


# ── Format notification ───────────────────────────────────────────────────────

def format_trump_alert(item: "TrumpItem", tz: str = "UTC") -> str:
    time_s = _fmt_time(item.published, tz)

    lines = [
        f"🚨 <b>TRUMP — {_esc(item.source)}</b>",
        f"🕒 <code>{time_s}</code>",
        "─" * 30,
        f"<i>{_esc(item.title)}</i>",
        "─" * 30,
    ]
    if item.url:
        lines.append(f'🔗 <a href="{item.url}">Voir le post original</a>  |  /deep /price')
    else:
        lines.append("⚡ /deep  |  /price")
    return "\n".join(lines)
