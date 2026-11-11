"""Search, list, inspect books and library statistics using Calibre Python API.

Usage:
    calibre-debug -e search_books.py -- stats
    calibre-debug -e search_books.py -- search -q "author:Sapkowski"
    calibre-debug -e search_books.py -- show 6 49
    calibre-debug -e search_books.py -- categories --field authors
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from calibre_conn import open_cache, print_json, serialize_book_summary


def cmd_stats(cache, library_path: str) -> None:
    book_ids = cache.all_book_ids()
    fmt_counts: Counter[str] = Counter()
    lang_counts: Counter[str] = Counter()
    no_cover = 0
    no_format = 0

    for bid in book_ids:
        fmts = cache.formats(bid, verify_formats=True)
        if not fmts:
            no_format += 1
        for f in fmts:
            fmt_counts[f] += 1
        if not cache.field_for("cover", bid):
            no_cover += 1
        langs = cache.field_for("languages", bid)
        if not langs:
            lang_counts["(none)"] += 1
        else:
            for l in langs:
                lang_counts[l] += 1

    custom_cols = {
        k: {
            "name": v["name"],
            "datatype": v["datatype"],
            "is_multiple": bool(v.get("is_multiple")),
        }
        for k, v in cache.field_metadata.custom_field_metadata().items()
    }

    print_json(
        {
            "library_path": library_path,
            "total_books": len(book_ids),
            "total_authors": len(cache.all_field_names("authors")),
            "total_series": len(cache.all_field_names("series")),
            "total_tags": len(cache.all_field_names("tags")),
            "formats": dict(fmt_counts.most_common()),
            "languages": dict(lang_counts.most_common()),
            "books_without_cover": no_cover,
            "books_without_formats": no_format,
            "custom_columns": custom_cols,
        }
    )


def cmd_search(cache, query: str, sort_by: str, ascending: bool, limit: int | None) -> None:
    if query.strip():
        matched_ids = cache.search(query)
    else:
        matched_ids = set(cache.all_book_ids())

    sorted_ids = cache.multisort([(sort_by, ascending)], ids_to_sort=matched_ids)
    if limit is not None and limit > 0:
        sorted_ids = sorted_ids[:limit]

    books = [serialize_book_summary(cache, bid, include_comments=False) for bid in sorted_ids]
    print_json(
        {
            "query": query,
            "total_matches": len(matched_ids),
            "returned": len(books),
            "books": books,
        }
    )


def cmd_show(cache, book_ids: list[int]) -> None:
    results = []
    missing = []
    for bid in book_ids:
        if cache.has_id(bid):
            results.append(serialize_book_summary(cache, bid, include_comments=True))
        else:
            missing.append(bid)
    print_json({"books": results, "missing_ids": missing})


def cmd_categories(cache, field: str) -> None:
    from calibre.utils.icu import sort_key

    id_map = cache.get_id_map(field)
    usage = cache.get_usage_count_by_id(field)
    items = []
    for item_id, name in id_map.items():
        items.append(
            {
                "id": item_id,
                "name": name,
                "count": usage.get(item_id, 0),
            }
        )
    items.sort(key=lambda x: sort_key(x["name"]))
    print_json({"field": field, "total_items": len(items), "items": items})


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Search and inspect Calibre library via Python API.")
    parser.add_argument("--library", help="Path to Calibre library directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("stats", help="Show library statistics")

    p_search = subparsers.add_parser("search", help="Search or list books")
    p_search.add_argument("-q", "--query", default="", help="Calibre search query (empty = all books)")
    p_search.add_argument("--sort", default="timestamp", help="Field to sort by (default: timestamp)")
    p_search.add_argument("--asc", action="store_true", help="Sort ascending (default: descending)")
    p_search.add_argument("-n", "--limit", type=int, default=50, help="Max results (0 = unlimited)")

    p_show = subparsers.add_parser("show", help="Show full metadata for specific book IDs")
    p_show.add_argument("book_ids", nargs="+", type=int, help="Book IDs")

    p_cat = subparsers.add_parser("categories", help="List all values and counts for a category field")
    p_cat.add_argument(
        "--field",
        default="authors",
        choices=["authors", "tags", "series", "publisher", "languages", "formats"],
        help="Category field name",
    )

    args = parser.parse_args(argv)
    cache, lib_path = open_cache(args.library, write_mode=False)

    if args.command == "stats":
        cmd_stats(cache, lib_path)
    elif args.command == "search":
        limit = None if args.limit == 0 else args.limit
        cmd_search(cache, args.query, args.sort, args.asc, limit)
    elif args.command == "show":
        cmd_show(cache, args.book_ids)
    elif args.command == "categories":
        cmd_categories(cache, args.field)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
