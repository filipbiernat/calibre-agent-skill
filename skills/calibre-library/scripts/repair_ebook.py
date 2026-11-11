#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair_ebook.py — Universal E-Book Cleaner and Repair Toolkit.

Automatically repairs common EPUB/XHTML formatting artifacts, OCR errors,
broken paragraphs from PDF conversions, malformed HTML headings, and regenerates
navigation tables of contents (NCX). Also provides direct conversion and repair
from legacy MOBI / AZW files to clean EPUB without external dependencies.

Features:
1. Malformed XHTML & Head Section Repair:
   - Strips illegal <p> tags and MS Office/Word conditional comments (<!--[if ... <![endif]-->) from <head>.
   - Removes broken Word link references (filelist.xml, themedata.thmx, colorschememapping.xml).
   - Replaces corrupted or empty document titles/authors (e.g. unamed, index,  replacement characters).
2. Broken Paragraph Merging:
   - Intelligently merges lines/paragraphs artificially split by PDF/OCR column breaks.
   - Preserves dialogues, poetry, blockquotes, headings, and formatted lists.
   - Handles hyphenated word splits across line breaks.
3. Whitespace & Typography Cleanup:
   - Collapses multiple consecutive spaces, hard tabs, and forced non-breaking spaces within text nodes.
   - Removes leading indentation spaces right after opening <p> tags.
   - Fixes missing spacing around dialogue dashes (em/en-dashes: "–Word" -> "– Word").
   - Fixes glued punctuation missing trailing spaces (".Word" -> ". Word", "!Word" -> "! Word").
4. Generator Cruft Removal:
   - Removes advertising footers and boilerplates (e.g. BookDesigner, LRS/LRF parsers).
   - Strips self-closing empty paragraph tags (<p .../>) that disrupt e-reader flow.
   - Unwraps fragmented styling spans.
5. Heading & Table of Contents (TOC) Reconstruction:
   - Promotes chapter titles, prologues, and epilogues to proper <h2> headings.
   - Regenerates complete, valid toc.ncx navigation maps.
6. Standalone MOBI/AZW -> Clean EPUB:
   - Built-in PalmDOC / LZ77 decompression.
   - Extracts embedded images and EXTH metadata.
   - Reconstructs clean XHTML files and generates valid EPUB packages.

Usage:
    # Repair a single EPUB file:
    python repair_ebook.py "path/to/book.epub"

    # Repair all EPUBs in current directory:
    python repair_ebook.py --all

    # Overwrite originals in-place (creates backup/):
    python repair_ebook.py "path/to/book.epub" --in-place

    # Direct MOBI -> repaired EPUB:
    python repair_ebook.py "path/to/book.mobi"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
from html import escape, unescape


# ==============================================================================
# 1. Text & HTML Helpers
# ==============================================================================

def strip_tags(html_str: str) -> str:
    """Strip all XML/HTML tags and decode HTML entities."""
    return unescape(re.sub(r'<[^>]+>', '', html_str))


def clean_inline_spaces(html_body: str) -> tuple[str, int]:
    """
    Collapse multiple spaces, tabs, and non-breaking spaces within text nodes,
    and remove leading spaces at paragraph starts (<p>  Text).
    """
    count = 0

    def repl_text(match):
        nonlocal count
        txt = match.group(0)
        if not txt.strip():
            return txt
        new_txt, n = re.subn(r'(?<=\S)[ \t\xa0]{2,}(?=\S)', ' ', txt)
        count += n
        new_txt = re.sub(r'\s*\r?\n\s*', ' ', new_txt)
        new_txt = re.sub(r' {2,}', ' ', new_txt)
        return new_txt

    cleaned = re.sub(r'(?<=>)[^<]+(?=<)', repl_text, html_body)

    # Remove leading spaces right after <p> or <p><span>
    cleaned, n_lead = re.subn(
        r'(<p\b[^>]*>(?:\s*<span\b[^>]*>)?)[ \t]+(?=\S)',
        r'\1',
        cleaned,
        flags=re.I
    )
    count += n_lead
    return cleaned, count


def fix_dialogue_and_punctuation_spacing(html_body: str) -> tuple[str, int]:
    """
    Fix typographic spacing around dashes and punctuation:
    - Missing space after dialogue dash at paragraph start ('–Text' -> '– Text').
    - Missing space before/after dash within sentences ('word– word' -> 'word – word').
    - Missing space after sentence punctuation before capital letters ('end.Start' -> 'end. Start').
    """
    fixes = 0

    # Dialogue dash at paragraph start
    html_body, n = re.subn(
        r'(<p\b[^>]*>(?:\s*<(?:span|i|b|em|strong)\b[^>]*>)*\s*)([–—])([^\s–—<>0-9])',
        r'\1\2 \3',
        html_body
    )
    fixes += n

    def fix_text_node(m):
        nonlocal fixes
        txt = m.group(0)
        if not txt.strip():
            return txt

        # Punctuation directly followed by dash without space: ".–Text" or ".– Text"
        txt, n1 = re.subn(
            r'([.!?…”"»\]])([–—])\s*([A-Za-z0-9\u00C0-\u024F])',
            r'\1 \2 \3',
            txt
        )
        # Word glued to dash before a space: "word– word"
        txt, n2 = re.subn(
            r'([A-Za-z0-9\u00C0-\u024F])([–—])\s+([A-Za-z0-9\u00C0-\u024F])',
            r'\1 \2 \3',
            txt
        )
        # Missing space after period, exclamation, or question mark before a capital letter
        txt, n3 = re.subn(
            r'([a-z\u00E0-\u024F]{2,})([.!?])([A-Z\u00C0-\u00DE][a-z\u00E0-\u024F])',
            r'\1\2 \3',
            txt
        )
        fixes += (n1 + n2 + n3)
        return txt

    html_body = re.sub(r'(?<=>)[^<]+(?=<)', fix_text_node, html_body)
    return html_body, fixes


def clean_generator_cruft(html_body: str) -> tuple[str, int]:
    """
    Strip known advertising footers and empty self-closing paragraph tags.
    """
    fixes = 0

    # BookDesigner / LRS boilerplates
    html_body, n1 = re.subn(
        r'<div\b[^>]*>\s*<p\b[^>]*>\s*(?:<span[^>]*>)?\s*This file was created with BookDesigner program.*?\s*</div>',
        '',
        html_body,
        flags=re.S | re.I
    )
    html_body, n2 = re.subn(
        r'<p\b[^>]*>\s*(?:<(?:span|b|i|font)[^>]*>\s*)*(?:This file was created with BookDesigner program|bookdesigner@the-ebook\.org|bd\.toosnow\.com|LRS to LRF parser[^<]*).*?</p>',
        '',
        html_body,
        flags=re.S | re.I
    )
    # Self-closing empty paragraphs (<p class="calibre"/>)
    html_body, n3 = re.subn(r'<p\b(?![^>]*/>)[^>]*/>\s*', '', html_body, flags=re.I)
    html_body, n3b = re.subn(r'<p\b[^>]*/>\s*', '', html_body, flags=re.I)

    # Fix unclosed footnote links encompassing following text: <a ...>[1]</a> following text
    def fix_unclosed_footnote_link(m):
        inner_link = m.group(1)
        following = m.group(2)
        if 'note' in following.lower() or 'przyp' in following.lower():
            return m.group(0)
        return f"{inner_link}</a> {following}"

    html_body, n4 = re.subn(
        r'(<a\b[^>]*>\s*<span>(?:\[\d+\]|\*+)</span>\s*(?:<span[^>]*>\s*</span>)?)\s*([^<].*?)</a>',
        fix_unclosed_footnote_link,
        html_body,
        flags=re.S
    )

    fixes += (n1 + n2 + n3 + n3b + n4)
    return html_body, fixes


# ==============================================================================
# 2. Broken Paragraph Merging (OCR / PDF line wraps)
# ==============================================================================

def is_heading_like(txt: str) -> bool:
    """Check if text is likely a chapter title, number, or separator."""
    t = txt.strip()
    if not t:
        return True
    if len(t) <= 4 and (t.isdigit() or re.match(r'^[IVXLCDM]+$', t, re.I)):
        return True
    if re.match(r'^(?:Chapter|Rozdział|Kapitel|Chapitre|Prologue|Prolog|Epilogue|Epilog|Part|Część|Book|Księga)\b', t, re.I):
        return True
    # Standalone short uppercase text
    letters = [c for c in t if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(t) < 70:
        return True
    return False


def should_merge_paragraphs(p1_html: str, p2_html: str) -> tuple[bool, bool]:
    """
    Determine whether two consecutive <p> tags belong to a single sentence
    broken across pages or PDF hard line breaks.
    """
    styled_only_re = r'^\s*(?:<span\b[^>]*>\s*)*<(?:b|i|strong|em)\b[^>]*>.*?</(?:b|i|strong|em)>\s*(?:</span>\s*)*$'
    if re.match(styled_only_re, p1_html, re.S) or re.match(styled_only_re, p2_html, re.S):
        return False, False

    t1 = strip_tags(p1_html).strip()
    t2 = strip_tags(p2_html).strip()
    if not t1 or not t2:
        return False, False
    if is_heading_like(t1) or is_heading_like(t2):
        return False, False

    # Second paragraph must start with a lowercase letter (not uppercase or dialogue dash)
    first_char2 = t2[0]
    if not first_char2.islower():
        return False, False

    # Case 1: First paragraph ends with a hyphen (broken word)
    if re.search(r'[A-Za-z\u00C0-\u024F]-$', t1):
        return True, True

    # Case 2: First paragraph ends without sentence termination (letter, comma, colon, semicolon, ellipsis)
    if re.search(r'(?:[A-Za-z0-9\u00C0-\u024F,;:—–\-”"»)]|\.\.\.|…|\b\d+\.)$', t1):
        return True, False

    return False, False


def is_empty_spacer_p(p_inner: str) -> bool:
    """Return True if paragraph content is just whitespace or &nbsp;."""
    return not strip_tags(p_inner).replace('\xa0', '').strip()


def merge_broken_paragraphs_in_html(html_body: str) -> tuple[str, int]:
    """
    Merge sentences broken across <p> elements, bridging over empty spacer paragraphs.
    """
    html_body = re.sub(r'<p\b[^>]*class=["\']softbreak["\'][^>]*>\s*(?:&nbsp;|\xa0)?\s*</p>\s*', '', html_body, flags=re.I)

    p_tag_re = re.compile(r'(<p\b(?![^>]*/>)[^>]*>)(.*?)(</p>)', re.S | re.I)

    tokens = []
    last_end = 0
    for m in p_tag_re.finditer(html_body):
        if m.start() > last_end:
            tokens.append(('RAW', html_body[last_end:m.start()]))
        tokens.append(('P', m.group(1), m.group(2), m.group(3)))
        last_end = m.end()
    if last_end < len(html_body):
        tokens.append(('RAW', html_body[last_end:]))

    merged_count = 0
    i = 0
    while i < len(tokens):
        if tokens[i][0] != 'P':
            i += 1
            continue

        j = i + 1
        can_bridge = True
        while j < len(tokens):
            tk = tokens[j]
            if tk[0] == 'RAW':
                if tk[1].strip():
                    can_bridge = False
                    break
                j += 1
            elif tk[0] == 'P':
                if is_empty_spacer_p(tk[2]):
                    j += 1
                else:
                    break

        if can_bridge and j < len(tokens) and tokens[j][0] == 'P':
            _, open1, inner1, close1 = tokens[i]
            _, open2, inner2, close2 = tokens[j]
            do_merge, is_hyphen = should_merge_paragraphs(inner1, inner2)
            if do_merge:
                i1 = inner1.rstrip()
                i2 = inner2.lstrip()
                if is_hyphen and i1.endswith('-'):
                    new_inner = f"{i1[:-1]}{i2}"
                else:
                    new_inner = f"{i1} {i2}"
                tokens[i] = ('P', open1, new_inner, close1)
                del tokens[i + 1 : j + 1]
                merged_count += 1
                continue

        i += 1

    out_parts = [tk[1] if tk[0] == 'RAW' else f"{tk[1]}{tk[2]}{tk[3]}" for tk in tokens]
    return ''.join(out_parts), merged_count


# ==============================================================================
# 3. HTML Document & Head Cleanup
# ==============================================================================

def clean_head_section(raw_html: str, book_title: str, book_author: str) -> tuple[str, int]:
    """
    Repair HTML <head>:
    - Strips illegal <p> tags and MS Office conditional comments from <head>.
    - Removes dead Word file links.
    - Replaces corrupted title/author metadata.
    """
    fixes = 0
    m_head = re.search(r'(<head\b[^>]*>)(.*?)(</head>)', raw_html, re.S | re.I)
    if not m_head:
        return raw_html, 0

    head_open, head_inner, head_close = m_head.groups()
    orig_head = head_inner

    head_inner, n = re.subn(r'<p\b[^>]*>.*?</p>\s*', '', head_inner, flags=re.S | re.I)
    fixes += n

    head_inner, n = re.subn(r'<!--\[if\b.*?<!\[endif\]-->\s*', '', head_inner, flags=re.S | re.I)
    fixes += n

    head_inner, n = re.subn(
        r'<link\b[^>]*href=["\'](?:filelist\.xml|themedata\.thmx|colorschememapping\.xml)["\'][^>]*/>\s*',
        '',
        head_inner,
        flags=re.I,
    )
    fixes += n

    safe_title = escape(book_title or "Book")
    head_inner, n = re.subn(
        r'<title>\s*(?:unamed|index|\ufffd+)\s*</title>',
        f'<title>{safe_title}</title>',
        head_inner,
        flags=re.I,
    )
    fixes += n

    safe_author = escape(book_author or "")
    head_inner, n = re.subn(
        r'(<meta\b[^>]*name=["\']author["\'][^>]*content=["\'])\ufffd+(["\'][^>]*/>)',
        rf'\g<1>{safe_author}\2',
        head_inner,
        flags=re.I,
    )
    fixes += n

    if head_inner != orig_head:
        raw_html = raw_html[:m_head.start()] + head_open + head_inner + head_close + raw_html[m_head.end():]

    return raw_html, fixes


def normalize_headings_and_structure(spine_docs: list[dict], book_title: str) -> int:
    """
    Normalize chapter headings across spine documents:
    - Moves trailing orphaned chapter numbers/labels at the very end of file N to the top of file N+1.
    - Joins two-part headings (e.g. <h2>Chapter 1</h2> + <p><b>The Beginning</b></p> -> <h2>Chapter 1 — The Beginning</h2>).
    """
    fixes = 0

    # Moving trailing chapter labels ("Chapter 1", "Prolog", "5") to the next document
    trailing_re = re.compile(
        r'(?:\s*<p\b[^>]*>\s*(?:&nbsp;|\xa0)?\s*</p>)*\s*'
        r'<p\b[^>]*>\s*(?:<b\b[^>]*>)?\s*(Prologue|Prolog|Epilogue|Epilog|Chapter\s+\d+|Rozdział\s+\d+|\d{1,2})\s*(?:</b>)?\s*</p>\s*$',
        re.S | re.I
    )
    leading_h2_re = re.compile(
        r'^\s*<h2(\b[^>]*)>\s*(?:<b\b[^>]*>)?\s*(.*?)\s*(?:</b>)?\s*</h2>',
        re.S | re.I
    )

    for i in range(len(spine_docs) - 1):
        body_curr = spine_docs[i]['body']
        body_next = spine_docs[i + 1]['body']
        m_trail = trailing_re.search(body_curr)
        m_lead = leading_h2_re.search(body_next)
        if m_trail and m_lead:
            chap_label = m_trail.group(1).strip()
            h2_attrs = m_lead.group(1)
            h2_title = strip_tags(m_lead.group(2)).strip()
            if not h2_title.startswith(chap_label):
                sep = ". " if chap_label.isdigit() else " — "
                new_h2 = f'<h2{h2_attrs}>{chap_label}{sep}{h2_title}</h2>'
                spine_docs[i]['body'] = body_curr[:m_trail.start()].rstrip() + '\n'
                spine_docs[i + 1]['body'] = new_h2 + body_next[m_lead.end():]
                fixes += 1

    # Join <h2>Chapter X</h2> + <p><b>Title</b></p> in same document
    combined_num_title_re = re.compile(
        r'<h2(\b[^>]*)>\s*(?:<b\b[^>]*>)?\s*(\d{1,2}|Chapter\s+\d+|Rozdział\s+\d+)\s*(?:</b>)?\s*</h2>\s*'
        r'<p\b[^>]*>\s*<b\b[^>]*>\s*([^<]{2,70}?)\s*</b>\s*</p>',
        re.S | re.I
    )
    for doc in spine_docs:
        new_body, n = combined_num_title_re.subn(
            lambda m: f'<h2{m.group(1)}>{m.group(2)} — {m.group(3).strip()}</h2>',
            doc['body']
        )
        if n:
            doc['body'] = new_body
            fixes += n

    return fixes


def rebuild_toc_and_fix_links(
    spine_docs: list[dict],
    book_title: str,
    ncx_bytes: bytes | None,
) -> tuple[bytes | None, int]:
    """
    Collect headings (<h1>, <h2>), assign anchor IDs if missing,
    and generate a clean, valid toc.ncx navigation file.
    """
    toc_entries = []
    heading_re = re.compile(r'<(h[12])(\b[^>]*)>(.*?)</\1>', re.S | re.I)
    ignore_titles = {'table of contents', 'spis treści', 'contents', book_title.lower().strip()}

    auto_id_counter = 1
    for doc in spine_docs:
        href = doc['href']
        body = doc['body']

        def process_heading(m):
            nonlocal auto_id_counter
            tag, attrs, inner = m.groups()
            if 'sigilNotInTOC' in attrs:
                return m.group(0)
            title_txt = re.sub(r'\s+', ' ', strip_tags(inner)).strip()
            if not title_txt or title_txt.lower() in ignore_titles:
                return m.group(0)

            m_id = re.search(r'\bid=["\']([^"\']+)["\']', attrs)
            if m_id:
                hid = m_id.group(1)
            else:
                hid = f"heading_toc_{auto_id_counter}"
                auto_id_counter += 1
                attrs = f'{attrs} id="{hid}"'

            toc_entries.append((title_txt, f"{href}#{hid}"))
            return f"<{tag}{attrs}>{inner}</{tag}>"

        doc['body'] = heading_re.sub(process_heading, body)

    if not ncx_bytes or not toc_entries:
        return ncx_bytes, len(toc_entries)

    uid = str(uuid.uuid4())
    m_uid = re.search(r'<meta\b[^>]*name=["\']dtb:uid["\'][^>]*content=["\']([^"\']+)["\']', ncx_bytes.decode('utf-8', errors='replace'))
    if m_uid:
        uid = m_uid.group(1)

    navpoints_xml = []
    for idx, (lbl, src) in enumerate(toc_entries, start=1):
        navpoints_xml.append(
            f'    <navPoint id="navPoint-{idx}" playOrder="{idx}">\n'
            f'      <navLabel>\n'
            f'        <text>{escape(lbl)}</text>\n'
            f'      </navLabel>\n'
            f'      <content src="{escape(src)}"/>\n'
            f'    </navPoint>'
        )

    new_ncx = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        '  <head>\n'
        f'    <meta content="{escape(uid)}" name="dtb:uid"/>\n'
        '    <meta content="2" name="dtb:depth"/>\n'
        '    <meta content="0" name="dtb:totalPageCount"/>\n'
        '    <meta content="0" name="dtb:maxPageNumber"/>\n'
        '  </head>\n'
        '  <docTitle>\n'
        f'    <text>{escape(book_title)}</text>\n'
        '  </docTitle>\n'
        '  <navMap>\n'
        + "\n".join(navpoints_xml)
        + "\n  </navMap>\n</ncx>\n"
    )
    return new_ncx.encode('utf-8'), len(toc_entries)


# ==============================================================================
# 4. Standalone PalmDOC / MOBI Parser
# ==============================================================================

def decompress_palmdoc(data: bytes) -> bytes:
    """Decompress PalmDOC LZ77 byte stream."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        i += 1
        if c == 0x00:
            out.append(0x00)
        elif 0x01 <= c <= 0x08:
            out.extend(data[i : i + c])
            i += c
        elif 0x09 <= c <= 0x7F:
            out.append(c)
        elif 0x80 <= c <= 0xBF:
            if i >= n:
                break
            c2 = data[i]
            i += 1
            pair = ((c << 8) | c2) & 0x3FFF
            dist = pair >> 3
            length = (pair & 0x07) + 3
            if 0 < dist <= len(out):
                for _ in range(length):
                    out.append(out[-dist])
        else:
            out.append(0x20)
            out.append(c ^ 0x80)
    return bytes(out)


def parse_mobi_file(fpath: str) -> dict:
    """Extract HTML text, EXTH metadata, and embedded images from a MOBI/AZW file."""
    with open(fpath, 'rb') as f:
        raw = f.read()

    if len(raw) < 86:
        raise ValueError(f"File is too short to be a valid MOBI/AZW: {fpath}")

    num_records = struct.unpack('>H', raw[76:78])[0]
    offsets = [struct.unpack('>I', raw[78 + i * 8 : 82 + i * 8])[0] for i in range(num_records)]
    offsets.append(len(raw))

    rec0 = raw[offsets[0] : offsets[1]]
    compression, _, text_len, rec_count, rec_size, enc_type, _ = struct.unpack('>HHIHHHH', rec0[0:16])
    if enc_type != 0:
        raise ValueError(f"File has DRM encryption (enc_type={enc_type}): {fpath}")

    encoding = 'cp1252'
    first_image_idx = 0
    title = os.path.splitext(os.path.basename(fpath))[0]
    author = "Unknown"
    language = "en"
    publisher = ""
    description = ""

    if len(rec0) >= 32 and rec0[16:20] == b'MOBI':
        hdr_len = struct.unpack('>I', rec0[20:24])[0]
        codepage = struct.unpack('>I', rec0[28:32])[0]
        if codepage == 65001:
            encoding = 'utf-8'
        elif codepage == 1250:
            encoding = 'cp1250'

        if len(rec0) >= 92:
            fn_off, fn_len = struct.unpack('>II', rec0[84:92])
            if fn_off + fn_len <= len(rec0) and fn_len > 0:
                title = rec0[fn_off : fn_off + fn_len].decode(encoding, errors='replace').strip()

        if len(rec0) >= 0x70:
            first_image_idx = struct.unpack('>I', rec0[0x6C:0x70])[0]

        if len(rec0) >= 0x84:
            exth_flags = struct.unpack('>I', rec0[0x80:0x84])[0]
            exth_off = 16 + hdr_len
            if (exth_flags & 0x40) and len(rec0) >= exth_off + 12 and rec0[exth_off : exth_off + 4] == b'EXTH':
                exth_count = struct.unpack('>I', rec0[exth_off + 8 : exth_off + 12])[0]
                pos = exth_off + 12
                for _ in range(exth_count):
                    if pos + 8 > len(rec0):
                        break
                    rtype, rlen = struct.unpack('>II', rec0[pos : pos + 8])
                    if rlen < 8 or pos + rlen > len(rec0):
                        break
                    rdata = rec0[pos + 8 : pos + rlen]
                    pos += rlen
                    val = rdata.decode(encoding, errors='replace').strip()
                    if rtype == 100 and val:
                        author = val
                    elif rtype == 503 and val:
                        title = val
                    elif rtype == 101 and val:
                        publisher = val
                    elif rtype == 103 and val:
                        description = val
                    elif rtype == 524 and val:
                        language = val

    chunks = []
    extra_flags = 0
    if len(rec0) >= 0xF4 and rec0[16:20] == b'MOBI':
        hdr_len = struct.unpack('>I', rec0[20:24])[0]
        if hdr_len >= 0xE4:
            extra_flags = struct.unpack('>H', rec0[0xF2:0xF4])[0]

    for r in range(1, 1 + rec_count):
        if r >= len(offsets) - 1:
            break
        chunk = raw[offsets[r] : offsets[r + 1]]
        if extra_flags:
            for bit in range(15, 0, -1):
                if extra_flags & (1 << bit):
                    val = 0
                    shift = 0
                    pos = len(chunk) - 1
                    while pos >= 0:
                        b = chunk[pos]
                        val |= (b & 0x7F) << shift
                        pos -= 1
                        shift += 7
                        if b & 0x80:
                            break
                    if 0 < val <= len(chunk):
                        chunk = chunk[: len(chunk) - val]
            if extra_flags & 1 and chunk:
                overlap = (chunk[-1] & 0x03) + 1
                if overlap <= len(chunk):
                    chunk = chunk[:-overlap]

        if compression == 1:
            chunks.append(chunk)
        elif compression == 2:
            chunks.append(decompress_palmdoc(chunk))
        else:
            raise ValueError(f"Unsupported MOBI compression ({compression}): {fpath}")

    html_str = b''.join(chunks).decode(encoding, errors='replace')

    images = {}
    if 0 < first_image_idx < num_records:
        img_seq = 1
        for r in range(first_image_idx, num_records):
            idata = raw[offsets[r] : offsets[r + 1]]
            ext, mime = None, None
            if idata.startswith(b'\xff\xd8\xff'):
                ext, mime = 'jpg', 'image/jpeg'
            elif idata.startswith(b'\x89PNG'):
                ext, mime = 'png', 'image/png'
            elif idata.startswith(b'GIF8'):
                ext, mime = 'gif', 'image/gif'
            if ext:
                images[img_seq] = (f"images/img_{img_seq:05d}.{ext}", mime, idata)
                img_seq += 1

    return {
        'html': html_str,
        'title': title,
        'author': author,
        'language': language,
        'publisher': publisher,
        'description': description,
        'images': images,
    }


def convert_mobi_to_epub(mobi_path: str, epub_out_path: str) -> None:
    """Convert a MOBI/AZW file to a structured EPUB archive."""
    data = parse_mobi_file(mobi_path)
    html = data['html']
    title = data['title']
    author = data['author']
    language = data['language']
    images = data['images']

    m_body = re.search(r'<body\b[^>]*>(.*)</body>', html, re.S | re.I)
    body = m_body.group(1) if m_body else html

    def repl_img(m):
        idx = int(m.group(1))
        return f'<img src="{images[idx][0]}" alt="image"/>' if idx in images else ''

    body = re.sub(r'<img\b[^>]*recindex=["\']?(\d+)["\']?[^>]*/?>', repl_img, body, flags=re.I)

    # Promote standalone bold/centered chapter titles to <h2>
    def promote_heading(m):
        full_p, inner = m.group(0), m.group(1)
        txt = strip_tags(inner).strip()
        if not txt or len(txt) > 75:
            return full_p
        if re.match(r'^(?:Chapter\s+\d+|Rozdział\s+\d+|Prologue|Prolog|Epilogue|Epilog)\b', txt, re.I):
            return f'<mbp:pagebreak/><h2>{escape(txt)}</h2>'
        return full_p

    body = re.sub(r'<p\b[^>]*>(.*?)</p>', promote_heading, body, flags=re.S | re.I)

    # Clean MOBI tags
    body = re.sub(r'<p\b[^>]*>', '<p class="calibre1">', body, flags=re.I)
    body = re.sub(r'</?(?:font|u|div)\b[^>]*>', '', body, flags=re.I)
    body = re.sub(r'<a\b[^>]*filepos=["\']?\d+["\']?[^>]*>(.*?)</a>', r'\1', body, flags=re.S | re.I)

    raw_parts = re.split(r'<mbp:pagebreak\s*/?>\s*(?:</mbp:pagebreak>)?', body, flags=re.I)
    parts = [p.strip() for p in raw_parts if strip_tags(p).strip() or '<img' in p]
    if not parts:
        parts = [body]

    book_uuid = str(uuid.uuid4())
    stylesheet = (
        "body { font-family: serif; line-height: 1.4; margin: 5pt; }\n"
        "p.calibre1 { margin-top: 0; margin-bottom: 0.3em; text-indent: 1.2em; text-align: justify; }\n"
        "h1, h2, h3 { text-align: center; text-indent: 0; margin-top: 1em; margin-bottom: 0.8em; }\n"
    )

    manifest_items = [
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '    <item id="css" href="stylesheet.css" media-type="text/css"/>',
    ]
    spine_items = []
    xhtml_files = {}

    for img_idx, (img_href, img_mime, _) in images.items():
        manifest_items.append(f'    <item id="img_{img_idx}" href="{img_href}" media-type="{img_mime}"/>')

    for idx, part in enumerate(parts):
        fname = f"index_split_{idx:03d}.xhtml"
        item_id = f"split_{idx:03d}"
        manifest_items.append(f'    <item id="{item_id}" href="{fname}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'    <itemref idref="{item_id}"/>')
        xhtml_files[fname] = (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml">\n'
            '  <head>\n'
            f'    <title>{escape(title)}</title>\n'
            f'    <meta name="author" content="{escape(author)}"/>\n'
            '    <link href="stylesheet.css" rel="stylesheet" type="text/css"/>\n'
            '  </head>\n'
            '  <body class="calibre">\n'
            f'{part}\n'
            '  </body>\n'
            '</html>\n'
        ).encode('utf-8')

    content_opf = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">\n'
        f'    <dc:title>{escape(title)}</dc:title>\n'
        f'    <dc:creator opf:role="aut">{escape(author)}</dc:creator>\n'
        f'    <dc:language>{escape(language)}</dc:language>\n'
        f'    <dc:identifier id="uuid_id" opf:scheme="uuid">{book_uuid}</dc:identifier>\n'
        '  </metadata>\n'
        '  <manifest>\n'
        + "\n".join(manifest_items)
        + '\n  </manifest>\n'
        '  <spine toc="ncx">\n'
        + "\n".join(spine_items)
        + '\n  </spine>\n'
        '</package>\n'
    ).encode('utf-8')

    container_xml = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles>\n'
        '    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>\n'
        '  </rootfiles>\n'
        '</container>\n'
    ).encode('utf-8')

    initial_ncx = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        '  <head>\n'
        f'    <meta content="{book_uuid}" name="dtb:uid"/>\n'
        '  </head>\n'
        f'  <docTitle><text>{escape(title)}</text></docTitle>\n'
        '  <navMap/>\n'
        '</ncx>\n'
    ).encode('utf-8')

    with zipfile.ZipFile(epub_out_path, 'w') as zout:
        zout.writestr('mimetype', b'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        zout.writestr('META-INF/container.xml', container_xml, compress_type=zipfile.ZIP_DEFLATED)
        zout.writestr('content.opf', content_opf, compress_type=zipfile.ZIP_DEFLATED)
        zout.writestr('toc.ncx', initial_ncx, compress_type=zipfile.ZIP_DEFLATED)
        zout.writestr('stylesheet.css', stylesheet.encode('utf-8'), compress_type=zipfile.ZIP_DEFLATED)
        for _, (img_href, _, img_bytes) in images.items():
            zout.writestr(img_href, img_bytes, compress_type=zipfile.ZIP_DEFLATED)
        for fname, fbytes in xhtml_files.items():
            zout.writestr(fname, fbytes, compress_type=zipfile.ZIP_DEFLATED)


# ==============================================================================
# 5. Core EPUB Repair Engine
# ==============================================================================

def repair_epub(input_path: str, output_path: str) -> dict:
    """Repair an EPUB archive and return summary metrics."""
    stats = {
        'head_fixes': 0,
        'merged_paragraphs': 0,
        'inline_spaces_cleaned': 0,
        'dialogue_punct_fixed': 0,
        'cruft_removed': 0,
        'structural_fixes': 0,
        'toc_entries': 0,
    }

    with zipfile.ZipFile(input_path, 'r') as zin:
        file_map = {name: zin.read(name) for name in zin.namelist()}

    container_xml = ET.fromstring(file_map['META-INF/container.xml'])
    ns = {'c': 'urn:oasis:names:tc:opendocument:xmlns:container'}
    opf_path = container_xml.find('.//c:rootfile', ns).attrib['full-path']
    opf_dir = os.path.dirname(opf_path)

    opf_root = ET.fromstring(file_map[opf_path])
    book_title = "Book"
    book_author = ""
    for elem in opf_root.iter():
        tag = elem.tag.split('}')[-1]
        if tag == 'title' and elem.text:
            book_title = elem.text.strip()
        elif tag == 'creator' and elem.text:
            book_author = elem.text.strip()

    manifest = {}
    ncx_zip_path = None
    for item in opf_root.findall('.//{*}manifest/{*}item'):
        mid = item.attrib['id']
        href = item.attrib['href']
        mtype = item.attrib.get('media-type', '')
        manifest[mid] = href
        if 'ncx' in mtype or href.endswith('.ncx'):
            ncx_zip_path = os.path.normpath(os.path.join(opf_dir, href)).replace('\\', '/') if opf_dir else href

    spine_ids = [itemref.attrib['idref'] for itemref in opf_root.findall('.//{*}spine/{*}itemref')]
    spine_docs = []

    for idref in spine_ids:
        href = manifest.get(idref)
        if not href:
            continue
        zip_path = os.path.normpath(os.path.join(opf_dir, href)).replace('\\', '/') if opf_dir else href
        if zip_path not in file_map:
            continue

        raw_html = file_map[zip_path].decode('utf-8', errors='replace')
        raw_html, n_head = clean_head_section(raw_html, book_title, book_author)
        stats['head_fixes'] += n_head

        m_body = re.search(r'(<body\b[^>]*>)(.*?)(</body>)', raw_html, re.S | re.I)
        if not m_body:
            continue

        spine_docs.append({
            'idref': idref,
            'href': href,
            'zip_path': zip_path,
            'prefix': raw_html[:m_body.end(1)],
            'body': m_body.group(2),
            'suffix': raw_html[m_body.start(3):],
        })

    stats['structural_fixes'] += normalize_headings_and_structure(spine_docs, book_title)

    for doc in spine_docs:
        body = doc['body']

        body, n_cr = clean_generator_cruft(body)
        stats['cruft_removed'] += n_cr

        body, n_sp = clean_inline_spaces(body)
        stats['inline_spaces_cleaned'] += n_sp

        body, n_dp = fix_dialogue_and_punctuation_spacing(body)
        stats['dialogue_punct_fixed'] += n_dp

        body, n_mp = merge_broken_paragraphs_in_html(body)
        stats['merged_paragraphs'] += n_mp

        doc['body'] = body

    ncx_bytes = file_map.get(ncx_zip_path) if ncx_zip_path else None
    new_ncx_bytes, n_toc = rebuild_toc_and_fix_links(spine_docs, book_title, ncx_bytes)
    if ncx_zip_path and new_ncx_bytes:
        file_map[ncx_zip_path] = new_ncx_bytes
        stats['toc_entries'] = n_toc

    for doc in spine_docs:
        full_html = doc['prefix'] + doc['body'] + doc['suffix']
        file_map[doc['zip_path']] = full_html.encode('utf-8')

    tmp_out = output_path + ".tmp"
    with zipfile.ZipFile(tmp_out, 'w') as zout:
        if 'mimetype' in file_map:
            zout.writestr('mimetype', file_map['mimetype'], compress_type=zipfile.ZIP_STORED)
        for name, data in file_map.items():
            if name == 'mimetype':
                continue
            zout.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)

    shutil.move(tmp_out, output_path)
    return stats


# ==============================================================================
# 6. CLI Entrypoint
# ==============================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Universal e-book cleaner for formatting, punctuation, broken paragraphs, and TOC in EPUB/MOBI."
    )
    parser.add_argument("inputs", nargs="*", help="File or directory path(s) to process.")
    parser.add_argument("--all", action="store_true", help="Process all EPUB/MOBI files in the current folder.")
    parser.add_argument("--in-place", action="store_true", help="Overwrite original files (creates backup/ subfolder).")
    parser.add_argument("--output-dir", default="repaired", help="Output directory for repaired files (default: 'repaired').")
    parser.add_argument("--json", action="store_true", help="Print results as structured JSON.")

    args = parser.parse_args(argv)

    def collect_books(dpath: str, recursive: bool = True) -> list[str]:
        found = []
        walker = os.walk(dpath) if recursive else [(dpath, [], os.listdir(dpath))]
        for root_d, _, files_d in walker:
            if os.path.basename(root_d).lower() in ("repaired", "backup", "__pycache__"):
                continue
            epubs_in_dir = {os.path.splitext(fn)[0].lower() for fn in files_d if fn.lower().endswith('.epub')}
            for fn in sorted(files_d):
                low = fn.lower()
                if low.endswith('.epub') and not low.endswith('_fixed.epub'):
                    found.append(os.path.join(root_d, fn))
                elif low.endswith(('.mobi', '.azw')):
                    base = os.path.splitext(fn)[0].lower()
                    if base not in epubs_in_dir:
                        found.append(os.path.join(root_d, fn))
        return found

    targets = []
    if args.all or not args.inputs:
        targets.extend(collect_books(".", recursive=False))
    else:
        for p in args.inputs:
            if os.path.isdir(p):
                targets.extend(collect_books(p, recursive=True))
            elif os.path.isfile(p):
                targets.append(p)
            else:
                if not args.json:
                    print(f"File not found: {p}", file=sys.stderr)

    if not targets:
        if args.json:
            print(json.dumps({"processed_count": 0, "results": []}))
        else:
            print("No .epub or .mobi files found to process.")
        return 0

    results = []
    for fpath in targets:
        fname = os.path.basename(fpath)
        fdir = os.path.dirname(os.path.abspath(fpath))
        base_name, ext = os.path.splitext(fname)
        is_mobi = ext.lower() in ('.mobi', '.azw')
        out_fname = f"{base_name}.epub" if is_mobi else fname

        if args.in_place:
            if not is_mobi:
                backup_dir = os.path.join(fdir, "backup")
                os.makedirs(backup_dir, exist_ok=True)
                shutil.copy2(fpath, os.path.join(backup_dir, fname))
            out_path = os.path.join(fdir, out_fname)
        else:
            out_dir = args.output_dir if os.path.isabs(args.output_dir) else os.path.join(fdir, args.output_dir)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, out_fname)

        tmp_epub = None
        try:
            if is_mobi:
                with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tf:
                    tmp_epub = tf.name
                convert_mobi_to_epub(fpath, tmp_epub)
                stats = repair_epub(tmp_epub, out_path)
            else:
                stats = repair_epub(fpath, out_path)

            res = {
                "file": fname,
                "input_path": fpath,
                "output_path": out_path,
                "is_mobi_source": is_mobi,
                "stats": stats,
            }
            results.append(res)
            if not args.json:
                print(f"Processed: {fname} -> {out_path}")
                print(
                    f"  Merged paragraphs: {stats['merged_paragraphs']} | "
                    f"Collapsed spaces: {stats['inline_spaces_cleaned']} | "
                    f"Punctuation fixes: {stats['dialogue_punct_fixed']} | "
                    f"Cruft removed: {stats['cruft_removed']} | "
                    f"TOC entries: {stats['toc_entries']}"
                )
        finally:
            if tmp_epub and os.path.exists(tmp_epub):
                os.remove(tmp_epub)

    if args.json:
        print(json.dumps({"processed_count": len(results), "results": results}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
