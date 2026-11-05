from __future__ import annotations

from ov.agent.engine import state
from ov.agent.engine.links import links_for, seen_ids

DEV = "https://dev-lumen.onevizion.com"
PROD = "https://lumen.onevizion.com"
URLS = {"dev-lumen": DEV, "lumen": PROD}


def _state(tools: list[dict], users: list[str] = ()) -> dict:
    s = state.empty_state({"id": "r1", "status": "done"}, {"prompt": "hi"})
    s["tools"] = tools
    s["chat"] = [{"id": f"u{i}", "role": "user", "text": text} for i, text in enumerate(users)]
    s["items"] = [{"kind": "tool", "id": t["id"]} for t in tools]
    s["items"] += [{"kind": "user", "id": f"u{i}"} for i in range(len(users))]
    return s


def test_object_mentions_link_only_ids_the_agent_saw():
    tools = [{"id": "t1", "name": "ov_sql", "label": "SQL", "status": "ok", "output": "RULE_ID 100026539 PKG 12513"}]
    text = (
        "Rule 100026539 runs slow, rule 999999 is a guess, and `rule 100026539` in code stays. "
        f"See [PKG_KAFKA]({DEV}/admin/dbpackage/Form.do?id=12513) and "
        f"[PKG_RULEATOR]({DEV}/admin/dbpackage/Form.do?id=4444). DB package 12513 too."
    )

    linked = links_for(text, seen_ids(_state(tools), "dev-lumen"), URLS)

    assert linked["mentions"] == [
        {"text": "Rule 100026539", "url": f"{DEV}/admin/rules/Form.do?id=100026539"},
        {"text": "DB package 12513", "url": f"{DEV}/admin/dbpackage/Form.do?id=12513"},
    ]
    assert linked["unverified"] == [f"{DEV}/admin/dbpackage/Form.do?id=4444"]


def test_mentions_link_to_the_instance_the_agent_worked_on_not_the_thread_instance():
    tools = [
        {"id": "t1", "name": "ov_sql", "input": '{"instance": "lumen", "query": "q"}', "output": "100024483"},
        {"id": "t2", "name": "ov_import", "input": '{"instance": "dev-lumen", "file": "rule_100026030.xml"}'},
        {"id": "t3", "name": "ws_write", "input": '{"path": "rule_100026250.txt"}'},
    ]

    seen = seen_ids(_state(tools, ["what about rule 100027000?"]), "lumen")
    linked = links_for("Rule 100024483, rule 100026030, rule 100026250 and rule 100027000.", seen, URLS)

    assert [m["url"] for m in linked["mentions"]] == [
        f"{PROD}/admin/rules/Form.do?id=100024483",
        f"{DEV}/admin/rules/Form.do?id=100026030",
        f"{DEV}/admin/rules/Form.do?id=100026250",
        f"{DEV}/admin/rules/Form.do?id=100027000",
    ]


def test_mentions_stay_plain_without_a_known_instance():
    tools = [{"id": "t1", "name": "ws_read", "input": '{"path": "a.txt"}', "output": "rule 100024483"}]
    assert links_for("Rule 100024483.", seen_ids(_state(tools), ""), URLS)["mentions"] == []
