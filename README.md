# captainslog

A personal task capture and agenda MCP server for daily use with GitHub Copilot CLI and VS Code Copilot.

Inspired by the org-mode workflow — quick capture of tasks and notes, a smart agenda that surfaces what actually needs attention today, and a clean backlog to work through. Backed by a local SQLite database; no server, no cloud, no API keys.

- **Requires:** Python 3.13+, [uv](https://docs.astral.sh/uv/)

---

## Table of Contents

- [Installation](#installation)
- [MCP Client Configuration](#mcp-client-configuration)
  - [GitHub Copilot CLI](#github-copilot-cli)
  - [VS Code Copilot](#vs-code-copilot)
- [Available Tools](#available-tools)
- [Example Prompts](#example-prompts)
- [Data Storage](#data-storage)
- [Development](#development)

---

## Installation

### Option A — Install as a uv tool (recommended)

Installs the `captainslog` command globally into an isolated environment managed by uv.

```sh
uv tool install git+https://github.com/ossirytk/captainslog
```

Verify the install:

```sh
captainslog --help
```

To update to the latest version later:

```sh
uv tool upgrade captainslog
```

### Option B — Clone and run from source

```sh
git clone https://github.com/ossirytk/captainslog
cd captainslog
uv sync
```

Run directly without installing:

```sh
uv run captainslog
```

---

## MCP Client Configuration

The server communicates over **stdio** (standard MCP transport). Register it in your client config once and then interact with it through natural language.

### GitHub Copilot CLI

Add the server to your Copilot CLI MCP config file.

**Location:**
- Linux / macOS: `~/.config/github-copilot/mcp.json`
- Windows: `%APPDATA%\GitHub Copilot\mcp.json`

**Using the installed tool (Option A):**

```json
{
  "servers": {
    "captainslog": {
      "type": "stdio",
      "command": "captainslog"
    }
  }
}
```

**Using a local checkout (Option B):**

```json
{
  "servers": {
    "captainslog": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/captainslog", "captainslog"]
    }
  }
}
```

### VS Code Copilot

Add the server to your VS Code user or workspace MCP settings.

**User-level** — create or edit:
- Linux: `~/.config/Code/User/mcp.json`
- macOS: `~/Library/Application Support/Code/User/mcp.json`
- Windows: `%APPDATA%\Code\User\mcp.json`

```json
{
  "servers": {
    "captainslog": {
      "type": "stdio",
      "command": "captainslog"
    }
  }
}
```

**Workspace-level** — create `.vscode/mcp.json` in your project root:

```json
{
  "servers": {
    "captainslog": {
      "type": "stdio",
      "command": "captainslog"
    }
  }
}
```

**Using a local checkout (Option B):**

```json
{
  "servers": {
    "captainslog": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/captainslog", "captainslog"]
    }
  }
}
```

> **Windows note:** Use forward slashes or escaped backslashes in JSON paths.
> Use `uv tool dir` to find where uv installs tools if `captainslog` is not on your `PATH`.

---

## Available Tools

| Tool | Description |
|------|-------------|
| `capture` | Log a new task or note with optional priority, category, and due date |
| `capture_many` | Log several tasks in a single call |
| `agenda` | Surface tasks due today, overdue, or marked high priority |
| `complete` | Mark a task as done by ID |
| `complete_many` | Mark several tasks done in one call |
| `list_entries` | Browse the backlog with category, status, priority, and date-range filters |
| `get_entry` | Read all fields of a single entry by ID |
| `update_entry` | Edit an existing entry (title, body, priority, due date, etc.) |
| `delete_entry` | Remove an entry by ID |
| `delete_many` | Remove several entries in one call |
| `search` | Full-text search across task titles and body text |
| `list_categories` | List all categories with open/done counts |
| `stats` | Quick summary of counts by status and priority |
| `weekly_review` | Summary of completed, overdue, and new entries for a given week |
| `sync_to_org` | Export the full log to `~/.captainslog/captainslog.org` (org-mode) |
| `sync_to_markdown` | Export the full log to `~/.captainslog/captainslog.md` |

---

## Example Prompts

Once registered with your MCP client, interact naturally:

> *"Add a task to call the dentist this Friday, personal category, high priority"*  
> *"What's on my agenda today?"*  
> *"Show me all open work tasks"*  
> *"Mark tasks 3 and 7 as done"*  
> *"What did I finish this week?"*  
> *"Export my log to org-mode"*

---

## Data Storage

All data is stored locally in a SQLite database at `~/.captainslog/log.db`. Nothing leaves your machine.

---

## Development

```sh
# Install dev dependencies
uv sync

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Fix auto-fixable lint issues
uv run ruff check --fix .

# Run tests
uv run pytest
```
