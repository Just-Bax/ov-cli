from __future__ import annotations

import itertools

from ov.agent.storage import db

_ids = itertools.count(1)


class RunError(Exception):
    pass


def uid(prefix: str) -> str:
    return f"{prefix}_{db.now_ms()}_{next(_ids)}"
