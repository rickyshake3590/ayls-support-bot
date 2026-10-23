from bot.rag import schedule_answer_from

ITEMS = [
    {"day": "1", "start": "09:00", "span": "9:00 AM - 9:10 AM", "title": "Opening", "session": "no", "url": "u"},
    {"day": "1", "start": "13:00", "span": "1:00 PM - 2:00 PM", "title": "Keynote A", "session": "yes", "url": "u"},
    {"day": "1", "start": "15:00", "span": "3:00 PM - 4:00 PM", "title": "Panel B", "session": "yes", "url": "u"},
    {"day": "2", "start": "10:00", "span": "10:00 AM - 11:00 AM", "title": "Keynote C", "session": "yes", "url": "u"},
]


def test_day_sessions_listed_under_heading_in_time_order() -> None:
    answer = schedule_answer_from(ITEMS, "What are the sessions on day 1?")
    assert answer is not None and answer.mode == "schedule"
    assert answer.text == "Heading: Day 1 Sessions\n- 1:00 PM - 2:00 PM: Keynote A\n- 3:00 PM - 4:00 PM: Panel B"


def test_day_itinerary_includes_all_items_for_that_day() -> None:
    answer = schedule_answer_from(ITEMS, "Show the day 1 itinerary")
    assert answer is not None
    assert answer.text.startswith("Heading: Day 1 Itinerary\n- 9:00 AM - 9:10 AM: Opening")
    assert "Keynote C" not in answer.text


def test_sessions_without_a_day_span_all_days() -> None:
    answer = schedule_answer_from(ITEMS, "Names of all sessions")
    assert answer is not None and answer.text.startswith("Heading: Sessions")
    assert "Keynote C" in answer.text


def test_other_questions_go_to_the_model() -> None:
    assert schedule_answer_from(ITEMS, "Is there a schedule for the summit?") is None
    assert schedule_answer_from(ITEMS, "What is the registration fee?") is None
