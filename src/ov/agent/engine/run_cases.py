from __future__ import annotations

from ov.agent.engine import cases
from ov.agent.engine.cancel import Cancel
from ov.agent.engine.run_common import RunError, uid
from ov.agent.engine.run_titles import TITLE_CHARS, short_title
from ov.agent.engine.run_tools import TOOL_ERROR_CHARS, TOOL_OUTPUT_CHARS
from ov.agent.storage import db
from ov.agent.tools.base import clip

LOGIN_ATTEMPTS = 2


class CasesMixin:
    def _preload_case(self, ref: str) -> str:
        tool = {"id": uid("load"), "name": "ov_case", "label": f"Read case {ref} from trackor"}
        started = db.now_ms()
        self.emit({"type": "tool", "tool": {**tool, "status": "running"}})
        try:
            text = self.load_case(ref)
        except Exception as exc:
            self._tool_done(tool, "error", started, str(exc)[:TOOL_ERROR_CHARS])
            raise
        self._tool_done(tool, "ok", started, text[:TOOL_OUTPUT_CHARS])
        return f"Troubleshoot this case.\n\n{clip(text, self, 'case')}"

    def load_case(self, ref: str) -> str:
        return self.read_case(ref, self.cancel, names_thread=True)

    def read_case(self, ref: str, cancel: Cancel, names_thread: bool = False) -> str:
        for attempt in range(LOGIN_ATTEMPTS):
            try:
                bundle = cases.load_case(ref, self.work_dir, cancel)
                break
            except cases.NeedsLogin as exc:
                if attempt or not self.require_login(exc.host):
                    raise RunError(f"Not signed in to {exc.host}.") from None

        text = cases.render(bundle, self.work_dir)
        if self.state["summary"].get("caseKey"):
            return text

        meta = {"type": "meta", "caseKey": bundle["key"], "caseUrl": bundle["url"], "instance": bundle["website"]}
        if names_thread:
            title = " ".join(bundle["title"].split()) or f"Case {bundle['key']}"
            meta["title"] = short_title(f"{bundle['key']}: {title}", TITLE_CHARS)
        self.emit(meta)
        if bundle["website"]:
            text += f"\n\nThe run's default instance is now {bundle['website']}."
        return text
