from __future__ import annotations

import argparse
from typing import Any, TextIO

from rich.console import Console, Group
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from rich_argparse import RichHelpFormatter

from ov import __version__

BRAND = "bold #42a5f5"
HEADING = "bold"
NAME = "#26a69a"
DIM = "#78909c"
INDENT = (0, 0, 0, 2)

SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Sign in", ("login", "logout", "remember", "whoami", "instances", "tenants", "use")),
    ("Call the API", ("api", "request", "spec")),
    ("Agent", ("agent",)),
    ("Setup", ("config", "setup", "update")),
)

RichHelpFormatter.styles.update(
    {
        "argparse.args": NAME,
        "argparse.groups": HEADING,
        "argparse.metavar": DIM,
        "argparse.prog": BRAND,
    }
)
RichHelpFormatter.group_name_formatter = str.capitalize


class CommandParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", RichHelpFormatter)
        super().__init__(*args, **kwargs)


def _command_help(commands: argparse._SubParsersAction) -> dict[str, str]:
    return {action.dest: action.help or "" for action in commands._choices_actions}


def _rows(entries: list[tuple[str, str]], width: int) -> Padding:
    table = Table.grid(padding=(0, 3))
    table.add_column(style=NAME, no_wrap=True, min_width=width)
    table.add_column()
    for name, about in entries:
        table.add_row(name, about)
    return Padding(table, INDENT)


def _options(parser: argparse.ArgumentParser) -> list[tuple[str, str]]:
    rows = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction) or not action.option_strings:
            continue
        metavar = f" {action.metavar}" if action.metavar else ""
        rows.append((", ".join(action.option_strings) + metavar, action.help or ""))
    return rows


def render_root(parser: argparse.ArgumentParser, commands: argparse._SubParsersAction, epilog: str) -> Group:
    about = _command_help(commands)
    options = _options(parser)
    width = max(len(name) for _, names in SECTIONS for name in names)
    usage = Text.assemble(("Usage", HEADING), "  ov ", ("[-i INSTANCE]", DIM), " <command> ", ("[options]", DIM))
    parts: list[Any] = [
        Text.from_markup(f"[{BRAND}]ov[/] [{DIM}]{__version__}[/]  {parser.description}"),
        Text(""),
        usage,
    ]

    for title, names in SECTIONS:
        parts += [Text(""), Text(title, style=HEADING), _rows([(name, about[name]) for name in names], width)]

    parts += [Text(""), Text("Options", style=HEADING), _rows(options, 0)]
    parts += [Text(""), Text(epilog, style=DIM)]
    return Group(*parts)


def print_root(
    parser: argparse.ArgumentParser, commands: argparse._SubParsersAction, epilog: str, file: TextIO | None
) -> None:
    Console(file=file, highlight=False, soft_wrap=False).print(render_root(parser, commands, epilog))
