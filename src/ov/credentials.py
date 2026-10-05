from __future__ import annotations

import base64
import json
import os
import secrets as random
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import store
from .errors import OvError
from .paths import home, restrict, write_atomic

SERVICE = "ov-cli"
KEY_NAME = "vault-key"
BACKEND_ENV = "OV_CREDENTIALS"
FILE_BACKEND = "file"
VAULT_VERSION = 1
ASSOCIATED_DATA = b"ov-vault-v1"
NONCE_BYTES = 12
KEY_BYTES = 32


class CredentialsError(OvError):
    pass


def get(key: str) -> dict[str, Any] | None:
    with store.lock():
        return _read().get(key)


def put(key: str, secrets: dict[str, Any]) -> None:
    with store.lock():
        vault = _read()
        vault[key] = secrets
        _write(vault)


def delete(key: str) -> None:
    with store.lock():
        vault = _read()
        if vault.pop(key, None) is not None:
            _write(vault)


def keys() -> list[str]:
    with store.lock():
        return sorted(_read())


def vault_file() -> Path:
    return home() / "vault"


def key_file() -> Path:
    return home() / "vault.key"


def _read() -> dict[str, Any]:
    path = vault_file()
    if not path.exists():
        return {}

    key = _stored_key()
    if key is None:
        raise CredentialsError(f"The key for {path} is missing. Delete the vault to sign in again.")

    envelope = json.loads(path.read_text(encoding="utf-8"))
    try:
        plain = AESGCM(key).decrypt(
            base64.b64decode(envelope["nonce"]),
            base64.b64decode(envelope["data"]),
            ASSOCIATED_DATA,
        )
    except InvalidTag as exc:
        raise CredentialsError(f"{path} does not match its key. Delete the vault to sign in again.") from exc

    return json.loads(plain)


def _write(vault: dict[str, Any]) -> None:
    key = _stored_key() or _new_key()
    nonce = random.token_bytes(NONCE_BYTES)
    data = AESGCM(key).encrypt(nonce, json.dumps(vault, separators=(",", ":")).encode(), ASSOCIATED_DATA)

    envelope = {
        "version": VAULT_VERSION,
        "nonce": base64.b64encode(nonce).decode(),
        "data": base64.b64encode(data).decode(),
    }
    write_atomic(vault_file(), json.dumps(envelope))


def _uses_file() -> bool:
    return os.environ.get(BACKEND_ENV, "").strip().lower() == FILE_BACKEND


def _stored_key() -> bytes | None:
    if _uses_file():
        path = key_file()
        return base64.b64decode(path.read_text(encoding="utf-8").strip()) if path.exists() else None
    stored = _keyring().get_password(SERVICE, KEY_NAME)
    return base64.b64decode(stored) if stored else None


def _new_key() -> bytes:
    key = random.token_bytes(KEY_BYTES)
    encoded = base64.b64encode(key).decode()
    if _uses_file():
        write_atomic(key_file(), encoded)
        restrict(key_file())
        return key

    _keyring().set_password(SERVICE, KEY_NAME, encoded)
    return key


def _keyring() -> Any:
    import keyring
    from keyring.backends import fail

    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring) or backend.priority < 1:
        raise CredentialsError(
            f"No system keyring is available. Set {BACKEND_ENV}={FILE_BACKEND} to keep the vault key in {key_file()}."
        )
    return backend
