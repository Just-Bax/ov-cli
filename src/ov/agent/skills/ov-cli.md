---
title: ov CLI
description: How to reach any signed-in OneVizion instance with the ov tool.
---

Every instance is reached through the `ov` tool. Pass arguments as a list, without the leading `ov`; pass the instance alias or host as `instance` and the tool adds `-i`. Calls are read-only unless the user allowed changes for this run.

Discover before guessing:

- `api tags`: the API groups on this instance.
- `api list <word>`: search every API operation, e.g. `api list rule`, `api list import`.
- `api show <ref>`: parameters of one operation. `api schema <ref>`: its request body shape.
- `<tag> <operation> --help`: the generated command for an operation, with one flag per parameter.
- `request GET <path> -q k=v`: call any API path directly (paths are relative to /api).

Most useful calls:

- Platform version: `request GET /v3/server_info`.
- Trackor types and fields: `request GET /v3/trackor_types`, then `request GET /v3/trackor_types/<TYPE>`.
- Trackors of a type: `request GET /v3/trackor_types/<TYPE>/trackors -q fields=A,B -q FIELD=value` (a field filter is a LIKE match; check exact values yourself).
- One trackor: `request GET /v3/trackors/<TRACKOR_ID> -q fields=A,B`.
- Conditions (equal, not_equal, greater, less, within, is_null, is_not_null, and/or, parentheses): use the trackor_search tool. Dates go in double quotes as "YYYY-MM-DD" or "YYYY-MM-DDTHH:mm:ss".
- SQL: use the sql tool (SELECT only, max 1000 rows). It needs the Test SQL privilege on that instance.
- Full definition of a configuration component (rule, report, automation, workflow, module, notification, trackor type, field, view, filter, import, DB package, widget): `components-export run -d '{"components":[{"component_type":"RULE","component_ids":[123]}]}'`. Component types: IMPORT, CONFIG_GROUP, WORKFLOW, CONFIG_APPLET, CONFIG_FIELD, DYNAMIC_VTABLE, APPLICATION, VIEW_OPT, FILTER_OPT, BPD_ITEM, TRACKOR_FORM, TRACKOR_TOUR, WORKPLAN, TRACKOR_TYPE, RULE, RELATION_TYPE, REPORT, SEC_ROLE, DB_PACKAGE, BI_TABLE, MODULE, NOTIF, AUTOMATION, RULE_TYPE, WIDGET_PANEL, WIDGET.
- Chats on a trackor: `request GET /v3/chats -q trackor_id=<id>`, then `request GET /v3/chats/<chat_id>/messages`.
- Files: `request GET "/../efiles/EFileGetBlobFromDb.do?id=<blob_id>" --out <name>`; the file lands in this run's workspace, open it with read_file.

Exit codes in errors: 3 means the session expired (the app asks the user to sign in and retries), 4 means no such operation or record, 5 is an API error (read the message; OneVizion reports missing field privileges as HTTP 500), 6 is a missing privilege, 7 is a write blocked because changes are off for this run.

Start args with the command (`request`, `api`, a tag), never with an option. Run SQL only with the sql tool. Files you read or write with `--out`, `-d @file` or `--file` live in this run's workspace.

If a call is forbidden, say which privilege is missing and look for another route to the same fact before stopping.
