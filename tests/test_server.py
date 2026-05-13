from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest

from captainslog import db
from captainslog.server import agenda, capture, complete, delete_entry, get_entry, list_categories, search, update_entry


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "log.db")
    db.init_db()
    return tmp_path


def _entry_id(result: str) -> int:
    match = re.search(r"#(\d+)", result)
    assert match is not None
    return int(match.group(1))


def _last_entry_id(result: str) -> int:
    matches = re.findall(r"#(\d+)", result)
    assert matches
    return int(matches[-1])


def test_capture_update_get_and_delete(fresh_db) -> None:
    del fresh_db
    created = capture(title="Write docs", body="Draft the usage notes", category="work")
    entry_id = _entry_id(created)

    entry = get_entry(entry_id)
    assert entry["title"] == "Write docs"
    assert entry["body"] == "Draft the usage notes"
    assert entry["category"] == "work"
    assert entry["depends_on"] == []

    updated = update_entry(
        entry_id,
        title="Write better docs",
        body="Draft the usage notes and examples",
        priority="high",
        status="in_progress",
    )
    assert updated == f"Entry #{entry_id} updated."

    entry = get_entry(entry_id)
    assert entry["title"] == "Write better docs"
    assert entry["body"] == "Draft the usage notes and examples"
    assert entry["priority"] == "high"
    assert entry["status"] == "in_progress"

    deleted = delete_entry(entry_id)
    assert deleted == f"Entry #{entry_id} deleted."
    assert get_entry(entry_id) == f"No entry found with id {entry_id}."


def test_agenda_filters_and_blocking(fresh_db) -> None:
    del fresh_db
    today = datetime.now(UTC).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()

    overdue = _entry_id(capture(title="Overdue task", due_date=yesterday, category="work"))
    high = _entry_id(capture(title="High priority task", due_date=tomorrow, priority="high", category="work"))
    in_progress = _entry_id(capture(title="In progress task", due_date=tomorrow, category="home"))
    done = _entry_id(capture(title="Done task", due_date=today.isoformat(), category="home"))
    blocked = _entry_id(
        capture(title="Blocked task", depends_on=[overdue], category="work", due_date=today.isoformat())
    )

    update_entry(in_progress, status="in_progress")
    update_entry(done, status="done")

    items = agenda(target_date=today.isoformat())
    ids = {item["id"] for item in items}
    assert overdue in ids
    assert high in ids
    assert in_progress in ids
    assert blocked in ids
    assert done not in ids

    first = items[0]
    assert first["id"] == in_progress
    assert first["blocked_by"] == []
    assert next(item for item in items if item["id"] == blocked)["blocked_by"] == [overdue]


def test_category_listing_and_recurrence(fresh_db) -> None:
    del fresh_db
    today = datetime.now(UTC).date().isoformat()
    recurring = _entry_id(capture(title="Weekly review", due_date=today, recurrence="weekly", category="work"))
    capture(title="Normal task", category="work")
    done = _entry_id(capture(title="Completed task", category="home"))
    update_entry(done, status="done")

    categories = list_categories()
    work = next(item for item in categories if item["category"] == "work")
    home = next(item for item in categories if item["category"] == "home")
    assert work["total"] == 2
    assert work["open"] == 2
    assert home["done"] == 1

    result = complete(recurring)
    next_id = _last_entry_id(result)
    next_entry = get_entry(next_id)
    assert next_entry["recurrence"] == "weekly"
    assert next_entry["due_date"] == (date.fromisoformat(today) + timedelta(weeks=1)).isoformat()
    assert get_entry(recurring)["status"] == "done"


def test_search_uses_fts_or_fallback(fresh_db) -> None:
    del fresh_db
    capture(title="Grocery run", body="Buy milk and eggs", category="home")
    capture(title="Other task", body="Something unrelated", category="work")

    results = search("milk", limit=10)
    assert results
    assert results[0]["title"] == "Grocery run"

    if db.FTS5_AVAILABLE:
        phrase = search('"Buy milk"', limit=10)
        assert phrase
        assert phrase[0]["title"] == "Grocery run"
