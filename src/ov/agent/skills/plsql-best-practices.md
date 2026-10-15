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

Use the ID package: `id.<trackor_type>.tt`, `id.<trackor_type>.cf.<field>`, `id.<trackor_type>.rel.<child_type>`, `id.vt.<vtable>.<value>`, `id.wp.datepair.<abbr>`, `id.imp.<import>`, `id.rpt.<report>` (lowercase, spaces as underscores; in plain SQL `id.get('id.site.tt')`). It survives renumbering and copies between instances. When an id must stay literal, put it in a named constant with the object's name next to it.

## Rule code

- Start with what the rule does and why, in one short comment.
- Read the trigger's bind variables (for example :pk, :imp_run_id, :process_id) once into variables.
- Keep rules small and fast: they run inside the user's save. Select by key, never loop over every trackor of a type in an update rule.
- Do not commit or roll back in a rule, and do not swallow errors with `when others then null`; let the error reach the user or raise a clear one.

## Data fixes

A data fix proposed with ov_propose is a plain anonymous block: no commit, no exception handler, no rollback. It uses the APIs above, selects the exact rows by key, and its effect can be checked afterwards with one SELECT you also give.

## Naming and layout

- Prefixes: `v_` variables, `c_` constants, `gv_`/`gc_` package-level variables and spec constants, `p_` parameters (always with IN/OUT), `cur_` explicit cursors, `rec_` cursor records, `rt_` record types, `list_` collections, `t_` object types, `e_` exceptions.
- Anchor variables that hold database values with `%TYPE` (`v_key xitor.xitor_key%type`).
- Standard parameter names: `p_tid` trackor id, `p_ttid` trackor type id, `p_cfid` field id, `p_pid` program id, `p_uid` user id.
- 4 spaces, no tabs; one parameter per line with the first on a new line; one statement per line; spaces around operators.
- No redundant brackets (`if x = 1 and y = 2 then`); long conditions one per line, aligned.
- Prefer cursor FOR loops (`for rec in (select ...) loop`) over open/fetch/close; do not EXIT or RETURN out of FOR or WHILE loops.
- `--` comments that explain why, not what. Packages and their routines get a short `/** ... */` description.
