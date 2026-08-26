"""
MCP server over the warmteprogramma DuckDB.

Every query in queries.sql becomes a tool, registered dynamically from the
`-- name / -- description / -- use when` headers. Adding a query to that file
adds a tool; nothing here needs editing.

Run:
    python -m src.mcp.server                  # stdio
    TRANSPORT=http python -m src.mcp.server   # streamable http
"""

from __future__ import annotations
import inspect
import json
import os
from pathlib import Path
from typing import Any
import pandas as pd
from mcp.server import MCPServer
from src.db.db_client import DBClient


# DB_PATH = Path(os.environ.get(
#     "DB_PATH",
#     Path(__file__).parents[2] / "data" / f"{os.environ.get('DB_NAME', 'nplw')}.duckdb",
# ))

DB_PATH = "C:\\Users\\mavritsa\\repositories\\heat-transition-ai\\data\\nplw.duckdb"

MAX_ROWS = int(os.environ.get("MCP_MAX_ROWS", "200"))

db = DBClient(DB_PATH, read_only=True)

INSTRUCTIONS = """
This server answers questions about Dutch municipal heat-transition programmes
(warmteprogramma's) from a database of evidenced extractions.

Rules for using it well:

1. A count means nothing without its denominator. Call `coverage_overview`
   before reporting any aggregate, and state how many municipalities the
   number is out of.

2. Silence and refusal are different. `modality = 'niet_vermeld'` means the
   document does not address the topic; `expliciet_geen` means it demonstrably
   rules it out. Never report the first as the second. Use
   `explicitly_excluded` for refusals, not `who_answered`.

3. Municipalities sharing a document are not independent observations. Check
   `shared_documents` before reporting a count and qualify it if relevant.

4. Every substantive answer carries a source quote and page. Cite them. If
   `ref` is null, say the answer is uncited rather than presenting it as
   evidenced.

5. `search_quotes` returns whatever matched, not a survey of all programmes.
   Report its results as examples found, never as a complete picture.

6. Many quantitative parameters are structurally absent from these documents.
   If asked for a national total of dwellings, euros or megawatts, use
   `answerability_by_question` to show why it cannot be computed rather than
   estimating one.
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
    "gemeente":    "Municipality name, e.g. 'Zwolle'. Case-insensitive.",
    "question_id": "Question id from the registry — call list_questions first.",
    "question_a":  "First question id.",
    "question_b":  "Second question id.",
    "province":    "Province name, e.g. 'Overijssel'.",
    "pattern":     "SQL LIKE pattern, e.g. '%warmtenet%'. Use '%' to match all.",
    "term":        "Free-text term to search for in the source quotes.",
}


def _make_handler(name: str, params: list[str]):
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


def build_server() -> MCPServer:
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
            _make_handler(name, spec["params"]),
            name=name,
            description=description,
        )

    # ── hand-written helpers the registry can't express ──────
    @server.tool(
        name="list_questions",
        description=(
            "The question registry: every question id, its section, answer type "
            "and text.\n\nUse when: You need a question_id for another tool, or "
            "the user asks what the database can answer."
        ),
    )
    async def list_questions(section: str | None = None) -> str:
        sql = ("SELECT id, section, type, values, en, nl FROM question "
               "WHERE ($1 IS NULL OR section ILIKE $1) ORDER BY ord")
        df = db.conn.execute(sql.replace("$1", "?"), [section, section]).df()
        return _serialise(df)

    @server.tool(
        name="list_municipalities",
        description=(
            "Municipalities in the reference list, with whether a programme was "
            "found.\n\nUse when: Resolving a name, or checking a municipality is "
            "covered before querying it."
        ),
    )
    async def list_municipalities(province: str | None = None) -> str:
        df = db.conn.execute(
            "SELECT gemeente, gemeentecode, province, region, number_users, "
            "       url IS NOT NULL AS heeft_programma "
            "FROM gemeente WHERE (? IS NULL OR province ILIKE ?) "
            "ORDER BY number_users DESC NULLS LAST",
            [province, province],
        ).df()
        return _serialise(df)

    @server.tool(
        name="run_sql",
        description=(
            "Run a read-only SELECT against the database. Tables: gemeente, "
            "question, response.\n\nUse when: No registered query fits. Prefer "
            "the named queries — they encode the silence and denominator rules."
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
            return _serialise(db.conn.execute(sql).df())
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

