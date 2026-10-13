from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Dialect, Index, Integer, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class JsonText(TypeDecorator[Any]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, _dialect: Dialect) -> str:
        return json.dumps(value)

    def process_result_value(self, value: str | None, _dialect: Dialect) -> Any:
        return None if value is None else json.loads(value)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JsonText)


class Run(Base):
    __tablename__ = "run"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    instance: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JsonText)
    saved_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class Event(Base):
    __tablename__ = "event"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JsonText)


class Conversation(Base):
    __tablename__ = "conversation"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    messages: Mapped[Any] = mapped_column(JsonText)


class Settled(Base):
    __tablename__ = "settled"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ts: Mapped[int] = mapped_column(Integer)


class Pinned(Base):
    __tablename__ = "pinned"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ts: Mapped[int] = mapped_column(Integer)


class Snoozed(Base):
    __tablename__ = "snoozed"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    until: Mapped[int] = mapped_column(Integer)


class Feedback(Base):
    __tablename__ = "feedback"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rating: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text)
    ts: Mapped[int] = mapped_column(Integer)


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (Index("usage_by_run", "run_id"), Index("usage_by_time", "ts"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(Text)
    ts: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    tokens: Mapped[dict[str, int]] = mapped_column(JsonText)
    nano: Mapped[int] = mapped_column(Integer)


class Skill(Base):
    __tablename__ = "skill"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
