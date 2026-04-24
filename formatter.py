from datetime import datetime, timezone
from html import escape as _esc
from news_fetcher import Article
from config import ASSET_EMOJI, ASSET_TYPE
import market_data as md

DIVIDER = "─" * 30
SEP     = "═" * 32


# ── helpers ───────────────────────────────────────────────────────────────────

def _article_block(article: Article, index: int) -> str:
    age_s = f"  <i>{article.age_str()}</i>" if article.age_str() else ""
    lines = [
        f"<b>{index}. {_esc(article.title)}</b>",
        f"📰 <code>{_esc(article.source)}</code>{age_s}",
    ]
    if article.summary:
        lines.append(f"<i>{_esc(article.summary)}</i>")
    lines.append(f'🔗 <a href="{article.url}">Read</a>')
    return "\n".join(lines)


def _split_message(text: str, limit: int = 4096) -> list:
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for para in text.split("\n\n"):
        segment = para + "\n\n"
        if len(current) + len(segment) > limit:
            if current:
                chunks.append(current.rstrip())
            current = segment
        else:
            current += segment
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or [text[:limit]]


# ── news reports ──────────────────────────────────────────────────────────────

def build_newreport(articles: list, limit: int = 8) -> list:
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"🇺🇸 <b>US NEWS — tradingLIVE</b>\n🕒 <i>{now}</i>\n{SEP}"
    footer = f"\n{SEP}\n⚡ /price | /correlation | /week | /deep | /help"
    if not articles:
        return [f"{header}\n\n<i>No news available.</i>{footer}"]
    blocks = [_article_block(a, i) for i, a in enumerate(articles[:limit], 1)]
    return _split_message(f"{header}\n\n" + f"\n\n{DIVIDER}\n\n".join(blocks) + f"\n\n{footer}")


def build_us_report(articles: list, limit: int = 10) -> list:
    return build_newreport(articles, limit)


# ── market data ───────────────────────────────────────────────────────────────

_DEFAULT_SYMBOLS = ["EUR/USD", "USD/CAD", "GBP/USD", "USD/JPY", "XAU/USD", "NAS100", "US500", "NVDA"]


def build_price_message(assets_data: dict, symbols: list = None) -> list:
    now   = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [
        "💹 <b>PRIX EN DIRECT — tradingLIVE</b>",
        f"🕒 <i>{now}</i>",
        "<i>⚠️ Indices/stocks: ~15min de délai | Forex: quasi temps réel</i>",
        SEP,
        "",
    ]

    for name in (symbols or _DEFAULT_SYMBOLS):
        d = assets_data.get(name)
        if not d or d.get("error"):
            lines.append(f"{ASSET_EMOJI.get(name, '📊')} <b>{name}</b>  <i>données indisponibles</i>")
            lines.append("")
            continue

        emoji      = ASSET_EMOJI.get(name, "📊")
        price_str  = md.format_price(d["price"], name)
        chg1, chg7 = d["change_1d"], d["change_7d"]
        arrow1     = "🟢" if chg1 >= 0 else "🔴"
        rsi        = d["rsi"]
        trend_icon = "📈" if d["trend"] == "bullish" else "📉"
        trend_txt  = "Bullish" if d["trend"] == "bullish" else "Bearish"
        rsi_warn   = "  ⚠️ <i>Surachat</i>" if rsi >= 70 else ("  ⚠️ <i>Survente</i>" if rsi <= 30 else "")

        lines.append(
            f"{emoji} <b>{name}</b>    <code>{price_str}</code>   "
            f"{arrow1} <b>{chg1:+.2f}%</b>  |  7j: <b>{chg7:+.2f}%</b>"
        )
        lines.append(
            f"   RSI: <b>{rsi}</b>{rsi_warn}   {trend_icon} {trend_txt}   "
            f"S: <code>{md.format_price(d['support'], name)}</code>  "
            f"R: <code>{md.format_price(d['resistance'], name)}</code>"
        )
        lines.append("")

    lines += [SEP, "⚡ <b>tradingLIVE</b> | /correlation | /deep | /week"]
    return _split_message("\n".join(lines))


def build_correlation_message(corr_df, pairs: list = None) -> list:
    now   = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [
        "🔗 <b>CORRÉLATIONS INTER-MARCHÉS — 30 JOURS</b>",
        f"🕒 <i>{now}</i>",
        SEP, "",
        "<b>Matrice (rendements journaliers | -1 → +1)</b>", "",
    ]

    import numpy as np
    assets = list(corr_df.columns)
    lines.append(f"<code>{'':10}" + "".join(f"{a[:5]:>7}" for a in assets) + "</code>")
    for row in assets:
        r = f"{row[:10]:<10}"
        for col in assets:
            val = corr_df.loc[row, col]
            r += f"  {'1.00':>5}" if row == col else (
                f"  {val:>+5.2f}" if not np.isnan(val) else f"  {'N/A':>5}"
            )
        lines.append(f"<code>{r}</code>")

    if pairs:
        lines += ["", SEP, "", "<b>Analyse des corrélations clés</b>", ""]
        for p in [p for p in pairs if abs(p["val"]) >= 0.50][:6]:
            sign = "+" if p["val"] >= 0 else ""
            lines += [
                f"• {p['label']}",
                f"  <code>{p['a']}</code> ↔ <code>{p['b']}</code> : <b>{sign}{p['val']:.2f}</b>",
                f"  <i>{p['desc']}</i>", "",
            ]
        if not any(abs(p["val"]) >= 0.50 for p in pairs):
            lines.append("<i>Aucune corrélation forte détectée — actifs indépendants.</i>")

    lines += ["", SEP, "⚡ <b>tradingLIVE</b> | /price | /deep | /week"]
    return _split_message("\n".join(lines))


def build_week_message(events: list) -> list:
    from economic_calendar import format_week_message
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"📅 <b>CALENDRIER ÉCONOMIQUE — SEMAINE EN COURS</b>\n🕒 <i>{now}</i>\n{SEP}"
    body   = format_week_message(events)
    footer = f"\n{SEP}\n⚡ <b>tradingLIVE</b> | /price | /deep | /newreport"
    return _split_message(f"{header}\n{body}{footer}")


def build_deep_message(ai_analysis: str) -> list:
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"🧠 <b>ANALYSE PROFONDE — tradingLIVE</b>\n🕒 <i>{now}</i>\n{SEP}\n"
    footer = f"\n{SEP}\n⚡ <b>tradingLIVE</b> | /price | /correlation | /week"
    return _split_message(f"{header}\n{ai_analysis}{footer}")
