from __future__ import annotations

from ov.agent.engine import state


def test_object_mentions_link_only_ids_the_agent_saw():
    from ov.agent.engine.links import links_for, seen_ids

    s = state.empty_state({"id": "r1", "status": "done"}, {"prompt": "hi"})
    s["tools"] = [
        {"id": "t1", "name": "ov_sql", "label": "SQL", "status": "ok", "output": "RULE_ID 100026539 PKG 12513"}
    ]
    text = (
        "Rule 100026539 runs slow, rule 999999 is a guess, and `rule 100026539` in code stays. "
        "See [PKG_KAFKA](https://dev-lumen.onevizion.com/admin/dbpackage/Form.do?id=12513) and "
        "[PKG_RULEATOR](https://dev-lumen.onevizion.com/admin/dbpackage/Form.do?id=4444). DB package 12513 too."
    )
    linked = links_for(text, "https://dev-lumen.onevizion.com", seen_ids(s))
    assert linked["mentions"] == [
        {"text": "Rule 100026539", "url": "https://dev-lumen.onevizion.com/admin/rules/Form.do?id=100026539"},
        {"text": "DB package 12513", "url": "https://dev-lumen.onevizion.com/admin/dbpackage/Form.do?id=12513"},
    ]
    assert linked["unverified"] == ["https://dev-lumen.onevizion.com/admin/dbpackage/Form.do?id=4444"]
