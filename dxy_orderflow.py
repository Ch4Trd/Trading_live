"""
dxy_orderflow.py
Commande /dxy_orderflow — Analyse mécanique de l'Orderflow du Dollar Index.

Logique SMC / ICT stricte :
  ─ BOS détecté uniquement via CLÔTURE du corps (pas les mèches)
  ─ State machine : Bullish / Bearish / Consolidation
  ─ FVG : gap mèche-à-mèche candle[i-2] ↔ candle[i], filtré si comblé
  ─ PDH / PDL : session précédente complète (external liquidity)
  ─ Biais contrarien : corrélation DXY ↔ NQ/ES/FX

Ticker : DX-Y.NYB (Yahoo Finance — DXY Cash Index)
Timeframes : H4 (macro), M15 (intraday)
"""

import asyncio
import logging
from datetime import datetime, timezone
from html import escape as _esc
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from subscription import subscription_manager

log = logging.getLogger(__name__)

DXY_TICKER = "DX-Y.NYB"

# Nombre minimum de bougies pour que l'analyse soit valide
MIN_BARS_H4  = 30
MIN_BARS_M15 = 40


# ── 1. Fetch OHLCV ────────────────────────────────────────────────────────────

def _fetch(interval: str, period: str) -> Optional[pd.DataFrame]:
    """Fetch OHLCV DXY. Retourne None si données insuffisantes."""
    try:
        df = yf.Ticker(DXY_TICKER).history(period=period, interval=interval)
        if df.empty:
            return None
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        return df if not df.empty else None
    except Exception as exc:
        log.warning("dxy_orderflow fetch [%s %s]: %s", interval, period, exc)
        return None


def _fetch_all() -> dict:
    """Fetch H4, M15 et Daily en parallèle (threads)."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_h4    = pool.submit(_fetch, "4h",  "60d")
        f_m15   = pool.submit(_fetch, "15m", "5d")
        f_daily = pool.submit(_fetch, "1d",  "15d")
        return {
            "h4":    f_h4.result(),
            "m15":   f_m15.result(),
            "daily": f_daily.result(),
        }


# ── 2. Détection des Swing Points ─────────────────────────────────────────────

def _find_swings(df: pd.DataFrame, order: int) -> tuple[list, list]:
    """
    Retourne (swing_highs, swing_lows) sous forme de listes de (bar_index, price).
    Un swing high est confirmé si son High est strictement ≥ aux `order` bougies
    de chaque côté. Idem pour les swing lows.
    """
    highs = df["High"].values
    lows  = df["Low"].values
    n     = len(df)
    sh, sl = [], []

    for i in range(order, n - order):
        h_win = highs[i - order: i + order + 1]
        l_win = lows[i - order:  i + order + 1]
        if highs[i] >= max(h_win):
            sh.append((i, float(highs[i])))
        if lows[i] <= min(l_win):
            sl.append((i, float(lows[i])))

    return sh, sl


# ── 3. Break of Structure (BOS) — corps strict ────────────────────────────────

def _detect_bos(df: pd.DataFrame, order: int) -> dict:
    """
    Scanne le DataFrame et retourne le DERNIER BOS confirmé.

    Règles ICT/SMC strictes :
      Bullish BOS : close[i] > swing_high le plus récent avant i
      Bearish BOS : close[i] < swing_low  le plus récent avant i

    La clôture du CORPS est utilisée (pas les mèches haute/basse).
    Retourne : {"type": "bullish"|"bearish"|"consolidation",
                "price": float|None, "time": Timestamp|None}
    """
    empty = {"type": "consolidation", "price": None, "time": None}
    n     = len(df)
    if n < order * 2 + 6:
        return empty

    closes = df["Close"].values
    sh_list, sl_list = _find_swings(df, order)

    last_bos = empty.copy()

    for i in range(order + 1, n):
        close = closes[i]

        prev_sh = [(idx, p) for idx, p in sh_list if idx < i]
        prev_sl = [(idx, p) for idx, p in sl_list if idx < i]
        if not prev_sh or not prev_sl:
            continue

        # Swing le plus récent avant la bougie i
        sh_idx, sh_price = max(prev_sh, key=lambda x: x[0])
        sl_idx, sl_price = max(prev_sl, key=lambda x: x[0])

        if close > sh_price:
            last_bos = {
                "type":  "bullish",
                "price": round(sh_price, 3),
                "time":  df.index[i],
            }
        elif close < sl_price:
            last_bos = {
                "type":  "bearish",
                "price": round(sl_price, 3),
                "time":  df.index[i],
            }
        # Si aucun break → on conserve le dernier état (state machine)

    return last_bos


# ── 4. Fair Value Gap (FVG) — dernier ouvert ─────────────────────────────────

def _detect_last_open_fvg(df: pd.DataFrame, min_gap_pct: float = 0.0003) -> Optional[dict]:
    """
    FVG = imbalance entre la MÈCHE haute de candle[i-2] et la MÈCHE basse de candle[i].

    Bullish FVG : High[i-2] < Low[i]   → gap haussier non comblé
    Bearish FVG : Low[i-2]  > High[i]  → gap baissier non comblé

    "Ouvert" = aucune bougie postérieure n'a tradé DANS la zone.
    Retourne le plus récent FVG encore ouvert, ou None.
    """
    df = df.reset_index(drop=True)
    n  = len(df)
    if n < 5:
        return None

    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values

    current_price = float(closes[-1])
    min_gap       = current_price * min_gap_pct

    fvgs = []
    for i in range(2, n):
        h2 = highs[i - 2]
        l2 = lows[i - 2]
        h0 = highs[i]
        l0 = lows[i]

        if h2 < l0 and (l0 - h2) >= min_gap:   # Bullish FVG
            fvgs.append({"type": "bullish", "bottom": round(h2, 3), "top": round(l0, 3), "bar": i})
        elif l2 > h0 and (l2 - h0) >= min_gap:  # Bearish FVG
            fvgs.append({"type": "bearish", "bottom": round(h0, 3), "top": round(l2, 3), "bar": i})

    # Filtrer les FVG comblés (price traded through the zone)
    open_fvgs = []
    for fvg in fvgs:
        bar    = fvg["bar"]
        filled = False
        for j in range(bar + 1, n):
            if fvg["type"] == "bullish":
                # Comblé si une bougie descend sous le bas du gap
                if lows[j] <= fvg["bottom"]:
                    filled = True
                    break
            else:
                # Comblé si une bougie monte au-dessus du haut du gap
                if highs[j] >= fvg["top"]:
                    filled = True
                    break
        if not filled:
            open_fvgs.append(fvg)

    return open_fvgs[-1] if open_fvgs else None


# ── 5. PDH / PDL (Previous Day High / Low) ───────────────────────────────────

def _get_pdh_pdl(daily_df: pd.DataFrame) -> dict:
    """
    PDH = plus haut de la session journalière précédente (complète).
    PDL = plus bas de la session journalière précédente (complète).

    On prend l'avant-dernière bougie quotidienne, qui est toujours la
    dernière session complète, quelle que soit l'heure actuelle.
    """
    if daily_df is None or len(daily_df) < 2:
        return {"pdh": None, "pdl": None, "date": None}

    # L'avant-dernière barre = session précédente complète
    prev = daily_df.iloc[-2]
    return {
        "pdh":  round(float(prev["High"]), 3),
        "pdl":  round(float(prev["Low"]),  3),
        "date": daily_df.index[-2].strftime("%Y-%m-%d"),
    }


# ── 6. Biais contrarien DXY ↔ Indices / FX ───────────────────────────────────

def _compute_bias(bos_h4: dict, bos_m15: dict) -> str:
    """
    Matrice de corrélation DXY ↔ NQ/ES/FX.

    DXY BULLISH (les deux TF) → indices FORTEMENT BEARISH
    DXY BEARISH (les deux TF) → indices FORTEMENT BULLISH
    Divergence H4 / M15       → setup en cours de construction
    Consolidation             → attendre confirmation
    """
    h4  = bos_h4.get("type", "consolidation")
    m15 = bos_m15.get("type", "consolidation")

    # Cas alignés — signal fort
    if h4 == "bullish" and m15 == "bullish":
        return (
            "⚠️ <b>DXY H4 BULLISH + M15 BULLISH — Signal fort</b>\n\n"
            "📉 Biais fortement <b>BEARISH</b> sur les indices <b>(NQ / ES)</b>.\n"
            "   Les acheteurs d'indices risquent de se retrouver piégés dans des <b>Bull Traps</b>.\n"
            "   Privilégier les setups de vente sur rejets de résistance.\n\n"
            "💵 <b>Forex :</b> USD offensif — <code>EUR/USD</code> & <code>GBP/USD</code> sous pression.\n"
            "   Biais <b>BULLISH</b> sur <code>USD/JPY</code> et <code>USD/CAD</code>.\n"
            "🥇 <b>Or :</b> Pression baissière — USD fort compresse <code>XAU/USD</code>."
        )

    if h4 == "bearish" and m15 == "bearish":
        return (
            "✅ <b>DXY H4 BEARISH + M15 BEARISH — Signal fort</b>\n\n"
            "📈 Biais fortement <b>BULLISH</b> sur les indices <b>(NQ / ES)</b>.\n"
            "   Setups d'achat sur pullbacks vers supports / FVG Bullish favorisés.\n\n"
            "💵 <b>Forex :</b> USD en distribution — <code>EUR/USD</code> & <code>GBP/USD</code> bien orientés.\n"
            "   Biais <b>BEARISH</b> sur <code>USD/JPY</code> et <code>USD/CAD</code>.\n"
            "🥇 <b>Or :</b> USD faible → tailwind haussier sur <code>XAU/USD</code>."
        )

    # Divergence — setup en construction
    if h4 == "bullish" and m15 == "bearish":
        return (
            "🔄 <b>Divergence : DXY H4 BULLISH / M15 BEARISH</b>\n\n"
            "Structure macro favorable au dollar mais DXY consolide intraday.\n"
            "   → Le M15 est probablement en train de <b>former un retracement</b> "
            "avant de reprendre la direction H4.\n\n"
            "📉 Biais <b>BEARISH modéré</b> sur indices — attendre confirmation M15 bullish.\n"
            "⏳ Stratégie : surveiller un BOS M15 haussier sur DXY pour valider le setup short indices."
        )

    if h4 == "bearish" and m15 == "bullish":
        return (
            "🔄 <b>Divergence : DXY H4 BEARISH / M15 BULLISH</b>\n\n"
            "Structure macro bearish sur le dollar mais DXY rebondit intraday.\n"
            "   → Le M15 est probablement en train de <b>purger la liquidité haute</b> "
            "avant de reprendre la distribution H4.\n\n"
            "📈 Biais <b>BULLISH modéré</b> sur indices — attendre confirmation M15 bearish sur DXY.\n"
            "⏳ Stratégie : surveiller un BOS M15 baissier sur DXY pour valider le setup long indices."
        )

    # Consolidation — pas de signal
    return (
        "⏸ <b>DXY en CONSOLIDATION — Pas de biais directionnel clair</b>\n\n"
        "Aucun Break of Structure récent confirmé sur H4 ou M15.\n"
        "   → Le marché accumule probablement de la liquidité avant un mouvement.\n\n"
        "🎯 Action : attendre un BOS confirmé par le <b>corps</b> d'une bougie H4.\n"
        "   Surveiller les niveaux PDH / PDL et FVG comme déclencheurs potentiels."
    )


# ── 7. Formatage du message Telegram ──────────────────────────────────────────

def _format_message(
    price:   float,
    bos_h4:  dict,
    bos_m15: dict,
    fvg:     Optional[dict],
    pdh_pdl: dict,
) -> str:
    """
    Génère le rapport Telegram structuré en HTML (équivalent Markdown Premium).
    """
    now_s = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Header ──────────────────────────────────────────────────────────────
    lines = [
        "📊 <b>FLUX DE LIQUIDITÉ — DOLLAR INDEX (DXY)</b>",
        f"🕒 <i>{now_s}</i>  |  Prix: <code>{price:.3f}</code>",
        "━" * 34,
        "",
    ]

    # ── Orderflow H4 ────────────────────────────────────────────────────────
    h4_type  = bos_h4["type"]
    h4_emoji = "📈" if h4_type == "bullish" else ("📉" if h4_type == "bearish" else "➡️")
    h4_label = h4_type.upper()
    h4_price = f"  <i>(Dernier BOS à <code>{bos_h4['price']}</code>)</i>" if bos_h4["price"] else ""

    lines.append(f"• <b>Orderflow Macro (H4) :</b> {h4_emoji} <b>{h4_label}</b>{h4_price}")

    # ── Structure M15 ───────────────────────────────────────────────────────
    m15_type  = bos_m15["type"]
    m15_emoji = "📈" if m15_type == "bullish" else ("📉" if m15_type == "bearish" else "➡️")
    m15_label = m15_type.upper()
    m15_price = f"  <i>(Dernier BOS à <code>{bos_m15['price']}</code>)</i>" if bos_m15["price"] else ""

    lines += [
        f"• <b>Structure Intraday (M15) :</b> {m15_emoji} <b>{m15_label}</b>{m15_price}",
        "",
        "─" * 34,
        "",
        "⚡ <b>ZONES ALGORITHMIQUES PROCHES (M15)</b>",
        "",
    ]

    # ── FVG ─────────────────────────────────────────────────────────────────
    if fvg:
        fvg_emoji = "🟢" if fvg["type"] == "bullish" else "🔴"
        fvg_dir   = "Bullish" if fvg["type"] == "bullish" else "Bearish"
        lines.append(
            f"• <b>Dernier FVG Ouvert :</b> {fvg_emoji} {fvg_dir} "
            f"<code>{fvg['bottom']:.3f}</code> — <code>{fvg['top']:.3f}</code>"
            f"  <i>(taille: {(fvg['top']-fvg['bottom']):.3f})</i>"
        )
    else:
        lines.append("• <b>Dernier FVG Ouvert :</b> ✅ Aucun FVG M15 non comblé détecté")

    # ── PDH / PDL ────────────────────────────────────────────────────────────
    if pdh_pdl["pdh"] is not None:
        lines += [
            f"• <b>Liquidité Externe Haute (BSL/PDH) :</b> <code>{pdh_pdl['pdh']:.3f}</code>"
            f"  <i>({pdh_pdl['date']})</i>",
            f"• <b>Liquidité Externe Basse (SSL/PDL) :</b> <code>{pdh_pdl['pdl']:.3f}</code>"
            f"  <i>({pdh_pdl['date']})</i>",
        ]
    else:
        lines.append("• <b>PDH / PDL :</b> Données journalières insuffisantes")

    # Distance prix / niveaux
    if pdh_pdl["pdh"]:
        dist_pdh = abs(price - pdh_pdl["pdh"])
        dist_pdl = abs(price - pdh_pdl["pdl"])
        lines.append(
            f"\n<i>Distance actuelle → PDH: {dist_pdh:.3f}  |  PDL: {dist_pdl:.3f}</i>"
        )

    # ── Biais contrarien ─────────────────────────────────────────────────────
    bias_text = _compute_bias(bos_h4, bos_m15)
    lines += [
        "",
        "─" * 34,
        "",
        "🎯 <b>BIAIS CONTRARIEN — INDICES (NQ / ES) &amp; FX</b>",
        "",
        bias_text,
        "",
        "━" * 34,
        "⚡ <b>tradingLIVE</b> | /analyze NQ | /analyze GOLD | /vix | /deep",
    ]

    return "\n".join(lines)


# ── 8. Handler Telegram ───────────────────────────────────────────────────────

async def cmd_dxy_orderflow(update, ctx) -> None:
    """
    Handler /dxy_orderflow.
    Analyse mécanique SMC/ICT du Dollar Index sur H4 et M15.
    """
    user_id = update.effective_user.id
    if not subscription_manager.is_user_active(user_id):
        await update.message.reply_text(
            "❌ <b>Subscription requise</b>", parse_mode="HTML"
        )
        return

    msg = await update.message.reply_text(
        "<i>🔍 Analyse Orderflow DXY (H4 + M15)… (~10s)</i>",
        parse_mode="HTML",
    )

    loop = asyncio.get_running_loop()

    try:
        data = await loop.run_in_executor(None, _fetch_all)

        h4_df    = data["h4"]
        m15_df   = data["m15"]
        daily_df = data["daily"]

        # ── Validation des données ──────────────────────────────────────────
        errors = []
        if h4_df is None or len(h4_df) < MIN_BARS_H4:
            errors.append(f"H4 : {len(h4_df) if h4_df is not None else 0} bougies (min {MIN_BARS_H4})")
        if m15_df is None or len(m15_df) < MIN_BARS_M15:
            errors.append(f"M15 : {len(m15_df) if m15_df is not None else 0} bougies (min {MIN_BARS_M15})")

        if errors:
            await msg.delete()
            await update.message.reply_text(
                "❌ <b>Données insuffisantes pour l'analyse :</b>\n"
                + "\n".join(f"• {e}" for e in errors)
                + "\n\n<i>Réessaie dans quelques secondes — API Yahoo Finance momentanément limitée.</i>",
                parse_mode="HTML",
            )
            return

        # ── Calculs ──────────────────────────────────────────────────────────
        price   = round(float(m15_df["Close"].iloc[-1]), 3)
        bos_h4  = _detect_bos(h4_df,  order=3)   # H4 : confirmation sur 3 bougies
        bos_m15 = _detect_bos(m15_df, order=2)   # M15 : confirmation sur 2 bougies
        fvg     = _detect_last_open_fvg(m15_df)
        pdh_pdl = _get_pdh_pdl(daily_df)

        # ── Formatage + envoi ─────────────────────────────────────────────────
        report = _format_message(price, bos_h4, bos_m15, fvg, pdh_pdl)

        await msg.delete()
        from formatter import _split_message
        for part in _split_message(report):
            await update.message.reply_text(
                part, parse_mode="HTML", disable_web_page_preview=True
            )

    except Exception as exc:
        log.error("cmd_dxy_orderflow error: %s", exc, exc_info=True)
        try:
            await msg.delete()
        except Exception:
            pass
        from html import escape
        await update.message.reply_text(
            f"❌ Erreur : <code>{escape(str(exc))}</code>",
            parse_mode="HTML",
        )
