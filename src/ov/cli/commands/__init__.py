from . import agent, api, auth, request, schema, settings, setup

GROUPS = (auth, api, request, schema, settings, setup, agent)

# Reserved so a schema tag such as "config" cannot shadow a built-in command.
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

__all__ = ["GROUPS", "BUILTIN_NAMES"]
