"""
MCP server over the warmteprogramma knowledge graph (Postgres).

Every query in ``src/db/sql/queries.sql`` becomes a tool, registered
dynamically from its ``-- name / -- description / -- use when`` header.
Adding a query to that file adds a tool; nothing here needs editing.

Run:
    python -m apps.mcp                         # stdio
    TRANSPORT=http python -m apps.mcp          # streamable http
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Any

import pandas as pd
from mcp.server import MCPServer

from src.db import DBClient

__all__ = ["build_server", "main"]

MAX_ROWS = int(os.environ.get("MCP_MAX_ROWS", "200"))

INSTRUCTIONS = """
This server answers questions about Dutch municipal heat-transition programmes
(warmteprogramma's) from a graph database of CBS demographics, programme
documents and their extracted answers.

Rules for using it well:

1. A count means nothing without its denominator. Call `coverage_overview`
   (or `province_overview` for a regional breakdown) before reporting any
   aggregate, and state how many municipalities the number is out of.

2. Municipalities sharing a document are not independent observations. Check
   `shared_documents` before reporting a count across several municipalities —
   the same programme text may otherwise be counted more than once.

3. `search_quotes` and `answers_for_question` return whatever matched, not a
   survey of every programme. Report their results as examples found, not a
   complete picture, unless the result count matches `coverage_overview`.

4. `missing_programmes` lists municipalities with no linked document at all —
   check it before treating silence on a topic as a negative answer.
""".strip()


def _serialise(result: Any) -> str:
    if isinstance(result, pd.DataFrame):
        df = result
    elif isinstance(result, list):
        df = pd.DataFrame(result)          # list of dicts, or of tuples
    else:
        df = pd.DataFrame([result])

    total = len(df)
    payload: dict[str, Any] = {
        "rows": json.loads(df.head(MAX_ROWS).to_json(orient="records", date_format="iso")),
        "row_count": total,
    }
    if total > MAX_ROWS:
        payload["truncated"] = f"showing first {MAX_ROWS} of {total} rows"
    return json.dumps(payload, ensure_ascii=False, indent=2)


PARAM_HINTS = {
    "gemeente":    "Municipality name, e.g. 'Zwolle'. Case-insensitive. Pass '%' to match every municipality.",
    "question_id": "Question id from the registry — call list_questions or find_questions first.",
    "term":        "Free-text term to search for.",
}


def _make_handler(db: DBClient, name: str, params: list[str]):
    """
    Build an async handler whose signature matches the query's parameters —
    MCPServer.add_tool derives the input schema by inspecting the function.
    """
    async def handler(**kwargs: Any) -> str:
        try:
            return _serialise(db.query(name, **kwargs))
        except Exception as exc:  # surface as a tool error, not a crash
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"},
                              ensure_ascii=False)

    handler.__name__ = name
    handler.__signature__ = inspect.Signature(
        [inspect.Parameter(p, inspect.Parameter.KEYWORD_ONLY, annotation=str)
         for p in params]
    )
    handler.__annotations__ = {p: str for p in params} | {"return": str}
    return handler


def build_server(db: DBClient | None = None) -> MCPServer:
    """Assemble the MCP server. Pass a fake `db` (with `.queries`, `.query`,
    `.fetch`) to wire and inspect tools without a live database connection."""
    db = db if db is not None else DBClient(readonly=True)

    server = MCPServer(
        name="warmteprogramma",
        title="Warmteprogramma's van Nederlandse gemeenten",
        instructions=INSTRUCTIONS,
        version="0.1.0",
    )

    # ── registry-driven tools ────────────────────────────────
    for name, spec in db.queries.items():
        description = spec["description"]
        if spec.get("use_when"):
            description = f"{description}\n\nUse when: {spec['use_when']}"
        if spec["params"]:
            hints = "\n".join(f"- {p}: {PARAM_HINTS.get(p, '')}" for p in spec["params"])
            description = f"{description}\n\nParameters:\n{hints}"

        server.add_tool(
            _make_handler(db, name, spec["params"]),
            name=name,
            description=description,
        )

    # ── hand-written helpers the registry can't express ──────
    # (these take real Python defaults, so their filters are genuinely
    # optional — the registry-driven tools above require every param.)
    @server.tool(
        name="list_questions",
        description=(
            "The question registry: every question id, its section, answer type "
            "and text.\n\nUse when: You need a question_id for another tool, or "
            "the user asks what the database can answer."
        ),
    )
    async def list_questions(section: str | None = None) -> str:
        rows = db.fetch(
            "SELECT id, section, type, allowed, en, nl, ord "
            "FROM question "
            "WHERE (%s IS NULL OR section ILIKE %s) "
            "ORDER BY ord",
            (section, section),
        )
        return _serialise(rows)

    @server.tool(
        name="list_municipalities",
        description=(
            "Municipalities with their CBS population and whether a programme "
            "document was found.\n\nUse when: Resolving a name, or checking a "
            "municipality is covered before querying it."
        ),
    )
    async def list_municipalities(province: str | None = None) -> str:
        rows = db.fetch(
            "SELECT g.code, g.name, g.province, g.population, "
            "       EXISTS (SELECT 1 FROM report_gemeente_edges e "
            "               WHERE e.gemeente_code = g.code) AS heeft_programma "
            "FROM gemeente_nodes g "
            "WHERE (%s IS NULL OR g.province ILIKE %s) "
            "ORDER BY g.population DESC NULLS LAST",
            (province, province),
        )
        return _serialise(rows)

    @server.tool(
        name="run_sql",
        description=(
            "Run a read-only SELECT against the database. Tables: gemeente_nodes, "
            "wijk_nodes, buurt_nodes, question, report_nodes, chunk_nodes, "
            "chunk_answer_nodes, area_nodes, and their *_edges join tables.\n\n"
            "Use when: No registered query fits. Prefer the named queries — they "
            "encode the denominator and shared-document rules."
        ),
    )
    async def run_sql(sql: str) -> str:
        lowered = sql.strip().lower()
        if not lowered.startswith(("select", "with")):
            return json.dumps({"error": "only SELECT / WITH statements are allowed"})
        if any(k in lowered for k in
               ("insert", "update", "delete", "drop", "create", "alter", "attach", "copy")):
            return json.dumps({"error": "write and DDL statements are not allowed"})
        try:
            return _serialise(db.fetch(sql))
        except Exception as exc:
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"},
                              ensure_ascii=False)

    return server


def main() -> None:
    server = build_server()
    transport = os.environ.get("TRANSPORT", "stdio").lower()
    if transport == "http":
        server.run(transport="streamable-http")
    elif transport == "sse":
        server.run(transport="sse")
    else:
        server.run()


if __name__ == "__main__":
    main()
