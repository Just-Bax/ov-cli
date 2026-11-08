from __future__ import annotations

import base64
import html
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, CDPSession

from ov.browser.model import BrowserError

STAY_PUT_STATUS = 204
PAGE_REQUESTS = [{"urlPattern": "*", "resourceType": "Document", "requestStage": "Request"}]
PREVIEW_PATH = "/ov-agent-preview/"
PREVIEW_WIDGET = "widget.html"
PREVIEW_STATUS = 200
PREVIEW_SANDBOX = "allow-same-origin allow-scripts allow-forms allow-downloads allow-popups"
PREVIEW_PAGE = (
    '<!doctype html><html><head><meta charset="utf-8"><meta name="_csrf" content="{csrf}">'
    "<title>{name} preview</title><style>html,body{{margin:0;height:100%}}"
    "iframe{{border:0;width:100%;height:100%;display:block}}</style></head>"
    '<body><iframe src="{src}" sandbox="{sandbox}"></iframe></body></html>'
)

Allows = Callable[[str], bool]


class Fence:
    def __init__(self, context: BrowserContext, allows: Allows) -> None:
        browser = context.browser
        if browser is None:
            raise BrowserError("The browser has no control session to keep pages on the instance.")

        self._allows = allows
        self._previews: dict[str, bytes] = {}
        session = browser.new_browser_cdp_session()
        session.on("Fetch.requestPaused", lambda event: self._paused(session, event))
        session.send("Fetch.enable", {"patterns": PAGE_REQUESTS})

    def preview(self, name: str, page: str, csrf: str) -> str:
        wrapper = f"{PREVIEW_PATH}{name}"
        widget = f"{wrapper}/{PREVIEW_WIDGET}"
        self._previews[widget] = page.encode()
        self._previews[wrapper] = PREVIEW_PAGE.format(
            csrf=html.escape(csrf), name=html.escape(name), src=widget, sandbox=PREVIEW_SANDBOX
        ).encode()
        return wrapper

    def _paused(self, session: CDPSession, event: dict[str, Any]) -> None:
        request = event["requestId"]
        url = event["request"]["url"]
        if "redirectedRequestId" in event:
            session.send("Fetch.continueRequest", {"requestId": request})
        elif not self._allows(url):
            session.send("Fetch.fulfillRequest", {"requestId": request, "responseCode": STAY_PUT_STATUS})
        elif urlsplit(url).path in self._previews:
            self._serve_preview(session, request, self._previews[urlsplit(url).path])
        else:
            session.send("Fetch.continueRequest", {"requestId": request})

    def _serve_preview(self, session: CDPSession, request: str, page: bytes) -> None:
        session.send(
            "Fetch.fulfillRequest",
            {
                "requestId": request,
                "responseCode": PREVIEW_STATUS,
                "responseHeaders": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
                "body": base64.b64encode(page).decode("ascii"),
            },
        )
