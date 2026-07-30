"""Answer schema questions against a single markdown document via LiteLLM.

Plain-text answers: no JSON schema, no enums, no typed models.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import litellm
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

MODEL = os.environ.get("MODEL", "gpt-5.4")
API_KEY = os.environ.get("API_KEY")
API_BASE = os.environ.get("API_BASE")
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.0"))
MAX_CHARS = int(os.environ.get("MAX_CHARS", "400000"))

SYSTEMS = {
        "en": """
            You are a careful analyst who reads municipal heat-transition programmes (warmteprogramma's).
            
            Rules:
            - Answer SOLELY on the basis of the document provided.
            - If the document does not state the answer, begin your reply with exactly: not stated
              You may add a short clause explaining what the document says instead, e.g.
              "not stated - the programme mentions heat networks but gives no building counts".
              Zero is NOT a synonym for "not stated". Never supply a number from your own
              knowledge, and do not compute or infer values that are not stated literally in the document.
            - Answer briefly and factually: a number, a word, or at most two sentences.
            - End with a VERBATIM quote from the document that supports your answer, in quotation
              marks, with the page number if visible. Do not invent a quote. But when the answer is
              "not stated", give NO quote and NO page - there is nothing to cite.
            - Write ALL prose in English. Translate every Dutch word that is not inside quotation
              marks, including the first word of a sentence: "inwoners" -> "residents",
              "buurt" -> "neighbourhood", "wijk" -> "district", "gemeente" -> "municipality".
              The ONLY Dutch allowed anywhere in your answer is the text inside the verbatim quote.
              A Dutch word in English prose is an error.
            - The document may have a technical header line with metadata at the top (municipality,
              province, number of inhabitants, URL). This is NOT part of the heat-transition programme
              and must never be used as a source or quote.
            - Do not give JSON, do not list fields, only running text.
            """,
        "nl": """
            Je bent een zorgvuldige analist die gemeentelijke warmteprogramma's leest.
            
            Regels:
            - Antwoord UITSLUITEND op basis van het aangeleverde document.
            - Staat het antwoord niet in het document, begin je antwoord dan exact met: niet vermeld
              Je mag een korte toelichting toevoegen over wat er wel staat, bijvoorbeeld
              "niet vermeld - het programma noemt warmtenetten maar geeft geen aantallen gebouwen".
              Nul is GEEN synoniem voor "niet vermeld". Vul nooit een getal aan uit eigen kennis,
              en reken of leid geen waarden af die niet letterlijk in het document staan.
            - Antwoord kort en feitelijk: een getal, een woord, of hooguit twee zinnen.
            - Sluit af met een LETTERLIJK citaat uit het document dat je antwoord draagt, tussen
              aanhalingstekens, met paginanummer indien zichtbaar. Verzin geen citaat. Maar als het
              antwoord "niet vermeld" is, geef dan GEEN citaat en GEEN pagina - er is niets te citeren.
            - Schrijf je antwoord in het Nederlands.
            - Het document kan bovenaan een technische kopregel met metadata bevatten (gemeente,
              provincie, aantal inwoners, URL). Die hoort NIET bij het warmteprogramma en mag nooit
              als bron of citaat gebruikt worden.
            - Geef geen JSON, geen opsomming van velden, alleen lopende tekst.
            """,
}


PROMPTS = {
    "en": {
        "question": "Question:",
        "batch": (
            "Answer ALL the questions below.\n"
            "For each question repeat the exact heading '### <id>' and put your "
            "answer on the lines beneath it. No other headings."
        ),
    },
    "nl": {
        "question": "Vraag:",
        "batch": (
            "Beantwoord ALLE onderstaande vragen.\n"
            "Herhaal per vraag exact de kopregel '### <id>' en zet je antwoord op "
            "de regels daaronder. Geen andere koppen."
        ),
    },
}


def _document_block(md: str) -> tuple[str, bool]:
    truncated = len(md) > MAX_CHARS
    return md[:MAX_CHARS], truncated


def _complete(messages: list[dict[str, str]]) -> tuple[str, Any]:
    completion = litellm.completion(
        model=MODEL,
        api_key=API_KEY,
        api_base=API_BASE,
        temperature=TEMPERATURE,
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


def ask(md: str, question: str | dict[str, Any], lan: str = "en") -> dict[str, Any]:
    """Answer one question against one markdown document. Response is plain text."""
    if isinstance(question, str):
        question = {"id": "ad_hoc", "nl": question}

    prompt_text = question[lan]
    body, truncated = _document_block(md)

    text, usage = _complete(
        [
            {"role": "system", "content": SYSTEMS[lan]},
            {
                "role": "user",
                "content": (
                    f"<document>\n{body}\n</document>\n\n"
                    f"{PROMPTS[lan]['question']} {prompt_text}"
                ),
            },
        ]
    )

    result: dict[str, Any] = {
        "question_id": question.get("id"),
        "model": MODEL,
        "truncated": truncated,
        "doc_chars": len(md),
        "response": (text or "").strip(),
    }
    tokens = _usage(usage)
    if tokens:
        result["tokens"] = tokens
    return result


def ask_batch(md: str, questions: list[dict[str, Any]], lan: str = "en") -> list[dict[str, Any]]:
    """Answer every question in a single call. Response is plain text per question."""
    body, truncated = _document_block(md)
    listing = "\n".join(
        f"### {q['id']}\n{q[lan]}" for q in questions
    )

    text, usage = _complete(
        [
            {"role": "system", "content": SYSTEMS[lan]},
            {
                "role": "user",
                "content": (
                    f"<document>\n{body}\n</document>\n\n"
                    f"{PROMPTS[lan]['batch']}\n\n"
                    f"{listing}"
                ),
            },
        ]
    )

    answers = _split_sections(text or "")
    shared = {
        "model": MODEL,
        "truncated": truncated,
        "doc_chars": len(md),
        "batched": True,
    }

    rows = []
    for q in questions:
        rows.append(
            {
                **shared,
                "question_id": q["id"],
                "response": answers.get(q["id"], ""),
                **({} if q["id"] in answers else {"error": "missing from batch reply"}),
            }
        )

    tokens = _usage(usage)
    if tokens and rows:
        rows[0]["tokens"] = tokens
    return rows


def _split_sections(text: str) -> dict[str, str]:
    """Split '### id' delimited output into {id: answer}."""
    parts = re.split(r"^#{1,6}\s*([\w-]+)\s*$", text, flags=re.MULTILINE)
    out = {}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip()] = parts[i + 1].strip()
    return out