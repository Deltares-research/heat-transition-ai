"""Tools available to the agent, ready for an MCP server to register.

``AGENT_TOOLS`` is a name -> tool registry built at import time. Today it
only merges in the SQL tools from ``src/tools/sql_tools.py`` (one per
``src/db/sql/queries.sql`` query); other tool sources (e.g. non-SQL ones)
should be merged into it here as they're added, so callers only ever import
one registry::

    from src.tools import AGENT_TOOLS

    for tool in AGENT_TOOLS.values():
        mcp.add_tool(tool.bind(db), name=tool.name, description=tool.description)
"""

from src.tools.sql_tools import SQLTool, load_sql_tools

AGENT_TOOLS: dict[str, SQLTool] = {
    **load_sql_tools(),
}

__all__ = ["SQLTool", "load_sql_tools", "AGENT_TOOLS"]
