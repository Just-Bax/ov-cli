---
title: PagerDuty
description: When and how to use PagerDuty incidents and on-call next to Datadog and OneVizion data.
---

The PagerDuty tools (pagerduty_incidents, pagerduty_incident, pagerduty_oncall) are available only when the user connected PagerDuty in Settings. pagerduty_incidents and pagerduty_oncall take an instance and use the PagerDuty services matched to its host; pass all_services=true to search every service. Times are UTC.

When to use them:
- A case or question says something is down, slow, erroring for everyone, or "since this morning": check pagerduty_incidents for the instance around that time, open ones first (statuses triggered and acknowledged).
- Someone mentions an incident number or PagerDuty link: read it with pagerduty_incident.
- The user asks who is handling something or who to contact: pagerduty_oncall.

How to work with them:
- Read the incident's timeline and alerts. Alerts raised by Datadog monitors carry the monitor name and query: follow up with datadog_monitors, datadog_logs and datadog_metrics for the same window, and with failed OneVizion processes (PROCESS) on the instance.
- State the incident by number, status and times, e.g. "PagerDuty #12345, triggered 14:02 UTC, resolved 14:40". Link it.
- An incident shows that an alert fired, not why. Find the cause on the instance and in Datadog before claiming one.
- If a tool says the instance is not matched, tell the user to match it in Settings > Integrations > PagerDuty, or search with all_services=true and a query.
- Do not copy on-call people's names, phone numbers or emails into case replies; name the team or escalation policy instead.
