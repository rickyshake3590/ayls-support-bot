"""Turn site content/ records into natural-language chunks for embedding.

Each chunk carries a citation URL. Routes come from the live site (one route
per section, no anchors). Sections with no public page cite the home page.
"""

import json
import pathlib
from collections.abc import Iterator
from typing import Any

from . import config

Chunk = dict[str, Any]

# Public route for each content file. None means no public page yet.
ROUTES: dict[str, str | None] = {
    "event": "/",
    "schedule": "/itinerary",
    "speakers": "/speakers",
    "faq": "/",
    "venue": None,
    "travel": None,
}

TBC = "TBC"


def _url(stem: str) -> str:
    route = ROUTES.get(stem)
    return f"{config.BASE_URL}{route or '/'}"


def _event_parts(i: dict[str, Any]) -> dict[str, str]:
    """One chunk per topic, so each question matches a short, focused text."""
    days = "; ".join(f"Day {d['day']} ({d['label']}): {d['title']}" for d in i["days"])
    fees = "; ".join(f"{f['text']} (source: {f['source']})" for f in i.get("fees", []))
    contact = i["contact"]
    return {
        "overview": (
            f"{i['name']} is organised by {i['organiser']}. "
            f"It takes place in {i['city']}, {i['country']}."
        ),
        "dates": f"Dates: {i['dates']['start']} to {i['dates']['end']}. Days: {days}.",
        "contact": (
            f"Contact for the summit: email {contact['email']}. "
            f"WhatsApp: {contact['whatsapp']}."
        ),
        "fees": f"Registration fee and cost of the summit: {fees}.",
    }


def _schedule(i: dict[str, Any]) -> str:
    return (
        f"Programme item: {i['title']}. Day {i['day']} ({i['date']}), "
        f"{i['start']}{'-' + i['end'] if i.get('end') else ''}, "
        f"location: {i.get('location', TBC)}. "
        f"{i.get('description', '')}"
    ).strip()


def _speaker(i: dict[str, Any]) -> str:
    return (
        f"Speaker: {i['name']}. {i.get('role', '')}, {i.get('organization', '')}. "
        f"{i.get('bio', '')}"
    )


def _faq(i: dict[str, Any]) -> str:
    if "answer" in i:
        body = i["answer"]
    else:
        lines = [i.get("lead", "")]
        lines += [f"- {b}" for b in i.get("bullets", [])]
        lines.append(i.get("note", ""))
        body = "\n".join(line for line in lines if line)
    return f"Question: {i['question']}\nAnswer: {body}"


def _generic(i: dict[str, Any]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in i.items() if k not in ("id", "public"))


FORMAT = {
    "schedule": _schedule,
    "speakers": _speaker,
    "faq": _faq,
}


def _is_hidden(item: dict[str, Any]) -> bool:
    """True when the item must not reach the bot: public:false, or an unfinished TBC answer."""
    if item.get("public", True) is False:
        return True
    return item.get("answer", "").strip() == TBC


def _chunk(chunk_id: str, text: str, stem: str) -> Chunk:
    return {"id": chunk_id, "text": text, "meta": {"source": stem, "url": _url(stem)}}


def _json_chunks(path: pathlib.Path) -> Iterator[Chunk]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if path.stem == "event":
        for key, text in _event_parts(data).items():
            yield _chunk(f"event:{key}", text, path.stem)
        return
    items = data if isinstance(data, list) else [data]
    fmt = FORMAT.get(path.stem, _generic)
    for n, item in enumerate(items):
        if _is_hidden(item):
            continue
        yield _chunk(f"{path.stem}:{item.get('id', n)}", fmt(item), path.stem)


def _markdown_chunks(path: pathlib.Path) -> Iterator[Chunk]:
    text = path.read_text(encoding="utf-8")
    for n, section in enumerate(text.split("\n## ")):
        section = section.strip()
        _, _, body = section.partition("\n")
        if body.strip() in ("", TBC):
            continue
        yield _chunk(f"{path.stem}:{n}", section, path.stem)


def load_chunks(root: pathlib.Path | None = None) -> list[Chunk]:
    """Return every public chunk under root, with unique ids. Raises on duplicates."""
    root = root or pathlib.Path(config.CONTENT_DIR)
    chunks: list[Chunk] = []
    for path in sorted(root.glob("*.json")):
        chunks.extend(_json_chunks(path))
    for path in sorted(root.glob("*.md")):
        chunks.extend(_markdown_chunks(path))

    ids = [c["id"] for c in chunks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate chunk ids: {sorted(duplicates)}")
    return chunks
