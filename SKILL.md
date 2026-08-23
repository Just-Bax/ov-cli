---
name: ov
description: Read and change OneVizion data through the `ov` command line client, across one or many OneVizion instances. Use when the user asks about trackors, trackor types, config fields, imports, exports, integrations, reports, users, widgets or anything else in a OneVizion system, or asks to call the OneVizion API. Triggers on "OneVizion", "trackor", "trackor type", "onevizion.com", "our PPM system", "the OV API", "prod vs QA".
---

# ov

Command line client for the OneVizion API. It runs as the signed-in user and can see and
change exactly what that user can.

## Parse `--json`, and put the flag last

```bash
ov api list --json          # works
ov --json api list          # exit 2, unrecognized argument
```

Errors are JSON on stdout too: `{"error": "...", "exit_code": 5, "status": 400}`.

## Discover before you call

There is no fixed endpoint list. The commands are generated from the instance's own
OpenAPI schema, so **always look the operation up rather than guessing a path**.

```bash
ov api tags --json                     # the groups
ov api list --tag users --json         # operations in one group
ov api list trackor --json             # search name, path and summary
ov api show users:create-user --json   # parameters, body, method and path
ov api schema users:create-user --json # the request body's shape
```

`ov api show` returns `parameters` (each with `name`, `in`, `required`, `type`, `enum`)
and `usage`, the generated command to run.

## Calling

Two spellings for the same thing. Prefer `ov api call` in scripts: its arguments do not
change when the schema does.

```bash
ov api call users:get-user-by-id -p user_id=42 --json
ov api call users:get-user-by-un-or-email -q user_name=jsmith --json
ov api call users:create-user -d '{"user_name": "jsmith"}' --json
```

| Flag | Sets |
|---|---|
| `-p NAME=VALUE` | a path parameter |
| `-q NAME=VALUE` | a query parameter |
| `-H NAME:VALUE` | a header |
| `-d JSON` | the body, inline, `@file.json`, or `-` for stdin |
| `-f NAME=VALUE` | one body field; `NAME:=VALUE` parses JSON, a dotted NAME nests |
| `--file FIELD=@path` | a multipart upload |

The generated form takes path parameters positionally and everything else as named flags:

```bash
ov users get-user-by-id 42 --json
ov trackor-types search-trackors CONTRACT --fields TRACKOR_KEY --json
```

A parameter whose name collides with a CLI flag (`json`, `out`, `raw`, `field`, `data`,
`header`, `param`, `query`, `accept`, `refresh`, `table`) gets no generated flag. Reach it
with `-q` instead.

For anything the schema does not describe, including the internal API:

```bash
ov request GET /v3/schema/trackor_types --json
ov request POST /internal/... -d @body.json --json
```

## Check a write before making it

Every calling form takes `--dry-run`, which prints the request and sends nothing:

```bash
ov api call users:create-user -f user_name=jsmith --dry-run --json
```

Use it before any POST, PUT, PATCH or DELETE, show the user what it would send, and let
them confirm. Writes here change live business data.

## Session and instances

The user may be signed in to several OneVizion systems at once. Each has an `alias`, and
one is current.

```bash
ov instances --json    # [{alias, base_url, mode, expires, seconds_left, current}]
ov whoami --json       # the current one, plus "authorized": true|false
ov whoami acme --json  # a named one
```

**Check `ov instances` before acting when the user names a system** ("in prod", "on QA",
"the acme one"). Match what they said to an alias or hostname, then pass `-i <alias>` on
every call for that request. `-i` works before or after the subcommand and accepts an
alias, hostname, URL or unambiguous prefix.

```bash
ov -i acme api list --json
ov -i acme users get-user-by-id 42 --json
```

If the user does not name one, use the current instance and say which that was.

A host can carry several **tenants**, aliased `host/tenant` (`sandbox-2022/mtrac`). They
are separate instances as far as `-i` is concerned, and each holds different data. `ov
tenants --json` lists the ones reachable on an instance. A bare host alias means the
tenant the account signs in to.

Do not run `ov use`: it changes the default for the user's later shell commands too. Pass
`-i` instead, which affects only your call.

Generated command groups differ per instance, because each has its own schema. Exit 2
with "is not a group on instance 'X'" means you used another instance's vocabulary; re-run
`ov -i X api tags`.

If `authorized` is false, or any command exits 3, ask the user to run `ov login <url>`.
Do not run `ov login` yourself: without `--token` it opens a browser window and blocks for
up to five minutes waiting for a password, SSO redirect or MFA code.

Tokens are short-lived and the CLI re-mints them from the stored web session on its own.
Exit 3 means the web session itself is gone, which only the user can fix.

## Reading responses

```bash
ov api call schema:get-trackor-types --json          # JSON on stdout
ov api call schema:get-trackor-types --table         # a table, human mode only
ov api call reports:export-report -p report_id=7 --out ./report.xlsx
```

Responses are not cached unless the user turned it on, so repeated reads hit the server.
The API schema is cached for a day; add `--refresh` to re-read it if the user says an
endpoint was just added.

## Exit codes

| Code | Meaning | Do |
|---|---|---|
| 0 | success | |
| 1 | general error | Read the `error` string. |
| 2 | bad command line | Fix the invocation. |
| 3 | not logged in, or the session expired | Ask the user to run `ov login`. |
| 4 | no such operation, record or instance | Re-run `ov api list` or `ov instances` and pick a real one. |
| 5 | the API returned an error | Read `status` and `error`; the body is in `body`. |
| 6 | authenticated, but no privilege | Tell the user which module they need. |

Exit 4 on an operation ref lists near-misses. Correct your own ref before asking the user.

Exit 6 is not a bug to work around. The account lacks a OneVizion module privilege; say
which call failed and stop.

## Never

- Run `ov login`. It blocks on a human in a browser window.
- Read, print or copy `~/.ov/config.json`. It holds the live bearer token and session
  cookies. `ov config show --json` omits them deliberately.
- Run a write operation without showing the user a `--dry-run` first.
- Run `ov login --tenant` yourself: it opens a browser like any other sign-in.
- Assume two tenants on one host hold the same data. `sandbox-2022` and
  `sandbox-2022/mtrac` are different systems; check which one the user means.
- Run `ov logout`, `ov use`, `ov config set` or `ov setup` unasked. All four change state
  that outlives the conversation; `ov use` silently repoints the user's own shell.
- Assume the current instance is the one the user means when they named a system. Resolve
  it against `ov instances` and pass `-i`.
- Guess an endpoint path. Look it up with `ov api list` or `ov api show`; a wrong path on
  a POST is a silent no-op at best.
