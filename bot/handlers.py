"""Telegram handlers: Q&A, human handoff (organiser handles), sensitive-topic check, error handling.

Handoff is direct: the bot lists organiser handles and the user messages them on Telegram.
The bot keeps no handoff records.

Messages use Telegram HTML. Every dynamic string goes through esc() first.
"""

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from . import config, rag
from .ratelimit import limiter

log = logging.getLogger("bot.handlers")

BLUE = "🔹"
ORANGE = "🔸"

SUMMIT_TITLE = "Asia Youth Leadership Summit 2026"
SUMMIT_DETAILS = "Chiang Mai, Thailand, 4-6 December 2026\nOrganised by The Salvation Army"
PRIVACY_LINE = "Please do not send passport, payment or other sensitive details here."
AVAILABILITY_NOTE = "Organisers reply when they are available. We cannot promise a reply time."
HUMAN_LABEL = "Do you need human assistance?"
HUMAN_CALLBACK = "human"

EXTRACTIVE_NOTE = "Assistant is busy. Here is the most relevant official information."
NOT_FOUND = "I could not find that in the official summit information."
RATE_LIMIT_REPLY = "You are sending messages quickly, please wait a moment."
TEXT_ONLY_REPLY = "I can only answer text questions at the moment."
SENSITIVE_REPLY = (
    "This sounds important. Please contact an organiser now. "
    "If anyone is in immediate danger, contact local emergency services."
)
ERROR_REPLY = "Sorry, something went wrong."

# Phrases that skip the LLM and offer a human straight away. Matched case-insensitively.
SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "safeguarding",
    "abuse",
    "harassment",
    "medical",
    "emergency",
    "visa problem",
    "refund",
    "complaint",
    "passport",
)


def esc(text: str) -> str:
    return html.escape(text)


def bullets(items: list[str], marker: str = BLUE) -> str:
    return "\n".join(f"{marker} {esc(item)}" for item in items)


def human_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(HUMAN_LABEL, callback_data=HUMAN_CALLBACK)]])


def handoff_text(lead: str = "") -> str:
    """Organiser handles under a heading, with an optional lead line in front."""
    handles = config.organiser_handles()
    parts = []
    if lead:
        parts.append(f"{ORANGE} {esc(lead)}")
    parts.append("👤 <b>Talk to an organiser</b>")
    parts.append("Message one of these on Telegram:")
    parts.append(bullets(handles))
    parts.append(f"<i>{esc(AVAILABILITY_NOTE)}</i>")
    return "\n".join(parts)


def greeting() -> str:
    return "\n".join([
        "👋 <b>Welcome</b>",
        "Ask me anything about the summit.",
        "",
        f"📍 <b>{esc(SUMMIT_TITLE)}</b>",
        esc(SUMMIT_DETAILS),
        "",
        f"⚠️ <i>{esc(PRIVACY_LINE)}</i>",
    ])


def render_body(text: str) -> str:
    """Turn the content format (Question:/Answer:/- bullets) into readable Telegram text."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Question:"):
            lines.append(f"{BLUE} <b>{esc(line[len('Question:'):].strip())}</b>")
        elif line.startswith("Answer:"):
            lines.append(esc(line[len("Answer:"):].strip()))
        elif line.startswith("- "):
            lines.append(f"{ORANGE} {esc(line[2:].strip())}")
        else:
            lines.append(esc(line))
    return "\n".join(lines).strip()


def format_answer(result: rag.Answer) -> str:
    parts = []
    if result.mode == "extractive":
        parts.append(f"⏳ <i>{esc(EXTRACTIVE_NOTE)}</i>\n\n")
    parts.append(render_body(result.text))
    parts.append(f'\n\n🔗 <a href="{html.escape(result.url)}">Official summit page</a>')
    return "".join(parts)


def is_sensitive(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)


async def _send(message: Message | None, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    if message is None:
        return
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=markup,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update.effective_message, greeting(), human_markup())


async def human(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.effective_message
    await _send(message, handoff_text())


async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any non-command private message: answer it from the summit content."""
    message = update.effective_message
    if message is None:
        return

    if not message.text:
        await _send(message, handoff_text(TEXT_ONLY_REPLY), human_markup())
        return

    question = message.text
    chat_id = update.effective_chat.id

    if is_sensitive(question):
        await _send(message, handoff_text(SENSITIVE_REPLY), human_markup())
        return

    if not limiter.allow(chat_id):
        await _send(message, f"{ORANGE} {esc(RATE_LIMIT_REPLY)}")
        return

    result = await rag.answer(question)
    if result is None:
        await _send(message, handoff_text(NOT_FOUND), human_markup())
        return
    await _send(message, format_answer(result), human_markup())


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Log the exception type only, plus Telegram's own error text. That text is an API
    # explanation, never user content.
    err = context.error
    if isinstance(err, TelegramError):
        log.error("handler error: %s: %s", type(err).__name__, err.message)
    else:
        log.error("handler error: %s", type(err).__name__)
    if isinstance(update, Update) and update.effective_chat and update.effective_chat.type == "private":
        message = update.callback_query.message if update.callback_query else update.effective_message
        try:
            await _send(message, handoff_text(ERROR_REPLY), human_markup())
        except Exception:  # the error reply itself must never crash polling
            log.error("could not send error reply")
