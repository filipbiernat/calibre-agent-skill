# Calibre `new_api` (`calibre.db.cache.Cache`) Quick Reference

## Accessing the Database in `calibre-debug -e`

```python
from calibre.library import db

cache = db(r"C:\Filip\GoogleDrive\Biblioteka calibre").new_api
```

> **Important Gotcha with `calibre-debug -c`**:
> Avoid generator expressions `(x for x in y)` at the top level of `calibre-debug -c "..."` strings because `calibre-debug -c` uses `exec()` with a local scope dictionary, which causes `NameError` inside generator expressions. Either use list comprehensions `[x for x in y]` or run a script file with `calibre-debug -e script.py -- [args]`.

---

## Reading Metadata & Searching

| Method | Signature / Usage | Description |
| :--- | :--- | :--- |
| `all_book_ids()` | `cache.all_book_ids() -> frozenset[int]` | Set of all book IDs in the library. |
| `has_id(book_id)` | `cache.has_id(42) -> bool` | Check if a book ID exists. |
| `search(query)` | `cache.search('author:Sapkowski and not formats:MOBI') -> set[int]` | Run Calibre Query Language search and return matching book IDs. |
| `multisort(fields, ids_to_sort=None)` | `cache.multisort([('timestamp', False)], ids)` | Sort book IDs by one or more `(field, ascending)` tuples. |
| `field_for(name, book_id)` | `cache.field_for('title', 42)` | Fast single-field lookup. Multi-value fields (`authors`, `tags`, `languages`, `formats`) return tuples; `identifiers` returns a `dict`. |
| `all_field_for(name, book_ids)` | `cache.all_field_for('tags', [1, 2, 3])` | Bulk lookup for multiple books at once. |
| `get_metadata(book_id, get_cover=False)` | `mi = cache.get_metadata(42)` | Full `Metadata` object (slower than `field_for`, use when reading/writing full metadata objects). |
| `get_proxy_metadata(book_id)` | `pmi = cache.get_proxy_metadata(42)` | Lazy on-demand metadata object. |
| `all_field_names(field)` | `cache.all_field_names('tags') -> frozenset[str]` | All distinct values for a many-one or many-many field. |
| `get_id_map(field)` | `cache.get_id_map('authors') -> dict[int, str]` | Map of internal `item_id -> value` for a field. |
| `get_usage_count_by_id(field)` | `cache.get_usage_count_by_id('tags') -> dict[int, int]` | Map of `item_id -> book count`. |
| `get_item_id(field, item_name)` | `cache.get_item_id('authors', 'Tom Clancy')` | Lookup internal ID for an author/tag/series. |
| `books_for_field(name, item_id)` | `cache.books_for_field('tags', tag_id) -> set[int]` | Set of book IDs associated with `item_id`. |

---

## Writing & Updating Metadata

> **Safety Rule**: Never call write methods while `calibre.exe` (GUI) is running! Always check with `calibre_conn.ensure_safe_for_write()`.

| Method | Signature / Usage | Description |
| :--- | :--- | :--- |
| `set_field(name, book_id_to_val_map)` | `cache.set_field('languages', {6: ['pol'], 49: ['pol']})` | Bulk update a field across many books in a single transaction. Returns affected book IDs. |
| `set_metadata(book_id, mi)` | `cache.set_metadata(42, mi)` | Update a book from a `Metadata` object. |
| `rename_items(field, item_id_to_new_name_map)` | `cache.rename_items('authors', {old_id: 'Tom Clancy'})` | Rename an author/tag/series/publisher. **If the target name already exists, Calibre automatically merges both items across all books!** |
| `remove_items(field, item_ids)` | `cache.remove_items('tags', [tag_id_1, tag_id_2])` | Completely remove specific tags/series from all books (or `restrict_to_book_ids`). |
| `set_cover(book_id_data_map)` | `cache.set_cover({42: cover_bytes})` | Set or remove (`None`) book covers. |
| `embed_metadata(book_ids, only_fmts=None)` | `cache.embed_metadata([42], only_fmts=['EPUB', 'MOBI'])` | Write database metadata & cover directly into the e-book files on disk. |

---

## Managing Books & Formats

| Method | Signature / Usage | Description |
| :--- | :--- | :--- |
| `formats(book_id, verify_formats=True)` | `cache.formats(42) -> tuple[str, ...]` | Tuple of uppercase format extensions (`('EPUB', 'MOBI')`). |
| `format_metadata(book_id, fmt)` | `cache.format_metadata(42, 'MOBI')` | Returns dict with `path`, `size`, `mtime`. |
| `copy_format_to(book_id, fmt, dest)` | `cache.copy_format_to(42, 'EPUB', r'C:\temp\out.epub')` | Thread-safe export of a book format to a file path or stream. |
| `copy_cover_to(book_id, dest)` | `cache.copy_cover_to(42, r'C:\temp\cover.jpg')` | Thread-safe export of a book's cover image. |
| `add_books(books, add_duplicates=True)` | `cache.add_books([(mi, {'EPUB': path})])` | Add new books. Returns `(created_ids, duplicates)`. |
| `add_format(book_id, fmt, stream_or_path, replace=True)` | `cache.add_format(42, 'MOBI', r'C:\temp\book.mobi')` | Attach or replace a format file for an existing book. |
| `remove_formats(formats_map, db_only=False)` | `cache.remove_formats({47: ['MBP']})` | Delete specific formats from specified books. |
| `remove_books(book_ids, permanent=False)` | `cache.remove_books([262], permanent=False)` | Remove books. When `permanent=False`, files are moved to the library's `.caltrash` directory and can be restored with `move_book_from_trash(book_id)`. |
| `find_identical_books(mi)` | `cache.find_identical_books(mi) -> set[int]` | Fuzzy-match title and author superset to detect duplicates. |

---

## Annotations & Notes

| Method | Signature / Usage | Description |
| :--- | :--- | :--- |
| `all_annotations_for_book(book_id)` | `cache.all_annotations_for_book(42)` | All highlights/bookmarks/notes for a book. |
| `search_annotations(fts_engine_query)` | `cache.search_annotations('keyword')` | Full-text search across annotations. |
| `notes_for(field, item_id)` | `cache.notes_for('authors', author_id)` | Read HTML note attached to an author/tag/series. |
