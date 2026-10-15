from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Dialect, ForeignKey, Index, Integer, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def thread_fk() -> ForeignKey:
    return ForeignKey("thread.id", ondelete="CASCADE")


class Provider(StrEnum):
    COPILOT = "copilot"
    CLAUDE = "claude"


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
    MESSAGE = "message"
    USER = "user"
    CHANGE = "change"
    EDIT = "edit"
    OUTCOME = "outcome"
    QUESTION = "question"
    LOGIN = "login"
    QUEUED = "queued"
    UNQUEUE = "unqueue"
    REWIND = "rewind"
    ACCESS = "access"
    BROWSER = "browser"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class UsageKind(StrEnum):
    TURN = "turn"
    STEP = "step"
    NAMING = "naming"
    GUARD = "guard"


class Reasoning(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class FollowUp(StrEnum):
    STEER = "steer"
    QUEUE = "queue"


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
        one_of("provider", Provider),
        CheckConstraint("allow_write IN (0, 1)", name="allow_write_valid"),
        Index("thread_by_created", "created_at"),
        Index("thread_by_settled", "settled_at"),
        Index("thread_by_status", "status"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    instance: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    allow_write: Mapped[bool] = mapped_column(Integer)
    pinned_at: Mapped[int | None] = mapped_column(Integer)
    snoozed_until: Mapped[int | None] = mapped_column(Integer)
    settled_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class Attachment(Base):
    __tablename__ = "attachment"
    __table_args__ = (Index("attachment_by_thread", "thread_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(Text, thread_fk())
    turn_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer)


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
        one_of("provider", Provider),
        Index("usage_by_thread", "thread_id"),
        Index("usage_by_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(Text, thread_fk())
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer)
    cached_tokens: Mapped[int] = mapped_column(Integer)
    cache_write_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_nano: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)


class Preference(Base):
    __tablename__ = "preference"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        one_of("reasoning", Reasoning, nullable=True),
        one_of("provider", Provider),
        one_of("follow_up", FollowUp),
        CheckConstraint("max_steps BETWEEN 1 AND 500", name="max_steps_valid"),
        CheckConstraint("expand_tools IN (0, 1)", name="expand_tools_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    provider: Mapped[str] = mapped_column(Text)
    default_model: Mapped[str | None] = mapped_column(Text)
    fast_model: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)
    max_steps: Mapped[int] = mapped_column(Integer)
    follow_up: Mapped[str] = mapped_column(Text)
    workspace: Mapped[str | None] = mapped_column(Text)
    workspace_notes: Mapped[str | None] = mapped_column(Text)
    expand_tools: Mapped[bool] = mapped_column(Integer)
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
