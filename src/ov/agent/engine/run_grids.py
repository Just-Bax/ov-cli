from __future__ import annotations

from typing import Any

from ov.agent.engine.cancel import Cancel
from ov.agent.engine.run_branch import INHERITED_REVERT
from ov.agent.engine.run_common import RunError, uid
from ov.agent.storage import db
from ov.agent.tools import grid as grids

REVERT_REQUEST = (
    'Revert the data change "{title}" ({id}): call ov_update with revert {id} to put the old values back, '
    "after the user approves."
)
DONE = "done"


class GridsMixin:
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
