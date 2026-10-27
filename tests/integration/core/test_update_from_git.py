from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ov.core import update
from ov.core.errors import OvError


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "master", cwd=origin)
    git("config", "user.email", "t@example.test", cwd=origin)
    git("config", "user.name", "T", cwd=origin)
    (origin / "pyproject.toml").write_text("v1", encoding="utf-8")
    git("add", ".", cwd=origin)
    git("commit", "-q", "-m", "first", cwd=origin)

    clone = tmp_path / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)

    (origin / "app.py").write_text("x = 1", encoding="utf-8")
    git("add", ".", cwd=origin)
    git("commit", "-q", "-m", "second", cwd=origin)
    return origin, clone


def test_a_checkout_is_pulled_fast_forward(repos, monkeypatch):
    origin, clone = repos
    monkeypatch.setattr(
        update, "detect", lambda: update.Install(clone, git("rev-parse", "HEAD", cwd=clone), uv_tool=True)
    )

    found = update.plan()
    assert found.latest == git("rev-parse", "HEAD", cwd=origin)
    assert [c.split(" ", 1)[1] for c in found.commits] == ["second"]
    assert not found.reinstall

    update.pull(found)
    assert (clone / "app.py").exists()
    assert update.plan().commits == []


def test_dependency_changes_reinstall_the_tool(repos, monkeypatch):
    origin, clone = repos
    (origin / "pyproject.toml").write_text("v2", encoding="utf-8")
    git("commit", "-qam", "deps", cwd=origin)
    install = update.Install(clone, git("rev-parse", "HEAD", cwd=clone), uv_tool=True)
    monkeypatch.setattr(update, "detect", lambda: install)

    found = update.plan()
    assert found.reinstall
    assert update.install_command(found)[:3] == ["uv", "tool", "upgrade"]


def test_local_changes_that_conflict_stop_the_pull(repos, monkeypatch):
    _, clone = repos
    (clone / "app.py").write_text("mine", encoding="utf-8")
    install = update.Install(clone, git("rev-parse", "HEAD", cwd=clone), uv_tool=False)
    monkeypatch.setattr(update, "detect", lambda: install)

    with pytest.raises(OvError, match="git merge"):
        update.pull(update.plan())
    assert (clone / "app.py").read_text(encoding="utf-8") == "mine"


def test_missing_packages_reinstall_even_when_the_code_is_current(repos, monkeypatch):
    _, clone = repos
    head = git("rev-parse", "HEAD", cwd=clone)
    git("pull", "-q", cwd=clone)
    current = git("rev-parse", "HEAD", cwd=clone)
    assert head != current
    monkeypatch.setattr(update, "detect", lambda: update.Install(clone, current, uv_tool=True))
    monkeypatch.setattr(update, "missing_dependencies", lambda: ["sqlalchemy"])

    found = update.plan()
    assert found.current == found.latest
    assert found.reinstall
