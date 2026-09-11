from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

os.environ["LITELLM_LOG"] = "ERROR"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import litellm
import yaml
from dotenv import load_dotenv
from tqdm import tqdm

litellm.suppress_debug_info = True

load_dotenv(Path(__file__).parents[1] / ".env")

MODEL      = os.environ.get("MODEL", "azure_ai/gpt-5.6-sol")
API_KEY    = os.environ.get("API_KEY")
API_BASE   = os.environ.get("API_BASE")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1200"))

litellm.drop_params = True

SYSTEM = """
You are an analyst reading a passage from a Dutch municipal heat transition
programme (warmteprogramma).

Rules:
- Answer ONLY from the passage provided. Do not use outside knowledge.
- For each numbered question, reply on a new line starting with the number.
- If the passage does not address a question, reply with exactly: not addressed
- Write in English. Dutch terms inside quotes are fine.
- One or two sentences per answer maximum.

After the numbered answers, add one final line:
AREAS: <comma-separated list of neighbourhood, district or area names mentioned,
        each followed by its type in parentheses: (buurt), (wijk) or (gebied)>
If no areas are mentioned, write: AREAS: none
""".strip()


def load_questions(tbox_path: Path) -> list[tuple[str, str]]:
    """(concept_id, question) per top-level concept."""
    tb = yaml.safe_load(tbox_path.read_text(encoding="utf-8"))
    concepts = tb["concepts"]
    all_subtypes = {s for c in concepts for s in c.get("subtypes", [])}
    return [
        (c["id"], f"What does this passage say about {c['label'].lower()}?")
        for c in concepts if c["id"] not in all_subtypes
    ]


def load_chunks(path: Path) -> list[dict]:
    chunks = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"loaded {len(chunks):,} chunks", file=sys.stderr)
    return chunks


def parse_areas(raw: str) -> list[dict]:
    """Parse 'AREAS: Binnenstad (wijk), Noordereiland (buurt)' into dicts."""
    m = re.search(r"AREAS:\s*(.+)$", raw, re.MULTILINE)
    if not m:
        return []
    raw_areas = m.group(1).strip()
    if raw_areas.lower() == "none":
        return []
    areas = []
    for part in raw_areas.split(","):
        part = part.strip()
        tm = re.search(r"\((buurt|wijk|gebied)\)", part, re.IGNORECASE)
        area_type = tm.group(1).lower() if tm else "gebied"
        name = re.sub(r"\(.*?\)", "", part).strip()
        if name:
            areas.append({"name": name, "type": area_type})
    return areas


def ask_passage(passage: str,
                questions: list[tuple[str, str]]) -> tuple[list[dict], list[dict]]:
    """One LLM call: all concept questions + area extraction."""
    q_block = "\n".join(
        f"{i+1}. [{cid}] {q}" for i, (cid, q) in enumerate(questions)
    )
    resp = litellm.completion(
        model=MODEL,
        api_key=API_KEY,
        api_base=API_BASE,
        max_completion_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content":
             f"Passage:\n{passage}\n\n"
             f"Answer each question. If the passage does not address it, "
             f"reply with exactly: not addressed\n\n{q_block}"},
        ],
    )
    raw = resp.choices[0].message.content.strip()

    areas = parse_areas(raw)

    results = []
    for i, (cid, q) in enumerate(questions):
        m = re.search(
            rf"(?:^|\n)\s*{i+1}[.)]\s*(.+?)(?=\n\s*{i+2}[.)]|\nAREAS:|\Z)",
            raw, re.DOTALL
        )
        answer = m.group(1).strip() if m else ""
        if not answer or answer.lower().startswith("not addressed"):
            continue
        results.append({"concept_id": cid, "question": q, "answer": answer})

    return results, areas


if __name__ == "__main__":

    chunk_path = Path(__file__).parents[1] / "data/processed/chunks_embedded.jsonl"
    tbox_path  = Path(__file__).parents[1] / "kg/tbox_concepts.yaml"
    out_path   = Path(__file__).parents[1] / "data/processed/chunk_answers.jsonl"

    chunks    = load_chunks(chunk_path)
    questions = load_questions(tbox_path)

    print(f"{len(chunks)} chunks x {len(questions)} questions\n", file=sys.stderr)

    with out_path.open("w", encoding="utf-8") as fh:
        for chunk in tqdm(chunks, desc="Answering chunks"):
            try:
                hits, areas = ask_passage(chunk["text"], questions)
            except Exception as e:
                print(f"\nERROR {chunk['doc_id']}:{chunk['chunk_index']}: {e}",
                      file=sys.stderr)
                continue

            for hit in hits:
                fh.write(json.dumps({
                    "doc_id":      chunk["doc_id"],
                    "chunk_index": chunk["chunk_index"],
                    "section":     chunk.get("heading_path", "?"),
                    "areas":       areas,
                    **hit,
                }, ensure_ascii=False) + "\n")
            fh.flush()

    print(f"\nwrote {out_path}", file=sys.stderr)

