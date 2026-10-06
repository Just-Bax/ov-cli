from __future__ import annotations

from urllib.parse import urlsplit

from .. import session as session_store
from ..paths import slugify, spec_dir
from . import datadog, graph, pagerduty


def forget(alias: str, base_url: str) -> None:
    graph.graph_file(alias).unlink(missing_ok=True)
    datadog.forget(alias)

    if any(s.base_url == base_url for s in session_store.listed().values()):
        return

    for path in spec_dir().glob(f"{slugify(base_url)}.*.json"):
        path.unlink()
    pagerduty.forget_host(urlsplit(base_url).netloc)


def prune() -> None:
    known = set(session_store.listed())
    graphs = {path.stem for path in graph.graph_file("x").parent.glob("*.json")}
    known_slugs = {slugify(alias) for alias in known}

    for stem in graphs - known_slugs:
        graph.graph_file(stem).unlink()

    for alias in set(datadog.load_state().get("matches", {})) - known:
        datadog.forget(alias)
