from . import agent, api, auth, request, schema, settings, setup

GROUPS = (auth, api, request, schema, settings, setup, agent)

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
        "agent",
        "ui",
    }
)

__all__ = ["BUILTIN_NAMES", "GROUPS"]
