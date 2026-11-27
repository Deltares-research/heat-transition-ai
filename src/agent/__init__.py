from __future__ import annotations

from src.agent.base import BaseAgent
from src.agent.dummy import DummyAgent
from src.agent.response import AgentResponse, Reference, TokenUsage, ToolCall
from src.agent.scoring import score
from src.agent.basic_rag import RAGAgent

# Which agent implementation gets deployed, keyed by a name the API/CLI pass
# in — not to be confused with config file lookup, which each agent now
# resolves on its own (BaseAgent always loads config/config.json).
AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "dummy": DummyAgent,
    "basic_rag": RAGAgent,
}


def get_agent(name: str) -> BaseAgent:
    """Instantiate the agent registered under `name`. See AGENT_REGISTRY."""
    try:
        agent_cls = AGENT_REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"No agent registered as {name!r}. Available: {sorted(AGENT_REGISTRY)}"
        ) from None
    return agent_cls()


__all__ = [
    "AgentResponse",
    "BaseAgent",
    "DummyAgent",
    "Reference",
    "TokenUsage",
    "ToolCall",
    "score",
    "RAGAgent",
    "AGENT_REGISTRY",
    "get_agent",
]
