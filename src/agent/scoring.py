"""Per-question RAG-quality scoring via an LLM judge.

This is NOT a comparison against a golden-dataset answer. It scores the RAG
mechanics of one question/response pair standalone: whether the answer stays
grounded in the references the agent retrieved (faithfulness), whether it
actually addresses the question asked (answer relevancy), and whether the
retrieved references were themselves relevant to the question (context
relevancy). Mirrors the litellm calling convention in `src/responder/llm.py`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.agent.response import AgentResponse, Reference

__all__ = ["score"]

load_dotenv(Path(__file__).parents[2] / ".env")

# Falls back to the same model/creds as src/responder/llm.py, but can be
# pointed at a different (e.g. cheaper) judge model independently.
MODEL = os.environ.get("JUDGE_MODEL", os.environ.get("MODEL", "gpt-5.4"))
API_KEY = os.environ.get("API_KEY")
API_BASE = os.environ.get("API_BASE")
TEMPERATURE = float(os.environ.get("JUDGE_TEMPERATURE", "0.0"))

SYSTEM_PROMPT = """
You are a meticulous RAG evaluator. You are given a user question, the
reference passages a retrieval-augmented agent drew on, and the agent's
answer. Score the answer on three dimensions, each a float from 0.0 to 1.0:

- faithfulness: is every claim in the answer supported by the references?
  Unsupported or contradicted claims lower this score.
- answer_relevancy: does the answer actually address the question asked?
- context_relevancy: were the references relevant and sufficient for
  answering the question, independent of whether the answer used them well?

Return ONLY a JSON object, no prose, no markdown fences:
{"faithfulness": <0-1>, "answer_relevancy": <0-1>, "context_relevancy": <0-1>, "reasoning": "<one short sentence>"}
""".strip()


def _context_block(references: list[Reference]) -> str:
    if not references:
        return "(none — the agent retrieved no references)"
    return "\n\n".join(
        f"[{ref.doc_id}] {ref.quote or '(no quote captured)'}" for ref in references
    )


def _complete(messages: list[dict[str, str]]) -> str:
    import litellm

    litellm.drop_params = True  # reasoning models reject temperature, max_tokens, etc.

    completion = litellm.completion(
        model=MODEL,
        api_key=API_KEY,
        api_base=API_BASE,
        temperature=TEMPERATURE,
        response_format={"type": "json_object"},
        messages=messages,
    )
    return completion.choices[0].message.content or ""


def _parse(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def score(response: AgentResponse) -> str:
    """Judge one agent response's RAG quality, standalone (no golden answer
    involved). Returns one summary line, since `AgentResponse.scoring` is a
    plain string field rather than a schema of its own.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"### Question\n{response.user_prompt}\n\n"
                f"### Retrieved references\n{_context_block(response.references)}\n\n"
                f"### Agent answer\n{response.agent_response}"
            ),
        },
    ]

    parsed = _parse(_complete(messages))
    if not parsed:
        return "ERROR | judge reply unparseable"

    faithfulness = float(parsed.get("faithfulness", 0.0))
    answer_relevancy = float(parsed.get("answer_relevancy", 0.0))
    context_relevancy = float(parsed.get("context_relevancy", 0.0))
    reasoning = parsed.get("reasoning", "")

    return (
        f"faithfulness={faithfulness:.2f} "
        f"| answer_relevancy={answer_relevancy:.2f} "
        f"| context_relevancy={context_relevancy:.2f} "
        f"| {reasoning}"
    )
