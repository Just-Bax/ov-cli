from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from ... import session as session_store
from ...config import normalize_base_url
from ...errors import LoginFailed, NotConfigured, NotLoggedIn, OvError, SessionExpired
from ...login import install_chromium, interactive_login
from ...paths import config_file
from ...session import Session
from ...tenants import NO_TENANTS, resolve_tenant, tenant_rows
from ..context import Context, build_client
from ..dynamic import reset_cache
from ..output import build_table, emit, note, warn

LOGOFF_PATH = "/LogOff.do"


def register(subparsers: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    login = subparsers.add_parser(
        "login", parents=[common], help="sign in to a OneVizion instance through a browser"
    )
    login.add_argument(
        "url",
        nargs="?",
        help="instance URL or hostname, e.g. https://acme.onevizion.com. "
        "Omit to sign in again to the current instance.",
    )
    login.add_argument(
        "--as",
        dest="alias",
        metavar="ALIAS",
        help="name this instance, instead of the first label of its hostname",
    )
    login.add_argument(
        "--token",
        help="skip the browser and use an accessKey:secretKey pair from Admin > Auth Tokens",
    )
    login.add_argument(
        "--timeout", type=int, default=300, help="seconds to wait for sign-in (default 300)"
    )
    login.add_argument(
        "--no-spec", action="store_true", help="do not download the OpenAPI schema after signing in"
    )
    login.add_argument(
        "--tenant",
        metavar="NAME",
        help="sign in to this tenant instead of your default one (name or pid); "
        "needs a user with your email address in it",
    )
    login.add_argument(
        "--verbose",
        action="store_true",
        help="print every sign-in poll, for diagnosing a login that never completes",
    )
    login.add_argument(
        "--keep-current",
        action="store_true",
        help="store the credentials without making this the current instance",
    )
    login.set_defaults(func=cmd_login)

    logout = subparsers.add_parser(
        "logout", parents=[common], help="revoke the token and forget one instance"
    )
    logout.add_argument("instance_ref", nargs="?", metavar="INSTANCE", help="defaults to current")
    logout.add_argument("--all", action="store_true", help="sign out of every instance")
    logout.set_defaults(func=cmd_logout)

    whoami = subparsers.add_parser(
        "whoami", parents=[common], help="show the current instance and whether its token works"
    )
    whoami.add_argument("instance_ref", nargs="?", metavar="INSTANCE", help="defaults to current")
    whoami.set_defaults(func=cmd_whoami)

    instances = subparsers.add_parser(
        "instances", parents=[common], help="list every instance you are signed in to"
    )
    instances.add_argument(
        "--check", action="store_true", help="call each instance to confirm its token still works"
    )
    instances.set_defaults(func=cmd_instances)

    tenants = subparsers.add_parser(
        "tenants",
        parents=[common],
        help="list the tenants your account can reach on an instance",
    )
    tenants.set_defaults(func=cmd_tenants)

    use = subparsers.add_parser(
        "use", parents=[common], help="make one instance the default for later commands"
    )
    use.add_argument("instance_ref", metavar="INSTANCE", help="alias, hostname or URL")
    use.set_defaults(func=cmd_use)


def cmd_login(ctx: Context) -> int:
    args = ctx.args
    base_url = _target_url(ctx)
    # Fail before opening a browser if --as names someone else's instance.
    session_store.unique_alias(base_url, args.alias or "")

    session = _token_login(ctx, base_url) if args.token else _browser_login(ctx, base_url)
    if args.tenant:
        _choose_tenant(ctx, session, args.tenant)

    # The browser can land on a different host than the one we opened, and the
    # tenant is only known once it has been looked up, so the alias is settled
    # here. It has to happen before the mint, which persists the session under
    # whatever alias it finds.
    session.alias = session_store.unique_alias(
        session.base_url, args.alias or "", session.tenant, session.tenant_id
    )
    if args.tenant:
        note(ctx, f"Switching to tenant [cyan]{session.tenant}[/cyan]...")
        _mint_in_tenant(ctx, session)

    note(ctx, "Checking the credentials...")
    with build_client(ctx.config, session) as client:
        try:
            client.api("GET", "/authorize", accept="text/plain")
        except SessionExpired as exc:
            raise LoginFailed(f"The credentials were not accepted: {exc}") from None
        except OvError as exc:
            # /authorize needs Web Services at Read. Anything else the account
            # can reach is still worth having, so this is a warning, not a stop.
            warn(ctx, f"[yellow]Signed in, but /api/authorize said:[/yellow] {exc}")

    session_store.save(session, make_current=not args.keep_current)
    reset_cache()
    ctx.cache.clear()

    fetched = 0
    if not args.no_spec:
        note(ctx, "Downloading the API schema...")
        fetched = _prefetch_spec(ctx, session)

    data = {
        "status": "logged_in",
        "alias": session.alias,
        "base_url": session.base_url,
        "tenant": session.tenant or None,
        "mode": session.mode,
        "access_key": session.access_key,
        "expires": session.expires_text or None,
        "current": not args.keep_current,
        "operations": fetched or None,
        "config_file": str(config_file()),
    }
    emit(ctx, data, text=_login_text(session, fetched, current=not args.keep_current))
    return 0


def _choose_tenant(ctx: Context, session: Session, wanted: str) -> None:
    """Look the tenant up without committing anything yet."""
    if session.is_static:
        raise OvError(
            "--tenant needs a browser sign-in. An API token is already tied to one tenant."
        )

    note(ctx, "Reading the tenant list...")
    with build_client(ctx.config, session) as client:
        session.tenant_id, session.tenant = resolve_tenant(client.tenants(), wanted)


def _mint_in_tenant(ctx: Context, session: Session) -> None:
    """Replace the sign-in token with one issued inside the chosen tenant.

    Sign-in always lands in the account's own tenant, and a token is scoped to
    the tenant it was minted in, so the original cannot simply be kept.
    """
    with build_client(ctx.config, session) as client:
        client.refresh_token()


def _login_text(session: Session, fetched: int, current: bool) -> str:
    where = session.base_url
    if session.tenant:
        where += f" tenant [cyan]{session.tenant}[/cyan]"
    lines = [
        f"[green]Logged in[/green] to {where} "
        f"as [cyan]{session.alias}[/cyan] ({session.mode} credential)."
    ]
    if session.expires_text:
        lines.append(f"Token expires {session.expires_text}.")
    if fetched:
        lines.append(f"{fetched} API operations available. Try 'ov api tags'.")
    lines.append(
        "[dim]Now the default instance. Target another with 'ov -i <alias> ...'.[/dim]"
        if current
        else f"[dim]Stored, but not the default. Use it with 'ov -i {session.alias} ...'.[/dim]"
    )
    return "\n".join(lines)


def _target_url(ctx: Context) -> str:
    if ctx.args.url:
        return normalize_base_url(ctx.args.url)
    try:
        return session_store.load(ctx.instance).base_url
    except (NotLoggedIn, OvError) as exc:
        if isinstance(exc, NotLoggedIn):
            raise NotConfigured from None
        raise


def _browser_login(ctx: Context, base_url: str) -> Session:
    note(
        ctx,
        f"Opening a browser at [cyan]{base_url}/Login.do[/cyan].\n"
        "Sign in there. Single sign-on and MFA are fine: this waits until the instance "
        "itself accepts you, however many redirects that takes.\n"
        "[dim]Your password goes into the real login page, never through this tool. "
        "Only the resulting session token is stored.[/dim]",
    )
    return _login_installing_browser_if_needed(ctx, base_url, ctx.args.timeout * 1000)


def _progress(ctx: Context) -> Callable[[str], None]:
    """Say what the wait is doing.

    A five minute block with no output reads as a hang, and the reason a login
    never completes is only visible from inside the poll.
    """

    def report(message: str) -> None:
        if ctx.args.verbose:
            warn(ctx, f"[dim]{message}[/dim]")
        else:
            # Keep the elapsed seconds even in the quiet form. A line that never
            # changes cannot be told apart from a stopped process.
            warn(ctx, f"[dim]{message.split(':')[0]}, still waiting for sign-in[/dim]")

    return report


def _login_installing_browser_if_needed(ctx: Context, base_url: str, timeout_ms: int) -> Session:
    report = _progress(ctx)
    try:
        return interactive_login(
            base_url,
            timeout_ms=timeout_ms,
            on_progress=report,
            verify=ctx.config.verify_tls,
        )
    except LoginFailed as exc:
        if "Chromium is not installed" not in str(exc):
            raise

    note(
        ctx,
        "\n[yellow]The browser used for signing in is not downloaded yet[/yellow] "
        "(about 150MB, one time).",
    )
    if not sys.stdin.isatty():
        raise OvError("Run 'ov setup' first.")
    if input("Download it now? [Y/n] ").strip().lower() not in ("", "y", "yes"):
        raise OvError("Cancelled. Run 'ov setup' when you are ready.")
    if not install_chromium():
        raise OvError("Download failed. Run 'ov setup' by hand.")
    return interactive_login(
        base_url,
        timeout_ms=timeout_ms,
        on_progress=report,
        verify=ctx.config.verify_tls,
    )


def _token_login(ctx: Context, base_url: str) -> Session:
    token = ctx.args.token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if token.count(":") != 1 or not all(token.split(":")):
        raise OvError("--token expects accessKey:secretKey, as shown in Admin > Auth Tokens.")
    return Session(base_url=base_url, mode="token", bearer_token=token)


def _prefetch_spec(ctx: Context, session: Session) -> int:
    try:
        with build_client(ctx.config, session) as client:
            from ...service import OvService

            service = OvService(
                client,
                spec_group=ctx.config.spec_group,
                spec_ttl_seconds=ctx.config.spec_ttl_seconds,
            )
            return len(service.fetch_spec().operations)
    except OvError as exc:
        warn(
            ctx,
            f"[yellow]Signed in, but the API schema is unavailable:[/yellow] {exc}\n"
            "[dim]'ov request' still works; 'ov api' needs the schema.[/dim]",
        )
        return 0


def cmd_logout(ctx: Context) -> int:
    if ctx.args.all:
        return _logout_all(ctx)

    ref = ctx.args.instance_ref or ctx.instance
    try:
        session = session_store.load(ref)
    except NotLoggedIn:
        emit(ctx, {"status": "not_logged_in"}, text="Not signed in to anything.")
        return 0

    revoked = _revoke(ctx, session)
    session_store.remove(session.alias)
    reset_cache()
    cleared = ctx.cache.clear()

    remaining = session_store.current_alias()
    emit(
        ctx,
        {
            "status": "logged_out",
            "alias": session.alias,
            "base_url": session.base_url,
            "token_revoked": revoked,
            "cache_entries_cleared": cleared,
            "current": remaining,
        },
        text=_logout_text(session, revoked, remaining),
    )
    return 0


def _logout_text(session: Session, revoked: bool, remaining: str | None) -> str:
    head = (
        f"[green]Logged out[/green] of {session.alias} ({session.base_url})."
        if revoked
        else f"[green]Forgot[/green] {session.alias} ({session.base_url}). "
        "[dim]The token stays valid on the server until it expires.[/dim]"
    )
    tail = f"\nCurrent instance is now [cyan]{remaining}[/cyan]." if remaining else ""
    return head + tail


def _logout_all(ctx: Context) -> int:
    sessions = session_store.all_sessions()
    results = []
    for session in list(sessions.values()):
        results.append(
            {
                "alias": session.alias,
                "base_url": session.base_url,
                "token_revoked": _revoke(ctx, session),
            }
        )
    session_store.clear()
    reset_cache()
    ctx.cache.clear()

    emit(
        ctx,
        {"status": "logged_out", "instances": results},
        text=f"[green]Logged out[/green] of {len(results)} instance(s).",
    )
    return 0


def _revoke(ctx: Context, session: Session) -> bool:
    """Ending the web session invalidates every token it minted, so this is a
    real revocation rather than just forgetting the string."""
    if session.is_static:
        return False
    try:
        with build_client(ctx.config, session) as client:
            client.web_get(LOGOFF_PATH, accept="text/html")
    except OvError:
        return False
    return True


def cmd_whoami(ctx: Context) -> int:
    session = session_store.load(ctx.args.instance_ref or ctx.instance)
    data = session.redacted()
    data["current"] = session.alias == session_store.current_alias()
    data["spec_group"] = ctx.config.spec_group

    try:
        with build_client(ctx.config, session) as client:
            client.api("GET", "/authorize", accept="text/plain")
        data["authorized"] = True
    except OvError as exc:
        data["authorized"] = False
        data["detail"] = str(exc)

    def table():
        rows = [[k.replace("_", " ").title(), str(v)] for k, v in data.items() if v is not None]
        return build_table(
            "Signed in", [{"header": "Field", "style": "dim"}, {"header": "Value"}], rows
        )

    emit(ctx, data, table)
    return 0 if data["authorized"] else 3


def cmd_instances(ctx: Context) -> int:
    sessions = session_store.all_sessions()
    current = session_store.current_alias()

    rows = []
    for alias in sorted(sessions):
        session = sessions[alias]
        row = session.redacted()
        row["current"] = alias == current
        if ctx.args.check:
            row["authorized"] = _authorized(ctx, session)
        rows.append(row)

    def table():
        columns = [
            {"header": "", "style": "green"},
            {"header": "Alias", "style": "cyan"},
            {"header": "URL", "overflow": "fold"},
            {"header": "Mode"},
            {"header": "Expires"},
        ]
        if ctx.args.check:
            columns.append({"header": "OK"})
        body = []
        for row in rows:
            cells = [
                "*" if row["current"] else "",
                row["alias"],
                row["base_url"],
                row["mode"],
                row["expires"] or "-",
            ]
            if ctx.args.check:
                cells.append("yes" if row.get("authorized") else "no")
            body.append(cells)
        return build_table(None, columns, body)

    emit(ctx, rows, table, empty="Not signed in to anything. Run 'ov login <url>'.")
    return 0


def _authorized(ctx: Context, session: Session) -> bool:
    try:
        with build_client(ctx.config, session) as client:
            client.api("GET", "/authorize", accept="text/plain")
    except OvError:
        return False
    return True


def cmd_tenants(ctx: Context) -> int:
    session = ctx.session
    if session.is_static:
        raise OvError("Listing tenants needs a browser sign-in; an API token cannot switch.")

    available = ctx.client.tenants()
    rows = tenant_rows(available, session.tenant_id)

    def table():
        return build_table(
            f"Tenants on {session.base_url}",
            [
                {"header": "", "style": "green"},
                {"header": "Tenant", "style": "cyan"},
                {"header": "pid"},
            ],
            [["*" if r["current"] else "", r["name"], r["tenant_id"]] for r in rows],
        )

    emit(ctx, rows, table, empty=NO_TENANTS)
    return 0


def cmd_use(ctx: Context) -> int:
    session = session_store.use(ctx.args.instance_ref)
    reset_cache()
    emit(
        ctx,
        {"alias": session.alias, "base_url": session.base_url, "current": True},
        text=f"Now using [cyan]{session.alias}[/cyan] ({session.base_url}).",
    )
    return 0
