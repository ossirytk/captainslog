"""Captain's Log MCP server — capture and agenda tools."""

from datetime import UTC, datetime
from typing import Literal

from fastmcp import FastMCP

from captainslog.db import get_connection, init_db

mcp = FastMCP(
    name="captainslog",
    instructions=(
        "Captain's Log is a personal task and agenda manager. "
        "Use `capture` to quickly log new tasks or notes. "
        "Use `agenda` to surface what needs attention today. "
        "Use `complete` to mark tasks done. "
        "Use `list_entries` to browse or filter the backlog."
    ),
)


@mcp.tool
def capture(
    title: str,
    body: str = "",
    priority: Literal["low", "normal", "high"] = "normal",
    category: str = "inbox",
    due_date: str = "",
) -> str:
    """Add a new task or note to the log.

    Args:
        title: Short description of the task or note.
        body: Optional longer details or context.
        priority: Task priority — low, normal, or high.
        category: Freeform category label, e.g. 'work', 'personal', 'health'.
        due_date: Optional due date in YYYY-MM-DD format.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO entries (title, body, priority, category, due_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (title, body, priority, category, due_date or None),
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

    Args:
        entry_id: The numeric ID of the entry to complete.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE entries SET status = 'done', updated_at = datetime('now') WHERE id = ?",
            (entry_id,),
        )
    if cursor.rowcount == 0:
        return f"No entry found with id {entry_id}."
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


def run() -> None:
    init_db()
    mcp.run()


if __name__ == "__main__":
    run()
