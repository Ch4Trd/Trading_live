"""
news_fetcher.py – Fetch and parse RSS feeds for US news.
No API key required. Pure feedparser + requests.
"""

import feedparser
import requests
import logging
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import US_FEEDS, MAX_ARTICLES_PER_SOURCE, REQUEST_TIMEOUT

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


@dataclass
class Article:
    title:     str
    source:    str
    url:       str
    summary:   str = ""
    published: Optional[datetime] = None
    region:    str = "US"

    def age_str(self) -> str:
        if not self.published:
            return ""
        now  = datetime.now(timezone.utc)
        diff = now - (self.published.replace(tzinfo=timezone.utc)
                      if self.published.tzinfo is None else self.published)
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _fetch_feed(source_name: str, url: str) -> list[Article]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        log.warning("Feed error [%s]: %s", source_name, exc)
        return []

    articles = []
    for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
        title = getattr(entry, "title", "").strip()
        link  = getattr(entry, "link",  "").strip()
        if not title or not link:
            continue
        summary = re.sub(r"<[^>]+>", "", getattr(entry, "summary", "")).strip()
        summary = summary[:200] + "…" if len(summary) > 200 else summary

        articles.append(Article(
            title=title, source=source_name, url=link,
            summary=summary, published=_parse_date(entry), region="US",
        ))
    return articles


def fetch_us() -> list[Article]:
    all_articles: list[Article] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_feed, name, url): name for name, url in US_FEEDS.items()}
        for future in as_completed(futures):
            all_articles.extend(future.result())
    all_articles.sort(
        key=lambda a: a.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return all_articles
