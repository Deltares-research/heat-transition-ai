"""FastAPI app exposing the agent in ``src/agent`` over HTTP.

Run:
    python -m apps.api               # uvicorn on :8000
    uvicorn apps.api:app --reload    # dev server with reload
"""

from __future__ import annotations

import os
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.agent import AgentResponse, BaseAgent, DummyAgent

__all__ = ["app"]

# The webapp talks to this API directly (CORS) when not run behind Vite's dev
# proxy, e.g. `vite preview` or a separately hosted build.
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

# Stubbed with DummyAgent until a real BaseAgent subclass exists. Swap the
# body of `get_agent` for the real one — everything else below is agnostic to
# which agent is behind it.
AGENT_CONFIG = "example"


class AskRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


@lru_cache(maxsize=1)
def get_agent() -> BaseAgent:
    return DummyAgent(AGENT_CONFIG)


app = FastAPI(title="heat-transition-ai agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AgentResponse)
def ask(request: AskRequest) -> AgentResponse:
    agent = get_agent()
    try:
        return agent.respond(request.prompt)
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=501,
            detail="No concrete agent is wired up yet — BaseAgent.respond() is abstract.",
        ) from exc
