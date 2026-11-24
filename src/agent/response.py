"""Pydantic schema for what one agent call produces."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["AgentResponse", "Reference", "TokenUsage", "ToolCall"]


class ToolCall(BaseModel):
    """One tool invocation the agent made while producing its response."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None


class TokenUsage(BaseModel):
    """Token accounting for a single underlying model call."""

    tokens_in: int
    tokens_out: int


class Reference(BaseModel):
    """One source chunk the agent drew on, traceable to its document.

    ``chunk_id`` follows the ``{doc_id}:{chunk_index}`` scheme from
    ``src.ingestion.chunks.chunk_id`` — doc_id alone is kept alongside it since
    it is what ``report_nodes`` (and its ``title``) key on.
    """

    doc_id: str
    chunk_id: str
    title: str | None = None
    quote: str | None = None


class AgentResponse(BaseModel):
    """Everything produced by one `BaseAgent.respond()` call."""

    user_prompt: str
    agent_response: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reasoning_steps: list[str] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    token_usage: list[TokenUsage] = Field(default_factory=list)
