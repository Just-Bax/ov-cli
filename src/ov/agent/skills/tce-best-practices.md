---
title: TCE Best Practices
description: Working OneVizion support cases as a Tier 3 engineer - trackor, the workflow, and how to write the case reply.
---

## Trackor ticketing

trackor.onevizion.com is the ticket system. Pass `instance: "trackor.onevizion.com"` for anything on it. To read a whole case use load_case; a bare case number or case link from the user is loaded for you before you start.

Cases (trackor type `Cases`, plural): the support ticket. The case number is XITOR_KEY (comes back as TRACKOR_KEY); TRACKOR_ID is a different, long internal id.

- C_TITLE, C_DESCRIPTION_MEMO, C_PROBLEM, C_TYPE (Event, Change Request, Config Event, NOC Event, Question, ...), C_STATUS, C_SEVERITY.
- C_WEBSITE: the customer instance host the case is about. C_SERVER_URL sometimes too.
- C_ICC_LOG_WIKI: internal comment log. C_COMMENT_LOG_WIKI: public comments.
- C_OWNER: Tier 1 owner (CSM). C_DEV_OWNER: Tier 3 owner (TCE).
- C_RELATED_ISSUE, C_RELATED_ISSUE_TASKS_: linked development work.
- C_RESOLUTION, C_ROOT_CAUSE_DETAILS: filled on past solved cases; useful for similar-case search.

Issues (trackor type `Issue`): development work. VQS_IT_XITOR_NAME (summary), VQS_IT_STATUS, XITOR_CLASS_ID (Bug, New Feature, Improvement), I_PLANNED_VERSION, VQS_IT_RELEASE_NOTES, I_ROADMAP_EPIC.

Issue Tasks (trackor type `Issue_Task`): IT_DESCRIPTION, IT_TASK_TYPE ("Inquiry" for enhancement requests).

Similar past cases: trackor_search on Cases with a distinctive phrase, e.g. `equal(C_TITLE, "copy-blobs-to-public-s3")` or a module/rule name, then read C_RESOLUTION and the chat of the closest ones. Say which past case matched and what fixed it.

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

Follow exactly:

- Start with a direct Yes or No, then the reason, then anything else. No lead-in sentence.
- Write as I, never we.
- One paragraph of flowing text. No line breaks inside a paragraph, no hard wrapping, no bullets. It is pasted into a chat box.
- Short. Cut every sentence that does not change what the customer does next. No restating their question, no explaining how you investigated, no counts or IDs unless they matter to them.
- Plain language, not technical. No table names, no field IDs, no code.
- No greeting, no thanks, no sign-off, no em dashes, ASCII only.
- Only cover what the case asked. Extra findings go in the comment only if the user asks for them.
- If a PROD change is needed, describe it in one sentence and ask if it is ok to apply.
