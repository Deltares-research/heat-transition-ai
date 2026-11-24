"""Rich rendering shared by every command module.

Kept separate from app.py so each command imports only what it needs, and
from the individual command modules so the table styling doesn't drift
between "ingest-gemeentes" and "ingest-documents".
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

__all__ = ["render_table_diff"]


def render_table_diff(
    console: Console,
    before: dict[str, int],
    after: dict[str, int],
    title: str,
) -> None:
    """Row counts per table, with the change this run made highlighted."""
    table = Table(title=title, show_edge=True)
    table.add_column("table", style="bold")
    table.add_column("rows", justify="right")
    table.add_column("change", justify="right")

    for name, count in after.items():
        delta = count - before.get(name, 0)
        if delta > 0:
            change = f"[green]+{delta:,}[/green]"
        elif delta < 0:
            change = f"[red]{delta:,}[/red]"
        else:
            change = "[dim]-[/dim]"
        table.add_row(name, f"{count:,}", change)

    console.print(table)
