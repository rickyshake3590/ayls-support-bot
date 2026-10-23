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


def test_handoff_text_lists_each_handle_as_a_bullet() -> None:
    text = handlers.handoff_text()
    assert f"{handlers.BLUE} @alice" in text
    assert f"{handlers.BLUE} @bob" in text
    assert "Talk to an organiser" in text
    assert "<i>" in text


def test_handoff_lead_comes_first_and_is_escaped() -> None:
    text = handlers.handoff_text("Use <b> & stay safe.")
    assert text.startswith(f"{handlers.ORANGE} Use &lt;b&gt; &amp; stay safe.")


def test_render_body_formats_question_answer_and_bullets() -> None:
    body = "Question: What is included?\nAnswer: Covered:\n- Food\n- Rooms"
    assert handlers.render_body(body) == (
        "<b>What is included?</b>\nCovered:\n"
        f"{handlers.ORANGE} Food\n{handlers.ORANGE} Rooms"
    )


def test_render_body_escapes_html() -> None:
    assert "&lt;script&gt;" in handlers.render_body("<script>x</script>")


def test_extractive_answer_has_note_and_link() -> None:
    text = handlers.format_answer(rag.Answer(text="Answer: Yes.", url="https://example.org/", mode="extractive"))
    assert text.startswith(f"<i>{handlers.esc(handlers.EXTRACTIVE_NOTE)}</i>")
    assert 'href="https://example.org/"' in text


@pytest.mark.asyncio
async def test_sensitive_question_skips_llm_and_gives_handles() -> None:
    message = FakeMessage("I need a refund")
    await handlers.private_message(update(message), None)
    assert len(message.replies) == 1
    assert handlers.esc(handlers.SENSITIVE_REPLY) in message.replies[0]
    assert f"{handlers.BLUE} @alice" in message.replies[0]


@pytest.mark.asyncio
async def test_non_text_gets_text_only_reply_with_handles() -> None:
    message = FakeMessage(text=None)
    await handlers.private_message(update(message), None)
    assert handlers.TEXT_ONLY_REPLY in message.replies[0]
    assert f"{handlers.BLUE} @bob" in message.replies[0]


@pytest.mark.asyncio
async def test_no_answer_gives_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_answer(question: str) -> None:
        return None

    monkeypatch.setattr(rag, "answer", no_answer)
    message = FakeMessage("Best pizza in Rome?")
    await handlers.private_message(update(message), None)
    assert handlers.NOT_FOUND in message.replies[0]
    assert f"{handlers.BLUE} @alice" in message.replies[0]


@pytest.mark.asyncio
async def test_answer_is_sent_with_source_link(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(question: str) -> rag.Answer:
        return rag.Answer(text="SGD 300.", url="https://example.org/", mode="llm")

    monkeypatch.setattr(rag, "answer", answered)
    message = FakeMessage("What is the fee?")
    await handlers.private_message(update(message), None)
    assert "SGD 300." in message.replies[0]
    assert 'href="https://example.org/"' in message.replies[0]


def test_missing_handles_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORGANISER_HANDLES", " , ")
    with pytest.raises(RuntimeError):
        handlers.handoff_text()
