"""Entry point and command dispatch for the Rich CLI.

    python -m apps.cli ingest-gemeentes
    python -m apps.cli ingest-documents --prefix corpus/ --limit 5

Each `apps/cli/<command>.py` module exposes `add_parser(subparsers)`, which
registers its subcommand and wires `parser.set_defaults(handler=run)`. `run`
takes `(args, console)` and returns an exit code — the same shape for every
command, so adding one is just another `add_parser` call below.
"""

from __future__ import annotations

import argparse
import time

from rich.console import Console
from rich.traceback import install as install_rich_traceback

from apps.cli import documents as documents_cmd
from apps.cli import gemeentes as gemeentes_cmd
from src.console import safe_console

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m apps.cli",
        description="Heat-transition-ai pipeline commands.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    gemeentes_cmd.add_parser(subparsers)
    documents_cmd.add_parser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    safe_console()

    console = Console()
    install_rich_traceback(console=console, show_locals=False)

    parser = build_parser()
    args = parser.parse_args(argv)

    started = time.perf_counter()
    try:
        code = args.handler(args, console) or 0
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/yellow]")
        return 130
    except (ConnectionError, PermissionError, RuntimeError, FileNotFoundError) as exc:
        console.print(f"\n[red]{exc}[/red]")
        return 1

    console.print(f"\n[dim]done in {time.perf_counter() - started:,.1f}s[/dim]")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
