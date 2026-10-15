---
title: Issue Life Cycle
description: Use to tell where a development issue stands, whether a fix has reached a customer's version, or which version or backport will carry it.
---

An Issue on trackor.onevizion.com moves forward as its Issue Tasks (ITs) are completed; most steps create the next IT automatically. Only "Opened" and "Canceled" are set by hand.

## Statuses (I:Status)

Pending (new, nothing to do) -> Opened (assigned) -> In Progress -> Code Review -> Ready for Merge -> Test -> Owner Review -> Completed. Side states: Awaiting Response (blocked on someone), Canceled (reason in the release notes). Completed means the main fix is done; backports may still be open.

## Issue Tasks in order

1. Dev: implementation. An issue can have several Dev ITs; all must be completed.
2. Implementation Review: development management reviews the result; corrections go back to the developer.
3. Code Review: a reviewer checks the code.
4. Branch Tests: the branch is tested; failed tests go back as fixes.
5. Merge: merged to master.
6. Test: QA tests the merged change. Bugs found create Bug ITs that are fixed and retested.
7. Completion Review: final review of the whole issue and its customer impact, then the issue is Completed.
8. Backport: created after completion when the fix must also reach older supported versions; completed by the developer and tested by QA.

Inquiry ITs sit outside this flow: questions or suspected bugs for development to look at.

## Versions

- Ver:Version on the issue starts as TBD and moves to the next release version when the issue reaches Test; a backport adds another version.
- Production releases come every two weeks. ESR (Extended Support Release) versions are picked a few times a year for customers who upgrade less often; the latest ESR gets bug-fix releases (for example 21.15.2, 21.15.3) through Backport ITs, created automatically for Bug issues from their Completion Checklist (I:Bug Reported Version, I:Bug Introduced Version).
- The Ver:Enterprise Support Release checkbox marks ESR versions. A version being the current ESR does not mean every customer runs it.

## Has the fix reached this customer?

1. Read the instance's version: `ov request GET /v3/server_info` on that instance.
2. Read the issue's status, Ver:Version / I_PLANNED_VERSION, and its Backport ITs with their versions and statuses.
3. The fix is there only if the issue (or its backport for that version line) is completed in a version at or below the instance's version on the same line. Otherwise say which version will carry it, or that no backport exists for the customer's ESR line.
4. Say what you checked: both versions and the IT that delivers the fix.
