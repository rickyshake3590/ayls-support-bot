import json
import os
import pathlib

import pytest

from bot import config
from bot.content_loader import load_chunks


def write_json(root: pathlib.Path, name: str, data: object) -> None:
    (root / name).write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def site(tmp_path: pathlib.Path) -> pathlib.Path:
    write_json(tmp_path, "schedule.json", [
        {"id": "d1-open", "day": 1, "date": "2026-12-04", "start": "09:00",
         "end": "10:00", "title": "Opening Plenary", "location": "Main Hall",
         "public": True},
        {"id": "d1-secret", "day": 1, "date": "2026-12-04", "start": "11:00",
         "end": "12:00", "title": "Closed Session", "public": False},
    ])
    write_json(tmp_path, "faq.json", [
        {"id": "a", "question": "Q1?", "answer": "Plain answer."},
        {"id": "b", "question": "Q2?", "lead": "Covered:", "bullets": ["Food"],
         "note": "Extras not covered."},
        {"id": "c", "question": "Q3?", "answer": "TBC"},
    ])
    write_json(tmp_path, "event.json", {
        "name": "Test Summit", "organiser": "Org", "city": "Chiang Mai",
        "country": "Thailand", "dates": {"start": "2026-12-04", "end": "2026-12-06"},
        "days": [{"day": 1, "label": "Fri", "title": "Day 1"}],
        "contact": {"email": "a@example.org", "whatsapp": "+65 0"},
        "fees": [{"text": "SGD 300", "source": "Terms"}],
    })
    (tmp_path / "venue.md").write_text("# Venue\n\n## Address\nTBC\n", encoding="utf-8")
    (tmp_path / "travel.md").write_text(
        "# Travel\n\n## Visas\nApply early.\n\n## Transport\nTBC\n", encoding="utf-8"
    )
    return tmp_path


def test_public_false_items_are_excluded(site: pathlib.Path) -> None:
    ids = {c["id"] for c in load_chunks(site)}
    assert "schedule:d1-open" in ids
    assert "schedule:d1-secret" not in ids


def test_tbc_answers_and_sections_are_excluded(site: pathlib.Path) -> None:
    ids = {c["id"] for c in load_chunks(site)}
    assert "faq:c" not in ids
    assert "venue:1" not in ids
    assert "travel:1" in ids
    assert "travel:2" not in ids


def test_ids_are_unique(site: pathlib.Path) -> None:
    ids = [c["id"] for c in load_chunks(site)]
    assert len(ids) == len(set(ids))


def test_duplicate_ids_raise(site: pathlib.Path) -> None:
    write_json(site, "speakers.json", [
        {"id": "x", "name": "A", "role": "R", "organization": "O", "bio": "B"},
        {"id": "x", "name": "B", "role": "R", "organization": "O", "bio": "B"},
    ])
    with pytest.raises(ValueError, match="duplicate"):
        load_chunks(site)


def test_schedule_chunk_contains_fields(site: pathlib.Path) -> None:
    chunk = next(c for c in load_chunks(site) if c["id"] == "schedule:d1-open")
    assert "Opening Plenary" in chunk["text"]
    assert "09:00-10:00" in chunk["text"]
    assert "location: Main Hall" in chunk["text"]
    assert chunk["meta"] == {"source": "schedule", "url": f"{config.BASE_URL}/itinerary"}


def test_faq_formats(site: pathlib.Path) -> None:
    chunks = {c["id"]: c["text"] for c in load_chunks(site)}
    assert chunks["faq:a"] == "Question: Q1?\nAnswer: Plain answer."
    assert chunks["faq:b"] == "Question: Q2?\nAnswer: Covered:\n- Food\nExtras not covered."


def test_event_chunk_lists_fees_with_source(site: pathlib.Path) -> None:
    chunk = next(c for c in load_chunks(site) if c["id"].startswith("event:"))
    assert "Test Summit" in chunk["text"]
    assert "SGD 300 (source: Terms)" in chunk["text"]
    assert chunk["meta"]["url"] == f"{config.BASE_URL}/"


def test_chunks_without_public_page_cite_home(site: pathlib.Path) -> None:
    chunk = next(c for c in load_chunks(site) if c["id"] == "travel:1")
    assert chunk["meta"]["url"] == f"{config.BASE_URL}/"


SITE_CONTENT = os.environ.get("SITE_CONTENT_DIR", "")


@pytest.mark.skipif(not pathlib.Path(SITE_CONTENT).is_dir(), reason="set SITE_CONTENT_DIR")
def test_real_site_content_loads() -> None:
    chunks = load_chunks(pathlib.Path(SITE_CONTENT))
    assert len(chunks) > 50
    assert all(c["text"] and c["meta"]["url"].startswith(config.BASE_URL) for c in chunks)
