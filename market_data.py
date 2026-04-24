"""
market_data.py – Prix temps réel + price action via yfinance.
Trend basé sur EMA20 en H4 et H1 (pas de SMA daily).
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import ASSETS, ASSET_TYPE

log = logging.getLogger(__name__)


def _calc_rsi(prices: pd.Series, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    delta = prices.diff().dropna()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    val   = rsi.iloc[-1]
    return round(float(val), 1) if not np.isnan(val) else 50.0


def _calc_ema(prices: pd.Series, period: int) -> pd.Series:
    return prices.ewm(span=period, adjust=False).mean()


def _trend_from_tf(symbol: str, interval: str, ema_period: int = 20) -> str:
    """Retourne 'bullish' ou 'bearish' basé sur EMA{ema_period} sur l'intervalle donné."""
    try:
        period = "30d" if interval == "4h" else "7d"
        hist   = yf.Ticker(symbol).history(period=period, interval=interval)
        if hist.empty or len(hist) < ema_period + 2:
            return "neutral"
        closes = hist["Close"].dropna()
        ema    = _calc_ema(closes, ema_period)
        price  = float(closes.iloc[-1])
        ema_now  = float(ema.iloc[-1])
        ema_prev = float(ema.iloc[-5]) if len(ema) >= 5 else float(ema.iloc[0])
        if price > ema_now and ema_now >= ema_prev:
            return "bullish"
        if price < ema_now and ema_now <= ema_prev:
            return "bearish"
        # Prix au-dessus de l'EMA mais EMA qui tourne (ou inverse) = neutre
        return "bullish" if price > ema_now else "bearish"
    except Exception as exc:
        log.debug("trend_from_tf error [%s %s]: %s", symbol, interval, exc)
        return "neutral"


def _fetch_single(name: str, symbol: str) -> dict:
    try:
        hist = yf.Ticker(symbol).history(period="35d", interval="1d")
        if hist.empty:
            return {"name": name, "error": True}

        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return {"name": name, "error": True}

        price = float(closes.iloc[-1])
        p1    = float(closes.iloc[-2])
        p7    = float(closes.iloc[-8]) if len(closes) >= 8 else float(closes.iloc[0])
        p30   = float(closes.iloc[0])

        volume = None
        if "Volume" in hist.columns:
            vol_series = hist["Volume"].dropna()
            if not vol_series.empty:
                volume = int(vol_series.iloc[-1])

        # Trends H4 et H1 en parallèle
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_h4 = pool.submit(_trend_from_tf, symbol, "4h")
            f_h1 = pool.submit(_trend_from_tf, symbol, "1h")
            trend_h4 = f_h4.result()
            trend_h1 = f_h1.result()

        return {
            "name":       name,
            "symbol":     symbol,
            "price":      price,
            "change_1d":  ((price - p1)  / p1)  * 100,
            "change_7d":  ((price - p7)  / p7)  * 100,
            "change_30d": ((price - p30) / p30) * 100,
            "rsi":        _calc_rsi(closes),
            "trend":      trend_h4,          # compatibilité avec le reste du code
            "trend_h4":   trend_h4,
            "trend_h1":   trend_h1,
            "support":    float(closes.tail(30).min()),
            "resistance": float(closes.tail(30).max()),
            "volume":     volume,
            "closes":     closes,
            "error":      False,
        }
    except Exception as exc:
        log.warning("market_data error [%s]: %s", name, exc)
        return {"name": name, "error": True}


def fetch_all_assets() -> dict:
    results = {}
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(_fetch_single, n, s): n for n, s in ASSETS.items()}
        for f in as_completed(futures):
            d = f.result()
            results[d["name"]] = d
    return results


def get_history_df(days: int = 30) -> pd.DataFrame:
    frames = {}
    for name, symbol in ASSETS.items():
        try:
            hist = yf.Ticker(symbol).history(period=f"{days + 5}d", interval="1d")
            if not hist.empty:
                frames[name] = hist["Close"].dropna()
        except Exception as exc:
            log.warning("history error [%s]: %s", name, exc)
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).tail(days)


def format_price(val: float, name: str) -> str:
    t = ASSET_TYPE.get(name, "stock")
    if t == "forex":
        return f"{val:.4f}" if val < 100 else f"{val:.2f}"
    if t == "commodity":
        return f"{val:,.2f}"
    return f"{val:,.2f}"
