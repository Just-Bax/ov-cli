---
title: Sources
description: Searching the code and docs the user configured, and cloned repos, with source_search and source_read.
---

Sources are folders on this computer the user added in Settings (for example the platform code or module checkouts), each with a description of what it holds; the list is in "Sources" above. A repo cloned with github_clone is a source too, named "repo:<name>".

- source_search runs git grep with an extended regex; narrow it with path (e.g. "db/ddl/*", "*.py") and ignore_case. Search for the exact error text, class, procedure or table name first, then widen.
- source_read reads a file (use start and end for long ones) or lists a folder (path ""). Read the code you cite; do not guess from a file name.
- Platform DDL lives under db/ddl in the platform source: tables in db/ddl/tables/<table>.sql, packages under db/ddl/packages. Check a column or package there before relying on it.
- Quote what you found with its path and line, e.g. "pkg_rule.sql line 412".
