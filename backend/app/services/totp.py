"""
TOTP (RFC 6238) — 2-step verification, implemented with the Python stdlib only
(no pyotp dependency). Compatible with Google Authenticator, Authy, 1Password, etc.

  secret      = generate_secret()                 # base32, store per user
  uri         = provisioning_uri(secret, email)   # otpauth:// — render as a QR
  ok          = verify(secret, "123456")          # ±1 step clock-skew tolerance
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from app.config import get_settings

PERIOD = 30   # seconds per code
DIGITS = 6


def generate_secret() -> str:
    """A new base32 secret (160 bits of entropy), no padding."""
    return base64.b32encode(secrets.token_bytes(20)).decode("utf-8").rstrip("=")


def _code_at(secret: str, for_time: int) -> str:
    counter = int(for_time) // PERIOD
    # Re-pad the base32 secret to a multiple of 8 chars before decoding.
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** DIGITS)).zfill(DIGITS)


def verify(secret: str, code: str, window: int = 1) -> bool:
    """True if `code` is valid now (±`window` steps for clock skew). Constant-time."""
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return False
    now = int(time.time())
    for w in range(-window, window + 1):
        if hmac.compare_digest(_code_at(secret, now + w * PERIOD), code):
            return True
    return False


def generate_backup_codes(n: int = 8) -> list[str]:
    """n human-friendly one-time recovery codes, e.g. 'a1b2-c3d4'."""
    out = []
    for _ in range(n):
        raw = secrets.token_hex(4)  # 8 hex chars
        out.append(f"{raw[:4]}-{raw[4:]}")
    return out


def hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.strip().replace(" ", "").lower().encode()).hexdigest()


def provisioning_uri(secret: str, account: str, issuer: str | None = None) -> str:
    """otpauth:// URI for QR enrollment in an authenticator app. The issuer
    (shown in the authenticator) defaults to the product name."""
    issuer = issuer or get_settings().product_name
    label = quote(f"{issuer}:{account}")
    return (f"otpauth://totp/{label}?secret={secret}"
            f"&issuer={quote(issuer)}&period={PERIOD}&digits={DIGITS}&algorithm=SHA1")
