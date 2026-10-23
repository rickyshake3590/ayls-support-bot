"""Retrieval-only eval over tests/eval_questions.yaml. No LLM calls, so it is deterministic and free.

Needs a built index at INDEX_DIR (run `python -m bot.ingest` first). Skips otherwise.
"""

import pathlib
from typing import Any

import pytest
import yaml

from bot import config
from bot.rag import retrieve_sync

EVAL_FILE = pathlib.Path(__file__).parent / "eval_questions.yaml"
QUESTIONS: list[dict[str, Any]] = yaml.safe_load(EVAL_FILE.read_text(encoding="utf-8"))


def _params() -> list[Any]:
    return [pytest.param(q, id=q["question"][:60]) for q in QUESTIONS]


@pytest.fixture(autouse=True)
def require_index() -> None:
    if not pathlib.Path(config.INDEX_DIR).is_dir():
        pytest.skip("no index: run python -m bot.ingest first")


@pytest.mark.parametrize("case", _params())
def test_retrieval(case: dict[str, Any]) -> None:
    hits = retrieve_sync(case["question"])
    if case.get("expect_none"):
        assert hits == [], f"expected no hits, got {hits[0].source}: {hits[0].text[:80]}"
    else:
        expected = case["expect"].lower()
        assert any(expected in h.text.lower() for h in hits), (
            f"'{case['expect']}' not in top hits: {[h.text[:60] for h in hits]}"
        )
