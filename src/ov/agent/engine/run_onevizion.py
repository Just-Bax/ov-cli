from __future__ import annotations

from typing import Any

from ov.agent.engine import cases
from ov.agent.engine.cancel import Cancel
from ov.agent.engine.run_branch import INHERITED_REVERT
from ov.agent.engine.run_common import RunError, uid
from ov.agent.engine.run_titles import TITLE_CHARS, short_title
from ov.agent.engine.run_tools import TOOL_ERROR_CHARS, TOOL_OUTPUT_CHARS
from ov.agent.storage import db
from ov.agent.tools import grid as grids
from ov.agent.tools.base import clip

LOGIN_ATTEMPTS = 2
REVERT_REQUEST = (
    'Revert the data change "{title}" ({id}): call ov_update with revert {id} to put the old values back, '
    "after the user approves."
)
DONE = "done"


class OneVizionMixin:
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
        with self._lock:
            known = {case["key"] for case in self.state["cases"]}
        if bundle["key"] in known:
            return text

        meta = {"type": "meta", "caseKey": bundle["key"], "caseUrl": bundle["url"]}
        if known:
            self.emit(meta)
            return text

        meta["instance"] = bundle["website"]
        if names_thread:
            title = " ".join(bundle["title"].split()) or f"Case {bundle['key']}"
            meta["title"] = short_title(f"{bundle['key']}: {title}", TITLE_CHARS)
        self.emit(meta)

        if bundle["website"]:
            text += f"\n\nThe run's default instance is now {bundle['website']}."
        return text

    def _grid(self, grid_id: str) -> dict[str, Any]:
        with self._lock:
            found = next((g for g in self.state["grids"] if g["id"] == grid_id), None)
        if found is None:
            raise RunError("No such grid in this thread.")
        return found

    def rerun_grid(self, grid_id: str) -> None:
        grid = self._grid(grid_id)
        if not grid.get("source") or not grid.get("instance"):
            raise RunError("This grid shows data the agent already had. Ask the agent to load it again.")
        if grid.get("loading"):
            return

        self.emit({"type": "grid", "grid": {"id": grid_id, "loading": True, "error": None}})
        self._spawn(self._reload_grid, grid_id, grid["instance"], grid["source"])

    def _reload_grid(self, grid_id: str, alias: str, source: dict[str, Any]) -> None:
        try:
            rows, total = grids.fetch(alias, source, Cancel())
        except Exception as exc:
            self.emit({"type": "grid", "grid": {"id": grid_id, "loading": False, "error": str(exc)}})
            return

        update = {"id": grid_id, "loading": False, "error": None, "rows": rows, "total": total, "ranAt": db.now_ms()}
        self.emit({"type": "grid", "grid": update})

    def revert_grid(self, grid_id: str) -> None:
        if self.inherited_item(grid_id):
            raise RunError(INHERITED_REVERT)

        grid = self._grid(grid_id)
        change = grid.get("change")
        if not change or change["state"] != DONE or not change["updated"]:
            raise RunError("Only a finished data change that updated rows can be reverted.")

        self.follow_up(uid("u"), REVERT_REQUEST.format(title=grid["title"], id=grid_id), [], False)
