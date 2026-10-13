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

## Verification

```sh
uv run --extra dev ruff format .
uv run --extra dev ruff check src tests
uv run --extra dev pytest -q
cd web && pnpm check && pnpm build
```

`pnpm build` writes `src/ov/agent/static`, which is committed so `pip install` ships the web app; rebuild and commit it with every web change.
