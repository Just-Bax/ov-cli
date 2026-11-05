from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Dialect, ForeignKey, Index, Integer, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MAX_STEPS_LIMIT = 500


def thread_fk() -> ForeignKey:
    return ForeignKey("thread.id", ondelete="CASCADE")


def parent_fk() -> ForeignKey:
    return ForeignKey("thread.id", ondelete="SET NULL")


class ThreadStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    STATUS = "status"
    META = "meta"
    TOOL = "tool"
    AGENT_MESSAGE = "agent_message"
    USER_MESSAGE = "user_message"
    CHANGE = "change"
    GRID = "grid"
    EDIT = "edit"
    OUTCOME = "outcome"
    QUESTION = "question"
    LOGIN = "login"
    QUEUE_ADD = "queue_add"
    QUEUE_REMOVE = "queue_remove"
    QUEUE_ORDER = "queue_order"
    REWIND = "rewind"
    ACCESS = "access"
    BROWSER = "browser"
    COMPACT = "compact"
    CONTEXT = "context"


class Origin(StrEnum):
    BRANCH = "branch"


class FollowUp(StrEnum):
    STEER = "steer"
    QUEUE = "queue"


class Access(StrEnum):
    READ = "read"
    ASK = "ask"
    AUTO = "auto"
    FULL = "full"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class UsageKind(StrEnum):
    TURN = "turn"
    AGENT = "agent"
    BROWSER = "browser"
    TITLE = "title"
    GUARD = "guard"
    SUMMARY = "summary"


class Reasoning(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class SkillSource(StrEnum):
    BUNDLED = "bundled"
    CUSTOM = "custom"


def one_of(column: str, values: type[StrEnum], nullable: bool = False) -> CheckConstraint:
    allowed = ", ".join(f"'{v.value}'" for v in values)
    condition = f"{column} IN ({allowed})"
    return CheckConstraint(f"{column} IS NULL OR {condition}" if nullable else condition, name=f"{column}_valid")


class JsonText(TypeDecorator[Any]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, _dialect: Dialect) -> str | None:
        return None if value is None else json.dumps(value)

    def process_result_value(self, value: str | None, _dialect: Dialect) -> Any:
        return None if value is None else json.loads(value)


class Base(DeclarativeBase):
    pass


class Thread(Base):
    __tablename__ = "thread"
    __table_args__ = (
        one_of("status", ThreadStatus),
        one_of("access", Access),
        one_of("origin", Origin, nullable=True),
        CheckConstraint("inherited_until >= 0", name="inherited_until_valid"),
        Index("thread_by_updated", "updated_at"),
        Index("thread_by_settled", "settled_at"),
        Index("thread_by_status", "status"),
        Index("thread_by_parent", "parent_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    instance: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    access: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[str | None] = mapped_column(Text, parent_fk())
    origin: Mapped[str | None] = mapped_column(Text)
    origin_turn_id: Mapped[str | None] = mapped_column(Text)
    inherited_until: Mapped[int] = mapped_column(Integer)
    pinned_at: Mapped[int | None] = mapped_column(Integer)
    snoozed_until: Mapped[int | None] = mapped_column(Integer)
    settled_at: Mapped[int | None] = mapped_column(Integer)
    status_changed_at: Mapped[int | None] = mapped_column(Integer)
    seen_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class Event(Base):
    __tablename__ = "event"
    __table_args__ = (one_of("type", EventType),)

    thread_id: Mapped[str] = mapped_column(Text, thread_fk(), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    type: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JsonText)
    created_at: Mapped[int] = mapped_column(Integer)


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (one_of("role", MessageRole),)

    thread_id: Mapped[str] = mapped_column(Text, thread_fk(), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[Any] = mapped_column(JsonText, nullable=True)
    tool_calls: Mapped[Any] = mapped_column(JsonText, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(Text)
    turn_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer)


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (
        one_of("kind", UsageKind),
        Index("usage_by_thread", "thread_id"),
        Index("usage_by_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(Text, thread_fk())
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_tokens: Mapped[int] = mapped_column(Integer)
    cache_write_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_nano: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)


class Preference(Base):
    __tablename__ = "preference"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        one_of("reasoning", Reasoning, nullable=True),
        CheckConstraint(f"max_steps BETWEEN 1 AND {MAX_STEPS_LIMIT}", name="max_steps_valid"),
        CheckConstraint("notify IN (0, 1)", name="notify_valid"),
        CheckConstraint("tab_badge IN (0, 1)", name="tab_badge_valid"),
        CheckConstraint("compact_branches IN (0, 1)", name="compact_branches_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    provider: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)
    max_steps: Mapped[int] = mapped_column(Integer)
    workspace: Mapped[str | None] = mapped_column(Text)
    workspace_notes: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)
    notify: Mapped[bool] = mapped_column(Integer)
    tab_badge: Mapped[bool] = mapped_column(Integer)
    compact_branches: Mapped[bool] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ProviderModel(Base):
    __tablename__ = "provider_model"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    default_model: Mapped[str | None] = mapped_column(Text)
    fast_model: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[int] = mapped_column(Integer)


class Skill(Base):
    __tablename__ = "skill"
    __table_args__ = (
        one_of("source", SkillSource),
        CheckConstraint("enabled IN (0, 1)", name="enabled_valid"),
    )

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
