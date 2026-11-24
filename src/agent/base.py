"""Base class for agents.

A subclass names its config file (e.g. ``"my_agent"`` or ``"my_agent.json"``,
resolved against ``src/agent/config/``) and implements `respond`. This class
owns nothing beyond that config lookup — the LLM client, tool wiring and any
state belong to the subclass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.response import AgentResponse
from src.paths import require_file

__all__ = ["BaseAgent"]

CONFIG_DIR = Path(__file__).parent / "config"


class BaseAgent:
    def __init__(self, config_name: str) -> None:
        self.config: dict[str, Any] = self._load_config(config_name)

    @staticmethod
    def _load_config(config_name: str) -> dict[str, Any]:
        path = Path(config_name)
        if path.suffix != ".json":
            path = path.with_suffix(".json")
        if not path.is_absolute():
            path = CONFIG_DIR / path
        path = require_file(path)
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def respond(self, prompt: str) -> AgentResponse:
        """Take a user prompt, return the agent's response. Subclasses implement this."""
        raise NotImplementedError
