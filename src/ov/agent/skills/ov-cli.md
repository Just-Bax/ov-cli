---
title: OV CLI
description: The agent's tools and integrations, when to use each, and how to query instances without loading them.
core: true
---

## What you have

- `ov`: any ov command on a signed-in instance: API calls, schema discovery, chats, files. Pass arguments as a list without the leading `ov`, and the instance as `instance`.
- `ov_sql`: one read-only SELECT through the platform's Test SQL. Needs the Test SQL privilege.
- `ov_map`: what an object is linked to (rules, fields, imports, packages), from a cached map. Start here before reading code. It is built with Test SQL, or from component exports when the account has no Test SQL.
- `ov_export`: the full definition and code of components by id, saved to files; read them with run_read and line ranges. Use it for package bodies and long rule SQL instead of reading CLOBs with SQL. Each code field is its own .txt file: compare two instances by diffing those files, not by parsing the XML.
- `ov_import`: import a component export into an instance. Always dry run first; a real import needs changes allowed and the user's approval unless the thread is on Auto.
- `ov_search`: trackor search with conditions. `ov_case`: a whole support case from trackor.onevizion.com.
- `ov_update`: change field values on many trackors at once. It shows every old and new value in a grid, asks for approval, writes through the API and reports failed rows. It can revert a finished change.
- `run_grid`: show records to the user as a sortable, filterable grid with links. Use it whenever the answer is a list.
- `ov_mcp` and `ov_ddl` (AI Enabled instances only, when listed under Tools): the instance's MCP server, and the platform's own DDL and package source.
- Workspace (ws_ tools): the user's code folder, when one is set. Datadog (dd_ tools) and PagerDuty (pd_ tools): server and incident views, when connected. Read their skills before using them.
- `run_ask` before working when a needed input is missing (several related questions in one call), `run_report` for case findings, `ov_propose` for code changes.

## Pick sources by what the account can use

Each signed-in instance in the prompt lists what this account can use there. Choose the source from that list before the first call, and say which privilege was missing when it limits the answer.

| Need | With Test SQL | Without Test SQL |
|---|---|---|
| What links to an object | ov_map | ov_map (built from exports) |
| Rule, import, report, package code | ov_export | ov_export |
| Platform tables, columns, UTIL signatures | all_tab_columns, all_source | ov_ddl (AI Enabled), else the onevizion-reference skill |
| Trackor data | ov_sql, ov_search, API | ov_search, `request GET /v3/trackor_types/<TYPE>/trackors`, `ov_mcp` trackors_search |
| Field names and types of a trackor type | config_field | `request GET /v3/trackor_types/<TYPE>` |
| Import, report, export runs | PROCESS and the run tables | `request GET /v3/imports/<import_id>/runs -q status=INTERRUPTED`, one run with `/v3/imports/runs/<process_id>`; reports with `/v3/reports/<report_id>/runs`. The lists have no paging or date filter: always filter by one import or report and a status, never list every run |
| Module runs and logs | MODULE_RUN, MODULE_LOG | `request GET /v3/modules/runs -q module_name=<name>`, `/v3/modules/runs/logs -q module_name=<name> -q process_id=<id> -q log_level=Error` |
| Rule queue, rule runs, audit log, error log | SQL | not readable without Test SQL; say so, and offer to open the grid in the browser |

When neither Test SQL nor component export is allowed, the instance is still useful through the API and the browser: trackor data, workplans, users, runs and logs. Never stop at "no privilege"; say what you can still check and check it.

## SQL that does not hurt the instance

Test SQL cannot be cancelled: a query you give up on keeps running in Oracle and slows the instance for everyone. The platform also counts the full result of every query before returning the first rows, so a small limit does not make a big query cheap.

- Filter big tables (see OneVizion Basics) by key or date before anything else. One field on all trackors can be millions of rows.
- To look at data, sample inside the query: `... fetch first 20 rows only`.
- Never count or group a whole value table or a whole field to "get a feel". Count with the same selective filter you will use next, or skip the count.
- Prefer the API or ov_search for one trackor's values, and ov_map or metadata tables for configuration questions.
- A query that took more than about 30 seconds tells you the table is big: do not run more like it; narrow the next one by key and a shorter window.
- If a query may take over a minute, run it in the background and keep working. If it times out, do not rerun it as is: narrow it.
- To wait for something to change (a job, an import, a queue), use run_wait with the query instead of sleep commands or repeated checks.
- Never guess a table or column name. Look it up in all_tab_columns first; when a query still fails on a name, the error lists the real columns.
- Test SQL parses queries itself and rejects some Oracle JSON syntax: `RETURNING <type>`, `NULL ON ERROR`, `ERROR ON ERROR`, `ON EMPTY` and `IS JSON`. Use plain `json_value(col, '$.path')` (it already returns null on errors) and wrap it in `to_number` or `to_date` instead of RETURNING.
- A failed query comes back as an answer with status FAILED, not an HTTP error; ov_sql shows the error message.

## Calls

- Discover before guessing: `api list <word>`, `api show <ref>`, `api schema <ref>`; any path with `request GET <path> -q k=v` (paths relative to /api).
- Platform version: `request GET /v3/server_info`. Your own privileges: `request GET /v3/privs -q security_group=<NAME>`.
- Trackor data: `request GET /v3/trackor_types/<TYPE>/trackors -q fields=A,B -q FIELD=value` (a field filter is a LIKE match). One trackor: `request GET /v3/trackors/<TRACKOR_ID> -q fields=A,B`. Field list: `request GET /v3/trackor_types/<TYPE>`. Trackor tree: `request GET /v3/trackor_tree`.
- TRACKOR_ID comes back on every record and must never be in fields: asking for it fails with "Can't find config field". TRACKOR_KEY must be asked for.
- Filter children by a parent with the parent's key: `-q PARENT_TYPE.TRACKOR_KEY=<key>`. A parent filter on TRACKOR_ID is silently ignored and returns every record.
- Parent fields use dot notation in fields: `fields=STORE.TRACKOR_KEY,STORE.CITY`.
- A trackor selector field holds the selected trackor's key (or another configured value), not its TRACKOR_ID; look the target up by key.
- Electronic file fields come back as `{data, file_name}`; read the file only when file_name is set: `request GET /v3/trackor/<TRACKOR_ID>/file/<FIELD> --out <name>`.
- Creating a trackor answers 201 with TRACKOR_ID and TRACKOR_KEY; updates answer 200.
- ov_search operators: equal, not_equal, greater, less, is_null, is_not_null, within, and/or with parentheses; values and dates in double quotes, dates as "yyyy-MM-ddTHH:mm:ss".
- Import, export and report runs: add `--wait` to the `api call` that starts one; it follows the run to the end and prints the final status (exit 1 if it failed). Use background for long ones.
- Module runs and logs: `api list module`. Chats: `request GET /v3/chats -q trackor_id=<id>`, then `/v3/chats/<chat_id>/messages`.
- Files: `request GET "/../efiles/EFileGetBlobFromDb.do?id=<blob_id>" --out <name>`, then run_read.
- Exit codes: 3 session expired (the user is asked to sign in; continue), 4 no such operation or record, 5 API error (missing field privileges show as HTTP 500), 6 missing privilege, 7 change blocked because the thread is Read-only.

Files written with `--out`, `-d @file` or `--file` live in the run folder; open them with run_read. Session commands (login, logout, use, config, setup) are not available.

## Showing data

- A list of records the user should look at goes into run_grid, not a Markdown table. Give each column a type: `trackor` for trackor keys (with id_key, the column holding TRACKOR_ID), `link` with href for other objects (`/admin/rules/Form.do?id={RULE_ID}`), `number`, `date`, `status` for states, `text` for the rest.
- Prefer sql or ov as the grid source so the user can re-run it. Use rows only for a few records you already have, and file for a JSON response saved with `--out`.
- Keep the chat answer short when a grid shows the details: what the grid shows and what stands out.

## Changing data

- Many trackors, same kind of change: find them first (ov_search, ov_sql or run_grid), then one ov_update with every row. Never loop over ov calls one trackor at a time.
- Values use the API format: drop-down values as their text, dates as YYYY-MM-DD, checkboxes as 1 or 0.
- After it finishes, read the failures in its result and explain them; a rule rejecting the change shows as the rule's error message.
