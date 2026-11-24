"""A stub agent that always answers the same question.

Returns a fully populated `AgentResponse` — fake reasoning steps, tool calls
and references included — so the API and webapp can be exercised end to end
before a real agent exists.
"""

from __future__ import annotations

from src.agent.base import BaseAgent
from src.agent.response import AgentResponse, Reference, TokenUsage, ToolCall

__all__ = ["DummyAgent"]


class DummyAgent(BaseAgent):
    def respond(self, prompt: str) -> AgentResponse:
        return AgentResponse(
            user_prompt=prompt,
            agent_response="The capital of the Netherlands is Amsterdam.",
            reasoning_steps=[
                "Identified the question as asking for a country's capital.",
                "Recalled that Amsterdam is the constitutional capital of the Netherlands.",
                "The Hague hosts the government, but that isn't what was asked.",
            ],
            tool_calls=[
                ToolCall(
                    name="list_municipalities",
                    arguments={"province": "Noord-Holland"},
                    result={"rows": [{"gemeente": "Amsterdam", "is_capital": True}]},
                ),
                ToolCall(
                    name="search_quotes",
                    arguments={"term": "hoofdstad"},
                    result={"row_count": 3, "truncated": False},
                ),
            ],
            references=[
                Reference(
                    doc_id="amsterdam",
                    chunk_id="amsterdam:0",
                    title="Warmteprogramma Amsterdam",
                    quote="Amsterdam is de hoofdstad van Nederland.",
                ),
            ],
            token_usage=[TokenUsage(tokens_in=42, tokens_out=13)],
        )
