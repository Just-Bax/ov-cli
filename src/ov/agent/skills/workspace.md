---
title: Workspace
description: The user's code folder, the ws_ tools, what needs changes allowed (Ask first or Auto, not Read-only), and Vizion Hub module work.
core: true
---

The workspace is one folder on the user's computer with their code: the platform repo, Vizion Hub modules, scripts. Its path and the user's notes are under "Workspace" above. Every ws_ path is relative to it.

## Reading

- Find before you read: ws_list with a glob for file names, ws_search for text such as an error message, a table, a class or a field name. Narrow with path and glob.
- Quote real code from ws_read, never a guess from a file name.
- Reading never needs permission.

## Changing

- ws_edit and ws_write need changes allowed. Agree the plan first (see Working Style), then make small exact edits copied from what you just read; ws_write only for new files or full rewrites.
- Every ws_run command is judged before it runs. Commands that only read run at once. Commands that change anything here (commits, branches, installs, builds, tests) need changes allowed. Pushes, pull request actions, remote writes, deletes, unknown scripts and paths outside the workspace also wait for the user's approval (in Auto only when risky). If a command is refused, tell the user what you would run and why; do not rephrase it to get around the check.
- Look at git status and the branch before changing a repo, and keep the user's uncommitted work.
- Run only the tests or build steps that cover what you changed.
- When done, list the files you changed and what is left for the user.
- Reach OneVizion instances with the ov tools, not by running ov in ws_run (there it is always read-only).

## GitHub

Use the gh CLI through ws_run inside the repo's folder. If gh is missing or not signed in, tell the user to install it and run `gh auth login`.
- Read: `gh pr list`, `gh pr view <n> --comments`, `gh pr diff <n>` (`--name-only` first on big ones), `gh pr checks <n>`, `gh issue view <n> --comments`, `gh run view <id> --log-failed`, `gh api repos/{owner}/{repo}/pulls/<n>/comments --jq ".[] | {path, line, user: .user.login, body}"`.
- Anything that writes to GitHub waits for approval: say what you will post and why first.

## Vizion Hub modules

- A module's code: find its folder in the workspace; if it is missing, clone MODULE.GIT_REPO_URL into the folder the user's notes name for modules (a clone changes the workspace, so it needs changes allowed (Ask first or Auto, not Read-only)).
- New modules start from the module template repository. A local OneVizion server can install a module straight from a local repo with a Repository URL like `file:///C:/path/to/repo`, using the "Install manually" option; changes must be committed locally first.
- To rerun a failed install step with a fixed .sql, .csv or .xml file, edit the copy in the web app's working directory for that module id, then copy the fix back to the repo.
- Module XMLs carry only languages 0 (internal), 1 (English) and 98 (label ids). Sample data imports must use the Insert/Update action.
