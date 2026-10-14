from __future__ import annotations

from typing import Any

from ov.agent.storage import db
from ov.agent.tools.base import LABEL_CHARS, Tool, ToolContext, ToolError, string_param, strings_param


def _instance(args: dict[str, Any], ctx: ToolContext) -> str:
    instance = str(args.get("instance") or ctx.instance).strip()
    if not instance:
        raise ToolError("This thread has no instance. Ask the user which instance to test, then plan again.")
    return instance


def _steps(raw: Any) -> list[str]:
    steps = [str(s).strip() for s in raw or [] if str(s).strip()]
    if not steps:
        raise ToolError("Give at least one step, one action per step.")
    return steps


def _plan(args: dict[str, Any], ctx: ToolContext) -> str:
    instance = _instance(args, ctx)
    title = str(args["title"]).strip()
    if not title:
        raise ToolError("Give the walkthrough a short title.")

    goal = str(args.get("goal") or "").strip() or title
    steps = _steps(args["steps"])
    walk = db.create_walkthrough(f"wk{db.now_ms():x}", instance, title, goal, steps)

    ctx.emit({"type": "walkthrough", "walkthrough": walk})
    return f"Walkthrough planned ({walk['id']}). The user can review, edit and run it from the card."


def _update(args: dict[str, Any], ctx: ToolContext) -> str:
    walk_id = str(args["id"]).strip()
    current = db.get_walkthrough(walk_id)
    if current is None:
        raise ToolError(f"No walkthrough {walk_id}.")

    steps = _steps(args["steps"]) if args.get("steps") else current["steps"]
    walk = db.update_walkthrough(
        walk_id,
        title=str(args.get("title") or current["title"]).strip(),
        goal=str(args.get("goal") or current["goal"]).strip(),
        steps=steps,
    )
    if walk is None:
        raise ToolError(f"Walkthrough {walk_id} could not be updated.")

    ctx.emit({"type": "walkthrough", "walkthrough": walk})
    return f"Walkthrough {walk_id} updated. The user can review and run the new version."


TOOLS = [
    Tool(
        "walk_plan",
        "Plan a walkthrough: a short browser test a real user would run on the instance, as "
        "ordered steps the fast model checks at every step. Use it once you and the user agree on "
        "a scenario to test. Each step is one plain action or check, e.g. "
        '"Open the Rules admin page", "Click New rule", "Confirm it shows in the list". The user '
        "reviews, edits and runs it from the card; you do not run it yourself.",
        {
            "title": string_param("Short name for the test"),
            "goal": string_param("What is true when it passes, one sentence"),
            "steps": strings_param("Ordered steps, one plain action or check each"),
            "instance": string_param("Instance host; defaults to this thread's instance"),
        },
        ["title", "steps"],
        lambda a: f"plan walkthrough: {str(a.get('title', ''))[:LABEL_CHARS]}",
        _plan,
        silent=True,
    ),
    Tool(
        "walk_update",
        "Revise a walkthrough you planned earlier, by id, when the user asks to change its steps, "
        "title or goal. Re-shows the card with the new version.",
        {
            "id": string_param("Walkthrough id from walk_plan"),
            "title": string_param("New title"),
            "goal": string_param("New goal"),
            "steps": strings_param("Full replacement list of steps"),
        },
        ["id"],
        lambda a: f"update walkthrough {a.get('id')}",
        _update,
        silent=True,
    ),
]
