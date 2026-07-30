from __future__ import annotations
import json
from pathlib import Path
import yaml
from tqdm import tqdm
from src import ask_batch, ask
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parents[1]/".env")
LANGUAGE = os.environ.get("LANGUAGE", "en")
BATCH_MODE = os.environ.get("BATCH_MODE", "on")


LIMIT: int | None = None      # first N documents, or None for all
FORCE = False                 # True re-answers everything


def load_questions(path: Path) -> list[dict]:
    questions = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(questions, list):
        raise ValueError(f"expected a list of questions, got {type(questions).__name__}")
    return questions


def strip_metadata(md: str) -> str:
    """Drop the id + fenced metadata header written by render_md."""
    marker = "\nTEXT:\n"
    i = md.find(marker)
    return md[i + len(marker):] if i != -1 else md


def done_docs(out_path: Path) -> set[str]:
    """doc_ids already answered without error, so runs are resumable."""
    if not out_path.exists():
        return set()
    done, failed = set(), set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        (failed if row.get("error") else done).add(row.get("doc_id"))
    return done - failed


if __name__ == "__main__":

    root = Path(__file__).parents[1]
    md_path = root / "data/processed/md"
    questions_path = root / "data/questions.yaml"
    out_path = root / "data" / f"responses_{LANGUAGE}.jsonl"

    questions = load_questions(questions_path)
    md_files = sorted(md_path.glob("*.md"))
    if LIMIT:
        md_files = md_files[:LIMIT]

    already = set() if FORCE else done_docs(out_path)
    todo = [f for f in md_files if f.stem not in already]
    print(f"{len(todo)} documents x {len(questions)} questions -> {len(todo) if BATCH_MODE == 'on' else len(todo)*len(questions)} calls")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        for md_file in tqdm(todo):
            md = strip_metadata(md_file.read_text(encoding="utf-8"))

            if BATCH_MODE == "on":
                try:
                    rows = ask_batch(md, questions, LANGUAGE)
                except Exception as e:
                    rows = [{"question_id": q.get("id"), "error": repr(e)} for q in questions]
            else:
                rows = []
                for q in questions:
                    try:
                        rows.append(ask(md, q, LANGUAGE))
                    except Exception as e:
                        rows.append({"question_id": q.get("id"), "error": repr(e)})

            for row in rows:
                row["doc_id"] = md_file.stem
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()

    print(f"wrote {out_path}")