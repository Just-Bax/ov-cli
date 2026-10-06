from __future__ import annotations

EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_NOT_FOUND = 4
EXIT_API = 5
EXIT_FORBIDDEN = 6
EXIT_READ_ONLY = 7
EXIT_INTERRUPTED = 130


class OvError(Exception):
    exit_code = EXIT_ERROR


class NotConfigured(OvError):
    def __init__(self) -> None:
        super().__init__("No OneVizion instance configured. Run 'ov login https://yours.onevizion.com'.")


class NotLoggedIn(OvError):
    exit_code = EXIT_AUTH

    def __init__(self) -> None:
        super().__init__("Not logged in. Run 'ov login' first.")


class SessionExpired(OvError):
    exit_code = EXIT_AUTH

    def __init__(self, detail: str = "") -> None:
        message = "OneVizion session expired. Run 'ov login' again."
        super().__init__(f"{message} ({detail})" if detail else message)


class LoginFailed(OvError):
    exit_code = EXIT_AUTH


class NotFound(OvError):
    exit_code = EXIT_NOT_FOUND


class Ambiguous(OvError):
    exit_code = EXIT_NOT_FOUND


class Forbidden(OvError):
    exit_code = EXIT_FORBIDDEN


class ReadOnlyBlocked(OvError):
    exit_code = EXIT_READ_ONLY


class ApiError(OvError):
    exit_code = EXIT_API

    def __init__(self, status: int, message: str, body: object = None, url: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.url = url

    def to_dict(self) -> dict[str, object]:
        return {
            "error": str(self),
            "exit_code": self.exit_code,
            "status": self.status,
            "url": self.url,
            "body": self.body,
        }


class Unreachable(OvError):
    pass


class SpecUnavailable(OvError):
    exit_code = EXIT_API
