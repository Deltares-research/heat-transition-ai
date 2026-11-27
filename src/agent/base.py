"""Base class for agents.

A subclass implements `respond` and gets its settings from a ``config.json``
sitting next to that subclass's own module/package — this class owns nothing
beyond that config lookup. The LLM client, tool wiring and any state belong
to the subclass.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any
from abc import abstractmethod
from src.agent.response import AgentResponse
from src.paths import require_file

__all__ = ["BaseAgent"]


class BaseAgent:
    def __init__(self) -> None:
        self.config: dict[str, Any] = self._load_config()
        self.build_agent()

    def _load_config(self) -> dict[str, Any]:
        config_dir = Path(inspect.getfile(type(self))).parent
        path = require_file(config_dir / "config.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    @abstractmethod
    def build_agent(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def respond(self, prompt: str) -> AgentResponse:
        """Take a user prompt, return the agent's response. Subclasses implement this."""
        raise NotImplementedError
