"""Filesystem path helpers shared by every entry point (plain scripts and CLI)."""

from __future__ import annotations

from pathlib import Path

__all__ = ["require_file"]


def require_file(path: Path | str) -> Path:
    """Resolve a required input file, raising a readable error if absent."""
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Input file not found: {resolved}")
    return resolved
