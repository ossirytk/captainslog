---
name: captainslog
description: Personal task capture and agenda management. Use this skill when the user wants to log a task or note, check what's on their agenda today, mark a task complete, or browse their backlog. Invoke for prompts like "add a task", "what's on my todo list", "capture a note", "show my agenda", "mark task done", or "show open tasks".
---

## Overview

captainslog is a personal task and note log backed by a local SQLite database at `~/.captainslog/log.db`. It exposes four MCP tools for managing tasks and notes.

## Available Tools

| Tool | When to use |
|------|-------------|
| `captainslog-capture` | Log a new task or note. Accepts `title` (required), `body`, `priority` (`low`/`normal`/`high`), `category`, and `due_date` (YYYY-MM-DD). |
| `captainslog-agenda` | Surface items due today, overdue, or high priority. Accepts optional `target_date` (YYYY-MM-DD, defaults to today). |
| `captainslog-complete` | Mark a task done by its numeric `entry_id`. |
| `captainslog-list_entries` | Browse the backlog. Accepts optional `category`, `status` (`todo`/`in_progress`/`done`/`cancelled`), and `limit`. |

## Guidance

- When capturing: infer `priority` and `category` from the user's wording. If the user says "urgent" or "asap", use `high`. If they mention a domain (work, personal, health), set it as the `category`.
- When completing: call `captainslog-list_entries` first if you need to find the right `entry_id`.
- When checking the agenda: call `captainslog-agenda` with no arguments to get today's view. Follow up with `captainslog-list_entries` if the user wants to see the full backlog.
- Always confirm captures with the returned entry ID so the user can reference it later.
