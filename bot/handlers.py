"""Telegram handlers: Q&A, human handoff (organiser handles), sensitive-topic check, error handling.

Handoff is direct: the bot lists organiser handles and the user messages them on Telegram.
The bot keeps no handoff records.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from . import config, rag
from .ratelimit import limiter

log = logging.getLogger("bot.handlers")

SUMMIT_LINE = (
    "Asia Youth Leadership Summit 2026, Chiang Mai, Thailand, 4-6 December 2026 "
    "(organised by The Salvation Army)."
)
PRIVACY_LINE = "Please do not send passport, payment or other sensitive details here."
AVAILABILITY_NOTE = "Organisers reply when they are available, and we cannot promise a reply time."
HUMAN_LABEL = "Do you need human assistance?"
HUMAN_CALLBACK = "human"

GREETING = f"Welcome. Ask me about the summit.\n{SUMMIT_LINE}\n{PRIVACY_LINE}"
NOT_FOUND = "I could not find that in the official summit information."
EXTRACTIVE_NOTE = "Our assistant is busy, here is the most relevant official information:"
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


def human_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(HUMAN_LABEL, callback_data=HUMAN_CALLBACK)]])


def handoff_text(lead: str = "") -> str:
    """The organiser handles, with an optional line in front."""
    handles = ", ".join(config.organiser_handles())
    parts = [lead, f"Please message one of our organisers directly on Telegram: {handles}.",
             AVAILABILITY_NOTE]
    return "\n".join(part for part in parts if part)


def is_sensitive(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)


def answer_text(result: rag.Answer) -> str:
    prefix = f"{EXTRACTIVE_NOTE}\n\n" if result.mode == "extractive" else ""
    return f"{prefix}{result.text}\n\nSource: {result.url}"


async def _reply(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    message = update.callback_query.message if update.callback_query else update.effective_message
    if message is not None:
        await message.reply_text(text, reply_markup=markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, GREETING, human_markup())


async def human(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    await _reply(update, handoff_text())


async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any non-command private message: answer it from the summit content."""
    message = update.effective_message
    if message is None:
        return

    if not message.text:
        await message.reply_text(f"{TEXT_ONLY_REPLY}\n\n{handoff_text()}", reply_markup=human_markup())
        return

    question = message.text
    chat_id = update.effective_chat.id

    if is_sensitive(question):
        await message.reply_text(handoff_text(SENSITIVE_REPLY), reply_markup=human_markup())
        return

    if not limiter.allow(chat_id):
        await message.reply_text(RATE_LIMIT_REPLY)
        return

    result = await rag.answer(question)
    if result is None:
        await message.reply_text(handoff_text(NOT_FOUND), reply_markup=human_markup())
        return
    await message.reply_text(answer_text(result), reply_markup=human_markup())


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Log the exception type only, plus Telegram's own error text. That text is an API
    # explanation, never user content.
    err = context.error
    if isinstance(err, TelegramError):
        log.error("handler error: %s: %s", type(err).__name__, err.message)
    else:
        log.error("handler error: %s", type(err).__name__)
    if isinstance(update, Update) and update.effective_chat and update.effective_chat.type == "private":
        try:
            await _reply(update, handoff_text(ERROR_REPLY), human_markup())
        except Exception:  # the error reply itself must never crash polling
            log.error("could not send error reply")

