---
title: OneTeam Basics
description: Use for anything on trackor.onevizion.com: cases, issues, issue tasks, inquiries, epics, versions, error reports, or finding past work.
---

trackor.onevizion.com (OneTeam) is OneVizion's own instance: support cases, development issues, versions and error reports. Pass `instance: "trackor.onevizion.com"`. Expect no Test SQL privilege there: use ov_case, ov_search and API calls, not ov_sql. A bare case number or case link from the user is loaded for you.

## Cases (trackor type `Cases`)

The support ticket. The case number is XITOR_KEY (TRACKOR_KEY in the API); TRACKOR_ID is a different long id.
- C_TITLE, C_DESCRIPTION_MEMO, C_PROBLEM, C_TYPE (Event, Change Request, Config Event, NOC Event, Question, ...), C_STATUS, C_SEVERITY.
- C_WEBSITE: the customer instance the case is about (sometimes C_SERVER_URL too).
- C_ICC_LOG_WIKI: internal comments. C_COMMENT_LOG_WIKI: public comments.
- C_OWNER: Tier 1 owner (CSM). C_DEV_OWNER: Tier 3 owner (TCE).
- C_RELATED_ISSUE, C_RELATED_ISSUE_TASKS_: linked development work.
- C_RESOLUTION, C_ROOT_CAUSE_DETAILS: how past cases were solved.

## Issues (trackor type `Issue`) and Issue Tasks (`Issue_Task`)

- Issue: VQS_IT_XITOR_NAME (summary), VQS_IT_STATUS, XITOR_CLASS_ID (Bug, New Feature, Improvement), I_PLANNED_VERSION, VQS_IT_RELEASE_NOTES, I_ROADMAP_EPIC. The issue's summary and release notes are written for customers.
- Issue Task: IT_DESCRIPTION, IT_TASK_TYPE. "Inquiry" tasks are requests for development to review (enhancement ideas, suspected bugs nobody has filed yet).
- Read Issue Life Cycle for statuses, task types, versions and backports.

## Error reports

Platform errors are emailed to OneTeam and grouped into "Err-*" issues by the Java class and line of the error, with an Error Report trackor per occurrence (URL, user name, timestamp, version). To find the issue for an error: search Error Reports by instance URL and user around the error time, or search Issue summaries for the first `com.onevizion` frame of the stack trace (class.method:line). Look at the version too: the error may come from an older version where it is already fixed.

## Finding past work

- Similar cases: ov_search on Cases with a distinctive phrase, e.g. `equal(C_TITLE, "copy-blobs-to-public-s3")` or a rule or module name, then read C_RESOLUTION and the chat of the closest ones. Say which case matched and what fixed it.
- Existing development: search Issue (VQS_IT_XITOR_NAME, release notes) and Issue_Task (IT_DESCRIPTION with IT_TASK_TYPE = "Inquiry"), and the case's own C_RELATED_ISSUE fields. Name the closest matches and say plainly whether they cover the request.
- Link a record: `https://trackor.onevizion.com/form/ConfigAppForm.do?id=<TRACKOR_ID>`.
