from __future__ import annotations

import argparse
from collections.abc import Callable

from .. import session as session_store
from .. import spec as spec_module
from ..config import Config
from ..errors import OvError
from ..spec import Operation, Spec
from .context import Context
from .opargs import add_invocation_flags, add_param_flags, run_operation

# Reading the cached document costs a few hundred milliseconds on a large
# schema, so only the tag actually being invoked is ever expanded.
_cached: dict[str, Spec | None] = {}


def cached_spec(config: Config, instance: str | None = None) -> Spec | None:
    """The schema of one instance as it sits on disk, ignoring its age.

    Help text and command names have to exist before any request happens, so an
    expired cache is still the right thing to build the parser from; refreshing
    it is 'ov spec fetch'. Each instance has its own schema, so an unknown
    instance yields no generated commands rather than another instance's.
    """
    key = instance or ""
    if key in _cached:
        return _cached[key]

    spec: Spec | None = None
    try:
        base_url = session_store.load(instance).base_url
    except OvError:
        base_url = ""
    if base_url:
        spec = spec_module.load_cached(base_url, config.spec_group, ttl_seconds=0)

    _cached[key] = spec
    return spec


def reset_cache() -> None:
    _cached.clear()


def register_tag(
    subparsers: argparse._SubParsersAction,
    common: argparse.ArgumentParser,
    spec: Spec,
    tag: str,
) -> None:
    operations = spec.by_tag(tag)
    if not operations:
        return

    group = subparsers.add_parser(
        tag,
        parents=[common],
        help=f"{len(operations)} generated operations from the API schema",
        description=f"Generated from {spec.title} {spec.version}, tag '{tag}'.",
    )
    actions = group.add_subparsers(dest="operation_name")

    for operation in operations:
        leaf = actions.add_parser(
            operation.name,
            parents=[common],
            help=_help_for(operation),
            description=operation.description or operation.summary or None,
            epilog=f"{operation.method} {operation.path}",
        )
        add_param_flags(leaf, operation)
        add_invocation_flags(leaf)
        leaf.set_defaults(func=_runner(operation))

    group.set_defaults(func=_lister(tag, operations))


def _help_for(operation: Operation) -> str:
    prefix = "(deprecated) " if operation.deprecated else ""
    return prefix + (operation.summary or f"{operation.method} {operation.path}")


def _runner(operation: Operation) -> Callable[[Context], int]:
    def run(ctx: Context) -> int:
        return run_operation(ctx, operation)

    return run


def _lister(tag: str, operations: list[Operation]) -> Callable[[Context], int]:
    def run(ctx: Context) -> int:
        from .output import build_table, emit

        data = [o.to_dict() for o in operations]

        def table():
            return build_table(
                f"ov {tag}",
                [
                    {"header": "Command", "style": "cyan"},
                    {"header": "Method"},
                    {"header": "Path", "overflow": "fold"},
                    {"header": "Summary", "overflow": "fold"},
                ],
                [[o.name, o.method, o.path, o.summary] for o in operations],
            )

        emit(ctx, data, table)
        return 0

    return run
