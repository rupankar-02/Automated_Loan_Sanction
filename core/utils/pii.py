"""PII handling.

  Aadhaar number, account number -> stored and shown masked (last 4 digits only).
  PAN                            -> stored encrypted (full), shown masked by default.
Masking is applied to raw_value AND normalized_value before anything is written.
"""
from core.utils.crypto import FieldCipher

MASKED_KEYS = {"aadhaar_number", "account_number"}
ENCRYPTED_KEYS = {"pan_number", "employee_pan", "pan"}
SENSITIVE_KEYS = MASKED_KEYS | ENCRYPTED_KEYS


def mask_tail(value: str, keep: int = 4) -> str:
    v = "".join(c for c in value if not c.isspace())
    return ("X" * max(len(v) - keep, 0)) + v[-keep:] if v else v


def mask_pan(value: str) -> str:
    """ABCDE1234F -> ABCDE****F"""
    v = value.strip().upper()
    return v[:5] + "****" + v[-1] if len(v) == 10 else mask_tail(v, 1)


def display_value(key: str, value: str | None, *, reveal: bool = False, validated: bool = True) -> str:
    """Value for the UI. A PAN that failed validation is shown as read so the user can correct it."""
    if value is None:
        return ""
    if key in MASKED_KEYS:
        return mask_tail(value)
    if key in ENCRYPTED_KEYS and not reveal and validated:
        return mask_pan(value)
    return value


def protect_value(key: str, value: str | None, cipher: FieldCipher) -> tuple[str | None, str | None]:
    """What may be written to storage: (stored_value, keyed_hash_or_None)."""
    if value is None:
        return None, None
    if key in MASKED_KEYS:
        return mask_tail(value), None
    if key in ENCRYPTED_KEYS:
        return cipher.encrypt(value), cipher.keyed_hash(value)
    return value, None


def scrub_state_value(key: str, value: str | None) -> str | None:
    """In-memory equivalent after saving: nothing sensitive stays in full in the session."""
    if value is None:
        return None
    if key in MASKED_KEYS:
        return mask_tail(value)
    if key in ENCRYPTED_KEYS:
        return mask_pan(value)
    return value
