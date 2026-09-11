"""
Chunk translated warmteprogramma markdown files for embedding.

Strategy: split on markdown headings so chunks are semantically coherent.
Each chunk carries its document id, gemeente, page range estimate, heading
path and character offsets so it can be cited back to the source.

Output: JSONL, one object per chunk, written to data/processed/chunks.jsonl.

Usage:
    python chunk_md.py                   # all files in md_en/
    python chunk_md.py --limit 5
    python chunk_md.py --file 1.md
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


MIN_CHARS   = 200     # drop chunks shorter than this (usually empty sections)
MAX_CHARS   = 3000    # split long sections at paragraph boundaries
OVERLAP     = 200     # carry this many chars from the end of the previous chunk

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    doc_id:       str
    chunk_index:  int
    heading_path: str          # e.g. "Participation > Residents"
    text:         str
    char_start:   int
    char_end:     int
    n_chars:      int


def heading_level(hashes: str) -> int:
    return len(hashes)


def split_by_headings(text: str) -> list[tuple[str, str, int]]:
    """
    Split on headings. Returns [(heading_path, section_text, char_offset), ...].
    Sections include the heading line itself.
    """
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("", text, 0)]

    sections = []
    heading_stack: list[tuple[int, str]] = []   # (level, title)

    for i, m in enumerate(matches):
        level = heading_level(m.group(1))
        title = m.group(2).strip()

        # trim the stack to the current level
        heading_stack = [(l, t) for l, t in heading_stack if l < level]
        heading_stack.append((level, title))
        path = " > ".join(t for _, t in heading_stack)

        start = m.start()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((path, text[start:end], start))

    # text before the first heading (title page, intro paragraph)
    first = matches[0].start()
    if first > 0:
        sections.insert(0, ("", text[:first], 0))

    return sections


def split_long_section(path: str, text: str, offset: int,
                        max_chars: int, overlap: int) -> list[tuple[str, str, int]]:
    """Split a section that exceeds max_chars on blank lines."""
    if len(text) <= max_chars:
        return [(path, text, offset)]

    paragraphs = re.split(r"\n\n+", text)
    chunks, current, cur_offset = [], [], offset
    length = 0
    tail   = ""

    for para in paragraphs:
        if length + len(para) > max_chars and current:
            body = "\n\n".join(current)
            chunks.append((path, tail + body, cur_offset - len(tail)))
            tail       = body[-overlap:] if overlap else ""
            cur_offset = offset + text.index(para)
            current, length = [], 0
        current.append(para)
        length += len(para) + 2

    if current:
        body = "\n\n".join(current)
        chunks.append((path, tail + body, cur_offset - len(tail)))

    return chunks


def chunk_document(doc_id: str, text: str) -> list[Chunk]:
    sections = split_by_headings(text)
    raw: list[tuple[str, str, int]] = []

    for path, section_text, char_offset in sections:
        raw.extend(split_long_section(path, section_text,
                                      char_offset, MAX_CHARS, OVERLAP))

    chunks = []
    for i, (path, body, start) in enumerate(raw):
        body = body.strip()
        if len(body) < MIN_CHARS:
            continue
        chunks.append(Chunk(
            doc_id       = doc_id,
            chunk_index  = i,
            heading_path = path,
            text         = body,
            char_start   = start,
            char_end     = start + len(body),
            n_chars      = len(body),
        ))

    # re-index after filtering
    for j, c in enumerate(chunks):
        c.chunk_index = j

    return chunks


def process_file(path: Path, out: list[dict]) -> int:
    doc_id = path.stem
    text   = path.read_text(encoding="utf-8")
    chunks = chunk_document(doc_id, text)
    out.extend(asdict(c) for c in chunks)
    return len(chunks)


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":

    corpus_path = Path(__file__).parents[1] / "data/corpus/mds_en"
    out_path = Path(__file__).parents[1] / "data/processed"
    out_path.mkdir(parents=True, exist_ok=True)
    out_path = out_path / "chunks.jsonl"

    files = list((corpus_path.glob("*.md")))

    records = []
    total = 0
    for f in files:
        try:
            n = process_file(f, records)
            total += n
            print(f"  {f.name}: {n} chunks")
        except Exception as e:
            print(f"  ERROR {f.name}: {e}", file=sys.stderr)

    write_jsonl(records, out_path)
    print(f"\nwrote {len(records):,} chunks total to {out_path}")
    print(f"avg chars/chunk: {sum(r['n_chars'] for r in records) // max(len(records), 1)}")

