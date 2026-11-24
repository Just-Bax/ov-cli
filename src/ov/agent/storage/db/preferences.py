from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert

from ov.agent.storage.db.clock import now_ms
from ov.agent.storage.db.engine import _begin
from ov.agent.storage.db.startup import PREFERENCE_ROW
from ov.agent.storage.models import MAX_STEPS_LIMIT, Preference, ProviderModel, Reasoning

FULL_NAME_REQUIRED = "Your full name is required."
PREFERENCE_COLUMNS = {
    "provider": "provider",
    "reasoning": "reasoning",
    "maxSteps": "max_steps",
    "workspace": "workspace",
    "workspaceNotes": "workspace_notes",
    "fullName": "full_name",
    "instructions": "instructions",
    "notify": "notify",
    "tabBadge": "tab_badge",
    "compactBranches": "compact_branches",
    "boost": "boost",
}
BOOLEAN_PREFERENCES = ("notify", "tabBadge", "compactBranches", "boost")
TEXT_PREFERENCES = ("workspace", "workspaceNotes", "fullName", "instructions")
MODEL_PREFERENCES = {"defaultModel": "default_model", "fastModel": "fast_model"}
REASONING_LEVELS = tuple(level.value for level in Reasoning)


def get_preferences() -> dict[str, Any]:
    with _begin() as conn:
        row = conn.execute(select(Preference).where(Preference.id == PREFERENCE_ROW)).one()

    values = {key: getattr(row, column) for key, column in PREFERENCE_COLUMNS.items()}
    main, fast = provider_models(row.provider)

    return {
        **values,
        "defaultModel": main,
        "fastModel": fast,
        **{key: values[key] or "" for key in (*TEXT_PREFERENCES, "reasoning")},
        **{key: bool(values[key]) for key in BOOLEAN_PREFERENCES},
    }


def _max_steps(value: Any) -> int:
    try:
        steps = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"maxSteps must be a whole number, got {value!r}.") from None
    return min(max(steps, 1), MAX_STEPS_LIMIT)


def provider_models(provider: str) -> tuple[str, str]:
    with _begin() as conn:
        row = conn.execute(select(ProviderModel).where(ProviderModel.provider == provider)).one_or_none()
    if row is None:
        return "", ""
    return row.default_model or "", row.fast_model or ""


def has_provider_models(provider: str) -> bool:
    with _begin() as conn:
        found = conn.execute(select(ProviderModel.provider).where(ProviderModel.provider == provider)).first()
    return found is not None


def _save_models(conn: Any, provider: str, models: dict[str, Any]) -> None:
    values = {MODEL_PREFERENCES[key]: str(value or "").strip() or None for key, value in models.items()}
    statement = insert(ProviderModel).values(provider=provider, updated_at=now_ms(), **values)
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=[ProviderModel.provider], set_={**values, "updated_at": now_ms()}
        )
    )


def _check_preferences(patch: dict[str, Any]) -> None:
    unknown = set(patch) - set(PREFERENCE_COLUMNS) - set(MODEL_PREFERENCES)
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}.")
    if patch.get("reasoning") and patch["reasoning"] not in REASONING_LEVELS:
        raise ValueError(f"Unknown reasoning level: {patch['reasoning']}")
    if "fullName" in patch and not str(patch["fullName"] or "").strip():
        raise ValueError(FULL_NAME_REQUIRED)


def _preference_values(patch: dict[str, Any]) -> dict[str, Any]:
    _check_preferences(patch)

    values = {PREFERENCE_COLUMNS[key]: value for key, value in patch.items()}
    if "maxSteps" in patch:
        values["max_steps"] = _max_steps(patch["maxSteps"])
    for key in BOOLEAN_PREFERENCES:
        if key in patch:
            values[PREFERENCE_COLUMNS[key]] = bool(patch[key])
    if "workspace" in patch:
        from ov.agent.workspace import validate_folder

        values["workspace"] = validate_folder(str(patch["workspace"]))

    for key in (*TEXT_PREFERENCES, "reasoning"):
        if key in patch:
            values[PREFERENCE_COLUMNS[key]] = str(values[PREFERENCE_COLUMNS[key]] or "").strip() or None

    return values


def save_preferences(patch: dict[str, Any]) -> dict[str, Any]:
    models = {key: value for key, value in patch.items() if key in MODEL_PREFERENCES}
    values = _preference_values({key: value for key, value in patch.items() if key not in MODEL_PREFERENCES})
    with _begin() as conn:
        conn.execute(update(Preference).where(Preference.id == PREFERENCE_ROW).values(updated_at=now_ms(), **values))
        if models:
            provider = conn.execute(select(Preference.provider).where(Preference.id == PREFERENCE_ROW)).scalar_one()
            _save_models(conn, provider, models)

    return get_preferences()
