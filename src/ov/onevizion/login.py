from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from ov.core.errors import Forbidden, LoginFailed, OvError
from ov.core.paths import browser_profile_dir
from ov.onevizion import auth
from ov.onevizion.auth import AJAX_HEADERS, CSRF_PATH, LOGIN_PATH, MINT_PATH
from ov.onevizion.session import Session, cookies_from_playwright, expiry_to_epoch

LOGIN_WAIT_MS = 5 * 60 * 1000
PAGE_LOAD_TIMEOUT_MS = 60_000
HTTP_MINT_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 1.0
PROGRESS_EVERY_SECONDS = 5.0
STUCK_AFTER_ROUNDS = 20
MS_PER_SECOND = 1000

BROWSERS_PATH_ENV = "PLAYWRIGHT_BROWSERS_PATH"
SCREEN_PORT_ENV = "OV_LOGIN_SCREEN_PORT"
SCREEN_SIZE_ENV = "OV_LOGIN_SCREEN_SIZE"
SCREEN_CHANNEL = "chromium"
UA_PLATFORMS = {
    "win32": "Windows NT 10.0; Win64; x64",
    "darwin": "Macintosh; Intel Mac OS X 10_15_7",
    "linux": "X11; Linux x86_64",
}
INSTALL_MARKER = "INSTALLATION_COMPLETE"

PENDING_PATHS = (
    "/login.do",
    "/loginfull.do",
    "/saml/",
    "/mfa/formmfaauthcode.do",
    "/formmustchangepassword.do",
)

_MISSING_BROWSER_HINTS = ("executable doesn't exist", "please run the following command")
PROFILE_IN_USE_HINT = "exitcode=21"
PROFILE_BUSY = (
    "Another sign-in is still using the sign-in browser.\nFinish or close that one first, or wait for it to time out."
)
PARENT_GONE = "OV Agent closed before sign-in finished."

_parent_gone = threading.Event()

NO_WIDGET_PRIV = (
    "Signed in, but this account cannot mint an API token: it needs the WIDGET "
    "module at Read.\nAsk an administrator for it, or use "
    "'ov login <url> --token accessKey:secretKey' with a token from "
    "Admin > Auth Tokens."
)

MINT_SCRIPT = """
async (paths) => {
  const port = location.port ? ':' + location.port : '';
  const origin = location.protocol + '//' + location.hostname + port;
  const ajax = { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' };
  const csrfResponse = await fetch(origin + paths.csrf, {
    credentials: 'include', headers: ajax,
  });
  if (!csrfResponse.ok) {
    return { error: 'page: ' + paths.csrf + ' returned ' + csrfResponse.status };
  }
  let csrf;
  try {
    csrf = await csrfResponse.json();
  } catch (e) {
    return { error: 'page: ' + paths.csrf + ' did not return JSON' };
  }
  const headers = Object.assign({}, ajax);
  headers[csrf.headerName] = csrf.token;
  const response = await fetch(origin + paths.mint, {
    method: 'POST', credentials: 'include', headers,
  });
  if (!response.ok) {
    return {
      status: response.status,
      error: 'page: ' + paths.mint + ' returned ' + response.status,
    };
  }
  try {
    return await response.json();
  } catch (e) {
    return { error: 'page: ' + paths.mint + ' did not return JSON' };
  }
}
"""

Progress = Callable[[str], None]
Minted = tuple[dict[str, Any] | None, str]


def _silent(_message: str) -> None:
    pass


def interactive_login(
    base_url: str,
    timeout_ms: int = LOGIN_WAIT_MS,
    on_progress: Progress = _silent,
    verify: bool = True,
    headless: bool = False,
) -> Session:
    base_url = base_url.rstrip("/")
    with sync_playwright() as p:
        context = _launch(p, headless, on_progress)
        try:
            _open_login_page(context, base_url)
            minted = _await_token(context, base_url, timeout_ms, on_progress, verify=verify)
            cookies = cookies_from_playwright(context.cookies(base_url), _host(base_url))
            on_progress("signed in, closing the browser")
        finally:
            with contextlib.suppress(PlaywrightError):
                context.close()

    return _session_from(minted, cookies, base_url)


def _open_login_page(context: Any, base_url: str) -> None:
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto(f"{base_url}{LOGIN_PATH}", wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
    except PlaywrightError as exc:
        raise LoginFailed(f"Could not open {base_url}{LOGIN_PATH}: {_first_line(exc)}") from exc


def _host(base_url: str) -> str:
    host = urlsplit(base_url).hostname
    if not host:
        raise LoginFailed(f"Not an instance URL: {base_url!r}")
    return host


def _first_line(exc: Exception) -> str:
    return next(iter(str(exc).splitlines()), type(exc).__name__)


def _await_token(
    context: Any,
    base_url: str,
    timeout_ms: int,
    report: Progress,
    *,
    verify: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + timeout_ms / MS_PER_SECOND
    next_report = started + PROGRESS_EVERY_SECONDS
    refused = 0
    last_error = ""
    seen: list[str] = []

    while time.monotonic() < deadline:
        if _parent_gone.is_set():
            raise LoginFailed(PARENT_GONE)

        pages = _live_pages(context)
        seen = [page.url for page in pages]
        minted, last_error, signed_in = _try_signed_in_tabs(context, pages, seen, base_url, verify)
        if minted is not None:
            return minted

        refused = refused + 1 if signed_in else 0
        if refused >= STUCK_AFTER_ROUNDS:
            raise LoginFailed(_stuck_message(base_url, last_error, seen))

        if time.monotonic() >= next_report:
            next_report = time.monotonic() + PROGRESS_EVERY_SECONDS
            report(f"waiting {int(time.monotonic() - started)}s: {last_error} [{', '.join(seen)}]")

        _pause(pages)

    raise LoginFailed(_timeout_message(base_url, last_error, seen))


def _try_signed_in_tabs(
    context: Any, pages: list[Any], urls: list[str], base_url: str, verify: bool
) -> tuple[dict[str, Any] | None, str, bool]:
    host = _host(base_url)
    ready = [page for page, url in zip(pages, urls, strict=True) if _looks_signed_in(url, host)]
    if not ready:
        return None, f"no tab is on {host} yet", False

    error = ""
    for page in ready:
        minted, error = _mint(context, page, base_url, verify=verify)
        if minted is not None:
            return minted, "", True
    return None, error, True


def _timeout_message(base_url: str, last_error: str, seen: list[str]) -> str:
    return (
        f"Timed out waiting for sign-in at {base_url}.\n"
        f"Last attempt: {last_error or 'nothing tried'}\n"
        f"Open tabs: {', '.join(seen) or 'none'}\n"
        "If a tab is signed in and this still fails, re-run with --verbose and send "
        "the output, or use 'ov login <url> --token accessKey:secretKey'."
    )


def _stuck_message(base_url: str, last_error: str, seen: list[str]) -> str:
    return (
        f"Signed in at {base_url}, but the instance would not issue an API token.\n"
        f"Tried three ways, all refused: {last_error}\n"
        f"Open tabs: {', '.join(seen)}\n\n"
        "Most likely the account lacks the WIDGET module at Read, which is what the "
        "token endpoint requires.\n"
        "Use a token instead: Admin > Auth Tokens, create one of type API, then\n"
        f"  ov login {base_url} --token accessKey:secretKey"
    )


def _pause(pages: list[Any]) -> None:
    for page in pages:
        try:
            page.wait_for_timeout(POLL_INTERVAL_SECONDS * MS_PER_SECOND)
            return
        except PlaywrightError:
            continue

    time.sleep(POLL_INTERVAL_SECONDS)


def _live_pages(context: Any) -> list[Any]:
    live = [page for page in context.pages if not page.is_closed()]
    if not live:
        raise LoginFailed("The browser window was closed before sign-in finished.")
    return live


def _looks_signed_in(url: str, host: str) -> bool:
    parts = urlsplit(url)
    if not parts.hostname or parts.hostname.lower() != host.lower():
        return False
    return not any(parts.path.lower().startswith(p) for p in PENDING_PATHS)


def _mint(context: Any, page: Any, base_url: str, *, verify: bool = True) -> Minted:
    minted, page_error = _mint_from_page(page)
    if minted is not None:
        return minted, ""

    minted, request_error = _mint_from_context(context, base_url)
    if minted is not None:
        return minted, ""

    minted, http_error = _mint_over_http(context, base_url, verify)
    if minted is not None:
        return minted, ""

    return None, f"{page_error}; {request_error}; {http_error}"


def _mint_over_http(context: Any, base_url: str, verify: bool) -> Minted:
    try:
        cookies = cookies_from_playwright(context.cookies(base_url), _host(base_url))
    except PlaywrightError as exc:
        return None, f"http: could not read cookies: {_first_line(exc)}"
    if not cookies:
        return None, "http: the browser has no cookies for this host yet"

    session = Session(base_url=base_url, mode="session", cookies=cookies)
    try:
        with httpx.Client(
            base_url=base_url,
            follow_redirects=True,
            timeout=HTTP_MINT_TIMEOUT_SECONDS,
            verify=verify,
            cookies=cookies,
        ) as http:
            auth.mint_web_session_token(http, session)
    except Forbidden as exc:
        raise LoginFailed(str(exc)) from None
    except (OvError, httpx.HTTPError) as exc:
        return None, f"http: {_first_line(exc)}"

    return {"bearerToken": session.bearer_token, "expirationTime": session.expires_text}, ""


def _mint_from_page(page: Any) -> Minted:
    try:
        result = page.evaluate(MINT_SCRIPT, {"csrf": CSRF_PATH, "mint": MINT_PATH})
    except PlaywrightError as exc:
        return None, f"page: {_first_line(exc)}"
    return _read_minted(result, "page")


def _mint_from_context(context: Any, base_url: str) -> Minted:
    request = context.request
    try:
        csrf = request.get(f"{base_url}{CSRF_PATH}", headers=AJAX_HEADERS)
        if not csrf.ok:
            return None, f"request: {CSRF_PATH} returned {csrf.status}"

        token = csrf.json()
        headers = {**AJAX_HEADERS, token["headerName"]: token["token"]}
        response = request.post(f"{base_url}{MINT_PATH}", headers=headers)
    except (PlaywrightError, ValueError, KeyError) as exc:
        return None, f"request: {_first_line(exc)}"

    if response.status == 403:
        raise LoginFailed(NO_WIDGET_PRIV)
    if not response.ok:
        return None, f"request: {MINT_PATH} returned {response.status}"

    try:
        result = response.json()
    except ValueError:
        return None, f"request: {MINT_PATH} did not return JSON"
    return _read_minted(result, "request")


def _read_minted(result: Any, source: str) -> Minted:
    if not isinstance(result, dict):
        return None, f"{source}: unreadable response"
    if result.get("status") == 403:
        raise LoginFailed(NO_WIDGET_PRIV)
    if result.get("error"):
        return None, str(result["error"])
    if not result.get("bearerToken") or not result.get("expirationTime"):
        return None, f"{source}: no bearerToken or expirationTime in the response"
    return result, ""


def _session_from(minted: dict[str, Any], cookies: dict[str, str], base_url: str) -> Session:
    return Session(
        base_url=base_url,
        mode="session",
        cookies=cookies,
        bearer_token=minted["bearerToken"],
        expires_text=minted["expirationTime"],
        expires_at=expiry_to_epoch(minted["expirationTime"]),
    )


def _launch(p: Any, headless: bool, report: Progress) -> Any:
    options: dict[str, Any] = {
        "user_data_dir": str(browser_profile_dir()),
        "headless": headless,
        "args": ["--no-first-run", "--no-default-browser-check"],
    }

    port = os.environ.get(SCREEN_PORT_ENV)
    if port:
        options.update(_screen_options(os.environ[SCREEN_SIZE_ENV]))
        options["args"].append(f"--remote-debugging-port={port}")
        threading.Thread(target=_watch_parent, daemon=True).start()

    try:
        return p.chromium.launch_persistent_context(**options)
    except PlaywrightError as exc:
        if PROFILE_IN_USE_HINT in str(exc).lower():
            raise LoginFailed(PROFILE_BUSY) from None
        if not _looks_like_missing_browser(exc):
            raise LoginFailed(f"Could not start the browser: {exc}") from exc
        _fetch_browser(report)

    try:
        return p.chromium.launch_persistent_context(**options)
    except PlaywrightError as exc:
        raise LoginFailed(f"Could not start the browser: {exc}") from exc


def _watch_parent() -> None:
    sys.stdin.read()
    _parent_gone.set()


def _screen_options(size: str) -> dict[str, Any]:
    width, height = (int(n) for n in size.split("x"))
    return {
        "headless": True,
        "channel": SCREEN_CHANNEL,
        "viewport": {"width": width, "height": height},
        "user_agent": desktop_user_agent(),
    }


def desktop_user_agent() -> str:
    major = _pinned_version().split(".")[0]
    platform = UA_PLATFORMS["linux" if sys.platform.startswith("linux") else sys.platform]
    return f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"


def _browser_entries() -> list[dict[str, Any]]:
    return json.loads(_browsers_manifest().read_text(encoding="utf-8"))["browsers"]


def _pinned_version() -> str:
    entries = _browser_entries()
    return next(entry["browserVersion"] for entry in entries if entry["name"] == SCREEN_CHANNEL)


def _browsers_manifest() -> Path:
    return Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"


def _fetch_browser(report: Progress) -> None:
    report("sign-in browser missing, downloading it once (about 150MB)")
    if not install_chromium():
        raise LoginFailed("The sign-in browser could not be downloaded.\nCheck your connection, then run: ov setup")


def _looks_like_missing_browser(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(hint in message for hint in _MISSING_BROWSER_HINTS)


def install_chromium() -> bool:
    result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    return result.returncode == 0


def _browsers_root() -> Path:
    override = os.environ.get(BROWSERS_PATH_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _pinned_builds() -> list[str]:
    entries = _browser_entries()
    return [
        f"{entry['name'].replace('-', '_')}-{entry['revision']}"
        for entry in entries
        if entry["name"].startswith("chromium") and entry.get("installByDefault")
    ]


def browser_is_installed() -> bool:
    root = _browsers_root()
    wanted = _pinned_builds()
    return bool(wanted) and all((root / name / INSTALL_MARKER).exists() for name in wanted)
