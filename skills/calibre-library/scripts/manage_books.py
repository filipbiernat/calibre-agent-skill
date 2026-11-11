"""Add/remove books, manage formats, and export files via Calibre Python API.

Usage:
    calibre-debug -e manage_books.py -- add-book "C:\path\to\book.epub" --tags "Do przeczytania"
    calibre-debug -e manage_books.py -- add-format --id 6 --file "C:\path\to\book.mobi"
    calibre-debug -e manage_books.py -- export --id 6 --to-dir "C:\temp\export"
    calibre-debug -e manage_books.py -- remove-formats --ids 47 49 --formats MBP PDR
    calibre-debug -e manage_books.py -- remove-books --ids 262 --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from calibre_conn import open_cache, print_json, serialize_book_summary
from fix_library_paths import remove_desktop_ini_in_dir


def cmd_add_book(cache, args) -> None:
    from calibre.ebooks.metadata.meta import get_metadata

    file_path = os.path.abspath(args.file)
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lstrip(".").upper()
    with open(file_path, "rb") as stream:
        mi = get_metadata(stream, stream_type=ext.lower(), use_libprs_metadata=True)

    if args.title:
        mi.title = args.title
    if args.authors:
        mi.authors = [a.strip() for a in args.authors.split("&") if a.strip()]
    if args.tags:
        mi.tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.series:
        mi.series = args.series
    if args.series_index is not None:
        mi.series_index = args.series_index

    identical_ids = sorted(cache.find_identical_books(mi))
    if identical_ids and not args.allow_duplicates:
        print_json(
            {
                "added": False,
                "reason": "duplicate_detected",
                "identical_book_ids": identical_ids,
                "existing_books": [serialize_book_summary(cache, bid) for bid in identical_ids],
            }
        )
        return

    ids, duplicates = cache.add_books([(mi, {ext: file_path})], add_duplicates=args.allow_duplicates)
    created = [serialize_book_summary(cache, bid) for bid in ids]
    print_json(
        {
            "added": bool(ids),
            "created_book_ids": ids,
            "duplicates_skipped": len(duplicates),
            "books": created,
        }
    )


def cmd_add_format(cache, args) -> None:
    file_path = os.path.abspath(args.file)
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    if not cache.has_id(args.id):
        raise ValueError(f"Book ID {args.id} does not exist")

    fmt = (args.format or os.path.splitext(file_path)[1].lstrip(".")).upper()
    added = cache.add_format(args.id, fmt, file_path, replace=not args.no_replace)
    print_json(
        {
            "book_id": args.id,
            "format": fmt,
            "added": added,
            "book": serialize_book_summary(cache, args.id),
        }
    )


def cmd_export(cache, args) -> None:
    if not cache.has_id(args.id):
        raise ValueError(f"Book ID {args.id} does not exist")

    os.makedirs(args.to_dir, exist_ok=True)
    available_fmts = cache.formats(args.id, verify_formats=True)
    target_fmts = [args.format.upper()] if args.format else list(available_fmts)

    exported_files = []
    for fmt in target_fmts:
        if fmt not in available_fmts:
            continue
        meta = cache.format_metadata(args.id, fmt)
        orig_name = os.path.basename(meta["path"]) if meta.get("path") else f"book_{args.id}.{fmt.lower()}"
        dest_path = os.path.abspath(os.path.join(args.to_dir, orig_name))
        cache.copy_format_to(args.id, fmt, dest_path)
        exported_files.append({"format": fmt, "path": dest_path})

    cover_dest = None
    if args.include_cover and cache.field_for("cover", args.id):
        cover_dest = os.path.abspath(os.path.join(args.to_dir, f"cover_{args.id}.jpg"))
        cache.copy_cover_to(args.id, cover_dest)

    print_json(
        {
            "book_id": args.id,
            "exported_files": exported_files,
            "exported_cover": cover_dest,
        }
    )


def cmd_remove_formats(cache, args) -> None:
    fmts_to_remove = [f.upper() for f in args.formats]
    formats_map = {bid: fmts_to_remove for bid in args.ids if cache.has_id(bid)}
    if args.dry_run:
        print_json({"dry_run": True, "formats_map": {str(k): v for k, v in formats_map.items()}})
        return

    removed = cache.remove_formats(formats_map, db_only=False)
    print_json(
        {
            "dry_run": False,
            "removed": {str(k): sorted(list(v)) for k, v in removed.items()},
        }
    )


def cmd_remove_books(cache, args) -> None:
    valid_ids = [bid for bid in args.ids if cache.has_id(bid)]
    summaries = [serialize_book_summary(cache, bid) for bid in valid_ids]
    if args.dry_run:
        print_json(
            {
                "dry_run": True,
                "permanent": args.permanent,
                "books_to_remove": summaries,
            }
        )
        return

    lib_path = cache.backend.library_path
    for bid in valid_ids:
        rel = cache.field_for("path", bid)
        if rel:
            abs_dir = os.path.join(lib_path, rel.replace("/", os.sep))
            remove_desktop_ini_in_dir(abs_dir)
            remove_desktop_ini_in_dir(os.path.dirname(abs_dir))

    cache.remove_books(valid_ids, permanent=args.permanent)
    print_json(
        {
            "dry_run": False,
            "permanent": args.permanent,
            "removed_books": summaries,
        }
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Add, export, or remove books and formats via Calibre Python API.")
    parser.add_argument("--library", help="Path to Calibre library directory")
    parser.add_argument("--force", action="store_true", help="Allow write even if Calibre GUI is running")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_add = subparsers.add_parser("add-book", help="Add a new book file to the library")
    p_add.add_argument("file", help="Path to ebook file")
    p_add.add_argument("--title", help="Override title")
    p_add.add_argument("--authors", help="Override authors ('&'-separated)")
    p_add.add_argument("--tags", help="Comma-separated tags")
    p_add.add_argument("--series", help="Series name")
    p_add.add_argument("--series-index", type=float, help="Series index")
    p_add.add_argument("--allow-duplicates", action="store_true", help="Add even if title/author already exists")

    p_fmt = subparsers.add_parser("add-format", help="Add or replace a format on an existing book")
    p_fmt.add_argument("--id", type=int, required=True, help="Book ID")
    p_fmt.add_argument("--file", required=True, help="Path to format file")
    p_fmt.add_argument("--format", help="Explicit format extension (default: inferred from file)")
    p_fmt.add_argument("--no-replace", action="store_true", help="Do not overwrite if format already exists")

    p_exp = subparsers.add_parser("export", help="Export book format(s) to a directory")
    p_exp.add_argument("--id", type=int, required=True, help="Book ID")
    p_exp.add_argument("--to-dir", required=True, help="Destination directory")
    p_exp.add_argument("--format", help="Specific format to export (default: all formats)")
    p_exp.add_argument("--include-cover", action="store_true", help="Also export cover image")

    p_rfmt = subparsers.add_parser("remove-formats", help="Remove specific formats (e.g. MBP, PDR) from books")
    p_rfmt.add_argument("--ids", nargs="+", type=int, required=True, help="Book IDs")
    p_rfmt.add_argument("--formats", nargs="+", required=True, help="Format names (e.g. MBP PDR)")
    p_rfmt.add_argument("--dry-run", action="store_true", help="Preview without deleting")

    p_rbook = subparsers.add_parser("remove-books", help="Remove books (moves to Calibre Trash by default)")
    p_rbook.add_argument("--ids", nargs="+", type=int, required=True, help="Book IDs to remove")
    p_rbook.add_argument("--permanent", action="store_true", help="Permanently delete instead of using Calibre Trash")
    p_rbook.add_argument("--dry-run", action="store_true", help="Preview without deleting")

    args = parser.parse_args(argv)
    write_mode = args.command != "export" and not getattr(args, "dry_run", False)
    cache, _ = open_cache(args.library, write_mode=write_mode, force=args.force)

    if args.command == "add-book":
        cmd_add_book(cache, args)
    elif args.command == "add-format":
        cmd_add_format(cache, args)
    elif args.command == "export":
        cmd_export(cache, args)
    elif args.command == "remove-formats":
        cmd_remove_formats(cache, args)
    elif args.command == "remove-books":
        cmd_remove_books(cache, args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
