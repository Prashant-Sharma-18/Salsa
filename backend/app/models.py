"""Database models.

Conventions:
- Every business-owned row carries ``business_id``; queries must scope by the
  business derived from the authenticated membership (see ``security.py``).
- Timestamps are naive UTC datetimes; the API serialises them with a ``Z`` suffix.
- Points are integers. Money is stored as integer cents.
- ``PointLedgerEntry`` rows are append-only (enforced by ORM event hooks below).
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, event, false

from .extensions import db

_clock_override: ContextVar[datetime | None] = ContextVar("clock_override", default=None)


def utcnow() -> datetime:
    override = _clock_override.get()
    if override is not None:
        return override
    return datetime.now(timezone.utc).replace(tzinfo=None)


@contextmanager
def frozen_clock(at: datetime):
    """Pin ``utcnow()`` (used for seeding history and in tests). Never used by request handling."""
    token = _clock_override.set(at)
    try:
        yield
    finally:
        _clock_override.reset(token)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


# --------------------------------------------------------------------------- users


class User(TimestampMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    email_verified_at = db.Column(db.DateTime)
    is_platform_admin = db.Column(db.Boolean, nullable=False, default=False)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    timezone = db.Column(db.String(64), nullable=False, default="America/New_York")

    # Two-factor authentication (TOTP). The secret is encrypted at rest (see mfa.py).
    mfa_secret_encrypted = db.Column(db.String(255))
    mfa_enabled_at = db.Column(db.DateTime)
    mfa_last_step = db.Column(db.BigInteger)  # last accepted TOTP time step, prevents code replay

    # Account lockout after repeated failed sign-ins.
    failed_login_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    locked_until = db.Column(db.DateTime)

    @property
    def mfa_enabled(self) -> bool:
        return self.mfa_enabled_at is not None

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "email_verified": self.email_verified_at is not None,
            "is_platform_admin": self.is_platform_admin,
            "timezone": self.timezone,
            "mfa_enabled": self.mfa_enabled,
        }


class MfaRecoveryCode(TimestampMixin, db.Model):
    """Single-use backup codes for when the authenticator app is unavailable. Only hashes are stored."""

    __tablename__ = "mfa_recovery_codes"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False, unique=True)
    used_at = db.Column(db.DateTime)


class UserSession(TimestampMixin, db.Model):
    __tablename__ = "user_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    csrf_token = db.Column(db.String(64), nullable=False)
    active_business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="SET NULL"))
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)

    user = db.relationship("User")


class AuthToken(TimestampMixin, db.Model):
    """Single-use, expiring tokens for email verification and password reset. Only hashes are stored."""

    __tablename__ = "auth_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = db.Column(db.String(32), nullable=False)  # verify_email | password_reset | mfa_challenge
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")


# ---------------------------------------------------------------------- businesses


class Business(TimestampMixin, db.Model):
    __tablename__ = "businesses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(80), nullable=False, unique=True)
    timezone = db.Column(db.String(64), nullable=False, default="America/New_York")
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    # Billing (see billing.py). plan: trial | starter | growth | pro
    plan = db.Column(db.String(32), nullable=False, default="trial")
    plan_status = db.Column(db.String(16), nullable=False, default="trialing", server_default="trialing")
    trial_ends_at = db.Column(db.DateTime)
    current_period_end = db.Column(db.DateTime)
    stripe_customer_id = db.Column(db.String(64), unique=True)
    stripe_subscription_id = db.Column(db.String(64), unique=True)
    # When true, owners and managers must have two-factor authentication to use the business.
    require_mfa = db.Column(db.Boolean, nullable=False, default=False, server_default=false())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "timezone": self.timezone,
            "is_demo": self.is_demo,
            "plan": self.plan,
            "require_mfa": self.require_mfa,
            "created_at": iso(self.created_at),
        }


ROLES = ("owner", "manager", "staff")


class BusinessMembership(TimestampMixin, db.Model):
    __tablename__ = "business_memberships"
    __table_args__ = (
        UniqueConstraint("business_id", "user_id"),
        CheckConstraint("role in ('owner','manager','staff')", name="role_valid"),
    )
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="active")  # active | deactivated
    all_locations = db.Column(db.Boolean, nullable=False, default=True)

    user = db.relationship("User")
    business = db.relationship("Business")
    location_links = db.relationship("LocationMembership", cascade="all, delete-orphan", backref="membership")

    @property
    def location_ids(self) -> list[int]:
        return sorted(link.location_id for link in self.location_links)

    def to_dict(self):
        return {
            "id": self.id,
            "user": {"id": self.user.id, "display_name": self.user.display_name, "email": self.user.email},
            "role": self.role,
            "status": self.status,
            "all_locations": self.role == "owner" or self.all_locations,
            "location_ids": self.location_ids,
            "created_at": iso(self.created_at),
        }


class BusinessInvitation(TimestampMixin, db.Model):
    __tablename__ = "business_invitations"
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    email = db.Column(db.String(254), nullable=False)
    role = db.Column(db.String(16), nullable=False)
    all_locations = db.Column(db.Boolean, nullable=False, default=True)
    location_ids = db.Column(db.JSON, nullable=False, default=list)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    expires_at = db.Column(db.DateTime, nullable=False)
    accepted_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)

    business = db.relationship("Business")

    @property
    def status(self) -> str:
        if self.accepted_at:
            return "accepted"
        if self.revoked_at:
            return "revoked"
        if self.expires_at < utcnow():
            return "expired"
        return "pending"

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "role": self.role,
            "status": self.status,
            "expires_at": iso(self.expires_at),
            "created_at": iso(self.created_at),
        }


class Location(TimestampMixin, db.Model):
    __tablename__ = "locations"
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default="active")  # active | archived

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "status": self.status,
            "created_at": iso(self.created_at),
        }


class LocationMembership(db.Model):
    __tablename__ = "location_memberships"
    __table_args__ = (UniqueConstraint("membership_id", "location_id"),)
    id = db.Column(db.Integer, primary_key=True)
    membership_id = db.Column(
        db.Integer, db.ForeignKey("business_memberships.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False)


# ------------------------------------------------------------------------- program


class LoyaltyProgram(TimestampMixin, db.Model):
    __tablename__ = "loyalty_programs"
    __table_args__ = (
        CheckConstraint("points_per_dollar >= 0", name="ppd_nonneg"),
        CheckConstraint("min_spend_cents >= 0", name="min_spend_nonneg"),
    )
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default="active")  # draft | active | paused
    brand_color = db.Column(db.String(7), nullable=False, default="#1769aa")
    logo_url = db.Column(db.String(500), nullable=False, default="")
    contact_email = db.Column(db.String(254), nullable=False, default="")
    contact_phone = db.Column(db.String(32), nullable=False, default="")

    earning_enabled = db.Column(db.Boolean, nullable=False, default=True)
    points_per_dollar = db.Column(db.Integer, nullable=False, default=1)
    min_spend_cents = db.Column(db.Integer, nullable=False, default=0)

    redemption_enabled = db.Column(db.Boolean, nullable=False, default=True)

    referrals_enabled = db.Column(db.Boolean, nullable=False, default=True)
    referrer_reward_points = db.Column(db.Integer, nullable=False, default=100)
    referee_reward_points = db.Column(db.Integer, nullable=False, default=50)
    referral_min_spend_cents = db.Column(db.Integer, nullable=False, default=0)

    # Inactivity expiry: when set, the full balance expires after N days without earning/redeeming activity.
    points_expiry_days = db.Column(db.Integer)

    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def rules_summary(self) -> list[str]:
        lines = []
        if self.earning_enabled:
            line = f"Earn {self.points_per_dollar} point{'s' if self.points_per_dollar != 1 else ''} for every $1 spent"
            if self.min_spend_cents:
                line += f" on purchases of ${self.min_spend_cents / 100:,.2f} or more"
            lines.append(line + ". Partial dollars are rounded down.")
        else:
            lines.append("Earning points is currently paused.")
        if self.redemption_enabled:
            lines.append("Redeem points for rewards from the catalog. Show your redemption code to staff to use it.")
        else:
            lines.append("Reward redemption is currently paused.")
        if self.referrals_enabled:
            friend = f" and they get {self.referee_reward_points} points" if self.referee_reward_points else ""
            spend = f" of at least ${self.referral_min_spend_cents / 100:,.2f}" if self.referral_min_spend_cents else ""
            lines.append(
                f"Refer a friend: you get {self.referrer_reward_points} points{friend} after their first purchase{spend}."
            )
        if self.points_expiry_days:
            lines.append(
                f"Points expire if your account has no earning or redemption activity for {self.points_expiry_days} days."
            )
        else:
            lines.append("Points do not expire.")
        return lines

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "brand_color": self.brand_color,
            "logo_url": self.logo_url,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "earning_enabled": self.earning_enabled,
            "points_per_dollar": self.points_per_dollar,
            "min_spend_cents": self.min_spend_cents,
            "redemption_enabled": self.redemption_enabled,
            "referrals_enabled": self.referrals_enabled,
            "referrer_reward_points": self.referrer_reward_points,
            "referee_reward_points": self.referee_reward_points,
            "referral_min_spend_cents": self.referral_min_spend_cents,
            "points_expiry_days": self.points_expiry_days,
            "rules": self.rules_summary(),
            "updated_at": iso(self.updated_at),
        }


# ----------------------------------------------------------------------- customers


class Customer(TimestampMixin, db.Model):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("business_id", "email_normalized"),
        CheckConstraint("points_balance >= 0", name="balance_nonneg"),
        Index("ix_customers_business_name", "business_id", "display_name"),
    )
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254))
    email_normalized = db.Column(db.String(254))
    phone = db.Column(db.String(32))
    status = db.Column(db.String(16), nullable=False, default="active")  # active | inactive | anonymized
    enrolled_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    enrolled_location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    referral_code = db.Column(db.String(16), nullable=False, unique=True)
    points_balance = db.Column(db.Integer, nullable=False, default=0)
    last_activity_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    marketing_opt_in = db.Column(db.Boolean, nullable=False, default=False)
    anonymized_at = db.Column(db.DateTime)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self, detail: bool = False):
        data = {
            "id": self.id,
            "display_name": self.display_name,
            "email": self.email,
            "phone": self.phone,
            "status": self.status,
            "enrolled_at": iso(self.enrolled_at),
            "points_balance": self.points_balance,
            "referral_code": self.referral_code,
            "marketing_opt_in": self.marketing_opt_in,
            "is_demo": self.is_demo,
        }
        if detail:
            data["enrolled_location_id"] = self.enrolled_location_id
            data["last_activity_at"] = iso(self.last_activity_at)
        return data


class ConsentRecord(TimestampMixin, db.Model):
    """Append-only history of marketing consent changes."""

    __tablename__ = "consent_records"
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    consent_type = db.Column(db.String(32), nullable=False, default="marketing_email")
    granted = db.Column(db.Boolean, nullable=False)
    source = db.Column(db.String(32), nullable=False)  # staff | customer_portal | join_page | import
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    def to_dict(self):
        return {
            "id": self.id,
            "consent_type": self.consent_type,
            "granted": self.granted,
            "source": self.source,
            "created_at": iso(self.created_at),
        }


class CustomerAccessToken(TimestampMixin, db.Model):
    """Single-use magic-link token that is exchanged for a portal session."""

    __tablename__ = "customer_access_tokens"
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)


class CustomerSession(TimestampMixin, db.Model):
    __tablename__ = "customer_sessions"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    csrf_token = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)

    customer = db.relationship("Customer")


# ------------------------------------------------------------------ points / money


class Purchase(TimestampMixin, db.Model):
    __tablename__ = "purchases"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key"),
        UniqueConstraint("business_id", "external_ref"),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
    )
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    amount_cents = db.Column(db.Integer, nullable=False)
    eligible_cents = db.Column(db.Integer, nullable=False)
    external_ref = db.Column(db.String(64))  # receipt / order number, unique per business when provided
    idempotency_key = db.Column(db.String(96), nullable=False)
    points_awarded = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(16), nullable=False, default="recorded")  # recorded | reversed
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "location_id": self.location_id,
            "amount_cents": self.amount_cents,
            "eligible_cents": self.eligible_cents,
            "external_ref": self.external_ref,
            "points_awarded": self.points_awarded,
            "status": self.status,
            "created_at": iso(self.created_at),
        }


LEDGER_TYPES = ("award", "redemption", "reversal", "adjustment", "expiration", "referral_bonus")


class PointLedgerEntry(TimestampMixin, db.Model):
    __tablename__ = "point_ledger_entries"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key"),
        Index("ix_ledger_business_created", "business_id", "created_at"),
        Index("ix_ledger_customer_created", "customer_id", "created_at"),
    )
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    entry_type = db.Column(db.String(24), nullable=False)
    points = db.Column(db.Integer, nullable=False)  # signed
    balance_after = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=False, default="")
    source_type = db.Column(db.String(24))  # purchase | redemption | referral | ledger | manual | expiry
    source_id = db.Column(db.Integer)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    idempotency_key = db.Column(db.String(96))
    reverses_entry_id = db.Column(db.Integer, db.ForeignKey("point_ledger_entries.id"), unique=True)

    actor = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "location_id": self.location_id,
            "entry_type": self.entry_type,
            "points": self.points,
            "balance_after": self.balance_after,
            "reason": self.reason,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "actor": self.actor.display_name if self.actor else None,
            "reverses_entry_id": self.reverses_entry_id,
            "created_at": iso(self.created_at),
        }


@event.listens_for(PointLedgerEntry, "before_update")
def _ledger_no_update(mapper, connection, target):
    raise RuntimeError("Ledger entries are append-only; create a reversal entry instead")


@event.listens_for(PointLedgerEntry, "before_delete")
def _ledger_no_delete(mapper, connection, target):
    raise RuntimeError("Ledger entries are append-only; create a reversal entry instead")


# ------------------------------------------------------------------------ rewards

REWARD_TYPES = ("fixed_discount", "free_item", "custom")


class Reward(TimestampMixin, db.Model):
    __tablename__ = "rewards"
    __table_args__ = (
        CheckConstraint("points_cost > 0", name="cost_positive"),
        CheckConstraint("stock_limit IS NULL OR stock_redeemed <= stock_limit", name="stock_within_limit"),
    )
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    reward_type = db.Column(db.String(24), nullable=False)
    value_cents = db.Column(db.Integer)
    points_cost = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="active")  # active | archived
    stock_limit = db.Column(db.Integer)
    stock_redeemed = db.Column(db.Integer, nullable=False, default=0)  # counts issued (non-cancelled) codes
    terms = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "reward_type": self.reward_type,
            "value_cents": self.value_cents,
            "points_cost": self.points_cost,
            "status": self.status,
            "stock_limit": self.stock_limit,
            "stock_remaining": None if self.stock_limit is None else self.stock_limit - self.stock_redeemed,
            "terms": self.terms,
            "updated_at": iso(self.updated_at),
        }


REDEMPTION_STATUSES = ("issued", "redeemed", "expired", "cancelled")


class Redemption(TimestampMixin, db.Model):
    __tablename__ = "redemptions"
    __table_args__ = (UniqueConstraint("business_id", "idempotency_key"),)
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    reward_id = db.Column(db.Integer, db.ForeignKey("rewards.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    code = db.Column(db.String(16), nullable=False, unique=True)
    points_cost = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="issued")
    idempotency_key = db.Column(db.String(96), nullable=False)
    ledger_entry_id = db.Column(db.Integer, db.ForeignKey("point_ledger_entries.id"))
    issued_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    issued_via = db.Column(db.String(16), nullable=False, default="staff")  # staff | customer_portal
    completed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    completed_location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    completed_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(255))
    expires_at = db.Column(db.DateTime, nullable=False)

    reward = db.relationship("Reward")
    customer = db.relationship("Customer")

    def to_dict(self, include_customer: bool = True):
        data = {
            "id": self.id,
            "code": self.code,
            "status": self.status,
            "points_cost": self.points_cost,
            "reward": {"id": self.reward.id, "name": self.reward.name, "terms": self.reward.terms},
            "location_id": self.location_id,
            "issued_via": self.issued_via,
            "completed_at": iso(self.completed_at),
            "completed_location_id": self.completed_location_id,
            "cancelled_at": iso(self.cancelled_at),
            "expires_at": iso(self.expires_at),
            "created_at": iso(self.created_at),
        }
        if include_customer:
            data["customer"] = {
                "id": self.customer.id,
                "display_name": self.customer.display_name,
                "points_balance": self.customer.points_balance,
            }
        return data


# ----------------------------------------------------------------------- referrals

REFERRAL_STATUSES = ("created", "clicked", "signed_up", "qualified", "rewarded", "rejected")


class Referral(TimestampMixin, db.Model):
    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("referred_customer_id"),)
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    referrer_customer_id = db.Column(
        db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referred_customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"))
    referred_email_normalized = db.Column(db.String(254))
    status = db.Column(db.String(16), nullable=False, default="created")
    source = db.Column(db.String(32), nullable=False, default="staff")  # staff | link | portal
    rejection_reason = db.Column(db.String(255))
    signed_up_at = db.Column(db.DateTime)
    qualified_at = db.Column(db.DateTime)
    rewarded_at = db.Column(db.DateTime)
    qualifying_purchase_id = db.Column(db.Integer, db.ForeignKey("purchases.id", ondelete="SET NULL"))

    referrer = db.relationship("Customer", foreign_keys=[referrer_customer_id])
    referred = db.relationship("Customer", foreign_keys=[referred_customer_id])

    def to_dict(self):
        return {
            "id": self.id,
            "referrer": {"id": self.referrer.id, "display_name": self.referrer.display_name},
            "referred": (
                {"id": self.referred.id, "display_name": self.referred.display_name} if self.referred else None
            ),
            "status": self.status,
            "source": self.source,
            "rejection_reason": self.rejection_reason,
            "signed_up_at": iso(self.signed_up_at),
            "qualified_at": iso(self.qualified_at),
            "rewarded_at": iso(self.rewarded_at),
            "created_at": iso(self.created_at),
        }


# ----------------------------------------------------------------------- billing


class BillingEvent(db.Model):
    """Processed payment-provider webhook events, for idempotency."""

    __tablename__ = "billing_events"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(128), nullable=False, unique=True)
    event_type = db.Column(db.String(64), nullable=False)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="SET NULL"))
    received_at = db.Column(db.DateTime, nullable=False, default=utcnow)


# ----------------------------------------------------------------- audit / outbox


class AuditLog(TimestampMixin, db.Model):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_business_created", "business_id", "created_at"),)
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"))
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(64), nullable=False)
    target_type = db.Column(db.String(32))
    target_id = db.Column(db.Integer)
    details = db.Column(db.JSON, nullable=False, default=dict)

    actor = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "action": self.action,
            "actor": self.actor.display_name if self.actor else "System",
            "target_type": self.target_type,
            "target_id": self.target_id,
            "details": self.details,
            "created_at": iso(self.created_at),
        }


class NotificationOutbox(TimestampMixin, db.Model):
    __tablename__ = "notification_outbox"
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"))
    kind = db.Column(db.String(32), nullable=False)
    recipient = db.Column(db.String(254), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    dedupe_key = db.Column(db.String(128), unique=True)
    status = db.Column(db.String(16), nullable=False, default="pending")  # pending | sending | sent | failed
    attempts = db.Column(db.Integer, nullable=False, default=0)
    claimed_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(255))
