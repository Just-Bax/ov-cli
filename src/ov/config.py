from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from . import store
from .errors import OvError
from .paths import downloads_dir


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
        if self.download_dir:
            path = Path(self.download_dir).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            return path
        return downloads_dir()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _known() -> set[str]:
    return {f.name for f in fields(Config)}


def load() -> Config:
    data = store.read()
    known = _known()
    return Config(**{k: v for k, v in data.items() if k in known})


def save(config: Config) -> None:
    store.update(**config.to_dict())


def set_value(config: Config, key: str, raw: str) -> Config:
    known = _known()
    if key not in known:
        options = ", ".join(sorted(known))
        raise OvError(f"Unknown setting '{key}'. Valid settings: {options}")

    current = getattr(config, key)
    if isinstance(current, bool):
        value: Any = raw.strip().lower() in ("1", "true", "yes", "on")
    elif isinstance(current, int):
        try:
            value = int(raw)
        except ValueError:
            raise OvError(f"'{key}' expects a whole number, got {raw!r}") from None
    else:
        value = raw

    setattr(config, key, value)
    store.update(**{key: value})
    return config


def normalize_base_url(raw: str) -> str:
    """Accept a bare hostname as well as a URL, since that is what people paste
    out of the address bar."""
    value = raw.strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    if not value.startswith(("http://", "https://")):
        raise OvError(f"Not an http(s) URL: {raw!r}")
    return value
