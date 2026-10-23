"""SQLite ticket mapping: user chat <-> organiser forum topic.

Stores only IDs and timestamps. Message content never reaches this database.
"""

import pathlib
import sqlite3
import time
from dataclasses import dataclass

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_chat_id INTEGER NOT NULL,
    thread_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at INTEGER NOT NULL
)
"""


@dataclass(frozen=True)
class Ticket:
    id: int
    user_chat_id: int
    thread_id: int
    status: str
    created_at: int


def connect(path: str | None = None) -> sqlite3.Connection:
    db_path = path or config.DB_PATH
    if db_path != ":memory:":
        pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def _row(row: sqlite3.Row | None) -> Ticket | None:
    if row is None:
        return None
    return Ticket(**dict(row))


def open_ticket(conn: sqlite3.Connection, user_chat_id: int) -> Ticket | None:
    row = conn.execute(
        "SELECT * FROM tickets WHERE user_chat_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (user_chat_id,),
    ).fetchone()
    return _row(row)


def by_thread(conn: sqlite3.Connection, thread_id: int) -> Ticket | None:
    row = conn.execute(
        "SELECT * FROM tickets WHERE thread_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (thread_id,),
    ).fetchone()
    return _row(row)


def create(conn: sqlite3.Connection, user_chat_id: int, thread_id: int) -> int:
    cursor = conn.execute(
        "INSERT INTO tickets (user_chat_id, thread_id, status, created_at) VALUES (?, ?, 'open', ?)",
        (user_chat_id, thread_id, int(time.time())),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def close(conn: sqlite3.Connection, ticket_id: int) -> None:
    conn.execute("UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
    conn.commit()
