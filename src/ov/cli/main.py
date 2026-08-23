from __future__ import annotations

import argparse
import json
import os
import sys

from .. import __version__
from .. import config as config_module
from ..errors import EXIT_USAGE, ApiError, OvError
from ..paths import home
from .commands import BUILTIN_NAMES, GROUPS
from .context import INSTANCE_ENV, Context
from .dynamic import cached_spec, register_tag
from .output import console

DESCRIPTION = "Command line client for the OneVizion API."

INSTANCE_HELP = "which signed-in instance to use (alias, hostname or URL)"

# The only flag that takes a value before the subcommand, so scanning argv has
# to know to step over what follows it.
_INSTANCE_FLAGS = ("-i", "--instance")


def add_instance_flag(parser: argparse.ArgumentParser) -> None:
    """Accepted both before and after the subcommand.

    SUPPRESS matters: without it the subparser's own default would overwrite a
    value given at the root, so 'ov -i acme users ...' would silently target the
    current instance instead.
    """
    parser.add_argument(
        "-i",
        "--instance",
        metavar="INSTANCE",
        default=argparse.SUPPRESS,
        help=INSTANCE_HELP,
    )


def build_common() -> argparse.ArgumentParser:
    """Flags every leaf command shares, so they appear in each command's own
    help rather than only at the root."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine readable output")
    common.add_argument("--no-color", action="store_true", help="disable coloured output")
    common.add_argument("--refresh", action="store_true", help="ignore cached responses and schema")
    add_instance_flag(common)
    return common


class RootParser(argparse.ArgumentParser):
    """Adds one line of context to 'invalid choice'.

    Generated groups differ per instance, so a name that works against one
    system is genuinely not a command against another. Argparse cannot say that.
    """

    hint: str = ""

    def error(self, message: str) -> None:  # type: ignore[override]
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
        epilog=_epilog(config, _instance_in(argv)),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.hint = _unknown_group_hint(config, argv)
    parser.add_argument("--version", action="version", version=f"ov {__version__}")
    parser.add_argument("--home", action="store_true", help="print the config directory and exit")
    add_instance_flag(parser)

    subparsers = parser.add_subparsers(dest="command")
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
    """Expand the schema tag being invoked into real commands.

    Registering every tag up front would parse a whole OpenAPI document on every
    run, including 'ov login', so only the tag named on the command line is built.
    """
    wanted = _first_positional(argv)
    if not wanted or wanted in BUILTIN_NAMES:
        return

    spec = cached_spec(config, _instance_in(argv))
    if spec is None or wanted not in spec.tags:
        return
    register_tag(subparsers, common, spec, wanted)


def _first_positional(argv: list[str]) -> str | None:
    skip = False
    for token in argv:
        if skip:
            skip = False
            continue
        if token == "--":
            continue
        if token.startswith("-"):
            if token in _INSTANCE_FLAGS:
                skip = True
            continue
        return token
    return None


def _instance_in(argv: list[str]) -> str | None:
    """Read -i out of argv before argparse runs, so the generated commands can
    be built from the right instance's schema."""
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


def _epilog(config: config_module.Config, instance: str | None) -> str:
    spec = cached_spec(config, instance)
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
    """Windows consoles and redirected pipes default to a legacy codepage, so a
    single non-ASCII value would otherwise abort a render part-written."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser(argv)
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
        return 130
    finally:
        ctx.close()


def _report(ctx: Context, exc: OvError) -> None:
    if ctx.as_json:
        payload = (
            exc.to_dict()
            if isinstance(exc, ApiError)
            else {"error": str(exc), "exit_code": exc.exit_code}
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return

    out = console(ctx, stderr=True)
    out.print(f"[red]{exc}[/red]")
    if isinstance(exc, ApiError) and exc.body:
        out.print(f"[dim]{json.dumps(exc.body, ensure_ascii=False, default=str)[:2000]}[/dim]")


if __name__ == "__main__":
    sys.exit(main())
