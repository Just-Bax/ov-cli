![OV CLI](assets/banner.jpg)

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#install)

[Install](#install) | [Sign in](#sign-in) | [Full API coverage](#full-api-coverage) | [Sending data](#sending-data) | [Settings](#settings) | [Read-only mode](#read-only-mode) | [The agent](#the-agent) | [Exit codes](#exit-codes) | [Use from an AI agent](#use-from-an-ai-agent) | [Contributing](#contributing)

Command line client for the [OneVizion](https://onevizion.com) API.

Installs as the package `ov-cli` and gives you an `ov` command.

You sign in through a browser window, exactly as you would to use the app. From then on
every endpoint your account can reach is a command, generated from your own instance's
OpenAPI schema, so the coverage matches the server you are actually pointed at rather
than a list someone wrote down. Every command takes `--json`.

```console
$ ov login https://acme.onevizion.com
Logged in to https://acme.onevizion.com as acme (session credential).
Token expires 2026-08-25T13:56:23.
214 API operations available. Try 'ov api tags'.
Now the default instance. Target another with 'ov -i <alias> ...'.

$ ov api tags
OneVizion API (214 operations)
┏━━━━━━━━━━━━━━━━━┳━━━━━┓
┃ Tag             ┃ Ops ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━┩
│ auth-token      │   1 │
│ schema          │   2 │
│ trackor-types   │  14 │
│ users           │   5 │
│ ...             │     │
└─────────────────┴─────┘

$ ov schema get-trackor-types --table
$ ov trackor-types read-trackor CONTRACT 12345
$ ov users get-user-by-id 42 --json | jq .email
$ ov -i globex users get-user-by-id 42     # a different OneVizion system
```

## Install

You do not need Python or anything else installed first.

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Just-Bax/ov-cli/master/install.ps1 | iex
```

**macOS / Linux**:

```bash
curl -fsSL https://raw.githubusercontent.com/Just-Bax/ov-cli/master/install.sh | sh
```

Then open a **new** terminal and run `ov login https://yours.onevizion.com`, or `ov agent`
to do everything from the browser.

The installer fetches [uv](https://docs.astral.sh/uv/), which supplies its own Python, then
installs `ov` into an isolated environment and downloads the browser used for signing in
(about 150MB, once).

If that step is skipped or interrupted, `ov setup` does it, and `ov login`
fetches it itself rather than failing.

<details>
<summary>Already have Python tooling?</summary>

```bash
uv tool install --force --reinstall-package ov-cli \
  "ov-cli @ https://github.com/Just-Bax/ov-cli/archive/refs/heads/master.zip"
ov setup
```

Or from a clone, for development:

```bash
pip install -e .
ov setup
```
</details>

### Updating

```bash
ov update           # fetch and install the latest version
ov update --check   # only say whether one is available
```

`ov update` uses git with your own GitHub access, so it also works while the repo is
private. From a clone (`pip install -e` or `uv tool install --editable`) it fast-forwards
the clone, and stops without touching your work if your local changes conflict; it
reinstalls when dependencies changed or a required package is missing. Otherwise it reinstalls `ov` from the latest
commit on GitHub. On Windows the reinstall finishes a few seconds after the command
exits, because a running `ov` cannot replace itself; the log is in `~/.ov/update.log`.
Settings, sign-ins and agent history in `~/.ov` are kept.

After installing, `ov update` upgrades the agent database (`ov agent --migrate` does the
same by hand), keeping a copy of the old one next to it as `agent.<revision>.bak.db`. A
running `ov agent` still uses the old layout, so the upgrade waits while one is open:
stop it and start `ov agent` again, and it upgrades the database on start. An older
`ov agent` and a newer one never share the database during an upgrade.

Re-running the install command works too.

### Uninstalling

```bash
uv tool uninstall ov-cli
```

Your settings in `~/.ov` are left alone; delete that folder to remove them.

## Sign in

```bash
ov login https://acme.onevizion.com
```

A browser window opens on the real OneVizion login page. Sign in there and it closes on
its own once you are through.

Single sign-on works unchanged. The wait does not watch the address bar, because with an
external identity provider most of the login happens on someone else's domain and comes
back through a redirect chain. Instead it asks your instance for a token once a second,
from every open tab that is on your host, until one says yes. Microsoft Entra, Okta, SAML
and MFA prompts all just take however long they take, up to `--timeout` seconds
(default 300).

If the instance refuses to issue a token even though you are signed in, the command says
so within a few seconds instead of waiting out the timeout, and names the likely cause.
`ov login <url> --verbose` prints each attempt: which tabs are open, and exactly what each
of the three token requests got back.

The commonest cause is the account lacking the **Widget** module at Read, which is what the
token endpoint requires.

Your password is typed into the real login page. This tool never reads it, never asks for
it, and never writes it anywhere. Token requests only ever go to the host you named, never
to the identity provider.

What gets stored is a **web session token**: the CLI asks the app for one the same way
the built-in widgets do, and it carries exactly your privileges. It dies with your web
session, and `ov logout` revokes it on the server rather than just forgetting it.

Tokens are short-lived. The CLI re-mints one automatically from your session whenever the
old one is close to expiry or the server rejects it, so you rarely see this. Once the web
session itself ends, commands exit 3 and you run `ov login` again.

### More than one system

Sign in to as many instances as you like. Each is stored separately, named after the
first label of its hostname, and the most recent login becomes the default.

```bash
ov login https://acme.onevizion.com          # -> alias "acme"
ov login https://globex.onevizion.com        # -> alias "globex", now the default
ov login https://qa.acme.onevizion.com --as qa
```

```console
$ ov instances
┏━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃   ┃ Alias  ┃ URL                           ┃ Mode    ┃ Expires             ┃
┡━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│   │ acme   │ https://acme.onevizion.com    │ session │ 2026-08-25T13:56:23 │
│ * │ globex │ https://globex.onevizion.com  │ session │ 2026-08-25T14:02:11 │
│   │ qa     │ https://qa.acme.onevizion.com │ token   │ -                   │
└───┴────────┴───────────────────────────────┴─────────┴─────────────────────┘
```

Pick one per command with `-i`, before or after the subcommand:

```bash
ov -i acme api tags
ov users get-user-by-id 42 -i qa
OV_INSTANCE=acme ov schema get-trackor-types
```

Or change the default:

```bash
ov use acme
```

`-i` accepts the alias, the hostname, the full URL, or any unambiguous prefix of them, so
`-i acme`, `-i acme.onevizion.com` and `-i https://acme.onevizion.com` are the same
instance. If a prefix matches two, the error lists both.

Each instance keeps its **own** cached schema, so the generated commands reflect the
system you are actually pointed at. A group that exists on one and not another is
reported as such rather than as a bare "invalid choice".

```bash
ov tenants               # tenants reachable on the current instance
ov instances --check     # call each one to see whose token still works
ov whoami qa             # detail for one instance
ov logout acme           # revoke and forget one
ov logout --all          # all of them
```

Logging out of an instance also deletes everything kept for it on this computer: its
secrets, cached schema, Instance map and Datadog servers. Agent runs are kept. `ov agent` does the
same on start for anything left over from instances you are no longer signed in to.

### Instances with several tenants

A OneVizion host can run many tenants, and a tenant is a Program. Your account
belongs to exactly one of them; what spans tenants is your **email**, with a separate user
in each. Signing in always lands you in your own tenant, and the token you get is scoped
to it, so the others are only reachable by switching first.

```bash
ov tenants                                        # what this account can reach here
ov login https://acme.onevizion.com --tenant North
ov -i acme/north api tags
```

Each tenant is stored separately and aliased `host/tenant`. The bare host alias keeps
meaning the tenant you sign in to, so nothing changes on single-tenant instances:

```console
$ ov instances
┏━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃   ┃ Alias              ┃ URL                               ┃ Mode    ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ * │ acme       │ https://acme.onevizion.com │ session │
│   │ acme/north │ https://acme.onevizion.com │ session │
└───┴────────────────────┴───────────────────────────────────┴─────────┘
```

`-i` takes the tenant name on its own too, so `-i north` is enough when it is unambiguous.

`--tenant` only works where a user with your email already exists in the target tenant,
and only with a browser sign-in: an API token is issued inside one tenant and cannot move.

### Without a browser

If you have an API token from **Admin > Auth Tokens** (type API), use it instead:

```bash
ov login https://acme.onevizion.com --token AbCdEf1234GhIjKl5678:MnOpQr90StUvWx...
```

Pass `--token -` to read it from stdin instead, so it stays out of your shell history and
the process list. That token does not expire, so nothing is re-minted and `ov logout` only
deletes the local copy. Invalidate it in the admin page when you are done with it. Session-mode and
token-mode instances can be signed in at the same time.

```bash
ov setup      # re-download the sign-in browser if it goes missing
```

## Full API coverage

`ov` does not ship a hand-written list of endpoints. On login it downloads
`/api/docs/openapi` from your instance and caches it, then builds commands from it. An
instance on a newer release, or with an endpoint yours does not have, gets the commands
it actually serves.

There are three ways into the same set of operations.

### Generated commands

```bash
ov api tags                       # the groups
ov users                          # the commands in one group
ov users get-user-by-id --help    # its real parameters, from the schema
ov users get-user-by-id 42
```

Path parameters are positional, in the order the endpoint declares them. Everything else
is a flag named after the parameter:

```bash
ov trackor-types search-trackors CONTRACT --fields "TRACKOR_KEY,STATUS" --page 1
```

### By reference

```bash
ov api list                       # every operation
ov api list trackor               # search name, path and summary
ov api show trackor-types:read-trackor
ov api schema users:create-user   # the request body's shape
ov api call users:get-user-by-id -p user_id=42
```

`ov api call` is the same machinery with `-p`, `-q` and `-H` instead of generated flags.
It is what to use in a script, since its spelling does not change with the schema.

### Raw

```bash
ov request GET /v3/schema/trackor_types
ov request POST /v3/trackor_types/CONTRACT/trackors -d @new.json
```

`ov request` skips the schema entirely. Use it for endpoints the schema does not describe,
such as the internal API, or when the schema cannot be read at all.

## Sending data

Bodies come from `--data`, or are built up from `--field`:

```bash
ov api call users:create-user -d '{"user_name": "jsmith", "email": "j@acme.com"}'
ov api call users:create-user -d @user.json
cat user.json | ov api call users:create-user -d -

ov api call users:create-user -f user_name=jsmith -f email=j@acme.com
ov api call users:create-user -f 'user_name=jsmith' -f 'roles:=["ADMIN"]'
ov api call trackor-types:create-trackor -p trackor_type=CONTRACT -f fields.STATUS=Open
```

`NAME=VALUE` stores a string, `NAME:=VALUE` parses the value as JSON, and a dotted name
nests. Files upload with `--file field=@path`.

Nothing is sent until you say so:

```bash
ov users get-user-by-id 42 --dry-run
```

## Reading responses

```bash
ov schema get-trackor-types              # highlighted JSON
ov schema get-trackor-types --json       # plain JSON, pipe-safe
ov schema get-trackor-types --table      # a table, when the response is a flat list
ov api call reports:export-report -p report_id=7 --out ./report.xlsx
ov request GET /v3/server_info --raw     # the body exactly as it arrived
```

`--json` never colours or wraps, so `ov ... --json | jq` is always safe.

## Settings

```bash
ov config                                    # show settings, paths and signed-in instances
ov config set spec_ttl_seconds 3600
ov config clear-cache
ov spec fetch                                # re-read the API schema now
```

| Setting | Default | Purpose |
|---|---|---|
| `spec_group` | `v3` | which OpenAPI group to generate commands from |
| `download_dir` | `~/.ov/downloads` | where `--out` lands when given a bare name |
| `cache_ttl_seconds` | `0` (off) | how long GET responses are reused |
| `spec_ttl_seconds` | `86400` | how long the schema is reused before refetching |
| `timeout_seconds` | `60` | HTTP timeout |
| `color` | `true` | coloured output |
| `verify_tls` | `true` | verify TLS certificates |

Response caching is off by default, because a stale trackor is worse than a second
request. Turn it on with `ov config set cache_ttl_seconds 600`; only bodiless GETs are
cached, and entries are keyed per instance. Pass `--refresh` to any command to ignore both
the response cache and the schema cache for that run.

## Read-only mode

Set `OV_READONLY=1` to make `ov` refuse anything that could change data:

```bash
OV_READONLY=1 ov request GET /v3/server_info      # allowed
OV_READONLY=1 ov request DELETE /v3/users/7       # exit 7
```

Allowed: every GET, trackor searches, `POST /v3/sql/test` (SELECT only) and component
exports. Web UI requests are limited to the API schema and sign-out. Everything else stops
with exit 7 before a request is sent. Useful when handing `ov` to an AI agent.

## The agent

```bash
ov agent          # or: ov ui
```

Starts a local web app at http://127.0.0.1:5180 and opens it in your browser: OV Agent,
a chat with an AI Tier 3 engineer that works on your OneVizion instances through `ov`.

- **Support cases:** type a case number or paste a trackor link. It reads the whole case
  from trackor.onevizion.com (fields, chat, attachments, emails), moves to the affected
  instance, finds the root cause with evidence, checks existing Issues, proposes fixes as
  diffs, and writes the reply for the case chat.
- **Anything else:** ask a question ("which rules failed in the last 24 hours?"), paste
  errors, attach screenshots, emails or logs.

It shows each API call and SQL query it makes, and ends an investigation with findings and
the evidence it checked.

The first screen walks you through setup:

1. Sign in to GitHub. The agent runs on GitHub Copilot, so the account needs a Copilot
   subscription; you pick the model.
2. Sign in to at least one instance (the same browser sign-in as `ov login`).
3. Pick a main model. It can be changed per run. In Settings you can also pick a fast
   model (Haiku, for example) for small chores such as naming runs.

Setup stays open until the last step, so signing in to GitHub does not skip the others.

Read-only by default: every call runs with `OV_READONLY=1`. Turn on **Allow changes** for
a run and the agent may apply changes, but each one shows you the exact `ov` command and
waits for your **Approve**.

In **Settings**:

- **Skills** are guides for the agent. Core skills (OneVizion Basics, Working Style, OV
  CLI and Workspace) are always in the system prompt, so the first query already uses the right tables
  and tools. The rest are listed by name and when to read them, and the agent loads one
  with `skill_read` when a task needs it, so reviewing an incident reads PagerDuty and
  Datadog first. A skill becomes core with `core: true` in its front matter. Seven ship with
  `ov`: OneVizion Basics
  (where rules, automations, notifications, imports, reports, modules and workflows live,
  and how their runs and errors are logged), Working Style, one skill per tool group (OV
  CLI, Workspace, Datadog, PagerDuty; the last three only while set up), and TCE Best
  Practices (trackor cases, the troubleshooting workflow, the case reply style). These
  bundled skills are read-only and update with `ov`; switch any off, or **Clone to edit**
  one (the copy is yours to change and the original turns off), or write your own.
- **Workspace** is one folder with your code (for example the platform repo and your
  Vizion Hub modules side by side). The agent searches, reads, edits and creates files and
  runs commands (git, builds, tests) only inside it. Add notes so it knows where things
  are. See [Coding in the workspace](#coding-in-the-workspace).
- **Instances** lists your `ov` sign-ins and signs in to new ones, on the instance's own
  login page shown inside the app (or in a separate window), or with an API token (access
  key and secret key from Admin > Auth Tokens).
- **Cost** shows what the agent costs in Copilot credits: your Copilot plan and the credits
  used this billing cycle across all your Copilot use, then OV Agent's own credits, requests
  and tokens per day, per model and per thread. The numbers are the credits Copilot reports
  for each request; threads from before usage was recorded show "Not tracked".

Preferences also hold the **Reasoning** level (how hard models think; each model gets the
nearest level it supports) and what **messages while working** do: steer (picked up at the
next step) or queue (sent after the turn). Ctrl+Enter sends the other way.

In a thread:

- The header shows its credits (hover for tokens and models) and a **...** menu: pin, snooze,
  export as Markdown, settle, and delete (removes its messages and files for good). Click the instance in the subtitle for its sign-in
  state and to check its platform version and response time.
- Mentions like "rule 123" link to their page on the instance when that ID appeared in the
  agent's tool results; links to IDs it never looked up get a warning.
- The envelope under an answer writes it as a case reply in your reply style.
- Ctrl+F finds text anywhere in the thread, including turns not loaded yet.

Each sidebar thread has the same **...** menu. Snooze offers in 1 hour, in 3 hours, tomorrow,
next week or a custom time; snoozed and settled threads wait in their own shelves at the
bottom. Undo any of these from the toast or with Ctrl+Z for five seconds. Ctrl+K opens the
command palette; press ? for every keyboard shortcut.

The agent's tools come in groups, and the system prompt lists the ones a run has:

| Group | Tools |
| --- | --- |
| OV CLI | `ov` (any ov command), `ov_sql`, `ov_export` (component export to workspace files), `ov_import` (component import from an export file; dry run first, then approval), `ov_search` (trackor search), `ov_map` (Instance map lookup), `ov_case` (a trackor support case) |
| Workspace | `ws_list`, `ws_search`, `ws_read`, `ws_edit`, `ws_write`, `ws_run` (only while a workspace folder is set) |
| Datadog | `dd_logs`, `dd_metrics`, `dd_monitors`, `dd_events`, `dd_apm` |
| PagerDuty | `pd_incidents`, `pd_incident`, `pd_oncall`, `pd_directory`; with changes allowed also `pd_note`, `pd_ack`, `pd_resolve`, `pd_escalate`, `pd_reassign`, `pd_snooze` |
| Skills | `skill_read` |
| Run | `run_read` (attachments, exports and long output in the run folder), `run_ask`, `run_report` |

Nothing leaves your machine except calls to your instances and to GitHub Copilot. The
server listens on 127.0.0.1 only. History and uploads live in `~/.ov/agent`; the
GitHub token is kept in the vault with your other credentials.

### Coding in the workspace

1. Settings > Workspace: enter the folder, for example `C:\Projects\OneVizion`, and a few
   notes ("ov/ is the platform repo, Modules/ holds Vizion Hub modules; clone new ones
   there"). Save.
2. Ask for code work in a normal run: "Clone the sftp module into Modules and add retry to
   the upload", "Why does TestSqlApiControllerV3 reject this query?", "Fix the failing rule
   package and run its tests". The agent finds files with `ws_search`, reads them with
   `ws_read`, changes them with `ws_edit` and `ws_write`, and runs `git`, builds and tests
   with `ws_run`. Every step shows up in the run.
3. Commands run straight away, except ones that delete files, push, rewrite git history,
   stop processes, publish packages, run downloaded code or touch paths outside the
   workspace. Those wait for your Approve, showing the exact command and folder.
4. **Workspace** in the sidebar browses the folder and opens files in an editor: edit, then
   save with Ctrl+S. "Ask the agent" there starts a run about the open file.

GitHub work (pull requests, their diffs, review comments, checks, issues) goes through the
`gh` CLI in the workspace: install it and run `gh auth login` once. Reading is free; posting
a comment or review, creating, merging or closing anything, or `gh api` writes wait for
your approval.

The agent commits only when you ask and never pushes on its own. Paths in the `ws_` tools
cannot leave the workspace; a shell command could, which is why those need your approval.

**Instance map** shows how an instance's configuration fits together: trackor types and
their relations, fields, rules and what triggers them, automations, imports, reports,
notifications, workflows and modules, plus the fields each rule, import and report uses in
its SQL. Pick an instance and Build: it reads the configuration with read-only SQL (about a
minute on a large instance, Test SQL privilege needed) and caches it in `~/.ov/agent/graphs`.
Start from a hotspot or search, double-click an object to bring in what it links to, and use
"Ask the agent" on any object. The agent uses the same map in runs (`ov_map`) to see
what depends on something before it touches it. Links found in SQL text are best-effort.
DB packages are objects on the map too: their bodies come from one component export, so a package
links to the fields, trackor types and packages it uses and to the rules that call it. Only
clean references count as links: quoted names (`'P_STATUS'`), config ids, `id.*` object
references (`id.project.cf.p_status`, `id.get('id.site.tt')`) and `PACKAGE.procedure` calls.

**Explorer** is a read-only code browser over the same map. Pick a rule, DB package,
trackor type, import, report, workflow, automation or notification in the tree to open its
code in a tab. References in the code sit on a pill in their object's color: hover for a
card with what it is and how it is referenced, click to open. The panel on the right shows
status and trigger, quick static checks (SELECT INTO without a no-data handler, queries
inside loops, COMMIT in a rule, swallowed errors, unknown hard-coded ids and similar),
recent runs and errors, and everything the object links to.

Every object, on the map, in the Explorer and in a code hover card, has the same actions:
**Ask the agent** opens New run with a prompt filled in for you to edit and send, **Open in
Explorer** opens its code, **Show on map** jumps to it on the Instance map, and the arrow
opens it in OneVizion. The Explorer adds **Review with AI** for objects with code.

**Datadog** (optional) adds the server side. In Settings > Integrations, connect it with
your own keys: an **API key** (Organization Settings > API Keys) and an **application key**
from Personal Settings > Application Keys, ideally limited to the read-only scopes the
connect dialog lists (`logs_read_data`, `logs_read_index_data`, `metrics_read`,
`timeseries_query`, `monitors_read`, `events_read`, `apm_read`, `hosts_read`). The dialog
checks both keys, shows what the application key can read, and stores them in the OS
vault; nothing is written to the code or shared. Then pick the servers each instance runs
on, such as its web and app servers and replicas. **Detect servers** reads Datadog's host
list and groups hosts under the instance whose name appears in their host name after the
machine's own name (`web01.acme.example` and `app01.acme-vpc.example` belong to `acme`;
the longest instance name wins, so `acme` never takes `dev-acme`'s servers). Each server's
role is its machine name without the number (`web`, `app`). Adjust the chips, or write any
Datadog filter instead; a tenant shares its host's servers unless you give it its own.

Once connected, runs get read-only Datadog tools (`dd_logs` with message grouping,
`dd_metrics`, `dd_monitors`, `dd_events`, `dd_apm`), offered only for
what the key can read, with a `role` option to look at one kind of server.

The **Health** page shows one instance at a time, each card loading on its own: a verdict
with open incidents, alerting monitors, error logs against the previous window, peak p95,
failed OneVizion processes and the busiest server; a timeline of requests, p95 and error
logs with incidents, Datadog events (deploys, restarts) and failed runs marked under it, so
you see what lined up; incidents you can expand for the alert and its timeline; every
server with a trend line per metric; top error groups; failed runs by type; slowest
endpoints; monitors and events. Every card has Ask, which opens New run with a prompt
about that card. A card your account or key cannot read says so instead of failing, for
example failed runs on an instance where you lack the Test SQL privilege. Nothing on the
page writes to Datadog, PagerDuty or the instance.

Your Datadog admins can see application keys and may audit their use, and logs the
agent reads in a run go to GitHub Copilot like any other tool result.

**PagerDuty** (optional) adds incidents and on-call. In Settings > Integrations, connect it
with your account address (e.g. `yourcompany.pagerduty.com`, which also picks the US or EU
region) and a personal **API user token** from My Profile > User Settings > Create API User
Token. The token is checked and stored in the vault. There is
nothing to map: services are shared, so each incident is tied to an instance by what its
alert names - OV monitoring's `website` field, the database on database alerts (learned from
website alerts that carry both), or the host or `[Instance]` tag in a Datadog alert. Runs get `pd_incidents`,
`pd_incident` (timeline, alerts and notes) and `pd_oncall`, and Health shows
open and recent incidents and who is on call for the policies that paged, and counts
triggered incidents in its verdict, even before the instance is matched in Datadog.

With **Allow changes** on for a run, the agent can also change incidents: add notes,
acknowledge, resolve, snooze, escalate to a level, and reassign to another escalation policy
or to people (pd_directory finds them by name). Each change waits for your Approve, and
PagerDuty records it as you. These need a full-access user token; a read-only one is refused
with a message saying so. PagerDuty admins can see and revoke user tokens.

`ov agent --port 5181` picks another port; `--no-open` skips opening the browser.

## Files on disk

Everything lives in `~/.ov` (`ov --home` prints the path, `OV_HOME` overrides it):

```
~/.ov/
  config.json      settings and the list of signed-in instances, no secrets
  browser/         Playwright profile, so login remembers you
  spec/            cached OpenAPI schema, one file per instance and group
  cache/           cached API responses
  downloads/       files written by --out
  agent/           agent history (agent.db), run folders, uploads, Instance maps
  vault            every secret, encrypted
```

Bearer tokens, session cookies and integration keys live in `~/.ov/vault`, encrypted with
AES-256-GCM. Its key is the only entry in the OS keyring (Windows Credential Manager, macOS
Keychain, or the Secret Service on Linux). Without a keyring, `ov` stops and asks for
`OV_CREDENTIALS=file`, which keeps the key in `~/.ov/vault.key`, owner-only. A vault whose
key is gone cannot be read; delete it and sign in again.

Directories are created owner-only and files are replaced atomically under a lock, so two
`ov` processes refreshing tokens at once cannot corrupt the config. On Windows the
permission bits are not enforced; your profile's ACL is what protects `~/.ov` there.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | general error, including an instance that could not be reached |
| 2 | bad command line |
| 3 | not logged in, or the session expired |
| 4 | no such operation, record or instance |
| 5 | the API returned an error, or the schema could not be read |
| 6 | authenticated, but the server answered 403 |
| 7 | blocked by read-only mode (`OV_READONLY`) |
| 8 | the agent database needs an upgrade but a running `ov agent` has it open |

## Privileges

The CLI can only reach what your account can. Three matter for the CLI itself:

| Module | Priv | Needed for |
|---|---|---|
| Widget | Read | minting the web session token, so `ov login` without `--token` |
| API Docs | Read | reading the schema, so the generated commands and `ov api` |
| Web Services | Read | essentially every `/api/v3` endpoint |

Without **API Docs** you still get `ov request`. Without **Widget** you can still sign in
with `--token`.

Note that OneVizion does not answer 403 for every privilege failure. A missing field-level
privilege comes back as HTTP 500 with an explanatory message, so it surfaces as exit 5
rather than exit 6. Read the message, not the exit code, when a call is refused.

## Use from an AI agent

`ov agent` is the built-in one. To use `ov` from another agent (Claude Code, Copilot CLI,
your own): every command speaks `--json` and maps failures onto distinct exit codes, so `ov`
works as a tool. [`SKILL.md`](SKILL.md) is the brief: auth model, how to discover
endpoints, JSON shapes, exit codes, and the operations the agent should leave to you.

It is told not to run `ov login`, which waits on a browser window, and not to read the
stored credentials. Run the agent with `OV_READONLY=1` if it should only look.

## Contributing

Issues and pull requests are welcome.

```bash
git clone https://github.com/Just-Bax/ov-cli
cd ov-cli

uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
uv run --extra dev ruff format --check src tests
```

CI runs the same on Windows, Linux and macOS with Python 3.11 to 3.13.

The agent's UI is React in `web/`. Its build is committed to `src/ov/agent/static`, so
installing `ov` never needs Node. After changing it:

```bash
cd web
pnpm install
pnpm dev          # http://localhost:5179, proxies /api to a running `ov agent`
pnpm check        # typecheck + prettier
pnpm build        # writes src/ov/agent/static; commit the result
```

CI fails if the committed build does not match `web/`.

The layout follows the request path: `client.py` speaks HTTP and owns the two auth
schemes, `auth.py` mints tokens, `session.py` keeps one credential set per instance and
resolves what `-i` names, `spec.py` turns the OpenAPI document into the `Operation`
objects everything else works from, `invoke.py` maps command line input onto one HTTP
request, `service.py` is the only API access the commands get, and `cli/commands/` holds
one module per command group. `cli/dynamic.py` is what turns a schema tag into commands.
`agent/` is the agent server: `server.py` (HTTP API and the built UI), `run.py` (the
model loop), `tools.py` (what the model may call, each `ov` call a read-only subprocess),
`copilot.py`, `skills.py` and `project.py` (the code workspace). `agent/state.py` mirrors `web/shared/reduce.ts`.

The agent database is SQLite at `~/.ov/agent/agent.db`, accessed through SQLAlchemy in
`agent/db.py`, with the tables declared in `agent/models.py`. Alembic migrations live in
`agent/migrations/versions` and run when the agent first opens the database; before
upgrading an existing database it writes a copy next to it as `agent.<revision>.bak.db`.
To change the schema, edit `models.py`, then generate and review a migration:

```bash
uv run alembic revision --autogenerate --rev-id 0003 -m "what changed"
```

`alembic.ini` points the command at `~/.ov` (or `OV_HOME`), so set `OV_HOME` to a scratch
folder while generating. `test_models_match_the_migrations` fails if the models and the
migrations disagree.

Tests use a recorded OpenAPI document and a mock transport, so `pytest` never touches the
network. `test_login_browser.py` is the exception: it starts a real headless Chromium
against a local stand-in for OneVizion, because the sign-in wait depends on how Playwright
delivers browser events and that cannot be checked with fakes. It skips itself if the
browser is not installed.

The wordmark, mark, app icon, colors and artwork are in `brand/`; open `brand/index.html`.

## License

[Apache-2.0](LICENSE) - Copyright 2026 Isfandiyor Baxtiyorov. See [NOTICE](NOTICE).

This is an unofficial client. It is not affiliated with, endorsed by, or supported by
OneVizion, Inc. It reads only what your own account can already see, using your own
session.

The license covers this code only. It grants no rights in the OneVizion name or marks,
the OneVizion platform, its API, or any instance; access to an instance is governed by
your own agreement with its operator.
