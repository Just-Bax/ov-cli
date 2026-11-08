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
MAX_LISTED_INSTANCES = 4


class AgentTerminal:
    def __init__(self, color: bool) -> None:
        self._out = Console(no_color=not color, highlight=False, soft_wrap=True)

    def started(self, url: str, full_access: bool) -> None:
        settings = db.get_preferences()
        provider = providers.get(settings["provider"])
        model = settings["defaultModel"] or "no model picked yet"

        rows = Table.grid(padding=(0, 3))
        rows.add_column(style=LABEL)
        rows.add_column()
        rows.add_row("Open", Text(url, style=f"bold underline link {url}"))
        rows.add_row("Provider", f"{provider.name}  [{DIM}]{model}[/]")
        rows.add_row("Instances", self._instances())
        rows.add_row("Workspace", settings["workspace"] or f"[{DIM}]not set[/]")
        if full_access:
            rows.add_row(
                "Access", f"[{DANGER}]Full access offered[/]: threads set to it change anything without asking"
            )

        self._out.print()
        self._out.print(f"  [{BRAND}]OV Agent[/] [{DIM}]{__version__}[/]")
        self._out.print()
        self._out.print(Padding(rows, (0, 0, 0, 2)))
        self._out.print()
        self._out.print(f"  [{DIM}]Press[/] Ctrl+C [{DIM}]to stop[/]")
        self._out.print()

    def _instances(self) -> str:
        rows = instances()
        if not rows:
            return f"[{DIM}]none yet, sign in from the app[/]"

        signed_in = [r["alias"] for r in rows if r["valid"]]
        expired = len(rows) - len(signed_in)
        shown = ", ".join(signed_in[:MAX_LISTED_INSTANCES])
        more = f" +{len(signed_in) - MAX_LISTED_INSTANCES}" if len(signed_in) > MAX_LISTED_INSTANCES else ""
        stale = f"  [{DIM}]{expired} expired[/]" if expired else ""
        return f"{shown}{more}{stale}" if signed_in else f"[{DIM}]all {expired} sessions expired[/]"

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
