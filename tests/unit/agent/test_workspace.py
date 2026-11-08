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


def test_paths_outside_the_workspace_are_flagged(workspace, tmp_path):
    from ov.agent import workspace as project

    base = project.root()
    assert project.escapes("git status && pytest tests/x.py", base) == []
    assert project.escapes(f"type {tmp_path / 'secret.txt'}", base)[0].startswith("touches")
    assert project.escapes(f"type {workspace / 'module' / 'main.py'}", base) == []


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
    assert project.escapes("Set-Content ..\\..\\x.txt hi", sub) == ["climbs out of the workspace"]
    assert project.escapes("cat ../readme.md", sub) == []
    assert project.escapes("Get-Content $env:USERPROFILE\\.ssh\\id_rsa", project.root()) == [
        "uses a path from an environment variable"
    ]


def test_path_search_ranks_names_first_and_skips_ignored_files(workspace):
    import subprocess

    from ov.agent import workspace_paths

    root = workspace
    repo = root / "app"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "composer.ts").write_text("x", encoding="utf-8")
    (repo / "src" / "my_composer_helpers.ts").write_text("x", encoding="utf-8")
    (repo / "ignored.log").write_text("x", encoding="utf-8")
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    found = [row["path"] for row in workspace_paths.find("composer")]
    assert found[:2] == ["app/src/composer.ts", "app/src/my_composer_helpers.ts"]
    assert workspace_paths.find("ignored") == []
    assert {"path": "app/src", "dir": True} in workspace_paths.find("app/src")
    assert any(row["path"] == "module" and row["dir"] for row in workspace_paths.find(""))


def test_the_run_folder_is_not_outside_the_workspace(workspace, tmp_path):
    from ov.agent import workspace as project

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    command = f"Get-Content {run_dir / 'rules.xml'}"
    assert project.escapes(command, project.root())[0].startswith("touches")
    assert project.escapes(command, project.root(), (run_dir,)) == []


def test_scripts_a_command_runs_are_read_for_the_judge(workspace):
    from ov.agent import workspace as project

    (workspace / "build.ps1").write_text("Write-Output build", encoding="utf-8")
    command = "powershell -File build.ps1; python module/main.py; node missing.js"
    assert project.scripts_run(command, project.root()) == {
        "build.ps1": "Write-Output build",
        "module/main.py": "alpha\nRULE_ID = 1\n",
    }
