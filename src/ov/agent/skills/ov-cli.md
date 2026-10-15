---
title: OV CLI
description: The agent's tools and integrations, when to use each, and how to query instances without loading them.
core: true
---

## What you have

- `ov`: any ov command on a signed-in instance: API calls, schema discovery, chats, files. Pass arguments as a list without the leading `ov`, and the instance as `instance`.
- `ov_sql`: one read-only SELECT through the platform's Test SQL. Needs the Test SQL privilege.
- `ov_map`: what an object is linked to (rules, fields, imports, packages), from a cached map. Start here before reading code.
- `ov_export`: the full definition and code of components by id, saved to files; read them with run_read and line ranges. Use it for package bodies and long rule SQL instead of reading CLOBs with SQL.
- `ov_import`: import a component export into an instance. Always dry run first; a real import needs Allow changes and the user's approval.
- `ov_search`: trackor search with conditions. `ov_case`: a whole support case from trackor.onevizion.com.
- Workspace (ws_ tools): the user's code folder, when one is set. Datadog (dd_ tools) and PagerDuty (pd_ tools): server and incident views, when connected. Read their skills before using them.
- `run_ask` for decisions only the user can make, `run_report` for case findings, `ov_propose` for code changes.

## SQL that does not hurt the instance

Test SQL cannot be cancelled: a query you give up on keeps running in Oracle and slows the instance for everyone. The platform also counts the full result of every query before returning the first rows, so a small limit does not make a big query cheap.

- Filter big tables (see OneVizion Basics) by key or date before anything else. One field on all trackors can be millions of rows.
- To look at data, sample inside the query: `... fetch first 20 rows only`.
- Never count or group a whole value table or a whole field to "get a feel". Count with the same selective filter you will use next, or skip the count.
- Prefer the API or ov_search for one trackor's values, and ov_map or metadata tables for configuration questions.
- A query that took more than about 30 seconds tells you the table is big: do not run more like it; narrow the next one by key and a shorter window.
- If a query may take over a minute, run it in the background and keep working. If it times out, do not rerun it as is: narrow it.

## Calls

- Discover before guessing: `api list <word>`, `api show <ref>`, `api schema <ref>`; any path with `request GET <path> -q k=v` (paths relative to /api).
- Platform version: `request GET /v3/server_info`.
- Trackor data: `request GET /v3/trackor_types/<TYPE>/trackors -q fields=A,B -q FIELD=value` (a field filter is a LIKE match). One trackor: `request GET /v3/trackors/<TRACKOR_ID> -q fields=A,B`. Field list: `request GET /v3/trackor_types/<TYPE>`.
- ov_search operators: equal, not_equal, greater, less, is_null, is_not_null, within, and/or with parentheses; values and dates in double quotes, dates as "YYYY-MM-DD".
- Module runs and logs: `api list module`. Chats: `request GET /v3/chats -q trackor_id=<id>`, then `/v3/chats/<chat_id>/messages`.
- Files: `request GET "/../efiles/EFileGetBlobFromDb.do?id=<blob_id>" --out <name>`, then run_read.
- Exit codes: 3 session expired (the user is asked to sign in; continue), 4 no such operation or record, 5 API error (missing field privileges show as HTTP 500), 6 missing privilege, 7 change blocked because Allow changes is off.

Files written with `--out`, `-d @file` or `--file` live in the run folder; open them with run_read. Session commands (login, logout, use, config, setup) are not available.
