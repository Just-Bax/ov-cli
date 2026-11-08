from __future__ import annotations

import httpx

from ov.agent.api import session


def test_an_unsigned_caller_cannot_use_the_api(agent_server):
    with httpx.Client() as stranger:
        assert stranger.get(f"{agent_server}/api/health").status_code == 200

        refused = stranger.get(f"{agent_server}/api/threads")
        assert refused.status_code == 401 and "ov agent" in refused.json()["error"]

        page = stranger.get(f"{agent_server}/")
        assert page.status_code == 401 and b"Open OV Agent from your terminal" in page.content


def test_the_launch_link_signs_the_browser_in(agent_server):
    with httpx.Client() as browser:
        wrong = browser.get(f"{agent_server}/?{session.LINK_PARAM}=guess", follow_redirects=False)
        assert wrong.status_code == 401 and session.COOKIE not in browser.cookies

        opened = browser.get(session.link(agent_server, session.token()), follow_redirects=False)
        assert opened.status_code == 303 and opened.headers["Location"] == "/"
        assert "HttpOnly" in opened.headers["Set-Cookie"] and "SameSite=Strict" in opened.headers["Set-Cookie"]

        assert browser.get(f"{agent_server}/api/threads").status_code == 200
