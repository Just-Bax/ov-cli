---
title: OV CLI
description: How to reach any signed-in OneVizion instance with the ov tool.
---

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
- Search with conditions: the trackor_search tool (it sends the text/plain body for you). Operators: equal, not_equal, greater, less, is_null, is_not_null, within, and/or with parentheses. Values and dates in double quotes, dates as "YYYY-MM-DD" or "YYYY-MM-DDTHH:mm:ss".
- SQL: the sql tool only (SELECT only, max 1000 rows). Needs the Test SQL privilege on that instance.
- Full definition of any config component (rule, report, automation, workflow, module, notification, trackor type, field, view, filter, import, DB package, widget): `components-export run -d '{"components":[{"component_type":"RULE","component_ids":[123]}]}'`, then read the result. Component types: IMPORT, CONFIG_GROUP, WORKFLOW, CONFIG_APPLET, CONFIG_FIELD, DYNAMIC_VTABLE, APPLICATION, VIEW_OPT, FILTER_OPT, BPD_ITEM, TRACKOR_FORM, TRACKOR_TOUR, WORKPLAN, TRACKOR_TYPE, RULE, RELATION_TYPE, REPORT, SEC_ROLE, DB_PACKAGE, BI_TABLE, MODULE, NOTIF, AUTOMATION, RULE_TYPE, WIDGET_PANEL, WIDGET. Use this when SQL is not allowed.
- Vizion Hub module runs and logs: `api list module` (module-runs, module-logs).
- Chats on a trackor: `request GET /v3/chats -q trackor_id=<id>`, then `request GET /v3/chats/<chat_id>/messages`.
- Files: `request GET "/../efiles/EFileGetBlobFromDb.do?id=<blob_id>" --out <name>`; the file lands in this run's workspace, open it with read_file.

Errors carry an exit code: 3 the session expired (the app asks the user to sign in and retries; just continue), 4 no such operation or record, 5 an API error (read the message; OneVizion reports missing field privileges as HTTP 500), 6 a missing privilege, 7 a write blocked because changes are off.

Files you read or write with `--out`, `-d @file` or `--file` live in this run's workspace. Session commands (login, logout, use, config, setup) are not available to you.
