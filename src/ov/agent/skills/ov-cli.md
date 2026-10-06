---
title: OV CLI
description: The OV tools: ov, ov_sql, ov_export, ov_search, ov_map and ov_case on signed-in instances.
core: true
---

The OV tools work on signed-in OneVizion instances:

- `ov`: any ov command - API calls, schema discovery, component export, chats, files.
- `ov_sql`: a read-only SELECT through the platform's Test SQL endpoint.
- `ov_export`: the full definition and code of components (DB packages, rules, imports, reports and more) by id, saved to workspace files.
- `ov_search`: trackor search with conditions.
- `ov_map`: what an object is linked to, from the Instance map. Start here before reading code.
- `ov_case`: a whole support case from trackor.onevizion.com, with chat and attachments.

Every instance is reached through the `ov` tool. Pass arguments as a list, starting with the command and without the leading `ov`; pass the instance alias or host as `instance` and the tool adds `-i`. Calls are read-only unless the user allowed changes for this run.

Discover before guessing:

- `api list <word>`: search every API operation, e.g. `api list rule`, `api list import`, `api list module`.
- `api show <ref>`: parameters of one operation. `api schema <ref>`: its request body shape.
- `request GET <path> -q k=v`: call any API path directly (paths are relative to /api).

Most useful calls:

- Platform version: `request GET /v3/server_info`.
- Trackor data: `request GET /v3/trackor_types/<TYPE>/trackors -q fields=A,B -q FIELD=value` (a field filter is a LIKE match; check exact values yourself). The record key is `XITOR_KEY` in filters and comes back as `TRACKOR_KEY`.
- Field list of a trackor type: `request GET /v3/trackor_types/<TYPE>`.
- One trackor by its TRACKOR_ID (a long number, not the key): `request GET /v3/trackors/<TRACKOR_ID> -q fields=A,B`.
- Search with conditions: the ov_search tool (it sends the text/plain body for you). Operators: equal, not_equal, greater, less, is_null, is_not_null, within, and/or with parentheses. Values and dates in double quotes, dates as "YYYY-MM-DD" or "YYYY-MM-DDTHH:mm:ss".
- SQL: the ov_sql tool only (SELECT only, max 1000 rows). Needs the Test SQL privilege on that instance.
- Code and full definition of a component: the ov_export tool with its type and ids. It saves each long field (a package body, a rule's SQL) to a workspace file and tells you the line count; read it with read_file and line ranges. Always use it for DB package bodies and long rule SQL instead of reading CLOBs in pieces with ov_sql: one call instead of dozens, and it works without the Test SQL privilege. Use ov_sql to find ids and for small columns.
- Vizion Hub module runs and logs: `api list module` (module-runs, module-logs).
- Chats on a trackor: `request GET /v3/chats -q trackor_id=<id>`, then `request GET /v3/chats/<chat_id>/messages`.
- Files: `request GET "/../efiles/EFileGetBlobFromDb.do?id=<blob_id>" --out <name>`; the file lands in this run's workspace, open it with read_file.

Errors carry an exit code: 3 the session expired (the app asks the user to sign in and retries; just continue), 4 no such operation or record, 5 an API error (read the message; OneVizion reports missing field privileges as HTTP 500), 6 a missing privilege, 7 a write blocked because changes are off.

Files you read or write with `--out`, `-d @file` or `--file` live in this run's own folder, not in the code workspace; open them with read_file. Session commands (login, logout, use, config, setup) are not available to you.
