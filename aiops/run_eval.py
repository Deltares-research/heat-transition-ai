"""Per-question RAG-quality evaluation runner for the agent in `src/agent`.

    python -m aiops.run_eval

Loads `aiops/config.json` (which agent class + agent-config to evaluate) and
`aiops/golden_dataset.jsonl` (one question per line, plus the
references/tools/answer a human would expect for context — not used by
scoring itself). Runs every question through the agent, judges each
response's RAG quality standalone with `src.agent.scoring.score` (an LLM
judge — no comparison to the golden answer), and writes `aiops/report.json`.
Exits non-zero if any question's mean judge score falls below `MIN_SCORE`, so
CI can use this as a gate.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.agent.base import BaseAgent
from src.agent.scoring import score
from src.paths import require_file

__all__ = ["main", "run"]

AIOPS_DIR = Path(__file__).parent
DEFAULT_CONFIG = AIOPS_DIR / "config.json"
DEFAULT_DATASET = AIOPS_DIR / "golden_dataset.jsonl"
DEFAULT_REPORT = AIOPS_DIR / "report.json"

MIN_SCORE = 0.6


class GoldenExample(BaseModel):
    """One row of the golden dataset driving the eval. Only `question` is fed
    to the agent — `references`/`tools`/`answer` are kept for human context
    and future use; scoring judges the live response standalone."""

    question: str
    references: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    answer: str


def _load_agent(config_path: Path) -> BaseAgent:
    """Instantiate the agent named in `config_path`'s "agent" field (a
    dotted `module.ClassName` path) with its "agent_config" name."""
    config = json.loads(require_file(config_path).read_text(encoding="utf-8"))
    module_name, _, class_name = config["agent"].rpartition(".")
    agent_cls = getattr(importlib.import_module(module_name), class_name)
    return agent_cls(config["agent_config"])


def _load_dataset(dataset_path: Path) -> list[GoldenExample]:
    examples = []
    with open(require_file(dataset_path), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(GoldenExample.model_validate_json(line))
    return examples


def _mean_score(scoring: str) -> float | None:
    """Pull the `name=0.NN` metrics out of a `score()` summary line."""
    values = [float(v) for v in re.findall(r"=([01](?:\.\d+)?)\b", scoring)]
    return sum(values) / len(values) if values else None


def run(config_path: Path, dataset_path: Path, report_path: Path) -> list[dict[str, Any]]:
    agent = _load_agent(config_path)
    rows: list[dict[str, Any]] = []

    for example in _load_dataset(dataset_path):
        response = agent.respond(example.question)
        response.scoring = score(response)
        rows.append(
            {
                "question": example.question,
                "agent_response": response.agent_response,
                "scoring": response.scoring,
            }
        )

    report_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the aiops per-question RAG-scoring eval.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    rows = run(args.config, args.dataset, args.report)

    failed = 0
    for row in rows:
        mean = _mean_score(row["scoring"])
        flag = "OK" if mean is not None and mean >= MIN_SCORE else "LOW"
        print(f"[{flag}] {row['question']} -> {row['scoring']}")
        if flag == "LOW":
            failed += 1

    print(f"\n{len(rows) - failed}/{len(rows)} at or above {MIN_SCORE}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
