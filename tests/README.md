# Tests

## Layout

- `conftest.py` - global fixtures: an isolated `OV_HOME` per test, `logged_in`, `two_instances`.
- `helpers/` - shared fakes and builders, imported as `from helpers.<module> import ...`
  (`tests` is on `pythonpath`).
- `fixtures/` - static test data (the OpenAPI document, legacy agent database rows).
- `unit/` - pure logic, no servers, CLI runs, git, subprocesses or browsers.
  Mirrors `src/ov`: `core/`, `onevizion/`, `agent/{api,engine,instances,integrations,storage,tools}/`.
- `integration/` - starts the agent HTTP server, runs the CLI end to end, uses real git repos,
  spawns subprocesses or drives a real browser. Everything here is marked `integration`;
  the Playwright test is also marked `browser` and skips when Chromium is not installed.

Fixtures used by one area live in that directory's `conftest.py`
(`unit/agent`, `integration/agent`, `integration/cli`). Test file names are unique across the tree.

## Running

```sh
uv run --extra dev pytest -q                                    # everything
uv run --extra dev pytest -q tests/unit                         # unit only
uv run --extra dev pytest -q -m "not integration"               # unit only, by marker
uv run --extra dev pytest -q -m integration                     # integration only
uv run --extra dev pytest -q -m "not browser"                   # skip the Playwright test
uv run --extra dev pytest -q tests/unit/agent/engine/test_state.py   # a single file
```
