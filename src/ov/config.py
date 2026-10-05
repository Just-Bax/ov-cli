from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from . import store
from .errors import OvError
from .paths import downloads_dir

TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
FALSE_WORDS = frozenset({"0", "false", "no", "off"})


@dataclass
class Config:
    spec_group: str = "v3"
    download_dir: str = ""
    cache_ttl_seconds: int = 0
    spec_ttl_seconds: int = 86400
    timeout_seconds: int = 60
    color: bool = True
    verify_tls: bool = True

    def resolved_download_dir(self) -> Path:
        if not self.download_dir:
            return downloads_dir()
        path = Path(self.download_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _known() -> set[str]:
    return {f.name for f in fields(Config)}


def load() -> Config:
    data = store.read()
    known = _known()
    return Config(**{k: v for k, v in data.items() if k in known})


def set_value(config: Config, key: str, raw: str) -> Config:
    known = _known()
    if key not in known:
        options = ", ".join(sorted(known))
        raise OvError(f"Unknown setting '{key}'. Valid settings: {options}")

    value = _parse(key, raw, getattr(config, key))
    setattr(config, key, value)
    store.update(**{key: value})
    return config


def _parse(key: str, raw: str, current: Any) -> Any:
    if isinstance(current, bool):
        return _parse_bool(key, raw)
    if not isinstance(current, int):
        return raw

    try:
        return int(raw)
    except ValueError:
        raise OvError(f"'{key}' expects a whole number, got {raw!r}") from None


def _parse_bool(key: str, raw: str) -> bool:
    word = raw.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise OvError(f"'{key}' expects true or false, got {raw!r}")


def normalize_base_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    if not value:
        raise OvError("No instance URL given.")

    if "://" not in value:
        value = f"https://{value}"
    if not value.startswith(("http://", "https://")):
        raise OvError(f"Not an http(s) URL: {raw!r}")
    return value
