"""
daily_digest.py
Deux envois automatiques par jour aux abonnes /daily :

  1. MATIN - a 07:00 (heure locale du user via /tz) :
     tous les evenements economiques du jour (calendrier).

  2. RESULTATS - une fois que TOUS les events du jour sont termines
     (dernier event + buffer pour laisser publier l'actual) :
     les resultats de tous les events avec analyse de surprise.

Abonnement via la commande /daily on|off|status.
Le job tourne toutes les 5 min et dedouble par date (jamais 2x le meme jour).
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from economic_calendar import get_day_events, format_day_message
from result_command import format_results_message
from subscription import subscription_manager

log = logging.getLogger(__name__)

DIGEST_SUB_FILE   = Path(__file__).parent / "digest_subscribers.json"
DIGEST_STATE_FILE = Path(__file__).parent / "digest_state.json"

MORNING_HOUR        = 7    # 07:00 heure locale
RESULTS_BUFFER_MIN  = 45   # minutes apres le dernier event avant d'envoyer les resultats

SEND_KW = dict(parse_mode="HTML", disable_web_page_preview=True)


# -- Persistance ---------------------------------------------------------------

def _load_set(path: Path) -> set:
    try:
        if path.exists():
            return set(json.loads(path.read_text()))
    except Exception as exc:
        log.warning("daily_digest load set %s: %s", path, exc)
    return set()


def _load_dict(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as exc:
        log.warning("daily_digest load dict %s: %s", path, exc)
    return {}


def _save(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(list(data) if isinstance(data, set) else data, indent=2))
    except Exception as exc:
        log.warning("daily_digest save %s: %s", path, exc)


digest_subscribers: set  = _load_set(DIGEST_SUB_FILE)
_digest_state:      dict = _load_dict(DIGEST_STATE_FILE)


# -- Textes --------------------------------------------------------------------

TEXTS = {
    "on": {
        "fr": ("\U0001F305 <b>Brief quotidien active</b>\n"
               "• Chaque matin a <b>07:00</b> (ton fuseau /tz) : tous les evenements du jour\n"
               "• En fin de journee : les resultats de tous les evenements\n"
               "<i>Desactive avec /daily off</i>"),
        "en": ("\U0001F305 <b>Daily brief enabled</b>\n"
               "• Every morning at <b>07:00</b> (your /tz timezone): all of today's events\n"
               "• End of day: results of all events\n"
               "<i>Disable with /daily off</i>"),
        "es": ("\U0001F305 <b>Resumen diario activado</b>\n"
               "• Cada manana a las <b>07:00</b> (tu zona /tz): todos los eventos del dia\n"
               "• Al final del dia: resultados de todos los eventos\n"
               "<i>Desactiva con /daily off</i>"),
        "ar": ("\U0001F305 <b>تم تفعيل الملخّص اليومي</b>\n"
               "• كل صباح الساعة <b>07:00</b> (/tz): كل أحداث اليوم\n"
               "• نهاية اليوم: نتائج كل الأحداث\n"
               "<i>/daily off</i>"),
    },
    "off": {
        "fr": "\U0001F319 <b>Brief quotidien desactive.</b> Reactive avec /daily on",
        "en": "\U0001F319 <b>Daily brief disabled.</b> Re-enable with /daily on",
        "es": "\U0001F319 <b>Resumen diario desactivado.</b> Reactiva con /daily on",
        "ar": "\U0001F319 <b>تم إيقاف الملخّص اليومي.</b> /daily on",
    },
    "status_on": {
        "fr": "\U0001F305 Brief quotidien : <b>ACTIVE</b> (07:00 + resultats fin de journee)",
        "en": "\U0001F305 Daily brief: <b>ON</b> (07:00 + end-of-day results)",
        "es": "\U0001F305 Resumen diario: <b>ACTIVADO</b> (07:00 + resultados al final del dia)",
        "ar": "\U0001F305 الملخّص اليومي: <b>مفعّل</b> (07:00)",
    },
    "status_off": {
        "fr": "\U0001F319 Brief quotidien : <b>DESACTIVE</b>. Active avec /daily on",
        "en": "\U0001F319 Daily brief: <b>OFF</b>. Enable with /daily on",
        "es": "\U0001F319 Resumen diario: <b>DESACTIVADO</b>. Activa con /daily on",
        "ar": "\U0001F319 الملخّص اليومي: <b>متوقّف</b>. /daily on",
    },
    "usage": {
        "fr": "❓ Usage : /daily on | off | status",
        "en": "❓ Usage: /daily on | off | status",
        "es": "❓ Uso: /daily on | off | status",
        "ar": "❓ /daily on | off | status",
    },
    "morning_header": {
        "fr": "\U0001F305 <b>BRIEF DU MATIN - EVENEMENTS DU JOUR</b>",
        "en": "\U0001F305 <b>MORNING BRIEF - TODAY'S EVENTS</b>",
        "es": "\U0001F305 <b>RESUMEN MATINAL - EVENTOS DEL DIA</b>",
        "ar": "\U0001F305 <b>ملخّص الصباح - أحداث اليوم</b>",
    },
    "morning_empty": {
        "fr": "☕ Aucun evenement economique USD aujourd'hui. Bonne journee de trading !",
        "en": "☕ No USD economic events today. Have a great trading day!",
        "es": "☕ Sin eventos economicos USD hoy. Buen dia de trading!",
        "ar": "☕ لا توجد أحداث اقتصادية للدولار اليوم.",
    },
    "results_header": {
        "fr": "\U0001F306 <b>BILAN DU JOUR - RESULTATS</b>",
        "en": "\U0001F306 <b>END OF DAY - RESULTS</b>",
        "es": "\U0001F306 <b>CIERRE DEL DIA - RESULTADOS</b>",
        "ar": "\U0001F306 <b>حصيلة اليوم - النتائج</b>",
    },
}


def _t(key: str, lang: str) -> str:
    block = TEXTS.get(key, {})
    return block.get(lang, block.get("fr", ""))


# -- Helpers -------------------------------------------------------------------

def _split_message(text: str, limit: int = 4000) -> list:
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        parts.append(current)
    return parts


def _user_tz(chat_id: str) -> ZoneInfo:
    try:
        import bot
        return ZoneInfo(bot.get_tz(chat_id))
    except Exception:
        return ZoneInfo("UTC")


def _user_lang(chat_id: str) -> str:
    try:
        import bot
        return bot.get_lang(chat_id)
    except Exception:
        return "fr"


# -- Commande /daily -----------------------------------------------------------

async def cmd_daily(update, ctx) -> None:
    user_id = update.effective_user.id
    if not subscription_manager.is_user_active(user_id):
        await update.message.reply_text("❌ **Subscription requise**", parse_mode="Markdown")
        return

    chat_id = str(update.effective_chat.id)
    lang    = _user_lang(chat_id)
    args    = ctx.args

    if not args or args[0] == "status":
        key = "status_on" if chat_id in digest_subscribers else "status_off"
        await update.message.reply_text(_t(key, lang), **SEND_KW)
        return
    if args[0] == "on":
        digest_subscribers.add(chat_id)
        _save(DIGEST_SUB_FILE, digest_subscribers)
        await update.message.reply_text(_t("on", lang), **SEND_KW)
        return
    if args[0] == "off":
        digest_subscribers.discard(chat_id)
        _save(DIGEST_SUB_FILE, digest_subscribers)
        await update.message.reply_text(_t("off", lang), **SEND_KW)
        return
    await update.message.reply_text(_t("usage", lang), **SEND_KW)


# -- Job periodique (toutes les 5 min) -----------------------------------------

async def daily_digest_job(context) -> None:
    if not digest_subscribers:
        return

    import asyncio
    now_utc = datetime.now(timezone.utc)
    loop    = asyncio.get_running_loop()

    events = await loop.run_in_executor(None, get_day_events)

    all_done = False
    if events:
        last_event = max(e.date for e in events)
        all_done   = now_utc >= last_event + timedelta(minutes=RESULTS_BUFFER_MIN)

    utc_today = now_utc.date().isoformat()
    dirty     = False

    for chat_id in list(digest_subscribers):
        state = _digest_state.setdefault(chat_id, {})
        tz    = _user_tz(chat_id)
        lang  = _user_lang(chat_id)
        local = now_utc.astimezone(tz)
        local_today = local.date().isoformat()

        # 1. Brief du matin a 07:00 local
        if local.hour == MORNING_HOUR and state.get("morning") != local_today:
            header = f"{_t('morning_header', lang)}\n\U0001F552 <i>{local.strftime('%Y-%m-%d')}</i>\n" + "=" * 28
            body   = format_day_message(events) if events else _t("morning_empty", lang)
            footer = "-" * 28 + "\n⚡ <b>tradingLIVE</b> | /day | /week | /result"
            await _send(context, chat_id, f"{header}\n\n{body}\n\n{footer}")
            state["morning"] = local_today
            dirty = True

        # 2. Bilan resultats une fois tous les events termines
        if events and all_done and state.get("results") != utc_today:
            header = _t("results_header", lang)
            body   = format_results_message(events, now_utc)
            await _send(context, chat_id, f"{header}\n\n{body}")
            state["results"] = utc_today
            dirty = True

    if dirty:
        _save(DIGEST_STATE_FILE, _digest_state)


async def _send(context, chat_id: str, text: str) -> None:
    for part in _split_message(text):
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=part, **SEND_KW)
        except Exception as exc:
            log.warning("daily_digest send [%s]: %s", chat_id, exc)
