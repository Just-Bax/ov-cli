---
title: OneVizion basics
description: What OneVizion is, where things live in an instance, and how to link to them.
---

OneVizion is a configurable platform for tracking projects, assets and processes. Each customer has its own instance (a host such as acme.onevizion.com), sometimes with several tenants. Almost everything is configuration, not code:

- Trackor types are the record types (Project, Site, Case, ...). Trackors are the records. Fields (config fields) hold the data; relation types link trackor types into parent and child hierarchies.
- Workplans hold tasks and dates on a trackor. Workflows move trackors through steps.
- Rules run SQL or PL/SQL on events (field change, trackor create, schedule). Automations and notifications react to events. Imports load data; reports export it.
- Vizion Hub modules are Python integrations that run on a schedule, with run logs per module run. Their code lives in a git repo named in MODULE.GIT_REPO_URL.
- Security roles and privileges decide what each user can see and change, down to single fields.

Find things by their real definition, never by memory:

- Columns on the live instance: `select column_name, data_type from user_tab_columns where table_name = 'RULE'`.
- Common tables: XITOR (trackors), XITOR_TYPE, CONFIG_FIELD, RULE, RULE_TYPE, AUTOMATION, NOTIF, NOTIF_QUEUE, REPORT__, IMPORT_RUN, PROCESS, AUDIT_LOG, BLOB_DATA, DB_PACKAGE, MODULE, MODULE_RUN, MODULE_LOG, WF_WORKFLOW, WF_STEP.
- If a source with platform code or module code is configured, search it for error text and class names from stack traces.

Typical investigations:

- A rule fails or misbehaves: export the rule, read its SQL, check AUDIT_LOG and recent errors, reproduce the data condition with SELECTs.
- A module run fails: read the run log and the module settings, then the module code (git_clone the repo from MODULE.GIT_REPO_URL).
- A report or import is slow or wrong: its definition, its recent runs and timings, and the data it reads.
- A workflow or automation misbehaves: export it, plus the rules it triggers.

Links (give the user one for every object you mention):

- Rule `https://<host>/admin/rules/Form.do?id=<RULE_ID>`, report `/admin/reports/Form.do?id=<ID>`, automation `/admin/automation/Form.do?id=<ID>`.
- Trackor `https://<host>/form/ConfigAppForm.do?id=<TRACKOR_ID>`.
- A grid filtered to one record: `https://<host>/grid/SimpleGrid.do?ModuleName=<MODULE>&qsField=<FIELD>&qsValue=<VALUE>`, with modules such as ADMIN_RULES, ADMIN_REPORTS, ADMIN_AUTOMATION, ADMIN_PROCESSES, ADMIN_MODULE, ADMIN_WF_TEMPLATE, ADMIN_DB_PACKAGE, ADMIN_TRACKOR_TYPES, ADMIN_CONFIG_FIELDS, ADMIN_NOTIF, ADMIN_IMPORT_GROUP.
