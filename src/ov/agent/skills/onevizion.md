---
title: OneVizion Basics
description: What OneVizion is, where every object lives in the database, how runs and errors are logged, and how to link to things.
core: true
---

OneVizion is a configurable platform for tracking projects, assets and processes. Each customer has its own instance (a host such as acme.onevizion.com), sometimes with several tenants. Almost everything is configuration stored in an Oracle schema: trackor types and fields, rules, automations, notifications, imports, reports, workflows, Vizion Hub modules. Find things by their real definition, never by memory. If a column is not listed here, check it first: `select column_name, data_type from user_tab_columns where table_name = 'RULE'`. If the platform repo is in the workspace, table DDL is at `db/ddl/tables/<table>.sql` inside it and packages under `db/`; search it with ws_search for error text and class names from stack traces.

## The instance map

Call ov_map first when you need to know what is connected to an object: which rules are triggered by or use a field, what loads a trackor type, which workflow runs a rule, which rules call a DB package and what the package uses. It answers from a cached map of the whole configuration without SQL; links marked "in code" come from rule, import, report and DB package code, counting only quoted names, config ids, `id.*` object references and `PACKAGE.procedure` calls, so dynamic SQL can be missed. Confirm anything important on the instance before you rely on it.

## Object references (the ID package)

Code can name config objects without hard-coded ids through the generated `ID` package (PKG_OBJREF): `id.<trackor_type>.tt`, `id.<trackor_type>.cf.<field>`, `id.<trackor_type>.rel.<child_type>`, `id.<trackor_type>.class.<class>`, `id.vt.<vtable>.<value>`, `id.vtable.<vtable>`, `id.imp.<import>`, `id.rpt.<report>`, `id.wf.<workflow_template>`, `id.wp_template.<template>`, `id.wp.datepair.<abbr>`. Names are lowercase with spaces as underscores. PL/SQL uses them directly (`util.SetValByID(v_id, id.issue.cf.estim_hours, 200)`); plain SQL wraps them: `id.get('id.site.tt')`. ENTITY_OBJREF_DEPENDENCY (ENTITY_COMPONENT_ID, ENTITY_ID, TABLE_NAME, COLUMN_NAME, OBJREF, OBJECT_COMPONENT_ID, OBJECT_ID) lists which entity code uses which reference. Prefer object references over hard-coded ids in fixes: they survive renumbering and copies between instances.

## PROCESS: the run log behind reports, imports, exports, modules, rules and automations

- PROCESS: PROCESS_ID, PROCESS_TYPE_ID, STATUS_ID, USER_ID, SUBMISSION_DATE, START_DATE, END_DATE, RUNTIME (seconds), ERROR_MESSAGE (short), ERROR_MESSAGE_FULL (CLOB, the detail), COMMENTS.
- PROCESS_TYPE_ID: 1 Report, 2 Import, 3 Grid Export, 4 Data Submit, 5 Module, 6 Rule, 8 Automation.
- STATUS_ID: 0 pending, 1 running, 2 executed without errors, 3 executed with errors, 4 in queue, 5 importing data, 6 executed without warnings, 7 executed with warnings, 14 interrupted, 15 interrupting, 20 cancelled (cell limit), 21 cleanup of hung process, 23 temporarily suspended.
- Error log page of one process: `https://<host>/admin/processes/FormErrorLog.do?id=<PROCESS_ID>`. Grid ADMIN_PROCESSES.

```sql
select p.process_id, t.process_type, s.status, p.start_date, p.runtime, p.error_message
  from process p join process_type t on t.process_type_id = p.process_type_id
  join process_status s on s.process_status_id = p.status_id
 where p.status_id in (3,14,21) and p.submission_date > sysdate - 1 order by p.process_id desc
```

## Rules

- RULE: RULE_ID, RULE (name), RULE_TYPE_ID (the trigger), RULE_CLASS_ID, IS_ENABLED, IS_ASYNC, ENABLE_TRACE, ORDER_NUMBER, SQL_TEXT (CLOB, the PL/SQL), PRIMARY_TRACKOR_TYPE_ID, FILTER_OPT_ID, FILTER_SQL. Negative RULE_ID = system rule.
- RULE_TYPE: RULE_TYPE_ID, RULE_TYPE, ID_FIELD (bind name), REPEAT_INTERVAL (scheduler expression for scheduled types). Common types: 8 config field updated, 18 trackor created, 19 trackor updated, 20 trackor deleted, 80 trackor created/updated, 21/23 relation created/deleted, 4 Form Button, 35 Mass Assign, 30/31/32 workplan, 1/55 task, 37/38 import completed/started, 41-44 workflow, 51/52 report executed, 120/121 module started/completed. Scheduled rules use a custom type with REPEAT_INTERVAL.
- RULE_ID_NUM (RULE_ID, ID_NUM): what a rule is bound to (e.g. the CONFIG_FIELD_ID for type 8).
- RULE_CLASS_ID: 1 PL/SQL, 6 HTTP call, 14 AI request, 17 Python, -1 automation.
- Run history: RULE_RUN (RULE_RUN_ID, RULE_ID, PROCESS_ID, ROWS_PROCESSED, RETURN_STR, WARNING_MESSAGES); rows exist only when ENABLE_TRACE = 1, for scheduled rules, and for Form Button / Mass Assign rules. RULE_RUN_ENTITY_PK lists the trackors a run touched.
- Async queue: RULE_QUEUE (RULE_QUEUE_ID, RULE_ID, RULE_QUEUE_STATUS_ID, CREATED_TS, STARTED_TS, PROCESSED_TS, EXCEPTION_MESSAGE CLOB). Status: 0 pending, 1 running, 2 executed with exception, 3 success, 4 merged, 5 in execution queue.
- HTTP call rules: RULE_HTTP_CALL_LOG (RULE_ID, XITOR_ID, REQUEST, RESPONSE, RESPONSE_HTTP_STATUS_CODE, ERROR_MESSAGE, RULE_STARTED_TS).
- Last run: COMP_OBJECT_LOG.LAST_RUN_DATE where COMPONENT_ID = 4 and OBJECT_ID = RULE_ID.
- Which rule changed a value: AUDIT_LOG joined to AUDIT_CALL_STACK (see Audit).
- Forms: rule `/admin/rules/Form.do?id=`, rule type `/admin/ruletypes/Form.do?id=`, rule run `/admin/rulerun/Form.do?id=`, queue entry `/admin/rulequeue/Form.do?id=`. Grids ADMIN_RULES, ADMIN_RULE_RUN, ADMIN_RULE_QUEUE, ADMIN_RULES_HTTP_LOG.

```sql
select r.rule_id, r.rule, t.rule_type, r.rule_class_id, r.is_enabled, r.is_async
  from rule r join rule_type t on t.rule_type_id = r.rule_type_id where upper(r.rule) like upper('%name%')
select q.rule_queue_id, q.rule_id, q.created_ts, q.processed_ts, dbms_lob.substr(q.exception_message, 4000, 1) err
  from rule_queue q where q.rule_queue_status_id = 2 order by q.rule_queue_id desc
```

## Automations

- AUTOM: AUTOM_ID, AUTOM_NAME, ENABLED, TRACKOR_TYPE_ID, RELATED_TRACKOR_TYPE_ID, STOP_ON_FILTER_MATCH, DESCRIPTION.
- AUTOM_FILTER (AUTOM_FILTER_ID, AUTOM_ID, FILTER_OPT_ID, FILTER_SQL, ORDER_NUMBER) -> AUTOM_ACTION (AUTOM_ACTION_ID, AUTOM_FILTER_ID, AUTOM_ACTION_TYPE_ID, ENABLED, ORDER_NUMBER, EXECUTE_RULES).
- Triggers: AUTOM_TRIGGER_SCHEDULE (schedule is a custom RULE_TYPE with REPEAT_INTERVAL), AUTOM_TRIGGER_TRACKOR_TYPE, AUTOM_TRIGGER_CF, AUTOM_TRIGGER_TASK, AUTOM_TRIGGER_TASK_DATE, AUTOM_TRIGGER_RELATION_TYPE.
- Automations execute through rules (RULE_CLASS_ID = -1); async parts go through RULE_QUEUE.
- Runs: AUTOM_RUN (AUTOM_RUN_ID, AUTOM_ACTION_ID, PROCESS_ID, ROWS_PROCESSED); errors in PROCESS (type 8).
- Forms: automation `/admin/automation/Form.do?id=`, filter/action `/admin/automation/FormFilterAction.do?id=`, run `/admin/automationrun/Form.do?id=`. Grids ADMIN_AUTOMATION, ADMIN_AUTOMATION_RUN.

## Notifications

- NOTIF: NOTIF_ID, NOTIF_NAME, NOTIF_TYPE_ID, IS_ENABLED, TRACKOR_TYPE_ID, TRACKOR_SQL, USER_SQL, SQL_SEND_TO, FILTER_OPT_ID, STATIC_EMAILS, LAST_EXEC_DATE.
- NOTIF_QUEUE: NOTIF_QUEUE_ID, USER_ID, TO_ADDRESS, SUBJ, MSG, QUEUE_STATUS_ID, CREATED_TS, PROCESSED_TS. Status: 0 building, 1 complete/not sent, 2 sending, 3 failed/will retry, 4 failed/no more attempts, 5 sent, 6 cancelled. NOTIF_QUEUE_NOTIF_XREF (NOTIF_ID, NOTIF_QUEUE_ID) links them.
- Send errors: NOTIF_QUEUE_ATTEMPT (NOTIF_QUEUE_ID, TS, ERR_CODE). SQL timings: NOTIF_PROCESSING_LOG.
- Form `/admin/notifications/Form.do?id=`. Grids ADMIN_NOTIFICATIONS, ADMIN_NOTIF_QUEUE.

## Imports

- IMP_SPEC (IMP_SPEC_ID, NAME, IMP_FILE_TYPE_ID, DATE_FORMAT, VALIDATE_DATA_MODE_ID, MAX_EXEC_TIME), IMP_ENTITY (IMP_ENTITY_ID, IMP_SPEC_ID, XITOR_TYPE_ID, ENTITY_NAME, SQL_TEXT), IMP_DATA_MAP (IMP_SPEC_ID, IMP_ENTITY_ID, IMP_COLUMN_ID, DATA_MAP_NAME, SQL_TEXT).
- Runs: IMP_RUN (IMP_RUN_ID, IMP_SPEC_ID, PROCESS_ID, NUM_ROWS, ROWS_PROCESSED, BLOB_DATA_ID); status/errors in PROCESS (type 2).
- Row errors: IMP_RUN_ERROR (IMP_RUN_ID, ROW_NUM, COL_NAME, BAD_DATA_VALUE, ERROR_MSG, IMP_ERROR_TYPE_ID) with IMP_ERROR_TYPE (e.g. 1 PK, 2 data, 3 CF not found, 5 mapping SQL, 12/13 new/update trackor rule error, 18/19 import complete/start rule error).
- Form `/admin/configimport/Form.do?id=`. Grids ADMIN_CONFIG_IMPORT, IMPORT_HISTORY.

## Reports

- REPORT_FILES (REPORT_FILE_ID, REPORT_NAME, REPORT_GROUP_ID, DEFAULT_REPORT_FORMAT, REPORT_DELIVERY, MAX_EXEC_TIME), REPORT_SQL (REPORT_FILE_ID, SQL_NAME, SQL_TEXT, ORDER_NUMBER).
- Runs: REPORT_RUN (REPORT_RUN_ID, REPORT_FILE_ID, PROCESS_ID, PARAMETERS, REPORT_BLOB_DATA_ID); timing and errors in PROCESS (type 1). Grid exports: EXPORT_RUN.
- Form `/admin/reports/Form.do?id=`. Grids ADMIN_REPORTS, REPORT_HISTORY.

## Vizion Hub modules

- MODULE: MODULE_ID, MODULE_NAME, IS_ENABLED, VERSION, GIT_REPO_URL, COMMAND, SCHEDULE (cron), LAST_RUN, NEXT_RUN, LOG_LEVEL. Settings: MODULE_PARAM (NAME, VALUE, VALUE_CLOB); never read hidden or password values.
- Runs: MODULE_RUN (MODULE_RUN_ID, MODULE_ID, PROCESS_ID); logs MODULE_LOG (MODULE_RUN_ID, TS, LOG_LEVEL 0 info/1 warn/2 error/3 debug, MESSAGE, DESCRIPTION CLOB). Install history: MODULE_INSTALL (VERSION, MODULE_STATUS_ID, ERROR_MESSAGE).
- The code: the module's folder in the workspace, or clone GIT_REPO_URL into it with ws_run, then ws_search / ws_read it.
- Forms: module `/admin/module/Form.do?id=`, run `/admin/modulerun/Form.do?id=`. Grids ADMIN_MODULE, ADMIN_MODULE_RUN, ADMIN_MODULE_LOG.

## Workflows

- WF_TEMPLATE (WF_TEMPLATE_ID, TEMPLATE_NAME, VERSION, IS_CURRENT_VERSION), WF_TEMPLATE_STEP (STEP_NAME, STEP_TYPE_ID, PLSQL_BLOCK, RULE_ID, NEXT_WF_TEMPLATE_STEP_ID).
- Instances: WF_WORKFLOW (WF_WORKFLOW_ID, WF_TEMPLATE_ID, WORKFLOW_NAME, WF_STATE_ID 1 running/3 suspended/4 finished/5 abandoned, START_DATE, FINISH_DATE), WF_STEP (WF_WORKFLOW_ID, STEP_NAME, PLSQL_BLOCK, START_DATE, FINISH_DATE, KEY_VALUE = trackor id).
- Forms: template `/admin/wftemplate/Form.do?id=`, step `/admin/wftemplate/FormStep.do?id=`, running workflow `/admin/wf/Form.do?id=`.

## Trackor types, fields, trackors and values

- XITOR_TYPE (XITOR_TYPE_ID, XITOR_TYPE name, KEY_FIELD, IS_AUTOKEY), RELATION_TYPE (PARENT_TYPE_ID, CHILD_TYPE_ID, CARDINALITY_ID), RELATION (RELATION_TYPE_ID, PARENT_ID, CHILD_ID).
- CONFIG_FIELD: CONFIG_FIELD_ID, CONFIG_FIELD_NAME, XITOR_TYPE_ID, DATA_TYPE, IS_READ_ONLY, IS_MANDATORY, SQL_QUERY (calculated/DB fields), DEFAULT_VALUE_SQL, LOG_CHANGES. Data types: 0 Text, 1 Number, 2 Date, 3 Checkbox, 4 Drop-Down, 5 Memo, 7 Wiki, 8 DB Drop-Down, 9 DB Selector, 10 Selector, 15 Electronic File, 16 Multiple EFiles, 20 Trackor Selector, 21 Trackor Drop-Down, 22 Trackor MultiSelector, 25 Calculated, 30 Hyperlink, 50 Rollup, 80 MultiSelector, 90 Date/Time.
- XITOR (XITOR_ID, XITOR_KEY, XITOR_TYPE_ID, IS_TEMPLATE). Values keyed by (KEY_VALUE = XITOR_ID, CONFIG_FIELD_ID): CONFIG_VALUE_CHAR (VALUE_CHAR, VALUE_CLOB) for text/memo/wiki/hyperlink, CONFIG_VALUE_NUMBER (VALUE_NUMBER) for numbers, checkboxes, drop-down value ids and file BLOB_DATA_ID, CONFIG_VALUE_DATE (VALUE_DATE), CONFIG_VALUE_MULT for multi-selects. Easiest read: `pkg_config_field_rpt.getValStrByID(xitor_id, config_field_id)`.
- Forms: trackor type `/admin/trackortypes/Form.do?id=`, field `/admin/configfields/Form.do?id=`, trackor `/form/ConfigAppForm.do?id=<TRACKOR_ID>`.

## Audit and error logs

- AUDIT_LOG: TABLE_NAME, COLUMN_NAME (CONFIG_FIELD_ID for fields), PK, ACTION (U/I/D), FROM_/TO_CHAR, FROM_/TO_NUMBER, FROM_/TO_DATE, TS, USER_ID, XITOR_ID. AUDIT_CALL_STACK (AUDIT_LOG_ID, ROUTINE_TYPE_ID, ROUTINE_ID, ROUTINE_TEXT) tells which rule, import or routine made the change.
- ERROR_LOG (ERROR_LOG_ID, ERROR_REPORT_ID = the GUID users see, USER_ID, TS, ERROR_MESSAGE CLOB). USER_ERROR (UN, URL, TS, ERROR_TEXT); never select its HTTP_COOKIE or FORMS columns.
- INVALID_OBJECT (COMPONENT_ID, ENTITY_ID, ENTITY_NAME, ERROR_MESSAGE, INVALID_SINCE): config objects whose SQL no longer compiles. COMPONENT_ID: 1 import, 3 report, 4 rule, 5 field, 17 workflow, 22 notification, 27 DB package, 42 module, 50 automation.
- DB_PACKAGE (DB_PACKAGE_ID, DB_PACKAGE_NAME, DB_PACKAGE_SPEC, DB_PACKAGE_BODY). Form `/admin/dbpackage/Form.do?id=`.
- Users: USERS (USER_ID, UN, EMAIL, IS_DISABLED, LAST_LOGIN_DATE; never PWD), SEC_ROLE (ROLE_TYPE), USER_SEC_ROLE. Files: BLOB_DATA (BLOB_DATA_ID, FILENAME, BLOB_DATA_LEN, KEY_VALUE, CONFIG_FIELD_ID, CREATED_TS).

```sql
select error_log_id, error_report_id, ts, dbms_lob.substr(error_message, 4000, 1) msg
  from error_log where ts > sysdate - 1 order by error_log_id desc
select a.ts, a.user_id, a.action, a.column_name, a.from_char, a.to_char, s.routine_type_id, s.routine_id
  from audit_log a left join audit_call_stack s on s.audit_log_id = a.audit_log_id
 where a.pk = :xitor_id order by a.audit_log_id desc
```

## Links

Give the user a link for every object you mention, using the form URLs above on `https://<host>`. A grid filtered to one record: `https://<host>/grid/SimpleGrid.do?ModuleName=<MODULE>&qsField=<FIELD>&qsValue=<VALUE>` with the grid names above.

## Typical investigations

- A rule fails or does the wrong thing: read the rule (RULE or a component export), its trigger and bindings, RULE_QUEUE exceptions, RULE_RUN + PROCESS errors, and AUDIT_LOG for the affected trackor; reproduce the data condition with SELECTs.
- A module run fails: MODULE_RUN -> PROCESS error, MODULE_LOG errors, the module settings, then the module code from GIT_REPO_URL.
- An import fails or loads wrong data: IMP_RUN -> PROCESS, IMP_RUN_ERROR rows, the IMP_DATA_MAP SQL, and the rules triggered by import start/complete.
- A report is slow or wrong: REPORT_RUN -> PROCESS RUNTIME and errors, the REPORT_SQL, and the data it reads.
- An email was not sent: NOTIF_QUEUE status and NOTIF_QUEUE_ATTEMPT errors for that notification.
- Something broke after a change: INVALID_OBJECT, then AUDIT_LOG of the config tables.
