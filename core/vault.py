"""Encrypted credential vault for EloPhanto.

Stores website credentials (and arbitrary secrets) in an AES-encrypted
file using Fernet (``cryptography`` library).  The encryption key is
derived from a user-provided master password via PBKDF2-HMAC-SHA256.

Files:
    ``vault.salt``  — random 16-byte salt (not secret, but unique per vault)
    ``vault.enc``   — Fernet-encrypted JSON blob

Both files are in ``.gitignore`` by default.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

_SALT_FILE = "vault.salt"
_ENC_FILE = "vault.enc"
_KDF_ITERATIONS = 480_000  # OWASP recommendation for PBKDF2-SHA256


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte Fernet key from *password* + *salt*."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


class VaultError(Exception):
    """Raised for vault-related failures."""


class Vault:
    """Encrypted key-value credential store.

    Usage::

        vault = Vault.create("/path/to/project", "master-password")
        vault.set("google.com", {"email": "me@gmail.com", "password": "s3cret"})
        creds = vault.get("google.com")

        # Later:
        vault = Vault.unlock("/path/to/project", "master-password")
        creds = vault.get("google.com")
    """

    def __init__(self, base_dir: str | Path, fernet: Fernet, data: dict[str, Any]) -> None:
        self._base = Path(base_dir)
        self._fernet = fernet
        self._data: dict[str, Any] = data

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, base_dir: str | Path, password: str) -> Vault:
        """Create a new vault (overwrites existing vault files)."""
        base = Path(base_dir)
        salt = os.urandom(16)
        key = _derive_key(password, salt)
        fernet = Fernet(key)

        vault = cls(base, fernet, {})
        (base / _SALT_FILE).write_bytes(salt)
        vault._save()
        logger.info("Vault created at %s", base)
        return vault

    @classmethod
    def unlock(cls, base_dir: str | Path, password: str) -> Vault:
        """Unlock an existing vault.

        Raises ``VaultError`` if the vault doesn't exist or the
        password is wrong.
        """
        base = Path(base_dir)
        salt_path = base / _SALT_FILE
        enc_path = base / _ENC_FILE

        if not salt_path.exists() or not enc_path.exists():
            raise VaultError("No vault found. Run `elophanto vault init` to create one.")

        salt = salt_path.read_bytes()
        key = _derive_key(password, salt)
        fernet = Fernet(key)

        try:
            plaintext = fernet.decrypt(enc_path.read_bytes())
            data = json.loads(plaintext.decode("utf-8"))
        except InvalidToken as err:
            raise VaultError("Wrong password.") from err
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise VaultError(f"Vault data is corrupted: {exc}") from exc

        return cls(base, fernet, data)

    @classmethod
    def exists(cls, base_dir: str | Path) -> bool:
        """Check whether vault files exist."""
        base = Path(base_dir)
        return (base / _SALT_FILE).exists() and (base / _ENC_FILE).exists()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """Retrieve a credential by key (e.g. domain name)."""
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        """Store a credential and persist to disk."""
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> bool:
        """Delete a credential. Returns True if it existed."""
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False

    def list_keys(self) -> list[str]:
        """List all stored credential keys."""
        return list(self._data.keys())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Encrypt and write data to disk."""
        plaintext = json.dumps(self._data, ensure_ascii=False).encode("utf-8")
        ciphertext = self._fernet.encrypt(plaintext)
        (self._base / _ENC_FILE).write_bytes(ciphertext)
