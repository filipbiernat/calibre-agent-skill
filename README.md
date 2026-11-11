# Calibre Agent Skill (`calibre-library`)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Calibre](https://img.shields.io/badge/Calibre-Python%20API%20(new__api)-blue.svg)](https://manual.calibre-ebook.com/db_api.html)

An AI agent skill and Python toolkit for managing local **Calibre** e-book libraries using **Calibre's native in-process Python API** (`calibre.db.cache.Cache` executed via `calibre-debug -e`) and CLI conversion utilities (`ebook-convert`).

Designed for AI coding assistants (**Google Antigravity**, **Claude Code**, **Cursor**, **GitHub Copilot**) to search, audit, edit metadata in bulk, repair cloud-sync path desyncs, and convert formats (e.g. `EPUB` → `MOBI` for Kindle) with structured **UTF-8 JSON** output.

---

## Why Native Python API Instead of `calibredb` Subprocesses?

Most CLI wrappers spawn a new `calibredb` process for every operation, re-initializing the runtime and re-reading `metadata.db` each time. By running scripts inside `calibre-debug -e`, this skill accesses `db(path).new_api` (`calibre.db.cache.Cache`) directly in memory:

- **Fast Bulk Operations:** Update metadata, tags, languages, or series across hundreds of books in milliseconds (`set_field`).
- **Smart Item Merging:** Rename an author, tag, or series with `rename_items` — if the target name already exists, Calibre automatically merges both items across all books.
- **Cloud-Sync & Google Drive Safety:** Includes process lock checks (`calibre.exe` detection) and a dedicated repair tool (`fix_library_paths.py`) that resolves Google Drive `desktop.ini` `WinError 5` permission errors and rescues misplaced book folders.
- **Zero External Dependencies:** Runs entirely on the Python environment bundled inside standard Calibre installations.

---

## Repository Structure

```text
calibre-agent-skill/
├── LICENSE                                   # MIT License
├── README.md                                 # Project documentation
├── .gitignore
└── skills/
    └── calibre-library/
        ├── SKILL.md                          # Main instruction file for AI agents
        ├── references/
        │   └── python_api_reference.md       # Quick reference for calibre.db.cache.Cache
        └── scripts/
            ├── calibre_conn.py               # Shared DB connection, GUI lock check & JSON serializer
            ├── search_books.py               # Search (Calibre Query Language), inspect & stats
            ├── audit_library.py              # Library health check (missing MOBI, bad tags, duplicates)
            ├── edit_metadata.py              # Single & bulk metadata editor, author/tag merging
            ├── manage_books.py               # Add/export/remove books and formats (uses Calibre Trash)
            ├── convert_books.py              # Batch & single format converter (e.g. EPUB -> MOBI)
            └── fix_library_paths.py          # Repair Google Drive path desyncs & clean desktop.ini folders
```

---

## Prerequisites

- **Calibre** installed and available on `PATH` (`calibre-debug`, `ebook-convert`).
  - Windows default location: `C:\Program Files\Calibre2\`
- Set your library path via the `CALIBRE_LIBRARY` environment variable, `--library <path>` CLI flag, or `DEFAULT_LIBRARY_PATH` in [`scripts/calibre_conn.py`](./skills/calibre-library/scripts/calibre_conn.py).

---

## Installation & Setup for AI Agents

Skills instruct autonomous coding agents on how and when to use this toolkit. Depending on your environment and operating system, link or install the skill into your agent's configuration directory.

### 1. Google Antigravity

#### Windows (PowerShell)
To make the skill globally available across all workspaces on Windows (avoiding issues where Go's `os.ReadDir` skips top-level filesystem reparse points/junctions):

```powershell
# 1. Create a real directory in the global skills folder
New-Item -ItemType Directory -Force -Path "$HOME\.gemini\config\skills\calibre-library"

# 2. HardLink SKILL.md and Junction the subdirectories
New-Item -ItemType HardLink -Force `
  -Path "$HOME\.gemini\config\skills\calibre-library\SKILL.md" `
  -Target "C:\path\to\calibre-agent-skill\skills\calibre-library\SKILL.md"

New-Item -ItemType Junction `
  -Path "$HOME\.gemini\config\skills\calibre-library\scripts" `
  -Target "C:\path\to\calibre-agent-skill\skills\calibre-library\scripts"

New-Item -ItemType Junction `
  -Path "$HOME\.gemini\config\skills\calibre-library\references" `
  -Target "C:\path\to\calibre-agent-skill\skills\calibre-library\references"
```

#### Linux & macOS (Bash / Zsh)
```bash
# Global configuration for Antigravity
mkdir -p ~/.gemini/config/skills
ln -s "/path/to/calibre-agent-skill/skills/calibre-library" ~/.gemini/config/skills/calibre-library
```

---

### 2. Claude Code

Claude Code loads skills/rules from `~/.claude/commands/` or `.claude/skills/` (project-level), or directly via system prompt instructions / prompt files.

#### Linux / macOS
```bash
# Link skill directory to Claude global skills or user commands
mkdir -p ~/.claude/skills
ln -s "/path/to/calibre-agent-skill/skills/calibre-library" ~/.claude/skills/calibre-library
```

#### Windows (PowerShell)
```powershell
New-Item -ItemType Directory -Force -Path "$HOME\.claude\skills"
New-Item -ItemType Junction `
  -Path "$HOME\.claude\skills\calibre-library" `
  -Target "C:\path\to\calibre-agent-skill\skills\calibre-library"
```

---

### 3. Cursor & Windsurf (.cursorrules / .windsurfrules / Rules for AI)

For Cursor or Windsurf, you can expose the skill instructions across projects or per-workspace:

- **Per Workspace / Repository:**
  Reference [`skills/calibre-library/SKILL.md`](./skills/calibre-library/SKILL.md) in your `.cursorrules` or `.cursor/rules/calibre.mdc`:
  ```markdown
  When managing the Calibre library, follow instructions and run scripts from:
  path/to/calibre-agent-skill/skills/calibre-library/SKILL.md
  Always execute scripts with: calibre-debug -e <script_path> -- [args]
  ```
- **Symlink into project rules (macOS/Linux):**
  ```bash
  mkdir -p .cursor/rules
  ln -s "/path/to/calibre-agent-skill/skills/calibre-library/SKILL.md" .cursor/rules/calibre.mdc
  ```

---

### 4. Custom CLI Agents & Standalone Use (Generic / Codex / Aider / Any LLM)

Any agent with terminal access can use this toolkit without a specialized plugin framework:

1. **Set the environment variable** pointing to your library (optional if using default):
   - **Linux / macOS:**
     ```bash
     export CALIBRE_LIBRARY="$HOME/Calibre Library"
     ```
   - **Windows (PowerShell):**
     ```powershell
     $env:CALIBRE_LIBRARY = "C:\Users\<username>\Calibre Library"
     ```
2. **Include the contents of [`SKILL.md`](./skills/calibre-library/SKILL.md) in the agent's context or system prompt.** All scripts output structured **UTF-8 JSON**, making them directly parseable by any language model tool-calling loop.

---

## Quick Usage Examples

> **Note:** Always pass `--` before script arguments when invoking via `calibre-debug -e` so `calibre-debug` does not intercept flags like `-q` or `--help`.

### 1. Library Statistics & Search (`search_books.py`)

```powershell
# Full library statistics (formats, languages, missing covers, custom columns)
calibre-debug -e skills/calibre-library/scripts/search_books.py -- stats

# Search using Calibre Query Language
calibre-debug -e skills/calibre-library/scripts/search_books.py -- search -q "author:Sapkowski and not formats:MOBI"

# Inspect full metadata & file paths for specific book IDs
calibre-debug -e skills/calibre-library/scripts/search_books.py -- show 6 49

# List all authors or tags with book counts
calibre-debug -e skills/calibre-library/scripts/search_books.py -- categories --field authors
```

### 2. Library Health Audit (`audit_library.py`)

```powershell
calibre-debug -e skills/calibre-library/scripts/audit_library.py
```

Detects:
- Missing format files on disk vs `metadata.db`,
- Duplicate `(book_id)` folders and empty `desktop.ini` ghost directories caused by Google Drive sync,
- Books that have `EPUB`/`DOCX`/`RTF` but lack `MOBI` for Kindle,
- Duplicate, inverted (`Last First`), or `ALL CAPS` author names,
- Corrupted tags (e.g. book blurbs accidentally split by commas into tags, unbalanced parentheses),
- Books missing cover images or language metadata.

### 3. Edit Metadata & Merge Authors/Tags (`edit_metadata.py`)

```powershell
# Update fields on one or multiple books (preview with --dry-run)
calibre-debug -e skills/calibre-library/scripts/edit_metadata.py -- set --ids 6 --languages pol --series "Wiedźmin" --series-index 2

# Merge duplicate author names across the entire library
calibre-debug -e skills/calibre-library/scripts/edit_metadata.py -- rename-item --field authors --from "CLANCY TOM" --to "Tom Clancy" --dry-run

# Remove garbage tags from the library
calibre-debug -e skills/calibre-library/scripts/edit_metadata.py -- remove-items --field tags --names "YA)" --dry-run
```

### 4. Convert Formats for Kindle (`convert_books.py`)

```powershell
# Preview all books that have EPUB/AZW3/DOCX/RTF but lack MOBI
calibre-debug -e skills/calibre-library/scripts/convert_books.py -- --missing-mobi --dry-run

# Convert specific book IDs to MOBI and attach to their Calibre records
calibre-debug -e skills/calibre-library/scripts/convert_books.py -- --ids 1 6 119 --to MOBI
```

### 5. Repair Google Drive Path Desyncs (`fix_library_paths.py`)

```powershell
# Preview path rescues, untracked book imports, and desktop.ini cleanup
calibre-debug -e skills/calibre-library/scripts/fix_library_paths.py -- --dry-run

# Execute fixes
calibre-debug -e skills/calibre-library/scripts/fix_library_paths.py
```

---

## License

Released under the [MIT License](./LICENSE).
