from __future__ import annotations

import json
from typing import Any

from .fixture_files import read_fixture

SIGNATURE = (
    "public com.onevizion.vo.api.v3.UserJsonModel "
    "com.onevizion.web.controller.api.v3.UserJsonApiControllerV3.{method}({args})"
)

OPENAPI: dict[str, Any] = json.loads(read_fixture("openapi.json"))


def signature(method: str, args: str = "java.lang.Long") -> str:
    return SIGNATURE.format(method=method, args=args)
