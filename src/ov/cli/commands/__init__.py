from . import api, auth, request, schema, settings, setup

GROUPS = (auth, api, request, schema, settings, setup)

# Names the generated per-tag groups must not take over. A schema tag called
# "config" would otherwise shadow the settings command.
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
    }
)

__all__ = ["GROUPS", "BUILTIN_NAMES"]
