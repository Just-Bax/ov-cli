# Code Style Rules

## Comments

- No comments and no docstrings anywhere in code: `.py`, `.ts`, `.tsx`, `.css`, `.yml`.
- Markdown is exempt, and so are the skills in `src/ov/agent/skills`.
- Name things well instead of explaining them. If code needs a comment, restructure it.

## Blank lines inside functions

- A computation and its own guard are one step. Keep them tight.
- Put a blank line between steps, and after a multi-line block that ends a step.
- A single-line `return` concluding a guarded value stays attached. A multi-line result construction gets a blank line before it.
- Functions with 6 or fewer body lines stay tight throughout.
- Never a blank line directly after `def`. Never two blank lines in a row.

```python
def resolve(model: str, language: str | None) -> str:
    served = _served(model)
    if language is None:
        return served[0]

    if language not in served:
        raise ValueError(f"unsupported language: {language}")

    return _engine_code(model, language)
```

## Other rules

- No fallbacks, no degraded modes. If something required cannot be found or run as configured, raise with a clear message. Never warn-and-continue, never swallow an exception.
- No magic values: tuning numbers, limits and URLs are named module-level constants.
- No backward compatibility or migration code.
- Integrations are called only when the user asks for it, never in the background.
- Nothing specific to one company's infrastructure (host names, service names, databases) in code, skills, docs or tests.
- Delete dead code and throwaway scripts.
- Do not overengineer. Simple, clean, maintainable.
- ASCII only.

## Motion

Motion marks a change; it is never decoration. Less is better.

- Tokens live once in `web/src/index.css`: `--ease-out` (entering), `--ease-in` (leaving, faster), `--ease-back` (tiny overshoot, success marks only), `--duration-small` / `--duration-medium` / `--duration-exit`, `--stagger-step`. No inline `cubic-bezier`, no bounce or elastic curves.
- Timing: small UI (menus, tooltips, presses) 120-180ms; medium (dialogs, toasts, sliding indicators) 200-280ms. Exits are faster than entrances and may simply fade. Only spinners and progress move at constant speed.
- Motion belongs on a real state change: a dialog or menu opening, a message arriving live, a value copied, the active nav item or segment moving, a toast.
- Never animate: page-to-page navigation, refetched or polled data, history loaded when a thread opens, hover on cards or fields, number counters, anything that delays reading or clicking.
- Rows reveal only on their first fetched load, staggered 24ms and capped at 8 (`useFirstLoadReveal` in `web/src/lib/motion.ts`). Stable keys keep rows mounted so refetches stay still.
- Sliding indicators use `useSlidingIndicator` and `SlideIndicator`: the first measurement does not animate, and layout changes (like collapsing the sidebar) jump instead of slide.
- The rotating word on the home page keeps its slower blur swap (700ms in, 500ms out) on purpose; it is the one celebratory exception.
- The thread's cost pill runs a blur wave across its characters (`.counting`, `--count-step`) while the thread is running, to show the amount is still being counted. It is the only animated number, and it stops the moment the turn ends.
- A pulsing ring (`live-ring`) only marks something happening right now.
- `prefers-reduced-motion` is handled globally: near-zero durations and no infinite loops. Do not add per-component exceptions.

## Verification

```sh
uv run --extra dev ruff format .
uv run --extra dev ruff check src tests
uv run --extra dev pytest -q
cd web && pnpm check && pnpm build
```

`pnpm build` writes `src/ov/agent/static`, which is committed so `pip install` ships the web app; rebuild and commit it with every web change.
