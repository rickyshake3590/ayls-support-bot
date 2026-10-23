"""Telegram handlers: Q&A, human handoff relay, sensitive-topic check, error handling.

Only IDs and timestamps are stored (bot/db.py). The last question lives in memory
for the ticket card and is never written to disk.
"""

import logging
from typing import Any

from telegram import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    User,
)
from telegram.ext import ContextTypes

from . import db, rag
from .ratelimit import limiter

log = logging.getLogger("bot.handlers")

SUMMIT_LINE = (
    "Asia Youth Leadership Summit 2026, Chiang Mai, Thailand, 4-6 December 2026 "
    "(organised by The Salvation Army)."
)
PRIVACY_LINE = "Please do not send passport, payment or other sensitive details here."
AVAILABILITY_NOTE = "An organiser will reply when available. We cannot promise a reply time."
HUMAN_LABEL = "Do you need human assistance?"
HUMAN_CALLBACK = "human"

GREETING = f"Welcome. Ask me about the summit.\n{SUMMIT_LINE}\n{PRIVACY_LINE}"
NOT_FOUND = "I could not find that in the official summit information. Would you like to speak to an organiser?"
EXTRACTIVE_NOTE = "Our assistant is busy, here is the most relevant official information:"
RATE_LIMIT_REPLY = "You are sending messages quickly, please wait a moment."
TEXT_ONLY_REPLY = "I can only answer text questions at the moment. Would you like to speak to an organiser?"
SENSITIVE_REPLY = (
    "This sounds important. Please speak to an organiser now. "
    "If anyone is in immediate danger, contact local emergency services."
)
ALREADY_OPEN = "You are already connected to an organiser. Type your message here."
TICKET_OPENED = f"An organiser has been notified. Please type your question. {AVAILABILITY_NOTE} Send /end to return to the assistant."
TICKET_ENDED = "You are back with the assistant. Ask your question any time."
TICKET_CLOSED_BY_ORGANISER = "An organiser has closed this conversation. Ask a question any time, or tap the button for help again."
ERROR_REPLY = "Sorry, something went wrong. Please try again, or speak to an organiser."

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


def is_sensitive(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)


def topic_name(user: User) -> str:
    handle = f"@{user.username}" if user.username else "no username"
    return f"{user.first_name} ({handle})"[:128]


def ticket_card(ticket_id: int, user: User, last_question: str) -> str:
    return (
        f"Ticket {ticket_id}\n"
        f"User: {topic_name(user)}\n"
        f"Last question: {last_question}\n\n"
        "Reply in this topic to message the user. Use /close when done."
    )


def answer_text(result: rag.Answer) -> str:
    prefix = f"{EXTRACTIVE_NOTE}\n\n" if result.mode == "extractive" else ""
    return f"{prefix}{result.text}\n\nSource: {result.url}"


async def _reply(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    message = update.callback_query.message if update.callback_query else update.effective_message
    if message is not None:
        await message.reply_text(text, reply_markup=markup)


def _conn(context: ContextTypes.DEFAULT_TYPE) -> Any:
    return context.bot_data["db"]


def _group_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return int(context.bot_data["organiser_group_id"])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, GREETING, human_markup())


async def open_human(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    user = update.effective_user
    chat_id = update.effective_chat.id
    if user is None:
        return

    conn = _conn(context)
    if db.open_ticket(conn, chat_id):
        await _reply(update, ALREADY_OPEN)
        return

    group = _group_id(context)
    topic = await context.bot.create_forum_topic(chat_id=group, name=topic_name(user))
    thread_id = topic.message_thread_id
    ticket_id = db.create(conn, chat_id, thread_id)
    last_question = context.user_data.get("last_question", "(none yet)")
    await context.bot.send_message(
        chat_id=group,
        message_thread_id=thread_id,
        text=ticket_card(ticket_id, user, last_question),
    )
    await _reply(update, TICKET_OPENED)


async def end_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    conn = _conn(context)
    ticket = db.open_ticket(conn, chat_id)
    if ticket is not None:
        group = _group_id(context)
        db.close(conn, ticket.id)
        await context.bot.send_message(
            chat_id=group, message_thread_id=ticket.thread_id, text="The user has ended this conversation."
        )
        await context.bot.close_forum_topic(chat_id=group, message_thread_id=ticket.thread_id)
    await _reply(update, TICKET_ENDED, human_markup())


async def _relay_to_organisers(message: Message, context: ContextTypes.DEFAULT_TYPE, ticket: db.Ticket) -> None:
    await context.bot.copy_message(
        chat_id=_group_id(context),
        from_chat_id=ticket.user_chat_id,
        message_id=message.message_id,
        message_thread_id=ticket.thread_id,
    )


async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any non-command private message: relay during a ticket, otherwise answer it."""
    message = update.effective_message
    chat_id = update.effective_chat.id
    if message is None:
        return
    conn = _conn(context)

    ticket = db.open_ticket(conn, chat_id)
    if ticket is not None:
        await _relay_to_organisers(message, context, ticket)
        return

    if not message.text:
        await message.reply_text(TEXT_ONLY_REPLY, reply_markup=human_markup())
        return

    question = message.text
    context.user_data["last_question"] = question

    if is_sensitive(question):
        await message.reply_text(SENSITIVE_REPLY, reply_markup=human_markup())
        return

    if not limiter.allow(chat_id):
        await message.reply_text(RATE_LIMIT_REPLY)
        return

    result = await rag.answer(question)
    if result is None:
        await message.reply_text(NOT_FOUND, reply_markup=human_markup())
        return
    await message.reply_text(answer_text(result), reply_markup=human_markup())


async def organiser_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A message posted inside an organiser topic: relay to that ticket's user."""
    message = update.effective_message
    if message is None or message.message_thread_id is None:
        return
    conn = _conn(context)
    ticket = db.by_thread(conn, message.message_thread_id)
    if ticket is None:
        return
    await context.bot.copy_message(
        chat_id=ticket.user_chat_id,
        from_chat_id=_group_id(context),
        message_id=message.message_id,
    )


async def close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/close inside an organiser topic: close the ticket, tell the user, close the topic."""
    message = update.effective_message
    if message is None or message.message_thread_id is None:
        return
    conn = _conn(context)
    ticket = db.by_thread(conn, message.message_thread_id)
    if ticket is None:
        await message.reply_text("No open ticket in this topic.")
        return
    db.close(conn, ticket.id)
    await context.bot.send_message(
        chat_id=ticket.user_chat_id, text=TICKET_CLOSED_BY_ORGANISER, reply_markup=human_markup()
    )
    await context.bot.close_forum_topic(chat_id=_group_id(context), message_thread_id=ticket.thread_id)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Log the exception type only: exception messages can contain user text.
    log.error("handler error: %s", type(context.error).__name__)
    if isinstance(update, Update) and update.effective_chat and update.effective_chat.type == "private":
        try:
            await _reply(update, ERROR_REPLY, human_markup())
        except Exception:  # the error reply itself must never crash polling
            log.error("could not send error reply")
