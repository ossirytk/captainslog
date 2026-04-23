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
        "Use `capture` to log one task, or `capture_many` for several at once. "
        "Use `agenda` to surface what needs attention today. "
        "Use `complete` to mark one task done, or `complete_many` for several. "
        "Use `list_entries` to browse or filter the backlog (supports priority, date-range, and sort filters). "
        "Use `get_entry` to read all fields of a single entry. "
        "Use `update_entry` to edit an existing entry. "
        "Use `delete_entry` to remove one entry, or `delete_many` for several. "
        "Use `search` to find entries by keyword. "
        "Use `list_categories` to see all categories with open/done counts. "
        "Use `stats` for a quick count summary by status and priority. "
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


@mcp.tool
def capture(  # noqa: PLR0913
    title: str,
    body: str = "",
    priority: Literal["low", "normal", "high"] = "normal",
    category: str = "inbox",
    due_date: str = "",
    recurrence: Literal["daily", "weekly", "monthly", ""] = "",
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
                  due_date <= :today
                  OR priority = 'high'
              )
            ORDER BY
                CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                due_date NULLS LAST,
                created_at
            """,
            {"today": today},
        ).fetchall()
    return [dict(row) for row in rows]


@mcp.tool
def complete(entry_id: int) -> str:
    """Mark a task as done.

    If the entry has a recurrence set and a due_date, a new entry is automatically
    created with the next due date so the series continues.

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
    return [dict(row) for row in rows]


@mcp.tool
def update_entry(  # noqa: PLR0913
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

        if not fields:
            return "No fields to update — provide at least one update or clear_* flag."

        fields.append("updated_at = datetime('now')")
        params.append(entry_id)
        conn.execute(
            f"UPDATE entries SET {', '.join(fields)} WHERE id = ?",  # noqa: S608
            params,
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
        if not rows:
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
    return dict(row)


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

    Recurrence is handled per entry: if an entry recurs, the next occurrence is created.

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
            else:
                results.append(f"Entry #{entry_id} marked as done.")
    return results


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
