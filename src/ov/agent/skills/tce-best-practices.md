---
title: TCE Best Practices
description: Read before working a support case or writing a case reply: trackor, the workflow and the reply format.
---

## Trackor ticketing

trackor.onevizion.com is the ticket system. Pass `instance: "trackor.onevizion.com"` for anything on it. To read a whole case use ov_case; a bare case number or case link from the user is loaded for you before you start.

Cases (trackor type `Cases`, plural): the support ticket. The case number is XITOR_KEY (comes back as TRACKOR_KEY); TRACKOR_ID is a different, long internal id.

- C_TITLE, C_DESCRIPTION_MEMO, C_PROBLEM, C_TYPE (Event, Change Request, Config Event, NOC Event, Question, ...), C_STATUS, C_SEVERITY.
- C_WEBSITE: the customer instance host the case is about. C_SERVER_URL sometimes too.
- C_ICC_LOG_WIKI: internal comment log. C_COMMENT_LOG_WIKI: public comments.
- C_OWNER: Tier 1 owner (CSM). C_DEV_OWNER: Tier 3 owner (TCE).
- C_RELATED_ISSUE, C_RELATED_ISSUE_TASKS_: linked development work.
- C_RESOLUTION, C_ROOT_CAUSE_DETAILS: filled on past solved cases; useful for similar-case search.

Issues (trackor type `Issue`): development work. VQS_IT_XITOR_NAME (summary), VQS_IT_STATUS, XITOR_CLASS_ID (Bug, New Feature, Improvement), I_PLANNED_VERSION, VQS_IT_RELEASE_NOTES, I_ROADMAP_EPIC.

Issue Tasks (trackor type `Issue_Task`): IT_DESCRIPTION, IT_TASK_TYPE ("Inquiry" for enhancement requests).

Similar past cases: ov_search on Cases with a distinctive phrase, e.g. `equal(C_TITLE, "copy-blobs-to-public-s3")` or a module/rule name, then read C_RESOLUTION and the chat of the closest ones. Say which past case matched and what fixed it.

Link to a trackor record: `https://trackor.onevizion.com/form/ConfigAppForm.do?id=<TRACKOR_ID>`.

## Working a case

Read the case, find the affected instance (C_WEBSITE, or from the text), and investigate there. Read every attachment (screenshots, .eml, logs) with read_file, not just the case text.

Before proposing any enhancement, check trackor for existing work: search Issue (VQS_IT_XITOR_NAME) and Issue_Task (IT_DESCRIPTION, with IT_TASK_TYPE = "Inquiry"), and check whether the case already has C_RELATED_ISSUE or C_RELATED_ISSUE_TASKS_. Name the closest matches in finish (existing) and say plainly whether they cover the request.

For each issue in the case: find the root cause with evidence, check whether it is still happening, and decide whether it needs a fix, a user action, or nothing (expected behavior).

Working order:

1. Understand what is actually being asked, which instance, which objects.
2. Investigate on the instance: current config, logs, data. Prefer facts over guesses.
3. Search Issue / Issue_Task when an enhancement or bug is involved.
4. Root cause with the evidence that proves it, and whether it is still happening now.
5. propose_change for every concrete change, with the current code as before.
6. finish with the findings, existing matches, unrelated problems and the reply.

Deliver: a short summary per issue that answers the question actually asked (unrelated problems go to the unrelated list, never mixed in); for a fix, where it is (object name, ID, link) and the fixed code as propose_change; and one comment for the case chat as `reply`.

## Reply style (the case chat comment)

Write it as a few short paragraphs separated by a blank line, always in this order:

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
- If a PROD change is needed and not yet applied, say what it is in one sentence and ask if it is ok to apply.
- ASCII only, no em dashes.

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
