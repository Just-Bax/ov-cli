---
title: OneVizion Basics
description: The OneVizion data model and words everyone working on an instance must know.
core: true
---

OneVizion is a configurable platform: almost everything is configuration stored in one Oracle schema per instance (a host such as acme.onevizion.com). Find things by their real definition on the instance, never by memory. For a column you are unsure of: `select column_name, data_type from user_tab_columns where table_name = 'X'`. Legacy names live on in tables: XITOR means trackor, CONFIG_GROUP means tab.

## Core objects

- Program (PROGRAM, PROGRAM_ID): a tenant. Almost every table has PROGRAM_ID. Some hosts have several tenants; never assume they share data.
- Trackor type (XITOR_TYPE): a kind of record, such as Site or Project. KEY_FIELD and IS_AUTOKEY decide how keys are made.
- Trackor (XITOR: XITOR_ID, XITOR_KEY, XITOR_TYPE_ID, XITOR_CLASS_ID, IS_TEMPLATE): one record. XITOR_ID (the TRACKOR_ID in the API, a long number) is not the key users see (XITOR_KEY, TRACKOR_KEY in the API).
- Trackor class (V_XITOR_CLASS): a subtype of a trackor type that can show different tabs.
- Trackor tree (RELATION_TYPE: PARENT_TYPE_ID, CHILD_TYPE_ID, CARDINALITY_ID 2 one-to-many, 3 many-to-many) and relations (RELATION: PARENT_ID, CHILD_ID). ANCESTOR holds every ancestor of a trackor.
- Field (CONFIG_FIELD: CONFIG_FIELD_ID, CONFIG_FIELD_NAME, XITOR_TYPE_ID, DATA_TYPE). Data types: 0 Text, 1 Number, 2 Date, 3 Checkbox, 4 Drop-Down, 5 Memo, 7 Wiki, 8 DB Drop-Down, 9 DB Selector, 10 Selector, 15 Electronic File, 16 Multiple EFiles, 20 Trackor Selector, 21 Trackor Drop-Down, 22 Trackor MultiSelector, 25 Calculated, 30 Hyperlink, 50 Rollup, 60 WP Task Date, 80 MultiSelector, 90 Date/Time, 91 Time.
- Values, keyed by KEY_VALUE (= XITOR_ID) and CONFIG_FIELD_ID: CONFIG_VALUE_CHAR (text, memo, wiki, hyperlink), CONFIG_VALUE_NUMBER (numbers, checkboxes, drop-down value ids, trackor selector ids, file BLOB_DATA_ID), CONFIG_VALUE_DATE, CONFIG_VALUE_MULT (multi-selects). Read them with `pkg_config_field_rpt.getValStrByID(xitor_id, config_field_id)` rather than joining by hand.
- Drop-down values (ATTRIB_V_TABLE, ATTRIB_V_TABLE_VALUE): lists of values referenced by id.
- Workplans and tasks (WP_WORKPLAN, WP_TASKS, WP_TASK_DATES with date pairs from V_WP_TASK_DATE_TYPE).
- Users (USERS, each with its own trackor in USERS.XITOR_ID) and security roles (SEC_ROLE, USER_SEC_ROLE).

## Behaviour

- Rules: PL/SQL (or HTTP, Python, AI) that runs on an event such as a field update, trackor create, import or schedule.
- Automations: no-code filter and action chains; they run through rules.
- Workflows, imports, reports, notifications and Vizion Hub modules each log their runs in PROCESS.
- The ID package names objects without hard-coded ids: `id.<trackor_type>.tt`, `id.<trackor_type>.cf.<field>`, `id.vt.<vtable>.<value>`; in plain SQL `id.get('id.site.tt')`.

## Time zones

The servers run in the time zone of the PrimaryTimezone system parameter, and a logon trigger sets each DB session to it, so current_date and logged timestamps are instance time. Users see logs shifted by their own offset (USERS.TZ_OFFSET) unless the ForceUserTimezone parameter is set. Date and Date/Time field values are never converted: what was entered is what every user sees.

## Big tables

CONFIG_VALUE_*, AUDIT_LOG, USAGE_LOG, PROCESS, RULE_RUN, RULE_QUEUE, RULE_HTTP_CALL_LOG, MODULE_LOG, ERROR_LOG, NOTIF_QUEUE, BLOB_DATA, XITOR and RELATION can hold millions of rows. Filter them by key (KEY_VALUE, XITOR_ID, PK, RULE_ID) and a narrow date range; never count or group a whole table or a whole field. Reading CLOBs (request, response, message bodies) across many rows is slow: find the few rows first, then read their CLOBs.

Before querying configuration or log tables, read onevizion-reference for their real columns; names are often not what you would guess (the rule name is RULE.RULE, not RULE_NAME).
