"""Authentication, CSRF, tenant context and permission enforcement."""

import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import current_app, g, request

from .errors import Forbidden, NotFound, Unauthorized
from .extensions import db
from .models import Business, BusinessMembership, CustomerSession, Location, UserSession, utcnow

_hasher = PasswordHasher()
# Pre-computed hash so sign-in timing does not reveal whether an email exists.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")


def random_code(length: int = 8) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


# ------------------------------------------------------------------- permissions

ALL_PERMISSIONS = {
    "business.manage",
    "program.view",
    "program.manage",
    "locations.view",
    "locations.manage",
    "members.view",
    "members.manage",
    "customers.view",
    "customers.create",
    "customers.edit",
    "customers.privacy",
    "purchases.create",
    "ledger.adjust",
    "ledger.reverse",
    "rewards.view",
    "rewards.manage",
    "redemptions.issue",
    "redemptions.complete",
    "redemptions.cancel",
    "referrals.view",
    "referrals.manage",
    "analytics.view",
    "exports.run",
    "audit.view",
    "expiry.run",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": set(ALL_PERMISSIONS),
    "manager": {
        "program.view",
        "locations.view",
        "members.view",
        "customers.view",
        "customers.create",
        "customers.edit",
        "purchases.create",
        "ledger.adjust",
        "ledger.reverse",
        "rewards.view",
        "rewards.manage",
        "redemptions.issue",
        "redemptions.complete",
        "redemptions.cancel",
        "referrals.view",
        "referrals.manage",
        "analytics.view",
        "exports.run",
        "audit.view",
    },
    "staff": {
        "program.view",
        "locations.view",
        "customers.view",
        "customers.create",
        "purchases.create",
        "rewards.view",
        "redemptions.issue",
        "redemptions.complete",
        "referrals.view",
    },
}


@dataclass
class TenantContext:
    business: Business
    membership: BusinessMembership

    @property
    def business_id(self) -> int:
        return self.business.id

    @property
    def role(self) -> str:
        return self.membership.role

    @property
    def permissions(self) -> set[str]:
        return ROLE_PERMISSIONS[self.membership.role]

    def can(self, perm: str) -> bool:
        return perm in self.permissions

    @property
    def all_locations(self) -> bool:
        return self.membership.role == "owner" or self.membership.all_locations

    def allowed_location_ids(self) -> list[int] | None:
        """``None`` means unrestricted."""
        if self.all_locations:
            return None
        return self.membership.location_ids

    def require_location(self, location_id: int | None, required: bool = True) -> Location | None:
        if location_id is None:
            if required:
                from .errors import ValidationError

                raise ValidationError("Choose a location", fields={"location_id": "Required"})
            return None
        location = Location.query.filter_by(id=location_id, business_id=self.business_id).first()
        if not location or location.status != "active":
            raise NotFound("Location not found")
        allowed = self.allowed_location_ids()
        if allowed is not None and location.id not in allowed:
            raise Forbidden("You do not have access to this location")
        return location


# ---------------------------------------------------------------------- sessions


def _cookie_kwargs(max_age: int):
    return {
        "max_age": max_age,
        "httponly": True,
        "secure": current_app.config["COOKIE_SECURE"],
        "samesite": "Lax",
        "path": "/",
    }


def create_user_session(response, user, active_business_id=None) -> UserSession:
    token = new_token()
    lifetime = current_app.config["SESSION_LIFETIME"]
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_token(24),
        active_business_id=active_business_id,
        expires_at=utcnow() + lifetime,
    )
    db.session.add(session)
    db.session.flush()
    response.set_cookie(
        current_app.config["SESSION_COOKIE_NAME"], token, **_cookie_kwargs(int(lifetime.total_seconds()))
    )
    return session


def clear_cookie(response, name: str):
    response.delete_cookie(name, path="/", samesite="Lax", secure=current_app.config["COOKIE_SECURE"], httponly=True)


def load_user_session() -> UserSession | None:
    if "user_session" in g:
        return g.user_session
    token = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"])
    session = None
    if token:
        session = UserSession.query.filter_by(token_hash=hash_token(token)).first()
        if session and (session.revoked_at or session.expires_at < utcnow()):
            session = None
    g.user_session = session
    return session


def create_customer_session(response, customer) -> CustomerSession:
    token = new_token()
    lifetime = current_app.config["PORTAL_SESSION_LIFETIME"]
    session = CustomerSession(
        customer_id=customer.id,
        token_hash=hash_token(token),
        csrf_token=new_token(24),
        expires_at=utcnow() + lifetime,
    )
    db.session.add(session)
    db.session.flush()
    response.set_cookie(
        current_app.config["PORTAL_COOKIE_NAME"], token, **_cookie_kwargs(int(lifetime.total_seconds()))
    )
    return session


def load_customer_session() -> CustomerSession | None:
    token = request.cookies.get(current_app.config["PORTAL_COOKIE_NAME"])
    if not token:
        return None
    session = CustomerSession.query.filter_by(token_hash=hash_token(token)).first()
    if not session or session.revoked_at or session.expires_at < utcnow():
        return None
    if session.customer.status == "anonymized":
        return None
    return session


def check_csrf(expected: str):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise Forbidden("Invalid or missing CSRF token. Refresh the page and try again.")


# -------------------------------------------------------------------- decorators


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        session = load_user_session()
        if not session:
            raise Unauthorized()
        check_csrf(session.csrf_token)
        g.user = session.user
        return fn(*args, **kwargs)

    return wrapper


def current_tenant() -> TenantContext:
    """Resolve the business from the session's active business and verify active membership."""
    if "tenant" in g:
        return g.tenant
    session = load_user_session()
    if not session:
        raise Unauthorized()
    if not session.active_business_id:
        raise Forbidden("Select or create a business first")
    membership = BusinessMembership.query.filter_by(
        business_id=session.active_business_id, user_id=session.user_id, status="active"
    ).first()
    if not membership:
        raise Forbidden("You are not an active member of this business")
    g.tenant = TenantContext(business=membership.business, membership=membership)
    return g.tenant


def require(*perms: str):
    """Require login + active business membership + every listed permission."""

    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            tenant = current_tenant()
            for perm in perms:
                if not tenant.can(perm):
                    raise Forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def portal_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        session = load_customer_session()
        if not session:
            raise Unauthorized("Your access link has expired. Request a new one.")
        check_csrf(session.csrf_token)
        g.portal_session = session
        g.customer = session.customer
        return fn(*args, **kwargs)

    return wrapper
