from ov.cli.commands import agent, api, auth, request, schema, settings, setup, update

GROUPS = (auth, api, request, schema, settings, setup, update, agent)

BUILTIN_NAMES = frozenset(
    {
        "login",
        "logout",
        "whoami",
        "instances",
        "tenants",
        "use",
        "api",
        "request",
        "spec",
        "config",
        "setup",
        "update",
        "agent",
        "ui",
    }
)

__all__ = ["BUILTIN_NAMES", "GROUPS"]
