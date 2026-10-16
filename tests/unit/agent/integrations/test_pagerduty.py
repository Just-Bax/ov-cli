from __future__ import annotations

import json

import pytest
from helpers.fake_pagerduty import HOST, KEY, install_fake_pagerduty, link_pagerduty
from helpers.sessions import BASE_URL

from ov.agent.engine import prompt
from ov.agent.integrations import pagerduty
from ov.agent.storage.models import Access
from ov.agent.tools import TOOLS_BY_NAME, tool_specs
from ov.agent.tools.base import Approval, ToolError
from ov.core import credentials


@pytest.fixture
def fake(monkeypatch):
    return install_fake_pagerduty(monkeypatch)


@pytest.fixture
def linked(fake, logged_in):
    return link_pagerduty(fake)


class Ctx:
    def __init__(self, tmp_path, instance: str = "acme", write: bool = False, approve: str = "Approve") -> None:
        self.work_dir = tmp_path
        self.instance = instance
        self.write = write
        self.approve = approve
        self.asked: list[str] = []

    def can_write(self):
        return self.write

    def auto_approves(self):
        return False

    def full_access(self):
        return False

    def ask_approval(self, question, detail, reason=""):
        self.asked.append(question)
        return Approval(self.approve == "Approve", "")


def test_account_and_region_come_from_any_pagerduty_address():
    assert pagerduty.account_of("https://onevizion.pagerduty.com/incidents") == ("onevizion", "us")
    assert pagerduty.account_of("acme.eu.pagerduty.com") == ("acme", "eu")
    assert pagerduty.account_of("onevizion") == ("onevizion", "us")
    with pytest.raises(pagerduty.PagerDutyError):
        pagerduty.account_of("https://example.com/x")


def test_connect_checks_the_key_and_keeps_it_in_the_keyring(fake, ov_home):
    fake.denied = {"oncall"}
    status = pagerduty.connect("onevizion.pagerduty.com", f" {KEY} ")
    assert status["connected"] and status["user"] == "Bax" and status["keyLast4"] == "1234"
    assert status["permissions"] == {"incidents": True, "oncall": False}
    assert status["webUrl"] == "https://onevizion.pagerduty.com"
    assert credentials.get(pagerduty.CREDENTIAL_KEY) == {"api_key": KEY}
    assert KEY not in (ov_home / "agent" / "pagerduty.json").read_text(encoding="utf-8")
    assert all(r.url.host == "api.pagerduty.com" for r in fake.requests)


def test_a_bad_key_is_explained_and_not_stored(fake, ov_home):
    with pytest.raises(pagerduty.PagerDutyError, match="User API token"):
        pagerduty.connect("onevizion", "wrong")
    assert credentials.get(pagerduty.CREDENTIAL_KEY) is None and not pagerduty.connected()


def test_incidents_are_tied_to_instances_by_website_database_and_host(linked):
    rows = pagerduty.incidents(0, 1_791_108_000_000)
    mine = pagerduty.for_instance(rows, "acme")
    assert [r["number"] for r in mine] == [7, 6, 5, 3]
    assert pagerduty.load_state()["databases"] == {HOST: ["acmedb"]}
    assert [r["number"] for r in pagerduty.for_instance(rows[1:2], "acme")] == [6]


def test_a_tenant_sees_its_host_incidents(linked):
    from ov.onevizion import session as session_store
    from ov.onevizion.session import Session

    session_store.save(
        Session(
            base_url=BASE_URL,
            alias="acme/north",
            mode="session",
            bearer_token="T:S",
            expires_at=4102444800.0,
            tenant="North",
            tenant_id="9",
        )
    )
    rows = pagerduty.incidents(0, 1_791_108_000_000)
    assert len(pagerduty.for_instance(rows, "acme/north")) == 4


def test_tools_are_offered_only_when_connected(fake, logged_in):
    names = {s["function"]["name"] for s in tool_specs()}
    assert not {n for n in names if n.startswith("pd_")}
    assert "PagerDuty: not connected" in prompt.system_prompt(Access.READ, "")

    fake.denied = {"oncall"}
    pagerduty.connect("onevizion", KEY)
    names = {s["function"]["name"] for s in tool_specs()}
    assert {"pd_incidents", "pd_incident", "pd_directory"} <= names
    assert "pd_oncall" not in names and "pd_ack" not in names
    assert "pd_ack" in {s["function"]["name"] for s in tool_specs(write=True)}
    text = prompt.system_prompt(Access.READ, "")
    assert "- pagerduty: " in text
    assert "PagerDuty (incidents and on-call; changes only while allowed): pd_incidents" in text


def test_incident_tools(linked, tmp_path):
    ctx = Ctx(tmp_path)
    out = TOOLS_BY_NAME["pd_incidents"].handler({}, ctx)
    assert f"for {HOST}" in out and "#7 [triggered, high] Unhealthy Hosts" in out and "#4" not in out

    open_only = TOOLS_BY_NAME["pd_incidents"].handler({"statuses": ["triggered"]}, ctx)
    assert "#7" in open_only and "#6" not in open_only
    every = TOOLS_BY_NAME["pd_incidents"].handler({"all_instances": True}, ctx)
    assert "#4" in every
    found = TOOLS_BY_NAME["pd_incidents"].handler({"query": "acmedb"}, ctx)
    assert "#7" in found and "#5" not in found

    detail = TOOLS_BY_NAME["pd_incident"].handler({"incident": "https://onevizion.pagerduty.com/incidents/PINC7"}, ctx)
    assert detail.index("trigger:") < detail.index("acknowledge:")
    assert "[Datadog] JVM heap" in detail and "avg:jvm" in detail

    oncall = TOOLS_BY_NAME["pd_oncall"].handler({}, ctx)
    assert "level 1 Pat (policies PPOL1,PPOL2, Primary" in oncall and "level 2 Sam" in oncall
    everyone = TOOLS_BY_NAME["pd_oncall"].handler({}, Ctx(tmp_path, instance=""))
    assert "policies all" in everyone


def test_health_section(linked):
    report = pagerduty.health("acme", 0, 1_791_108_000_000, "24h")
    assert [i["number"] for i in report["open"]] == [7, 5]
    assert [i["number"] for i in report["incidents"]] == [7, 6, 5, 3]
    assert "text" not in report["open"][0]
    assert [o["user"] for o in report["oncall"]] == ["Pat"]
    assert not report["errors"]


def test_changes_need_allow_changes_and_approval(linked, tmp_path):
    ack = TOOLS_BY_NAME["pd_ack"].handler
    with pytest.raises(ToolError, match="changes are OFF"):
        ack({"incident": "7"}, Ctx(tmp_path))
    assert all(r.method == "GET" for r in linked.requests)

    with pytest.raises(ToolError, match="rejected"):
        ack({"incident": "PINC7"}, Ctx(tmp_path, write=True, approve="Reject"))
    assert all(r.method == "GET" for r in linked.requests)

    ctx = Ctx(tmp_path, write=True)
    assert "acknowledged" in ack({"incident": "PINC7"}, ctx)
    assert ctx.asked == ["Acknowledge PINC7 in PagerDuty?"]
    put = next(r for r in linked.requests if r.method == "PUT")
    assert json.loads(put.content) == {"incident": {"type": "incident_reference", "status": "acknowledged"}}

    TOOLS_BY_NAME["pd_note"].handler({"incident": "PINC7", "note": "Disk cleaned"}, ctx)
    note = next(r for r in linked.requests if r.method == "POST")
    assert note.url.path == "/incidents/PINC7/notes" and json.loads(note.content) == {
        "note": {"content": "Disk cleaned"}
    }


def test_reassign_finds_one_policy_by_name(linked, tmp_path):
    ctx = Ctx(tmp_path, write=True)
    TOOLS_BY_NAME["pd_reassign"].handler({"incident": "PINC7", "policy": "USA Support"}, ctx)
    body = json.loads(next(r for r in linked.requests if r.method == "PUT").content)
    assert body["incident"]["escalation_policy"] == {"id": "PUSA1", "type": "escalation_policy_reference"}
    with pytest.raises(ToolError, match="2 PagerDuty policy match"):
        TOOLS_BY_NAME["pd_reassign"].handler({"incident": "PINC7", "policy": "Support"}, ctx)

    TOOLS_BY_NAME["pd_reassign"].handler({"incident": "PINC7", "users": ["pat@example.test"]}, ctx)
    body = json.loads([r for r in linked.requests if r.method == "PUT"][-1].content)
    assert body["incident"]["assignments"] == [{"assignee": {"id": "PUSR1", "type": "user_reference"}}]


def test_a_read_only_token_is_explained(linked, tmp_path):
    linked.denied = {"read-only"}
    with pytest.raises(ToolError, match="read-only"):
        TOOLS_BY_NAME["pd_resolve"].handler({"incident": "PINC7"}, Ctx(tmp_path, write=True))
