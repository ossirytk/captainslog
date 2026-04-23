"""Captain's Log MCP server — capture and agenda tools."""

import calendar
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from captainslog.db import FTS5_AVAILABLE, get_connection, init_db

mcp = FastMCP(
    name="captainslog",
    instructions=(
        "Captain's Log is a personal task and agenda manager. "
        "Use `capture` to quickly log new tasks or notes. "
        "Use `agenda` to surface what needs attention today. "
        "Use `complete` to mark tasks done. "
        "Use `list_entries` to browse or filter the backlog. "
        "Use `search` to find entries by keyword. "
        "Use `weekly_review` to summarise a week's activity. "
        "Use `sync_to_org` or `sync_to_markdown` to export the log."
    ),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ORG_PRIORITY = {"high": "[#A]", "normal": "[#B]", "low": "[#C]"}
_MD_PRIORITY = {"high": "`high`", "normal": "`normal`", "low": "`low`"}


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
    with get_connection() as conn:
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
        target_date: Date to use as 'today' in YYYY-MM-DD format. Defaults to today.
    """
    today = target_date or datetime.now(tz=UTC).date().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, body, status, priority, category, due_date, created_at
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
    with get_connection() as conn:
        row = conn.execute(
            "SELECT title, body, priority, category, due_date, recurrence FROM entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return f"No entry found with id {entry_id}."

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
def list_entries(
    category: str = "",
    status: str = "",
    limit: int = 50,
) -> list[dict]:
    """Browse the backlog with optional filters.

    Args:
        category: Filter by category label. Empty means all categories.
        status: Filter by status (todo, in_progress, done, cancelled). Empty means all.
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

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    query = f"""
        SELECT id, title, status, priority, category, due_date, created_at
        FROM entries
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """  # noqa: S608 — where clause is built from validated field names, not user input

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


@mcp.tool
def search(query: str, limit: int = 20) -> list[dict]:
    """Search entries by keyword across title and body.

    Uses SQLite FTS5 for fast full-text search when available, falling back to
    LIKE-based matching otherwise.

    Args:
        query: Search term or phrase. Supports FTS5 match syntax (e.g. 'fix*', '"exact phrase"').
        limit: Maximum number of results to return.
    """
    with get_connection() as conn:
        if FTS5_AVAILABLE:
            rows = conn.execute(
                """
                SELECT e.id, e.title, e.body, e.status, e.priority, e.category,
                       e.due_date, e.recurrence, e.created_at,
                       snippet(entries_fts, 0, '**', '**', '...', 12) AS snippet
                FROM entries_fts
                JOIN entries e ON entries_fts.rowid = e.id
                WHERE entries_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        else:
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
        today = datetime.now(tz=UTC).date()
        start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    with get_connection() as conn:
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
def sync_to_org() -> str:
    """Export all entries to ~/.captainslog/captainslog.org in org-mode format.

    The org file is a read-friendly export. SQLite remains the source of truth.
    Entries are grouped by category and sorted by priority then due date.
    Priority mapping: high → [#A], normal → [#B], low → [#C].
    """
    with get_connection() as conn:
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

    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %a %H:%M")
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
    with get_connection() as conn:
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

    today = datetime.now(tz=UTC).date().isoformat()
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
    init_db()
    mcp.run()


if __name__ == "__main__":
    run()
