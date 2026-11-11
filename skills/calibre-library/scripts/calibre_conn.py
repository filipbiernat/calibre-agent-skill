"""Shared connection and safety utilities for Calibre Python API scripts.

Executed via:
    calibre-debug -e <script.py> -- [args...]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_LIBRARY_PATH = r"C:\Filip\GoogleDrive\Biblioteka calibre"


def get_library_path(cli_path: str | None = None) -> str:
    """Resolve the Calibre library path from CLI argument, env var, or default."""
    path = cli_path or os.environ.get("CALIBRE_LIBRARY") or DEFAULT_LIBRARY_PATH
    resolved = os.path.abspath(path)
    metadata_db = os.path.join(resolved, "metadata.db")
    if not os.path.isfile(metadata_db):
        raise FileNotFoundError(
            f"Calibre metadata.db not found at: {metadata_db}. "
            f"Pass --library <path> or set CALIBRE_LIBRARY."
        )
    return resolved


def is_calibre_gui_running() -> list[str]:
    """Check if Calibre GUI or competing processes (calibre.exe, calibre-parallel.exe) are running."""
    if os.name != "nt":
        return []
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq calibre.exe", "/FO", "CSV", "/NH"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        running = []
        for line in output.strip().splitlines():
            if "calibre.exe" in line.lower():
                running.append("calibre.exe")
        return running
    except Exception:
        return []


def ensure_safe_for_write(force: bool = False) -> None:
    """Abort write operations if Calibre GUI is currently open unless --force is passed."""
    if force:
        return
    running = is_calibre_gui_running()
    if running:
        raise RuntimeError(
            "Calibre GUI (calibre.exe) is currently running! "
            "Modifying the database via calibre-debug while Calibre GUI is open "
            "can corrupt metadata.db (especially on Google Drive). "
            "Please close Calibre first, or pass --force if you are certain."
        )


def open_cache(library_path: str | None = None, write_mode: bool = False, force: bool = False):
    """Open and return the thread-safe Calibre new_api Cache instance."""
    if write_mode:
        ensure_safe_for_write(force=force)
    resolved_path = get_library_path(library_path)
    from calibre.library import db

    legacy_db = db(resolved_path)
    return legacy_db.new_api, resolved_path


def serialize_book_summary(cache, book_id: int, include_comments: bool = False) -> dict[str, Any]:
    """Return a clean JSON-serializable dictionary of book metadata from Cache."""
    pubdate = cache.field_for("pubdate", book_id)
    timestamp = cache.field_for("timestamp", book_id)
    last_modified = cache.field_for("last_modified", book_id)

    def fmt_date(dt) -> str | None:
        if not dt:
            return None
        try:
            if dt.year <= 101:
                return None
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return str(dt)

    data: dict[str, Any] = {
        "id": book_id,
        "title": cache.field_for("title", book_id),
        "authors": list(cache.field_for("authors", book_id) or ()),
        "author_sort": cache.field_for("author_sort", book_id),
        "series": cache.field_for("series", book_id),
        "series_index": cache.field_for("series_index", book_id) if cache.field_for("series", book_id) else None,
        "tags": list(cache.field_for("tags", book_id) or ()),
        "formats": list(cache.formats(book_id, verify_formats=True) or ()),
        "languages": list(cache.field_for("languages", book_id) or ()),
        "rating": cache.field_for("rating", book_id),
        "publisher": cache.field_for("publisher", book_id),
        "pubdate": fmt_date(pubdate),
        "timestamp": fmt_date(timestamp),
        "last_modified": fmt_date(last_modified),
        "identifiers": dict(cache.field_for("identifiers", book_id) or {}),
        "has_cover": bool(cache.field_for("cover", book_id)),
        "path": cache.field_for("path", book_id),
    }
    if include_comments:
        data["comments"] = cache.field_for("comments", book_id) or ""
        fmt_details = {}
        for fmt in data["formats"]:
            meta = cache.format_metadata(book_id, fmt)
            fmt_details[fmt] = {
                "size_bytes": meta.get("size"),
                "path": meta.get("path"),
            }
        data["format_details"] = fmt_details
    return data


def print_json(payload: Any) -> None:
    """Print UTF-8 JSON to stdout cleanly on Windows."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
