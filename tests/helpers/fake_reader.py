from __future__ import annotations

import re

from ov.agent.engine.cancel import Cancel
from ov.agent.instances import explorer

PACKAGE_BODY = "".join(f"-- line {i:05d}\n" for i in range(2500))


class FakeReader:
    alias = "acme"

    def __init__(self, clobs: dict[str, str]) -> None:
        self.cancel = Cancel()
        self.clobs = clobs
        self.queries: list[str] = []

    def page(self, sql: str, offset: int, size: int) -> list[dict[str, object]]:
        self.queries.append(sql)
        if "process" in sql:
            return [{"TS": "2026-10-01 10:00", "STATUS": "Error", "RUNTIME": 3, "MESSAGE": "ORA-1"}]

        row: dict[str, object] = {}
        for match in re.finditer(r"dbms_lob\.getlength\((\w+)\) n", sql):
            row["N"] = len(self.clobs.get(match.group(1), ""))
        for match in re.finditer(r"dbms_lob\.substr\((\w+), (\d+), (\d+)\) (c\d+)", sql):
            column, size_, start, alias = match.groups()
            text = self.clobs.get(column, "")
            row[alias.upper()] = text[int(start) - 1 : int(start) - 1 + int(size_)] or None
        return [row]


def install_fake_reader(monkeypatch):
    fake = FakeReader(
        {
            "db_package_body": PACKAGE_BODY,
            "db_package_spec": "package spec",
            "sql_text": "begin\n  select value into v from t where id = 4242;\nend;",
        }
    )

    monkeypatch.setattr(explorer, "_reader", lambda alias: fake)
    explorer.forget("acme")

    yield fake

    explorer.forget("acme")
