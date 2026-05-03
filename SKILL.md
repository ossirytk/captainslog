---
name: captainslog
description: Personal task capture and agenda management. Use this skill when the user wants to log a task or note, check what's on their agenda today, mark a task complete, browse their backlog, search entries, view statistics, or export the log. Invoke for prompts like "add a task", "what's on my todo list", "capture a note", "show my agenda", "mark task done", "show open tasks", "find entries about X", "export to org", or "weekly review".
---

## Overview

captainslog is a personal task and note log backed by a local SQLite database at `~/.captainslog/log.db`. It exposes 16 MCP tools for managing tasks and notes.

## Available Tools

### Capture

| Tool | When to use |
|------|-------------|
| `captainslog-capture` | Log a single new task or note. Accepts `title` (required), `body`, `priority` (`low`/`normal`/`high`, default `normal`), `category` (default `inbox`), `due_date` (YYYY-MM-DD), and `recurrence` (`daily`/`weekly`/`monthly`; requires `due_date`). |
| `captainslog-capture_many` | Log multiple tasks or notes in one call. Accepts `entries` — a list of dicts, each with the same fields as `capture` (only `title` is required per item). |

### Agenda & Review

| Tool | When to use |
|------|-------------|
| `captainslog-agenda` | Surface items due today, overdue, or high priority. Accepts optional `target_date` (YYYY-MM-DD, defaults to today). |
| `captainslog-weekly_review` | Summarise completed, overdue, and new entries for a given week. Accepts optional `week_start` (YYYY-MM-DD Monday, defaults to this week's Monday). |

### Browsing & Searching

| Tool | When to use |
|------|-------------|
| `captainslog-list_entries` | Browse the backlog with optional filters: `category`, `status` (`todo`/`in_progress`/`done`/`cancelled`), `priority` (`low`/`normal`/`high`), `due_before` (YYYY-MM-DD), `due_after` (YYYY-MM-DD), `sort_by` (`created_at`/`due_date`/`priority`), and `limit` (default 50). |
| `captainslog-get_entry` | Read all fields (including body and recurrence) of a single entry. Accepts `entry_id`. |
| `captainslog-search` | Find entries by keyword across title and body. Accepts `query` (supports FTS5 match syntax) and optional `limit` (default 20). |
| `captainslog-list_categories` | List all categories with total, open, done, and cancelled counts, sorted by open count. No parameters. |
| `captainslog-stats` | Quick summary of counts by status, open counts by priority, overdue count, and due-today count. No parameters. |

### Completing

| Tool | When to use |
|------|-------------|
| `captainslog-complete` | Mark a single task done by its numeric `entry_id`. Automatically creates the next occurrence for recurring entries. |
| `captainslog-complete_many` | Mark multiple tasks done in one call. Accepts `entry_ids` — a list of numeric IDs. Handles recurrence per entry. |

### Editing & Deleting

| Tool | When to use |
|------|-------------|
| `captainslog-update_entry` | Edit fields on an existing entry. Accepts `entry_id` (required) plus any subset of `title`, `body`, `priority`, `category`, `due_date`, `recurrence`, `status`. Use `clear_body`, `clear_due_date`, or `clear_recurrence` (bool flags) to explicitly remove those fields. |
| `captainslog-delete_entry` | Permanently delete a single entry by `entry_id`. |
| `captainslog-delete_many` | Permanently delete multiple entries in one call. Accepts `entry_ids` — a list of numeric IDs. |

### Export

| Tool | When to use |
|------|-------------|
| `captainslog-sync_to_org` | Export all non-cancelled entries to `~/.captainslog/captainslog.org` in org-mode format. No parameters. |
| `captainslog-sync_to_markdown` | Export all non-cancelled entries to `~/.captainslog/captainslog.md` in Markdown format. No parameters. |

## Guidance

- When capturing: infer `priority` and `category` from the user's wording. If the user says "urgent" or "asap", use `high`. If they mention a domain (work, personal, health), set it as the `category`. Use `capture_many` when the user provides a list of tasks at once.
- When completing: call `captainslog-list_entries` or `captainslog-search` first if you need to find the right `entry_id`. Use `complete_many` when the user wants to check off several items at once.
- When checking the agenda: call `captainslog-agenda` with no arguments to get today's view. Follow up with `captainslog-list_entries` if the user wants to see the full backlog.
- When editing: use `captainslog-update_entry` to change individual fields without overwriting the rest. Set `clear_due_date=true` or `clear_recurrence=true` to remove those fields rather than leaving them unchanged.
- When deleting: prefer `captainslog-delete_many` for bulk removal; use `captainslog-delete_entry` for a single item.
- For a quick overview: use `captainslog-stats` for counts or `captainslog-list_categories` to see how work is distributed across categories.
- For weekly retrospectives: call `captainslog-weekly_review` without arguments to review the current week.
- For exports: call `captainslog-sync_to_org` or `captainslog-sync_to_markdown` to generate a human-readable export file; SQLite remains the source of truth.
- Always confirm captures with the returned entry ID so the user can reference it later.
