from __future__ import annotations

import pytest


def test_bad_sign_in_input_is_refused():
    from ov.agent.api.screen import ScreenError, _checked

    assert _checked({"type": "mouse", "event": "mousePressed", "x": 3, "y": 4, "button": "left"})["x"] == 3.0
    for bad in (
        {"type": "mouse", "event": "mousePressed", "x": "a", "y": 1},
        {"type": "wheel", "x": 1, "y": 1, "dx": None},
        {"type": "key", "event": "keyDown", "keyCode": "13"},
        {"type": "eval"},
    ):
        with pytest.raises(ScreenError):
            _checked(bad)
