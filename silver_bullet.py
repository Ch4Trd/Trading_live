"""
silver_bullet.py
Handler /silver_bullet <asset> — détection ICT Silver Bullet en temps réel.

Fenêtres Silver Bullet (heure EST/EDT) :
  • 03:00–04:00  London Open Kill Zone
  • 10:00–11:00  AM Session Kill Zone
  • 14:00–15:00  PM Session Kill Zone

Logique stricte :
  1. Calcul du range BSL/SSL pré-fenêtre sur M5 (20 dernières bougies avant ouverture)
  2. Détection du sweep de liquidité (wick > niveau, corps reste à l'intérieur)
  3. Détection du MSS post-sweep (corps close au-dessus/dessous d'un swing structurel)
  4. Extraction du FVG sur la bougie MSS et ses adjacentes
  5. Rapport : [VALIDÉ 🟢] si setup complet, [RECHERCHE 🔍] si partiel, [HORS FENÊTRE ⏳] sinon
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

# ── Fenêtres Silver Bullet (EST, heure locale) ─────────────────────────────────
SB_WINDOWS = [
    (3,  4,  "London Open Kill Zone"),
    (10, 11, "AM Session Kill Zone"),
    (14, 15, "PM Session Kill Zone"),
]
LOOKBACK_CANDLES = 30   # bougies M5 utilisées pour le range pré-fenêtre
SWING_ORDER      = 3    # order pour détection des swings
MIN_BARS_M1      = 20
MIN_BARS_M5      = 40

# ── Mapping aliases → nom interne ─────────────────────────────────────────────
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

def _fetch_m5(ticker: str) -> pd.DataFrame | None:
    """Fetch M5 data (last 5 days)."""
    try:
        df = yf.download(ticker, interval="5m", period="5d",
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
        log.error("M5 fetch error %s: %s", ticker, e)
        return None


def _fetch_m1(ticker: str) -> pd.DataFrame | None:
    """Fetch M1 data; try 2d first, fallback to M5 for GC=F."""
    for period in ("2d", "5d"):
        try:
            df = yf.download(ticker, interval="1m", period=period,
                             auto_adjust=True, progress=False)
            if df is None or df.empty:
                continue
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.capitalize() for c in df.columns]
            df.index = pd.to_datetime(df.index)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            df.index = df.index.tz_convert(EST)
            df = df.dropna()
            if len(df) >= MIN_BARS_M1:
                return df
        except Exception as e:
            log.error("M1 fetch error %s period=%s: %s", ticker, period, e)
    return None


def _fetch_all_parallel(ticker: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Parallel fetch M1 + M5."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_m1 = pool.submit(_fetch_m1, ticker)
        fut_m5 = pool.submit(_fetch_m5, ticker)
        m1 = fut_m1.result()
        m5 = fut_m5.result()
    return m1, m5


# ── Window helpers ─────────────────────────────────────────────────────────────

def _current_window(now_est: datetime) -> tuple[int, int, str] | None:
    """Return the active SB window (h_start, h_end, label) or None."""
    h = now_est.hour
    m = now_est.minute
    for h_start, h_end, label in SB_WINDOWS:
        if h_start <= h < h_end or (h == h_end and m == 0):
            return (h_start, h_end, label)
    return None


def _next_window(now_est: datetime) -> tuple[int, int, str, str]:
    """Return next upcoming SB window and formatted time string."""
    h = now_est.hour
    for h_start, h_end, label in SB_WINDOWS:
        if h_start > h:
            delta = timedelta(hours=h_start - h, minutes=-now_est.minute)
            target = now_est + delta
            return h_start, h_end, label, target.strftime("%H:%M")
    # Tomorrow's first window
    h_start, h_end, label = SB_WINDOWS[0]
    delta = timedelta(hours=24 - h + h_start, minutes=-now_est.minute)
    target = now_est + delta
    return h_start, h_end, label, target.strftime("%H:%M")


# ── Technical detection ────────────────────────────────────────────────────────

def _find_swings(df: pd.DataFrame, order: int = 3):
    """Returns (highs, lows) as lists of (iloc_idx, price)."""
    highs, lows = [], []
    closes = df["Close"].values
    highs_v = df["High"].values
    lows_v = df["Low"].values
    n = len(df)
    for i in range(order, n - order):
        # Swing High
        if all(highs_v[i] >= highs_v[i - j] for j in range(1, order + 1)) and \
           all(highs_v[i] >= highs_v[i + j] for j in range(1, order + 1)):
            highs.append((i, highs_v[i]))
        # Swing Low
        if all(lows_v[i] <= lows_v[i - j] for j in range(1, order + 1)) and \
           all(lows_v[i] <= lows_v[i + j] for j in range(1, order + 1)):
            lows.append((i, lows_v[i]))
    return highs, lows


def _calc_pre_window_range(df_m5: pd.DataFrame, win_h_start: int, now_est: datetime):
    """
    Calcule le range BSL/SSL sur les LOOKBACK_CANDLES bougies M5
    qui précèdent l'ouverture de la fenêtre actuelle.
    Retourne (bsl_price, ssl_price) ou (None, None).
    """
    # Moment d'ouverture de la fenêtre aujourd'hui
    win_open = now_est.replace(hour=win_h_start, minute=0, second=0, microsecond=0)
    pre = df_m5[df_m5.index < win_open]
    if len(pre) < 5:
        return None, None
    pre = pre.tail(LOOKBACK_CANDLES)
    bsl = float(pre["High"].max())
    ssl = float(pre["Low"].min())
    return bsl, ssl


def _detect_sweep(df_segment: pd.DataFrame, bsl: float, ssl: float):
    """
    Détecte un sweep de liquidité dans df_segment (bougies de la fenêtre actuelle).
    Règle : wick dépasse le niveau, corps reste à l'intérieur.
    Retourne dict avec type / price / bar_idx ou None.
    """
    if df_segment.empty:
        return None

    for i, (ts, row) in enumerate(df_segment.iterrows()):
        body_hi = max(row["Open"], row["Close"])
        body_lo = min(row["Open"], row["Close"])

        # BSL sweep (liquidity above swept)
        if row["High"] > bsl and body_hi <= bsl:
            return {
                "type": "BSL_SWEEP",
                "level": bsl,
                "bar_time": ts,
                "bar_idx": i,
                "direction": "bearish",  # après sweep BSL → anticipation baisse
                "wick_extreme": float(row["High"]),
                "body_close": float(row["Close"]),
            }

        # SSL sweep (liquidity below swept)
        if row["Low"] < ssl and body_lo >= ssl:
            return {
                "type": "SSL_SWEEP",
                "level": ssl,
                "bar_time": ts,
                "bar_idx": i,
                "direction": "bullish",  # après sweep SSL → anticipation hausse
                "wick_extreme": float(row["Low"]),
                "body_close": float(row["Close"]),
            }
    return None


def _detect_mss(df_segment: pd.DataFrame, sweep: dict, swings_before: tuple):
    """
    Détecte le Market Structure Shift APRÈS le sweep.
    Règle body-only (ICT strict) : close dépasse un swing structurel formé après le sweep.
    Retourne dict avec type / price / bar_idx ou None.
    """
    sweep_idx = sweep["bar_idx"]
    direction = sweep["direction"]

    # Bougies post-sweep
    post = df_segment.iloc[sweep_idx + 1:]
    if post.empty:
        return None

    highs_pre, lows_pre = swings_before

    if direction == "bullish":
        # On cherche un swing high formé APRÈS le sweep → corps passe au-dessus
        # On crée les swings sur la portion post-sweep
        post_reset = df_segment.iloc[max(0, sweep_idx - SWING_ORDER):]
        post_highs, _ = _find_swings(post_reset, order=SWING_ORDER)
        if not post_highs:
            return None
        # Prendre le premier swing high local post-sweep
        target_swing = None
        for ph_i, ph_price in post_highs:
            real_idx = ph_i + max(0, sweep_idx - SWING_ORDER)
            if real_idx > sweep_idx:
                target_swing = (real_idx, ph_price)
                break
        if target_swing is None:
            return None
        sw_iloc, sw_price = target_swing
        for i in range(sw_iloc + 1, len(df_segment)):
            if df_segment.iloc[i]["Close"] > sw_price:
                return {
                    "type": "MSS_BULLISH",
                    "broken_swing": sw_price,
                    "bar_idx": i,
                    "bar_time": df_segment.index[i],
                    "mss_close": float(df_segment.iloc[i]["Close"]),
                }

    elif direction == "bearish":
        post_reset = df_segment.iloc[max(0, sweep_idx - SWING_ORDER):]
        _, post_lows = _find_swings(post_reset, order=SWING_ORDER)
        if not post_lows:
            return None
        target_swing = None
        for pl_i, pl_price in post_lows:
            real_idx = pl_i + max(0, sweep_idx - SWING_ORDER)
            if real_idx > sweep_idx:
                target_swing = (real_idx, pl_price)
                break
        if target_swing is None:
            return None
        sw_iloc, sw_price = target_swing
        for i in range(sw_iloc + 1, len(df_segment)):
            if df_segment.iloc[i]["Close"] < sw_price:
                return {
                    "type": "MSS_BEARISH",
                    "broken_swing": sw_price,
                    "bar_idx": i,
                    "bar_time": df_segment.index[i],
                    "mss_close": float(df_segment.iloc[i]["Close"]),
                }
    return None


def _detect_fvg_around_mss(df_segment: pd.DataFrame, mss: dict):
    """
    Cherche le FVG formé par la bougie MSS et ses voisines.
    Retourne dict {type, bottom, top, mid} ou None.
    """
    i = mss["bar_idx"]
    if i < 1 or i >= len(df_segment) - 1:
        return None

    c_prev = df_segment.iloc[i - 1]
    c_cur  = df_segment.iloc[i]
    c_next = df_segment.iloc[i + 1] if i + 1 < len(df_segment) else None

    # Check FVG classique : gap entre c_prev.High et c_next.Low (bullish)
    # ou c_prev.Low et c_next.High (bearish)
    if c_next is not None:
        # Bullish FVG
        if c_prev["High"] < c_next["Low"]:
            bot = float(c_prev["High"])
            top = float(c_next["Low"])
            return {"type": "FVG_BULL", "bottom": bot, "top": top, "mid": (bot + top) / 2}
        # Bearish FVG
        if c_prev["Low"] > c_next["High"]:
            top = float(c_prev["Low"])
            bot = float(c_next["High"])
            return {"type": "FVG_BEAR", "bottom": bot, "top": top, "mid": (bot + top) / 2}

    # Fallback : chercher FVG entre la bougie précédant i-1 et c_cur
    if i >= 2:
        c_p2 = df_segment.iloc[i - 2]
        if c_p2["High"] < c_cur["Low"]:
            bot = float(c_p2["High"])
            top = float(c_cur["Low"])
            return {"type": "FVG_BULL", "bottom": bot, "top": top, "mid": (bot + top) / 2}
        if c_p2["Low"] > c_cur["High"]:
            top = float(c_p2["Low"])
            bot = float(c_cur["High"])
            return {"type": "FVG_BEAR", "bottom": bot, "top": top, "mid": (bot + top) / 2}

    return None


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
    window: tuple | None,
    next_win: tuple,
    price: float,
    bsl: float | None,
    ssl: float | None,
    sweep: dict | None,
    mss: dict | None,
    fvg: dict | None,
    m1_bars: int,
    m5_bars: int,
) -> str:
    emoji = _ASSET_EMOJI.get(asset_name, "📊")
    fp = lambda v: _fmt_price(v, asset_name)

    lines = []
    lines.append(f"<b>⚡ ICT SILVER BULLET — {emoji} {_esc(asset_name)}</b>")
    lines.append(f"<code>Heure EST : {now_est.strftime('%H:%M:%S')}</code>")
    lines.append("")

    # ── Fenêtre ──
    if window:
        h_s, h_e, wlabel = window
        lines.append(f"🟩 <b>FENÊTRE ACTIVE : {h_s:02d}:00–{h_e:02d}:00 EST</b>")
        lines.append(f"   <i>{_esc(wlabel)}</i>")
    else:
        n_hs, n_he, n_label, n_time = next_win
        lines.append(f"⏳ <b>HORS FENÊTRE</b>")
        lines.append(f"   Prochaine : {n_hs:02d}:00–{n_he:02d}:00 — {_esc(n_label)}")
        lines.append(f"   Dans ≈ <b>{n_time}</b> (première ouverture)</b>")

    lines.append(f"\n💵 Prix actuel : <code>{fp(price)}</code>")
    lines.append(f"📊 Données : M1 {m1_bars} bars | M5 {m5_bars} bars")

    # ── Range pré-fenêtre ──
    lines.append("\n<b>━━ RANGE PRÉ-FENÊTRE ━━</b>")
    if bsl is not None and ssl is not None:
        lines.append(f"  BSL  <code>{fp(bsl)}</code>   ↑ Liquidité haute")
        lines.append(f"  SSL  <code>{fp(ssl)}</code>   ↓ Liquidité basse")
    else:
        lines.append("  ⚠️ Range insuffisant (données pré-fenêtre manquantes)")

    # ── Sweep ──
    lines.append("\n<b>━━ SWEEP DE LIQUIDITÉ ━━</b>")
    if sweep:
        sw_type = "BSL ↑ (setup baissier)" if sweep["type"] == "BSL_SWEEP" else "SSL ↓ (setup haussier)"
        lines.append(f"  ✅ <b>{sw_type}</b>")
        lines.append(f"  Niveau sweepé : <code>{fp(sweep['level'])}</code>")
        lines.append(f"  Wick extreme  : <code>{fp(sweep['wick_extreme'])}</code>")
        lines.append(f"  Corps close   : <code>{fp(sweep['body_close'])}</code>")
        lines.append(f"  Heure         : {sweep['bar_time'].strftime('%H:%M')}")
    else:
        lines.append("  🔍 Aucun sweep détecté dans la fenêtre courante")

    # ── MSS ──
    lines.append("\n<b>━━ MARKET STRUCTURE SHIFT (MSS) ━━</b>")
    if mss:
        mss_dir = "HAUSSIER 🟢" if mss["type"] == "MSS_BULLISH" else "BAISSIER 🔴"
        lines.append(f"  ✅ <b>MSS {mss_dir}</b>")
        lines.append(f"  Swing cassé   : <code>{fp(mss['broken_swing'])}</code>")
        lines.append(f"  Close de casse: <code>{fp(mss['mss_close'])}</code>")
        lines.append(f"  Heure         : {mss['bar_time'].strftime('%H:%M')}")
    elif sweep:
        lines.append("  🔍 MSS non encore confirmé — en attente de structure")
    else:
        lines.append("  ─ En attente du sweep")

    # ── FVG ──
    lines.append("\n<b>━━ FAIR VALUE GAP (ENTRÉE) ━━</b>")
    if fvg:
        fvg_label = "BULLISH 🟢" if fvg["type"] == "FVG_BULL" else "BEARISH 🔴"
        lines.append(f"  ✅ <b>FVG {fvg_label}</b>")
        lines.append(f"  Zone   : <code>{fp(fvg['bottom'])}</code> – <code>{fp(fvg['top'])}</code>")
        lines.append(f"  Mid 50%: <code>{fp(fvg['mid'])}</code>")
    elif mss:
        lines.append("  🔍 FVG non extrait autour du MSS")
    else:
        lines.append("  ─ En attente du MSS")

    # ── Verdict ──
    lines.append("\n<b>━━ VERDICT ━━</b>")
    if not window:
        lines.append("  ⏳ <b>[HORS FENÊTRE]</b> — Aucune action Silver Bullet valide")
    elif sweep and mss and fvg:
        direction = "LONG 🟢" if mss["type"] == "MSS_BULLISH" else "SHORT 🔴"
        lines.append(f"  🟢 <b>[SETUP VALIDÉ]</b> — Silver Bullet {direction}")
        lines.append(f"  Entrée idéale : FVG Mid <code>{fp(fvg['mid'])}</code>")
        lines.append(f"  Stop          : au-delà de <code>{fp(sweep['wick_extreme'])}</code>")
    elif sweep and mss:
        lines.append("  🟡 <b>[PARTIEL — FVG MANQUANT]</b>")
        lines.append("  Sweep ✅ | MSS ✅ | FVG ❌ — Setup incomplet")
    elif sweep:
        lines.append("  🔍 <b>[RECHERCHE — SWEEP DÉTECTÉ]</b>")
        lines.append("  En attente du MSS de confirmation")
    else:
        lines.append("  🔍 <b>[RECHERCHE — EN SURVEILLANCE]</b>")
        lines.append("  Aucun setup Silver Bullet actif pour l'instant")

    lines.append(f"\n<i>⏱ Analyse M1/M5 en temps réel · {now_est.strftime('%Y-%m-%d %H:%M')} EST</i>")
    return "\n".join(lines)


# ── Main handler ───────────────────────────────────────────────────────────────

async def cmd_silver_bullet(update, context):
    """Handler Telegram /silver_bullet <asset>."""
    user_id = update.effective_user.id
    if not subscription_manager.is_user_active(user_id):
        await update.message.reply_text(
            "🔒 <b>Accès restreint</b>\n\n"
            "Cette commande nécessite un abonnement actif.\n"
            "Contactez l'administrateur pour obtenir l'accès.",
            parse_mode="HTML",
        )
        return

    # Parse asset argument
    args = (context.args or [])
    if not args:
        await update.message.reply_text(
            "⚠️ Usage : <code>/silver_bullet &lt;asset&gt;</code>\n"
            "Exemples : <code>/silver_bullet NQ</code> | <code>/silver_bullet GOLD</code> | "
            "<code>/silver_bullet EU</code>",
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
    window = _current_window(now_est)
    next_win = _next_window(now_est)

    # Send loading message
    msg = await update.message.reply_text(
        f"⚡ <b>Silver Bullet scan en cours...</b>\n"
        f"Asset : {_ASSET_EMOJI.get(asset_name,'📊')} <b>{asset_name}</b>\n"
        f"Heure EST : <code>{now_est.strftime('%H:%M:%S')}</code>",
        parse_mode="HTML",
    )

    try:
        loop = asyncio.get_event_loop()
        m1_df, m5_df = await loop.run_in_executor(None, _fetch_all_parallel, ticker)

        m1_bars = len(m1_df) if m1_df is not None else 0
        m5_bars = len(m5_df) if m5_df is not None else 0

        if m5_df is None or m5_bars < MIN_BARS_M5:
            await msg.edit_text(
                f"❌ Données M5 insuffisantes pour {asset_name} ({m5_bars} bars). "
                "Réessayez dans quelques secondes.",
                parse_mode="HTML",
            )
            return

        # Current price
        price = float(m5_df["Close"].iloc[-1])

        # Range pré-fenêtre
        bsl, ssl = None, None
        sweep = None
        mss = None
        fvg = None

        if window:
            h_start = window[0]
            bsl, ssl = _calc_pre_window_range(m5_df, h_start, now_est)

            if bsl is not None:
                # Extract candles INSIDE current window
                win_open = now_est.replace(hour=h_start, minute=0, second=0, microsecond=0)
                win_close = now_est.replace(hour=window[1], minute=0, second=0, microsecond=0)
                # Use M1 if available, else M5
                src_df = m1_df if (m1_df is not None and m1_bars >= MIN_BARS_M1) else m5_df
                seg = src_df[(src_df.index >= win_open) & (src_df.index <= now_est)].copy()

                if len(seg) >= 3:
                    # Pre-window swings for context
                    pre_m5 = m5_df[m5_df.index < win_open].tail(LOOKBACK_CANDLES)
                    swings_before = _find_swings(pre_m5, order=SWING_ORDER)

                    sweep = _detect_sweep(seg, bsl, ssl)
                    if sweep:
                        seg_reset = seg.reset_index(drop=False)
                        mss = _detect_mss(seg, sweep, swings_before)
                        if mss:
                            fvg = _detect_fvg_around_mss(seg, mss)

        report = _format_report(
            asset_name, now_est, window, next_win,
            price, bsl, ssl, sweep, mss, fvg,
            m1_bars, m5_bars,
        )
        await msg.edit_text(report, parse_mode="HTML")

    except Exception as e:
        log.exception("silver_bullet error for %s", asset_name)
        await msg.edit_text(
            f"❌ Erreur lors de l'analyse Silver Bullet : <code>{_esc(str(e))}</code>",
            parse_mode="HTML",
        )
