"""heat-transition-ai: independent subpackages, no shared re-exports.

Each subsystem (agent, api, blob, cli, db, embedding, ingestion, mcp,
responder, text, tools) is imported directly, e.g. ``from src.db import
DBClient``. Nothing is re-exported here, since any ``src.*`` import runs
this file first — re-exporting one subsystem's heavy dependencies here
would force-load them for every other subsystem too.
"""

