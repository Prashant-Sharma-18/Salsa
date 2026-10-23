from flask import Blueprint, g, jsonify, request

from .. import billing
from ..errors import Conflict, Forbidden, NotFound
from ..extensions import db, limiter
from ..models import AuditLog, BusinessInvitation, BusinessMembership, Location, LoyaltyProgram
from ..security import current_tenant, load_user_session, login_required, require
from ..services import audit, businesses, ledger, redemptions
from ..validation import Fields, body, paginate
from .auth import session_payload

bp = Blueprint("business", __name__)


# -------------------------------------------------------------------- businesses


@bp.post("/businesses")
@login_required
@limiter.limit("10 per hour")
def create_business():
    f = Fields(body())
    f.string("name", max_len=120, min_len=2)
    f.string("timezone", required=False, max_len=64)
    f.string("location_name", max_len=120)
    f.string("location_address", required=False, max_len=255, default="")
    f.string("program_name", required=False, max_len=120)
    f.integer("points_per_dollar", required=False, min_value=1, max_value=100, default=1)
    f.string("first_reward_name", required=False, max_len=120)
    f.integer("first_reward_points", required=False, min_value=1, max_value=1_000_000)
    data = f.check()
    business = businesses.create_business(g.user, data)
    session = load_user_session()
    session.active_business_id = business.id
    db.session.commit()
    return jsonify({"data": session_payload(session)}), 201


@bp.get("/businesses/current")
@require()
def get_business():
    return jsonify({"data": current_tenant().business.to_dict()})


@bp.patch("/businesses/current")
@require("business.manage", billing_exempt=True)
def update_business():
    tenant = current_tenant()
    f = Fields(body())
    f.string("name", required=False, max_len=120, min_len=2)
    f.string("timezone", required=False, max_len=64)
    f.boolean("require_mfa")
    data = f.check()
    for key in ("name", "timezone"):
        if data.get(key):
            setattr(tenant.business, key, data[key])
    if data.get("require_mfa") is not None and data["require_mfa"] != tenant.business.require_mfa:
        if data["require_mfa"] and not g.user.mfa_enabled:
            raise Conflict("Turn on two-factor authentication for your own account first")
        tenant.business.require_mfa = data["require_mfa"]
        audit.record(
            "business.require_mfa_changed",
            business_id=tenant.business_id,
            target_type="business",
            target_id=tenant.business_id,
            require_mfa=data["require_mfa"],
        )
    audit.record(
        "business.updated", business_id=tenant.business_id, target_type="business", target_id=tenant.business_id
    )
    db.session.commit()
    return jsonify({"data": tenant.business.to_dict()})


# ----------------------------------------------------------------------- members


@bp.get("/members")
@require("members.view")
def list_members():
    tenant = current_tenant()
    members = BusinessMembership.query.filter_by(business_id=tenant.business_id).order_by(BusinessMembership.id).all()
    invitations = []
    if tenant.can("members.manage"):
        invitations = [
            i.to_dict()
            for i in BusinessInvitation.query.filter_by(business_id=tenant.business_id, accepted_at=None)
            .order_by(BusinessInvitation.created_at.desc())
            .limit(50)
        ]
    return jsonify({"data": {"members": [m.to_dict() for m in members], "invitations": invitations}})


@bp.post("/members/invitations")
@require("members.manage")
@limiter.limit("20 per hour")
def invite_member():
    tenant = current_tenant()
    if not g.user.email_verified_at:
        raise Forbidden("Verify your email address before inviting team members")
    f = Fields(body())
    f.email("email")
    f.choice("role", ("manager", "staff"))
    f.boolean("all_locations", default=True)
    f.int_list("location_ids")
    data = f.check()
    invitation = businesses.invite(
        tenant, data["email"], data["role"], data["all_locations"], data["location_ids"], g.user
    )
    db.session.commit()
    return jsonify({"data": invitation.to_dict()}), 201


@bp.delete("/members/invitations/<int:invitation_id>")
@require("members.manage", billing_exempt=True)
def revoke_invitation(invitation_id):
    tenant = current_tenant()
    invitation = BusinessInvitation.query.filter_by(id=invitation_id, business_id=tenant.business_id).first()
    if not invitation:
        raise NotFound("Invitation not found")
    if invitation.status != "pending":
        raise Conflict(f"This invitation is already {invitation.status}")
    from ..models import utcnow

    invitation.revoked_at = utcnow()
    audit.record(
        "member.invitation_revoked", business_id=tenant.business_id, target_type="invitation", target_id=invitation.id
    )
    db.session.commit()
    return jsonify({"data": invitation.to_dict()})


@bp.patch("/members/<int:membership_id>")
@require("members.manage", billing_exempt=True)
def update_member(membership_id):
    tenant = current_tenant()
    membership = businesses.get_membership(tenant, membership_id)
    f = Fields(body())
    f.choice("role", ("manager", "staff"), required=False)
    f.choice("status", ("active", "deactivated"), required=False)
    f.boolean("all_locations")
    if f.present("location_ids"):
        f.int_list("location_ids")
    data = f.check()
    businesses.update_membership(tenant, membership, data)
    db.session.commit()
    return jsonify({"data": membership.to_dict()})


# --------------------------------------------------------------------- locations


@bp.get("/locations")
@require("locations.view")
def list_locations():
    tenant = current_tenant()
    allowed = tenant.allowed_location_ids()
    locations = Location.query.filter_by(business_id=tenant.business_id).order_by(Location.name).all()
    return jsonify(
        {"data": [dict(loc.to_dict(), accessible=allowed is None or loc.id in allowed) for loc in locations]}
    )


@bp.post("/locations")
@require("locations.manage")
def create_location():
    tenant = current_tenant()
    f = Fields(body())
    f.string("name", max_len=120)
    f.string("address", required=False, max_len=255, default="")
    data = f.check()
    billing.check_limit(tenant.business, "locations")
    location = Location(business_id=tenant.business_id, name=data["name"], address=data["address"] or "")
    db.session.add(location)
    db.session.flush()
    audit.record("location.created", business_id=tenant.business_id, target_type="location", target_id=location.id)
    db.session.commit()
    return jsonify({"data": location.to_dict()}), 201


@bp.patch("/locations/<int:location_id>")
@require("locations.manage", billing_exempt=True)
def update_location(location_id):
    tenant = current_tenant()
    location = Location.query.filter_by(id=location_id, business_id=tenant.business_id).first()
    if not location:
        raise NotFound("Location not found")
    f = Fields(body())
    f.string("name", required=False, max_len=120)
    f.string("address", required=False, max_len=255)
    f.choice("status", ("active", "archived"), required=False)
    data = f.check()
    if data.get("status") == "archived" and location.status != "archived":
        active = Location.query.filter_by(business_id=tenant.business_id, status="active").count()
        if active <= 1:
            raise Conflict("A business needs at least one active location")
    if data.get("status") == "active" and location.status != "active":
        billing.check_limit(tenant.business, "locations")
    for key in ("name", "address", "status"):
        if data.get(key) is not None:
            setattr(location, key, data[key])
    audit.record("location.updated", business_id=tenant.business_id, target_type="location", target_id=location.id)
    db.session.commit()
    return jsonify({"data": location.to_dict()})


# ----------------------------------------------------------------------- program


@bp.get("/programs/current")
@require("program.view")
def get_program():
    program = LoyaltyProgram.query.filter_by(business_id=current_tenant().business_id).one()
    return jsonify({"data": program.to_dict()})


@bp.patch("/programs/current")
@require("program.manage", billing_exempt=True)
def update_program():
    tenant = current_tenant()
    program = LoyaltyProgram.query.filter_by(business_id=tenant.business_id).one()
    f = Fields(body())
    f.string("name", required=False, max_len=120)
    f.string("description", required=False, max_len=2000, min_len=0)
    f.choice("status", ("draft", "active", "paused"), required=False)
    f.color("brand_color")
    f.url("logo_url")
    if f.data.get("contact_email"):
        f.email("contact_email", required=False)
    elif f.present("contact_email"):
        f.out["contact_email"] = None
    f.string("contact_phone", required=False, max_len=32)
    f.boolean("earning_enabled")
    f.integer("points_per_dollar", required=False, min_value=0, max_value=100)
    f.money("min_spend", required=False, allow_zero=True)
    f.boolean("redemption_enabled")
    f.boolean("referrals_enabled")
    f.integer("referrer_reward_points", required=False, min_value=0, max_value=100_000)
    f.integer("referee_reward_points", required=False, min_value=0, max_value=100_000)
    f.money("referral_min_spend", required=False, allow_zero=True)
    if f.present("points_expiry_days"):
        f.integer("points_expiry_days", required=False, min_value=30, max_value=3650)
    # PATCH semantics: only fields present in the request are changed.
    data = {k: v for k, v in f.check().items() if f.present(k)}

    mapping = {"min_spend": "min_spend_cents", "referral_min_spend": "referral_min_spend_cents"}
    clearable_text = {"description", "logo_url", "contact_email", "contact_phone"}
    changed = {}
    for key, value in data.items():
        if value is None:
            if key in clearable_text:
                value = ""
            elif key in ("min_spend", "referral_min_spend"):
                value = 0
            elif key != "points_expiry_days":
                continue
        attr = mapping.get(key, key)
        if getattr(program, attr) != value:
            changed[attr] = value
            setattr(program, attr, value)
    if changed:
        audit.record(
            "program.updated",
            business_id=tenant.business_id,
            target_type="program",
            target_id=program.id,
            changes=changed,
        )
    db.session.commit()
    return jsonify({"data": program.to_dict()})


@bp.post("/programs/current/run-expiry")
@require("expiry.run")
def run_expiry():
    tenant = current_tenant()
    expired_balances = ledger.process_expirations(tenant.business_id, actor_id=g.user.id)
    expired_codes = redemptions.expire_stale(tenant.business_id)
    db.session.commit()
    return jsonify({"data": {"expired_balances": expired_balances, "expired_codes": expired_codes}})


# ------------------------------------------------------------------------- audit


@bp.get("/audit-logs")
@require("audit.view")
def list_audit_logs():
    tenant = current_tenant()
    query = AuditLog.query.filter_by(business_id=tenant.business_id)
    action = request.args.get("action")
    if action:
        query = query.filter(AuditLog.action.like(f"{action}%"))
    return jsonify(paginate(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()), lambda a: a.to_dict()))
