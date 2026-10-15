---
title: TCE Best Practices
description: Use when working a support case, troubleshooting a customer problem end to end, or writing a reply for the case chat.
---

Read OneTeam Basics for the case and issue fields; this skill is how to work the case.

## Working a case

1. Understand what is actually asked: which instance (C_WEBSITE, or from the text), which objects, what the customer expects. Read every attachment (screenshots, .eml, logs) with run_read, not just the case text.
2. Investigate on the instance: current configuration, logs with timestamps, the actual data. Confirm the problem is real and whether it still happens now, in the instance's time zone.
3. For each problem find the root cause with evidence, then decide: a fix, a user action, or expected behavior.
4. When an enhancement or bug is involved, search Issue and Issue_Task for existing work and check the case's related issue fields; say whether a match covers the request. For a platform bug, check whether a fix exists and has reached the customer's version (Issue Life Cycle).
5. ov_propose for every concrete code or component change, with the current code as before.
6. run_report with the findings, existing matches, unrelated problems and the reply.

Deliver a short summary per problem that answers the question asked (unrelated problems go to the unrelated list); for a fix, where it is (object name, id, link) and the fixed code as ov_propose; and one comment for the case chat as `reply`.

## Troubleshooting playbooks

- An error message or Error Report ID from a user: find it in ERROR_LOG on the instance around that time and user, read the full stack, then look for the Err-* issue on trackor.onevizion.com (OneTeam Basics).
- A rule, import, report, notification or module fails: its run in PROCESS and the matching log table (OneVizion Reference), then its code with ov_export, then the data it touched.
- Something slow or down: PagerDuty and Datadog for that window, then PROCESS runtimes and the queries involved. Never run heavy SQL on an instance that is already struggling.
- Something changed: AUDIT_LOG of the objects involved and INVALID_OBJECT, with timestamps in one zone.
- Configuration behaving unexpectedly: compare with how the platform documents the feature before calling it a bug; say which source you used.

## Reply style

Write the case chat comment as a few short paragraphs separated by a blank line, always in this order:

1. Update: one short line with where the case stands. "Fixed.", "Not fixed yet, I need a few details.", "This works as designed.", "The fix is ready and waiting for your OK." Add "There were two problems." when there were.
2. What the problem was: plain-language cause, one paragraph per problem. Name the object the customer knows (the rule, report or field by its name), never table names, IDs or code.
3. What I did: start with "I've". What was changed or checked, and where (production or test).
4. Current status and next step: "It's working fine now." plus exactly how to test it, or exactly what you need from them to continue.

Rules:

- Each paragraph is one to three sentences of flowing text. No bullets, no headings, no hard wrapping inside a paragraph.
- Write as I, never we. No greeting, no thanks, no sign-off.
- Plain language. Cut every sentence that does not change what the customer does next; do not explain how you investigated.
- Only cover what the case asked. Extra findings go in the comment only if the user asks for them.
- Skip a part that does not apply (no "What I did" when nothing was changed), but keep the order.
- If a production change is needed and not yet applied, say what it is in one sentence and ask if it is ok to apply.

Example:

Fixed. There were two problems.

The first was in the TD: Parent-Child Matchup rule on production. It could only read a related-project field that holds one project, but "Related Power Rack Project" allows several, so the rule never found the parent project.

The second was in TD: Parent Push-down. Once task 1000 had actual dates, any later change to task 7000 was rejected with an error about actual dates overlapping projected dates.

I've updated both rules on production and tested them on sample projects with one and with two related projects.

It's working fine now. Please test by updating task 7000 on S01052-001 and checking that task 1000 on S01052-013 follows.

Example when it is not solved yet:

Not fixed yet, I need a few details to find the cause.

The 9478 message is a general "unexpected error" screen that hides the real error, and the coordinate pair message comes from the browser, so neither left a server error I can see.

I've checked the error logs and recent configuration changes on the instance, and nothing changed before the problems started.

Please send the exact tenant URL, the trackor and tab where you add the coordinate pairs, and a screenshot of the browser console (F12, Console tab) right after each problem happens.
