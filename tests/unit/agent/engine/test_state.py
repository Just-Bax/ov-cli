from __future__ import annotations

from ov.agent.engine import state


def _turn(seq: int, n: int) -> list[dict]:
    return [
        {
            "seq": seq,
            "ts": 1,
            "event": {"type": "user", "message": {"id": f"u{n}", "role": "user", "text": f"q{n}", "ts": 1}},
        },
        {
            "seq": seq + 1,
            "ts": 1,
            "event": {
                "type": "tool",
                "tool": {"id": f"t{n}", "name": "ov", "label": "x", "status": "ok", "input": "{}", "output": "big"},
            },
        },
        {"seq": seq + 2, "ts": 1, "event": {"type": "message", "messageId": f"a{n}", "text": f"**answer {n}**"}},
    ]


def test_reducer_rewind_drops_later_items():
    s = state.empty_state({"id": "r1", "status": "queued"}, {"prompt": "hi"})
    events = [
        {"type": "user", "message": {"id": "u1", "role": "user", "text": "a", "ts": 1}},
        {"type": "text", "messageId": "a1", "delta": "he"},
        {"type": "text", "messageId": "a1", "delta": "llo"},
        {"type": "user", "message": {"id": "u2", "role": "user", "text": "b", "ts": 2}},
        {"type": "text", "messageId": "a2", "delta": "x"},
    ]

    for seq, event in enumerate(events):
        state.reduce(s, {"seq": seq, "ts": seq, "event": event})
    assert s["chat"][1]["text"] == "hello"

    state.reduce(s, {"seq": 9, "ts": 9, "event": {"type": "rewind", "itemId": "u2"}})
    assert [m["id"] for m in s["chat"]] == ["u1", "a1"]


def test_the_reducer_keeps_edits_out_of_the_thread():
    s = state.empty_state({"id": "r1", "status": "running"}, {"prompt": "hi"})
    edit = {"id": "e1", "toolId": "c1", "path": "a.py", "created": True, "added": 2, "removed": 0}
    state.reduce(s, {"seq": 1, "ts": 1, "event": {"type": "edit", "edit": edit}})
    assert s["edits"] == [edit] and s["items"] == []


def test_snapshot_keeps_recent_turns_and_outlines_the_rest():
    full = state.empty_state({"id": "r", "title": "t", "status": "done"}, {})
    for n in range(3):
        for stored in _turn(n * 3, n):
            state.reduce(full, stored)

    snap = state.snapshot(full, 2)
    assert snap["start"] == 3
    assert [x["id"] for x in snap["items"]] == ["u1", "t1", "a1", "u2", "t2", "a2"]
    assert snap["tools"][0] == {"id": "t1", "name": "ov", "label": "x", "status": "ok", "lazy": True}
    assert snap["outline"] == [
        {"kind": "user", "start": 0, "label": "q0"},
        {"kind": "agent", "start": 0, "label": "**answer 0**"},
    ]

    older = state.window(full, snap["start"], 10)
    assert older["start"] == 0
    assert [x["id"] for x in older["items"]] == ["u0", "t0", "a0"]
    assert state.details(full, {"t0"}, set())["tools"]["t0"] == {"input": "{}", "output": "big"}


def test_a_thread_is_searched_across_messages_changes_and_questions():
    s = state.empty_state({"id": "r1", "status": "done"}, {"prompt": "hi"})
    events = [
        {"type": "user", "message": {"id": "u1", "role": "user", "text": "Why is the Rule slow?", "ts": 1}},
        {"type": "message", "messageId": "a1", "text": "Looking at the rule queue.", "ts": 2},
        {"type": "tool", "tool": {"id": "t1", "name": "ov_sql", "label": "rule SQL", "status": "ok"}},
        {
            "type": "question",
            "question": {
                "id": "q1",
                "kind": "ask",
                "items": [{"header": "", "question": "Which instance?", "options": [], "multiple": False}],
            },
        },
        {
            "type": "change",
            "change": {
                "id": "c1",
                "title": "Speed up",
                "after": "select * from rule_queue",
                "what": "",
                "why": "",
                "how": "",
            },
        },
    ]

    for seq, event in enumerate(events):
        state.reduce(s, {"seq": seq, "ts": seq, "event": event})
    assert state.search(s, "RULE") == [0, 1, 4]
    assert state.search(s, "instance") == [3]
    assert state.search(s, "nothing here") == []


def test_streamed_reasoning_is_kept_on_the_message_it_belongs_to():
    s = state.empty_state({"id": "r1", "status": "queued"}, {"prompt": "hi"})
    events = [
        {"type": "reasoning", "messageId": "a1", "delta": "Check "},
        {"type": "reasoning", "messageId": "a1", "delta": "tags."},
        {"type": "text", "messageId": "a1", "delta": "Two."},
        {"type": "message", "messageId": "a2", "text": "", "ts": 5, "reasoning": "Only thought."},
    ]

    for seq, event in enumerate(events):
        state.reduce(s, {"seq": seq, "ts": seq, "event": event})

    assert [(m["id"], m["text"], m["reasoning"]) for m in s["chat"]] == [
        ("a1", "Two.", "Check tags."),
        ("a2", "", "Only thought."),
    ]
    assert [i["id"] for i in s["items"]] == ["a1", "a2"]


def test_instances_are_ordered_by_last_use():
    s = state.empty_state({"id": "r1", "status": "queued", "instance": "prod.example.com"}, "read")
    tools = [("t1", '{"instance": "dev"}'), ("t2", "{}"), ("t3", '{"instance": "prod.example.com"}')]
    for seq, (tool_id, args) in enumerate(tools):
        tool = {"id": tool_id, "name": "ov", "label": "x", "status": "ok", "input": args}
        state.reduce(s, {"seq": seq, "ts": seq, "event": {"type": "tool", "tool": tool}})
    assert s["instances"] == ["dev", "prod.example.com"]

    state.reduce(s, {"seq": 9, "ts": 9, "event": {"type": "meta", "instance": "test"}})
    assert s["instances"] == ["dev", "prod.example.com", "test"]
