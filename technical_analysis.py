"""
technical_analysis.py – Structure de marché, divergences RSI, confluence.
Calculs purement algorithmiques, aucune clé API requise.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape as _esc
from typing import Optional


# ── Indicateurs de base ───────────────────────────────────────────────────────

def calc_rsi_series(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50.0)


def calc_macd(
    closes: pd.Series,
    fast: int = 8,
    slow: int = 13,
    signal: int = 5,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Retourne (macd_line, signal_line, histogram). Paramètres courts pour 25 bars."""
    ema_fast = closes.ewm(span=fast,   adjust=False).mean()
    ema_slow = closes.ewm(span=slow,   adjust=False).mean()
    macd     = ema_fast - ema_slow
    sig      = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig


# ── Swing points ──────────────────────────────────────────────────────────────

def find_swings(series: pd.Series, order: int = 3) -> tuple[list[int], list[int]]:
    """
    Détecte swing highs et swing lows.
    order = barres de confirmation de chaque côté.
    Retourne (high_indices, low_indices).
    """
    vals  = series.values
    n     = len(vals)
    highs, lows = [], []
    for i in range(order, n - order):
        window = vals[i - order: i + order + 1]
        if vals[i] == max(window):
            highs.append(i)
        if vals[i] == min(window):
            lows.append(i)
    return highs, lows


# ── Market Structure ──────────────────────────────────────────────────────────

@dataclass
class StructureResult:
    phase:       str            # "Uptrend" | "Downtrend" | "Ranging"
    bos:         Optional[str]  # "Bullish BOS" | "Bearish BOS" | None
    choch:       Optional[str]  # "CHoCH Haussier" | "CHoCH Baissier" | None
    last_high:   float
    last_low:    float
    swing_highs: list = field(default_factory=list)
    swing_lows:  list = field(default_factory=list)


def analyze_structure(closes: pd.Series) -> StructureResult:
    if len(closes) < 15:
        return StructureResult("Données insuffisantes", None, None, 0.0, 0.0)

    hi_idx, lo_idx = find_swings(closes, order=3)

    swing_highs = [float(closes.iloc[i]) for i in hi_idx[-6:]]
    swing_lows  = [float(closes.iloc[i]) for i in lo_idx[-6:]]

    last_high = swing_highs[-1] if swing_highs else float(closes.max())
    last_low  = swing_lows[-1]  if swing_lows  else float(closes.min())

    phase = "Ranging"
    bos   = None
    choch = None

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1] > swing_highs[-2]
        lh = swing_highs[-1] < swing_highs[-2]
        hl = swing_lows[-1]  > swing_lows[-2]
        ll = swing_lows[-1]  < swing_lows[-2]

        if hh and hl:
            phase = "Uptrend"
        elif lh and ll:
            phase = "Downtrend"
        # else Ranging

        # BOS : cassure de la structure précédente
        current = float(closes.iloc[-1])
        if len(swing_highs) >= 2 and current > swing_highs[-2] and phase != "Uptrend":
            bos = "Bullish BOS"
        elif len(swing_lows) >= 2 and current < swing_lows[-2] and phase != "Downtrend":
            bos = "Bearish BOS"

        # CHoCH : premier signe de retournement dans une tendance établie
        if len(swing_highs) >= 3 and len(swing_lows) >= 3:
            if phase == "Uptrend" and swing_lows[-1] < swing_lows[-2]:
                choch = "CHoCH Baissier"
            elif phase == "Downtrend" and swing_highs[-1] > swing_highs[-2]:
                choch = "CHoCH Haussier"

    return StructureResult(
        phase=phase, bos=bos, choch=choch,
        last_high=last_high, last_low=last_low,
        swing_highs=swing_highs, swing_lows=swing_lows,
    )


def _phase_line(phase: str) -> str:
    if phase == "Uptrend":
        return "📈 <b>Uptrend</b> — HH + HL confirmés"
    if phase == "Downtrend":
        return "📉 <b>Downtrend</b> — LH + LL confirmés"
    return "➡️ <b>Ranging</b> — pas de tendance claire"


# ── Divergence RSI ────────────────────────────────────────────────────────────

@dataclass
class DivergenceResult:
    regular_bullish: bool = False
    regular_bearish: bool = False
    hidden_bullish:  bool = False
    hidden_bearish:  bool = False

    def has_any(self) -> bool:
        return any([
            self.regular_bullish, self.regular_bearish,
            self.hidden_bullish,  self.hidden_bearish,
        ])

    def lines(self) -> list[str]:
        out = []
        if self.regular_bullish:
            out.append("🟢 <b>Div. Haussière Régulière</b> — prix LL, RSI HL → retournement potentiel")
        if self.regular_bearish:
            out.append("🔴 <b>Div. Baissière Régulière</b> — prix HH, RSI LH → retournement potentiel")
        if self.hidden_bullish:
            out.append("🟡 <b>Div. Haussière Cachée</b> — prix HL, RSI LL → continuation haussière")
        if self.hidden_bearish:
            out.append("🟠 <b>Div. Baissière Cachée</b> — prix LH, RSI HH → continuation baissière")
        return out


def detect_divergence(closes: pd.Series) -> DivergenceResult:
    if len(closes) < 15:
        return DivergenceResult()

    rsi    = calc_rsi_series(closes)
    hi_idx, lo_idx = find_swings(closes, order=3)
    result = DivergenceResult()

    # Sur les swing highs
    if len(hi_idx) >= 2:
        i1, i2 = hi_idx[-2], hi_idx[-1]
        p1, p2 = float(closes.iloc[i1]), float(closes.iloc[i2])
        r1, r2 = float(rsi.iloc[i1]),    float(rsi.iloc[i2])
        if p2 > p1 and r2 < r1 - 2:      # prix HH, RSI LH → bearish regular
            result.regular_bearish = True
        if p2 < p1 and r2 > r1 + 2:      # prix LH, RSI HH → bearish hidden
            result.hidden_bearish = True

    # Sur les swing lows
    if len(lo_idx) >= 2:
        i1, i2 = lo_idx[-2], lo_idx[-1]
        p1, p2 = float(closes.iloc[i1]), float(closes.iloc[i2])
        r1, r2 = float(rsi.iloc[i1]),    float(rsi.iloc[i2])
        if p2 < p1 and r2 > r1 + 2:      # prix LL, RSI HL → bullish regular
            result.regular_bullish = True
        if p2 > p1 and r2 < r1 - 2:      # prix HL, RSI LL → bullish hidden
            result.hidden_bullish = True

    return result


# ── Confluence ────────────────────────────────────────────────────────────────

@dataclass
class ConfluenceResult:
    score:    int
    grade:    str
    bias:     str        # "Long" | "Short" | "Neutre"
    signals:  list[str]
    warnings: list[str]


def calc_confluence(
    asset_data: dict,
    structure:  StructureResult,
    divergence: DivergenceResult,
    macd_hist:  Optional[float] = None,
) -> ConfluenceResult:
    score    = 0
    signals  = []
    warnings = []

    trend_h4   = asset_data.get("trend_h4", "neutral")
    trend_h1   = asset_data.get("trend_h1", "neutral")
    rsi        = asset_data.get("rsi", 50.0)
    price      = asset_data.get("price", 0.0)
    support    = asset_data.get("support", 0.0)
    resistance = asset_data.get("resistance", 0.0)

    # 1. Trends H4 + H1 alignés (max +2)
    if trend_h4 == "bullish" and trend_h1 == "bullish":
        score += 2
        signals.append("✅ H4 + H1 Bullish alignés <b>(+2)</b>")
    elif trend_h4 == "bearish" and trend_h1 == "bearish":
        score += 2
        signals.append("✅ H4 + H1 Bearish alignés <b>(+2)</b>")
    elif trend_h4 == "bullish":
        score += 1
        signals.append("🟡 H4 Bullish, H1 mixte <b>(+1)</b>")
    elif trend_h4 == "bearish":
        score += 1
        signals.append("🟡 H4 Bearish, H1 mixte <b>(+1)</b>")

    # 2. Structure alignée (max +2)
    if structure.phase == "Uptrend" and trend_h4 == "bullish":
        score += 2
        signals.append("✅ Structure Uptrend + H4 Bullish <b>(+2)</b>")
    elif structure.phase == "Downtrend" and trend_h4 == "bearish":
        score += 2
        signals.append("✅ Structure Downtrend + H4 Bearish <b>(+2)</b>")
    elif structure.bos == "Bullish BOS":
        score += 1
        signals.append("🟡 Bullish BOS détecté <b>(+1)</b>")
    elif structure.bos == "Bearish BOS":
        score += 1
        signals.append("🟡 Bearish BOS détecté <b>(+1)</b>")

    # 3. RSI en zone favorable (+1)
    if trend_h4 == "bullish" and 40 <= rsi <= 65:
        score += 1
        signals.append(f"✅ RSI {rsi:.0f} zone haussière saine <b>(+1)</b>")
    elif trend_h4 == "bearish" and 35 <= rsi <= 60:
        score += 1
        signals.append(f"✅ RSI {rsi:.0f} zone baissière saine <b>(+1)</b>")
    elif rsi >= 72:
        warnings.append(f"⚠️ RSI {rsi:.0f} — surachat, éviter long")
    elif rsi <= 28:
        warnings.append(f"⚠️ RSI {rsi:.0f} — survente, éviter short")

    # 4. Divergence confirmante (+1) ou contre-tendance (warning)
    if divergence.regular_bullish and trend_h4 == "bullish":
        score += 1
        signals.append("✅ Divergence haussière confirmée <b>(+1)</b>")
    elif divergence.hidden_bullish and trend_h4 == "bullish":
        score += 1
        signals.append("✅ Div. cachée haussière (continuation) <b>(+1)</b>")
    elif divergence.regular_bearish and trend_h4 == "bearish":
        score += 1
        signals.append("✅ Divergence baissière confirmée <b>(+1)</b>")
    elif divergence.hidden_bearish and trend_h4 == "bearish":
        score += 1
        signals.append("✅ Div. cachée baissière (continuation) <b>(+1)</b>")
    elif divergence.regular_bearish and trend_h4 == "bullish":
        warnings.append("⚠️ Divergence baissière contre-tendance — prudence")
    elif divergence.regular_bullish and trend_h4 == "bearish":
        warnings.append("⚠️ Divergence haussière contre-tendance — prudence")

    # 5. MACD aligné (+1)
    if macd_hist is not None:
        if macd_hist > 0 and trend_h4 == "bullish":
            score += 1
            signals.append("✅ MACD histogramme positif <b>(+1)</b>")
        elif macd_hist < 0 and trend_h4 == "bearish":
            score += 1
            signals.append("✅ MACD histogramme négatif <b>(+1)</b>")

    # 6. Niveau de prix (proche support en long / résistance en short)
    if resistance > support > 0:
        rng      = resistance - support
        dist_sup = (price - support)    / rng * 100
        dist_res = (resistance - price) / rng * 100
        if trend_h4 == "bullish" and dist_sup < 10:
            score += 1
            signals.append("✅ Prix proche du support (+1)")
        elif trend_h4 == "bearish" and dist_res < 10:
            score += 1
            signals.append("✅ Prix proche de la résistance (+1)")
        if dist_res < 5:
            warnings.append("⚠️ Très proche résistance — risque de rejet")
        elif dist_sup < 5:
            warnings.append("⚠️ Très proche support — surveiller le rebond")

    # CHoCH warning
    if structure.choch:
        warnings.append(f"⚠️ {structure.choch} — surveiller retournement")

    # Grade
    if score >= 8:
        grade = "A — Signal fort"
    elif score >= 6:
        grade = "B — Signal valide"
    elif score >= 4:
        grade = "C — Signal faible"
    elif score >= 2:
        grade = "D — Trop risqué"
    else:
        grade = "F — Ne pas trader"

    # Bias
    if score >= 4 and trend_h4 == "bullish":
        bias = "Long"
    elif score >= 4 and trend_h4 == "bearish":
        bias = "Short"
    else:
        bias = "Neutre"

    return ConfluenceResult(score=score, grade=grade, bias=bias, signals=signals, warnings=warnings)


# ── Formatage HTML ────────────────────────────────────────────────────────────

GROUPS = [
    ("💱 FOREX",    ["EUR/USD", "USD/CAD", "GBP/USD", "USD/JPY"]),
    ("📈 INDICES",  ["NAS100", "US500"]),
    ("🖥️ ACTIONS", ["NVDA"]),
]


def format_structure_message(assets_data: dict) -> str:
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "📊 <b>MARKET STRUCTURE</b>",
        f"🕒 <i>{now}</i>",
        "═" * 32,
        "",
    ]

    for group_title, names in GROUPS:
        lines.append(f"<b>{group_title}</b>")
        lines.append("─" * 28)
        for name in names:
            d = assets_data.get(name, {})
            if d.get("error") or "closes" not in d:
                lines.append(f"• <b>{_esc(name)}</b> — données indisponibles")
                lines.append("")
                continue

            from market_data import format_price
            price_str = format_price(d["price"], name)
            struct    = analyze_structure(d["closes"])

            lines.append(f"• <b>{_esc(name)}</b>  <code>{price_str}</code>")
            lines.append(f"  {_phase_line(struct.phase)}")

            if struct.swing_highs and struct.swing_lows:
                from market_data import format_price as _fp
                sh = _fp(struct.last_high, name)
                sl = _fp(struct.last_low,  name)
                lines.append(f"  Dernier swing H: <code>{sh}</code>  L: <code>{sl}</code>")

            if struct.bos:
                emoji = "📈" if "Bullish" in struct.bos else "📉"
                lines.append(f"  {emoji} <b>{_esc(struct.bos)}</b> — cassure de structure")
            if struct.choch:
                lines.append(f"  ⚠️ <b>{_esc(struct.choch)}</b> — possible retournement")
            lines.append("")
        lines.append("")

    lines += ["═" * 32, "⚡ <b>tradingLIVE</b> | /divergence | /confluence | /deep"]
    return "\n".join(lines)


def format_divergence_message(assets_data: dict) -> str:
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "🔀 <b>DIVERGENCES RSI</b>",
        f"🕒 <i>{now}</i>",
        "═" * 32,
        "",
    ]

    for group_title, names in GROUPS:
        lines.append(f"<b>{group_title}</b>")
        lines.append("─" * 28)
        for name in names:
            d = assets_data.get(name, {})
            if d.get("error") or "closes" not in d:
                lines.append(f"• <b>{_esc(name)}</b> — données indisponibles")
                lines.append("")
                continue

            div = detect_divergence(d["closes"])
            lines.append(f"• <b>{_esc(name)}</b>  RSI: {d['rsi']}")

            if div.has_any():
                for line in div.lines():
                    lines.append(f"  {line}")
            else:
                lines.append("  ✅ Aucune divergence détectée")
            lines.append("")
        lines.append("")

    lines += ["═" * 32, "⚡ <b>tradingLIVE</b> | /structure | /confluence | /deep"]
    return "\n".join(lines)


def format_confluence_message(assets_data: dict) -> str:
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "🎯 <b>CONFLUENCE SCORE</b>",
        f"🕒 <i>{now}</i>",
        "═" * 32,
        "",
    ]

    for group_title, names in GROUPS:
        lines.append(f"<b>{group_title}</b>")
        lines.append("─" * 28)
        for name in names:
            d = assets_data.get(name, {})
            if d.get("error") or "closes" not in d:
                lines.append(f"• <b>{_esc(name)}</b> — données indisponibles")
                lines.append("")
                continue

            closes    = d["closes"]
            struct    = analyze_structure(closes)
            div       = detect_divergence(closes)
            _, _, hist = calc_macd(closes)
            macd_hist  = float(hist.iloc[-1]) if not hist.empty and not np.isnan(hist.iloc[-1]) else None

            conf = calc_confluence(d, struct, div, macd_hist)

            bias_icon = "📈" if conf.bias == "Long" else ("📉" if conf.bias == "Short" else "➡️")
            score_bar = "█" * conf.score + "░" * (10 - conf.score)
            lines.append(
                f"• <b>{_esc(name)}</b>  {bias_icon} {conf.bias}  "
                f"<b>{conf.score}/10</b>  <code>{score_bar}</code>"
            )
            lines.append(f"  <i>{_esc(conf.grade)}</i>")
            for sig in conf.signals:
                lines.append(f"  {sig}")
            for warn in conf.warnings:
                lines.append(f"  {warn}")
            lines.append("")
        lines.append("")

    lines += ["═" * 32, "⚡ <b>tradingLIVE</b> | /risk-calc | /structure | /deep"]
    return "\n".join(lines)
