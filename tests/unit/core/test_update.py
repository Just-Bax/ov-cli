from __future__ import annotations

import subprocess

import pytest

from ov.core import update
from ov.core.errors import OvError


def source_with(tmp_path, dependencies: list[str]):
    listed = ", ".join(f'"{d}"' for d in dependencies)
    (tmp_path / "pyproject.toml").write_text(f"[project]\ndependencies = [{listed}]\n", encoding="utf-8")
    return tmp_path


def installed_dependencies() -> list[str]:
    return [r for r in update.metadata.requires("ov-cli") if "extra ==" not in r]


def test_a_tool_install_reinstalls_only_ov_when_its_dependencies_are_unchanged(tmp_path):
    source = source_with(tmp_path, installed_dependencies())
    commands = update.source_commands(update.Install(None, "abc", uv_tool=True), source)
    uv = ["uv", "pip", "install", "--python", update.sys.executable]
    assert commands == [[*uv, "--no-deps", "--reinstall-package", "ov-cli", str(source)]]


def test_reordered_specifiers_are_not_a_dependency_change():
    reordered = ["playwright>=1.45.0,<1.63" if r.startswith("playwright") else r for r in installed_dependencies()]
    assert not update.dependencies_changed(reordered)


def test_changed_dependencies_are_installed_before_ov(tmp_path):
    wanted = [*installed_dependencies(), "surely-not-installed-pkg>=1"]
    source = source_with(tmp_path, wanted)
    commands = update.source_commands(update.Install(None, "abc", uv_tool=False), source)
    assert commands[0] == [update.sys.executable, "-m", "pip", "install", *wanted]
    assert commands[1][-3:] == ["--no-deps", "--force-reinstall", str(source)]


def test_an_install_from_the_source_cache_knows_its_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "source_root", lambda: tmp_path)
    info = {"url": (tmp_path / "3c974e6abc").as_uri(), "dir_info": {}}
    monkeypatch.setattr(update, "_direct_url", lambda: info)
    monkeypatch.setattr(update, "_uv_tool", lambda: True)
    assert update.detect().commit == "3c974e6abc"


def test_an_install_from_the_github_zip_updates_to_the_latest_commit(monkeypatch):
    info = {"url": "https://github.com/owner/ov-cli/archive/refs/heads/master.zip", "archive_info": {}}
    monkeypatch.setattr(update, "_direct_url", lambda: info)
    monkeypatch.setattr(update, "_uv_tool", lambda: True)
    monkeypatch.setattr(update, "_git", lambda args, cwd=None: "def456\trefs/heads/master")
    monkeypatch.setattr(update, "missing_dependencies", lambda: [])
    found = update.plan()
    assert (found.current, found.latest, found.reinstall) == ("", "def456", True)


def test_a_pip_checkout_reinstalls_editable(tmp_path):
    assert update.editable_command(update.Install(tmp_path, "abc", uv_tool=False))[-2:] == ["--editable", str(tmp_path)]


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


def test_the_install_runs_in_the_foreground_and_stops_on_failure(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **_):
        calls.append(command)
        return subprocess.CompletedProcess(command, fake_run.code)

    monkeypatch.setattr(update.subprocess, "run", fake_run)
    found = update.Plan(update.Install(tmp_path, "abc", uv_tool=False), "abc", "def", [], True)
    fake_run.code = 0
    update.reinstall(found)
    assert calls == [update.editable_command(found.install)]

    fake_run.code = 2
    with pytest.raises(OvError, match="exited with 2"):
        update.reinstall(found)


def test_an_editable_install_checks_the_dependencies_of_its_checkout(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["httpx>=0.28", "surely-not-installed-pkg>=1"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(update, "_direct_url", lambda: {"url": tmp_path.as_uri(), "dir_info": {"editable": True}})
    assert update.missing_dependencies() == ["surely-not-installed-pkg"]
