"""Registered SQL queries (``src/db/sql/queries.sql``), wrapped as tools.

Each query's ``-- name`` / ``-- description`` / ``-- use when`` header
(parsed by :func:`src.db.load_registry`) becomes an :class:`SQLTool`: a
callable that takes the database connection as its first argument plus the
query's own named parameters, carrying enough metadata to register itself
with an MCP server later::

    from src.tools import SQL_TOOLS

    db = DBClient(readonly=True)
    for tool in SQL_TOOLS.values():
        mcp.add_tool(tool.bind(db), name=tool.name, description=tool.description)

Adding a query to ``queries.sql`` adds a tool here; nothing in this module
needs editing.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.db import DBClient, load_registry

__all__ = ["SQLTool", "QUERIES_PATH", "load_sql_tools"]

QUERIES_PATH = Path(__file__).parents[1] / "db" / "sql" / "queries.sql"

# Every query parameter is a string by convention (`$gemeente`, `$term`, ...)
# except these, which need their real type so the generated signature — and
# the MCP input schema an LLM fills in — accepts the values queries.sql
# expects: a float vector for a cosine-similarity search, an int for a count.
_PARAM_TYPES: dict[str, type] = {
    "embedding": list[float],
    "limit": int,
}


@dataclass(frozen=True)
class SQLTool:
    """One registered read query, plus the metadata an MCP tool needs."""

    name: str
    description: str
    use_when: str
    params: list[str]
    query: str

    def run(self, db: DBClient, **params: Any) -> list[dict[str, Any]]:
        """Execute this query against ``db``. See ``DBClient.query``."""
        return db.query(self.name, **params)

    def bind(self, db: DBClient) -> Callable[..., list[dict[str, Any]]]:
        """A version of :meth:`run` with ``db`` already supplied, carrying
        this tool's name/description/signature — ready for ``mcp.add_tool()``,
        whose input-schema inspection needs a plain ``**kwargs``-free callable.
        """

        def bound(**params: Any) -> list[dict[str, Any]]:
            return self.run(db, **params)

        bound.__name__ = self.name
        bound.__doc__ = self.description
        bound.__signature__ = inspect.Signature(
            [
                inspect.Parameter(
                    p, inspect.Parameter.KEYWORD_ONLY,
                    annotation=_PARAM_TYPES.get(p, str),
                )
                for p in self.params
            ]
        )
        bound.__annotations__ = {p: _PARAM_TYPES.get(p, str) for p in self.params} | {"return": list}
        return bound


def load_sql_tools(path: Path = QUERIES_PATH) -> dict[str, SQLTool]:
    """Every ``-- name:`` query in ``path``, wrapped as an :class:`SQLTool`."""
    registry = load_registry(path)
    return {
        name: SQLTool(
            name=name,
            description=spec["description"],
            use_when=spec["use_when"],
            params=spec["params"],
            query=spec["query"],
        )
        for name, spec in registry.items()
    }
