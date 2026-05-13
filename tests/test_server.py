from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from captainslog import db
from captainslog.server import (
    agenda,
    archive,
    capture,
    capture_many,
    complete,
    complete_many,
    delete_entry,
    delete_many,
    get_entry,
    list_categories,
    list_entries,
    search,
    stats,
    sync_to_markdown,
    sync_to_org,
    update_entry,
    update_many,
    weekly_review,
)


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", tmp_path / ".captainslog" / "log.db")
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


def test_bulk_tools_stats_archive_and_delete_many(fresh_db) -> None:
    del fresh_db
    today = datetime.now(UTC).date().isoformat()
    created = capture_many(
        [
            {"title": "Alpha", "body": "alpha body", "category": "work"},
            {"title": "Beta", "category": "work", "due_date": today},
            {"title": "Gamma", "category": "home", "recurrence": "weekly"},
            {"title": "", "category": "home"},
        ]
    )
    assert any("Logged entry #" in item for item in created)
    assert any("recurrence requires due_date" in item for item in created)
    assert any("empty title" in item for item in created)

    entries = list_entries(limit=20)
    ids = [item["id"] for item in entries]
    assert len(ids) >= 2

    updated = update_many(
        [
            {"entry_id": ids[0], "status": "in_progress", "priority": "high"},
            {"entry_id": ids[1], "clear_body": True, "status": "todo"},
            {"entry_id": 999999, "title": "does-not-exist"},
            {"entry_id": ids[0]},
        ]
    )
    assert any("updated" in item for item in updated)
    assert any("No entry found with id 999999." in item for item in updated)
    assert any("no fields to update" in item for item in updated)

    recurring = _entry_id(capture(title="Daily task", due_date=today, recurrence="daily"))
    complete_results = complete_many([ids[0], recurring, 999999, ids[0]])
    assert any("marked as done." in item for item in complete_results)
    assert any("Next occurrence created as #" in item for item in complete_results)
    assert any("No entry found with id 999999." in item for item in complete_results)
    assert any("already marked as done" in item for item in complete_results)

    overview = stats()
    assert overview["total"] >= 3
    assert "by_status" in overview
    assert "open_by_priority" in overview

    stale_id = _entry_id(capture(title="Stale task", category="ops"))
    with db.get_connection() as conn:
        conn.execute("UPDATE entries SET created_at = datetime('now', '-10 days') WHERE id = ?", (stale_id,))
        conn.commit()
    archived = archive(older_than_days=7, status="todo", action="cancel")
    assert "Archived (marked as cancelled)" in archived

    delete_msg = delete_many([stale_id, 777777])
    assert "Deleted 1 entry." in delete_msg
    assert "1 ID(s) not found." in delete_msg


def test_weekly_review_dependency_updates_and_exports(fresh_db) -> None:
    del fresh_db
    today = datetime.now(UTC).date()
    monday = today - timedelta(days=today.weekday())

    dependency = _entry_id(capture(title="Dependency task", category="work"))
    main_task = _entry_id(capture(title="Main task", category="work"))

    invalid_dep = update_entry(main_task, depends_on=[dependency, 888888])
    assert "Invalid depends_on IDs" in invalid_dep

    valid_dep = update_entry(main_task, depends_on=[dependency])
    assert valid_dep == f"Entry #{main_task} updated."
    with_dep = get_entry(main_task)
    assert with_dep["depends_on"] == [dependency]
    assert with_dep["blocked_by"] == [dependency]

    update_entry(dependency, status="done")
    unblocked = get_entry(main_task)
    assert unblocked["blocked_by"] == []

    cleared = update_entry(main_task, clear_depends_on=True)
    assert cleared == f"Entry #{main_task} updated."
    assert get_entry(main_task)["depends_on"] == []

    complete(main_task)
    review = weekly_review(week_start=monday.isoformat())
    assert review["completed"] >= 1
    assert review["week"].startswith(monday.isoformat())

    if db.FTS5_AVAILABLE:
        with pytest.raises(ValueError, match="Invalid full-text query syntax"):
            search('"unterminated', limit=5)

    org_export = sync_to_org()
    md_export = sync_to_markdown()
    assert "Exported" in org_export
    assert "Exported" in md_export

    org_path = Path.home() / ".captainslog" / "captainslog.org"
    md_path = Path.home() / ".captainslog" / "captainslog.md"
    assert org_path.exists()
    assert md_path.exists()
    assert "CaptainsLog" in org_path.read_text(encoding="utf-8")
    assert "CaptainsLog" in md_path.read_text(encoding="utf-8")
