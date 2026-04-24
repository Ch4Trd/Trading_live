import sys
import json
import logging
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters,
)
from telegram.constants import ParseMode

import formatter as fmt
from news_fetcher import fetch_us
from market_data import fetch_all_assets, get_history_df
from economic_calendar import get_week_events, get_month_events, get_day_events, format_day_message
from algo_analyst import build_deep_report, analyze_correlations
from flash_news import fetch_flash_news, score_and_sort, format_flash_message
from i18n import t, SUPPORTED, DEFAULT
from config import (
    TELEGRAM_TOKEN,
    MAX_ARTICLES_REPORT, MAX_ALERT_ARTICLES, ALERT_INTERVAL_HOURS,
)

log        = logging.getLogger(__name__)
START_TIME = datetime.now(timezone.utc)
SUBS_FILE    = Path(__file__).parent / "subscribers.json"
LANG_FILE    = Path(__file__).parent / "languages.json"
TRUMP_FILE   = Path(__file__).parent / "trump_subscribers.json"
BREAKING_SUB = Path(__file__).parent / "breaking_subscribers.json"
MARKET_SUB   = Path(__file__).parent / "market_subscribers.json"
TZ_FILE      = Path(__file__).parent / "timezones.json"

SEND_KW              = dict(parse_mode=ParseMode.HTML, disable_web_page_preview=True)
TRUMP_POLL_INTERVAL  = 5 * 60    # 5 min
BREAKING_POLL_INTERVAL = 90      # 90 secondes
MARKET_POLL_INTERVAL   = 60      # 60 secondes

# Anti-spam FOMC : une seule analyse par heure
_last_fomc_analysis_ts: float = 0.0
FOMC_COOLDOWN_SECONDS         = 3600

# Caches mémoire anti-doublons (persistent entre les runs du job dans la session)
# Évite les renvois si save_seen échoue ou si l'article reste dans la fenêtre 10min
_market_sent_uids:   set = set()
_breaking_sent_uids: set = set()
_trump_sent_uids:    set = set()

# ── Claviers inline réutilisables ─────────────────────────────────────────────

_KB_ALERT = InlineKeyboardMarkup([[
    InlineKeyboardButton("📊 Prix",    callback_data="cmd_price"),
    InlineKeyboardButton("📅 Jour",    callback_data="cmd_day"),
    InlineKeyboardButton("🧠 Deep",    callback_data="cmd_deep"),
]])


# ── persistence helpers ───────────────────────────────────────────────────────

def _load_json_dict(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _load_json_set(path: Path) -> set:
    if path.exists():
        try:
            return set(json.loads(path.read_text()))
        except Exception:
            pass
    return set()


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(list(data) if isinstance(data, set) else data, indent=2))


# ── state ─────────────────────────────────────────────────────────────────────

subscribers:        dict = _load_json_dict(SUBS_FILE)
languages:          dict = _load_json_dict(LANG_FILE)
trump_subscribers:   set  = _load_json_set(TRUMP_FILE)
breaking_subscribers: set = _load_json_set(BREAKING_SUB)
market_subscribers:   set = _load_json_set(MARKET_SUB)
timezones:           dict = _load_json_dict(TZ_FILE)

DEFAULT_TZ = "UTC"

# Aliases courants → nom IANA
TZ_ALIASES: dict[str, str] = {
    "ET":   "America/New_York",
    "EST":  "America/New_York",
    "EDT":  "America/New_York",
    "CT":   "America/Chicago",
    "CST":  "America/Chicago",
    "MT":   "America/Denver",
    "MST":  "America/Denver",
    "PT":   "America/Los_Angeles",
    "PST":  "America/Los_Angeles",
    "PDT":  "America/Los_Angeles",
    "AT":   "America/Halifax",
    "AST":  "America/Halifax",
    "NT":   "America/St_Johns",
    "NST":  "America/St_Johns",
    "GMT":  "UTC",
    "CET":  "Europe/Paris",
    "CEST": "Europe/Paris",
    "WET":  "Europe/London",
    "BST":  "Europe/London",
    "EET":  "Europe/Helsinki",
    "MSK":  "Europe/Moscow",
    "IST":  "Asia/Kolkata",
    "JST":  "Asia/Tokyo",
    "CST8": "Asia/Shanghai",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
}


def get_lang(chat_id: str) -> str:
    return languages.get(str(chat_id), DEFAULT)


def get_tz(chat_id: str) -> str:
    return timezones.get(str(chat_id), DEFAULT_TZ)


def fmt_time(dt, tz_str: str) -> str:
    """Convertit un datetime UTC en heure locale formatée."""
    if not dt:
        return "--:--"
    try:
        from zoneinfo import ZoneInfo
        local = dt.astimezone(ZoneInfo(tz_str))
        return local.strftime("%H:%M %Z")
    except Exception:
        return dt.strftime("%H:%M UTC")


# ── helpers ───────────────────────────────────────────────────────────────────

async def _send_parts(update: Update, parts: list) -> None:
    for part in parts:
        await update.message.reply_text(part, **SEND_KW)


async def _typing(update: Update) -> None:
    await update.message.chat.send_action("typing")


async def _loading_msg(update: Update, text: str):
    return await update.message.reply_text(f"<i>{text}</i>", parse_mode=ParseMode.HTML)


# ── alert job (periodic news) ─────────────────────────────────────────────────

async def _alert_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id  = context.job.data
    loop     = asyncio.get_running_loop()
    articles = await loop.run_in_executor(None, fetch_us)
    parts    = fmt.build_newreport(articles[:MAX_ALERT_ARTICLES], limit=MAX_ALERT_ARTICLES)
    for part in parts:
        await context.bot.send_message(chat_id=chat_id, text=part, **SEND_KW)


# ── helpers : envoi traduit par langue ───────────────────────────────────────

def _group_by_lang_tz(chat_ids: set) -> dict[tuple[str, str], list[str]]:
    """Regroupe les chat_ids par (langue, fuseau horaire)."""
    groups: dict[tuple[str, str], list[str]] = {}
    for cid in chat_ids:
        key = (get_lang(str(cid)), get_tz(str(cid)))
        groups.setdefault(key, []).append(cid)
    return groups


async def _send_translated(bot, title: str, format_fn, subscribers: set, loop,
                           reply_markup=None) -> None:
    """Traduit et formate par groupe (langue + fuseau horaire), puis envoie.
    format_fn signature : (translated_title: str, tz: str) -> str
    reply_markup : InlineKeyboardMarkup optionnel ajouté à chaque message.
    """
    from ai_analyst import translate_text
    groups = _group_by_lang_tz(subscribers)
    for (lang, tz), chat_ids in groups.items():
        translated_title = await loop.run_in_executor(None, translate_text, title, lang)
        msg_text = format_fn(translated_title, tz)
        for chat_id in chat_ids:
            try:
                await bot.send_message(
                    chat_id=int(chat_id), text=msg_text,
                    reply_markup=reply_markup,
                    **SEND_KW,
                )
            except Exception as exc:
                log.warning("Send alert [%s]: %s", chat_id, exc)


# ── trump job ─────────────────────────────────────────────────────────────────

async def _trump_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    global _trump_sent_uids
    from trump_monitor import fetch_trump_updates, format_trump_alert, load_seen, save_seen
    from context_memory import add_entry
    if not trump_subscribers:
        return
    loop      = asyncio.get_running_loop()
    items     = await loop.run_in_executor(None, fetch_trump_updates)
    seen      = load_seen() | _trump_sent_uids
    new_items = [it for it in items if it.uid() not in seen]
    if not new_items:
        return
    for item in new_items:
        _trump_sent_uids.add(item.uid())
        seen.add(item.uid())
        add_entry("trump", item.title, item.source, score=7, url=item.url or "")
        await _send_translated(
            context.bot, item.title,
            lambda title, tz, _item=item: format_trump_alert(_item.__class__(
                title=title, source=_item.source, url=_item.url,
                published=_item.published, is_tweet=_item.is_tweet,
            ), tz=tz),
            trump_subscribers, loop,
            reply_markup=_KB_ALERT,
        )
    try:
        save_seen(seen)
    except Exception as exc:
        log.error("trump save_seen failed: %s", exc)


# ── market news job (60s) ─────────────────────────────────────────────────────

async def _market_news_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    global _market_sent_uids
    from market_filter import (
        fetch_market_news, format_market_alert,
        load_seen, save_seen,
    )
    from context_memory import add_entry
    if not market_subscribers:
        return
    loop  = asyncio.get_running_loop()
    items = await loop.run_in_executor(None, fetch_market_news)
    seen  = load_seen() | _market_sent_uids
    new_items = [it for it in items if it.uid() not in seen]
    if not new_items:
        return
    for item in new_items:
        _market_sent_uids.add(item.uid())
        seen.add(item.uid())
        add_entry("market", item.title, item.source, score=item.score,
                  summary=item.summary, url=item.url or "")
        await _send_translated(
            context.bot, item.title,
            lambda title, tz, _item=item: format_market_alert(_item.__class__(
                title=title, source=_item.source, url=_item.url,
                published=_item.published, score=_item.score, emoji=_item.emoji,
            ), tz=tz),
            market_subscribers, loop,
            reply_markup=_KB_ALERT,
        )
    try:
        save_seen(seen)
    except Exception as exc:
        log.error("market save_seen failed: %s", exc)
    log.info("Market news: %d alerte(s) envoyée(s).", len(new_items))


# ── breaking news job ─────────────────────────────────────────────────────────

async def _breaking_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    global _breaking_sent_uids
    from breaking_news import fetch_breaking_news, format_breaking_alert, load_seen, save_seen
    if not breaking_subscribers:
        return
    loop      = asyncio.get_running_loop()
    items     = await loop.run_in_executor(None, fetch_breaking_news)
    seen      = load_seen() | _breaking_sent_uids
    new_items = [it for it in items if it.uid() not in seen]
    if not new_items:
        return
    from context_memory import add_entry
    for item in new_items:
        _breaking_sent_uids.add(item.uid())
        seen.add(item.uid())
        add_entry("breaking", item.title, item.source, score=9,
                  summary=getattr(item, "summary", ""), url=item.url or "")
        await _send_translated(
            context.bot, item.title,
            lambda title, tz, _item=item: format_breaking_alert(_item.__class__(
                title=title, source=_item.source, url=_item.url,
                published=_item.published,
            ), tz=tz),
            breaking_subscribers, loop,
            reply_markup=_KB_ALERT,
        )
    try:
        save_seen(seen)
    except Exception as exc:
        log.error("breaking save_seen failed: %s", exc)
    log.info("Breaking: %d alerte(s) envoyée(s).", len(new_items))

    # ── Analyse FOMC auto ─────────────────────────────────────────────────────
    global _last_fomc_analysis_ts
    import time as _time
    fomc_item = next(
        (it for it in new_items
         if __import__("breaking_news").is_fomc_announcement(it.title)),
        None,
    )
    if fomc_item and (_time.time() - _last_fomc_analysis_ts) > FOMC_COOLDOWN_SECONDS:
        _last_fomc_analysis_ts = _time.time()
        log.info("FOMC détecté → analyse IA : %s", fomc_item.title)
        from ai_analyst import analyze_fomc_event
        from html import escape as _esc_fomc
        from formatter import _split_message as _spl

        groups = _group_by_lang_tz(breaking_subscribers)
        for (lang, _tz), chat_ids in groups.items():
            try:
                ai_text = await loop.run_in_executor(
                    None, analyze_fomc_event, fomc_item.title, fomc_item.summary, lang
                )
            except Exception as exc:
                log.warning("FOMC AI error [%s]: %s", lang, exc)
                continue
            if not ai_text:
                continue

            header = (
                "🏦 <b>ANALYSE FOMC — IA</b>\n"
                f"<b>{_esc_fomc(fomc_item.title)}</b>\n"
                f"<i>{_esc_fomc(fomc_item.source)}</i>\n"
                + "═" * 32
            )
            full_msg = f"{header}\n\n{_esc_fomc(ai_text)}\n\n" \
                       "─" * 28 + "\n⚡ <b>tradingLIVE</b> | /price | /deep"

            for chat_id in chat_ids:
                for part in _spl(full_msg):
                    try:
                        await context.bot.send_message(
                            chat_id=int(chat_id), text=part, **SEND_KW
                        )
                    except Exception as exc:
                        log.warning("FOMC send [%s]: %s", chat_id, exc)


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(str(update.effective_chat.id))
    await update.message.reply_text(t("start", lang), parse_mode=ParseMode.HTML)


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(str(update.effective_chat.id))
    await update.message.reply_text(t("help", lang), **SEND_KW)


# ── /lang ─────────────────────────────────────────────────────────────────────

async def cmd_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    lang    = get_lang(chat_id)
    if not ctx.args:
        await update.message.reply_text(t("lang_usage", lang), **SEND_KW)
        return
    new_lang = ctx.args[0].lower().strip()
    if new_lang not in SUPPORTED:
        await update.message.reply_text(t("lang_invalid", lang), **SEND_KW)
        return
    languages[chat_id] = new_lang
    _save_json(LANG_FILE, languages)
    await update.message.reply_text(t("lang_set", new_lang), **SEND_KW)


# ── /price ────────────────────────────────────────────────────────────────────

async def cmd_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg  = await _loading_msg(update, t("loading_price", lang))
    data = await asyncio.get_running_loop().run_in_executor(None, fetch_all_assets)
    await msg.delete()
    await _send_parts(update, fmt.build_price_message(data))


# ── /correlation ──────────────────────────────────────────────────────────────

async def cmd_correlation(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg  = await _loading_msg(update, t("loading_correlation", lang))
    loop = asyncio.get_running_loop()

    def _compute():
        df = get_history_df(30)
        if df.empty:
            return None, None
        returns = df.pct_change().dropna()
        corr    = returns.corr()
        return corr, analyze_correlations(corr)

    corr_df, pairs = await loop.run_in_executor(None, _compute)
    await msg.delete()
    if corr_df is None:
        await update.message.reply_text(t("error_no_history", lang), **SEND_KW)
        return
    await _send_parts(update, fmt.build_correlation_message(corr_df, pairs))


# ── /day ─────────────────────────────────────────────────────────────────────

DAY_HEADER = {
    "fr": "📅 <b>CALENDRIER DU JOUR</b>  <i>(🔴 High + 🟡 Medium)</i>",
    "en": "📅 <b>TODAY'S CALENDAR</b>  <i>(🔴 High + 🟡 Medium)</i>",
    "es": "📅 <b>CALENDARIO DEL DÍA</b>  <i>(🔴 High + 🟡 Medium)</i>",
}
DAY_EMPTY = {
    "fr": "✅ Aucun événement High/Medium aujourd'hui.",
    "en": "✅ No High/Medium events today.",
    "es": "✅ Sin eventos High/Medium hoy.",
}


async def cmd_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg    = await _loading_msg(update, t("loading_day", lang))
    events = await asyncio.get_running_loop().run_in_executor(None, get_day_events)
    await msg.delete()

    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"{DAY_HEADER[lang]}\n🕒 <i>{now} UTC</i>\n" + "═" * 32

    if not events:
        body = DAY_EMPTY[lang]
    else:
        body = format_day_message(events)

    footer = "─" * 32 + "\n⚡ <b>tradingLIVE</b> | /week | /price | /deep"
    from formatter import _split_message
    await _send_parts(update, _split_message(f"{header}\n\n{body}\n\n{footer}"))


# ── /week ─────────────────────────────────────────────────────────────────────

async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg    = await _loading_msg(update, t("loading_calendar", lang))
    events = await asyncio.get_running_loop().run_in_executor(None, get_week_events)
    await msg.delete()
    await _send_parts(update, fmt.build_week_message(events))


# ── /deep ─────────────────────────────────────────────────────────────────────

async def cmd_deep(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from ai_analyst import deep_market_analysis
    from html import escape
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg  = await _loading_msg(update, t("loading_deep", lang))
    loop = asyncio.get_running_loop()

    def _gather():
        import concurrent.futures
        from macro_data import fetch_vix, fetch_yield_curve
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            f_assets = pool.submit(fetch_all_assets)
            f_df     = pool.submit(get_history_df, 30)
            f_cal    = pool.submit(get_month_events, True)
            f_us     = pool.submit(fetch_us)
            f_vix    = pool.submit(fetch_vix)
            f_yield  = pool.submit(fetch_yield_curve)
            assets     = f_assets.result()
            df         = f_df.result()
            cal_events = f_cal.result()
            news_us    = f_us.result()
            vix_data   = f_vix.result()
            yield_data = f_yield.result()
        corr_df = None
        if not df.empty:
            returns = df.pct_change().dropna()
            corr_df = returns.corr()
        macro_data = {"vix": vix_data, "yield": yield_data}
        return assets, corr_df, cal_events, news_us, macro_data

    try:
        from ai_analyst import translate_articles
        assets, corr_df, cal_events, news_us, macro_data = await loop.run_in_executor(None, _gather)
        news_us = await loop.run_in_executor(None, translate_articles, news_us[:5], lang)
        report  = build_deep_report(assets, corr_df, cal_events, news_us, [], macro_data=macro_data)

        def _ai():
            cal_summary = "\n".join(
                f"{e.title} ({e.currency}) — impact:{e.impact}"
                for e in cal_events[:10]
            ) if cal_events else "No events."
            return deep_market_analysis(assets, cal_summary, news_us, [], lang=lang)

        ai_text = await loop.run_in_executor(None, _ai)

        await msg.delete()

        # Envoie le rapport algo
        from formatter import _split_message
        await _send_parts(update, _split_message(report))

        # Envoie l'analyse IA séparément (évite que <pre> soit coupé)
        if ai_text:
            ai_header = (
                "═" * 32 + "\n"
                + t("ai_label", lang) + "\n"
                + "─" * 28
            )
            # Pas de <pre> — on envoie le texte IA en HTML simple
            from html import escape as _esc_html
            ai_body = _esc_html(ai_text)
            for part in _split_message(f"{ai_header}\n\n{ai_body}"):
                await update.message.reply_text(part, **SEND_KW)

    except Exception as exc:
        log.error("cmd_deep error: %s", exc, exc_info=True)
        try:
            await msg.delete()
        except Exception:
            pass
        from html import escape as _esc_html
        await update.message.reply_text(
            t("error_deep", lang) + f"<code>{_esc_html(str(exc))}</code>",
            **SEND_KW,
        )


# ── /flashnews ────────────────────────────────────────────────────────────────

async def cmd_flashnews(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    try:
        hours = int(ctx.args[0]) if ctx.args else 3
        hours = max(1, min(hours, 12))
    except (ValueError, IndexError):
        hours = 3

    msg  = await _loading_msg(update, t("loading_flash", lang))
    loop = asyncio.get_running_loop()

    from ai_analyst import translate_articles
    from news_fetcher import Article as _Article

    def _fetch_and_score():
        return score_and_sort(fetch_flash_news(max_age_hours=hours))

    items = await loop.run_in_executor(None, _fetch_and_score)

    # Convertit FlashItem → Article-like pour la traduction, puis ré-applique
    if lang != "en" and items:
        class _Proxy:
            def __init__(self, item):
                self.title   = item.title
                self.summary = ""
                self._item   = item
        proxies = [_Proxy(it) for it in items]
        proxies = await loop.run_in_executor(None, translate_articles, proxies, lang)
        for proxy, item in zip(proxies, items):
            item.title = proxy.title

    await msg.delete()

    # Mémoire : enregistre les flash HIGH/MEDIUM
    from context_memory import add_entry
    for it in items:
        if it.impact in ("HIGH", "MEDIUM"):
            add_entry("flash", it.title, it.source,
                      score=8 if it.impact == "HIGH" else 5,
                      url=it.url or "")

    for part in format_flash_message(items, max_age_hours=hours):
        await update.message.reply_text(part, **SEND_KW)


# ── /newreport ────────────────────────────────────────────────────────────────

async def cmd_newreport(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from ai_analyst import translate_articles
    lang     = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg      = await _loading_msg(update, t("loading_report", lang))
    loop     = asyncio.get_running_loop()
    articles = await loop.run_in_executor(None, fetch_us)
    articles = await loop.run_in_executor(None, translate_articles, articles[:MAX_ARTICLES_REPORT], lang)
    await msg.delete()
    await _send_parts(update, fmt.build_newreport(articles, limit=MAX_ARTICLES_REPORT))


# ── /us ───────────────────────────────────────────────────────────────────────

async def cmd_us(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from ai_analyst import translate_articles
    lang     = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg      = await _loading_msg(update, t("loading_us", lang))
    loop     = asyncio.get_running_loop()
    articles = await loop.run_in_executor(None, fetch_us)
    articles = await loop.run_in_executor(None, translate_articles, articles[:10], lang)
    await msg.delete()
    await _send_parts(update, fmt.build_us_report(articles))


# ── /alert ────────────────────────────────────────────────────────────────────

async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    lang    = get_lang(chat_id)
    args    = ctx.args

    if not args or args[0] == "status":
        if chat_id in subscribers:
            await update.message.reply_text(t("alert_active", lang, h=subscribers[chat_id]), **SEND_KW)
        else:
            await update.message.reply_text(t("alert_inactive", lang), **SEND_KW)
        return

    if args[0] == "off":
        if chat_id in subscribers:
            del subscribers[chat_id]
            _save_json(SUBS_FILE, subscribers)
            for job in ctx.job_queue.get_jobs_by_name(f"alert_{chat_id}"):
                job.schedule_removal()
        await update.message.reply_text(t("alert_off_confirm", lang), **SEND_KW)
        return

    if args[0] == "on":
        try:
            hours = int(args[1]) if len(args) > 1 else ALERT_INTERVAL_HOURS
            hours = max(1, min(hours, 24))
        except ValueError:
            hours = ALERT_INTERVAL_HOURS
        for job in ctx.job_queue.get_jobs_by_name(f"alert_{chat_id}"):
            job.schedule_removal()
        ctx.job_queue.run_repeating(
            _alert_job, interval=hours * 3600, first=10,
            name=f"alert_{chat_id}", data=int(chat_id),
        )
        subscribers[chat_id] = hours
        _save_json(SUBS_FILE, subscribers)
        await update.message.reply_text(t("alert_on_confirm", lang, h=hours), **SEND_KW)


# ── /trump ────────────────────────────────────────────────────────────────────

TRUMP_TEXTS = {
    "on":         {"fr": "🚨 Alertes Trump activées. Tu seras notifié dès qu'il tweete ou fait une déclaration.",
                   "en": "🚨 Trump alerts enabled. You'll be notified whenever he tweets or makes a statement.",
                   "es": "🚨 Alertas de Trump activadas. Serás notificado cuando publique o haga declaraciones."},
    "off":        {"fr": "🔕 Alertes Trump désactivées.",
                   "en": "🔕 Trump alerts disabled.",
                   "es": "🔕 Alertas de Trump desactivadas."},
    "status_on":  {"fr": "✅ Alertes Trump actives. /trump off pour désactiver.",
                   "en": "✅ Trump alerts active. /trump off to disable.",
                   "es": "✅ Alertas de Trump activas. /trump off para desactivar."},
    "status_off": {"fr": "🔕 Alertes Trump inactives. /trump on pour activer.",
                   "en": "🔕 Trump alerts inactive. /trump on to enable.",
                   "es": "🔕 Alertas de Trump inactivas. /trump on para activar."},
    "usage":      {"fr": "❓ Usage : /trump on | off | status",
                   "en": "❓ Usage: /trump on | off | status",
                   "es": "❓ Uso: /trump on | off | status"},
}


async def cmd_trump(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    lang    = get_lang(chat_id)
    args    = ctx.args

    if not args or args[0] == "status":
        key = "status_on" if chat_id in trump_subscribers else "status_off"
        await update.message.reply_text(TRUMP_TEXTS[key][lang], **SEND_KW)
        return
    if args[0] == "on":
        trump_subscribers.add(chat_id)
        _save_json(TRUMP_FILE, trump_subscribers)
        await update.message.reply_text(TRUMP_TEXTS["on"][lang], **SEND_KW)
        return
    if args[0] == "off":
        trump_subscribers.discard(chat_id)
        _save_json(TRUMP_FILE, trump_subscribers)
        await update.message.reply_text(TRUMP_TEXTS["off"][lang], **SEND_KW)
        return
    await update.message.reply_text(TRUMP_TEXTS["usage"][lang], **SEND_KW)


# ── /tz ──────────────────────────────────────────────────────────────────────

TZ_TEXTS = {
    "set": {
        "fr": "🌍 Fuseau horaire défini : <b>{tz}</b>\nToutes tes alertes afficheront l'heure en <b>{tz}</b>.",
        "en": "🌍 Timezone set to <b>{tz}</b>\nAll your alerts will show time in <b>{tz}</b>.",
        "es": "🌍 Zona horaria configurada: <b>{tz}</b>\nTodas tus alertas mostrarán la hora en <b>{tz}</b>.",
    },
    "invalid": {
        "fr": "❌ Fuseau invalide : <code>{tz}</code>\nExemples : <code>America/Toronto</code>  <code>Europe/Paris</code>  <code>UTC</code>  <code>ET</code>  <code>CET</code>",
        "en": "❌ Invalid timezone: <code>{tz}</code>\nExamples: <code>America/Toronto</code>  <code>Europe/Paris</code>  <code>UTC</code>  <code>ET</code>  <code>CET</code>",
        "es": "❌ Zona horaria inválida: <code>{tz}</code>\nEjemplos: <code>America/Toronto</code>  <code>Europe/Paris</code>  <code>UTC</code>  <code>ET</code>  <code>CET</code>",
    },
    "status": {
        "fr": "🌍 Fuseau actuel : <b>{tz}</b>  |  Heure : <code>{now}</code>\nChange avec /tz &lt;fuseau&gt;  ex: /tz America/Toronto",
        "en": "🌍 Current timezone: <b>{tz}</b>  |  Time: <code>{now}</code>\nChange with /tz &lt;timezone&gt;  ex: /tz America/Toronto",
        "es": "🌍 Zona horaria actual: <b>{tz}</b>  |  Hora: <code>{now}</code>\nCambia con /tz &lt;zona&gt;  ej: /tz America/Toronto",
    },
    "usage": {
        "fr": "❓ Usage : /tz &lt;fuseau&gt;\nExemples : <code>America/Toronto</code>  <code>Europe/Paris</code>  <code>ET</code>  <code>CET</code>  <code>UTC</code>",
        "en": "❓ Usage: /tz &lt;timezone&gt;\nExamples: <code>America/Toronto</code>  <code>Europe/Paris</code>  <code>ET</code>  <code>CET</code>  <code>UTC</code>",
        "es": "❓ Uso: /tz &lt;zona&gt;\nEjemplos: <code>America/Toronto</code>  <code>Europe/Paris</code>  <code>ET</code>  <code>CET</code>  <code>UTC</code>",
    },
}


async def cmd_tz(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    from datetime import datetime, timezone as _tz

    chat_id = str(update.effective_chat.id)
    lang    = get_lang(chat_id)

    if not ctx.args:
        current = get_tz(chat_id)
        try:
            now_str = datetime.now(_tz.utc).astimezone(ZoneInfo(current)).strftime("%H:%M %Z")
        except Exception:
            now_str = "?"
        await update.message.reply_text(
            TZ_TEXTS["status"][lang].format(tz=current, now=now_str), **SEND_KW
        )
        return

    raw = ctx.args[0].strip()
    # Résout l'alias si connu
    iana = TZ_ALIASES.get(raw.upper(), raw)

    # Valide le nom IANA
    try:
        ZoneInfo(iana)
    except (ZoneInfoNotFoundError, KeyError):
        await update.message.reply_text(
            TZ_TEXTS["invalid"][lang].format(tz=raw), **SEND_KW
        )
        return

    timezones[chat_id] = iana
    _save_json(TZ_FILE, timezones)
    await update.message.reply_text(
        TZ_TEXTS["set"][lang].format(tz=iana), **SEND_KW
    )


# ── /market ───────────────────────────────────────────────────────────────────

MARKET_TEXTS = {
    "on": {
        "fr": ("🎯 <b>Alertes marché activées</b> — polling toutes les 60s.\n"
               "Tu recevras uniquement les news à fort impact : Fed, tarifs, NFP, CPI, "
               "earnings surprises, guerres, crashes...\n"
               "<i>Filtre intelligent : zéro news random.</i>"),
        "en": ("🎯 <b>Market alerts enabled</b> — polling every 60s.\n"
               "You'll only receive high-impact news: Fed, tariffs, NFP, CPI, "
               "earnings surprises, wars, crashes...\n"
               "<i>Smart filter: zero random news.</i>"),
        "es": ("🎯 <b>Alertas de mercado activadas</b> — polling cada 60s.\n"
               "Solo recibirás noticias de alto impacto: Fed, aranceles, NFP, IPC, "
               "sorpresas de resultados, guerras, crashes...\n"
               "<i>Filtro inteligente: cero noticias aleatorias.</i>"),
    },
    "off": {
        "fr": "🔕 Alertes marché désactivées.",
        "en": "🔕 Market alerts disabled.",
        "es": "🔕 Alertas de mercado desactivadas.",
    },
    "status_on": {
        "fr": "✅ Alertes marché actives — polling 60s. /market off pour désactiver.",
        "en": "✅ Market alerts active — polling 60s. /market off to disable.",
        "es": "✅ Alertas de mercado activas — polling 60s. /market off para desactivar.",
    },
    "status_off": {
        "fr": "🔕 Alertes marché inactives. /market on pour activer.",
        "en": "🔕 Market alerts inactive. /market on to enable.",
        "es": "🔕 Alertas de mercado inactivas. /market on para activar.",
    },
    "usage": {
        "fr": "❓ Usage : /market on | off | status",
        "en": "❓ Usage: /market on | off | status",
        "es": "❓ Uso: /market on | off | status",
    },
}


async def cmd_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    lang    = get_lang(chat_id)
    args    = ctx.args

    if not args or args[0] == "status":
        key = "status_on" if chat_id in market_subscribers else "status_off"
        await update.message.reply_text(MARKET_TEXTS[key][lang], **SEND_KW)
        return
    if args[0] == "on":
        market_subscribers.add(chat_id)
        _save_json(MARKET_SUB, market_subscribers)
        await update.message.reply_text(MARKET_TEXTS["on"][lang], **SEND_KW)
        return
    if args[0] == "off":
        market_subscribers.discard(chat_id)
        _save_json(MARKET_SUB, market_subscribers)
        await update.message.reply_text(MARKET_TEXTS["off"][lang], **SEND_KW)
        return
    await update.message.reply_text(MARKET_TEXTS["usage"][lang], **SEND_KW)


# ── /breaking ─────────────────────────────────────────────────────────────────

BREAKING_TEXTS = {
    "on":         {"fr": "⚡ Breaking news activées. Tu recevras une alerte immédiate sur FOMC, missiles, crashes, Trump speech, NFP, CPI...",
                   "en": "⚡ Breaking news alerts enabled. You'll get instant alerts for FOMC, missiles, crashes, Trump speech, NFP, CPI...",
                   "es": "⚡ Alertas de breaking news activadas. Recibirás alertas instantáneas sobre FOMC, misiles, crashes, Trump, NFP, CPI..."},
    "off":        {"fr": "🔕 Breaking news désactivées.",
                   "en": "🔕 Breaking news alerts disabled.",
                   "es": "🔕 Alertas de breaking news desactivadas."},
    "status_on":  {"fr": "✅ Breaking news actives — polling toutes les 90s. /breaking off pour désactiver.",
                   "en": "✅ Breaking news active — polling every 90s. /breaking off to disable.",
                   "es": "✅ Breaking news activas — polling cada 90s. /breaking off para desactivar."},
    "status_off": {"fr": "🔕 Breaking news inactives. /breaking on pour activer.",
                   "en": "🔕 Breaking news inactive. /breaking on to enable.",
                   "es": "🔕 Breaking news inactivas. /breaking on para activar."},
    "usage":      {"fr": "❓ Usage : /breaking on | off | status",
                   "en": "❓ Usage: /breaking on | off | status",
                   "es": "❓ Uso: /breaking on | off | status"},
}


async def cmd_breaking(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    lang    = get_lang(chat_id)
    args    = ctx.args

    if not args or args[0] == "status":
        key = "status_on" if chat_id in breaking_subscribers else "status_off"
        await update.message.reply_text(BREAKING_TEXTS[key][lang], **SEND_KW)
        return
    if args[0] == "on":
        breaking_subscribers.add(chat_id)
        _save_json(BREAKING_SUB, breaking_subscribers)
        await update.message.reply_text(BREAKING_TEXTS["on"][lang], **SEND_KW)
        return
    if args[0] == "off":
        breaking_subscribers.discard(chat_id)
        _save_json(BREAKING_SUB, breaking_subscribers)
        await update.message.reply_text(BREAKING_TEXTS["off"][lang], **SEND_KW)
        return
    await update.message.reply_text(BREAKING_TEXTS["usage"][lang], **SEND_KW)


# ── /structure ───────────────────────────────────────────────────────────────

async def cmd_structure(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from technical_analysis import format_structure_message
    from formatter import _split_message
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg  = await _loading_msg(update, "🔍 Analyse de structure en cours…")
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_all_assets)
    await msg.delete()
    for part in _split_message(format_structure_message(data)):
        await update.message.reply_text(part, **SEND_KW)


# ── /divergence ───────────────────────────────────────────────────────────────

async def cmd_divergence(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from technical_analysis import format_divergence_message
    from formatter import _split_message
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg  = await _loading_msg(update, "🔍 Détection de divergences RSI…")
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_all_assets)
    await msg.delete()
    for part in _split_message(format_divergence_message(data)):
        await update.message.reply_text(part, **SEND_KW)


# ── /confluence ───────────────────────────────────────────────────────────────

async def cmd_confluence(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from technical_analysis import format_confluence_message
    from formatter import _split_message
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg  = await _loading_msg(update, "🎯 Calcul du score de confluence…")
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_all_assets)
    await msg.delete()
    for part in _split_message(format_confluence_message(data)):
        await update.message.reply_text(part, **SEND_KW)


# ── /risk-calc ────────────────────────────────────────────────────────────────

_RISK_USAGE = {
    "fr": (
        "📐 <b>Risk Calculator</b>\n\n"
        "Usage : <code>/risk-calc &lt;compte&gt; &lt;risque%&gt; &lt;entrée&gt; &lt;stop&gt; [tp]</code>\n\n"
        "Exemple :\n"
        "<code>/risk-calc 10000 1 1.0850 1.0800 1.0950</code>\n"
        "<code>/risk-calc 50000 0.5 19500 19200</code>"
    ),
    "en": (
        "📐 <b>Risk Calculator</b>\n\n"
        "Usage: <code>/risk-calc &lt;account&gt; &lt;risk%&gt; &lt;entry&gt; &lt;stop&gt; [tp]</code>\n\n"
        "Examples:\n"
        "<code>/risk-calc 10000 1 1.0850 1.0800 1.0950</code>\n"
        "<code>/risk-calc 50000 0.5 19500 19200</code>"
    ),
    "es": (
        "📐 <b>Calculadora de Riesgo</b>\n\n"
        "Uso: <code>/risk-calc &lt;cuenta&gt; &lt;riesgo%&gt; &lt;entrada&gt; &lt;stop&gt; [tp]</code>\n\n"
        "Ejemplos:\n"
        "<code>/risk-calc 10000 1 1.0850 1.0800 1.0950</code>\n"
        "<code>/risk-calc 50000 0.5 19500 19200</code>"
    ),
}


async def cmd_risk_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from html import escape as _esc_html
    lang = get_lang(str(update.effective_chat.id))

    if not ctx.args or len(ctx.args) < 4:
        await update.message.reply_text(_RISK_USAGE.get(lang, _RISK_USAGE["en"]), **SEND_KW)
        return

    try:
        account   = float(ctx.args[0].replace(",", ""))
        risk_pct  = float(ctx.args[1])
        entry     = float(ctx.args[2])
        stop      = float(ctx.args[3])
        tp        = float(ctx.args[4]) if len(ctx.args) >= 5 else None
    except ValueError:
        await update.message.reply_text(_RISK_USAGE.get(lang, _RISK_USAGE["en"]), **SEND_KW)
        return

    if account <= 0 or risk_pct <= 0 or entry <= 0 or stop <= 0:
        await update.message.reply_text("❌ Valeurs invalides — tous les paramètres doivent être positifs.", **SEND_KW)
        return
    if stop == entry:
        await update.message.reply_text("❌ Stop loss = entrée — distance nulle.", **SEND_KW)
        return

    risk_usd    = account * risk_pct / 100
    sl_dist     = abs(entry - stop)
    direction   = "Long 📈" if entry > stop else "Short 📉"
    pos_units   = risk_usd / sl_dist
    std_lots    = pos_units / 100_000

    # Pips (utile pour forex ~1-2 ou JPY ~100+)
    if entry < 10:
        pip_factor = 10_000
        pip_label  = "pips"
    elif entry < 200:
        pip_factor = 100
        pip_label  = "pips"
    else:
        pip_factor = 1
        pip_label  = "points"

    sl_pips = sl_dist * pip_factor

    lines = [
        "📐 <b>RISK CALCULATOR</b>",
        "═" * 32,
        f"Compte      : <b>${account:,.0f}</b>",
        f"Risque      : <b>{risk_pct}%</b>  →  <b>${risk_usd:,.2f}</b>",
        f"Direction   : {direction}",
        "─" * 28,
        f"Entrée      : <code>{entry}</code>",
        f"Stop Loss   : <code>{stop}</code>",
        f"Distance SL : <code>{sl_dist:.5g}</code>  ({sl_pips:.1f} {pip_label})",
        "─" * 28,
        f"Taille pos. : <b>{pos_units:,.0f} unités</b>",
        f"             → <b>{std_lots:.2f} lot standard</b> (forex 100k)",
    ]

    if tp is not None:
        if (direction.startswith("Long") and tp <= entry) or \
           (direction.startswith("Short") and tp >= entry):
            lines.append("⚠️ Take profit dans la mauvaise direction")
        else:
            tp_dist   = abs(tp - entry)
            tp_pips   = tp_dist * pip_factor
            rr_ratio  = tp_dist / sl_dist
            gain_usd  = risk_usd * rr_ratio
            rr_emoji  = "✅" if rr_ratio >= 2 else ("🟡" if rr_ratio >= 1 else "❌")
            lines += [
                "─" * 28,
                f"Take Profit : <code>{tp}</code>",
                f"Distance TP : <code>{tp_dist:.5g}</code>  ({tp_pips:.1f} {pip_label})",
                f"R:R         : <b>1:{rr_ratio:.2f}</b>  {rr_emoji}",
                f"Gain potent.: <b>${gain_usd:,.2f}</b>",
            ]

    lines += [
        "═" * 32,
        "⚡ <b>tradingLIVE</b> | /confluence | /structure",
    ]
    await update.message.reply_text("\n".join(lines), **SEND_KW)


# ── /vix ──────────────────────────────────────────────────────────────────────

async def cmd_vix(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from macro_data import fetch_vix, format_vix_message
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg  = await _loading_msg(update, "📊 Récupération du VIX…")
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_vix)
    await msg.delete()
    await update.message.reply_text(format_vix_message(data), **SEND_KW)


# ── /yield-curve ──────────────────────────────────────────────────────────────

async def cmd_yield_curve(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from macro_data import fetch_yield_curve, format_yield_curve_message
    from formatter import _split_message
    lang = get_lang(str(update.effective_chat.id))
    await _typing(update)
    msg  = await _loading_msg(update, "📈 Récupération des taux US…")
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_yield_curve)
    await msg.delete()
    for part in _split_message(format_yield_curve_message(data)):
        await update.message.reply_text(part, **SEND_KW)


# ── /ask ─────────────────────────────────────────────────────────────────────

ASK_TEXTS = {
    "usage": {
        "fr": "❓ Pose une question : <code>/ask Que pense tu de l'EUR/USD aujourd'hui ?</code>",
        "en": "❓ Ask a question: <code>/ask What do you think about EUR/USD today?</code>",
        "es": "❓ Haz una pregunta: <code>/ask ¿Qué piensas sobre el EUR/USD hoy?</code>",
    },
    "loading": {
        "fr": "🤔 Analyse en cours…",
        "en": "🤔 Thinking…",
        "es": "🤔 Analizando…",
    },
    "error": {
        "fr": "❌ L'IA n'a pas pu répondre. Réessaie.",
        "en": "❌ The AI couldn't answer. Please try again.",
        "es": "❌ La IA no pudo responder. Inténtalo de nuevo.",
    },
}


async def cmd_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from ai_analyst import ask_ai
    from html import escape as _esc_html
    lang = get_lang(str(update.effective_chat.id))

    question = " ".join(ctx.args).strip() if ctx.args else ""
    if not question:
        await update.message.reply_text(ASK_TEXTS["usage"][lang], **SEND_KW)
        return

    await _typing(update)
    msg = await _loading_msg(update, ASK_TEXTS["loading"][lang])

    loop   = asyncio.get_running_loop()
    answer = await loop.run_in_executor(None, ask_ai, question, lang)

    await msg.delete()

    if not answer:
        await update.message.reply_text(ASK_TEXTS["error"][lang], **SEND_KW)
        return

    header = f"🤖 <b>tradingLIVE AI</b>\n<i>{_esc_html(question)}</i>\n" + "─" * 28
    from formatter import _split_message
    for part in _split_message(f"{header}\n\n{_esc_html(answer)}"):
        await update.message.reply_text(part, **SEND_KW)


# ── Callback handler pour les boutons inline ─────────────────────────────────

async def _button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les clics sur les boutons inline _KB_ALERT."""
    query   = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    lang    = get_lang(str(chat_id))
    loop    = asyncio.get_running_loop()

    async def _send(text: str) -> None:
        from formatter import _split_message
        for part in _split_message(text):
            await ctx.bot.send_message(chat_id=chat_id, text=part, **SEND_KW)

    data = query.data

    if data == "cmd_price":
        msg = await ctx.bot.send_message(chat_id=chat_id,
                                         text=t("loading_price", lang), **SEND_KW)
        assets = await loop.run_in_executor(None, fetch_all_assets)
        await msg.delete()
        _PRICE_BTN_SYMBOLS = ["XAU/USD", "NAS100", "US500", "GBP/USD", "EUR/USD"]
        for part in fmt.build_price_message(assets, symbols=_PRICE_BTN_SYMBOLS):
            await ctx.bot.send_message(chat_id=chat_id, text=part, **SEND_KW)

    elif data == "cmd_day":
        msg = await ctx.bot.send_message(chat_id=chat_id,
                                         text="📅 Chargement du calendrier…", **SEND_KW)
        events = await loop.run_in_executor(None, get_day_events)
        await msg.delete()
        now    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        header = f"{DAY_HEADER[lang]}\n🕒 <i>{now} UTC</i>\n" + "═" * 32
        body   = DAY_EMPTY[lang] if not events else format_day_message(events)
        footer = "─" * 32 + "\n⚡ <b>tradingLIVE</b> | /week | /price | /deep"
        from formatter import _split_message
        for part in _split_message(f"{header}\n\n{body}\n\n{footer}"):
            await ctx.bot.send_message(chat_id=chat_id, text=part, **SEND_KW)

    elif data == "cmd_deep":
        await ctx.bot.send_message(
            chat_id=chat_id,
            text="💡 Lance <b>/deep</b> pour l'analyse complète (prend ~15s).",
            **SEND_KW,
        )

    elif data == "cmd_vix":
        from macro_data import fetch_vix, format_vix_message
        msg    = await ctx.bot.send_message(chat_id=chat_id, text="⏳ VIX…", **SEND_KW)
        vix    = await loop.run_in_executor(None, fetch_vix)
        await msg.delete()
        await _send(format_vix_message(vix))


# ── /session ──────────────────────────────────────────────────────────────────

_SESSION_SCHEDULE = [
    # (open_utc, close_utc, name, flag, pairs, color)
    (21,  6,  "Sydney",   "🇦🇺", "AUD/USD  NZD/USD  USD/JPY",  "🟡"),
    (23,  8,  "Tokyo",    "🇯🇵", "USD/JPY  AUD/JPY  EUR/JPY",  "🟠"),
    ( 7, 16,  "Londres",  "🇬🇧", "EUR/USD  GBP/USD  EUR/GBP",  "🔵"),
    (12, 21,  "New York", "🇺🇸", "USD/CAD  EUR/USD  GBP/USD",  "🔴"),
]

def _is_session_open(open_h: int, close_h: int, hour: int) -> bool:
    if open_h < close_h:
        return open_h <= hour < close_h
    return hour >= open_h or hour < close_h   # nuit (ex: 21h→6h)


async def cmd_session(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang    = get_lang(str(update.effective_chat.id))
    now_utc = datetime.now(timezone.utc)
    hour    = now_utc.hour
    minute  = now_utc.minute
    now_str = now_utc.strftime("%H:%M UTC")

    lines = [
        "🕐 <b>SESSIONS DE TRADING</b>",
        f"<i>Maintenant : {now_str}</i>",
        "═" * 32,
        "",
    ]

    # Sessions actives
    active = []
    for open_h, close_h, name, flag, pairs, color in _SESSION_SCHEDULE:
        is_open = _is_session_open(open_h, close_h, hour)
        if is_open:
            # Temps restant
            close_min_total  = close_h * 60
            current_min      = hour * 60 + minute
            if close_h <= open_h:
                close_min_total += 24 * 60
                if current_min < open_h * 60:
                    current_min += 24 * 60
            rem_min = close_min_total - current_min
            rem_str = f"{rem_min // 60}h{rem_min % 60:02d}m restantes"
            lines.append(f"{color} <b>{flag} {name}</b>  🟢 OUVERTE")
            lines.append(f"   Paires actives : <code>{pairs}</code>")
            lines.append(f"   Ferme dans : {rem_str} (à {close_h:02d}:00 UTC)")
            lines.append("")
            active.append(name)

    # Sessions fermées
    lines.append("─" * 28)
    for open_h, close_h, name, flag, pairs, color in _SESSION_SCHEDULE:
        is_open = _is_session_open(open_h, close_h, hour)
        if not is_open:
            # Temps avant ouverture
            open_min_total  = open_h * 60
            current_min     = hour * 60 + minute
            wait_min        = open_min_total - current_min
            if wait_min < 0:
                wait_min += 24 * 60
            wait_str = f"dans {wait_min // 60}h{wait_min % 60:02d}m"
            lines.append(f"⚫ {flag} <b>{name}</b>  🔴 Fermée — ouvre {wait_str}")

    lines.append("")

    # Overlap actif ?
    active_set = set(active)
    overlaps = []
    if {"Londres", "New York"} <= active_set:
        overlaps.append("🔥 <b>Overlap Londres/New York</b> — volatilité maximale ! (12h-16h UTC)")
    if {"Tokyo", "Londres"} <= active_set:
        overlaps.append("⚡ <b>Overlap Tokyo/Londres</b> — EUR/JPY et GBP/JPY actifs (07h-08h UTC)")
    if {"Sydney", "Tokyo"} <= active_set:
        overlaps.append("🌏 <b>Overlap Sydney/Tokyo</b> — AUD/JPY volatil")

    if overlaps:
        for o in overlaps:
            lines.append(o)
        lines.append("")

    # Conseil selon session
    if not active:
        lines.append("💤 <i>Aucune session majeure ouverte — volatilité faible.</i>")
        lines.append("<i>Bon moment pour analyser, pas pour trader.</i>")
    elif "New York" in active_set and "Londres" in active_set:
        lines.append("🎯 <b>Meilleure fenêtre de la journée</b> — liquidité et volatilité max.")
        lines.append("EUR/USD GBP/USD USD/CAD : setups les plus fiables.")
    elif "Londres" in active_set:
        lines.append("📈 Session Londres — EUR et GBP en mouvement, volume solide.")
    elif "New York" in active_set:
        lines.append("🇺🇸 Session NY — attention aux news US et données macro.")
    elif "Tokyo" in active_set:
        lines.append("🇯🇵 Session Tokyo — JPY et AUD en focus. Ranges souvent plus serrés.")

    lines += [
        "",
        "═" * 32,
        "⚡ <b>tradingLIVE</b> | /price | /day | /vix",
    ]

    from formatter import _split_message
    for part in _split_message("\n".join(lines)):
        await update.message.reply_text(part, **SEND_KW)


# ── /ping ─────────────────────────────────────────────────────────────────────

async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(str(update.effective_chat.id))
    t0   = time.monotonic()
    msg  = await update.message.reply_text(t("ping_wait", lang), parse_mode=ParseMode.HTML)
    ms   = int((time.monotonic() - t0) * 1000)
    await msg.edit_text(t("ping_ok", lang, ms=ms), parse_mode=ParseMode.HTML)


# ── /uptime ───────────────────────────────────────────────────────────────────

async def cmd_uptime(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang  = get_lang(str(update.effective_chat.id))
    diff  = datetime.now(timezone.utc) - START_TIME
    total = int(diff.total_seconds())
    h, r  = divmod(total, 3600)
    m, s  = divmod(r, 60)
    since = START_TIME.strftime("%Y-%m-%d %H:%M UTC")
    await update.message.reply_text(t("uptime", lang, since=since, h=h, m=m, s=s), **SEND_KW)


# ── unknown ───────────────────────────────────────────────────────────────────

async def cmd_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(str(update.effective_chat.id))
    await update.message.reply_text(t("unknown_cmd", lang), parse_mode=ParseMode.HTML)


# ── post-init ─────────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("price",       "Real-time prices / Prix temps réel"),
        BotCommand("correlation", "Correlations / Corrélations"),
        BotCommand("day",         "Today's events (High+Medium) / Calendrier du jour"),
        BotCommand("week",        "Full week calendar / Calendrier semaine"),
        BotCommand("deep",        "Deep AI analysis / Analyse profonde IA"),
        BotCommand("flashnews",   "Flash news by impact — ex: /flashnews 6"),
        BotCommand("newreport",   "US news report"),
        BotCommand("us",          "Latest US news"),
        BotCommand("structure",    "Market structure: HH/HL/BOS/CHoCH"),
        BotCommand("divergence",  "RSI divergences — bullish/bearish regular & hidden"),
        BotCommand("confluence",  "Confluence score 0-10 — évite les faux signaux"),
        BotCommand("risk_calc",   "Risk calculator — /risk-calc 10000 1 1.085 1.080 1.095"),
        BotCommand("vix",         "VIX — indice de peur & volatilité"),
        BotCommand("yield_curve", "Yield curve US 3M/5Y/10Y/30Y"),
        BotCommand("ask",         "Ask the AI — /ask What do you think about gold?"),
        BotCommand("market",      "Market-moving alerts (60s) — /market on|off"),
        BotCommand("breaking",    "Breaking alerts: FOMC/missile/crash — /breaking on|off"),
        BotCommand("trump",       "Trump alerts — /trump on|off"),
        BotCommand("alert",       "Periodic alerts — /alert on 4"),
        BotCommand("tz",          "Timezone: /tz America/Toronto | Europe/Paris | ET..."),
        BotCommand("lang",        "Language: /lang fr | en | es"),
        BotCommand("session",     "Sessions de trading — Asia/London/NY en cours"),
        BotCommand("ping",        "Bot status"),
        BotCommand("uptime",      "Uptime"),
        BotCommand("help",        "Help / Aide"),
        BotCommand("start",       "Start"),
    ])
    for chat_id_str, hours in subscribers.items():
        app.job_queue.run_repeating(
            _alert_job, interval=hours * 3600, first=60,
            name=f"alert_{chat_id_str}", data=int(chat_id_str),
        )
    app.job_queue.run_repeating(
        _trump_job, interval=TRUMP_POLL_INTERVAL, first=30, name="trump_monitor",
    )
    app.job_queue.run_repeating(
        _breaking_job, interval=BREAKING_POLL_INTERVAL, first=15, name="breaking_monitor",
    )
    app.job_queue.run_repeating(
        _market_news_job, interval=MARKET_POLL_INTERVAL, first=20, name="market_monitor",
    )
    log.info(
        "Bot prêt. alerts:%d | trump:%d | breaking:%d | market:%d",
        len(subscribers), len(trump_subscribers), len(breaking_subscribers), len(market_subscribers),
    )


# ── entry point ───────────────────────────────────────────────────────────────

def run_bot() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN manquant dans .env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("lang",        cmd_lang))
    app.add_handler(CommandHandler("price",       cmd_price))
    app.add_handler(CommandHandler("correlation", cmd_correlation))
    app.add_handler(CommandHandler("day",         cmd_day))
    app.add_handler(CommandHandler("week",        cmd_week))
    app.add_handler(CommandHandler("deep",        cmd_deep))
    app.add_handler(CommandHandler("flashnews",   cmd_flashnews))
    app.add_handler(CommandHandler("newreport",   cmd_newreport))
    app.add_handler(CommandHandler("us",          cmd_us))
    app.add_handler(CommandHandler("structure",    cmd_structure))
    app.add_handler(CommandHandler("divergence",  cmd_divergence))
    app.add_handler(CommandHandler("confluence",  cmd_confluence))
    app.add_handler(CommandHandler("risk_calc",   cmd_risk_calc))
    app.add_handler(CommandHandler("riskcalc",    cmd_risk_calc))
    app.add_handler(CommandHandler("vix",         cmd_vix))
    app.add_handler(CommandHandler("yield_curve", cmd_yield_curve))
    app.add_handler(CommandHandler("yieldcurve",  cmd_yield_curve))
    app.add_handler(CommandHandler("ask",         cmd_ask))
    app.add_handler(CommandHandler("tz",          cmd_tz))
    app.add_handler(CommandHandler("market",      cmd_market))
    app.add_handler(CommandHandler("breaking",    cmd_breaking))
    app.add_handler(CommandHandler("trump",       cmd_trump))
    app.add_handler(CommandHandler("alert",       cmd_alert))
    app.add_handler(CommandHandler("session",     cmd_session))
    app.add_handler(CommandHandler("ping",        cmd_ping))
    app.add_handler(CommandHandler("uptime",      cmd_uptime))
    app.add_handler(CallbackQueryHandler(_button_callback))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    log.info("tradingLIVE démarré.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
