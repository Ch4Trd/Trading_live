"""
purge_scan.py
Handler /purge_scan <asset> — détection ICT Liquidity Purge / Stop Hunt.

Sessions analysées :
  • Asian Session  : 20:00–00:00 EST (veille) = 00:00–04:00 UTC
  • Prev Session   : High/Low de la bougie daily précédente

Règle de purge (stricte) :
  - Wick dépasse le niveau (High > level ou Low < level)
  - Corps (Open/Close) reste entièrement à l'intérieur de la session
    (max(Open,Close) < level pour bearish purge OU min(Open,Close) > level pour bullish purge)

Target : pool de liquidité opposée (si purge BSL → target SSL, et vice versa)

Rapport : tableau avec [CONFIRMÉE 🟢] ou [AUCUNE 🔍] par niveau
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import escape as _esc
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from subscription import subscription_manager

log = logging.getLogger(__name__)

EST = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

MIN_BARS_M5  = 40
MIN_BARS_M15 = 20

# ── Alias mapping ──────────────────────────────────────────────────────────────
ASSET_ALIASES: dict[str, str] = {
    "NQ": "NAS100", "NAS": "NAS100", "NDX": "NAS100", "NAS100": "NAS100",
    "NASDAQ": "NAS100", "NQ100": "NAS100",
    "ES": "US500", "SPX": "US500", "SP500": "US500", "US500": "US500",
    "S&P": "US500",
    "EURUSD": "EUR/USD", "EU": "EUR/USD", "EUR": "EUR/USD", "EUR/USD": "EUR/USD",
    "GBPUSD": "GBP/USD", "GU": "GBP/USD", "CABLE": "GBP/USD", "GBP": "GBP/USD",
    "GBP/USD": "GBP/USD",
    "USDJPY": "USD/JPY", "UJ": "USD/JPY", "JPY": "USD/JPY", "USD/JPY": "USD/JPY",
    "USDCAD": "USD/CAD", "UC": "USD/CAD", "CAD": "USD/CAD", "USD/CAD": "USD/CAD",
    "GOLD": "XAU/USD", "GC": "XAU/USD", "XAUUSD": "XAU/USD",
    "XAU": "XAU/USD", "XAU/USD": "XAU/USD", "OR": "XAU/USD",
    "NVDA": "NVDA", "NVIDIA": "NVDA",
}

_YF: dict[str, str] = {
    "EUR/USD": "EURUSD=X", "USD/CAD": "USDCAD=X",
    "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "XAU/USD": "GC=F",
    "NAS100":  "^NDX",
    "US500":   "^GSPC",
    "NVDA":    "NVDA",
}

_ASSET_EMOJI: dict[str, str] = {
    "EUR/USD": "🇪🇺", "USD/CAD": "🇨🇦", "GBP/USD": "🇬🇧", "USD/JPY": "🇯🇵",
    "XAU/USD": "🥇", "NAS100": "📈", "US500": "📊", "NVDA": "🖥️",
}

_IS_FOREX = {"EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD"}


# ── Fetch helpers ──────────────────────────────────────────────────────────────

def _fetch_intraday(ticker: str, interval: str, period: str) -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, interval=interval, period=period,
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns]
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(EST)
        return df.dropna()
    except Exception as e:
        log.error("Fetch error %s %s %s: %s", ticker, interval, period, e)
        return None


def _fetch_daily(ticker: str) -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, interval="1d", period="10d",
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns]
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df.dropna()
    except Exception as e:
        log.error("Daily fetch error %s: %s", ticker, e)
        return None


def _fetch_all_parallel(ticker: str):
    """Parallel fetch M5 (5d), M15 (5d), Daily (10d)."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_m5  = pool.submit(_fetch_intraday, ticker, "5m",  "5d")
        f_m15 = pool.submit(_fetch_intraday, ticker, "15m", "5d")
        f_d   = pool.submit(_fetch_daily, ticker)
        m5  = f_m5.result()
        m15 = f_m15.result()
        day = f_d.result()
    return m5, m15, day


# ── Session range calculators ──────────────────────────────────────────────────

def _get_asian_range(df_m5: pd.DataFrame, now_est: datetime) -> dict | None:
    """
    Asian session = 20:00–00:00 EST (la veille en EST = 00:00–04:00 UTC).
    On cherche la dernière session asiatique complète (celle qui s'est terminée avant now_est).
    """
    # La session asia se termine à minuit EST du même jour civil
    # Si maintenant il est 14h EST, la dernière asia était hier soir 20h–minuit
    today_midnight = now_est.replace(hour=0, minute=0, second=0, microsecond=0)
    asia_end   = today_midnight  # 00:00 EST aujourd'hui
    asia_start = asia_end - timedelta(hours=4)  # 20:00 EST hier

    seg = df_m5[(df_m5.index >= asia_start) & (df_m5.index < asia_end)]

    # Si pas assez de données, essayer la session asia d'il y a 2 jours
    if len(seg) < 3:
        asia_end   -= timedelta(days=1)
        asia_start -= timedelta(days=1)
        seg = df_m5[(df_m5.index >= asia_start) & (df_m5.index < asia_end)]

    if seg.empty:
        return None

    return {
        "high":  float(seg["High"].max()),
        "low":   float(seg["Low"].min()),
        "start": asia_start,
        "end":   asia_end,
        "bars":  len(seg),
    }


def _get_prev_session_range(daily_df: pd.DataFrame) -> dict | None:
    """
    Prev Session = la bougie daily précédente (iloc[-2]).
    """
    if daily_df is None or len(daily_df) < 2:
        return None
    prev = daily_df.iloc[-2]
    return {
        "high":  float(prev["High"]),
        "low":   float(prev["Low"]),
        "date":  daily_df.index[-2].strftime("%Y-%m-%d"),
    }


# ── Purge detection ────────────────────────────────────────────────────────────

def _detect_purge(df: pd.DataFrame, level_high: float, level_low: float,
                  session_name: str) -> list[dict]:
    """
    Scanne df à la recherche de purges de liquidité sur level_high et level_low.
    Retourne une liste de dicts avec les détails de chaque purge trouvée.
    """
    purges = []

    for i, (ts, row) in enumerate(df.iterrows()):
        body_hi = max(float(row["Open"]), float(row["Close"]))
        body_lo = min(float(row["Open"]), float(row["Close"]))

        # BSL Purge : wick au-dessus de level_high, corps en dessous
        if float(row["High"]) > level_high and body_hi <= level_high:
            purges.append({
                "type":         "BSL_PURGE",
                "level":        level_high,
                "level_label":  f"{session_name} High",
                "wick_extreme": float(row["High"]),
                "body_close":   float(row["Close"]),
                "bar_time":     ts,
                "target_type":  "SSL",
                "target_level": level_low,
                "direction":    "bearish",
                "session":      session_name,
            })

        # SSL Purge : wick en dessous de level_low, corps au-dessus
        if float(row["Low"]) < level_low and body_lo >= level_low:
            purges.append({
                "type":         "SSL_PURGE",
                "level":        level_low,
                "level_label":  f"{session_name} Low",
                "wick_extreme": float(row["Low"]),
                "body_close":   float(row["Close"]),
                "bar_time":     ts,
                "target_type":  "BSL",
                "target_level": level_high,
                "direction":    "bullish",
                "session":      session_name,
            })

    return purges


def _calc_target_distance(price: float, target: float, name: str) -> str:
    """Calcule la distance en pips ou points vers le target."""
    diff = abs(target - price)
    if name in _IS_FOREX:
        pips = diff * 10000
        return f"{pips:.1f} pips"
    return f"{diff:.2f} pts"


def _fmt_price(val: float, name: str) -> str:
    if name in _IS_FOREX:
        return f"{val:.5f}"
    if name == "XAU/USD":
        return f"{val:.2f}"
    return f"{val:.2f}"


# ── Message formatter ──────────────────────────────────────────────────────────

def _format_report(
    asset_name: str,
    now_est: datetime,
    price: float,
    asian_range: dict | None,
    prev_range: dict | None,
    purges_asian: list[dict],
    purges_prev: list[dict],
    m5_bars: int,
    m15_bars: int,
) -> str:
    emoji = _ASSET_EMOJI.get(asset_name, "📊")
    fp = lambda v: _fmt_price(v, asset_name)

    lines = []
    lines.append(f"<b>🎯 ICT PURGE SCAN — {emoji} {_esc(asset_name)}</b>")
    lines.append(f"<code>Heure EST : {now_est.strftime('%H:%M:%S')}</code>")
    lines.append(f"💵 Prix actuel : <code>{fp(price)}</code>")
    lines.append(f"📊 Données : M5 {m5_bars} bars | M15 {m15_bars} bars")

    # ── Asian Session Range ──
    lines.append("\n<b>━━ ASIAN SESSION (20:00–00:00 EST) ━━</b>")
    if asian_range:
        lines.append(f"  High : <code>{fp(asian_range['high'])}</code>")
        lines.append(f"  Low  : <code>{fp(asian_range['low'])}</code>")
        lines.append(f"  Range: <code>{fp(asian_range['high'] - asian_range['low'])}</code>")
        lines.append(f"  Période : {asian_range['start'].strftime('%m/%d %H:%M')} → {asian_range['end'].strftime('%H:%M')} EST")
        lines.append(f"  Bougies : {asian_range['bars']}")
    else:
        lines.append("  ⚠️ Données Asian Session insuffisantes")

    # ── Previous Session Range ──
    lines.append("\n<b>━━ PREVIOUS SESSION (DAILY) ━━</b>")
    if prev_range:
        lines.append(f"  High : <code>{fp(prev_range['high'])}</code>   [{prev_range['date']}]")
        lines.append(f"  Low  : <code>{fp(prev_range['low'])}</code>")
    else:
        lines.append("  ⚠️ Données Previous Session insuffisantes")

    # ── Purges Asian ──
    lines.append("\n<b>━━ PURGES DÉTECTÉES — ASIAN RANGE ━━</b>")
    if purges_asian:
        for p in purges_asian:
            dir_str = "BAISSIER 🔴" if p["direction"] == "bearish" else "HAUSSIER 🟢"
            dist = _calc_target_distance(price, p["target_level"], asset_name)
            lines.append(f"  🟢 <b>[CONFIRMÉE]</b> {p['level_label']} Purge — {dir_str}")
            lines.append(f"     Niveau purgé  : <code>{fp(p['level'])}</code>")
            lines.append(f"     Wick extreme  : <code>{fp(p['wick_extreme'])}</code>")
            lines.append(f"     Corps close   : <code>{fp(p['body_close'])}</code>")
            lines.append(f"     Heure         : {p['bar_time'].strftime('%H:%M')}")
            lines.append(f"     🎯 Target ({p['target_type']}): <code>{fp(p['target_level'])}</code>  [{dist}]")
    else:
        lines.append("  🔍 <b>[AUCUNE]</b> — Aucune purge Asian détectée")

    # ── Purges Previous Session ──
    lines.append("\n<b>━━ PURGES DÉTECTÉES — PREVIOUS SESSION ━━</b>")
    if purges_prev:
        for p in purges_prev:
            dir_str = "BAISSIER 🔴" if p["direction"] == "bearish" else "HAUSSIER 🟢"
            dist = _calc_target_distance(price, p["target_level"], asset_name)
            lines.append(f"  🟢 <b>[CONFIRMÉE]</b> {p['level_label']} Purge — {dir_str}")
            lines.append(f"     Niveau purgé  : <code>{fp(p['level'])}</code>")
            lines.append(f"     Wick extreme  : <code>{fp(p['wick_extreme'])}</code>")
            lines.append(f"     Corps close   : <code>{fp(p['body_close'])}</code>")
            lines.append(f"     Heure         : {p['bar_time'].strftime('%H:%M')}")
            lines.append(f"     🎯 Target ({p['target_type']}): <code>{fp(p['target_level'])}</code>  [{dist}]")
    else:
        lines.append("  🔍 <b>[AUCUNE]</b> — Aucune purge Previous Session détectée")

    # ── Résumé global ──
    total_purges = len(purges_asian) + len(purges_prev)
    lines.append("\n<b>━━ RÉSUMÉ ━━</b>")
    if total_purges == 0:
        lines.append("  🔍 <b>Aucune purge confirmée</b> — Liquidité intacte")
        lines.append("  Surveiller les niveaux pour un stop hunt potentiel")
    else:
        # Consolidate dominant direction
        bull = sum(1 for p in purges_asian + purges_prev if p["direction"] == "bullish")
        bear = sum(1 for p in purges_asian + purges_prev if p["direction"] == "bearish")
        dom = "HAUSSIER 🟢" if bull > bear else "BAISSIER 🔴" if bear > bull else "MIXTE ⚠️"
        lines.append(f"  ✅ <b>{total_purges} purge(s) confirmée(s)</b> — Biais dominant : {dom}")
        if bull > 0:
            lines.append(f"  • {bull} SSL Purge(s) → anticipation hausse vers BSL")
        if bear > 0:
            lines.append(f"  • {bear} BSL Purge(s) → anticipation baisse vers SSL")

    lines.append(f"\n<i>⏱ Analyse M5/M15 · {now_est.strftime('%Y-%m-%d %H:%M')} EST</i>")
    return "\n".join(lines)


# ── Main handler ───────────────────────────────────────────────────────────────

async def cmd_purge_scan(update, context):
    """Handler Telegram /purge_scan <asset>."""
    user_id = update.effective_user.id
    if not subscription_manager.is_user_active(user_id):
        await update.message.reply_text(
            "🔒 <b>Accès restreint</b>\n\n"
            "Cette commande nécessite un abonnement actif.\n"
            "Contactez l'administrateur pour obtenir l'accès.",
            parse_mode="HTML",
        )
        return

    args = (context.args or [])
    if not args:
        await update.message.reply_text(
            "⚠️ Usage : <code>/purge_scan &lt;asset&gt;</code>\n"
            "Exemples : <code>/purge_scan NQ</code> | <code>/purge_scan GOLD</code> | "
            "<code>/purge_scan EU</code>",
            parse_mode="HTML",
        )
        return

    raw = args[0].upper().strip()
    asset_name = ASSET_ALIASES.get(raw)
    if asset_name is None:
        await update.message.reply_text(
            f"❌ Asset inconnu : <code>{_esc(raw)}</code>\n"
            "Assets disponibles : NQ, ES, EURUSD, GBPUSD, USDJPY, USDCAD, GOLD, NVDA",
            parse_mode="HTML",
        )
        return

    ticker = _YF[asset_name]
    now_est = datetime.now(EST)

    msg = await update.message.reply_text(
        f"🎯 <b>Purge Scan en cours...</b>\n"
        f"Asset : {_ASSET_EMOJI.get(asset_name,'📊')} <b>{asset_name}</b>",
        parse_mode="HTML",
    )

    try:
        loop = asyncio.get_event_loop()
        m5_df, m15_df, daily_df = await loop.run_in_executor(None, _fetch_all_parallel, ticker)

        m5_bars  = len(m5_df)  if m5_df  is not None else 0
        m15_bars = len(m15_df) if m15_df is not None else 0

        if m5_df is None or m5_bars < MIN_BARS_M5:
            await msg.edit_text(
                f"❌ Données M5 insuffisantes pour {asset_name} ({m5_bars} bars). "
                "Réessayez dans quelques secondes.",
                parse_mode="HTML",
            )
            return

        price = float(m5_df["Close"].iloc[-1])

        # Session ranges
        asian_range = _get_asian_range(m5_df, now_est)
        prev_range  = _get_prev_session_range(daily_df)

        # Use M5 for purge scanning (more granular)
        # Scan only today's candles (current session)
        today_open = now_est.replace(hour=0, minute=0, second=0, microsecond=0)
        today_seg = m5_df[m5_df.index >= today_open]

        purges_asian: list[dict] = []
        purges_prev:  list[dict] = []

        if asian_range and len(today_seg) >= 3:
            purges_asian = _detect_purge(
                today_seg,
                asian_range["high"],
                asian_range["low"],
                "Asian",
            )

        if prev_range and len(today_seg) >= 3:
            purges_prev = _detect_purge(
                today_seg,
                prev_range["high"],
                prev_range["low"],
                "Prev Session",
            )

        # If no purges in today_seg, scan last 48h to catch recent ones
        if not purges_asian and not purges_prev and m5_bars > 0:
            cutoff = now_est - timedelta(hours=48)
            recent_seg = m5_df[m5_df.index >= cutoff]
            if asian_range:
                purges_asian = _detect_purge(
                    recent_seg, asian_range["high"], asian_range["low"], "Asian"
                )
            if prev_range:
                purges_prev = _detect_purge(
                    recent_seg, prev_range["high"], prev_range["low"], "Prev Session"
                )
            # Keep only last 3 of each
            purges_asian = purges_asian[-3:]
            purges_prev  = purges_prev[-3:]

        report = _format_report(
            asset_name, now_est, price,
            asian_range, prev_range,
            purges_asian, purges_prev,
            m5_bars, m15_bars,
        )
        await msg.edit_text(report, parse_mode="HTML")

    except Exception as e:
        log.exception("purge_scan error for %s", asset_name)
        await msg.edit_text(
            f"❌ Erreur lors du Purge Scan : <code>{_esc(str(e))}</code>",
            parse_mode="HTML",
        )
