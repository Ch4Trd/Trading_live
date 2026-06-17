import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
NVIDIA_API_KEY    = os.getenv("NVIDIA_API_KEY", "")

US_FEEDS = {
    "Reuters":       "https://feeds.reuters.com/reuters/businessNews",
    "AP News":       "https://feeds.apnews.com/rss/apf-business",
    "CNBC":          "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "MarketWatch":   "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "Seeking Alpha": "https://seekingalpha.com/market_currents.xml",
    "Investopedia":  "https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headline",
}

ASSETS = {
    "NAS100":  "^NDX",
    "US500":   "^GSPC",
    "XAU/USD": "GC=F",
    "NVDA":    "NVDA",
}

ASSET_EMOJI = {
    "NAS100":  "📈",
    "US500":   "📊",
    "XAU/USD": "🥇",
    "NVDA":    "🖥️",
}

ASSET_TYPE = {
    "NAS100":  "index",
    "US500":   "index",
    "XAU/USD": "commodity",
    "NVDA":    "stock",
}

MAX_ARTICLES_PER_SOURCE = 3
MAX_ARTICLES_REPORT     = 8
MAX_ALERT_ARTICLES      = 5
ALERT_INTERVAL_HOURS    = 4
REQUEST_TIMEOUT         = 10
# Endpoint JSON (le XML est rate-limité agressivement par Cloudflare sur IP datacenter)
FF_WEEK_URL             = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_MONTH_URL            = "https://nfs.faireconomy.media/ff_calendar_thismonth.json"
# Anciens endpoints XML conservés en fallback
FF_WEEK_URL_XML         = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
FF_MONTH_URL_XML        = "https://nfs.faireconomy.media/ff_calendar_thismonth.xml"
