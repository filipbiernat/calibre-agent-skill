---
name: calibre-library
description: >-
  Manage, search, audit, edit metadata, repair, and convert e-books (especially EPUB to MOBI for Kindle)
  in the user's Calibre library (C:\Filip\GoogleDrive\Biblioteka calibre) using Calibre's native Python API
  (calibre-debug -e) and CLI tools (ebook-convert, ebook-meta). Activate this skill whenever the user mentions
  Calibre, e-books, Kindle, MOBI, EPUB, book metadata, tags, authors, or library cleanup.
---

# Calibre Library Management Skill (Python API + Kindle Workflow)

This skill enables agents to manage the user's Calibre e-book library located at:
`C:\Filip\GoogleDrive\Biblioteka calibre`

Instead of spawning slow `calibredb` subprocesses in a loop, this skill uses **Calibre's native in-process Python API** (`from calibre.library import db; cache = db(path).new_api`) executed via `calibre-debug -e`, combined with `ebook-convert.exe` for format conversion (e.g., `EPUB` -> `MOBI` for Kindle).

---

## Critical Safety Rules

1. **Check for Running Calibre GUI Before Writing**:
   Calibre's database (`metadata.db`) is stored on Google Drive (`C:\Filip\GoogleDrive\Biblioteka calibre`). Never run write operations via `calibre-debug` while `calibre.exe` (the GUI) is open. All write scripts in [`scripts/`](./scripts/) automatically call `ensure_safe_for_write()` from [`calibre_conn.py`](./scripts/calibre_conn.py) and abort if `calibre.exe` is running.
2. **Use `--dry-run` First for Bulk Edits or Deletions**:
   When cleaning up tags, merging authors, removing sidecar formats (`MBP`, `PDR`, `LNK`), or deleting books, run with `--dry-run` first and show the user the planned changes.
3. **Prefer Calibre Trash Over Permanent Deletion**:
   [`manage_books.py`](./scripts/manage_books.py) uses `cache.remove_books(ids, permanent=False)` by default so removed books go to `.caltrash` and can be undeleted if needed.
4. **Always Pass `--` Before Script Arguments in `calibre-debug -e`**:
   `calibre-debug -e <script.py> -- [script arguments]` ensures `calibre-debug` does not swallow flags like `-q` or `--help`.

---

## Ready-to-Use Scripts

All scripts output **UTF-8 JSON** for reliable parsing and default to `C:\Filip\GoogleDrive\Biblioteka calibre` (override with `--library <path>` or `CALIBRE_LIBRARY` env var).

### 1. Search, Inspect & Library Statistics — [`scripts/search_books.py`](./scripts/search_books.py)

```powershell
# Library statistics (total books, formats breakdown, languages, missing covers, custom columns)
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\search_books.py" -- stats

# Search books using Calibre Query Language (sorted by timestamp desc by default)
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\search_books.py" -- search -q "author:Sapkowski"

# List all books lacking MOBI format
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\search_books.py" -- search -q "not formats:MOBI" -n 0

# Show full metadata, description (comments), and file paths/sizes for specific book IDs
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\search_books.py" -- show 6 49

# List all authors, tags, series, languages, or formats with book counts
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\search_books.py" -- categories --field authors
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\search_books.py" -- categories --field tags
```

### 2. Library Health Audit — [`scripts/audit_library.py`](./scripts/audit_library.py)

Scans the library in under 2 seconds and reports:
- Non-book / sidecar-only entries (e.g., `LNK` shortcuts, lone `PDR`/`MBP` Kindle sidecar files without a readable ebook),
- Books that have `EPUB`/`DOCX`/`RTF` but are missing `MOBI` for Kindle,
- Duplicate or inverted author names (e.g., `CLANCY TOM` vs `Tom Clancy`, `David Lagercrantz` vs `David Lagerkrantz`, `Bronte Emily`),
- Books with `Nieznany` / `Unknown` author,
- Corrupted tags (sentence fragments from split descriptions, unbalanced parentheses like `YA)`),
- Books missing covers or language codes (`pol`, `eng`).

```powershell
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\audit_library.py"
```

### 3. Edit Metadata & Merge Authors/Tags — [`scripts/edit_metadata.py`](./scripts/edit_metadata.py)

```powershell
# Set metadata fields on one or multiple books (supports --dry-run)
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\edit_metadata.py" -- set --ids 6 --languages pol --series "Wiedźmin" --series-index 2

# Add or remove specific tags on selected books without overwriting other tags
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\edit_metadata.py" -- set --ids 6 49 --add-tags "Fantastyka" --remove-tags "General"

# Rename or merge duplicate authors/tags/series across the entire library
# (If target name already exists, Calibre automatically merges both items!)
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\edit_metadata.py" -- rename-item --field authors --from "CLANCY TOM" --to "Tom Clancy" --dry-run

# Delete broken/garbage tags from the entire library
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\edit_metadata.py" -- remove-items --field tags --names "YA)" "and deeply moving" --dry-run
```

### 4. Convert Formats for Kindle (`EPUB` -> `MOBI`) — [`scripts/convert_books.py`](./scripts/convert_books.py)

Exports the source format (`EPUB`, `AZW3`, `DOCX`, `RTF`, etc.) to a temp folder, runs `ebook-convert.exe` with `CALIBRE_OVERRIDE_LANG=en`, and imports the resulting `MOBI` directly into the Calibre book record via `cache.add_format()`.

```powershell
# Preview all books that have EPUB/DOCX/RTF but lack MOBI
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\convert_books.py" -- --missing-mobi --dry-run

# Convert specific book IDs to MOBI and attach to library
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\convert_books.py" -- --ids 1 6 119 --to MOBI

# Convert all books missing MOBI
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\convert_books.py" -- --missing-mobi --to MOBI
```

### 5. Add, Export, or Remove Books & Formats — [`scripts/manage_books.py`](./scripts/manage_books.py)

```powershell
# Add a new ebook file to the library (checks for duplicates first unless --allow-duplicates is passed)
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\manage_books.py" -- add-book "C:\path\to\book.epub" --tags "Fantastyka"

# Attach an additional format file (e.g. repaired EPUB or converted MOBI) to an existing book
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\manage_books.py" -- add-format --id 6 --file "C:\path\to\book.mobi"

# Export a book's files (and optionally cover) to an external directory (e.g. for repair or Kindle USB transfer)
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\manage_books.py" -- export --id 6 --to-dir "C:\temp\calibre_export" --include-cover

# Remove unwanted sidecar formats (e.g. MBP, PDR) from specific books
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\manage_books.py" -- remove-formats --ids 47 49 --formats MBP --dry-run

# Move a junk book entry (e.g. ID 262 LNK file) to Calibre Trash
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\manage_books.py" -- remove-books --ids 262 --dry-run
```

### 6. Fix Google Drive Path Desyncs & Clean Empty `desktop.ini` Folders — [`scripts/fix_library_paths.py`](./scripts/fix_library_paths.py)

Repairs path desyncs caused by Google Drive (`desktop.ini` blocking Calibre folder renames/deletes):
- Rescues books in `metadata.db` whose files are sitting in a sibling `(book_id)` folder (e.g., `Leo Child` vs `Lee Child`),
- Restores untracked book folders on disk (`(book_id)` not in `metadata.db`) back into the database,
- Archives orphaned duplicate folders to `.caltrash`,
- Removes stale ghost format links from `metadata.db` when the primary format is intact,
- Deletes empty leftover folders containing only `desktop.ini` / stale `metadata.opf`.

```powershell
# Preview all path and folder fixes without modifying anything
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\fix_library_paths.py" -- --dry-run

# Apply fixes
calibre-debug -e "C:\Filip\SW\calibre-agent-skill\skills\calibre-library\scripts\fix_library_paths.py"
```

---

## Calibre Query Language Cheat Sheet

Use these expressions with `search_books.py -- search -q "<query>"` or `cache.search("<query>")`:

| Query Example | Meaning |
| :--- | :--- |
| `author:Sapkowski` | Author contains "Sapkowski" |
| `title:"Czas pogardy"` | Exact phrase in title |
| `formats:EPUB and not formats:MOBI` | Books that have EPUB but no MOBI |
| `formats:MBP or formats:PDR` | Books with Kindle sidecar files attached |
| `cover:false` | Books without a cover image |
| `languages:false` | Books with no language set |
| `languages:pol` | Books in Polish (`pol`, `eng`, `deu`) |
| `tags:false` | Books with no tags |
| `series:true` | Books belonging to any series |
| `rating:>3` | Books rated above 3 stars |

---

## Integrating External E-book Repair / Processing Scripts

When wrapping or integrating an external e-book repair tool (e.g. fixing broken EPUB/MOBI encoding, Polish characters, CSS, or TOC):
1. Export the target format to a temporary working directory using `cache.copy_format_to(book_id, fmt, temp_path)` (or `manage_books.py -- export`).
2. Save a backup inside Calibre using `cache.save_original_format(book_id, fmt)` (creates `ORIGINAL_EPUB` / `ORIGINAL_MOBI` in the book record so it can be restored anytime with `cache.restore_original_format(book_id, fmt)`).
3. Run the repair script on the exported file.
4. Re-import the repaired file into the book record with `cache.add_format(book_id, fmt, repaired_path, replace=True)` and optionally convert `EPUB` -> `MOBI` via [`convert_books.py`](./scripts/convert_books.py).

---

## Custom Python API Scripts

When you need a custom one-off operation not covered by the 5 scripts above (e.g., working with annotations, notes, custom columns, or cover compression), consult [`references/python_api_reference.md`](./references/python_api_reference.md) and import `open_cache` and `print_json` from [`scripts/calibre_conn.py`](./scripts/calibre_conn.py).
