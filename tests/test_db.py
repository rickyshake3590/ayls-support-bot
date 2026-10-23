from bot import db


def test_create_then_lookup_by_user_and_thread() -> None:
    conn = db.connect(":memory:")
    ticket_id = db.create(conn, user_chat_id=111, thread_id=9)
    open_for_user = db.open_ticket(conn, 111)
    assert open_for_user is not None
    assert open_for_user.id == ticket_id
    assert open_for_user.thread_id == 9
    assert db.by_thread(conn, 9) == open_for_user


def test_close_removes_ticket_from_open_lookups() -> None:
    conn = db.connect(":memory:")
    ticket_id = db.create(conn, user_chat_id=111, thread_id=9)
    db.close(conn, ticket_id)
    assert db.open_ticket(conn, 111) is None
    assert db.by_thread(conn, 9) is None


def test_second_ticket_can_open_after_close() -> None:
    conn = db.connect(":memory:")
    first = db.create(conn, user_chat_id=111, thread_id=9)
    db.close(conn, first)
    second = db.create(conn, user_chat_id=111, thread_id=12)
    assert second != first
    ticket = db.open_ticket(conn, 111)
    assert ticket is not None and ticket.thread_id == 12


def test_unknown_lookups_return_none() -> None:
    conn = db.connect(":memory:")
    assert db.open_ticket(conn, 404) is None
    assert db.by_thread(conn, 404) is None
