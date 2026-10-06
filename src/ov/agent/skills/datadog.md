---
title: Datadog
description: Read before using any dd_ tool: instance servers and roles, which tool answers what, and UTC times.
---

The Datadog tools (dd_logs, dd_metrics, dd_monitors, dd_events, dd_apm) are available only when the user connected Datadog in Settings. Each takes an instance and applies that instance's servers, listed in the prompt with their roles (for example web and app), so pass the instance, not raw host tags. Add role to look at one kind of server only, such as role=app for background jobs or role=web for page requests. Times are UTC; OneVizion dates are usually the instance's local time, so state which one you mean.

Use Datadog when the question is about the server rather than the configuration: slowness, timeouts, errors users see in the browser, outages, out-of-memory, a spike after a release, "it worked yesterday". For configuration questions (a rule, a field, an import mapping) the instance itself is the source of truth; Datadog only adds the server-side view.

How to work with it:
- Start narrow in time. Find when the problem happened from the case, PROCESS rows or the user's message, then query a window around it (for example 30 minutes before to 30 minutes after). Widen only if you find nothing.
- dd_monitors first for "is something down or alerting", then dd_events for deploys and restarts in the same window, then dd_logs with status:error and patterns=true to see what actually failed, then dd_logs without patterns on the top group to read real lines.
- Line Datadog up with OneVizion: a failed import or rule in PROCESS at 14:02 should be matched with errors in dd_logs around 14:02 (mind the time zone), and slow pages with dd_apm mode=slowest and dd_metrics (avg:system.cpu.user, avg:jvm.heap_memory, max:system.disk.in_use). Add "by {host}" to a metric to see which server stands out.
- Quote what you found with its time and a short excerpt; never paste long log dumps into the reply. Include the Datadog link the tool returned when it helps the reader.
- If a tool says the instance is not matched, tell the user to pick its servers in Settings > Integrations > Datadog, or search with an explicit query such as host:name*.
- If a tool says the key lacks a scope, say which one and carry on with what you can read.
- Logs can contain customer data. Use them to reason; do not copy personal data (emails, names, ids of people) into findings or replies.
