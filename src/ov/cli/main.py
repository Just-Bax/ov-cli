from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn, TextIO

from ov import __version__
from ov.cli.commands import BUILTIN_NAMES, GROUPS
from ov.cli.context import INSTANCE_ENV, Context
from ov.cli.dynamic import cached_spec, register_tag
from ov.cli.help import CommandParser, print_root
from ov.cli.output import console
from ov.core import config as config_module
from ov.core.errors import EXIT_INTERRUPTED, EXIT_USAGE, ApiError, OvError
from ov.core.paths import home

DESCRIPTION = "Command line client for the OneVizion API."

INSTANCE_HELP = "which signed-in instance to use (alias, hostname or URL)"
ERROR_BODY_SHOWN = 2000

_INSTANCE_FLAGS = ("-i", "--instance")


def add_instance_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-i",
        "--instance",
        metavar="INSTANCE",
        default=argparse.SUPPRESS,
        help=INSTANCE_HELP,
    )


def build_common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine readable output")
    common.add_argument("--no-color", action="store_true", help="disable coloured output")
    common.add_argument("--refresh", action="store_true", help="ignore cached responses and schema")
    add_instance_flag(common)
    return common


class RootParser(CommandParser):
    hint: str = ""
    commands: argparse._SubParsersAction | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def print_help(self, file: TextIO | None = None) -> None:
        if self.commands is None:
            raise RuntimeError("The root parser has no commands registered yet.")
        print_root(self, self.commands, self.epilog or "", file)

    def error(self, message: str) -> NoReturn:
        if self.hint and "invalid choice" in message:
            self.print_usage(sys.stderr)
            self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n{self.hint}\n")
        super().error(message)


def build_parser(argv: list[str]) -> argparse.ArgumentParser:
    common = build_common()
    config = config_module.load()

    parser = RootParser(
        prog="ov",
        description=DESCRIPTION,
        epilog=_epilog(config, argv),
    )

    parser.hint = _unknown_group_hint(config, argv)
    parser.add_argument("--version", action="version", version=f"ov {__version__}")
    parser.add_argument("--home", action="store_true", help="print the config directory and exit")
    add_instance_flag(parser)

    subparsers = parser.add_subparsers(dest="command", parser_class=CommandParser)
    parser.commands = subparsers
    for module in GROUPS:
        module.register(subparsers, common)

    _register_dynamic(subparsers, common, config, argv)
    return parser


def _register_dynamic(
    subparsers: argparse._SubParsersAction,
    common: argparse.ArgumentParser,
    config: config_module.Config,
    argv: list[str],
) -> None:
    wanted = _first_positional(argv)
    if not wanted or wanted in BUILTIN_NAMES:
        return
    spec = cached_spec(config, _instance_in(argv))
    if spec is not None and wanted in spec.tags:
        register_tag(subparsers, common, spec, wanted)


def _first_positional(argv: list[str]) -> str | None:
    skip = False
    for token in argv:
        if skip or token == "--":
            skip = False
            continue

        if not token.startswith("-"):
            return token

        skip = token in _INSTANCE_FLAGS

    return None


def _instance_in(argv: list[str]) -> str | None:
    for index, token in enumerate(argv):
        if token in _INSTANCE_FLAGS:
            return argv[index + 1] if index + 1 < len(argv) else None

        if token.startswith("--instance="):
            return token.partition("=")[2] or None

        if token.startswith("-i") and len(token) > 2 and not token.startswith("--"):
            return token[2:]

    return os.environ.get(INSTANCE_ENV) or None


def _unknown_group_hint(config: config_module.Config, argv: list[str]) -> str:
    wanted = _first_positional(argv)
    if not wanted or wanted in BUILTIN_NAMES:
        return ""

    instance = _instance_in(argv)
    named = f"instance '{instance}'" if instance else "the current instance"
    spec = cached_spec(config, instance)
    if spec is None:
        return (
            f"No API schema is cached for {named}. "
            "Run 'ov spec fetch', or 'ov login <url>' if you have not signed in to it."
        )

    if wanted in spec.tags:
        return ""
    return f"'{wanted}' is not a group on {named}. Groups: {', '.join(spec.tags)}."


def _epilog(config: config_module.Config, argv: list[str]) -> str:
    spec = None if _first_positional(argv) else cached_spec(config, _instance_in(argv))
    if spec is None or not spec.tags:
        return (
            "Every API operation is also reachable as 'ov <tag> <operation>' once an "
            "instance is signed in. Start with 'ov login https://yours.onevizion.com'."
        )

    tags = ", ".join(spec.tags)

    return (
        f"Generated groups ({len(spec.operations)} operations): {tags}\n"
        "Run 'ov <tag>' to list its commands, or 'ov api list' to search them all.\n"
        "Signed in to more than one system? 'ov instances', then 'ov -i <alias> ...'."
    )


def force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        parser = build_parser(argv)
    except OvError as exc:
        _report_early(argv, exc)
        return exc.exit_code

    args = parser.parse_args(argv)
    if args.home:
        print(home())
        return 0

    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE

    ctx = Context(args)
    try:
        return args.func(ctx)
    except OvError as exc:
        _report(ctx, exc)
        return exc.exit_code
    except KeyboardInterrupt:
        _report(ctx, OvError("Cancelled."))
        return EXIT_INTERRUPTED
    finally:
        ctx.close()


def _error_payload(exc: OvError) -> dict[str, Any]:
    return exc.to_dict() if isinstance(exc, ApiError) else {"error": str(exc), "exit_code": exc.exit_code}


def _report_early(argv: list[str], exc: OvError) -> None:
    if "--json" in argv:
        print(json.dumps(_error_payload(exc), ensure_ascii=False, indent=2, default=str))
    else:
        print(f"ov: error: {exc}", file=sys.stderr)


def _report(ctx: Context, exc: OvError) -> None:
    if ctx.as_json:
        print(json.dumps(_error_payload(exc), ensure_ascii=False, indent=2, default=str))
        return

    out = console(ctx, stderr=True)
    out.print(f"[red]{exc}[/red]")

    if isinstance(exc, ApiError) and exc.body:
        out.print(f"[dim]{json.dumps(exc.body, ensure_ascii=False, default=str)[:ERROR_BODY_SHOWN]}[/dim]")
