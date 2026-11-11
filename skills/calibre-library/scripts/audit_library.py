"""Audit Calibre library for common issues, metadata anomalies, and missing Kindle formats.

Usage:
    calibre-debug -e audit_library.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from calibre_conn import open_cache, print_json

READABLE_FORMATS = {"MOBI", "EPUB", "AZW", "AZW3", "PDF", "DOCX", "RTF", "TXT", "FB2", "LIT", "HTML"}
SIDECAR_FORMATS = {"MBP", "PDR", "LNK", "ORIGINAL_MOBI", "ORIGINAL_EPUB"}


def normalize_author_tokens(name: str) -> tuple[str, ...]:
    cleaned = re.sub(r"[^\w\s]", " ", name.lower())
    return tuple(sorted( cleaned.split() ))


def audit_library(cache, library_path: str) -> dict:
    book_ids = sorted(cache.all_book_ids())

    non_readable_books = []
    missing_files_on_disk = []
    missing_mobi_with_epub = []
    legacy_azw_without_mobi = []
    missing_cover = []
    missing_language = []
    unknown_authors = []
    books_with_sidecars = []

    for bid in book_ids:
        title = cache.field_for("title", bid)
        authors = list(cache.field_for("authors", bid) or ())
        db_fmts = set(cache.formats(bid, verify_formats=False))
        disk_fmts = set(cache.formats(bid, verify_formats=True))
        missing_fmts = sorted(db_fmts - disk_fmts)
        if missing_fmts:
            missing_files_on_disk.append(
                {
                    "id": bid,
                    "title": title,
                    "authors": authors,
                    "missing_formats": missing_fmts,
                    "present_formats": sorted(disk_fmts),
                }
            )
        fmts = disk_fmts
        langs = list(cache.field_for("languages", bid) or ())
        has_cover = bool(cache.field_for("cover", bid))

        summary = {"id": bid, "title": title, "authors": authors, "formats": sorted(fmts)}

        if not (fmts & READABLE_FORMATS):
            non_readable_books.append(summary)

        if "MOBI" not in fmts and ("EPUB" in fmts or "DOCX" in fmts or "RTF" in fmts):
            missing_mobi_with_epub.append(summary)
        elif "MOBI" not in fmts and "AZW" in fmts:
            legacy_azw_without_mobi.append(summary)

        if fmts & SIDECAR_FORMATS:
            books_with_sidecars.append(
                {
                    "id": bid,
                    "title": title,
                    "sidecars": sorted(fmts & SIDECAR_FORMATS),
                    "readable": sorted(fmts & READABLE_FORMATS),
                }
            )

        if not has_cover:
            missing_cover.append({"id": bid, "title": title, "authors": authors})

        if not langs:
            missing_language.append({"id": bid, "title": title, "authors": authors})

        if any(a.lower() in {"nieznany", "unknown", "anonim"} for a in authors):
            unknown_authors.append(summary)

    # Author anomalies (ALL CAPS, inverted order, duplicate token sets)
    author_id_map = cache.get_id_map("authors")
    author_usage = cache.get_usage_count_by_id("authors")
    token_groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    all_caps_authors = []

    for aid, name in author_id_map.items():
        entry = {"id": aid, "name": name, "count": author_usage.get(aid, 0)}
        tokens = normalize_author_tokens(name)
        if tokens:
            token_groups[tokens].append(entry)
        if name.isupper() and len(name) > 3:
            all_caps_authors.append(entry)

    duplicate_or_inverted_authors = [
        group for group in token_groups.values() if len(group) > 1
    ]

    # Suspicious tags (unbalanced parens, sentence fragments > 35 chars, URLs)
    tag_id_map = cache.get_id_map("tags")
    tag_usage = cache.get_usage_count_by_id("tags")
    suspicious_tags = []
    for tid, tname in tag_id_map.items():
        reasons = []
        if tname.count("(") != tname.count(")"):
            reasons.append("unbalanced_parentheses")
        if len(tname) > 40:
            reasons.append("too_long_sentence_fragment")
        if "http://" in tname or "https://" in tname:
            reasons.append("url_in_tag")
        if reasons:
            suspicious_tags.append(
                {"id": tid, "name": tname, "count": tag_usage.get(tid, 0), "reasons": reasons}
            )

    # Scan filesystem for misplaced/duplicate (book_id) folders (common with Google Drive desktop.ini)
    id_dir_pattern = re.compile(r"\((\d+)\)$")
    folders_by_id: dict[int, list[str]] = defaultdict(list)
    empty_desktop_ini_folders: list[str] = []

    for root, dirs, files in os.walk(library_path):
        # Skip .caltrash or hidden git dirs
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        base = os.path.basename(root)
        m = id_dir_pattern.search(base)
        if m:
            bid = int(m.group(1))
            rel_dir = os.path.relpath(root, library_path).replace(os.sep, "/")
            folders_by_id[bid].append(rel_dir)
            non_sys_files = [f for f in files if f.lower() != "desktop.ini"]
            if not non_sys_files and not dirs:
                empty_desktop_ini_folders.append(rel_dir)

    duplicate_id_folders = {
        str(bid): paths for bid, paths in folders_by_id.items() if len(paths) > 1
    }

    return {
        "library_path": library_path,
        "total_books": len(book_ids),
        "issues_summary": {
            "missing_files_on_disk_count": len(missing_files_on_disk),
            "duplicate_book_id_folders_count": len(duplicate_id_folders),
            "empty_desktop_ini_folders_count": len(empty_desktop_ini_folders),
            "non_readable_books_count": len(non_readable_books),
            "convertible_to_mobi_count": len(missing_mobi_with_epub),
            "legacy_azw_only_count": len(legacy_azw_without_mobi),
            "books_with_sidecar_files_count": len(books_with_sidecars),
            "unknown_author_books_count": len(unknown_authors),
            "duplicate_or_inverted_author_groups": len(duplicate_or_inverted_authors),
            "all_caps_authors_count": len(all_caps_authors),
            "suspicious_tags_count": len(suspicious_tags),
            "missing_cover_count": len(missing_cover),
            "missing_language_count": len(missing_language),
        },
        "missing_files_on_disk": missing_files_on_disk,
        "duplicate_book_id_folders": duplicate_id_folders,
        "empty_desktop_ini_folders": empty_desktop_ini_folders,
        "non_readable_books": non_readable_books,
        "convertible_to_mobi": missing_mobi_with_epub,
        "unknown_authors": unknown_authors,
        "duplicate_or_inverted_authors": duplicate_or_inverted_authors,
        "all_caps_authors": all_caps_authors,
        "suspicious_tags": suspicious_tags,
        "missing_language": missing_language,
        "missing_cover": missing_cover,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Audit Calibre library for anomalies and missing formats.")
    parser.add_argument("--library", help="Path to Calibre library directory")
    args = parser.parse_args(argv)

    cache, lib_path = open_cache(args.library, write_mode=False)
    report = audit_library(cache, lib_path)
    print_json(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
