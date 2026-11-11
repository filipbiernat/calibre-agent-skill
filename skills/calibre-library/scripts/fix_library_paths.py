"""Fix Google Drive / Calibre path desyncs, rescue misplaced formats, and clean up desktop.ini ghost folders.

Usage:
    # Preview all fixes without modifying disk or database:
    calibre-debug -e fix_library_paths.py -- --dry-run

    # Execute fixes:
    calibre-debug -e fix_library_paths.py
"""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import shutil
import stat
import sys
import tempfile
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from calibre_conn import open_cache, print_json

EBOOK_EXTS = {
    ".mobi", ".epub", ".azw", ".azw3", ".pdf", ".docx", ".rtf",
    ".txt", ".fb2", ".lit", ".html", ".zip", ".mbp", ".pdr", ".lnk"
}


def unlock_windows_path(path: str) -> None:
    """Clear ReadOnly, Hidden, and System attributes set by Google Drive on Windows."""
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x80)  # FILE_ATTRIBUTE_NORMAL
        except Exception:
            pass
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass


def force_rmtree(root_path: str) -> None:
    """Remove directory tree even when Google Drive desktop.ini files have System/ReadOnly attributes."""
    if not os.path.exists(root_path):
        return
    for r, dirs, files in os.walk(root_path, topdown=False):
        for f in files:
            fp = os.path.join(r, f)
            unlock_windows_path(fp)
            try:
                os.unlink(fp)
            except Exception:
                pass
        for d in dirs:
            dp = os.path.join(r, d)
            unlock_windows_path(dp)
            try:
                os.rmdir(dp)
            except Exception:
                pass
    unlock_windows_path(root_path)
    shutil.rmtree(root_path, onerror=lambda func, p, exc: (unlock_windows_path(p), func(p)))


def remove_desktop_ini_in_dir(folder_path: str) -> None:
    """Unlock and remove desktop.ini inside folder_path so Calibre's rmtree won't hit WinError 5."""
    if not os.path.isdir(folder_path):
        return
    unlock_windows_path(folder_path)
    ini_path = os.path.join(folder_path, "desktop.ini")
    if os.path.lexists(ini_path):
        unlock_windows_path(ini_path)
        try:
            os.unlink(ini_path)
        except Exception:
            pass


def find_ebook_files(folder_path: str) -> dict[str, str]:
    """Return map of {FORMAT: full_path} for ebook files in folder_path."""
    found: dict[str, str] = {}
    if not os.path.isdir(folder_path):
        return found
    for fname in os.listdir(folder_path):
        low = fname.lower()
        if low in {"desktop.ini", "metadata.opf", "cover.jpg"}:
            continue
        _, ext = os.path.splitext(fname)
        if ext.lower() in EBOOK_EXTS:
            found[ext.lstrip(".").upper()] = os.path.join(folder_path, fname)
    return found


def is_only_junk_files(folder_path: str, allow_opf: bool = True) -> bool:
    """Return True if folder contains only desktop.ini (and optionally metadata.opf) and no subdirectories."""
    if not os.path.isdir(folder_path):
        return False
    allowed = {"desktop.ini"}
    if allow_opf:
        allowed.add("metadata.opf")
    for entry in os.listdir(folder_path):
        full = os.path.join(folder_path, entry)
        if os.path.isdir(full):
            return False
        if entry.lower() not in allowed:
            return False
    return True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Repair Google Drive path desyncs, missing formats, and empty desktop.ini folders in Calibre."
    )
    parser.add_argument("--library", help="Path to Calibre library directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview all actions without applying changes")
    parser.add_argument("--force", action="store_true", help="Allow running even if Calibre GUI is open")
    args = parser.parse_args(argv)

    cache, lib_path = open_cache(args.library, write_mode=not args.dry_run, force=args.force)

    id_dir_pattern = re.compile(r"\((\d+)\)$")
    folders_by_id: dict[int, list[str]] = defaultdict(list)

    for root, dirs, _ in os.walk(lib_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        base = os.path.basename(root)
        m = id_dir_pattern.search(base)
        if m:
            bid = int(m.group(1))
            rel_dir = os.path.relpath(root, lib_path).replace(os.sep, "/")
            folders_by_id[bid].append(rel_dir)

    rescued_books = []
    removed_ghost_formats = []
    removed_ghost_duplicate_books = []
    restored_untracked_books = []
    archived_duplicate_folders = []
    deleted_empty_folders = []

    # 1. Rescue books in DB whose db_path lost its files because they are in a sibling (book_id) folder
    for bid in sorted(cache.all_book_ids()):
        db_rel_path = cache.field_for("path", bid)
        db_fmts = set(cache.formats(bid, verify_formats=False))
        disk_fmts = set(cache.formats(bid, verify_formats=True))
        missing_fmts = db_fmts - disk_fmts

        if missing_fmts:
            candidate_dirs = folders_by_id.get(bid, [])
            for cand_rel in candidate_dirs:
                if cand_rel == db_rel_path:
                    continue
                cand_abs = os.path.join(lib_path, cand_rel.replace("/", os.sep))
                found_map = find_ebook_files(cand_abs)
                rescuable = {fmt: fpath for fmt, fpath in found_map.items() if fmt in missing_fmts}
                if rescuable:
                    cover_file = os.path.join(cand_abs, "cover.jpg")
                    has_cover_file = os.path.isfile(cover_file)
                    rescued_books.append(
                        {
                            "id": bid,
                            "title": cache.field_for("title", bid),
                            "old_db_path": db_rel_path,
                            "rescued_from": cand_rel,
                            "formats": sorted(rescuable.keys()),
                            "cover_rescued": has_cover_file,
                        }
                    )
                    if not args.dry_run:
                        with tempfile.TemporaryDirectory(prefix="calibre_rescue_") as tmpdir:
                            staged_formats = {}
                            for fmt, fpath in rescuable.items():
                                dst_tmp = os.path.join(tmpdir, os.path.basename(fpath))
                                shutil.copy2(fpath, dst_tmp)
                                staged_formats[fmt] = dst_tmp
                            staged_cover = None
                            if has_cover_file:
                                with open(cover_file, "rb") as cf:
                                    staged_cover = cf.read()

                            # Unlock old_db_path and cand_abs so Calibre's internal rmtree won't hit WinError 5 on desktop.ini
                            if db_rel_path:
                                old_abs = os.path.join(lib_path, db_rel_path.replace("/", os.sep))
                                remove_desktop_ini_in_dir(old_abs)
                                remove_desktop_ini_in_dir(os.path.dirname(old_abs))
                            remove_desktop_ini_in_dir(cand_abs)
                            remove_desktop_ini_in_dir(os.path.dirname(cand_abs))

                            # Update path in cache and re-attach formats + cover from safe temp copy
                            cache.update_path({bid})
                            for fmt, tmp_fpath in staged_formats.items():
                                cache.add_format(bid, fmt, tmp_fpath, replace=True)
                            if staged_cover is not None:
                                cache.set_cover({bid: staged_cover})

                        new_db_rel = cache.field_for("path", bid)
                        if cand_rel != new_db_rel and os.path.exists(cand_abs):
                            trash_backup = os.path.join(
                                lib_path, ".caltrash", "rescued_duplicates", f"book_{bid}_{os.path.basename(cand_abs)}"
                            )
                            os.makedirs(os.path.dirname(trash_backup), exist_ok=True)
                            remove_desktop_ini_in_dir(cand_abs)
                            shutil.move(cand_abs, trash_backup)

        # Re-check if any formats are still missing on disk after rescue
        db_fmts_after = set(cache.formats(bid, verify_formats=False))
        disk_fmts_after = set(cache.formats(bid, verify_formats=True))
        still_missing = sorted(db_fmts_after - disk_fmts_after)

        if still_missing:
            if disk_fmts_after:
                # Book has valid working formats on disk, just remove stale ghost format records from DB
                removed_ghost_formats.append(
                    {
                        "id": bid,
                        "title": cache.field_for("title", bid),
                        "removed_db_only_formats": still_missing,
                        "remaining_valid_formats": sorted(disk_fmts_after),
                    }
                )
                if not args.dry_run:
                    cache.remove_formats({bid: still_missing}, db_only=True)
            else:
                # Book has zero files on disk anywhere; check if an identical title+author book exists with files
                title = cache.field_for("title", bid)
                authors = cache.field_for("authors", bid)
                duplicate_with_files = []
                for other_id in cache.all_book_ids():
                    if other_id != bid and cache.field_for("title", other_id) == title and cache.field_for("authors", other_id) == authors:
                        if cache.formats(other_id, verify_formats=True):
                            duplicate_with_files.append(other_id)
                if duplicate_with_files:
                    removed_ghost_duplicate_books.append(
                        {
                            "id": bid,
                            "title": title,
                            "replaced_by_book_ids": duplicate_with_files,
                        }
                    )
                    if not args.dry_run:
                        cache.remove_books([bid], permanent=True)

    # 2. Check folders on disk whose (ID) is NOT in metadata.db at all
    from calibre.ebooks.metadata.meta import get_metadata
    from calibre.ebooks.metadata.opf2 import OPF

    for bid, rel_dirs in sorted(folders_by_id.items()):
        if cache.has_id(bid):
            continue
        for rel_dir in rel_dirs:
            abs_dir = os.path.join(lib_path, rel_dir.replace("/", os.sep))
            if not os.path.isdir(abs_dir):
                continue
            ebook_map = find_ebook_files(abs_dir)
            if not ebook_map:
                continue

            # Determine metadata from metadata.opf or ebook file
            opf_path = os.path.join(abs_dir, "metadata.opf")
            mi = None
            if os.path.isfile(opf_path):
                try:
                    with open(opf_path, "rb") as f:
                        mi = OPF(f, basedir=abs_dir).to_book_metadata()
                except Exception:
                    mi = None
            if mi is None:
                first_fmt, first_path = next(iter(ebook_map.items()))
                with open(first_path, "rb") as f:
                    mi = get_metadata(f, stream_type=first_fmt.lower(), use_libprs_metadata=True)

            identical = sorted(cache.find_identical_books(mi))
            if not identical and mi.title:
                # Fallback fuzzy check: strip author prefix/numbers (e.g. "Lee Child - 12 - Nic do stracenia")
                tail_parts = [p.strip() for p in mi.title.split("-") if p.strip()]
                core_phrase = tail_parts[-1].lower() if tail_parts else mi.title.lower()
                if len(core_phrase) >= 5:
                    for other_id in cache.all_book_ids():
                        other_title = (cache.field_for("title", other_id) or "").lower()
                        if core_phrase in other_title:
                            identical.append(other_id)
            if identical:
                # Already exists in DB under another ID; move orphaned duplicate folder to .caltrash backup
                archived_duplicate_folders.append(
                    {
                        "orphaned_id": bid,
                        "rel_dir": rel_dir,
                        "title": mi.title,
                        "existing_book_ids": identical,
                    }
                )
                if not args.dry_run:
                    backup_dest = os.path.join(
                        lib_path, ".caltrash", "orphaned_duplicates", f"{bid}_{os.path.basename(abs_dir)}"
                    )
                    os.makedirs(os.path.dirname(backup_dest), exist_ok=True)
                    remove_desktop_ini_in_dir(abs_dir)
                    shutil.move(abs_dir, backup_dest)
            else:
                # Genuinely missing from DB (e.g. Parabellum. Horyzont zdarzen (296))! Restore it into DB!
                restored_untracked_books.append(
                    {
                        "old_folder_id": bid,
                        "rel_dir": rel_dir,
                        "title": mi.title,
                        "authors": list(mi.authors or ()),
                        "formats": sorted(ebook_map.keys()),
                    }
                )
                if not args.dry_run:
                    created_ids, _ = cache.add_books([(mi, ebook_map)], add_duplicates=False)
                    if created_ids:
                        new_id = created_ids[0]
                        cover_path = os.path.join(abs_dir, "cover.jpg")
                        if os.path.isfile(cover_path):
                            with open(cover_path, "rb") as cf:
                                cache.set_cover({new_id: cf.read()})
                        restored_untracked_books[-1]["new_book_id"] = new_id
                        # Move old untracked directory into .caltrash backup if different from new book path
                        new_rel_path = cache.field_for("path", new_id)
                        if rel_dir != new_rel_path and os.path.exists(abs_dir):
                            backup_dest = os.path.join(
                                lib_path, ".caltrash", "restored_originals", f"{bid}_{os.path.basename(abs_dir)}"
                            )
                            os.makedirs(os.path.dirname(backup_dest), exist_ok=True)
                            remove_desktop_ini_in_dir(abs_dir)
                            shutil.move(abs_dir, backup_dest)

    # 3. Clean up empty/ghost folders that only contain desktop.ini (and stale metadata.opf for non-active paths)
    active_db_paths: set[str] = set()
    for bid in cache.all_book_ids():
        p = cache.field_for("path", bid)
        if p:
            active_db_paths.add(p)
            parent = os.path.dirname(p).replace(os.sep, "/")
            if parent:
                active_db_paths.add(parent)

    # Walk bottom-up so parent author folders become empty once child ghost folders are removed
    for root, dirs, files in os.walk(lib_path, topdown=False):
        rel_dir = os.path.relpath(root, lib_path).replace(os.sep, "/")
        if rel_dir == "." or rel_dir.startswith("."):
            continue
        if rel_dir in active_db_paths:
            continue
        if is_only_junk_files(root, allow_opf=True):
            deleted_empty_folders.append(rel_dir)
            if not args.dry_run:
                force_rmtree(root)

    print_json(
        {
            "dry_run": args.dry_run,
            "summary": {
                "rescued_books_count": len(rescued_books),
                "restored_untracked_books_count": len(restored_untracked_books),
                "removed_ghost_formats_count": len(removed_ghost_formats),
                "removed_ghost_duplicate_books_count": len(removed_ghost_duplicate_books),
                "archived_duplicate_folders_count": len(archived_duplicate_folders),
                "deleted_empty_folders_count": len(deleted_empty_folders),
            },
            "rescued_books": rescued_books,
            "restored_untracked_books": restored_untracked_books,
            "removed_ghost_formats": removed_ghost_formats,
            "removed_ghost_duplicate_books": removed_ghost_duplicate_books,
            "archived_duplicate_folders": archived_duplicate_folders,
            "deleted_empty_folders": deleted_empty_folders,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
