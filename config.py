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
    "EUR/USD": "EURUSD=X",
    "USD/CAD": "USDCAD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "XAU/USD": "GC=F",
    "NAS100":  "^NDX",
    "US500":   "^GSPC",
    "NVDA":    "NVDA",
}

ASSET_EMOJI = {
    "EUR/USD": "🇪🇺",
    "USD/CAD": "🇨🇦",
    "GBP/USD": "🇬🇧",
    "USD/JPY": "🇯🇵",
    "XAU/USD": "🥇",
    "NAS100":  "📈",
    "US500":   "📊",
    "NVDA":    "🖥️",
}

ASSET_TYPE = {
    "EUR/USD": "forex",
    "USD/CAD": "forex",
    "GBP/USD": "forex",
    "USD/JPY": "forex",
    "XAU/USD": "commodity",
    "NAS100":  "index",
    "US500":   "index",
    "NVDA":    "stock",
}

MAX_ARTICLES_PER_SOURCE = 3
MAX_ARTICLES_REPORT     = 8
MAX_ALERT_ARTICLES      = 5
ALERT_INTERVAL_HOURS    = 4
REQUEST_TIMEOUT         = 10
FF_WEEK_URL             = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
FF_MONTH_URL            = "https://nfs.faireconomy.media/ff_calendar_thismonth.xml"
