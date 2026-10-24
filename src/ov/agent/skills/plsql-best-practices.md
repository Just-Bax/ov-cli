---
title: PL/SQL Best Practices
description: Use before writing or reviewing PL/SQL for rules, DB packages, workflow steps, imports or data fixes on an instance.
---

## Use the platform APIs, never raw DML on platform tables

Writing straight into XITOR, RELATION, CONFIG_VALUE_*, WP_*, BLOB_DATA or the label and security tables skips the rules, audit log, locks and calculations the platform runs on every change. Some tables (RELATION, ANCESTOR, deletes on XITOR, LABEL_PROGRAM, security tables) refuse direct changes outright; CONFIG_VALUE_* accept them silently and leave the data inconsistent. Use these instead (all from the `util` package unless named):

- Read a value: `util.GetValStrByID(trackor_id, field_id)` (display text for any type), `GetValNumByID`, `GetValDateByID`, `GetValCheckboxByID`, `GetValMemoByID`, `GetValStrMultByID`/`GetValNumMultByID` for multi-selects. In plain SQL and reports: `pkg_config_field_rpt.getValStrByID`, `getValStrByIDYN` (checkbox as Yes/No), `getValNumNLByID`, `getValDateById`.
- Set a value: `util.SetValCharByID`, `SetValNumByID` (numbers, checkboxes, drop-down value ids), `SetValDateByID`, `SetValMemoByID`, or the overloaded `SetValByID(trackor_id, field_id, value)`. Multi-selects: `SetMultValNumByID`, `AddValNumByID`, `RemoveValNumByID`. Locked fields are respected unless you pass IgnoreLocks = 1; do that only when the plan says so.
- Files: `util.CopyEFileFromBlobData(blob_data_id, trackor_id, field_id)` (works with cloud storage), `util.deleteEfile`, `util.renameEFile`.
- Trackors: `util.NewTrackor(trackor_type_id, key, ...)` returns the new id; `util.DropTrackor(trackor_id)`; `util.GetTrackorID(key, trackor_type_id)` (null when not found); `util.GetParentByID(trackor_id, parent_type_id)` (raises when none).
- Relations: `util.NewRelation(parent_id, child_id)`, `util.DropRelation(parent_id, child_id)`.
- Workplan task dates: `util_wp.get_task_id(...)`, `util_wp.get_task_date(task_id, id.wp.datepair.<abbr>, t_task_sf_date.s())`, `util_wp.set_task_date(...)`, `util_wp.set_task_na`/`block_task`.
- Errors shown to users: `util.RaiseError('message')` or `util.RaiseError(label_id, params)`.
- Mail: `util.SendMail(...)`, `util.SendNotification(subject, message, user_id)`.
- Current user and tenant: `pkg_sec.get_cu`, `pkg_sec.get_pid`. Labels: `pkg_label.format(label_id, params)`. Strings: `pkg_str.split_str2num`, `pkg_str.is_number`.

Check a signature on the instance before using it (`select text from all_source where name = 'UTIL' and type = 'PACKAGE' and upper(text) like '%SETVALNUMBYID%'`), since versions differ.

## Name objects, do not hard-code ids

Use the ID package: `id.<trackor_type>.tt`, `id.<trackor_type>.cf.<field>`, `id.<trackor_type>.rel.<child_type>`, `id.<parent>.rt.<child>` (relation type), `id.<trackor_type>.class.<class>`, `id.vtable.<vtable>`, `id.vt.<vtable>.<value>`, `id.wp_template.<template>`, `id.wp.<template>.tord_<n>` (template task), `id.wp.datepair.<abbr>`, `id.imp.<import>`, `id.rpt.<report>` (lowercase, spaces as underscores; in plain SQL `id.get('id.site.tt')`). It survives renumbering and copies between instances. Look the reference up on the instance rather than building it from a name by hand. Object references are already numbers: use `id.site.tt` directly, never select it into a variable first. When an id must stay literal, put it in a named constant with the object's name next to it.

A field whose name is not a valid Oracle identifier has no object reference; only then use the name-based functions (`util.GetValStr(:pk, 'FIELD')`).

## Rule code

- Read the trigger's bind variables (for example :pk, :imp_run_id, :process_id) once into variables; onevizion-reference lists them per trigger.
- Keep rules small and fast: they run inside the user's save. Select by key, never loop over every trackor of a type in an update rule. Past about 100 lines, or when logic repeats across rules, move it into a DB package and suggest that.
- Do not commit or roll back in a rule (only inside `pragma autonomous_transaction`), and do not swallow errors with `when others then null`; let the error reach the user or raise a clear one. Any unhandled error rolls back the whole save.
- No package functions (`util.GetVal...`, your own) in WHERE, JOIN ON or HAVING: each call switches between the SQL and PL/SQL engines for every row. Put them in the select list, or fetch the rows and test the value in PL/SQL.
- Aggregate in SQL (`sum`, `listagg ... on overflow truncate`) instead of looping to add up or concatenate; fetch a single row with `select ... into`, not a loop.
- Set drop-down values by id: `util.SetValNumByID(:pk, id.site.cf.s_status, id.vt.s_status.ready)`, not by text.
- DBMS_OUTPUT goes nowhere when a rule runs. Show a message with `util.setMessage(text)`; stop with `util.RaiseError`.
- Text users see comes from labels: `util.RaiseError(pkg_label.format(label_id, pkg_label.list_label_params('id' => v_id)))`.
- Never call `pkg_sec.set_cu` or `pkg_sec.set_pid`, even when asked: they act as another user or reach another tenant's data. If it is truly needed, the user adds it by hand.
- Initialize constants and `pkg_sec.get_pid` / `get_cu` in DECLARE; read business data (util.GetVal..., queries) in BEGIN.

## DB packages

- One public entry point in the spec; helpers stay private in the body, in this order: `load_*` (reads), `validate_*`, `calc_*` (pure, no side effects), `determine_*` (statuses and messages), `apply_*` (the only routines that set values), then the public routine that calls them.
- Pass related values as a record type, not long parameter lists. Package-level variables hold constants or a deliberate cache, never per-call state.
- Read each stable input once and reuse it; do not call `util.GetVal...` for the same value twice.
- Functions return values and change nothing; anything with side effects is a procedure.

## Data fixes

A data fix proposed with ov_propose is a plain anonymous block: no commit, no exception handler, no rollback. It uses the APIs above, selects the exact rows by key, and its effect can be checked afterwards with one SELECT you also give.

A script the user runs themselves follows the same rules and starts with a switch constant, `c_apply constant number := 0;`: with 0 it only prints (dbms_output) what it would change, with 1 it changes it. It never commits; the user commits after checking the output. Before you hand it over, run every query in it with ov_sql and check each API call's signature on the instance, so it does not fail when the user runs it.

## JSON in PL/SQL

- `json_object_t`, `json_array_t` and the other PL/SQL JSON types cannot be used inside a SQL statement (ORA-40573). Call `to_blob`, `to_clob` or `to_string` into a variable first, then use that variable in the UPDATE or SELECT.
- Check a column's type before converting it: some JSON lives in BLOB columns, which `json_object_t.parse` and `json_value` read directly, but string functions do not.

## Naming and layout

- Prefixes: `v_` variables, `c_` constants, `gv_`/`gc_` package-level variables and spec constants, `p_` parameters (always with IN/OUT), `cur_` explicit cursors, `rec_` cursor records, `rt_` record types, `list_` collections, `t_` object types, `e_` exceptions.
- Anchor variables that hold database values with `%TYPE` (`v_key xitor.xitor_key%type`).
- Standard parameter names: `p_tid` trackor id, `p_ttid` trackor type id, `p_cfid` field id, `p_pid` program id, `p_uid` user id.
- 4 spaces, no tabs; one parameter per line with the first on a new line; one statement per line; spaces around operators.
- No redundant brackets (`if x = 1 and y = 2 then`); long conditions one per line, aligned.
- Prefer cursor FOR loops (`for rec in (select ...) loop`) over open/fetch/close; do not EXIT or RETURN out of FOR or WHILE loops.
- No comments unless the user asks for them: clear names say what the code does.
