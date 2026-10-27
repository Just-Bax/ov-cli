from __future__ import annotations

import subprocess

import pytest

from ov.core import update
from ov.core.errors import OvError


def test_a_tool_install_upgrades_its_environment_without_touching_the_launcher():
    found = update.Plan(update.Install(None, "abc", uv_tool=True), "abc", "def", [], True)
    command = update.install_command(found)
    assert command[:5] == ["uv", "pip", "install", "--python", update.sys.executable]
    assert command[5:] == ["--reinstall-package", "ov-cli", f"ov-cli @ git+{update.REPO_URL}@{update.BRANCH}"]


def test_a_pip_checkout_reinstalls_editable(tmp_path):
    found = update.Plan(update.Install(tmp_path, "abc", uv_tool=False), "abc", "abc", [], True)
    assert update.install_command(found)[-2:] == ["--editable", str(tmp_path)]


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


def test_the_install_runs_in_the_foreground_and_stops_on_failure(monkeypatch):
    calls = []

    def fake_run(command, **_):
        calls.append(command)
        return subprocess.CompletedProcess(command, fake_run.code)

    monkeypatch.setattr(update.subprocess, "run", fake_run)
    found = update.Plan(update.Install(None, "abc", uv_tool=False), "abc", "def", [], True)
    fake_run.code = 0
    update.reinstall(found)
    assert calls == [update.install_command(found)]

    fake_run.code = 2
    with pytest.raises(OvError, match="exited with 2"):
        update.reinstall(found)


def test_an_editable_install_checks_the_dependencies_of_its_checkout(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["httpx>=0.28", "surely-not-installed-pkg>=1"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(update, "_direct_url", lambda: {"url": tmp_path.as_uri(), "dir_info": {"editable": True}})
    assert update.missing_dependencies() == ["surely-not-installed-pkg"]
