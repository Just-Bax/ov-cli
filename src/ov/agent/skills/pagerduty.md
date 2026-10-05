---
title: PagerDuty
description: When and how to use PagerDuty incidents and on-call next to Datadog and OneVizion data.
---

The PagerDuty tools (pagerduty_incidents, pagerduty_incident, pagerduty_oncall) are available only when the user connected PagerDuty in Settings. PagerDuty services here are shared (OV-Monitoring, DataDog, ...), so incidents are tied to an instance by the website in their alert: OV monitoring alerts carry a website field, Datadog alerts name the host. pagerduty_incidents takes an instance; all_instances=true lists everything. Times are UTC.

When to use them:
- A case or question says something is down, slow, erroring for everyone, or "since this morning": check pagerduty_incidents for the instance around that time, open ones first (statuses triggered and acknowledged).
- Someone mentions an incident number or PagerDuty link: read it with pagerduty_incident.
- The user asks who is handling something or who to contact: pagerduty_oncall.

How to work with them:
- Read the incident's timeline and alerts. Alerts raised by Datadog monitors carry the monitor name and query: follow up with datadog_monitors, datadog_logs and datadog_metrics for the same window, and with failed OneVizion processes (PROCESS) on the instance.
- State the incident by number, status and times, e.g. "PagerDuty #12345, triggered 14:02 UTC, resolved 14:40". Link it.
- An incident shows that an alert fired, not why. Find the cause on the instance and in Datadog before claiming one.
- If nothing is found for an instance, search all_instances=true with a query (the database or server name) before concluding there was no incident.
- Do not copy on-call people's names, phone numbers or emails into case replies; name the team or escalation policy instead.
