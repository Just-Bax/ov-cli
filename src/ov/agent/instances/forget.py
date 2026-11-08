from __future__ import annotations

from urllib.parse import urlsplit

from ov.agent.instances import graph
from ov.agent.integrations import datadog, pagerduty
from ov.core.paths import slugify, spec_dir
from ov.onevizion import session as session_store


def forget(alias: str, base_url: str) -> None:
    graph.graph_file(alias).unlink(missing_ok=True)
    graph.sources_file(alias).unlink(missing_ok=True)
    datadog.forget(alias)

    if any(s.base_url == base_url for s in session_store.listed().values()):
        return

    for path in spec_dir().glob(f"{slugify(base_url)}.*.json"):
        path.unlink()
    pagerduty.forget_host(urlsplit(base_url).netloc)


def prune() -> None:
    known = set(session_store.listed())
    known_slugs = {slugify(alias) for alias in known}
    for place in (graph.graph_file, graph.sources_file):
        for path in place("x").parent.glob("*.json"):
            if path.stem not in known_slugs:
                path.unlink()

    for alias in set(datadog.load_state().get("matches", {})) - known:
        datadog.forget(alias)
