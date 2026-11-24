"""Embeddings via Azure AI Foundry (text-embedding-3-large).

Configuration lives in ``secrets/embedder.env``; real environment variables
win over the file, as everywhere else.

Smoke-test with::

    python -m src.embedding
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Sequence

import litellm
from dotenv import load_dotenv

from src.console import safe_console

litellm.suppress_debug_info = True
litellm.drop_params = True

__all__ = ["Embedder", "EmbeddingConfig"]

ROOT = Path(__file__).parents[2]
ENV_PATH = ROOT / "secrets" / "embedder.env"

_MISSING = f"""No embedding configuration found.

Create {ENV_PATH} containing:

    AZURE_EMBEDDING_ENDPOINT=https://RESOURCE.openai.azure.com/
    AZURE_EMBEDDING_API_KEY=KEY
    AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-large
    AZURE_EMBEDDING_API_VERSION=2024-10-21

See secrets/embedder.env.example."""


class EmbeddingConfig:
    """Resolved embedding settings."""

    def __init__(self, env_path: Path | str = ENV_PATH) -> None:
        load_dotenv(env_path)

        self.endpoint = os.environ.get("AZURE_EMBEDDING_ENDPOINT", "").strip()
        self.api_key = os.environ.get("AZURE_EMBEDDING_API_KEY", "").strip()
        self.deployment = os.environ.get(
            "AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"
        ).strip()
        self.api_version = os.environ.get(
            "AZURE_EMBEDDING_API_VERSION", "2024-10-21"
        ).strip()
        self.model = os.environ.get("EMBEDDING_MODEL", "").strip() or f"azure/{self.deployment}"
        self.dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "3072"))
        self.batch = int(os.environ.get("EMBEDDING_BATCH", "64"))
        self.retries = int(os.environ.get("EMBEDDING_RETRIES", "5"))

        if not self.endpoint or not self.api_key:
            raise RuntimeError(_MISSING)

    def describe(self) -> str:
        return (
            f"{self.model} @ {self.endpoint} "
            f"(api-version {self.api_version}, {self.dimensions}d, batch {self.batch})"
        )


class Embedder:
    """Batched embedding calls with the dimension contract enforced."""

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or EmbeddingConfig()

    def _call(self, texts: Sequence[str]) -> list[list[float]]:
        response = litellm.embedding(
            model=self.config.model,
            input=list(texts),
            api_key=self.config.api_key,
            api_base=self.config.endpoint,
            api_version=self.config.api_version,
            dimensions=self.config.dimensions,
            num_retries=self.config.retries,
        )
        # The API may return items out of order; index is authoritative.
        ordered = sorted(response.data, key=lambda d: d["index"])
        vectors = [d["embedding"] for d in ordered]

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"embedding count mismatch: sent {len(texts)}, got {len(vectors)}"
            )
        for vector in vectors:
            if len(vector) != self.config.dimensions:
                raise RuntimeError(
                    f"expected {self.config.dimensions}-dimensional vectors, "
                    f"got {len(vector)}. Check EMBEDDING_DIMENSIONS matches the "
                    f"deployed model."
                )
        return vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed every text, in order, batching under the hood."""
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), self.config.batch):
            out.extend(self._call(texts[start : start + self.config.batch]))
        return out

    def embed_iter(self, texts: Sequence[str]) -> Iterator[list[list[float]]]:
        """Yield one batch of vectors at a time, for progress reporting."""
        for start in range(0, len(texts), self.config.batch):
            yield self._call(texts[start : start + self.config.batch])


def _check() -> int:
    config = EmbeddingConfig()
    print(config.describe())

    samples = [
        "Het warmteprogramma beschrijft de aardgasvrije wijkaanpak.",
        "The heat programme describes the natural-gas-free district approach.",
    ]
    vectors = Embedder(config).embed(samples)

    print(f"\nembedded {len(vectors)} texts, {len(vectors[0])} dimensions each")

    # A Dutch sentence and its English translation should sit close together;
    # this is the quickest end-to-end sanity check of the deployment.
    import math

    a, b = vectors
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    print(f"nl/en cosine similarity: {dot / norm:.3f}  (expect > 0.5)")
    return 0


def main() -> int:
    safe_console()
    try:
        return _check()
    except RuntimeError as exc:
        print(f"\n{exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - surface provider errors readably
        print(f"\n{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
