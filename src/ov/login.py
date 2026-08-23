from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import LoginFailed
from .paths import browser_profile_dir
from .session import Session, cookies_from_playwright, expiry_to_epoch

LOGIN_PATH = "/Login.do"
CSRF_PATH = "/CsrfToken.do"
MINT_PATH = "/widget/GenerateApiTokenForWebSession"

LOGIN_WAIT_MS = 5 * 60 * 1000
POLL_INTERVAL_SECONDS = 1.0
PROGRESS_EVERY_SECONDS = 5.0

# Rounds, not seconds, so the threshold does not shift with loop speed. Long
# enough to ride out a session that is still settling.
STUCK_AFTER_ROUNDS = 20

AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}

# Pages on the instance itself that still mean "not signed in yet".
PENDING_PATHS = (
    "/login.do",
    "/loginfull.do",
    "/saml/",
    "/mfa/formmfaauthcode.do",
    "/formmustchangepassword.do",
)

_MISSING_BROWSER_HINTS = ("executable doesn't exist", "please run the following command")

NO_WIDGET_PRIV = (
    "Signed in, but this account cannot mint an API token: it needs the WIDGET "
    "module at Read.\nAsk an administrator for it, or use "
    "'ov login <url> --token accessKey:secretKey' with a token from "
    "Admin > Auth Tokens."
)

# Run in the signed-in page so the exchange carries the same origin, referer and
# cookies a widget's own call would.
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


def interactive_login(
    base_url: str,
    timeout_ms: int = LOGIN_WAIT_MS,
    on_progress: Progress | None = None,
    verify: bool = True,
    headless: bool = False,
) -> Session:
    """Open a real browser at the OneVizion login page and come back with a
    bearer token once the user has signed in.

    Credentials never pass through this process; the user types them into the
    genuine page, which is what makes SSO and MFA work unchanged.

    Being signed in is decided by asking the instance for a token, not by
    reading the address bar: with an external identity provider the redirect
    chain runs through domains that are not ours to recognise.
    """
    playwright = _import_playwright()
    base_url = base_url.rstrip("/")
    host = urlsplit(base_url).hostname or ""
    report: Progress = on_progress or (lambda _message: None)

    with playwright() as p:
        context = _launch(p, headless)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(f"{base_url}{LOGIN_PATH}", wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                raise LoginFailed(
                    f"Could not open {base_url}{LOGIN_PATH}: {str(exc).splitlines()[0]}"
                ) from exc
            minted = _await_token(context, base_url, host, timeout_ms, report, verify)
            cookies = cookies_from_playwright(context.cookies())
            report("signed in, closing the browser")
        finally:
            _close(context)

    return _session_from(minted, cookies, base_url)


def _await_token(
    context: Any,
    base_url: str,
    host: str,
    timeout_ms: int,
    report: Progress,
    verify: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + timeout_ms / 1000
    next_report = started + PROGRESS_EVERY_SECONDS
    refused = 0
    last_error = ""
    seen: list[str] = []

    while time.monotonic() < deadline:
        pages = _open_pages(context)
        if not pages:
            raise LoginFailed("The browser window was closed before sign-in finished.")

        seen = [_url_of(page) for page in pages]
        # Single sign-on often hands the app to a new tab and leaves the one we
        # opened parked on the provider's page.
        ready = [page for page, url in zip(pages, seen) if _looks_signed_in(url, host)]

        for page in ready:
            minted, last_error = _mint(context, page, base_url, verify)
            if minted is not None:
                return minted

        if ready:
            # Signed in and still refused: a grace period covers a session that
            # is settling, beyond that the refusal will not fix itself.
            refused += 1
            if refused >= STUCK_AFTER_ROUNDS:
                raise LoginFailed(_stuck_message(base_url, last_error, seen))
        else:
            refused = 0
            last_error = f"no tab is on {host} yet"

        if time.monotonic() >= next_report:
            next_report = time.monotonic() + PROGRESS_EVERY_SECONDS
            waited = int(time.monotonic() - started)
            report(f"waiting {waited}s: {last_error} [{', '.join(seen) or 'no tabs'}]")

        _pause(pages)

    raise LoginFailed(
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
        f"Open tabs: {', '.join(seen) or 'none'}\n\n"
        "Most likely the account lacks the WIDGET module at Read, which is what the "
        "token endpoint requires.\n"
        "Use a token instead: Admin > Auth Tokens, create one of type API, then\n"
        f"  ov login {base_url} --token accessKey:secretKey"
    )


def _pause(pages: list[Any]) -> None:
    """Wait a beat between rounds, through Playwright rather than around it.

    The sync API only delivers browser events while the caller is inside one of
    its calls. A plain time.sleep never yields to it, so page.url keeps
    reporting whatever was true at the last real call and a sign-in completing
    after goto() is never seen.
    """
    for page in pages:
        try:
            page.wait_for_timeout(POLL_INTERVAL_SECONDS * 1000)
            return
        except Exception:
            continue
    time.sleep(POLL_INTERVAL_SECONDS)


def _open_pages(context: Any) -> list[Any]:
    live = []
    for page in context.pages:
        try:
            if not page.is_closed():
                live.append(page)
        except Exception:
            continue
    return live


def _url_of(page: Any) -> str:
    """page.url can be unreadable mid-redirect, which means 'keep waiting'."""
    try:
        return page.url
    except Exception:
        return ""


def _looks_signed_in(url: str, host: str) -> bool:
    """Only ever mint against the host the user named: an identity provider's
    domain is not somewhere to send a token request."""
    parts = urlsplit(url)
    if not parts.hostname or parts.hostname.lower() != host.lower():
        return False
    return not any(parts.path.lower().startswith(p) for p in PENDING_PATHS)


def _mint(
    context: Any, page: Any, base_url: str, verify: bool = True
) -> tuple[dict[str, Any] | None, str]:
    """One round of the widget token exchange, tried three ways.

    The page's own fetch is what the product itself does; the context's request
    API survives the navigation that kills a page script; plain HTTP over the
    browser's cookies is the same path that later refreshes the token.
    """
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


def _mint_over_http(context: Any, base_url: str, verify: bool) -> tuple[dict[str, Any] | None, str]:
    """Mint from this process using the browser's cookies."""
    import httpx

    from .auth import mint_web_session_token
    from .errors import Forbidden

    try:
        cookies = cookies_from_playwright(context.cookies())
    except Exception as exc:
        return None, f"http: could not read cookies: {str(exc).splitlines()[0]}"
    if not cookies:
        return None, "http: the browser has no cookies for this host yet"

    session = Session(base_url=base_url, mode="session", cookies=cookies)
    try:
        with httpx.Client(
            base_url=base_url,
            follow_redirects=True,
            timeout=30.0,
            verify=verify,
            cookies=cookies,
        ) as http:
            mint_web_session_token(http, session)
    except Forbidden as exc:
        raise LoginFailed(str(exc)) from None
    except Exception as exc:
        return None, f"http: {str(exc).splitlines()[0]}"

    return {
        "bearerToken": session.bearer_token,
        "expirationTime": session.expires_text,
    }, ""


def _mint_from_page(page: Any) -> tuple[dict[str, Any] | None, str]:
    try:
        result = page.evaluate(MINT_SCRIPT, {"csrf": CSRF_PATH, "mint": MINT_PATH})
    except Exception as exc:
        return None, f"page: {str(exc).splitlines()[0]}"
    return _read_minted(result, "page")


def _mint_from_context(context: Any, base_url: str) -> tuple[dict[str, Any] | None, str]:
    request = context.request
    try:
        csrf = request.get(f"{base_url}{CSRF_PATH}", headers=AJAX_HEADERS)
        if not csrf.ok:
            return None, f"request: {CSRF_PATH} returned {csrf.status}"

        token = csrf.json()
        headers = dict(AJAX_HEADERS)
        headers[token["headerName"]] = token["token"]

        response = request.post(f"{base_url}{MINT_PATH}", headers=headers)
    except Exception as exc:
        return None, f"request: {str(exc).splitlines()[0]}"

    if response.status == 403:
        raise LoginFailed(NO_WIDGET_PRIV)
    if not response.ok:
        return None, f"request: {MINT_PATH} returned {response.status}"

    try:
        return _read_minted(response.json(), "request")
    except Exception:
        return None, f"request: {MINT_PATH} did not return JSON"


def _read_minted(result: Any, source: str) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(result, dict):
        return None, f"{source}: unreadable response"
    if result.get("status") == 403:
        raise LoginFailed(NO_WIDGET_PRIV)
    if result.get("error"):
        return None, str(result["error"])
    if not result.get("bearerToken"):
        return None, f"{source}: no bearerToken in the response"
    return result, ""


def _session_from(minted: dict[str, Any], cookies: dict[str, str], base_url: str) -> Session:
    expires_text = minted.get("expirationTime") or ""
    return Session(
        base_url=base_url,
        mode="session",
        cookies=cookies,
        bearer_token=minted["bearerToken"],
        expires_text=expires_text,
        expires_at=expiry_to_epoch(expires_text),
    )


def _import_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise LoginFailed(
            "Playwright is not installed.\n"
            "Run: pip install playwright && playwright install chromium"
        ) from None
    return sync_playwright


def _launch(p: Any, headless: bool = False) -> Any:
    try:
        return p.chromium.launch_persistent_context(
            user_data_dir=str(browser_profile_dir()),
            headless=headless,
            args=["--no-first-run", "--no-default-browser-check"],
        )
    except Exception as exc:
        if _looks_like_missing_browser(exc):
            raise LoginFailed(
                "Chromium is not installed for Playwright.\nRun: playwright install chromium"
            ) from exc
        raise LoginFailed(f"Could not start the browser: {exc}") from exc


def _close(context: Any) -> None:
    try:
        context.close()
    except Exception:
        pass


def _looks_like_missing_browser(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(hint in message for hint in _MISSING_BROWSER_HINTS)


def install_chromium() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=False,
    )
    return result.returncode == 0


def _browsers_root() -> Path:
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return Path(override)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def browser_is_installed() -> bool:
    """Look for the unpacked browser on disk. Asking Playwright itself would
    start its driver, which prints teardown noise on a plain status check."""
    root = _browsers_root()
    return root.is_dir() and any(root.glob("chromium*"))
