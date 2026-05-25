"""
analyze_command.py
Handler /analyze <asset> — rapport de confluence technique + fondamentale premium.

Contenu du rapport :
  1. Structure de marché (Trend H4/H1, phase, BOS/CHoCH)
  2. Niveaux de liquidité BSL/SSL (swing highs/lows clés)
  3. Fair Value Gaps H4 et H1 (zones d'imbalance non comblées)
  4. Sentiment retail synthétique (proxy RSI + momentum)
  5. Contexte fondamental (dernières releases macro stockées)
  6. Scénario de confluence : biais + plan de trading théorique
"""

import asyncio
import logging
from datetime import datetime, timezone
from html import escape as _esc
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from config import ASSETS, ASSET_TYPE
from market_data import format_price
from technical_analysis import analyze_structure, detect_divergence, calc_macd
from subscription import subscription_manager
from macro_engine import macro_engine

log = logging.getLogger(__name__)

# ── Mapping aliases utilisateur → nom interne ──────────────────────────────────

ASSET_ALIASES: dict[str, str] = {
    # Indices US
    "NQ":      "NAS100",  "NAS":     "NAS100",  "NDX":    "NAS100",
    "NAS100":  "NAS100",  "NASDAQ":  "NAS100",  "NQ100":  "NAS100",
    "ES":      "US500",   "SPX":     "US500",   "SP500":  "US500",
    "US500":   "US500",   "S&P":     "US500",   "SPY":    "US500",
    # Forex
    "EURUSD":  "EUR/USD", "EU":      "EUR/USD", "EUR":    "EUR/USD",
    "GBPUSD":  "GBP/USD", "GU":      "GBP/USD", "CABLE":  "GBP/USD", "GBP":    "GBP/USD",
    "USDJPY":  "USD/JPY", "UJ":      "USD/JPY", "JPY":    "USD/JPY",
    "USDCAD":  "USD/CAD", "UC":      "USD/CAD", "CAD":    "USD/CAD",
    "EUR/USD": "EUR/USD", "GBP/USD": "GBP/USD",
    "USD/JPY": "USD/JPY", "USD/CAD": "USD/CAD",
    # Commodités
    "GOLD":    "XAU/USD", "GC":      "XAU/USD", "XAUUSD": "XAU/USD",
    "XAU":     "XAU/USD", "XAU/USD": "XAU/USD", "OR":      "XAU/USD",
    # Stocks
    "NVDA":    "NVDA",    "NVIDIA":  "NVDA",
}

# Correspondance nom interne → ticker yfinance
_YF: dict[str, str] = {
    "EUR/USD": "EURUSD=X",
    "USD/CAD": "USDCAD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "XAU/USD": "GC=F",
    "NAS100":  "^NDX",
    "US500":   "^GSPC",
    "NVDA":    "NVDA",
}

# Noms affichage
_DISPLAY: dict[str, str] = {
    "NAS100":  "NAS100 (NQ)",
    "US500":   "US500 (ES)",
    "EUR/USD": "EUR/USD",
    "GBP/USD": "GBP/USD",
    "USD/JPY": "USD/JPY",
    "USD/CAD": "USD/CAD",
    "XAU/USD": "XAU/USD (Gold)",
    "NVDA":    "NVDA",
}


# ── Fetch OHLCV ───────────────────────────────────────────────────────────────

def _fetch_ohlcv(symbol: str, interval: str) -> Optional[pd.DataFrame]:
    """Fetch OHLCV via yfinance. Retourne None si données insuffisantes."""
    period_map = {"4h": "60d", "1h": "30d", "1d": "180d"}
    period = period_map.get(interval, "30d")
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df.empty or len(df) < 10:
            return None
        return df.dropna()
    except Exception as exc:
        log.warning("fetch_ohlcv [%s %s]: %s", symbol, interval, exc)
        return None


# ── RSI float ────────────────────────────────────────────────────────────────

def _calc_rsi(closes: pd.Series, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff().dropna()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = (100 - (100 / (1 + rs))).iloc[-1]
    return round(float(rsi), 1) if not np.isnan(rsi) else 50.0


# ── Trend depuis DataFrame OHLCV ─────────────────────────────────────────────

def _trend_from_df(df: Optional[pd.DataFrame]) -> str:
    """Détermine le trend (bullish/bearish/neutral) via EMA20 sur le df."""
    if df is None or len(df) < 22:
        return "neutral"
    closes = df["Close"]
    ema    = closes.ewm(span=20, adjust=False).mean()
    price  = float(closes.iloc[-1])
    e_now  = float(ema.iloc[-1])
    e_prev = float(ema.iloc[-5]) if len(ema) >= 5 else e_now
    if price > e_now and e_now >= e_prev:
        return "bullish"
    if price < e_now and e_now <= e_prev:
        return "bearish"
    return "bullish" if price > e_now else "bearish"


# ── Fair Value Gap detection ───────────────────────────────────────────────────

def _detect_fvg(df: pd.DataFrame, lookback: int = 40) -> list[dict]:
    """
    Bullish FVG : df[i-2].High < df[i].Low   → gap imbalance haussier
    Bearish FVG : df[i-2].Low  > df[i].High  → gap imbalance baissier

    Filtre : taille minimale > 0.02% du prix pour éviter les micro-gaps.
    Retourne les 3 plus récents non-comblés.
    """
    df = df.tail(lookback).reset_index(drop=True)
    if len(df) < 3:
        return []

    fvgs = []
    current_price = float(df["Close"].iloc[-1])
    min_gap       = current_price * 0.0002

    for i in range(2, len(df)):
        h2 = float(df["High"].iloc[i - 2])
        l2 = float(df["Low"].iloc[i - 2])
        h0 = float(df["High"].iloc[i])
        l0 = float(df["Low"].iloc[i])

        if h2 < l0 and (l0 - h2) >= min_gap:  # Bullish FVG
            fvgs.append({
                "type":   "bullish",
                "top":    l0,    # bas de la bougie actuelle
                "bottom": h2,    # haut de la bougie i-2
                "mid":    (l0 + h2) / 2,
                "bar":    i,
            })
        elif l2 > h0 and (l2 - h0) >= min_gap:  # Bearish FVG
            fvgs.append({
                "type":   "bearish",
                "top":    l2,    # bas de la bougie i-2
                "bottom": h0,    # haut de la bougie actuelle
                "mid":    (l2 + h0) / 2,
                "bar":    i,
            })

    # Garder les 3 plus récents
    return fvgs[-3:]


# ── BSL / SSL (Buy-Side / Sell-Side Liquidity) ────────────────────────────────

def _detect_liquidity(df: pd.DataFrame, order: int = 3) -> dict:
    """
    BSL = swing highs récents = où les stops des shorts sont placés
    SSL = swing lows récents  = où les stops des longs sont placés

    Le marché "sweeps" ces niveaux avant de se retourner.
    """
    df   = df.tail(80).reset_index(drop=True)
    highs = df["High"].values
    lows  = df["Low"].values
    n     = len(df)

    bsl, ssl = [], []

    for i in range(order, n - order):
        h_win = highs[i - order: i + order + 1]
        l_win = lows[i - order:  i + order + 1]
        if highs[i] >= max(h_win):
            bsl.append(float(highs[i]))
        if lows[i] <= min(l_win):
            ssl.append(float(lows[i]))

    current_price = float(df["Close"].iloc[-1])
    threshold     = current_price * 0.001  # dédoublonner niveaux à < 0.1% d'écart

    def _dedupe(levels: list) -> list:
        result = []
        for lvl in levels:
            if not result or abs(lvl - result[-1]) > threshold:
                result.append(lvl)
        return result

    bsl = _dedupe(sorted(set(bsl), reverse=True))[:5]
    ssl = _dedupe(sorted(set(ssl)))[:5]

    return {"bsl": bsl, "ssl": ssl, "price": current_price}


# ── Sentiment retail synthétique ──────────────────────────────────────────────

def _synthetic_sentiment(rsi: float, change_7d: float) -> dict:
    """
    Proxy : RSI élevé → retail massivement long (signal contrarian bearish).
    Ajustement par le momentum 7 jours.
    """
    # Base RSI
    if rsi >= 75:      long_pct = 80
    elif rsi >= 65:    long_pct = 68
    elif rsi >= 55:    long_pct = 55
    elif rsi >= 45:    long_pct = 47
    elif rsi >= 35:    long_pct = 36
    else:              long_pct = 24

    # Ajustement momentum
    if change_7d > 4:   long_pct = min(88, long_pct + 10)
    elif change_7d > 2: long_pct = min(85, long_pct + 5)
    elif change_7d < -4: long_pct = max(12, long_pct - 10)
    elif change_7d < -2: long_pct = max(15, long_pct - 5)

    short_pct = 100 - long_pct

    if long_pct >= 70:
        signal = "⚠️ Majorité retail LONG → risque de squeeze baissier (contrarian)"
        bias   = "contrarian_short"
    elif short_pct >= 70:
        signal = "⚠️ Majorité retail SHORT → risque de squeeze haussier (contrarian)"
        bias   = "contrarian_long"
    elif long_pct >= 58:
        signal = "🟡 Retail légèrement long — surveiller"
        bias   = "slight_long"
    elif short_pct >= 58:
        signal = "🟡 Retail légèrement short — surveiller"
        bias   = "slight_short"
    else:
        signal = "✅ Sentiment équilibré — pas de signal contrarian"
        bias   = "neutral"

    return {
        "long_pct":  long_pct,
        "short_pct": short_pct,
        "signal":    signal,
        "bias":      bias,
    }


# ── Contexte fondamental récent ───────────────────────────────────────────────

def _get_macro_context() -> list[dict]:
    """Retourne les 5 dernières releases macro depuis l'historique du MacroEngine."""
    return macro_engine.history.get_all_recent(n=5)


# ── Calcul du biais global ────────────────────────────────────────────────────

def _compute_bias(
    name:      str,
    trend_h4:  str,
    trend_h1:  str,
    struct,
    sentiment: dict,
    rsi:       float,
    macro_ctx: list,
) -> tuple[str, str, int]:
    """Retourne (bias_label, bias_emoji, score_0_to_10)."""
    long_pts  = 0
    short_pts = 0

    # Trends (max +4)
    if trend_h4 == "bullish":  long_pts  += 2
    elif trend_h4 == "bearish": short_pts += 2
    if trend_h1 == "bullish":  long_pts  += 1
    elif trend_h1 == "bearish": short_pts += 1

    # Structure H4 (max +2)
    if struct:
        if struct.phase == "Uptrend":    long_pts  += 1
        elif struct.phase == "Downtrend": short_pts += 1
        if "Bullish" in (struct.bos or ""): long_pts  += 1
        if "Bearish" in (struct.bos or ""): short_pts += 1

    # RSI (max +1)
    if 40 <= rsi <= 65 and trend_h4 == "bullish":   long_pts  += 1
    elif 35 <= rsi <= 60 and trend_h4 == "bearish":  short_pts += 1
    elif rsi >= 72: short_pts += 1  # surachat
    elif rsi <= 28: long_pts  += 1  # survente

    # Sentiment contrarian (max +1)
    if sentiment["bias"] == "contrarian_long":  long_pts  += 1
    if sentiment["bias"] == "contrarian_short": short_pts += 1

    # Macro context (max +1)
    if macro_ctx:
        hawk = sum(1 for e in macro_ctx[:3] if e.get("qualifier") == "hawkish")
        dove = sum(1 for e in macro_ctx[:3] if e.get("qualifier") == "dovish")
        asset_type = ASSET_TYPE.get(name, "index")
        if asset_type == "index":
            if dove >= 2:  long_pts  += 1
            elif hawk >= 2: short_pts += 1
        elif asset_type in ("forex", "commodity") and "USD" in name:
            if hawk >= 2: long_pts  += 1
            elif dove >= 2: short_pts += 1
        elif name == "XAU/USD":  # or inverse USD
            if dove >= 2:  long_pts  += 1
            elif hawk >= 2: short_pts += 1

    total = long_pts + short_pts
    if total == 0:
        return "NEUTRE", "➡️", 5

    if long_pts > short_pts:
        score = min(10, round(long_pts / (total) * 10))
        return "LONG", "📈", score
    elif short_pts > long_pts:
        score = min(10, round(short_pts / (total) * 10))
        return "SHORT", "📉", score
    else:
        return "NEUTRE", "➡️", 5


# ── Formatage du rapport ──────────────────────────────────────────────────────

def _format_report(
    name:         str,
    current_price: float,
    h4_df:        Optional[pd.DataFrame],
    h1_df:        Optional[pd.DataFrame],
    rsi:          float,
    change_7d:    float,
    trend_h4:     str,
    trend_h1:     str,
) -> str:
    fp      = lambda v: format_price(v, name)
    display = _DISPLAY.get(name, name)
    now_s   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"📊 <b>ANALYSE CONFLUENCE — {_esc(display)}</b>",
        f"🕒 <i>{now_s}</i>  |  <code>{fp(current_price)}</code>",
        "━" * 32,
    ]

    # ── 1. Structure technique ──────────────────────────────────────────────
    lines += ["", "📐 <b>STRUCTURE TECHNIQUE</b>", "─" * 28]

    t4e = "📈" if trend_h4 == "bullish" else ("📉" if trend_h4 == "bearish" else "➡️")
    t1e = "📈" if trend_h1 == "bullish" else ("📉" if trend_h1 == "bearish" else "➡️")
    lines.append(f"Tendance H4 : {t4e} <b>{trend_h4.upper()}</b>")
    lines.append(f"Tendance H1 : {t1e} <b>{trend_h1.upper()}</b>")

    struct = None
    if h4_df is not None and len(h4_df) >= 15:
        struct = analyze_structure(h4_df["Close"])
        phase_map = {
            "Uptrend":   "📈 Uptrend — HH + HL confirmés",
            "Downtrend": "📉 Downtrend — LH + LL confirmés",
            "Ranging":   "➡️ Ranging — structure latérale",
        }
        lines.append(f"Phase H4    : <b>{phase_map.get(struct.phase, struct.phase)}</b>")
        if struct.bos:
            b_e = "📈" if "Bullish" in struct.bos else "📉"
            lines.append(f"BOS         : {b_e} <b>{_esc(struct.bos)}</b>")
        if struct.choch:
            lines.append(f"CHoCH       : ⚠️ <b>{_esc(struct.choch)}</b> — retournement possible")

    rsi_label = "🔴 Surachat" if rsi > 70 else ("🟢 Survente" if rsi < 30 else "🟡 Zone neutre")
    lines.append(f"RSI (14)    : <code>{rsi:.1f}</code>  {rsi_label}")

    # ── 2. Niveaux de liquidité BSL / SSL ───────────────────────────────────
    lines += ["", "💧 <b>NIVEAUX DE LIQUIDITÉ (H4)</b>", "─" * 28]

    liq = None
    if h4_df is not None:
        liq   = _detect_liquidity(h4_df)
        price = liq["price"]

        bsl_above = sorted([l for l in liq["bsl"] if l > price])[:3]
        ssl_below = sorted([l for l in liq["ssl"] if l < price], reverse=True)[:3]

        if bsl_above:
            bsl_str = "  |  ".join(f"<code>{fp(l)}</code>" for l in bsl_above)
            lines.append(f"BSL ↑ (stops shorts) : {bsl_str}")
        else:
            lines.append("BSL ↑ : Aucun niveau au-dessus du prix")

        if ssl_below:
            ssl_str = "  |  ".join(f"<code>{fp(l)}</code>" for l in ssl_below)
            lines.append(f"SSL ↓ (stops longs)  : {ssl_str}")
        else:
            lines.append("SSL ↓ : Aucun niveau en dessous du prix")

        lines.append(f"<i>Le marché sweeps ces niveaux avant de se retourner</i>")
    else:
        lines.append("Données H4 indisponibles")

    # ── 3. Fair Value Gaps ──────────────────────────────────────────────────
    lines += ["", "🔲 <b>FAIR VALUE GAPS (FVG)</b>", "─" * 28]

    fvg_h4 = _detect_fvg(h4_df) if h4_df is not None else []
    fvg_h1 = _detect_fvg(h1_df) if h1_df is not None else []

    def _fvg_section(fvgs: list, tf: str) -> list:
        if not fvgs:
            return [f"{tf} : Aucun FVG récent détecté"]
        out = []
        for f in reversed(fvgs):
            emoji = "🟢" if f["type"] == "bullish" else "🔴"
            label = "Bullish" if f["type"] == "bullish" else "Bearish"
            out.append(
                f"{tf} — {emoji} <b>{label} FVG</b> : "
                f"<code>{fp(f['bottom'])}</code> → <code>{fp(f['top'])}</code>"
                f"  (mid: <code>{fp(f['mid'])}</code>)"
            )
        return out

    lines += _fvg_section(fvg_h4, "H4")
    lines += _fvg_section(fvg_h1, "H1")

    # ── 4. Sentiment retail (proxy) ─────────────────────────────────────────
    lines += ["", "👥 <b>SENTIMENT RETAIL</b>  <i>(proxy RSI + momentum)</i>", "─" * 28]

    sentiment = _synthetic_sentiment(rsi, change_7d)
    bar_l = "█" * (sentiment["long_pct"] // 10) + "░" * (10 - sentiment["long_pct"] // 10)
    lines.append(f"Long  : <b>{sentiment['long_pct']}%</b>  <code>{bar_l}</code>")
    lines.append(f"Short : <b>{sentiment['short_pct']}%</b>")
    lines.append(sentiment["signal"])

    # ── 5. Contexte fondamental ─────────────────────────────────────────────
    lines += ["", "🌍 <b>DÉVIATIONS MACRO RÉCENTES</b>", "─" * 28]

    macro_ctx = _get_macro_context()
    if macro_ctx:
        for entry in macro_ctx[:4]:
            label     = entry.get("_label", "?").upper()
            qualifier = entry.get("qualifier", "neutral")
            actual    = entry.get("actual")
            forecast  = entry.get("forecast")
            date_s    = entry.get("date", "")[:10]
            q_emoji   = "🦅" if qualifier == "hawkish" else ("🕊️" if qualifier == "dovish" else "➡️")
            actual_s  = f"{actual:.4g}" if isinstance(actual, float) else str(actual)
            fc_s      = f"{forecast:.4g}" if isinstance(forecast, float) else str(forecast or "N/A")
            lines.append(
                f"{q_emoji} <b>{_esc(label)}</b> ({date_s}) "
                f"Réel=<b>{_esc(actual_s)}</b>  Prévu={_esc(fc_s)} → <b>{qualifier.upper()}</b>"
            )
    else:
        lines.append("<i>Aucune release macro enregistrée (moteur actif depuis le dernier restart).</i>")
        lines.append("<i>Utilise /day pour voir le calendrier et /breaking on pour activer les alertes.</i>")

    # ── 6. Scénario de confluence ────────────────────────────────────────────
    bias, bias_emoji, score = _compute_bias(
        name, trend_h4, trend_h1, struct, sentiment, rsi, macro_ctx
    )
    score_bar = "█" * score + "░" * (10 - score)

    lines += [
        "",
        "━" * 32,
        "🎯 <b>SCÉNARIO DE CONFLUENCE DU JOUR</b>",
        "━" * 32,
        "",
        f"Biais  : {bias_emoji} <b>{bias}</b>",
        f"Score  : <b>{score}/10</b>  <code>{score_bar}</code>",
        "",
    ]

    # Plan de trading selon le biais
    if bias == "LONG" and liq and fvg_h4:
        bull_fvgs = [f for f in fvg_h4 if f["type"] == "bullish" and f["top"] < current_price]
        ssl_below = sorted([l for l in liq["ssl"] if l < current_price], reverse=True)
        bsl_above = sorted([l for l in liq["bsl"] if l > current_price])

        if bull_fvgs:
            best = max(bull_fvgs, key=lambda f: f["top"])
            lines.append(f"Setup  : Pullback vers FVG Bullish H4")
            lines.append(f"         Zone : <code>{fp(best['bottom'])}</code> – <code>{fp(best['top'])}</code>")
        elif ssl_below:
            lines.append(f"Setup  : Achat sur SSL H4 le plus proche")
            lines.append(f"         Zone : <code>{fp(ssl_below[0])}</code>")
        else:
            lines.append("Setup  : Achat sur pullback structure H1")

        if ssl_below:
            lines.append(f"Stop   : Sous SSL @ <code>{fp(ssl_below[0])}</code>")
        if bsl_above:
            lines.append(f"Target : BSL @ <code>{fp(bsl_above[0])}</code>")
            if ssl_below:
                sl = current_price - ssl_below[0]
                tp = bsl_above[0] - current_price
                if sl > 0 and tp > 0:
                    lines.append(f"R:R    : ~1:{tp/sl:.1f}")

        lines.append(f"")
        lines.append(f"⚠️ Invalidation : Clôture H4 sous SSL → biais neutre")

    elif bias == "SHORT" and liq and fvg_h4:
        bear_fvgs = [f for f in fvg_h4 if f["type"] == "bearish" and f["bottom"] > current_price]
        bsl_above = sorted([l for l in liq["bsl"] if l > current_price])
        ssl_below = sorted([l for l in liq["ssl"] if l < current_price], reverse=True)

        if bear_fvgs:
            best = min(bear_fvgs, key=lambda f: f["bottom"])
            lines.append(f"Setup  : Rally vers FVG Bearish H4")
            lines.append(f"         Zone : <code>{fp(best['bottom'])}</code> – <code>{fp(best['top'])}</code>")
        elif bsl_above:
            lines.append(f"Setup  : Short sur BSL H4 le plus proche")
            lines.append(f"         Zone : <code>{fp(bsl_above[0])}</code>")
        else:
            lines.append("Setup  : Short sur rally structure H1")

        if bsl_above:
            lines.append(f"Stop   : Au-dessus BSL @ <code>{fp(bsl_above[0])}</code>")
        if ssl_below:
            lines.append(f"Target : SSL @ <code>{fp(ssl_below[0])}</code>")
            if bsl_above:
                sl = bsl_above[0] - current_price
                tp = current_price - ssl_below[0]
                if sl > 0 and tp > 0:
                    lines.append(f"R:R    : ~1:{tp/sl:.1f}")

        lines.append(f"")
        lines.append(f"⚠️ Invalidation : Clôture H4 au-dessus BSL → biais neutre")

    else:
        lines.append("Setup  : Biais insuffisant — attendre signal clair")
        lines.append("         → Surveiller un break + retest de structure H4")
        lines.append("         → Ou attendre la prochaine release macro (voir /day)")

    lines += [
        "",
        "━" * 32,
        "⚡ <b>tradingLIVE</b> | /confluence | /vix | /deep | /day",
    ]
    return "\n".join(lines)


# ── Handler Telegram ───────────────────────────────────────────────────────────

async def cmd_analyze(update, ctx) -> None:
    """Handler /analyze <asset>"""
    user_id = update.effective_user.id
    if not subscription_manager.is_user_active(user_id):
        await update.message.reply_text("❌ **Subscription requise**", parse_mode="Markdown")
        return

    if not ctx.args:
        await update.message.reply_text(
            "📊 <b>Analyse de Confluence</b>\n\n"
            "Usage : <code>/analyze &lt;asset&gt;</code>\n\n"
            "<b>Assets disponibles :</b>\n"
            "• Indices  : <code>NQ</code>  <code>ES</code>\n"
            "• Forex    : <code>EURUSD</code>  <code>GBPUSD</code>  <code>USDJPY</code>  <code>USDCAD</code>\n"
            "• Commodity: <code>GOLD</code>  <code>GC</code>\n"
            "• Stock    : <code>NVDA</code>",
            parse_mode="HTML",
        )
        return

    raw  = ctx.args[0].upper().strip()
    name = ASSET_ALIASES.get(raw) or ASSET_ALIASES.get(raw.replace("/", ""))
    if not name:
        await update.message.reply_text(
            f"❌ Asset <code>{_esc(raw)}</code> non reconnu.\n"
            "Essaie : <code>NQ</code>, <code>ES</code>, <code>GOLD</code>, <code>EURUSD</code>",
            parse_mode="HTML",
        )
        return

    symbol = _YF.get(name)
    if not symbol:
        await update.message.reply_text(f"❌ Symbol manquant pour {name}.", parse_mode="HTML")
        return

    msg = await update.message.reply_text(
        f"<i>🔍 Analyse de confluence {_DISPLAY.get(name, name)}… (~15s)</i>",
        parse_mode="HTML",
    )

    loop = asyncio.get_running_loop()

    def _gather():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            f_h4    = pool.submit(_fetch_ohlcv, symbol, "4h")
            f_h1    = pool.submit(_fetch_ohlcv, symbol, "1h")
            f_daily = pool.submit(_fetch_ohlcv, symbol, "1d")
            h4_df    = f_h4.result()
            h1_df    = f_h1.result()
            daily_df = f_daily.result()
        return h4_df, h1_df, daily_df

    try:
        h4_df, h1_df, daily_df = await loop.run_in_executor(None, _gather)

        if daily_df is None:
            await msg.delete()
            await update.message.reply_text(
                "❌ Données indisponibles. Marché fermé ou ticker yfinance inaccessible.",
                parse_mode="HTML",
            )
            return

        closes    = daily_df["Close"]
        price     = float(closes.iloc[-1])
        price_7d  = float(closes.iloc[-8]) if len(closes) >= 8 else float(closes.iloc[0])
        change_7d = (price - price_7d) / price_7d * 100
        rsi       = _calc_rsi(closes)
        trend_h4  = _trend_from_df(h4_df)
        trend_h1  = _trend_from_df(h1_df)

        report = _format_report(
            name=name,
            current_price=price,
            h4_df=h4_df,
            h1_df=h1_df,
            rsi=rsi,
            change_7d=change_7d,
            trend_h4=trend_h4,
            trend_h1=trend_h1,
        )

        await msg.delete()
        from formatter import _split_message
        for part in _split_message(report):
            await update.message.reply_text(
                part, parse_mode="HTML", disable_web_page_preview=True
            )

    except Exception as exc:
        log.error("cmd_analyze error: %s", exc, exc_info=True)
        try:
            await msg.delete()
        except Exception:
            pass
        from html import escape
        await update.message.reply_text(
            f"❌ Erreur : <code>{escape(str(exc))}</code>", parse_mode="HTML"
        )
