from types import SimpleNamespace
from typing import Any

import pytest

from bot import handlers, rag


class FakeMessage:
    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_: Any) -> None:
        self.replies.append(text)


def update(message: FakeMessage, chat_id: int = 111) -> Any:
    return SimpleNamespace(effective_message=message, effective_chat=SimpleNamespace(id=chat_id))


@pytest.fixture(autouse=True)
def handles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORGANISER_HANDLES", "@alice, @bob")


def test_handoff_text_lists_handles() -> None:
    text = handlers.handoff_text()
    assert "@alice, @bob" in text
    assert handlers.AVAILABILITY_NOTE in text


def test_handoff_text_puts_lead_first() -> None:
    assert handlers.handoff_text("Lead line.").startswith("Lead line.\n")


@pytest.mark.asyncio
async def test_sensitive_question_skips_llm_and_gives_handles() -> None:
    message = FakeMessage("I need a refund")
    await handlers.private_message(update(message), None)
    assert len(message.replies) == 1
    assert message.replies[0].startswith(handlers.SENSITIVE_REPLY)
    assert "@alice, @bob" in message.replies[0]


@pytest.mark.asyncio
async def test_non_text_gets_text_only_reply_with_handles() -> None:
    message = FakeMessage(text=None)
    await handlers.private_message(update(message), None)
    assert handlers.TEXT_ONLY_REPLY in message.replies[0]
    assert "@alice, @bob" in message.replies[0]


@pytest.mark.asyncio
async def test_no_answer_gives_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_answer(question: str) -> None:
        return None

    monkeypatch.setattr(rag, "answer", no_answer)
    message = FakeMessage("Best pizza in Rome?")
    await handlers.private_message(update(message), None)
    assert message.replies[0].startswith(handlers.NOT_FOUND)
    assert "@alice, @bob" in message.replies[0]


@pytest.mark.asyncio
async def test_answer_is_sent_with_source(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(question: str) -> rag.Answer:
        return rag.Answer(text="SGD 300.", url="https://example.org/", mode="llm")

    monkeypatch.setattr(rag, "answer", answered)
    message = FakeMessage("What is the fee?")
    await handlers.private_message(update(message), None)
    assert message.replies == ["SGD 300.\n\nSource: https://example.org/"]


def test_missing_handles_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORGANISER_HANDLES", " , ")
    with pytest.raises(RuntimeError):
        handlers.handoff_text()
