---
title: GitHub
description: Read before cloning or reading a module or project repository with github_clone.
---

github_clone clones a repository, or pulls it if it is already cloned, and returns its file list. It uses this computer's git and its credentials, so private repos work only if this computer can already reach them; if the clone is refused, say so and ask the user for access instead of guessing at the code.

- Vizion Hub modules: MODULE.GIT_REPO_URL holds the repo. Clone it, then read the module entry point, its settings handling and the code path named in the error.
- Match the code to what is deployed: compare MODULE.VERSION with the repo's tags or recent commits before blaming a line that may have changed since.
- After cloning, search and read the repo with source_search and source_read as "repo:<name>".
