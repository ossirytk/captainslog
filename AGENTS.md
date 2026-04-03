# AGENTS.md — Project Rules for AI Assistants (Python)

This repository is currently developed primarily from a **Windows dev drive** using **PowerShell** and **VS Code**.  
**WSL:Ubuntu**, **fish**, and **NvChad Neovim** remain supported alternative workflows.  
All tooling runs via terminal commands. Dependencies are managed with **uv**, and code quality is ensured by **ruff** (formatter + linter) and **pyrefly** (editor integration).

Contributors maintain CLI-first workflows with minimal, deterministic diffs that comply with repository standards.

GitHub Copilot agents and other LLM-based assistants use this file to align with project-specific practices.  
VS Code's agentic AI features can apply multi-file coordinated changes, so the rules below constrain that behavior.

---

## 0. Development Environment

- **Primary OS/workspace:** Windows dev drive
- **Supported alternative OS/workspace:** WSL 2 with Ubuntu
- **Editors:** VS Code (primary), NvChad Neovim (supported alternative)
- **Shells:** PowerShell (current default), `fish` in WSL (supported alternative)
- **Package Manager:** `uv` (fast, dependency-locked)
- **Formatter + Linter:** `ruff` (installed as tool via uv)
- **Editor Integration:** `pyrefly` (installed as tool via uv, provides code insights and can suggest modifications)

All terminal commands should be reproducible from the supported shell/editor combinations.

---

## 0.1 Available CLI Tools

The following tools are installed locally and available for use in terminal workflows and agent tasks:

| Tool | Purpose |
|------|---------|
| `diffutils` | File comparison (`diff`, `cmp`, `diff3`, `sdiff`) |
| `fd` | Fast, user-friendly alternative to `find` for file search |
| `fzf` | General-purpose fuzzy finder for interactive filtering |
| `ripgrep` (`rg`) | Fast regex search across files; prefer over `grep`/`Select-String` |
| `zip` | Archive creation and extraction |
| `tokei` | Count lines of code by language |
| `ast-grep` (`sg`) | Structural code search and rewriting using AST patterns |
| `jq` | JSON query and transformation CLI |
| `yq` | YAML/JSON/TOML query and transformation CLI |
| `hyperfine` | Command-line benchmarking with statistical output |
| `pre-commit` | Run and manage repository pre-commit hooks |
| `http` / `https` (HTTPie) | Human-friendly HTTP API client |
| `difft` (difftastic) | Syntax-aware structural diffing |
| `bat` | Cat clone with syntax highlighting and Git integration |
| `delta` | Syntax-highlighting pager for git diffs (git-delta) |
| `sd` | Intuitive find-and-replace CLI (sed alternative) |
| `tldr` | Simplified, community-driven man pages (tealdeer) |
| `grex` | Generate regular expressions from example strings |

Prefer these tools over PowerShell built-ins where applicable (e.g., use `rg` instead of `Select-String`, use `fd` instead of `Get-ChildItem` for file discovery).

### Preferred command order

- Content search: `rg` first, then `ast-grep` for structural/language-aware matching
- File discovery: `fd` first, then `rg --files` as a fallback
- JSON config inspection: `jq`
- YAML/TOML inspection: `yq`
- HTTP/API smoke checks: `http` / `https` (HTTPie)
- Diff/review: `difft` for syntax-aware diffs, `diff` for plain text diffs, `delta` for git diffs
- Performance comparisons: `hyperfine` for repeatable timing

### Avoid in autonomous runs

- Avoid interactive-only flows (for example `fzf` prompts) unless the user explicitly asks for interactive selection
- Avoid destructive git/file operations unless the user explicitly approves them
- Avoid long-running watch commands by default; use one-shot checks first, then switch to watch mode only when requested
- Avoid invoking `pre-commit run --all-files` on very large repos when a targeted path or hook is enough for the task

---

## 1. Authoritative Tools & Source of Truth

### Python
- Ruff is the ONLY formatter + linter.
- Ruff’s configuration in `pyproject.toml` is authoritative.
- Do NOT reformat using Black, isort, yapf, or any editor formatter.
- Pyrefly is allowed to suggest code modifications; incorporate them if they make sense.

### Cross-Editor Compatibility
- Contributors primarily use VS Code and still support Neovim workflows.  
- All changes must be reproducible via terminal commands.

---

## 2. Ruff Configuration Source

- Do not duplicate Ruff rules in this file.
- Treat `pyproject.toml` as the single source of truth for all Ruff settings (`[tool.ruff]`).
- If lint behavior changes, update `pyproject.toml` and rely on `uv run ruff ...` output for validation.

---

## 2.1 Tooling Reliability Notes

- VS Code agent/tool output can truncate long file previews and append helper text such as `Continue. The file is too long...`.
- Never paste tool helper/output text into source files.
- After large scripted edits, immediately validate file tails and rerun Ruff/tests before proceeding.

---

## 3. Terminal Workflows with uv

### Running Python Code

```powershell
# Using uv run (handles the environment automatically)
uv run python script.py
uv run python -m module_name

# PowerShell virtualenv activation
.venv\Scripts\Activate.ps1
python script.py
deactivate

# WSL/fish virtualenv activation (supported alternative)
. .venv/bin/activate.fish
python script.py
deactivate
```

### Linting and Formatting

```powershell
# Format code (in-place)
uv run ruff format .

# Check for lint issues
uv run ruff check .

# Fix auto-fixable lint issues
uv run ruff check --fix .

# Check specific file
uv run ruff check path/to/file.py
```

### Installing Dependencies

```powershell
# Add new dependency
uv add package_name

# Add dev dependency
uv add --dev package_name

# Sync environment from lock
uv sync

# Install in editable mode
uv pip install -e .
```

### Managing Python Versions

```powershell
# Check Python version used by uv
uv python list

# Pin to specific version
uv python pin 3.13
```

---

## 4. Editor Configuration

### VS Code Settings
- Use Ruff extension for real-time linting
- Pyrefly provides code insights and can identify improvements; use as needed
- Terminal integration: Use the integrated PowerShell terminal by default; WSL + `fish` remains a supported alternative

### NvChad/Neovim
- Configure LSP to use linting results from Ruff
- Consider nvim-lint with Ruff as linter
- Do not rely on editor auto-formatting; use `uv run ruff format` before committing

---

## 5. Git Workflow Discipline

- Run `uv run ruff check --fix .` before committing
- Run `uv run ruff format .` before committing
- Verify with `uv run ruff check .` (should be clean)
- Keep diffs minimal and focused on the change
- Do not include unrelated reformatting in commits

---

## 6. Improvements

Potential features and enhancements, grouped by what they require.
Mark ideas here rather than opening issues for every passing thought.

### No additional dependencies (pure Python)

- **Org-mode export** — `sync_to_org` tool writes `~/.captainslog/captainslog.org`
  with proper org syntax: `TODO`/`DONE` states, `DEADLINE:` timestamps, tag drawers.
  SQLite remains the source of truth; the org file is a read-friendly export.
- **Markdown export** — similar export for non-org editors.
- **Recurrence** — repeat field on entries (daily, weekly) with auto-reschedule on complete.
- **Weekly review tool** — returns a summary of completed vs. overdue vs. new entries
  for a given week range.

### Requires optional CLI tools

These enhancements depend on tools that may not be present on all systems.
Check with `Get-Command <tool>` before implementing; degrade gracefully if absent.

| Tool | Enhancement |
|------|-------------|
| `rg` | Full-text search across exported org/markdown files (`search` tool) |
| `fzf` | Interactive task selection — only when user explicitly requests interactive mode |
| `jq` | Structured output transformation for piping captainslog output into other tools |

### Org-mode interop notes

- NvChad (nvim-orgmode) and Emacs org-mode can both consume standard `.org` files
- Org `CATEGORY` property maps naturally to the `category` field
- Org priorities `[#A]` / `[#B]` / `[#C]` map to `high` / `normal` / `low`
- A round-trip import (`import_from_org`) is a stretch goal — org parsing is fragile

