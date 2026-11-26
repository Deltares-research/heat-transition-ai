"""PDF extraction, heading-aware chunking and Dutch-to-English translation.

Ported out of the old pipeline/4_chunk.py and pipeline/3_translate_mds.py so
the logic is importable rather than locked inside scripts whose filenames
start with a digit.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parents[2]
load_dotenv(ROOT / ".env")

__all__ = ["Chunk", "chunk_markdown", "pdf_to_markdown", "translate_markdown"]

# ── chunking ──────────────────────────────────────────────────

MIN_CHARS = 200     # drop fragments this short; usually empty sections
MAX_CHARS = 3000    # split longer sections at paragraph boundaries
OVERLAP = 200       # carry this much of the previous chunk for context

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    chunk_index: int
    heading_path: str
    text: str
    char_start: int
    char_end: int
    n_chars: int

    def as_dict(self) -> dict:
        return asdict(self)


def pdf_to_markdown(data: bytes) -> str:
    """Extract markdown from PDF bytes."""
    import pymupdf
    import pymupdf4llm

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return pymupdf4llm.to_markdown(doc, show_progress=False)


def _split_by_headings(text: str) -> list[tuple[str, str, int]]:
    """Split on markdown headings into (heading_path, section, char_offset)."""
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("", text, 0)]

    sections: list[tuple[str, str, int]] = []
    stack: list[tuple[int, str]] = []

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()

        stack = [(lvl, t) for lvl, t in stack if lvl < level]
        stack.append((level, title))
        path = " > ".join(t for _, t in stack)

        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((path, text[start:end], start))

    if matches[0].start() > 0:  # front matter before the first heading
        sections.insert(0, ("", text[: matches[0].start()], 0))

    return sections


def _split_long(
    path: str, text: str, offset: int, max_chars: int, overlap: int
) -> list[tuple[str, str, int]]:
    """Break an oversized section on blank lines, carrying an overlap."""
    if len(text) <= max_chars:
        return [(path, text, offset)]

    paragraphs = re.split(r"\n\n+", text)
    chunks: list[tuple[str, str, int]] = []
    current: list[str] = []
    cursor = offset
    length = 0
    tail = ""

    for para in paragraphs:
        if length + len(para) > max_chars and current:
            body = "\n\n".join(current)
            chunks.append((path, tail + body, cursor - len(tail)))
            tail = body[-overlap:] if overlap else ""
            cursor = offset + text.index(para)
            current, length = [], 0
        current.append(para)
        length += len(para) + 2

    if current:
        body = "\n\n".join(current)
        chunks.append((path, tail + body, cursor - len(tail)))

    return chunks


def chunk_markdown(
    text: str,
    min_chars: int = MIN_CHARS,
    max_chars: int = MAX_CHARS,
    overlap: int = OVERLAP,
) -> list[Chunk]:
    """Split a markdown document into citable, semantically coherent chunks."""
    raw: list[tuple[str, str, int]] = []
    for path, section, offset in _split_by_headings(text):
        raw.extend(_split_long(path, section, offset, max_chars, overlap))

    chunks: list[Chunk] = []
    for path, body, start in raw:
        body = body.strip()
        if len(body) < min_chars:
            continue
        chunks.append(Chunk(
            chunk_index=len(chunks),
            heading_path=path,
            text=body,
            char_start=start,
            char_end=start + len(body),
            n_chars=len(body),
        ))
    return chunks


# ── translation ───────────────────────────────────────────────

TRANSLATE_MODEL = os.environ.get("MODEL", "gpt-5.6-sol")
TRANSLATE_API_KEY = os.environ.get("API_KEY")
TRANSLATE_API_BASE = os.environ.get("API_BASE")
TRANSLATE_CHUNK_CHARS = int(os.environ.get("TRANSLATE_CHUNK_CHARS", "12000"))
TRANSLATE_MAX_TOKENS = int(os.environ.get("TRANSLATE_MAX_TOKENS", "4000"))

TRANSLATE_SYSTEM = """
You are a professional translator specialising in Dutch municipal policy documents.
Translate the following Dutch markdown text to English.

Rules:
- Preserve ALL markdown formatting exactly: headers (##), tables, bullet lists, bold, italic.
- Translate every Dutch word, including headings and table headers.
- For Dutch policy terms with no standard English equivalent, translate them and add the
  Dutch original in parentheses on the FIRST occurrence only:
  e.g. "designation authority (aanwijsbevoegdheid)", "heat programme (warmteprogramma)",
       "exploration area (verkenningsgebied)", "no-regret measure (geen-spijtmaatregel)".
- Do NOT translate proper nouns: municipality names, street names, organisation names,
  document titles, URLs.
- Do NOT add explanations, summaries, or notes outside the translation.
- Output ONLY the translated markdown. No preamble, no fences.
""".strip()


def _split_for_translation(text: str, max_chars: int) -> list[str]:
    """Split on blank lines so no chunk breaks mid-paragraph or mid-table."""
    paragraphs = text.split("\n\n")
    parts: list[str] = []
    current: list[str] = []
    length = 0

    for para in paragraphs:
        if length + len(para) > max_chars and current:
            parts.append("\n\n".join(current))
            current, length = [], 0
        current.append(para)
        length += len(para) + 2

    if current:
        parts.append("\n\n".join(current))
    return parts


def translate_markdown(text: str, model: str | None = None) -> str:
    """Translate Dutch markdown to English, preserving structure."""
    import litellm

    litellm.drop_params = True
    litellm.suppress_debug_info = True

    pieces = _split_for_translation(text, TRANSLATE_CHUNK_CHARS)
    out: list[str] = []

    for piece in pieces:
        response = litellm.completion(
            model=model or TRANSLATE_MODEL,
            api_key=TRANSLATE_API_KEY,
            api_base=TRANSLATE_API_BASE,
            max_completion_tokens=TRANSLATE_MAX_TOKENS,
            messages=[
                {"role": "system", "content": TRANSLATE_SYSTEM},
                {"role": "user", "content": piece},
            ],
        )
        out.append((response.choices[0].message.content or "").strip())

    return "\n\n".join(out)
