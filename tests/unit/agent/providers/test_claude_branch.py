from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from claude_agent_sdk import get_session_messages, project_key_for_directory

from ov.agent.integrations.claude import ClaudeError
from ov.agent.providers import claude_session


def _transcript(home: Path, cwd: Path, turns: int) -> tuple[str, list[str]]:
    session, ids = str(uuid.uuid4()), [str(uuid.uuid4()) for _ in range(turns)]
    folder = home / "projects" / project_key_for_directory(cwd)
    folder.mkdir(parents=True)

    lines, previous = [], None
    for index, message_id in enumerate(ids):
        role = "user" if index % 2 == 0 else "assistant"
        content = f"m{index}" if role == "user" else [{"type": "text", "text": f"m{index}"}]
        lines.append(
            {
                "type": role,
                "uuid": message_id,
                "parentUuid": previous,
                "sessionId": session,
                "cwd": str(cwd),
                "timestamp": "2026-11-05T00:00:00Z",
                "isSidechain": False,
                "message": {"role": role, "content": content},
            }
        )
        previous = message_id
    (folder / f"{session}.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return session, ids


def test_claude_fork_moves_the_transcript_to_the_branch(tmp_path, monkeypatch):
    home, parent, child = tmp_path / "c", tmp_path / "p", tmp_path / "k"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    session, ids = _transcript(home, parent, 4)

    forked = claude_session.fork_into(session, ids[1], child)

    moved = home / "projects" / project_key_for_directory(child) / f"{forked}.jsonl"
    assert moved.is_file()
    assert not (home / "projects" / project_key_for_directory(parent) / f"{forked}.jsonl").exists()
    assert [m.type for m in get_session_messages(forked, directory=str(child))] == ["user", "assistant"]
    assert len(get_session_messages(session, directory=str(parent))) == 4


def test_claude_fork_refuses_a_point_or_transcript_it_cannot_find(tmp_path, monkeypatch):
    home = tmp_path / "c"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    session, _ = _transcript(home, tmp_path / "p", 2)

    with pytest.raises(ClaudeError, match="no longer has that point"):
        claude_session.fork_into(session, str(uuid.uuid4()), tmp_path / "k")
    with pytest.raises(ClaudeError, match="is missing"):
        claude_session.fork_into(str(uuid.uuid4()), str(uuid.uuid4()), tmp_path / "k")


def test_a_branch_point_uses_the_anchor_of_the_message_it_starts_before():
    thread = SimpleNamespace(state={"session": {"id": "s2", "turns": {"u_two": {"id": "s1", "before": "m3"}}}})

    assert claude_session.branch_anchor(thread, "u_two") == ("s1", "m3")
    with pytest.raises(ClaudeError, match="no saved point"):
        claude_session.branch_anchor(thread, "u_three")


def test_the_latest_branch_point_is_found_wherever_the_transcript_is(tmp_path, monkeypatch):
    home = tmp_path / "c"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    session, ids = _transcript(home, tmp_path / "p", 4)

    moved = SimpleNamespace(state={"session": {"id": session, "turns": {}}}, work_dir=tmp_path / "elsewhere")
    assert claude_session.branch_anchor(moved, None) == (session, ids[-1])

    lost = SimpleNamespace(state={"session": {"id": str(uuid.uuid4()), "turns": {}}}, work_dir=tmp_path)
    with pytest.raises(ClaudeError, match="is missing"):
        claude_session.branch_anchor(lost, None)

    fresh = SimpleNamespace(state={"session": {"id": None, "turns": {}}}, work_dir=tmp_path)
    assert claude_session.branch_anchor(fresh, None) == (None, None)
