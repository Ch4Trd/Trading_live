"""
result_command.py
/result — Résultats des événements économiques du jour avec analyse des surprises.

Pour chaque événement passé (High + Medium) :
  • Actual vs Forecast vs Previous
  • Analyse de surprise : HAUSSIÈRE 🟢 / BAISSIÈRE 🔴 / CONFORME ➖
  • Impact estimé sur la devise concernée
  • Indicateur visuel delta (≫ fort écart / ≈ faible écart)
"""

import logging
import re
from datetime import datetime, timezone
from html import escape as _esc

from economic_calendar import get_day_events, EconEvent
from subscription import subscription_manager

log = logging.getLogger(__name__)

# ── Labels inversés : pour ces events, un chiffre PLUS BAS = meilleure nouvelle ──
_BEARISH_KEYWORDS = {
    "unemployment", "jobless", "claims", "initial claims",
    "continuing claims", "deficit", "debt", "delinquencies",
    "default", "layoffs", "bankruptcies",
}

# ── Correspondance devise → assets affectés ───────────────────────────────────
_CURRENCY_ASSETS = {
    "USD": "USD → NAS100↑/↓  US500↑/↓  GOLD↓/↑",
}

_FLAG_MAP  = {"USD": "🇺🇸", "CAD": "🇨🇦", "EUR": "🇪🇺", "GBP": "🇬🇧",
              "JPY": "🇯🇵", "AUD": "🇦🇺", "NZD": "🇳🇿", "CHF": "🇨🇭"}
_IMPACT_EMOJI = {"High": "🔴", "Medium": "🟡", "Low": "⚪"}


# ── Parsing numérique ─────────────────────────────────────────────────────────

def _parse_num(s: str) -> float | None:
    """
    Convertit "3.2%", "-256K", "15.1B", "1,250" → float
    Retourne None si non parsable.
    """
    if not s or s.strip() in ("-", "N/A", "—", ""):
        return None
    s = s.strip().replace(",", "")
    multiplier = 1.0
    if s.endswith("K") or s.endswith("k"):
        multiplier, s = 1_000, s[:-1]
    elif s.endswith("M") or s.endswith("m"):
        multiplier, s = 1_000_000, s[:-1]
    elif s.endswith("B") or s.endswith("b"):
        multiplier, s = 1_000_000_000, s[:-1]
    s = s.rstrip("%").strip()
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def _is_lower_better(title: str) -> bool:
    """Retourne True si un résultat PLUS BAS est une meilleure nouvelle pour la devise."""
    t = title.lower()
    return any(kw in t for kw in _BEARISH_KEYWORDS)


def _surprise_analysis(event: EconEvent) -> dict:
    """
    Analyse la surprise entre actual et forecast.
    Retourne un dict avec verdict, emoji, delta_str, strength.
    """
    actual   = _parse_num(event.actual)
    forecast = _parse_num(event.forecast)
    previous = _parse_num(event.previous)

    result = {
        "verdict":  "CONFORME",
        "emoji":    "➖",
        "delta":    "",
        "strength": "",   # "fort" | "modéré" | ""
        "bullish":  None, # True = bullish pour la devise / False = bearish
    }

    if actual is None:
        result["verdict"] = "EN ATTENTE"
        result["emoji"]   = "⏳"
        return result

    if forecast is not None:
        diff = actual - forecast
        pct_diff = (abs(diff) / abs(forecast) * 100) if forecast != 0 else 0

        lower_better = _is_lower_better(event.title)

        if abs(diff) < 1e-9:
            # Exactement égal
            result["verdict"] = "CONFORME"
            result["emoji"]   = "➖"
            result["bullish"] = None
        else:
            # Direction de la surprise
            raw_positive = diff > 0
            # Si un chiffre bas est meilleur (chômage), inverser
            is_bullish = (raw_positive and not lower_better) or \
                         (not raw_positive and lower_better)

            if is_bullish:
                result["verdict"] = "SURPRISE HAUSSIÈRE"
                result["emoji"]   = "🟢"
                result["bullish"] = True
            else:
                result["verdict"] = "SURPRISE BAISSIÈRE"
                result["emoji"]   = "🔴"
                result["bullish"] = False

            # Force de la surprise
            if pct_diff >= 20 or abs(diff) >= 100_000:
                result["strength"] = "FORTE"
                result["delta"]    = "≫"
            elif pct_diff >= 5 or abs(diff) >= 10_000:
                result["strength"] = "MODÉRÉE"
                result["delta"]    = "›"
            else:
                result["strength"] = "LÉGÈRE"
                result["delta"]    = "~"

    elif previous is not None and actual is not None:
        # Pas de forecast : compare à previous
        diff = actual - previous
        lower_better = _is_lower_better(event.title)
        raw_positive = diff > 0
        is_bullish = (raw_positive and not lower_better) or \
                     (not raw_positive and lower_better)
        if abs(diff) < 1e-9:
            result["verdict"] = "STABLE"
            result["emoji"]   = "➖"
        elif is_bullish:
            result["verdict"] = "AMÉLIORATION"
            result["emoji"]   = "🟢"
            result["bullish"] = True
            result["delta"]   = "›"
        else:
            result["verdict"] = "DÉGRADATION"
            result["emoji"]   = "🔴"
            result["bullish"] = False
            result["delta"]   = "›"

    return result


def _market_impact(event: EconEvent, surprise: dict) -> str:
    """Retourne une ligne d'impact estimé selon la devise et la direction."""
    if surprise["bullish"] is None:
        return ""

    ccy = event.currency
    flag = _FLAG_MAP.get(ccy, "🌐")
    bullish = surprise["bullish"]

    impact_lines = []

    if ccy == "USD":
        if bullish:
            impact_lines += [
                "💹 USD ↑  →  NAS100 ↓  US500 ↓  (taux élevés = multiples compressés)",
                "         →  GOLD ↓  (potentiel)",
            ]
        else:
            impact_lines += [
                "💹 USD ↓  →  NAS100 ↑  US500 ↑  (liquidités libérées = relief rally)",
                "         →  GOLD ↑  (potentiel)",
            ]

    return "\n".join(impact_lines)


# ── Formatter ─────────────────────────────────────────────────────────────────

def _fmt_result_block(event: EconEvent, surprise: dict) -> str:
    """Formate un bloc résultat pour un seul événement."""
    time_s = event.date.strftime("%H:%M UTC") if (event.date.hour or event.date.minute) else "All day"
    flag   = _FLAG_MAP.get(event.currency, "🌐")
    impact = _IMPACT_EMOJI.get(event.impact, "⚪")

    lines = []
    # Header
    strength_tag = f" <b>[{surprise['strength']}]</b>" if surprise.get("strength") else ""
    lines.append(
        f"{impact} {flag} <b>{_esc(event.title)}</b>  "
        f"<code>{time_s}</code>"
    )

    # Résultat
    actual_s   = f"<b>{_esc(event.actual)}</b>"   if event.actual   else "<i>—</i>"
    forecast_s = f"<code>{_esc(event.forecast)}</code>" if event.forecast else "<code>—</code>"
    prev_s     = f"<code>{_esc(event.previous)}</code>" if event.previous else "<code>—</code>"

    lines.append(
        f"   Réel : {actual_s}   "
        f"Prévu : {forecast_s}   "
        f"Préc : {prev_s}"
    )

    # Verdict
    delta = surprise.get("delta", "")
    lines.append(
        f"   {surprise['emoji']} <b>{surprise['verdict']}</b>"
        + (f"{strength_tag}  {delta}" if strength_tag else "")
    )

    # Impact marché
    impact_str = _market_impact(event, surprise)
    if impact_str:
        for il in impact_str.split("\n"):
            lines.append(f"   {il}")

    return "\n".join(lines)


def format_results_message(events: list[EconEvent], now: datetime) -> str:
    """Construit le message complet /result."""
    past   = [e for e in events if e.is_past()]
    future = [e for e in events if not e.is_past()]

    lines = []
    lines.append("📋 <b>RÉSULTATS ÉCONOMIQUES DU JOUR</b>")
    lines.append(f"<code>{now.strftime('%Y-%m-%d')} — {now.strftime('%H:%M')} UTC</code>")
    lines.append("═" * 34)

    if not past:
        lines.append("\n<i>⏳ Aucun résultat publié pour l'instant.</i>")
    else:
        lines.append(f"\n✅ <b>{len(past)} événement(s) publié(s)</b>\n")
        for e in past:
            surprise = _surprise_analysis(e)
            lines.append(_fmt_result_block(e, surprise))
            lines.append("")  # separator

    # Upcoming
    if future:
        lines.append("─" * 28)
        lines.append(f"⏰ <b>{len(future)} événement(s) à venir</b>")
        for e in future:
            time_s = e.date.strftime("%H:%M UTC") if (e.date.hour or e.date.minute) else "All day"
            flag   = _FLAG_MAP.get(e.currency, "🌐")
            impact = _IMPACT_EMOJI.get(e.impact, "⚪")
            fc_s   = f"  Prévu: <code>{_esc(e.forecast)}</code>" if e.forecast else ""
            lines.append(f"{impact} {flag} <b>{_esc(e.title)}</b>  <code>{time_s}</code>{fc_s}")

    lines.append("\n" + "═" * 34)
    lines.append("⚡ <b>tradingLIVE</b> | /day | /week | /analyze")
    return "\n".join(lines)


# ── Handler ───────────────────────────────────────────────────────────────────

async def cmd_result(update, context):
    """Handler /result — résultats des événements économiques du jour."""
    user_id = update.effective_user.id
    if not subscription_manager.is_user_active(user_id):
        await update.message.reply_text(
            "🔒 <b>Accès restreint</b>\n\nCette commande nécessite un abonnement actif.",
            parse_mode="HTML",
        )
        return

    import asyncio
    from formatter import _split_message

    msg = await update.message.reply_text(
        "📋 <i>Récupération des résultats économiques…</i>",
        parse_mode="HTML",
    )

    try:
        loop   = asyncio.get_event_loop()
        events = await loop.run_in_executor(None, get_day_events)
        now    = datetime.now(timezone.utc)
        report = format_results_message(events, now)

        await msg.delete()
        for part in _split_message(report):
            await update.message.reply_text(part, parse_mode="HTML",
                                            disable_web_page_preview=True)

    except Exception as e:
        log.exception("result_command error")
        await msg.edit_text(
            f"❌ Erreur lors de la récupération des résultats : <code>{_esc(str(e))}</code>",
            parse_mode="HTML",
        )
