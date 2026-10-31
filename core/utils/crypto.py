"""Field encryption (Fernet) and a keyed hash for matching without decrypting.

Key: FIELD_ENCRYPTION_KEY in .env. If unset, a key is generated into data/field.key (gitignored)
so the demo works out of the box; production must supply the key from a secret manager.
"""
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.fernet import Fernet

PREFIX = "enc:"


class FieldCipher:
    def __init__(self, key: bytes | str | None = None, key_file: Path | None = None):
        if key is None:
            key = os.getenv("FIELD_ENCRYPTION_KEY") or None
        if key is None:
            key_file = key_file or Path(__file__).resolve().parents[2] / "data" / "field.key"
            key_file.parent.mkdir(parents=True, exist_ok=True)
            if not key_file.exists():
                key_file.write_bytes(Fernet.generate_key())
            key = key_file.read_bytes()
        self._key = key.encode() if isinstance(key, str) else key
        self._fernet = Fernet(self._key)

    def encrypt(self, plain: str) -> str:
        return PREFIX + self._fernet.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        if not token.startswith(PREFIX):
            return token
        return self._fernet.decrypt(token[len(PREFIX):].encode()).decode()

    def keyed_hash(self, value: str) -> str:
        """HMAC-SHA256 under a key derived from the field key: equal values give equal hashes."""
        k = hashlib.sha256(b"field-hmac-v1" + self._key).digest()
        return hmac.new(k, value.strip().upper().encode(), hashlib.sha256).hexdigest()
