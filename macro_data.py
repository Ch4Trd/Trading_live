"""
macro_data.py – VIX + Yield Curve US.
Données macro en temps réel via yfinance.
"""

import logging
import numpy as np
import yfinance as yf
from datetime import datetime, timezone
from html import escape as _esc

log = logging.getLogger(__name__)

# Tickers yfinance pour les taux US
# ^IRX = 13-week T-bill, ^FVX = 5Y, ^TNX = 10Y, ^TYX = 30Y
# Ces tickers yfinance reportent la valeur × 10 (ex: 43.5 = 4.35%)
YIELD_TICKERS = {
    "3M":  "^IRX",
    "5Y":  "^FVX",
    "10Y": "^TNX",
    "30Y": "^TYX",
}


def _normalize_yield(val: float) -> float:
    """Normalise le yield yfinance : si > 20 → divise par 10 pour avoir le %."""
    return val / 10.0 if val > 20 else val


# ── VIX ───────────────────────────────────────────────────────────────────────

def fetch_vix() -> dict:
    try:
        hist = yf.Ticker("^VIX").history(period="35d", interval="1d")
        if hist.empty:
            return {"error": True}
        closes  = hist["Close"].dropna()
        current = float(closes.iloc[-1])
        prev    = float(closes.iloc[-2]) if len(closes) >= 2 else current
        week    = float(closes.iloc[-6]) if len(closes) >= 6 else current
        month   = float(closes.iloc[0])
        return {
            "current":    round(current, 2),
            "change_1d":  round((current - prev)  / prev  * 100, 2),
            "change_7d":  round((current - week)  / week  * 100, 2),
            "change_30d": round((current - month) / month * 100, 2),
            "error": False,
        }
    except Exception as exc:
        log.warning("fetch_vix error: %s", exc)
        return {"error": True}


def _vix_level(v: float) -> tuple[str, str]:
    """Retourne (label, conseil) selon le niveau de VIX."""
    if v < 12:
        return "🟢 TRÈS BAS (&lt;12)", "Marché complacent. Attention au retournement — acheter la volatilité?"
    if v < 16:
        return "🟢 BAS (12-16)", "Marché calme, entries propres possibles. Spreads serrés."
    if v < 20:
        return "🟡 MODÉRÉ (16-20)", "Volatilité normale. Trading en tendance favorable."
    if v < 25:
        return "🟠 ÉLEVÉ (20-25)", "Incertitude notable. Réduire la taille des positions."
    if v < 30:
        return "🔴 PEUR (25-30)", "Risk-off dominant. Favoriser JPY/USD/or, éviter indices long."
    if v < 40:
        return "🔴 FORTE PEUR (30-40)", "Sell-off en cours. Attendre stabilisation avant d'entrer."
    return "🚨 PANIQUE (&gt;40)", "Crise de marché. Uniquement gestion du risque — pas de nouvelles positions."


def format_vix_message(data: dict) -> str:
    if data.get("error"):
        return "❌ VIX indisponible — données yfinance temporairement inaccessibles."

    v      = data["current"]
    chg1   = data["change_1d"]
    chg7   = data["change_7d"]
    chg30  = data["change_30d"]
    arrow1 = "📈" if chg1 > 0 else "📉"
    level_label, level_advice = _vix_level(v)

    lines = [
        "😰 <b>VIX — Fear &amp; Greed Index</b>",
        "═" * 32,
        f"Actuel  : <b>{v:.1f}</b>  {arrow1} <b>{chg1:+.2f}%</b> (24h)",
        f"7j      : {chg7:+.2f}%   30j : {chg30:+.2f}%",
        "",
        f"Niveau  : {level_label}",
        f"<i>{level_advice}</i>",
        "",
        "🎯 <b>Impact trading :</b>",
    ]

    if v < 16:
        lines += [
            "• Spreads serrés — scalping et day trading OK",
            "• Entries en tendance avec stops normaux",
            "• Pas de signal de panique — risk-on probable",
        ]
    elif v < 20:
        lines += [
            "• Conditions normales, tendances fiables",
            "• Taille de position standard",
            "• Surveiller catalyst macro pour breakouts",
        ]
    elif v < 25:
        lines += [
            "• Réduire taille de position de 20-30%",
            "• Elargir les stops — volatilité accrue",
            "• USD/JPY et or : volatilité amplifiée",
            "• Indices : biais prudent, préférer short terme",
        ]
    elif v < 30:
        lines += [
            "• Risk-off dominant — USD, JPY, or en hausse",
            "• Indices sous pression, éviter long",
            "• Positions réduites de 50%, stops larges",
            "• Attendre signal de stabilisation VIX &lt; 25",
        ]
    else:
        lines += [
            "• Mode gestion du risque uniquement",
            "• Pas de nouvelles positions directionnelles",
            "• Surveiller niveau clé : retour VIX &lt; 30 = début de stabilisation",
            "• Corrélation USD haussier, or/JPY en forte demande",
        ]

    lines += [
        "",
        "═" * 32,
        "⚡ <b>tradingLIVE</b> | /yield-curve | /deep | /price",
    ]
    return "\n".join(lines)


# ── Yield Curve ───────────────────────────────────────────────────────────────

def fetch_yield_curve() -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(label: str, ticker: str) -> tuple[str, dict]:
        try:
            hist = yf.Ticker(ticker).history(period="7d", interval="1d")
            if hist.empty:
                return label, {"error": True}
            closes  = hist["Close"].dropna()
            current = _normalize_yield(float(closes.iloc[-1]))
            prev    = _normalize_yield(float(closes.iloc[-2])) if len(closes) >= 2 else current
            return label, {
                "yield":    round(current, 3),
                "change":   round(current - prev, 3),
                "error":    False,
            }
        except Exception as exc:
            log.warning("yield_curve error [%s]: %s", label, exc)
            return label, {"error": True}

    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_one, label, ticker): label
                   for label, ticker in YIELD_TICKERS.items()}
        for f in as_completed(futures):
            label, data = f.result()
            results[label] = data

    return results


def _spread_label(spread: float) -> str:
    if spread >= 0.5:
        return "🟢 Normal — croissance attendue"
    if spread >= 0.0:
        return "🟡 Plat — ralentissement possible"
    if spread >= -0.5:
        return "🔴 Légèrement inversé ⚠️"
    return "🚨 Fortement inversé — signal de récession"


def format_yield_curve_message(data: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "📈 <b>YIELD CURVE US</b>",
        f"🕒 <i>{now}</i>",
        "═" * 32,
    ]

    order = ["3M", "5Y", "10Y", "30Y"]
    yields = {}

    for label in order:
        d = data.get(label, {})
        if d.get("error"):
            lines.append(f"  <b>{label:&gt;3}</b> : ❌ indisponible")
        else:
            y   = d["yield"]
            chg = d["change"]
            arr = "▲" if chg >= 0 else "▼"
            lines.append(
                f"  <b>{label:>3}</b> : <code>{y:.3f}%</code>  "
                f"{arr} {abs(chg):.3f}"
            )
            yields[label] = y

    lines.append("")

    # Spreads clés
    if "10Y" in yields and "3M" in yields:
        sp = yields["10Y"] - yields["3M"]
        lines.append(f"Spread 10Y-3M : <b>{sp:+.3f}%</b>  {_spread_label(sp)}")
    if "10Y" in yields and "5Y" in yields:
        sp = yields["10Y"] - yields["5Y"]
        state = "🟢 Normal" if sp >= 0 else "🔴 Inversé"
        lines.append(f"Spread 10Y-5Y : <b>{sp:+.3f}%</b>  {state}")
    if "30Y" in yields and "10Y" in yields:
        sp = yields["30Y"] - yields["10Y"]
        lines.append(f"Spread 30Y-10Y: <b>{sp:+.3f}%</b>")

    lines.append("")

    # Interprétation
    inverted = "10Y" in yields and "3M" in yields and (yields["10Y"] - yields["3M"]) < 0

    if inverted:
        sp_val = yields["10Y"] - yields["3M"]
        lines += [
            "🔴 <b>Courbe inversée</b> — signal historique de récession",
            f"  Spread 10Y-3M : {sp_val:+.3f}%",
            "",
            "🎯 <b>Impact marché :</b>",
            "• <b>USD</b> : neutre à haussier si Fed hawkish, baissier si pivot",
            "• <b>Indices</b> : pression à moyen terme — attention aux earnings",
            "• <b>Or/JPY</b> : demande refuge en hausse",
            "• <b>Banques</b> : marge compressée — secteur sous pression",
            "• Historiquement : récession dans 6-18 mois post-inversion",
        ]
    elif "10Y" in yields and yields.get("10Y", 0) > 4.5:
        lines += [
            "🟡 <b>Yields élevés</b> — politique monétaire restrictive",
            "",
            "🎯 <b>Impact marché :</b>",
            "• <b>USD</b> : haussier — carry trade favorable",
            "• <b>Indices</b> : coût du capital élevé — valorisation sous pression",
            "• <b>Or</b> : pression baissière (coût d'opportunité élevé)",
            "• <b>Immobilier/obligations</b> : sous pression",
        ]
    else:
        lines += [
            "🟢 <b>Courbe normale</b> — croissance économique attendue",
            "",
            "🎯 <b>Impact marché :</b>",
            "• <b>Indices</b> : biais haussier — conditions de crédit favorables",
            "• <b>USD</b> : neutre à légèrement haussier",
            "• <b>Risk-on</b> : favorable aux actifs risqués",
        ]

    lines += [
        "",
        "═" * 32,
        "⚡ <b>tradingLIVE</b> | /vix | /deep | /price",
    ]
    return "\n".join(lines)
