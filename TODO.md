# Captainslog — Improvement Ideas

## Fixes

- **`agenda` doesn't surface `in_progress` tasks** — the agenda query filters for overdue/due-today/high-priority but skips items with `status = 'in_progress'`. Items actively being worked on should always appear at the top of the agenda.
- **Python 3.13+ requirement is too strict** — no 3.13-specific features are used. Lowering the minimum to 3.12 broadens compatibility (e.g., CI runners, older distros) without any real tradeoff.

## Enhancements

- **`update_many`** — `complete_many` and `delete_many` exist but there's no bulk update. Add `update_many` accepting a list of `{entry_id, ...fields}` dicts to support bulk re-categorization, priority changes, or due-date shifts.
- **Inter-task dependencies** — add a `depends_on` field (list of entry IDs) so tasks can be blocked by others. `agenda` and `list_entries` should indicate when a task is blocked and by what.
- **Archive sweep** — add an `archive` tool (or `list_entries` filter) that bulk-cancels or bulk-completes entries older than N days in a given status (e.g., stale `todo` items from 30+ days ago).
- **`in_progress` status in `stats`** — the stats summary groups by status but `in_progress` is easy to overlook. Surface it explicitly alongside a "currently active" count distinct from the todo count.
- **Recurrence edge cases** — document (and test) behavior when `complete` is called on a recurring task with no `due_date` set: currently a recurrence without a due_date cannot auto-schedule the next occurrence.
