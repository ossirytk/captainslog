"""Captain's Log MCP server — capture and agenda tools."""

import calendar
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from captainslog import db

mcp = FastMCP(
    name="captainslog",
    instructions=(
        "Captain's Log is a personal task and agenda manager. "
        "Use `capture` to log one task (supports depends_on), or `capture_many` for several at once. "
        "Use `agenda` to surface what needs attention today (includes in_progress; shows blocked_by). "
        "Use `complete` to mark one task done, or `complete_many` for several. "
        "Use `list_entries` to browse or filter the backlog (priority, date-range, sort; shows blocked_by). "
        "Use `get_entry` to read all fields of a single entry (includes depends_on and blocked_by). "
        "Use `update_entry` to edit an existing entry (supports depends_on/clear_depends_on), "
        "or `update_many` to bulk-update several entries at once. "
        "Use `delete_entry` to remove one entry, or `delete_many` for several. "
        "Use `archive` to bulk-cancel or bulk-complete stale entries older than N days. "
        "Use `search` to find entries by keyword. "
        "Use `list_categories` to see all categories with open/done counts. "
        "Use `stats` for a quick count summary by status and priority (includes currently_active count). "
        "Use `weekly_review` to summarise a week's activity. "
        "Use `sync_to_org` or `sync_to_markdown` to export the log."
    ),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ORG_PRIORITY = {"high": "[#A]", "normal": "[#B]", "low": "[#C]"}
_MD_PRIORITY = {"high": "`high`", "normal": "`normal`", "low": "`low`"}
_FTS_SYNTAX_ERROR_PATTERNS = ("fts5: syntax error", "unterminated string", "malformed")


def _compute_next_due(due_date_iso: str, recurrence: str) -> str:
    """Return the ISO date of the next occurrence."""
    d = date.fromisoformat(due_date_iso)
    if recurrence == "daily":
        d += timedelta(days=1)
    elif recurrence == "weekly":
        d += timedelta(weeks=1)
    elif recurrence == "monthly":
        month = d.month + 1
        year = d.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        max_day = calendar.monthrange(year, month)[1]
        d = d.replace(year=year, month=month, day=min(d.day, max_day))
    return d.isoformat()


def _org_tag(category: str) -> str:
    """Sanitise a category string for use as an org-mode tag."""
    tag = re.sub(r"[^A-Za-z0-9_@#%]", "_", category)
    return f":{tag}:" if tag else ""


def _org_date(iso: str) -> str:
    """Convert YYYY-MM-DD to org <YYYY-MM-DD Day> format."""
    d = date.fromisoformat(iso)
    return f"<{d.strftime('%Y-%m-%d %a')}>"


def _org_closed(iso_datetime: str) -> str:
    """Convert a datetime string to org CLOSED timestamp."""
    try:
        d = date.fromisoformat(iso_datetime[:10])
        return f"[{d.strftime('%Y-%m-%d %a')}]"
    except ValueError:
        return f"[{iso_datetime[:10]}]"


def _validate_and_dedupe_depends_on(
    conn: sqlite3.Connection,
    depends_on: list,
    entry_id: int,
) -> tuple[list[int], list[int]]:
    """Deduplicate, validate and filter a raw depends_on list.

    Returns ``(dep_ids, invalid_ids)`` where ``dep_ids`` is the cleaned list
    of valid dependency IDs (excluding self-references) and ``invalid_ids``
    contains any IDs that do not correspond to existing entries.
    """
    deduped = list(dict.fromkeys(d for d in depends_on if isinstance(d, int)))
    if not deduped:
        return [], []
    placeholders = ",".join("?" * len(deduped))
    valid_ids = {
        row[0]
        for row in conn.execute(
            f"SELECT id FROM entries WHERE id IN ({placeholders})",  # noqa: S608
            deduped,
        ).fetchall()
    }
    invalid_ids = sorted(set(deduped) - valid_ids - {entry_id})
    dep_ids = [d for d in deduped if d != entry_id and d in valid_ids]
    return dep_ids, invalid_ids


def _fetch_blocked_by_map(conn: sqlite3.Connection, entry_ids: list[int]) -> dict[int, list[int]]:
    """Return a mapping of entry_id → list of active blocker IDs for a batch of entries."""
    if not entry_ids:
        return {}
    id_placeholders = ",".join("?" * len(entry_ids))
    blocked_by_map: dict[int, list[int]] = {}
    for dr in conn.execute(
        f"""
        SELECT d.entry_id, d.depends_on_id
        FROM entry_deps d
        JOIN entries e ON e.id = d.depends_on_id
        WHERE d.entry_id IN ({id_placeholders})
          AND e.status NOT IN ('done', 'cancelled')
        """,  # noqa: S608
        entry_ids,
    ).fetchall():
        blocked_by_map.setdefault(dr[0], []).append(dr[1])
    return blocked_by_map


@mcp.tool
def capture(  # noqa: PLR0913
    title: str,
    body: str = "",
    priority: Literal["low", "normal", "high"] = "normal",
    category: str = "inbox",
    due_date: str = "",
    recurrence: Literal["daily", "weekly", "monthly", ""] = "",
    depends_on: list[int] | None = None,
) -> str:
    """Add a new task or note to the log.

    Args:
        title: Short description of the task or note.
        body: Optional longer details or context.
        priority: Task priority — low, normal, or high.
        category: Freeform category label, e.g. 'work', 'personal', 'health'.
        due_date: Optional due date in YYYY-MM-DD format.
        recurrence: Optional repeat cadence — daily, weekly, or monthly.
                    Requires due_date to be set for auto-reschedule on complete.
        depends_on: Optional list of entry IDs this task depends on (will be blocked by them).
    """
    if recurrence and not due_date:
        return "Recurrence requires due_date in YYYY-MM-DD format."

    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO entries (title, body, priority, category, due_date, recurrence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, body, priority, category, due_date or None, recurrence or None),
        )
        entry_id = cursor.lastrowid
        if depends_on:
            dep_ids, invalid_ids = _validate_and_dedupe_depends_on(conn, depends_on, entry_id)
            if invalid_ids:
                return f"Entry #{entry_id} created. Invalid depends_on IDs (not set): {invalid_ids}."
            if dep_ids:
                conn.executemany(
                    "INSERT INTO entry_deps (entry_id, depends_on_id) VALUES (?, ?)",
                    [(entry_id, dep_id) for dep_id in dep_ids],
                )
    return f"Logged entry #{entry_id}: {title!r}"


@mcp.tool
def agenda(target_date: str = "") -> list[dict]:
    """Return tasks that need attention — due today or overdue, plus high-priority items.

    Args:
        target_date: Date to use as 'today' in YYYY-MM-DD format. Defaults to today (local time).
    """
    today = target_date or date.today().isoformat()  # noqa: DTZ011
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, body, status, priority, category, due_date, recurrence, created_at
            FROM entries
            WHERE status NOT IN ('done', 'cancelled')
              AND (
                  status = 'in_progress'
                  OR due_date <= :today
                  OR priority = 'high'
              )
            ORDER BY
                CASE status WHEN 'in_progress' THEN 0 ELSE 1 END,
                CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                due_date NULLS LAST,
                created_at
            """,
            {"today": today},
        ).fetchall()
        entry_ids = [row["id"] for row in rows]
        blocked_by_map = _fetch_blocked_by_map(conn, entry_ids)
        result = []
        for row in rows:
            entry = dict(row)
            entry["blocked_by"] = blocked_by_map.get(entry["id"], [])
            result.append(entry)
    return result


@mcp.tool
def complete(entry_id: int) -> str:
    """Mark a task as done.

    If the entry has a recurrence set and a due_date, a new entry is automatically
    created with the next due date so the series continues.

    Note: if recurrence is set but no due_date is present, the next occurrence cannot
    be auto-scheduled. Set a due_date on the entry before completing to enable
    auto-scheduling.

    Args:
        entry_id: The numeric ID of the entry to complete.
    """
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT title, body, status, priority, category, due_date, recurrence FROM entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return f"No entry found with id {entry_id}."
        if row["status"] == "done":
            return f"Entry #{entry_id} is already marked as done."

        cursor = conn.execute(
            "UPDATE entries SET status = 'done', updated_at = datetime('now') WHERE id = ?",
            (entry_id,),
        )
        if cursor.rowcount == 0:
            return f"No entry found with id {entry_id}."

        recurrence = row["recurrence"]
        due_date = row["due_date"]
        if recurrence and due_date:
            next_due = _compute_next_due(due_date, recurrence)
            new_cursor = conn.execute(
                """
                INSERT INTO entries (title, body, priority, category, due_date, recurrence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (row["title"], row["body"], row["priority"], row["category"], next_due, recurrence),
            )
            new_id = new_cursor.lastrowid
            return f"Entry #{entry_id} marked as done. Next occurrence created as #{new_id} (due {next_due})."
        if recurrence and not due_date:
            return (
                f"Entry #{entry_id} marked as done. "
                "Note: recurrence is set but no due_date was present — next occurrence not scheduled."
            )

    return f"Entry #{entry_id} marked as done."


@mcp.tool
def list_entries(  # noqa: PLR0913
    category: str = "",
    status: str = "",
    priority: Literal["low", "normal", "high", ""] = "",
    due_before: str = "",
    due_after: str = "",
    sort_by: Literal["created_at", "due_date", "priority", ""] = "",
    limit: int = 50,
) -> list[dict]:
    """Browse the backlog with optional filters.

    Args:
        category: Filter by category label. Empty means all categories.
        status: Filter by status (todo, in_progress, done, cancelled). Empty means all.
        priority: Filter by priority (low, normal, high). Empty means all.
        due_before: Return only entries with due_date on or before this date (YYYY-MM-DD).
        due_after: Return only entries with due_date on or after this date (YYYY-MM-DD).
        sort_by: Sort order — created_at (default), due_date, or priority.
        limit: Maximum number of entries to return.
    """
    clauses = []
    params: list = []

    if category:
        clauses.append("category = ?")
        params.append(category)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    if due_before:
        clauses.append("due_date <= ?")
        params.append(due_before)
    if due_after:
        clauses.append("due_date >= ?")
        params.append(due_after)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    order = {
        "due_date": "due_date NULLS LAST, CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END",
        "priority": "CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, due_date NULLS LAST",
    }.get(sort_by or "", "created_at DESC")

    params.append(limit)

    query = f"""
        SELECT id, title, body, status, priority, category, due_date, recurrence, created_at
        FROM entries
        {where}
        ORDER BY {order}
        LIMIT ?
        """  # noqa: S608 — where clause is built from validated field names, not user input

    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        entry_ids = [row["id"] for row in rows]
        blocked_by_map = _fetch_blocked_by_map(conn, entry_ids)
        result = []
        for row in rows:
            entry = dict(row)
            entry["blocked_by"] = blocked_by_map.get(entry["id"], [])
            result.append(entry)
    return result


@mcp.tool
def update_entry(  # noqa: PLR0913, PLR0912
    entry_id: int,
    title: str | None = None,
    body: str | None = None,
    priority: Literal["low", "normal", "high"] | None = None,
    category: str | None = None,
    due_date: str | None = None,
    recurrence: Literal["daily", "weekly", "monthly"] | None = None,
    *,
    clear_body: bool = False,
    clear_due_date: bool = False,
    clear_recurrence: bool = False,
    status: Literal["todo", "in_progress", "done", "cancelled"] | None = None,
    depends_on: list[int] | None = None,
    clear_depends_on: bool = False,
) -> str:
    """Update fields on an existing entry. Omitted/empty-string fields are left unchanged.

    Args:
        entry_id: The numeric ID of the entry to update.
        title: New title, or omitted/empty to leave unchanged.
        body: New body text, or omitted/empty to leave unchanged.
        priority: New priority, or omitted/empty to leave unchanged.
        category: New category, or omitted/empty to leave unchanged.
        due_date: New due date (YYYY-MM-DD), or omitted/empty to leave unchanged.
        recurrence: New recurrence cadence, or omitted/empty to leave unchanged.
        clear_body: Set true to clear body text.
        clear_due_date: Set true to clear due date.
        clear_recurrence: Set true to clear recurrence.
        status: New status, or omitted/empty to leave unchanged.
        depends_on: Replace the full set of dependency IDs for this entry.
        clear_depends_on: Set true to remove all dependencies from this entry.
    """
    with db.get_connection() as conn:
        if conn.execute("SELECT 1 FROM entries WHERE id = ?", (entry_id,)).fetchone() is None:
            return f"No entry found with id {entry_id}."

        fields: list[str] = []
        params: list = []

        if title:
            fields.append("title = ?")
            params.append(title)
        if clear_body:
            fields.append("body = NULL")
        elif body:
            fields.append("body = ?")
            params.append(body)
        if priority:
            fields.append("priority = ?")
            params.append(priority)
        if category:
            fields.append("category = ?")
            params.append(category)
        if clear_due_date:
            fields.append("due_date = NULL")
        elif due_date:
            fields.append("due_date = ?")
            params.append(due_date)
        if clear_recurrence:
            fields.append("recurrence = NULL")
        elif recurrence:
            fields.append("recurrence = ?")
            params.append(recurrence)
        if status:
            fields.append("status = ?")
            params.append(status)

        dep_change = clear_depends_on or depends_on is not None
        if not fields and not dep_change:
            return "No fields to update — provide at least one update or clear_* flag."

        # Validate and prepare dep IDs before touching the database.
        dep_ids: list[int] = []
        if depends_on is not None:
            dep_ids, invalid_ids = _validate_and_dedupe_depends_on(conn, depends_on, entry_id)
            if invalid_ids:
                return f"Invalid depends_on IDs: {invalid_ids}. Entry #{entry_id} not updated."

        if fields:
            fields.append("updated_at = datetime('now')")
            params.append(entry_id)
            conn.execute(
                f"UPDATE entries SET {', '.join(fields)} WHERE id = ?",  # noqa: S608
                params,
            )

        if dep_change:
            if not fields:
                conn.execute(
                    "UPDATE entries SET updated_at = datetime('now') WHERE id = ?",
                    (entry_id,),
                )
            conn.execute("DELETE FROM entry_deps WHERE entry_id = ?", (entry_id,))
            if dep_ids:
                conn.executemany(
                    "INSERT INTO entry_deps (entry_id, depends_on_id) VALUES (?, ?)",
                    [(entry_id, dep_id) for dep_id in dep_ids],
                )

    return f"Entry #{entry_id} updated."


@mcp.tool
def delete_entry(entry_id: int) -> str:
    """Permanently delete an entry from the log.

    Args:
        entry_id: The numeric ID of the entry to delete.
    """
    with db.get_connection() as conn:
        cursor = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    if cursor.rowcount == 0:
        return f"No entry found with id {entry_id}."
    return f"Entry #{entry_id} deleted."


@mcp.tool
def search(query: str, limit: int = 20) -> list[dict]:
    """Search entries by keyword across title and body.

    Uses SQLite FTS5 for fast full-text search when available, falling back to
    LIKE-based matching otherwise.

    Args:
        query: Search term or phrase. Supports FTS5 match syntax (e.g. 'fix*', '"exact phrase"').
        limit: Maximum number of results to return.
    """
    with db.get_connection() as conn:
        if db.FTS5_AVAILABLE:
            try:
                rows = conn.execute(
                    """
                    SELECT e.id, e.title, e.body, e.status, e.priority, e.category,
                           e.due_date, e.recurrence, e.created_at,
                           snippet(entries_fts, 0, '**', '**', '...', 12) AS snippet
                    FROM entries_fts
                    JOIN entries e ON entries_fts.rowid = e.id
                    WHERE entries_fts MATCH ?
                    -- Lower bm25 score means a better match.
                    ORDER BY bm25(entries_fts)
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                error_text = str(exc).lower()
                if any(term in error_text for term in _FTS_SYNTAX_ERROR_PATTERNS):
                    msg = f"Invalid full-text query syntax: {query!r}"
                    raise ValueError(msg) from exc
                raise
        else:
            rows = []
        if not db.FTS5_AVAILABLE:
            pattern = f"%{query}%"
            rows = conn.execute(
                """
                SELECT id, title, body, status, priority, category,
                       due_date, recurrence, created_at,
                       title AS snippet
                FROM entries
                WHERE title LIKE ? OR body LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
    return [dict(row) for row in rows]


@mcp.tool
def weekly_review(week_start: str = "") -> dict:
    """Return a summary of completed, overdue, and new entries for a given week.

    Args:
        week_start: Monday of the target week in YYYY-MM-DD format.
                    Defaults to the Monday of the current week.
    """
    if week_start:
        start = date.fromisoformat(week_start)
    else:
        today = date.today()  # noqa: DTZ011
        start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    with db.get_connection() as conn:
        completed = conn.execute(
            """
            SELECT id, title, status, priority, category, due_date, recurrence, updated_at
            FROM entries
            WHERE status = 'done'
              AND updated_at >= ? AND updated_at <= ?
            ORDER BY updated_at DESC
            """,
            (start_iso, end_iso + "T23:59:59"),
        ).fetchall()

        overdue = conn.execute(
            """
            SELECT id, title, status, priority, category, due_date, recurrence, created_at
            FROM entries
            WHERE status NOT IN ('done', 'cancelled')
              AND due_date < ?
            ORDER BY due_date, priority
            """,
            (start_iso,),
        ).fetchall()

        new_entries = conn.execute(
            """
            SELECT id, title, status, priority, category, due_date, recurrence, created_at
            FROM entries
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at
            """,
            (start_iso, end_iso + "T23:59:59"),
        ).fetchall()

    return {
        "week": f"{start_iso} to {end_iso}",
        "completed": len(completed),
        "overdue": len(overdue),
        "new": len(new_entries),
        "completed_entries": [dict(r) for r in completed],
        "overdue_entries": [dict(r) for r in overdue],
        "new_entries": [dict(r) for r in new_entries],
    }


@mcp.tool
def get_entry(entry_id: int) -> dict | str:
    """Return all fields for a single entry, including body and recurrence.

    Args:
        entry_id: The numeric ID of the entry to retrieve.
    """
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, title, body, status, priority, category,
                   due_date, recurrence, created_at, updated_at
            FROM entries WHERE id = ?
            """,
            (entry_id,),
        ).fetchone()
        if row is None:
            return f"No entry found with id {entry_id}."
        entry = dict(row)
        entry["depends_on"] = [
            r[0]
            for r in conn.execute("SELECT depends_on_id FROM entry_deps WHERE entry_id = ?", (entry_id,)).fetchall()
        ]
        entry["blocked_by"] = [
            r[0]
            for r in conn.execute(
                """
                SELECT d.depends_on_id
                FROM entry_deps d
                JOIN entries e ON e.id = d.depends_on_id
                WHERE d.entry_id = ?
                  AND e.status NOT IN ('done', 'cancelled')
                """,
                (entry_id,),
            ).fetchall()
        ]
    return entry


@mcp.tool
def list_categories() -> list[dict]:
    """Return all categories with entry counts broken down by status.

    Useful for understanding the shape of the backlog at a glance.
    Returns a list of dicts with: category, total, open, done, cancelled.
    Sorted by number of open entries descending.
    """
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                category,
                COUNT(*) AS total,
                SUM(CASE WHEN status NOT IN ('done','cancelled') THEN 1 ELSE 0 END) AS open,
                SUM(CASE WHEN status = 'done'      THEN 1 ELSE 0 END) AS done,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled
            FROM entries
            GROUP BY category
            ORDER BY open DESC, total DESC
            """,
        ).fetchall()
    return [dict(row) for row in rows]


@mcp.tool
def stats() -> dict:
    """Return a summary of the log: counts by status, counts by priority, and overdue count.

    Useful for a quick situational overview without loading all entries.
    """
    today = date.today().isoformat()  # noqa: DTZ011
    with db.get_connection() as conn:
        by_status = {
            row["status"]: row["n"]
            for row in conn.execute("SELECT status, COUNT(*) AS n FROM entries GROUP BY status").fetchall()
        }
        by_priority = {
            row["priority"]: row["n"]
            for row in conn.execute(
                "SELECT priority, COUNT(*) AS n FROM entries WHERE status NOT IN ('done','cancelled') GROUP BY priority"
            ).fetchall()
        }
        overdue = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE status NOT IN ('done','cancelled') AND due_date < ?",
            (today,),
        ).fetchone()[0]
        due_today = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE status NOT IN ('done','cancelled') AND due_date = ?",
            (today,),
        ).fetchone()[0]

    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "currently_active": by_status.get("in_progress", 0),
        "open_by_priority": by_priority,
        "overdue": overdue,
        "due_today": due_today,
    }


@mcp.tool
def capture_many(entries: list[dict]) -> list[str]:
    """Add multiple tasks or notes in a single operation.

    Each entry is a dict with the same fields as `capture`:
      title (required), body, priority, category, due_date, recurrence.

    Args:
        entries: List of entry dicts. Each must have at least a 'title' key.
    """
    results: list[str] = []
    with db.get_connection() as conn:
        for item in entries:
            title = item.get("title", "").strip()
            if not title:
                results.append("Skipped entry with empty title.")
                continue
            recurrence = item.get("recurrence") or None
            if recurrence and recurrence not in ("daily", "weekly", "monthly"):
                results.append(f"Skipped {title!r}: invalid recurrence {recurrence!r}. Use daily, weekly, or monthly.")
                continue
            due_date = item.get("due_date") or None
            if recurrence and not due_date:
                results.append(f"Skipped {title!r}: recurrence requires due_date.")
                continue
            cursor = conn.execute(
                """
                INSERT INTO entries (title, body, priority, category, due_date, recurrence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    item.get("body") or None,
                    item.get("priority") or "normal",
                    item.get("category") or "inbox",
                    due_date,
                    recurrence,
                ),
            )
            results.append(f"Logged entry #{cursor.lastrowid}: {title!r}")
    return results


@mcp.tool
def complete_many(entry_ids: list[int]) -> list[str]:
    """Mark multiple entries as done in a single operation.

    Recurrence is handled per entry: if an entry recurs and has a due_date, the next
    occurrence is created. If recurrence is set but no due_date is present, no next
    occurrence can be scheduled and a warning is included in the result.

    Args:
        entry_ids: List of entry IDs to mark as done.
    """
    results: list[str] = []
    with db.get_connection() as conn:
        for entry_id in entry_ids:
            row = conn.execute(
                "SELECT title, body, status, priority, category, due_date, recurrence FROM entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
            if row is None:
                results.append(f"No entry found with id {entry_id}.")
                continue
            if row["status"] == "done":
                results.append(f"Entry #{entry_id} is already marked as done.")
                continue

            conn.execute(
                "UPDATE entries SET status = 'done', updated_at = datetime('now') WHERE id = ?",
                (entry_id,),
            )

            if row["recurrence"] and row["due_date"]:
                next_due = _compute_next_due(row["due_date"], row["recurrence"])
                new_cur = conn.execute(
                    """
                    INSERT INTO entries (title, body, priority, category, due_date, recurrence)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (row["title"], row["body"], row["priority"], row["category"], next_due, row["recurrence"]),
                )
                results.append(
                    f"Entry #{entry_id} marked as done. "
                    f"Next occurrence created as #{new_cur.lastrowid} (due {next_due})."
                )
            elif row["recurrence"] and not row["due_date"]:
                results.append(
                    f"Entry #{entry_id} marked as done. "
                    "Note: recurrence is set but no due_date was present — next occurrence not scheduled."
                )
            else:
                results.append(f"Entry #{entry_id} marked as done.")
    return results


@mcp.tool
def update_many(entries: list[dict]) -> list[str]:  # noqa: PLR0912, PLR0915
    """Update fields on multiple existing entries in a single operation.

    Each entry dict must have at least an 'entry_id' key plus at least one field
    to update. Dependency management (depends_on, clear_depends_on) is not supported
    here — use update_entry for that.

    Args:
        entries: List of dicts. Each must have 'entry_id' (int) plus any subset of:
                 title, body, priority, category, due_date, recurrence, status,
                 clear_body (bool), clear_due_date (bool), clear_recurrence (bool).
    """
    results: list[str] = []
    with db.get_connection() as conn:
        for item in entries:
            entry_id = item.get("entry_id")
            if not isinstance(entry_id, int):
                results.append(f"Skipped entry with missing or invalid entry_id: {entry_id!r}")
                continue
            if conn.execute("SELECT 1 FROM entries WHERE id = ?", (entry_id,)).fetchone() is None:
                results.append(f"No entry found with id {entry_id}.")
                continue

            fields: list[str] = []
            params: list = []

            title = item.get("title")
            body = item.get("body")
            priority = item.get("priority")
            category = item.get("category")
            due_date = item.get("due_date")
            recurrence = item.get("recurrence")
            status = item.get("status")
            clear_body = bool(item.get("clear_body", False))
            clear_due_date = bool(item.get("clear_due_date", False))
            clear_recurrence = bool(item.get("clear_recurrence", False))

            if title:
                fields.append("title = ?")
                params.append(title)
            if clear_body:
                fields.append("body = NULL")
            elif body:
                fields.append("body = ?")
                params.append(body)
            if priority:
                fields.append("priority = ?")
                params.append(priority)
            if category:
                fields.append("category = ?")
                params.append(category)
            if clear_due_date:
                fields.append("due_date = NULL")
            elif due_date:
                fields.append("due_date = ?")
                params.append(due_date)
            if clear_recurrence:
                fields.append("recurrence = NULL")
            elif recurrence:
                fields.append("recurrence = ?")
                params.append(recurrence)
            if status:
                fields.append("status = ?")
                params.append(status)

            if not fields:
                results.append(f"Entry #{entry_id}: no fields to update — skipped.")
                continue

            fields.append("updated_at = datetime('now')")
            params.append(entry_id)
            conn.execute(
                f"UPDATE entries SET {', '.join(fields)} WHERE id = ?",  # noqa: S608
                params,
            )
            results.append(f"Entry #{entry_id} updated.")
    return results


@mcp.tool
def archive(
    older_than_days: int,
    status: str = "todo",
    action: Literal["cancel", "complete"] = "cancel",
) -> str:
    """Bulk-cancel or bulk-complete stale entries older than a given number of days.

    Args:
        older_than_days: Entries whose created_at is older than this many days are targeted.
        status: Only entries currently in this status are affected (default: 'todo').
        action: Whether to 'cancel' or 'complete' the matched entries (default: 'cancel').
    """
    if older_than_days < 1:
        return "older_than_days must be at least 1."
    cutoff = (date.today() - timedelta(days=older_than_days)).isoformat()  # noqa: DTZ011
    new_status = "cancelled" if action == "cancel" else "done"
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE entries
            SET status = ?, updated_at = datetime('now')
            WHERE status = ?
              AND DATE(created_at) < ?
            """,
            (new_status, status, cutoff),
        )
    count = cursor.rowcount
    verb = "cancelled" if action == "cancel" else "completed"
    return f"Archived (marked as {verb}) {count} entr{'y' if count == 1 else 'ies'} older than {older_than_days} days with status '{status}'."  # noqa: E501


@mcp.tool
def delete_many(entry_ids: list[int]) -> str:
    """Permanently delete multiple entries in a single operation.

    Args:
        entry_ids: List of entry IDs to delete.
    """
    if not entry_ids:
        return "No IDs provided."
    placeholders = ", ".join("?" * len(entry_ids))
    with db.get_connection() as conn:
        cursor = conn.execute(
            f"DELETE FROM entries WHERE id IN ({placeholders})",  # noqa: S608
            entry_ids,
        )
    deleted = cursor.rowcount
    not_found = len(entry_ids) - deleted
    msg = f"Deleted {deleted} entr{'y' if deleted == 1 else 'ies'}."
    if not_found:
        msg += f" {not_found} ID(s) not found."
    return msg


@mcp.tool
def sync_to_org() -> str:
    """Export all entries to ~/.captainslog/captainslog.org in org-mode format.

    The org file is a read-friendly export. SQLite remains the source of truth.
    Entries are grouped by category and sorted by priority then due date.
    Priority mapping: high → [#A], normal → [#B], low → [#C].
    """
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, body, status, priority, category, due_date, recurrence, updated_at
            FROM entries
            WHERE status != 'cancelled'
            ORDER BY category,
                     CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                     due_date NULLS LAST,
                     created_at
            """,
        ).fetchall()

    now = datetime.now().strftime("%Y-%m-%d %a %H:%M")  # noqa: DTZ005
    lines: list[str] = [
        "#+TITLE: CaptainsLog",
        f"#+DATE: [{now}]",
        "#+STARTUP: overview",
        "#+TODO: TODO | DONE",
        "",
    ]

    for row in rows:
        state = "DONE" if row["status"] == "done" else "TODO"
        pri = _ORG_PRIORITY.get(row["priority"], "[#B]")
        tag = _org_tag(row["category"])
        heading = f"* {state} {pri} {row['title']}"
        if tag:
            # pad heading to col 77 for tag alignment (best-effort)
            pad = max(1, 77 - len(heading) - len(tag))
            heading = heading + " " * pad + tag
        lines.append(heading)

        if row["status"] == "done" and row["updated_at"]:
            lines.append(f"  CLOSED: {_org_closed(row['updated_at'])}")
        if row["due_date"]:
            lines.append(f"  DEADLINE: {_org_date(row['due_date'])}")

        props: list[str] = [f"  :ID:       {row['id']}"]
        if row["recurrence"]:
            props.append(f"  :RECURRENCE: {row['recurrence']}")
        lines.append("  :PROPERTIES:")
        lines.extend(props)
        lines.append("  :END:")

        if row["body"]:
            lines.extend(f"  {bl}" for bl in row["body"].splitlines())
        lines.append("")

    out_path = Path.home() / ".captainslog" / "captainslog.org"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return f"Exported {len(rows)} entries to {out_path}"


@mcp.tool
def sync_to_markdown() -> str:
    """Export all entries to ~/.captainslog/captainslog.md in Markdown format.

    The Markdown file is a read-friendly export. SQLite remains the source of truth.
    Entries are grouped by category and sorted by priority then due date.
    """
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, body, status, priority, category, due_date, recurrence, updated_at
            FROM entries
            WHERE status != 'cancelled'
            ORDER BY category,
                     CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                     due_date NULLS LAST,
                     created_at
            """,
        ).fetchall()

    today = datetime.now().date().isoformat()  # noqa: DTZ005
    lines: list[str] = [f"# CaptainsLog — {today}", ""]

    current_category: str | None = None
    for row in rows:
        if row["category"] != current_category:
            current_category = row["category"]
            lines.append(f"## {current_category}")
            lines.append("")

        checkbox = "[x]" if row["status"] == "done" else "[ ]"
        pri = _MD_PRIORITY.get(row["priority"], "`normal`")
        meta_parts = [pri]
        if row["due_date"]:
            meta_parts.append(f"due {row['due_date']}")
        if row["recurrence"]:
            meta_parts.append(f"*({row['recurrence']})*")
        meta = " · ".join(meta_parts)
        lines.append(f"- {checkbox} **{row['title']}** {meta}")

        if row["body"]:
            lines.extend(f"  {bl}" for bl in row["body"].splitlines())
        lines.append("")

    out_path = Path.home() / ".captainslog" / "captainslog.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return f"Exported {len(rows)} entries to {out_path}"


def run() -> None:
    db.init_db()
    mcp.run()


if __name__ == "__main__":
    run()
