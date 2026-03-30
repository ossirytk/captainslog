# captainslog

A personal task capture and agenda MCP server for daily use with GitHub Copilot CLI.

Inspired by the org-mode workflow — quick capture of tasks and notes, a smart agenda that surfaces what actually needs attention today, and a clean backlog to work through. Backed by a local SQLite database; no server, no cloud.

---

## Tools

| Tool | Description |
|------|-------------|
| `capture` | Log a new task or note with optional priority, category, and due date |
| `agenda` | Surface tasks due today, overdue, or marked high priority |
| `complete` | Mark a task as done by ID |
| `list_entries` | Browse the backlog with optional category and status filters |

---

## Usage

Run as an MCP server (stdio transport, for use with Copilot CLI or any MCP client):

```powershell
uv run captainslog
```

Register it in your MCP client config and then talk to it naturally:

> *"Add a task to call the dentist this Friday, personal category, high priority"*  
> *"What's on my agenda today?"*  
> *"Show me all open work tasks"*

Data is stored at `~/.captainslog/log.db`.

---

## Installation

```powershell
uv sync
uv run captainslog
```

---

## Development

```powershell
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Run checks and fix auto-fixable issues
uv run ruff check --fix .
```
