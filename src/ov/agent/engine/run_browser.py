from __future__ import annotations

from ov.agent.engine.cancel import Cancel
from ov.agent.engine.run_common import RunError
from ov.agent.instances.ovproc import find_instance, web_cookies
from ov.agent.integrations.common import Usage
from ov.agent.storage.models import UsageKind

BROWSER_OPENED_NOTE = (
    "The user opened {alias} in the browser beside the chat. You both see it and the user may click in it too. "
    "Questions about what is on screen and requests to go somewhere or do something there are about this browser: "
    "hand them to browser_run as goals; ov only reads while it is open."
)
BROWSER_CLOSED_NOTE = "The user closed the browser."


class BrowserMixin:
    def open_browser(self, ref: str) -> None:
        wanted = ref or self.instance
        if not wanted:
            raise RunError("This thread has no instance yet.")

        found = find_instance(wanted)
        if found is None:
            raise RunError(f"{wanted} is not a signed-in instance.")

        pilot = self.browser.start(found["alias"], found["url"], web_cookies(found["alias"]))
        self._notes.append(BROWSER_OPENED_NOTE.format(alias=found["alias"]))
        self.browser.navigate(pilot.url_of(""))

    def close_browser(self) -> None:
        if self.browser.live:
            self._notes.append(BROWSER_CLOSED_NOTE)
        self.browser.close()

    def drive_browser(self, goal: str, cancel: Cancel) -> str:
        return self.agent.drive_browser(self, self._helper_model(), goal, cancel)

    def record_step_usage(self, model: str, usage: Usage | None) -> None:
        self.record_usage(model, UsageKind.STEP, usage)
