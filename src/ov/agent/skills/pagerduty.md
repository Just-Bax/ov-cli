---
title: PagerDuty
description: Use before any pd_ tool, or when a case or question mentions an incident, an alert, an outage or who is on call.
---

The PagerDuty tools (pd_incidents, pd_incident, pd_oncall, pd_directory) are available only when the user connected PagerDuty in Settings. PagerDuty services are usually shared by many instances, so incidents are tied to an instance by what their alert names: a website field, a database, or a Datadog host. pd_incidents takes an instance; all_instances=true lists everything. Times are UTC.

When to use them:
- A case or question says something is down, slow, erroring for everyone, or "since this morning": check pd_incidents for the instance around that time, open ones first (statuses triggered and acknowledged).
- Someone mentions an incident number or PagerDuty link: read it with pd_incident.
- The user asks who is handling something or who to contact: pd_oncall.

How to work with them:
- Read the incident's timeline and alerts. Alerts raised by Datadog monitors carry the monitor name and query: follow up with dd_monitors, dd_logs and dd_metrics for the same window, and with failed OneVizion processes (PROCESS) on the instance.
- State the incident by number, status and times, e.g. "PagerDuty #12345, triggered 14:02 UTC, resolved 14:40". Link it.
- An incident shows that an alert fired, not why. Find the cause on the instance and in Datadog before claiming one.
- If nothing is found for an instance, search all_instances=true with a query (the database or server name) before concluding there was no incident.
- Do not copy on-call people's names, phone numbers or emails into case replies; name the team or escalation policy instead.

Changing incidents (only when the user allowed changes for this run; each change waits for their approval):
- pd_note adds a note: what you found, the cause, links to evidence. Notes are the record; write them in plain sentences.
- pd_ack acknowledges, pd_resolve resolves (add a note with the cause first), pd_snooze snoozes an acknowledged incident.
- pd_escalate moves an incident to a level of its escalation policy; check the levels with pd_oncall first.
- pd_reassign moves it to another escalation policy (for example a regional team) or to people. Find the exact names with pd_directory first; the tool refuses names that match more than one.
- Never change an incident the user did not ask about. Every change is recorded in PagerDuty as the user.
- If changes are off, say exactly what you would do and let the user turn on "Allow changes".
