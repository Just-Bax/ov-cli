from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from ov.agent.engine.cancel import Cancel
from ov.agent.integrations.common import Usage

if TYPE_CHECKING:
    from ov.agent.engine.run import Run

SUMMARY_OUTPUT_RESERVE = 20_000
AUTO_COMPACT_BUFFER = 13_000


class CostUnit(StrEnum):
    USD = "usd"
    CREDITS = "credits"
    TOKENS = "tokens"


class Initiator(StrEnum):
    USER = "user"
    AGENT = "agent"


class ModelUnavailable(Exception):
    def __init__(self, provider: str, model: str) -> None:
        super().__init__(f"Model {model} is not available on {provider}. Pick another one in Settings.")


@dataclass(frozen=True)
class ContextLimits:
    window: int
    prompt: int
    output: int

    @property
    def compact_at(self) -> int:
        room = min(self.window - min(self.output, SUMMARY_OUTPUT_RESERVE), self.prompt)
        return room - AUTO_COMPACT_BUFFER


class AgentProvider(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    cost_unit: ClassVar[CostUnit]
    cache_ttl_ms: ClassVar[int | None]
    errors: ClassVar[tuple[type[Exception], ...]]

    @abstractmethod
    def account(self) -> dict[str, Any]: ...

    @abstractmethod
    def list_models(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def default_models(self) -> tuple[str | None, str | None]: ...

    @abstractmethod
    def helper_model(self, chosen: str) -> str: ...

    @abstractmethod
    def complete(self, model: str, system: str, user_text: str, max_tokens: int) -> tuple[str, Usage | None]: ...

    @abstractmethod
    def summarize(self, model: str, prompt: str, transcript: str) -> tuple[str, Usage | None]: ...

    @abstractmethod
    def run_turn(self, run: Run, initiator: Initiator) -> None: ...

    @abstractmethod
    def has_context(self, run: Run) -> bool: ...

    @abstractmethod
    def compact(self, run: Run) -> None: ...

    @abstractmethod
    def drive_browser(self, run: Run, model: str, goal: str, cancel: Cancel) -> str: ...

    @abstractmethod
    def retry_anchor(self, run: Run, item_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def branch_context(self, source: Run, child: Run, before: str | None) -> None: ...

    @abstractmethod
    def forget_thread(self, events: list[dict[str, Any]], folder: str) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def signed_in(self) -> bool:
        return bool(self.account()["signedIn"])

    def model_info(self, model: str) -> dict[str, Any]:
        found = next((m for m in self.list_models() if m["id"] == model), None)
        if found is None:
            raise ModelUnavailable(self.name, model)
        return found

    def supports_vision(self, model: str) -> bool:
        return bool(self.model_info(model)["vision"])

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "costUnit": self.cost_unit.value,
            "cacheTtlMs": self.cache_ttl_ms,
            "account": self.account(),
        }
