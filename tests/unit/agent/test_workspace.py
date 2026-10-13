from __future__ import annotations

import pytest


def test_the_workspace_reads_searches_and_edits_inside_its_folder(workspace, tmp_path):
    from ov.agent import workspace as project

    assert "module/" in project.listing("", "")
    assert project.listing("", "*.py") == "module/main.py"
    assert project.search("RULE_ID", "", "", False).startswith("module/main.py:2:")
    assert "2: RULE_ID = 1" in project.read("module/main.py", 1, None)

    assert project.edit("module/main.py", "RULE_ID = 1", "RULE_ID = 2", False).startswith("Edited")
    assert "RULE_ID = 2" in project.text_of("module/main.py")
    project.write("module/new/readme.md", "hi")
    assert (workspace / "module" / "new" / "readme.md").read_text(encoding="utf-8") == "hi"

    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    for outside in ("../secret.txt", str(tmp_path / "secret.txt")):
        with pytest.raises(project.ProjectError, match="outside the workspace"):
            project.read(outside, 1, None)


def test_risky_commands_need_approval(workspace, tmp_path):
    from ov.agent import workspace as project

    base = project.root()
    assert project.risks("git status && pytest tests/x.py", base) == []
    assert project.risks("git push origin main", base) == ["pushes to a remote"]
    assert project.risks("Remove-Item -Recurse build", base) == ["deletes files"]
    assert project.risks("gh pr view 12 --comments && gh pr diff 12", base) == []
    assert project.risks("gh pr comment 12 -b ok", base) == ["changes something on GitHub"]
    assert project.risks("gh api repos/a/b/pulls/1/comments", base) == []
    assert project.risks("gh api -X POST repos/a/b/issues/1/comments -f body=x", base) == [
        "changes something on GitHub"
    ]
    assert project.risks(f"type {tmp_path / 'secret.txt'}", base)[0].startswith("touches")
    assert project.risks(f"type {workspace / 'module' / 'main.py'}", base) == []


def test_ws_search_takes_a_file_path_and_brace_globs(workspace):
    from ov.agent import workspace as project

    root = project.root()
    (root / "a.sql").write_text("create index i1 on xitor (x);\n")
    (root / "b.sql").write_text("create index i2 on cv (y);\n")
    (root / "c.txt").write_text("create index i3;\n")
    assert project.expand_glob("{a,b}.sql") == ["a.sql", "b.sql"]
    found = project.search("create index", "", "{a,b}.sql", False)
    assert "a.sql:1" in found and "b.sql:1" in found and "c.txt" not in found
    assert project.search("i2", "b.sql", "", False).startswith("b.sql:1:")


def test_commands_leaving_the_workspace_need_approval(workspace):
    from ov.agent import workspace as project

    sub = project.root() / "module"
    sub.mkdir(exist_ok=True)
    assert project.risks("Set-Content ..\\..\\x.txt hi", sub) == ["climbs out of the workspace"]
    assert project.risks("cat ../readme.md", sub) == []
    assert project.risks("Get-Content $env:USERPROFILE\\.ssh\\id_rsa", project.root()) == [
        "uses a path from an environment variable"
    ]
