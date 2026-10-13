from __future__ import annotations

import json

from ov.cli.main import main


def run(capsys, *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def payload(capsys, *argv: str):
    code, out = run(capsys, *argv)
    return code, json.loads(out)
