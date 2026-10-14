from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from ov.agent.engine.run import StatusFeed
from ov.agent.instances.ovproc import find_instance
from ov.agent.integrations import copilot
from ov.agent.storage import db
from ov.browser.engine import BrowserError, chromium
from ov.browser.engine import Session as PageSession
from ov.browser.walkthrough import Action, Status, StepResult, Walkthrough, parse_action
from ov.core.paths import agent_dir
from ov.onevizion import session as session_store

VIEWPORT = (1280, 800)
RUN_ID_PREFIX = "wr"
GUARD_MAX_TOKENS = 200
PLAN_MAX_STEPS = 20
PLAN_PROMPT = (
    "You write a browser test plan for a OneVizion instance, as steps a real user would follow. "
    "Given a one-line description, reply with ONE JSON object: "
    '{"title": "short name", "goal": "one sentence", "steps": ["step 1", "step 2", ...]}. '
    "Each step is one plain action or check (open a page, click a button, type a value, confirm something shows). "
    "Keep it to the described test; never add steps that delete or change data unless the description asks."
)

DRIVER_PROMPT = (
    "You drive a web browser to carry out ONE step of a test, as a real user would. "
    "You are given the test goal, the full plan, the current step, the page URL, the clickable elements "
    "(each with an index, role and name) and the visible page text. "
    "Reply with ONE JSON object and nothing else:\n"
    '{"action": "...", "index": N, "text": "...", "reason": "short"}\n'
    "Actions: goto (text=url), click (index), fill (index, text), select (index, text=option), "
    "press (text=key), wait (text=words to appear), assert (text=words that must be present to pass the step), "
    "pass (the step is clearly done), fail (the page shows the step cannot be done). "
    "Prefer the element whose name matches the step. Never invent an index that is not listed. "
    "Use assert to verify a result, and pass only once the step is visibly complete."
)
GUARD_PROMPT = (
    "You review one browser action a tester is about to take, and decide if it stays within the test goal. "
    "Block anything that would change or destroy data the goal did not ask for: deleting records, running rules "
    "or imports against real data, bulk or mass actions, admin changes to users, roles or security. "
    "Reading, navigating, filling a form the goal describes, and clicking the goal's own buttons are fine. "
    'Reply with ONE JSON object: {"ok": true|false, "why": "short reason"}.'
)


def walk_dir(run_id: str) -> Path:
    return agent_dir("walkthroughs", run_id)


def new_id(prefix: str) -> str:
    return f"{prefix}{db.now_ms():x}"


class ModelDriver:
    def __init__(self, model: str) -> None:
        self._model = model

    def act(self, context: dict[str, Any]) -> Action:
        body = json.dumps(
            {
                "goal": context["goal"],
                "plan": context["steps"],
                "step": context["step"],
                "url": context["url"],
                "elements": context["snapshot"],
                "page_text": context["text"],
            }
        )
        reply, _ = copilot.complete(self._model, DRIVER_PROMPT, body)
        return parse_action(_only_json(reply))


class ModelGuard:
    def __init__(self, model: str, record: Any) -> None:
        self._model = model
        self._record = record

    def allow(self, goal: str, action: Action, element: str) -> tuple[bool, str]:
        body = json.dumps({"goal": goal, "action": action.kind, "element": element, "text": action.text})
        reply, usage = copilot.complete(self._model, GUARD_PROMPT, body, GUARD_MAX_TOKENS)
        self._record(usage)
        try:
            verdict = json.loads(_only_json(reply))
        except json.JSONDecodeError:
            return False, f"The safety check did not answer clearly: {reply[:200]}"
        return bool(verdict.get("ok")), str(verdict.get("why") or "")


def _only_json(reply: str) -> str:
    start = reply.find("{")
    end = reply.rfind("}")
    if start < 0 or end < 0:
        return reply.strip()
    return reply[start : end + 1]


class WalkRunner:
    def __init__(self) -> None:
        self._feed = StatusFeed()
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    @property
    def feed(self) -> StatusFeed:
        return self._feed

    def start(self, plan: dict[str, Any], model: str, walkthrough_id: str | None) -> dict[str, Any]:
        if not plan["steps"]:
            raise BrowserError("Add at least one step before running.")

        run_id = new_id(RUN_ID_PREFIX)
        steps = [vars(StepResult(index=i, text=text)) for i, text in enumerate(plan["steps"])]
        run = db.create_walk_run(
            run_id,
            walkthrough_id,
            instance=plan["instance"],
            title=plan["title"],
            goal=plan["goal"],
            model=model,
            steps=steps,
        )
        cancel = threading.Event()
        with self._lock:
            self._cancels[run_id] = cancel
        walk_dir(run_id).mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._run, args=(run, model, cancel), daemon=True, name=f"walk-{run_id}").start()
        return run

    def stop(self, run_id: str) -> None:
        with self._lock:
            cancel = self._cancels.get(run_id)
        if cancel is not None:
            cancel.set()

    def _run(self, run: dict[str, Any], model: str, cancel: threading.Event) -> None:
        run_id = run["id"]
        results = [StepResult(**{k: step[k] for k in ("index", "text")}) for step in run["steps"]]
        try:
            self._drive(run, model, results, cancel)
        except BrowserError as exc:
            self._fail_all(results, str(exc))
            self._save(run_id, results, finished=True)
        finally:
            with self._lock:
                self._cancels.pop(run_id, None)

    def _drive(self, run: dict[str, Any], model: str, results: list[StepResult], cancel: threading.Event) -> None:
        run_id = run["id"]
        found = find_instance(run["instance"])
        if found is None:
            raise BrowserError(f"Not signed in to {run['instance']}. Sign in on the Instances page first.")

        session = session_store.all_sessions().get(found["alias"])
        if session is None or not session.cookies:
            raise BrowserError(f"{run['instance']} has no signed-in browser session to reuse.")

        self._save(run_id, results, finished=False, status=Status.RUNNING)
        with sync_playwright() as p:
            browser = chromium(p, headless=True, debug_port=None)
            page = PageSession(browser, session.base_url, session.cookies, *VIEWPORT)
            try:
                page.goto(session.base_url)
                walk = Walkthrough(
                    page, ModelDriver(model), self._guard(run_id, model), walk_dir(run_id), cancel.is_set
                )
                walk.run(run["goal"], [r.text for r in results], lambda r: self._on_step(run_id, results, r))
            finally:
                page.close()
                browser.close()
        self._save(run_id, results, finished=True, status=_overall(results))

    def _guard(self, run_id: str, model: str) -> ModelGuard:
        helper = db.get_preferences()["fastModel"] or model
        return ModelGuard(helper, lambda usage: self._record(run_id, helper, usage))

    def _record(self, run_id: str, model: str, usage: Any) -> None:
        if usage is not None:
            db.add_usage(run_id, model, "step", usage.tokens, usage.nano)

    def _on_step(self, run_id: str, results: list[StepResult], result: StepResult) -> None:
        results[result.index] = result
        self._save(run_id, results, finished=False, status=Status.RUNNING)

    def _save(self, run_id: str, results: list[StepResult], *, finished: bool, status: str | None = None) -> None:
        state = status or _overall(results)
        db.save_walk_run(run_id, state, [vars(r) for r in results], finished)
        self._feed.publish({"kind": "walk", "id": run_id})

    def _fail_all(self, results: list[StepResult], detail: str) -> None:
        for result in results:
            if result.status in (Status.PENDING, Status.RUNNING):
                result.status = Status.ERROR
                result.detail = detail
                break


def _overall(results: list[StepResult]) -> str:
    states = [r.status for r in results]
    for bad in (Status.ERROR, Status.BLOCKED, Status.FAILED, Status.STOPPED):
        if bad in states:
            return bad
    if all(s == Status.PASSED for s in states):
        return Status.PASSED
    return Status.RUNNING


def delete_run_files(run_id: str) -> None:
    folder = walk_dir(run_id)
    if folder.exists():
        shutil.rmtree(folder)


def draft_plan(instance: str, describe: str) -> dict[str, Any]:
    model = db.get_preferences()["defaultModel"]
    if not model:
        raise BrowserError("Pick a model first (Settings).")

    reply, _ = copilot.complete(model, PLAN_PROMPT, describe)
    try:
        plan = json.loads(_only_json(reply))
    except json.JSONDecodeError:
        raise BrowserError("The model did not return a plan. Try describing it again.") from None
    steps = [str(s).strip() for s in plan.get("steps") or [] if str(s).strip()][:PLAN_MAX_STEPS]
    return {
        "instance": instance,
        "title": str(plan.get("title") or "").strip() or describe[:80],
        "goal": str(plan.get("goal") or "").strip() or describe,
        "steps": steps,
    }


runner = WalkRunner()
