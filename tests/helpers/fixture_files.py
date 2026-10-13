from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")
