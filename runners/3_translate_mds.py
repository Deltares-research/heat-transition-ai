from __future__ import annotations
import os
import sys
from pathlib import Path
import litellm
from dotenv import load_dotenv
from tqdm import tqdm


load_dotenv(Path(__file__).parents[1] / ".env")

MODEL = os.environ.get("MODEL", "gpt-5.6-sol")
API_KEY = os.environ.get("API_KEY")
API_BASE = os.environ.get("API_BASE")
CHUNK_CHARS = int(os.environ.get("TRANSLATE_CHUNK_CHARS", "12000"))
MAX_TOKENS = int(os.environ.get("TRANSLATE_MAX_TOKENS", "4000"))

litellm.drop_params = True


SYSTEM = """
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


def split_chunks(text: str, max_chars: int) -> list[str]:
    """
    Split on blank lines so chunks never break mid-paragraph or mid-table.
    Tries to keep chunks under max_chars; oversized single paragraphs pass through whole.
    """
    paragraphs = text.split("\n\n")
    chunks, current = [], []
    length = 0

    for para in paragraphs:
        if length + len(para) > max_chars and current:
            chunks.append("\n\n".join(current))
            current, length = [], 0
        current.append(para)
        length += len(para) + 2

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def translate_chunk(text: str) -> str:
    resp = litellm.completion(
        model=MODEL,
        api_key=API_KEY,
        api_base=API_BASE,
        max_completion_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text},
        ],
    )
    return resp.choices[0].message.content.strip()


def translate_file(src: Path, dst: Path) -> None:
    text = src.read_text(encoding="utf-8")
    chunks = split_chunks(text, CHUNK_CHARS)
    parts = [translate_chunk(c) for c in chunks]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n\n".join(parts), encoding="utf-8")


if __name__ == "__main__":

    corpus_path = Path(__file__).parents[1] / "data/corpus"

    nl_dir = corpus_path / "mds_nl"
    en_dir = corpus_path / "mds_en"
    en_dir.mkdir(parents=True, exist_ok=True)

    files = list(nl_dir.glob("*.md"))
    print(f"{len(files)} files to translate")

    for f in tqdm(files, desc="Translating MDs"):
        try:
            translate_file(f, en_dir/f.name)
        except Exception as e:
            print(f"\nERROR {f.name}: {e}", file=sys.stderr)

