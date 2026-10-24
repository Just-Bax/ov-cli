from __future__ import annotations

import random
import string
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from ov import __version__
from ov.agent import providers, skills
from ov.agent.api.handler import APP_ID, Handler, HttpError, required, route
from ov.agent.engine.files import uploads_dir
from ov.agent.engine.run_manager import runs
from ov.agent.instances.ovproc import instances, version
from ov.agent.integrations import claude, copilot, openai_compatible
from ov.agent.providers.openai_compatible import OpenAICompatibleProvider
from ov.agent.storage import db

UPLOAD_ID_SUFFIX_CHARS = 6
COST_RANGE_DAYS = {"7d": 7, "30d": 30}


def _short_id() -> str:
    stamp = f"{int(time.time() * 1000):x}"
    return stamp + "".join(random.choices(string.ascii_lowercase + string.digits, k=UPLOAD_ID_SUFFIX_CHARS))


@route("GET", "/api/health")
def health(_: Handler) -> dict[str, Any]:
    return {"app": APP_ID, "version": __version__}


@route("GET", "/api/status")
def status(_: Handler) -> dict[str, Any]:
    rows = instances()
    settings = db.get_preferences()
    listed = [provider.describe() for provider in providers.every()]
    current = providers.get(settings["provider"])
    signed_in = next(p["account"]["signedIn"] for p in listed if p["id"] == current.id)

    return {
        "provider": current.id,
        "providers": listed,
        "ov": {"version": version()},
        "instances": {"total": len(rows), "valid": sum(1 for r in rows if r["valid"])},
        "settings": settings,
        "ready": bool(signed_in and rows and settings["defaultModel"]),
        "fullAccess": runs.full_access,
    }


@route("GET", "/api/claude/account")
def claude_account(_: Handler) -> dict[str, Any]:
    claude.forget_account()
    return claude.account()


@route("POST", "/api/copilot/device")
def copilot_device(_: Handler) -> dict[str, Any]:
    return copilot.start_device_flow()


@route("POST", "/api/copilot/poll")
def copilot_poll(h: Handler) -> dict[str, Any]:
    return copilot.poll_device_flow(required(h.json(), "deviceCode"))


@route("POST", "/api/copilot/logout")
def copilot_logout(_: Handler) -> dict[str, Any]:
    copilot.sign_out()
    return {"ok": True}


@route("GET", "/api/copilot/account")
def copilot_account(_: Handler) -> dict[str, Any]:
    return copilot.account()


@route("POST", "/api/openai/connect")
def openai_connect(h: Handler) -> dict[str, Any]:
    data = h.json()
    connected = openai_compatible.connect(required(data, "baseUrl"), str(data.get("apiKey") or ""))
    preferences = db.get_preferences()
    if preferences["provider"] == OpenAICompatibleProvider.id and not preferences["defaultModel"]:
        main, fast = providers.get(OpenAICompatibleProvider.id).default_models()
        db.save_preferences({"defaultModel": main, "fastModel": fast})
    return connected


@route("POST", "/api/openai/disconnect")
def openai_disconnect(_: Handler) -> dict[str, Any]:
    return openai_compatible.disconnect()


@route("PUT", "/api/openai/models")
def openai_configure_model(h: Handler) -> list[dict[str, Any]]:
    data = h.json()
    window = data.get("contextWindow")
    return openai_compatible.configure_model(
        required(data, "id"), bool(data.get("vision")), int(window) if window else None
    )


@route("GET", "/api/cost")
def cost(h: Handler) -> dict[str, Any]:
    provider = providers.get(h.query.get("provider") or db.get_preferences()["provider"])
    return db.cost_report(_cost_since(h.query.get("range", "month")), provider.id)


def _cost_since(range_name: str) -> int:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if range_name == "month":
        return int(today.replace(day=1).timestamp() * 1000)
    if range_name not in COST_RANGE_DAYS:
        raise HttpError(400, f"Unknown range: {range_name}")
    return int((today - timedelta(days=COST_RANGE_DAYS[range_name] - 1)).timestamp() * 1000)


@route("GET", "/api/models")
def models(h: Handler) -> list[dict[str, Any]]:
    return providers.get(h.query.get("provider") or db.get_preferences()["provider"]).list_models()


@route("GET", "/api/settings")
def get_settings(_: Handler) -> dict[str, Any]:
    return db.get_preferences()


@route("PUT", "/api/settings")
def put_settings(h: Handler) -> dict[str, Any]:
    patch = h.json()
    switching = patch.get("provider") and patch["provider"] != db.get_preferences()["provider"]
    if switching:
        chosen = providers.get(patch["provider"])
        if "defaultModel" not in patch:
            patch["defaultModel"], patch["fastModel"] = chosen.default_models()
    return db.save_preferences(patch)


@route("GET", "/api/skills")
def list_skills(_: Handler) -> list[dict[str, Any]]:
    return skills.list_skills()


@route("POST", "/api/skills")
def create_skill(h: Handler) -> dict[str, Any]:
    data = h.json()
    name = skills.create(str(data.get("title", "")), str(data.get("description", "")), str(data.get("content", "")))
    return {"name": name, "skills": skills.list_skills()}


@route("PUT", "/api/skills/([^/]+)")
def update_skill(h: Handler, name: str) -> list[dict[str, Any]]:
    skills.update(name, h.json())
    return skills.list_skills()


@route("POST", "/api/skills/([^/]+)/clone")
def clone_skill(_: Handler, name: str) -> dict[str, Any]:
    copy = skills.clone(name)
    return {"name": copy, "skills": skills.list_skills()}


@route("DELETE", "/api/skills/([^/]+)")
def delete_skill(_: Handler, name: str) -> list[dict[str, Any]]:
    skills.delete(name)
    return skills.list_skills()


@route("POST", "/api/uploads")
def upload(h: Handler) -> dict[str, str]:
    name = Path(unquote(h.headers.get("X-File-Name") or "")).name
    if not name:
        raise HttpError(400, "Give the file name in the X-File-Name header.")
    upload_id = _short_id()
    (uploads_dir() / upload_id).write_bytes(h.body())
    return {"id": upload_id, "name": name}
