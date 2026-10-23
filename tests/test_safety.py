import pytest

from bot.handlers import SENSITIVE_KEYWORDS, is_sensitive


@pytest.mark.parametrize("keyword", SENSITIVE_KEYWORDS)
def test_each_keyword_triggers(keyword: str) -> None:
    assert is_sensitive(f"I have a question about {keyword}")


def test_match_is_case_insensitive() -> None:
    assert is_sensitive("My PASSPORT was lost")


@pytest.mark.parametrize("text", [
    "What time is lunch?",
    "Is food provided?",
    "Who is the speaker from UNHCR?",
])
def test_ordinary_questions_do_not_trigger(text: str) -> None:
    assert not is_sensitive(text)
