from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ov.agent import workspace as project
from ov.agent.engine.files import within
from ov.agent.instances.http import web_session_alive
from ov.agent.instances.ovproc import find_instance, web_cookies
from ov.agent.tools.base import Tool, ToolContext, ToolError, approved, string_param
from ov.agent.tools.browser.guard import check
from ov.agent.tools.browser.page import attach, look
from ov.agent.tools.browser.specs import SAY, said
from ov.browser.model import BrowserError
from ov.onevizion.login import PENDING_PATHS

NOT_SIGNED_IN = "{host} still shows its sign-in page after signing in. Ask the user to check the account."
PREVIEW_QUESTION = "Run the widget {name} in the browser as you on {host}?"
PREVIEW_DETAIL = (
    "The widget's own code runs with your session, the way an External Widget would: it can read and change "
    "whatever your account can on {host}."
)
PREVIEW_BLOCKED = (
    "Not previewed: the widget would run with the user's session, which needs changes allowed in this thread "
    "(Always ask or Auto). Tell the user, or hand them the file to open."
)
PREVIEW_REJECTED = "The user did not allow the preview. Do not retry it."
PREVIEW_NAME = re.compile(r"[^a-z0-9-]+")
FINAL_SCREENSHOT = "Now: {title} | {url}\nThe final screenshot is attached."
NO_FINAL_SCREENSHOT = "No final screenshot: {reason}"


def signed_out(url: str, host: str) -> bool:
    parts = urlsplit(url)
    return parts.netloc.lower() != host.lower() or parts.path.lower().startswith(PENDING_PATHS)


def _instance(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    ref = str(args.get("instance") or ctx.instance).strip()
    if not ref:
        raise ToolError("Name the instance to open.")

    found = find_instance(ref)
    if found is None:
        raise ToolError(f"{ref} is not a signed-in instance.")
    return found


def _sign_in(ctx: ToolContext, found: dict[str, Any]) -> None:
    if not ctx.require_login(found["host"], found["tenant"] or "", web=True):
        raise ToolError(f"{found['host']} is not signed in.")


def _open(args: dict[str, Any], ctx: ToolContext) -> str:
    found = _instance(args, ctx)
    if not found["valid"] or not web_session_alive(found["alias"]):
        _sign_in(ctx, found)

    pilot = ctx.browser.start(found["alias"], found["url"], web_cookies(found["alias"]))
    target = pilot.url_of(str(args.get("path") or ""))
    if urlsplit(target).query:
        check(ctx, pilot, f"go to {target}", str(args["say"]))

    ctx.browser.navigate(target)
    if not signed_out(pilot.where()[1], found["host"]):
        return look(ctx, pilot, screenshot=True)

    _sign_in(ctx, found)
    pilot.add_cookies(web_cookies(found["alias"]))
    ctx.browser.navigate(target)
    if signed_out(pilot.where()[1], found["host"]):
        raise ToolError(NOT_SIGNED_IN.format(host=found["host"]))
    return look(ctx, pilot, screenshot=True)


def _run(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    report = ctx.drive_browser(str(args["goal"]), ctx.cancel)
    if not ctx.browser.live:
        return report

    try:
        shown = attach(ctx, pilot)
    except BrowserError as exc:
        return f"{report}\n\n{NO_FINAL_SCREENSHOT.format(reason=exc)}"
    if not shown:
        return report

    title, url = pilot.where()
    return f"{report}\n\n{FINAL_SCREENSHOT.format(title=title, url=url)}"


def _close(_: dict[str, Any], ctx: ToolContext) -> str:
    ctx.browser.close()
    return "Closed the browser."


def _widget_page(name: str, ctx: ToolContext) -> str:
    in_run = within(ctx.work_dir, name)
    if in_run.is_file():
        return in_run.read_text(encoding="utf-8")
    if project.configured():
        return project.text_of(name)
    raise ToolError(f"No file {name} in the run folder, and no workspace is set.")


def _preview(args: dict[str, Any], ctx: ToolContext) -> str:
    file = str(args["file"])
    page = _widget_page(file, ctx)
    found = _instance(args, ctx)
    name = PREVIEW_NAME.sub("-", Path(file).stem.lower()).strip("-") or "widget"

    if not ctx.can_write():
        raise ToolError(PREVIEW_BLOCKED)
    if not approved(
        ctx, PREVIEW_QUESTION.format(name=name, host=found["host"]), PREVIEW_DETAIL.format(host=found["host"])
    ):
        raise ToolError(PREVIEW_REJECTED)

    _open({"instance": found["alias"], "say": args["say"]}, ctx)
    pilot = ctx.browser.pilot()
    ctx.browser.navigate(pilot.preview(name, page))
    return look(ctx, pilot, screenshot=True)


OPEN = Tool(
    "browser_open",
    "Open a signed-in OneVizion instance in the live browser the user watches beside the chat, or go to another "
    "page of it. Only pages of that instance open. Returns the page as an accessibility snapshot with element refs, "
    "and a screenshot.",
    {
        "instance": string_param("Instance alias or host. Defaults to the run's instance."),
        "path": string_param("Path on the instance, e.g. '/form/ConfigAppForm.do?id=1'. Omit for home."),
        "say": SAY,
    },
    ["say"],
    said("Opening the browser"),
    _open,
)

RUN = Tool(
    "browser_run",
    "Hand one browser task to a fast assistant that drives the mouse and keyboard while the user watches, and "
    "reports back. Give a concrete goal: where to start, the steps or the outcome to reach, what to check, and "
    "when to stop, e.g. 'On the open Kafka Staging form, set Status to Staged, click Save, then check the Status "
    "field shows Staged'. Every change is still checked and may wait for the user's approval. Returns a report "
    "starting with Result: done, stuck or failed, and the final screenshot. Open the browser first with "
    "browser_open. Split long tests into a few goals and read each report before the next. To upload a file, "
    "name it in the goal; only files in the run folder or its attachments can be uploaded.",
    {"goal": string_param("The task, its steps and the expected result"), "say": SAY},
    ["goal", "say"],
    said("Working in the browser"),
    _run,
)

CLOSE = Tool(
    "browser_close",
    "Close the browser when the user is done with it.",
    {},
    [],
    lambda _: "Closing the browser",
    _close,
)

PREVIEW = Tool(
    "browser_preview",
    "Run a single-file HTML widget you built inside the instance, in the live browser, the way an External Widget "
    "runs: same origin, the user's session, so its token request and API calls hit live data. Nothing is deployed. "
    "Use it to check a widget before handing the file over; then look at it with browser_run or the snapshot it "
    "returns. Needs changes allowed and the user's approval, because the widget's code acts as the user.",
    {
        "file": string_param("The widget HTML: a file in the run folder or a path in the workspace"),
        "instance": string_param("Instance alias or host. Defaults to the run's instance."),
        "say": SAY,
    },
    ["file", "say"],
    said("Opening the widget preview"),
    _preview,
)
