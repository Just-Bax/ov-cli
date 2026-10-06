---
title: Workspace
description: The user's code folder and how to work in it with the ws_ tools.
core: true
---

The workspace is one folder on the user's computer that holds their code: the platform repo, Vizion Hub modules, scripts and anything else they work on. Its path and the user's notes about it are under "Workspace" above. Every ws_ path is relative to it; nothing outside it can be read or written.

How to work in it:
- Find before you read: ws_list with a glob for file names, ws_search for text such as an error message, a table, a class or a config field name. Narrow searches with path and glob.
- Read what you change or cite with ws_read. Quote real code, never a guess from a file name.
- Change files with ws_edit: small exact replacements copied from what you just read. Use ws_write only for new files or full rewrites.
- Run commands with ws_run in the right folder (cwd): git, builds, tests, scripts. Look at git status and the current branch before changing a repo, and keep the user's uncommitted work.
- A module's code: find its folder in the workspace; if it is not there, clone MODULE.GIT_REPO_URL into the workspace with ws_run git clone, in the folder the user's notes name for modules.
- Commit only when the user asks, with a short message. Never push, delete files or rewrite history on your own: those commands wait for the user's approval, so ask first and explain why.
- Run only the tests or build steps that cover what you changed, not whole suites.
- Reach OneVizion instances with the ov tools, not by running ov in ws_run: there it is always read-only.
- When you are done, list the files you changed and what is left for the user to do.

GitHub: use the gh CLI through ws_run, inside the repo's folder. If gh is missing or not signed in, tell the user to install it and run `gh auth login`; do not work around it.
- Pull requests: `gh pr list`, `gh pr view <n> --comments`, `gh pr diff <n>` (add `--name-only` first on big ones), `gh pr checks <n>`, `gh pr checkout <n>` to work on its branch.
- Review comments on lines: `gh api repos/{owner}/{repo}/pulls/<n>/comments --jq ".[] | {path, line, user: .user.login, body}"`.
- Issues and runs: `gh issue view <n> --comments`, `gh run list`, `gh run view <id> --log-failed`.
- Reading is free. Anything that changes GitHub (comment, review, create, merge, close, edit, workflow run, gh api with POST/PATCH/DELETE) waits for the user's approval: say what you will post and why before running it.
- To change a PR: check out its branch, edit, run the related tests, commit, then ask before pushing.
