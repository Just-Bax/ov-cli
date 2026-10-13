from __future__ import annotations

from ov.onevizion import session as session_store
from ov.onevizion.session import Session

BASE_URL = "https://acme.onevizion.test"
OTHER_URL = "https://globex.onevizion.test"


def seed_session(base_url: str, alias: str = "", token: str = "ACCESS:SECRET", **kwargs):
    return session_store.save(
        Session(
            base_url=base_url,
            alias=alias,
            mode="session",
            cookies={"JSESSIONID": "abc"},
            bearer_token=token,
            expires_at=4102444800.0,
            expires_text="2100-01-01T00:00:00",
        ),
        **kwargs,
    )
