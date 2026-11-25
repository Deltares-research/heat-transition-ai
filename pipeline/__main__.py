"""Run every pipeline step in order.

    python -m pipeline

Each step stays a standalone script (``python pipeline/01_ingest_gemeentes.py``
still works on its own) — this just runs them back to back, in the order
listed in ``pipeline.STEPS``, stopping at the first one that exits non-zero.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

from pipeline import STEPS

STEP_DIR = Path(__file__).parent
if str(STEP_DIR) not in sys.path:
    # Each step does `from _step import ...`, relying on its own directory
    # being on sys.path the way it is when the interpreter runs it directly
    # (`python pipeline/01_....py`) — runpy.run_path() doesn't do this for us.
    sys.path.insert(0, str(STEP_DIR))


def main() -> int:
    for name in STEPS:
        path = STEP_DIR / name
        print(f"\n=== {name} ===")
        try:
            runpy.run_path(str(path), run_name="__main__")
        except SystemExit as exc:
            code = exc.code or 0
            if code:
                print(f"\n{name} failed (exit code {code}), stopping.")
                return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
