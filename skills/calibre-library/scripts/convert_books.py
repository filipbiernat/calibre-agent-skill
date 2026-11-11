"""Convert e-book formats (e.g., EPUB -> MOBI for Kindle) and store them in the Calibre library.

Usage:
    # Convert specific book(s) to MOBI:
    calibre-debug -e convert_books.py -- --ids 1 6 119 --to MOBI

    # Find and convert all books that have EPUB but no MOBI (preview with --dry-run):
    calibre-debug -e convert_books.py -- --missing-mobi --dry-run
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from calibre_conn import open_cache, print_json

SOURCE_PRIORITY = ["EPUB", "AZW3", "AZW", "DOCX", "RTF", "FB2", "HTML", "TXT", "PDF"]


def find_ebook_convert() -> str:
    exe = shutil.which("ebook-convert")
    if exe:
        return exe
    default_win = r"C:\Program Files\Calibre2\ebook-convert.exe"
    if os.path.isfile(default_win):
        return default_win
    raise FileNotFoundError("ebook-convert executable not found in PATH or C:\\Program Files\\Calibre2")


def pick_source_format(available_fmts: tuple[str, ...], preferred_from: str | None, target_fmt: str) -> str | None:
    avail_upper = {f.upper() for f in available_fmts}
    if preferred_from:
        pf = preferred_from.upper()
        return pf if pf in avail_upper else None
    for candidate in SOURCE_PRIORITY:
        if candidate != target_fmt and candidate in avail_upper:
            return candidate
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Convert books in Calibre library (e.g. EPUB -> MOBI for Kindle).")
    parser.add_argument("--library", help="Path to Calibre library directory")
    parser.add_argument("--ids", nargs="+", type=int, help="Specific book IDs to convert")
    parser.add_argument(
        "--missing-mobi",
        action="store_true",
        help="Automatically select all books that have EPUB/DOCX/RTF but lack MOBI",
    )
    parser.add_argument("--from", dest="from_fmt", help="Source format (default: auto-select best, e.g. EPUB)")
    parser.add_argument("--to", dest="to_fmt", default="MOBI", help="Target format (default: MOBI)")
    parser.add_argument("--overwrite", action="store_true", help="Re-convert even if target format already exists")
    parser.add_argument("--extra-args", nargs="*", default=[], help="Extra arguments passed to ebook-convert")
    parser.add_argument("--dry-run", action="store_true", help="List books that would be converted without running")
    parser.add_argument("--force", action="store_true", help="Allow write even if Calibre GUI is running")

    args = parser.parse_args(argv)
    target_fmt = args.to_fmt.upper()

    cache, _ = open_cache(args.library, write_mode=not args.dry_run, force=args.force)

    candidate_ids: list[int] = []
    if args.ids:
        candidate_ids = [bid for bid in args.ids if cache.has_id(bid)]
    elif args.missing_mobi:
        for bid in sorted(cache.all_book_ids()):
            fmts = set(cache.formats(bid, verify_formats=True))
            if "MOBI" not in fmts and (fmts & {"EPUB", "DOCX", "RTF", "AZW3"}):
                candidate_ids.append(bid)
    else:
        parser.error("Specify either --ids <id...> or --missing-mobi")

    plan = []
    skipped = []
    for bid in candidate_ids:
        title = cache.field_for("title", bid)
        avail = cache.formats(bid, verify_formats=True)
        if target_fmt in avail and not args.overwrite:
            skipped.append({"id": bid, "title": title, "reason": f"already_has_{target_fmt}"})
            continue
        src_fmt = pick_source_format(avail, args.from_fmt, target_fmt)
        if not src_fmt:
            skipped.append({"id": bid, "title": title, "reason": "no_suitable_source_format", "formats": list(avail)})
            continue
        plan.append({"id": bid, "title": title, "from": src_fmt, "to": target_fmt})

    if args.dry_run:
        print_json({"dry_run": True, "planned_conversions": plan, "skipped": skipped})
        return 0

    ebook_convert = find_ebook_convert()
    env = os.environ.copy()
    env["CALIBRE_OVERRIDE_LANG"] = "en"

    converted = []
    errors = []

    with tempfile.TemporaryDirectory(prefix="calibre_conv_") as tmpdir:
        for item in plan:
            bid = item["id"]
            src_fmt = item["from"]
            src_file = os.path.join(tmpdir, f"book_{bid}.{src_fmt.lower()}")
            dst_file = os.path.join(tmpdir, f"book_{bid}.{target_fmt.lower()}")

            try:
                cache.copy_format_to(bid, src_fmt, src_file)
                cmd = [ebook_convert, src_file, dst_file] + list(args.extra_args)
                proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
                if proc.returncode != 0 or not os.path.isfile(dst_file):
                    errors.append(
                        {
                            "id": bid,
                            "title": item["title"],
                            "error": proc.stderr.strip() or proc.stdout.strip() or f"Exit code {proc.returncode}",
                        }
                    )
                    continue

                cache.add_format(bid, target_fmt, dst_file, replace=True)
                converted.append(item)
            except Exception as exc:
                errors.append({"id": bid, "title": item["title"], "error": str(exc)})

    print_json(
        {
            "dry_run": False,
            "converted_count": len(converted),
            "converted": converted,
            "skipped": skipped,
            "errors": errors,
        }
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
