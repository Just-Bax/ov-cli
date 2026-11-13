from __future__ import annotations

from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from ov import __version__
from ov.agent import providers
from ov.agent.instances.ovproc import instances
from ov.agent.storage import db

BRAND = "bold #42a5f5"
LABEL = "#90a4ae"
DIM = "#78909c"
DANGER = "bold #e53935"
CURRENT = "bold #42a5f5"
INDENT = 2
LABEL_WIDTH = len("Instances")
COLUMN_GAP = 3
CELL_GAP = 2
MAX_INSTANCE_COLUMNS = 6


class AgentTerminal:
    def __init__(self, color: bool) -> None:
        self._out = Console(no_color=not color, highlight=False, soft_wrap=True)

    def started(self, url: str, full_access: bool, plsql: bool) -> None:
        settings = db.get_preferences()
        provider = providers.get(settings["provider"])
        model = settings["defaultModel"] or "no model picked yet"

        rows = Table.grid(padding=(0, COLUMN_GAP))
        rows.add_column(style=LABEL)
        rows.add_column()
        rows.add_row("Open", Text(url, style=f"bold underline link {url}"))
        rows.add_row("Provider", f"{provider.name}  [{DIM}]{model}[/]")
        for index, line in enumerate(self._instances()):
            rows.add_row("Instances" if index == 0 else "", line)
        rows.add_row("Workspace", settings["workspace"] or f"[{DIM}]not set[/]")
        if full_access:
            rows.add_row(
                "Access", f"[{DANGER}]Full access offered[/]: threads set to it change anything without asking"
            )
        if plsql:
            rows.add_row("PL/SQL", f"[{DANGER}]ov_plsql on[/]: the agent can run PL/SQL blocks you approve")

        self._out.print()
        self._out.print(f"  [{BRAND}]OV Agent[/] [{DIM}]{__version__}[/]")
        self._out.print()
        self._out.print(Padding(rows, (0, 0, 0, INDENT)))
        self._out.print()
        self._out.print(f"  [{DIM}]Press[/] Ctrl+C [{DIM}]to stop[/]")
        self._out.print()

    def _instances(self) -> list[str]:
        rows = instances()
        if not rows:
            return [f"[{DIM}]none yet, sign in from the app[/]"]

        width = max(len(r["alias"]) for r in rows)
        signed_in = [_cell(r, width) for r in rows if r["valid"]]
        expired = [f"[{DIM}]{r['alias'].ljust(width)}[/]" for r in rows if not r["valid"]]
        summary = f"{len(signed_in)} signed in"
        if expired:
            summary += f"  [{DIM}]{len(expired)} expired[/]"

        room = self._out.width - INDENT - LABEL_WIDTH - COLUMN_GAP
        per_line = max(1, min(MAX_INSTANCE_COLUMNS, (room + CELL_GAP) // (width + CELL_GAP)))
        gap = " " * CELL_GAP
        lines = [summary]
        lines += [gap.join(chunk) for chunk in _chunks(signed_in, per_line)]
        lines += [gap.join(chunk) for chunk in _chunks(expired, per_line)]
        return lines

    def already_running(self, url: str) -> None:
        self._out.print(f"[{BRAND}]OV Agent[/] is already running at [bold]{url}[/]")

    def stopping(self) -> None:
        self._out.print(f"\n  [{DIM}]Stopping. Press Ctrl+C again to quit without waiting.[/]")

    def stopped(self) -> None:
        self._out.print(f"  [{BRAND}]OV Agent[/] stopped.\n")

    def forced(self) -> None:
        self._out.print("  Quit without waiting for threads and helpers to close.\n")

    def gave_up(self, seconds: int) -> None:
        self._out.print(f"  Quit after {seconds}s: some threads or helpers did not close in time.\n")


def _cell(row: dict, width: int) -> str:
    padded = row["alias"].ljust(width)
    return f"[{CURRENT}]{padded}[/]" if row["current"] else padded


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[start : start + size] for start in range(0, len(items), size)]
