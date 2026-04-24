"""
algo_analyst.py – Analyse de marché algorithmique sans IA.
RSI, tendances SMA, corrélations, support/résistance, biais directionnel.
Aucune clé API requise.
"""

import numpy as np
from datetime import datetime, timezone
from html import escape as _esc


# ── RSI signals ───────────────────────────────────────────────────────────────

def rsi_signal(rsi: float) -> tuple[str, str]:
    if rsi >= 75:
        return "⚠️ Surachat extrême", "baissier"
    if rsi >= 70:
        return "🔴 Surachat", "baissier"
    if rsi >= 60:
        return "🟡 Zone haute", "neutre-haussier"
    if rsi >= 45:
        return "🟢 Zone neutre haute", "haussier"
    if rsi >= 35:
        return "🟡 Zone neutre basse", "neutre-baissier"
    if rsi >= 30:
        return "🔴 Survente", "haussier"
    return "⚠️ Survente extrême", "haussier"


def bias_icon(bias: str) -> str:
    if "haussier" in bias.lower():
        return "📈"
    if "baissier" in bias.lower():
        return "📉"
    return "➡️"


# ── single asset analysis ─────────────────────────────────────────────────────

def _trend_label(trend: str) -> tuple[str, str]:
    """Retourne (icône+label, bias) pour un trend H4 ou H1."""
    if trend == "bullish":
        return "📈 Bullish", "haussier"
    if trend == "bearish":
        return "📉 Bearish", "baissier"
    return "➡️ Neutre", "neutre"


def analyze_asset(name: str, d: dict) -> dict:
    if d.get("error"):
        return {"name": name, "error": True}

    rsi        = d["rsi"]
    trend_h4   = d.get("trend_h4", d.get("trend", "neutral"))
    trend_h1   = d.get("trend_h1", "neutral")
    chg1       = d["change_1d"]
    chg7       = d["change_7d"]
    chg30      = d["change_30d"]
    price      = d["price"]
    support    = d["support"]
    resistance = d["resistance"]

    rsi_label, rsi_bias = rsi_signal(rsi)

    h4_label, h4_bias = _trend_label(trend_h4)
    h1_label, h1_bias = _trend_label(trend_h1)

    # Momentum bias from price changes
    score = sum([chg1 > 0, chg7 > 0, chg30 > 0])
    momentum_bias = "haussier" if score >= 2 else "baissier"

    # Biais final : H4 + RSI + momentum (H1 en confirmation seulement)
    biases = [h4_bias, rsi_bias.replace("neutre-", ""), momentum_bias]
    bull   = biases.count("haussier")
    bear   = biases.count("baissier")
    final_bias = "Haussier" if bull > bear else ("Baissier" if bear > bull else "Neutre")

    # Distance to support/resistance
    range_size    = resistance - support
    dist_sup      = ((price - support)    / range_size * 100) if range_size > 0 else 50
    dist_res      = ((resistance - price) / range_size * 100) if range_size > 0 else 50
    level_warning = ""
    if dist_res < 5:
        level_warning = "⚠️ Proche résistance — risque de rejet"
    elif dist_sup < 5:
        level_warning = "⚠️ Proche support — surveiller le rebond"
    elif dist_res < 15:
        level_warning = "🎯 Zone de résistance proche"

    return {
        "name":          name,
        "rsi_label":     rsi_label,
        "h4_label":      h4_label,
        "h1_label":      h1_label,
        "final_bias":    final_bias,
        "level_warning": level_warning,
        "dist_sup_pct":  dist_sup,
        "dist_res_pct":  dist_res,
        "error":         False,
    }


# ── correlation analysis ──────────────────────────────────────────────────────

def analyze_correlations(corr_df) -> list[dict]:
    import pandas as pd
    assets  = list(corr_df.columns)
    pairs   = []

    for i, a in enumerate(assets):
        for j, b in enumerate(assets):
            if j <= i:
                continue
            val = corr_df.loc[a, b]
            if np.isnan(val):
                continue

            if val >= 0.85:
                label = "🔴 Très forte positive"
                desc  = f"{a} et {b} évoluent quasi ensemble — diversification faible"
            elif val >= 0.60:
                label = "🟠 Forte positive"
                desc  = f"{a} et {b} tendent à monter/baisser ensemble"
            elif val >= 0.30:
                label = "🟡 Modérée positive"
                desc  = f"{a} et {b} légèrement liés"
            elif val >= -0.30:
                label = "⚪ Neutre"
                desc  = f"{a} et {b} évoluent indépendamment"
            elif val >= -0.60:
                label = "🟡 Modérée négative"
                desc  = f"{a} et {b} légèrement opposés"
            elif val >= -0.85:
                label = "🟠 Forte négative"
                desc  = f"{a} et {b} tendent à évoluer en sens inverse"
            else:
                label = "🔴 Très forte négative"
                desc  = f"{a} et {b} évoluent quasi en miroir"

            pairs.append({
                "a":     a,
                "b":     b,
                "val":   val,
                "label": label,
                "desc":  desc,
            })

    pairs.sort(key=lambda p: abs(p["val"]), reverse=True)
    return pairs


# ── macro overview ────────────────────────────────────────────────────────────

def macro_overview(assets_data: dict) -> str:
    bull_count  = sum(1 for d in assets_data.values() if not d.get("error") and d.get("trend_h4") == "bullish")
    bear_count  = sum(1 for d in assets_data.values() if not d.get("error") and d.get("trend_h4") == "bearish")
    total       = bull_count + bear_count

    avg_chg1 = np.mean([
        d["change_1d"] for d in assets_data.values()
        if not d.get("error")
    ])

    if bull_count > bear_count:
        sentiment = "🟢 Risk-ON dominant"
        detail    = f"{bull_count}/{total} actifs en tendance haussière"
    elif bear_count > bull_count:
        sentiment = "🔴 Risk-OFF dominant"
        detail    = f"{bear_count}/{total} actifs en tendance baissière"
    else:
        sentiment = "🟡 Marché indécis"
        detail    = "Sentiment mixte, pas de direction claire"

    perf = f"Performance moyenne 24h : {avg_chg1:+.2f}%"
    return f"{sentiment} — {detail}\n{perf}"


# ── full deep report ──────────────────────────────────────────────────────────

def build_deep_report(
    assets_data:   dict,
    corr_df,
    econ_events:   list,
    news_us:       list,
    news_ca:       list,
    macro_data:    dict | None = None,
) -> str:
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines  = []

    # ── Header
    lines += [
        f"🧠 <b>ANALYSE PROFONDE — tradingLIVE</b>",
        f"🕒 <i>{now}</i>",
        "═" * 32,
        "",
    ]

    # ── 1. Macro Overview
    lines += [
        "📊 <b>1. MACRO OVERVIEW</b>",
        "─" * 28,
        macro_overview(assets_data),
        "",
    ]

    # ── 1b. Macro Global (VIX + Yield Curve)
    if macro_data:
        vix_d   = macro_data.get("vix") or {}
        yield_d = macro_data.get("yield") or {}

        if not vix_d.get("error") or not all(v.get("error") for v in yield_d.values() if isinstance(v, dict)):
            lines += ["🌐 <b>MACRO GLOBAL</b>", "─" * 28]

            # VIX
            if not vix_d.get("error"):
                from macro_data import _vix_level
                v       = vix_d["current"]
                chg1    = vix_d["change_1d"]
                arr     = "📈" if chg1 > 0 else "📉"
                lbl, _  = _vix_level(v)
                lines.append(f"😰 VIX : <b>{v:.1f}</b> {arr} {chg1:+.2f}%  —  {lbl}")

            # Yield curve compacte
            ys = {}
            for tenor in ("3M", "5Y", "10Y", "30Y"):
                d = yield_d.get(tenor, {})
                if not d.get("error"):
                    ys[tenor] = d["yield"]
            if ys:
                parts_y = []
                for tenor, val in ys.items():
                    parts_y.append(f"{tenor}:{val:.2f}%")
                lines.append("📈 Yields : " + "  ".join(parts_y))
                if "10Y" in ys and "3M" in ys:
                    spread = ys["10Y"] - ys["3M"]
                    sp_lbl = "🟢 Normal" if spread >= 0 else "🔴 Inversé"
                    lines.append(f"   Spread 10Y-3M : <b>{spread:+.3f}%</b>  {sp_lbl}")

            lines.append("")

    # ── 2. Asset-by-asset analysis
    GROUPS = {
        "💱 FOREX":         ["EUR/USD", "USD/CAD", "GBP/USD", "USD/JPY"],
        "📈 INDICES":       ["NAS100", "US500"],
        "🖥️ ACTIONS":      ["NVDA"],
    }

    for group_title, group_assets in GROUPS.items():
        lines += [f"<b>{group_title}</b>", "─" * 28]
        for name in group_assets:
            d = assets_data.get(name, {})
            a = analyze_asset(name, d)
            if a.get("error"):
                lines.append(f"• <b>{name}</b> — données indisponibles")
                continue
            raw_d = assets_data[name]
            from market_data import format_price
            price_str = format_price(raw_d["price"], name)
            bias_ico  = bias_icon(a["final_bias"])
            lines.append(
                f"• <b>{name}</b>  <code>{price_str}</code>  "
                f"1j: {raw_d['change_1d']:+.2f}%  7j: {raw_d['change_7d']:+.2f}%"
            )
            lines.append(f"  H4: {a['h4_label']}   H1: {a['h1_label']}")
            lines.append(f"  RSI {raw_d['rsi']} — {a['rsi_label']}")
            if a["level_warning"]:
                lines.append(f"  {a['level_warning']}")
            lines.append(f"  {bias_ico} <b>Biais : {a['final_bias']}</b>")
            lines.append("")
        lines.append("")

    # ── 3. Correlations
    if corr_df is not None and not corr_df.empty:
        lines += ["🔗 <b>3. CORRÉLATIONS CLÉS (30j)</b>", "─" * 28]
        pairs = analyze_correlations(corr_df)
        strong = [p for p in pairs if abs(p["val"]) >= 0.60][:5]
        if strong:
            for p in strong:
                sign = "+" if p["val"] >= 0 else ""
                lines.append(f"• {p['label']}")
                lines.append(f"  <code>{p['a']}</code> ↔ <code>{p['b']}</code> : <b>{sign}{p['val']:.2f}</b>")
                lines.append(f"  <i>{p['desc']}</i>")
                lines.append("")
        else:
            lines.append("<i>Corrélations faibles — actifs indépendants.</i>")
            lines.append("")

    # ── 4. Economic calendar
    if econ_events:
        upcoming = [e for e in econ_events if not e.is_past()][:5]
        past_imp = [e for e in econ_events if e.is_past() and e.impact in ("High",) and e.actual][-3:]
        lines += ["📅 <b>4. CALENDRIER ÉCONOMIQUE</b>", "─" * 28]
        if past_imp:
            lines.append("<i>Résultats récents :</i>")
            for e in past_imp:
                lines.append(
                    f"{e.impact_emoji()} {e.flag()} <b>{_esc(e.title)}</b> → {_esc(e.actual)}"
                    + (f" (prévu {_esc(e.forecast)})" if e.forecast else "")
                )
            lines.append("")
        if upcoming:
            lines.append("<i>À venir cette semaine :</i>")
            for e in upcoming:
                lines.append(
                    f"{e.impact_emoji()} {e.flag()} <b>{_esc(e.title)}</b>"
                    + (f" — Prévu: {_esc(e.forecast)}" if e.forecast else "")
                )
        lines.append("")

    # ── 5. News highlights
    top_news = news_us[:5]
    if top_news:
        lines += ["📰 <b>5. NEWS CLÉS</b>", "─" * 28]
        for a in top_news:
            lines.append(f"🇺🇸 <i>{_esc(a.title)}</i>  <code>{_esc(a.source)}</code>")
        lines.append("")

    # ── 6. Summary bias table
    lines += ["🎯 <b>6. BIAIS DIRECTIONNEL</b>", "─" * 28]
    for name in ["EUR/USD", "USD/CAD", "GBP/USD", "USD/JPY", "NAS100", "US500", "NVDA"]:
        d = assets_data.get(name, {})
        a = analyze_asset(name, d)
        if a.get("error"):
            lines.append(f"• <b>{name}</b>  ➡️ Neutre (données manquantes)")
        else:
            icon = bias_icon(a["final_bias"])
            lines.append(f"• <b>{name}</b>  {icon} {a['final_bias']}")
    lines.append("")

    lines += ["═" * 32, "⚡ <b>tradingLIVE</b> | /price | /correlation | /week"]
    return "\n".join(lines)
