from __future__ import annotations

import subprocess

import pytest

from ov.core import update
from ov.core.errors import OvError


def test_a_tool_install_reinstalls_from_git():
    found = update.Plan(update.Install(None, "abc", uv_tool=True), "abc", "def", [], True)
    command = update.install_command(found)
    assert command[:4] == ["uv", "tool", "install", "--force"]
    assert command[-1] == f"ov-cli @ git+{update.REPO_URL}@{update.BRANCH}"


def test_missing_packages_stop_the_agent_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(update, "missing_dependencies", lambda: ["sqlalchemy", "alembic"])
    with pytest.raises(OvError, match=r"sqlalchemy, alembic.*ov update"):
        update.require_dependencies()


def test_installed_dependencies_are_all_present():
    assert update.missing_dependencies() == []


def test_the_database_upgrade_runs_in_the_new_code_and_waits_for_a_running_agent(monkeypatch):
    from ov.core.errors import EXIT_IN_USE

    calls = []

    def fake_run(command, **_):
        calls.append(command)
        return subprocess.CompletedProcess(command, fake_run.code, "", "busy")

    monkeypatch.setattr(update.subprocess, "run", fake_run)
    fake_run.code = 0
    assert update.migrate() is True
    assert calls[-1][1:] == ["-m", "ov", "agent", "--migrate"]

    fake_run.code = EXIT_IN_USE
    assert update.migrate() is False

    fake_run.code = 1
    with pytest.raises(OvError, match="busy"):
        update.migrate()


def test_the_windows_reinstall_upgrades_the_database_after_installing(monkeypatch):
    started = []
    monkeypatch.setattr(update.sys, "platform", "win32")
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **_: started.append(args))
    for flag in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        monkeypatch.setattr(update.subprocess, flag, 0, raising=False)

    assert update.reinstall(["uv", "tool", "install"]) is True
    script = started[0][-1]
    assert script.index("'uv', 'tool', 'install'") < script.index("'agent', '--migrate'")


def test_an_editable_install_checks_the_dependencies_of_its_checkout(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["httpx>=0.28", "surely-not-installed-pkg>=1"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(update, "_direct_url", lambda: {"url": tmp_path.as_uri(), "dir_info": {"editable": True}})
    assert update.missing_dependencies() == ["surely-not-installed-pkg"]
