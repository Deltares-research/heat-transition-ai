"""Answer schema questions against a single markdown document via LiteLLM.

One output contract: a JSON array, one object per question.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import litellm
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

litellm.drop_params = True  # reasoning models reject temperature, max_tokens, etc.

MODEL = os.environ.get("MODEL", "gpt-5.4")
API_KEY = os.environ.get("API_KEY")
API_BASE = os.environ.get("API_BASE")
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.0"))
MAX_CHARS = int(os.environ.get("MAX_CHARS", "400000"))
MAX_COMPLETION = int(os.environ.get("MAX_COMPLETION_TOKENS", "16000"))

MODALITIES = [
    "vastgesteld", "voornemen", "verkenning",
    "expliciet_geen", "onduidelijk", "niet_vermeld",
]

_FIELD_SPEC = """
Each object has exactly these keys:
{
  "question_id": "<id exactly as given>",
  "response":    <the answer, or null>,
  "modality":    "vastgesteld" | "voornemen" | "verkenning" |
                 "expliciet_geen" | "onduidelijk" | "niet_vermeld",
  "ref":         "<verbatim quote from the document>" | null,
  "page":        <page number> | null,
  "note":        "<at most one short clause>" | null
}

Field rules:
- response: a number, a short string, or null. At most two sentences.
- modality:
    vastgesteld     stated as adopted / decided
    voornemen       stated as an intention or plan
    verkenning      stated as under investigation
    expliciet_geen  the document explicitly rules this out
    onduidelijk     addressed, but ambiguously
    niet_vermeld    not addressed at all
  expliciet_geen and niet_vermeld are different. Use expliciet_geen only when
  the document demonstrably says no.
- ref: copied VERBATIM from the document, in Dutch, exactly as written. Never
  paraphrase, never reconstruct, never invent. Set ref to null when no exact
  supporting passage can be copied — some answers (adoption status, dates,
  authorship) have no quotable sentence, and null is correct there.
- page: the page the quote appears on, or null.
- note: optional, explaining what the document says instead. No quote here.

Emit an object for EVERY question, including ones the document does not
answer. Never omit a question. Never merge two questions into one object.
""".strip()

SYSTEMS = {
    "en": f"""
You are a careful analyst reading Dutch municipal heat-transition programmes
(warmteprogramma's).

## Grounding
- Answer SOLELY from the document provided.
- Never supply a value from your own knowledge, and never compute or infer a
  value that is not stated literally in the document.
- Zero is NOT a synonym for absence. If the document gives no number, the
  answer is null, not 0.
- The document may begin with a technical metadata header (municipality,
  province, inhabitants, URL). This is NOT part of the programme. Never use it
  as a source and never quote from it.

## Output
Return ONLY a JSON array. No prose, no explanation, no markdown fences.

{_FIELD_SPEC}

## Language
All prose fields (response, note) in English. Translate every Dutch term:
inwoners -> residents, buurt -> neighbourhood, wijk -> district,
gemeente -> municipality. Dutch appears ONLY inside "ref".
""".strip(),

    "nl": f"""
Je bent een zorgvuldige analist die gemeentelijke warmteprogramma's leest.

## Grondslag
- Antwoord UITSLUITEND op basis van het aangeleverde document.
- Vul nooit een waarde aan uit eigen kennis, en reken of leid geen waarden af
  die niet letterlijk in het document staan.
- Nul is GEEN synoniem voor afwezigheid. Geeft het document geen getal, dan is
  het antwoord null, niet 0.
- Het document kan bovenaan een technische kopregel met metadata bevatten
  (gemeente, provincie, inwoners, URL). Die hoort NIET bij het programma en mag
  nooit als bron of citaat gebruikt worden.

## Uitvoer
Geef UITSLUITEND een JSON-array terug. Geen tekst eromheen, geen uitleg, geen
markdown-fences.

{_FIELD_SPEC}

## Taal
Schrijf de tekstvelden (response, note) in het Nederlands.
""".strip(),
}

PROMPTS = {
    "en": {
        "single": "Answer this one question. Return a JSON array with exactly 1 object.",
        "batch": "Answer ALL {n} questions below. Return a JSON array with exactly {n} objects, in the same order.",
    },
    "nl": {
        "single": "Beantwoord deze ene vraag. Geef een JSON-array met precies 1 object.",
        "batch": "Beantwoord ALLE {n} onderstaande vragen. Geef een JSON-array met precies {n} objecten, in dezelfde volgorde.",
    },
}


# ──────────────────────────────────────────────────────────────
# LLM plumbing
# ──────────────────────────────────────────────────────────────

def _document_block(md: str) -> tuple[str, bool]:
    truncated = len(md) > MAX_CHARS
    return md[:MAX_CHARS], truncated


def _complete(messages: list[dict[str, str]]) -> tuple[str, Any]:
    completion = litellm.completion(
        model=MODEL,
        api_key=API_KEY,
        api_base=API_BASE,
        temperature=TEMPERATURE,
        max_completion_tokens=MAX_COMPLETION,
        response_format={"type": "json_object"},
        messages=messages,
    )
    return completion.choices[0].message.content, getattr(completion, "usage", None)


def _usage(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {
        "prompt": getattr(usage, "prompt_tokens", None),
        "completion": getattr(usage, "completion_tokens", None),
    }


# ──────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────

def _parse_answers(text: str) -> list[dict[str, Any]]:
    """
    Extract a list of answer objects from the reply.

    Tolerates: markdown fences, a wrapping object such as {"answers": [...]},
    and a bare object when only one question was asked.
    """
    if not text:
        return []

    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Last resort: grab the outermost bracketed span.
        m = re.search(r"[\[{].*[\]}]", cleaned, flags=re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []

    if isinstance(data, dict):
        for key in ("answers", "results", "items", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]  # single bare object

    return [o for o in data if isinstance(o, dict)]


def _normalise(obj: dict[str, Any], qid: str) -> dict[str, Any]:
    modality = obj.get("modality")
    return {
        "question_id": qid,
        "response": obj.get("response"),
        "modality": modality if modality in MODALITIES else "onduidelijk",
        "ref": obj.get("ref"),
        "page": obj.get("page"),
        "note": obj.get("note"),
    }


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def ask(md: str, question: str | dict[str, Any], lan: str = "en") -> dict[str, Any]:
    """Answer one question against one markdown document."""
    if isinstance(question, str):
        question = {"id": "ad_hoc", lan: question}

    body, truncated = _document_block(md)
    qid = question.get("id", "ad_hoc")

    text, usage = _complete(
        [
            {"role": "system", "content": SYSTEMS[lan]},
            {
                "role": "user",
                "content": (
                    f"<document>\n{body}\n</document>\n\n"
                    f"{PROMPTS[lan]['single']}\n\n"
                    f"### {qid}\n{question[lan]}"
                ),
            },
        ]
    )

    parsed = _parse_answers(text)
    result: dict[str, Any] = {
        "model": MODEL,
        "truncated": truncated,
        "doc_chars": len(md),
        "batched": False,
    }
    if parsed:
        result.update(_normalise(parsed[0], qid))
    else:
        result.update({
            "question_id": qid,
            "response": None,
            "error": "unparseable reply",
            "raw": (text or "")[:500],
        })

    tokens = _usage(usage)
    if tokens:
        result["tokens"] = tokens
    return result


def ask_batch(
    md: str,
    questions: list[dict[str, Any]],
    lan: str = "en",
    retry_missing: bool = True,
) -> list[dict[str, Any]]:
    """Answer every question in one call, retrying individually for stragglers."""
    body, truncated = _document_block(md)
    listing = "\n\n".join(f"### {q['id']}\n{q[lan]}" for q in questions)

    text, usage = _complete(
        [
            {"role": "system", "content": SYSTEMS[lan]},
            {
                "role": "user",
                "content": (
                    f"<document>\n{body}\n</document>\n\n"
                    f"{PROMPTS[lan]['batch'].format(n=len(questions))}\n\n"
                    f"{listing}"
                ),
            },
        ]
    )

    parsed = _parse_answers(text)
    by_id = {o["question_id"]: o for o in parsed if o.get("question_id")}

    # Positional fallback: the model answered in order but mangled the ids.
    if not by_id and len(parsed) == len(questions):
        by_id = {q["id"]: parsed[i] for i, q in enumerate(questions)}

    shared = {
        "model": MODEL,
        "truncated": truncated,
        "doc_chars": len(md),
        "batched": True,
    }

    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for q in questions:
        qid = q["id"]
        if qid in by_id:
            rows.append({**shared, **_normalise(by_id[qid], qid)})
        else:
            missing.append(q)
            rows.append({**shared, "question_id": qid, "response": None,
                         "error": "missing from batch reply"})

    if missing and retry_missing:
        print(f"  retrying {len(missing)} missing: {[q['id'] for q in missing]}")
        index = {r["question_id"]: i for i, r in enumerate(rows)}
        for q in missing:
            try:
                rows[index[q["id"]]] = ask(md, q, lan)
            except Exception as exc:
                rows[index[q["id"]]]["error"] = f"retry failed: {exc!r}"

    tokens = _usage(usage)
    if tokens and rows:
        rows[0]["tokens"] = tokens

    if not parsed:
        rows[0]["raw"] = (text or "")[:1000]

    return rows