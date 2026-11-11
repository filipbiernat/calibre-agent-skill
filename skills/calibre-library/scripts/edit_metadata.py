"""Edit book metadata, rename/merge authors/tags/series, and clean up tags via Calibre Python API.

Usage:
    # Update fields on one or more books:
    calibre-debug -e edit_metadata.py -- set --ids 6 49 --languages pol --series "Wiedźmin" --series-index 2

    # Rename or merge an author/tag/series across the library (if target name exists, Calibre merges them!):
    calibre-debug -e edit_metadata.py -- rename-item --field authors --from "CLANCY TOM" --to "Tom Clancy"

    # Remove specific garbage tags from the entire library:
    calibre-debug -e edit_metadata.py -- remove-items --field tags --names "YA)" "and deeply moving"
"""

from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from calibre_conn import open_cache, print_json, serialize_book_summary


def cmd_set_fields(cache, args) -> None:
    book_ids = [bid for bid in args.ids if cache.has_id(bid)]
    missing_ids = [bid for bid in args.ids if not cache.has_id(bid)]
    if not book_ids:
        print_json({"error": "No valid book IDs found", "missing_ids": missing_ids})
        return

    planned_changes: dict[str, dict[int, object]] = {}

    if args.title is not None:
        planned_changes["title"] = {bid: args.title for bid in book_ids}
    if args.authors is not None:
        authors_list = [a.strip() for a in args.authors.split("&") if a.strip()]
        planned_changes["authors"] = {bid: authors_list for bid in book_ids}
    if args.series is not None:
        planned_changes["series"] = {bid: args.series for bid in book_ids}
    if args.series_index is not None:
        planned_changes["series_index"] = {bid: args.series_index for bid in book_ids}
    if args.languages is not None:
        langs = [l.strip() for l in args.languages.split(",") if l.strip()]
        planned_changes["languages"] = {bid: langs for bid in book_ids}
    if args.rating is not None:
        planned_changes["rating"] = {bid: args.rating for bid in book_ids}
    if args.publisher is not None:
        planned_changes["publisher"] = {bid: args.publisher for bid in book_ids}
    if args.comments is not None:
        planned_changes["comments"] = {bid: args.comments for bid in book_ids}

    if args.tags is not None or args.add_tags or args.remove_tags:
        tags_map = {}
        for bid in book_ids:
            current = list(cache.field_for("tags", bid) or ())
            if args.tags is not None:
                current = [t.strip() for t in args.tags.split(",") if t.strip()]
            if args.add_tags:
                for t in args.add_tags:
                    if t not in current:
                        current.append(t)
            if args.remove_tags:
                remove_set = {t.lower() for t in args.remove_tags}
                current = [t for t in current if t.lower() not in remove_set]
            tags_map[bid] = current
        planned_changes["tags"] = tags_map

    if args.dry_run:
        print_json(
            {
                "dry_run": True,
                "book_ids": book_ids,
                "planned_changes": {k: {str(bid): v for bid, v in m.items()} for k, m in planned_changes.items()},
                "cover_path": args.cover,
            }
        )
        return

    affected: set[int] = set()
    for field_name, val_map in planned_changes.items():
        changed = cache.set_field(field_name, val_map, allow_case_change=True)
        affected.update(changed)

    if args.cover:
        cover_path = os.path.abspath(args.cover)
        with open(cover_path, "rb") as f:
            cover_bytes = f.read()
        cache.set_cover({bid: cover_bytes for bid in book_ids})
        affected.update(book_ids)

    updated_books = [serialize_book_summary(cache, bid) for bid in book_ids]
    print_json(
        {
            "dry_run": False,
            "affected_book_ids": sorted(affected),
            "missing_ids": missing_ids,
            "updated_books": updated_books,
        }
    )


def cmd_rename_item(cache, args) -> None:
    item_id = cache.get_item_id(args.field, args.from_name, case_sensitive=True)
    if item_id is None:
        item_id = cache.get_item_id(args.field, args.from_name, case_sensitive=False)
    if item_id is None:
        print_json({"error": f"Item '{args.from_name}' not found in field '{args.field}'"})
        return

    affected_books = sorted(cache.books_for_field(args.field, item_id))
    if args.dry_run:
        print_json(
            {
                "dry_run": True,
                "field": args.field,
                "item_id": item_id,
                "from": args.from_name,
                "to": args.to_name,
                "affected_book_ids": affected_books,
            }
        )
        return

    changed_books, id_map = cache.rename_items(args.field, {item_id: args.to_name})
    print_json(
        {
            "dry_run": False,
            "field": args.field,
            "from": args.from_name,
            "to": args.to_name,
            "affected_book_ids": sorted(changed_books),
            "old_to_new_id_map": {str(k): v for k, v in id_map.items()},
        }
    )


def cmd_remove_items(cache, args) -> None:
    found_ids = []
    not_found = []
    for name in args.names:
        iid = cache.get_item_id(args.field, name, case_sensitive=True)
        if iid is None:
            iid = cache.get_item_id(args.field, name, case_sensitive=False)
        if iid is not None:
            found_ids.append((name, iid))
        else:
            not_found.append(name)

    if args.dry_run:
        print_json(
            {
                "dry_run": True,
                "field": args.field,
                "items_to_remove": [{"name": n, "id": i} for n, i in found_ids],
                "not_found": not_found,
            }
        )
        return

    if not found_ids:
        print_json({"removed": [], "not_found": not_found, "affected_book_ids": []})
        return

    affected_books = cache.remove_items(args.field, [i for _, i in found_ids])
    print_json(
        {
            "dry_run": False,
            "field": args.field,
            "removed": [{"name": n, "id": i} for n, i in found_ids],
            "not_found": not_found,
            "affected_book_ids": sorted(affected_books),
        }
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Edit metadata in Calibre library via Python API.")
    parser.add_argument("--library", help="Path to Calibre library directory")
    parser.add_argument("--force", action="store_true", help="Allow write even if Calibre GUI is running")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_set = subparsers.add_parser("set", help="Set metadata fields on one or more books")
    p_set.add_argument("--ids", nargs="+", type=int, required=True, help="Book IDs to update")
    p_set.add_argument("--title", help="New title")
    p_set.add_argument("--authors", help="Authors separated by '&' (e.g. 'Tom Clancy & Steve Pieczenik')")
    p_set.add_argument("--series", help="Series name (empty string to clear)")
    p_set.add_argument("--series-index", type=float, help="Series index number")
    p_set.add_argument("--tags", help="Replace all tags with comma-separated list")
    p_set.add_argument("--add-tags", nargs="+", help="Add one or more tags to existing tags")
    p_set.add_argument("--remove-tags", nargs="+", help="Remove specific tags from the selected books")
    p_set.add_argument("--languages", help="Comma-separated ISO language codes (e.g. 'pol', 'eng')")
    p_set.add_argument("--rating", type=int, choices=range(0, 11), help="Rating from 0 to 10 (2=1 star, 10=5 stars)")
    p_set.add_argument("--publisher", help="Publisher name")
    p_set.add_argument("--comments", help="Book description/comments (HTML or plain text)")
    p_set.add_argument("--cover", help="Path to cover image file")
    p_set.add_argument("--dry-run", action="store_true", help="Preview changes without modifying database")

    p_ren = subparsers.add_parser("rename-item", help="Rename or merge an author, tag, series, or publisher")
    p_ren.add_argument("--field", required=True, choices=["authors", "tags", "series", "publisher"])
    p_ren.add_argument("--from", dest="from_name", required=True, help="Existing item name")
    p_ren.add_argument("--to", dest="to_name", required=True, help="New item name (merges if already exists)")
    p_ren.add_argument("--dry-run", action="store_true", help="Preview changes without modifying database")

    p_rem = subparsers.add_parser("remove-items", help="Delete specific tags/series/publishers from library")
    p_rem.add_argument("--field", required=True, choices=["tags", "series", "publisher"])
    p_rem.add_argument("--names", nargs="+", required=True, help="Exact names of items to remove")
    p_rem.add_argument("--dry-run", action="store_true", help="Preview changes without modifying database")

    args = parser.parse_args(argv)
    write_mode = not getattr(args, "dry_run", False)
    cache, _ = open_cache(args.library, write_mode=write_mode, force=args.force)

    if args.command == "set":
        cmd_set_fields(cache, args)
    elif args.command == "rename-item":
        cmd_rename_item(cache, args)
    elif args.command == "remove-items":
        cmd_remove_items(cache, args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
