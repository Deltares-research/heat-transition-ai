from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_ai import Agent

from src.agent.base import BaseAgent
from src.agent.response import AgentResponse, ToolCall, Reference, TokenUsage
from src.llm import BUILDER_REGISTRY

load_dotenv(Path(__file__).parents[3] / "secrets/azure_llm.env")


class RAGAgent(BaseAgent):

    def build_agent(self) -> None:
        self.agent = Agent(
            model=BUILDER_REGISTRY["azure"](self.config["responder"]["model"])
        )

    def respond(self, prompt: str) -> AgentResponse:

        agent_response = self.agent.run_sync(prompt)

        tool_calls = None
        reasoning_steps = None
        references = None
        token_usage = TokenUsage(
            tokens_in=agent_response.usage.input_tokens,
            tokens_out=agent_response.usage.output_tokens,
        )

        return AgentResponse(
            user_prompt=prompt,
            agent_response=agent_response.output,
            tool_calls=tool_calls,
            reasoning_steps=reasoning_steps,
            references=references,
            token_usage=token_usage,
            scoring=None,
        )


if __name__ == "__main__":

    agent = RAGAgent()

    response = agent.respond("Hi!")

    print(response.agent_response)

