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

## Installation for AI Agents (Google Antigravity)

To make the skill globally available across all workspaces on Windows (avoiding Go `os.ReadDir` skipping top-level `ReparsePoint` junctions):

```powershell
# 1. Create a real directory in the global skills folder
New-Item -ItemType Directory -Force -Path "$HOME\.gemini\config\skills\calibre-library"

# 2. HardLink SKILL.md and Junction the subdirectories
New-Item -ItemType HardLink -Force `
  -Path "$HOME\.gemini\config\skills\calibre-library\SKILL.md" `
  -Target "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\SKILL.md"

New-Item -ItemType Junction `
  -Path "$HOME\.gemini\config\skills\calibre-library\scripts" `
  -Target "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts"

New-Item -ItemType Junction `
  -Path "$HOME\.gemini\config\skills\calibre-library\references" `
  -Target "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\references"
```

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
