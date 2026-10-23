from types import SimpleNamespace
from typing import Any

import pytest

from bot import db, handlers

GROUP = -1001234567890


class FakeMessage:
    def __init__(self, text: str | None = None, thread_id: int | None = None) -> None:
        self.text = text
        self.message_id = 1
        self.message_thread_id = thread_id
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_: Any) -> None:
        self.replies.append(text)


class FakeBot:
    def __init__(self) -> None:
        self.copied: list[dict[str, Any]] = []

    async def copy_message(self, **kwargs: Any) -> None:
        self.copied.append(kwargs)


def context(conn: Any) -> Any:
    return SimpleNamespace(
        bot_data={"db": conn, "organiser_group_id": GROUP},
        user_data={},
        bot=FakeBot(),
    )


def update(message: FakeMessage, chat_id: int = 111) -> Any:
    return SimpleNamespace(effective_message=message, effective_chat=SimpleNamespace(id=chat_id))


@pytest.mark.asyncio
async def test_sensitive_question_skips_llm_and_offers_human() -> None:
    message = FakeMessage("I need a refund")
    await handlers.private_message(update(message), context(db.connect(":memory:")))
    assert message.replies == [handlers.SENSITIVE_REPLY]


@pytest.mark.asyncio
async def test_non_text_without_ticket_gets_text_only_reply() -> None:
    message = FakeMessage(text=None)
    await handlers.private_message(update(message), context(db.connect(":memory:")))
    assert message.replies == [handlers.TEXT_ONLY_REPLY]


@pytest.mark.asyncio
async def test_user_message_during_ticket_is_relayed_not_answered() -> None:
    conn = db.connect(":memory:")
    db.create(conn, user_chat_id=111, thread_id=9)
    ctx = context(conn)
    message = FakeMessage("Is food provided?")
    await handlers.private_message(update(message), ctx)
    assert message.replies == []
    assert ctx.bot.copied == [{
        "chat_id": GROUP, "from_chat_id": 111, "message_id": 1, "message_thread_id": 9,
    }]


@pytest.mark.asyncio
async def test_organiser_reply_relayed_to_ticket_user() -> None:
    conn = db.connect(":memory:")
    db.create(conn, user_chat_id=111, thread_id=9)
    ctx = context(conn)
    organiser_update = SimpleNamespace(effective_message=FakeMessage("Hello", thread_id=9))
    await handlers.organiser_message(organiser_update, ctx)
    assert ctx.bot.copied == [{
        "chat_id": 111, "from_chat_id": GROUP, "message_id": 1,
    }]


@pytest.mark.asyncio
async def test_organiser_message_in_unknown_topic_is_ignored() -> None:
    ctx = context(db.connect(":memory:"))
    await handlers.organiser_message(SimpleNamespace(effective_message=FakeMessage("x", thread_id=5)), ctx)
    assert ctx.bot.copied == []
