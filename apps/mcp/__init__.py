"""MCP server exposing the warmteprogramma knowledge graph as tools.

    python -m apps.mcp                         # stdio
    TRANSPORT=http python -m apps.mcp          # streamable http

See `apps/mcp/server.py` for how tools are built from `src/db/sql/queries.sql`.
"""

from apps.mcp.server import build_server, main

__all__ = ["build_server", "main"]
