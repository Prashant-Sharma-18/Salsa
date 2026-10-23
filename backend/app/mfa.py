"""Two-factor authentication with time-based one-time passwords (RFC 6238).

Compatible with Google Authenticator, Microsoft Authenticator, 1Password,
Authy and similar apps (SHA-1, 6 digits, 30-second steps).

- Secrets are encrypted at rest with Fernet. The key comes from
  ``MFA_ENCRYPTION_KEY`` or, if unset, is derived from ``SECRET_KEY``
  (rotating SECRET_KEY then requires users to re-enrol).
- Codes are accepted for the current step +/- one (clock drift) and each
  step can be used once (``users.mfa_last_step``) to block replay.
- Recovery codes are random, single use and stored as SHA-256 hashes.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import segno
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from .extensions import db
from .models import MfaRecoveryCode, User, utcnow

DIGITS = 6
PERIOD = 30
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10


def _fernet() -> Fernet:
    key = current_app.config.get("MFA_ENCRYPTION_KEY")
    if not key:
        digest = hashlib.sha256(("mfa-encryption:" + current_app.config["SECRET_KEY"]).encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**DIGITS)
    return str(code).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // PERIOD)


def totp(secret: str, now: float | None = None) -> str:
    return _hotp(secret, current_step(now))


def match_step(secret: str, code: str, now: float | None = None) -> int | None:
    """Return the matching time step for ``code`` within the drift window, or None."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if hmac.compare_digest(_hotp(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, email: str) -> str:
    issuer = current_app.config["APP_NAME"]
    label = quote(f"{issuer}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={PERIOD}"


def qr_svg(data: str, scale: int = 8) -> str:
    """Standalone SVG markup for a QR code (used for counter signs and referral links)."""
    import io

    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=scale, border=2, dark="#182230", xmldecl=False)
    return buf.getvalue().decode()


def qr_svg_data_uri(uri: str) -> str:
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#182230")


def verify_user_code(user: User, code: str) -> bool:
    """Check a TOTP code for an enrolled user and consume its time step."""
    if not user.mfa_secret_encrypted:
        return False
    secret = decrypt_secret(user.mfa_secret_encrypted)
    if not secret:
        return False
    step = match_step(secret, code)
    if step is None or (user.mfa_last_step is not None and step <= user.mfa_last_step):
        return False
    user.mfa_last_step = step
    return True


def _hash_recovery(code: str) -> str:
    normalized = "".join(ch for ch in code.upper() if ch.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()


def generate_recovery_codes(user: User) -> list[str]:
    """Replace any existing recovery codes and return the new plain-text codes (shown once)."""
    MfaRecoveryCode.query.filter_by(user_id=user.id).delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(5).upper()  # 10 hex chars = 40 bits
        codes.append(f"{raw[:5]}-{raw[5:]}")
        db.session.add(MfaRecoveryCode(user_id=user.id, code_hash=_hash_recovery(raw)))
    return codes


def use_recovery_code(user: User, code: str) -> bool:
    record = MfaRecoveryCode.query.filter_by(
        user_id=user.id, code_hash=_hash_recovery(code or ""), used_at=None
    ).first()
    if not record:
        return False
    record.used_at = utcnow()
    return True


def remaining_recovery_codes(user: User) -> int:
    return MfaRecoveryCode.query.filter_by(user_id=user.id, used_at=None).count()


def disable(user: User) -> None:
    user.mfa_secret_encrypted = None
    user.mfa_enabled_at = None
    user.mfa_last_step = None
    MfaRecoveryCode.query.filter_by(user_id=user.id).delete()
