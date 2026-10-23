import re

from flask import current_app

from ..email import link, queue_email
from ..errors import Conflict, Forbidden, NotFound, ValidationError
from ..extensions import db
from ..models import (
    Business,
    BusinessInvitation,
    BusinessMembership,
    Location,
    LocationMembership,
    LoyaltyProgram,
    Reward,
    User,
    utcnow,
)
from ..security import hash_token, new_token
from . import audit


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "business"
    slug, n = base, 2
    while Business.query.filter_by(slug=slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def create_business(user: User, data: dict) -> Business:
    """Onboarding: business + owner membership + first location + program (+ optional first reward)."""
    business = Business(
        name=data["name"], slug=slugify(data["name"]), timezone=data.get("timezone") or "America/New_York"
    )
    from .. import billing

    billing.start_trial(business)
    db.session.add(business)
    db.session.flush()
    db.session.add(BusinessMembership(business_id=business.id, user_id=user.id, role="owner", all_locations=True))
    db.session.add(
        Location(business_id=business.id, name=data["location_name"], address=data.get("location_address") or "")
    )
    db.session.add(
        LoyaltyProgram(
            business_id=business.id,
            name=data.get("program_name") or f"{data['name']} Rewards",
            points_per_dollar=data.get("points_per_dollar") or 1,
            contact_email=user.email,
        )
    )
    if data.get("first_reward_name") and data.get("first_reward_points"):
        db.session.add(
            Reward(
                business_id=business.id,
                name=data["first_reward_name"],
                reward_type="custom",
                points_cost=data["first_reward_points"],
            )
        )
    db.session.flush()
    audit.record("business.created", business_id=business.id, target_type="business", target_id=business.id)
    return business


def set_location_access(membership: BusinessMembership, all_locations: bool, location_ids: list[int]):
    if membership.role == "owner":
        membership.all_locations = True
        membership.location_links = []
        return
    valid = {
        loc.id
        for loc in Location.query.filter(
            Location.business_id == membership.business_id, Location.id.in_(location_ids or [0])
        )
    }
    if set(location_ids) - valid:
        raise ValidationError("Unknown location", fields={"location_ids": "Contains an unknown location"})
    if not all_locations and not location_ids:
        raise ValidationError(
            "Assign at least one location or grant access to all locations", fields={"location_ids": "Required"}
        )
    membership.all_locations = all_locations
    membership.location_links = [] if all_locations else [LocationMembership(location_id=lid) for lid in sorted(valid)]


def invite(
    tenant, email: str, role: str, all_locations: bool, location_ids: list[int], inviter: User
) -> BusinessInvitation:
    if role not in ("manager", "staff"):
        raise ValidationError("Invitations can only grant manager or staff roles", fields={"role": "Invalid role"})
    existing_user = User.query.filter_by(email=email).first()
    if (
        existing_user
        and BusinessMembership.query.filter_by(business_id=tenant.business_id, user_id=existing_user.id).first()
    ):
        raise Conflict("This person is already a member of the team", code="already_member")
    if not all_locations:
        valid = {
            loc.id
            for loc in Location.query.filter(
                Location.business_id == tenant.business_id, Location.id.in_(location_ids or [0])
            )
        }
        if not location_ids or set(location_ids) - valid:
            raise ValidationError("Choose valid locations", fields={"location_ids": "Choose at least one location"})
    from .. import billing

    pending_same_email = BusinessInvitation.query.filter_by(
        business_id=tenant.business_id, email=email, accepted_at=None, revoked_at=None
    ).count()
    billing.check_limit(tenant.business, "members", adding=0 if pending_same_email else 1)
    # Revoke older pending invitations for the same email so only the newest link works.
    for old in BusinessInvitation.query.filter_by(
        business_id=tenant.business_id, email=email, accepted_at=None, revoked_at=None
    ):
        old.revoked_at = utcnow()
    token = new_token()
    invitation = BusinessInvitation(
        business_id=tenant.business_id,
        email=email,
        role=role,
        all_locations=all_locations,
        location_ids=location_ids if not all_locations else [],
        token_hash=hash_token(token),
        invited_by_id=inviter.id,
        expires_at=utcnow() + current_app.config["INVITATION_TTL"],
    )
    db.session.add(invitation)
    db.session.flush()
    queue_email(
        "invitation",
        email,
        f"You're invited to join {tenant.business.name} on {current_app.config['APP_NAME']}",
        f"{inviter.display_name} invited you to join {tenant.business.name} as {role}.\n\n"
        f"Accept the invitation (expires in 7 days, single use):\n{link('/invite/' + token)}\n",
        business_id=tenant.business_id,
    )
    audit.record(
        "member.invited", business_id=tenant.business_id, target_type="invitation", target_id=invitation.id, role=role
    )
    return invitation


def find_invitation(token: str) -> BusinessInvitation:
    invitation = BusinessInvitation.query.filter_by(token_hash=hash_token(token)).first()
    if not invitation:
        raise NotFound("This invitation link is not valid")
    if invitation.status == "accepted":
        raise Conflict("This invitation has already been used", code="invitation_used")
    if invitation.status == "revoked":
        raise Conflict("This invitation was revoked. Ask the owner to send a new one.", code="invitation_revoked")
    if invitation.status == "expired":
        raise Conflict("This invitation has expired. Ask the owner to send a new one.", code="invitation_expired")
    return invitation


def accept_invitation(invitation: BusinessInvitation, user: User) -> BusinessMembership:
    if user.email != invitation.email:
        raise Forbidden("This invitation was sent to a different email address")
    if BusinessMembership.query.filter_by(business_id=invitation.business_id, user_id=user.id).first():
        raise Conflict("You are already a member of this business", code="already_member")
    membership = BusinessMembership(
        business_id=invitation.business_id,
        user_id=user.id,
        role=invitation.role,
        all_locations=invitation.all_locations,
    )
    db.session.add(membership)
    db.session.flush()
    if not invitation.all_locations:
        for lid in invitation.location_ids:
            if Location.query.filter_by(id=lid, business_id=invitation.business_id).first():
                db.session.add(LocationMembership(membership_id=membership.id, location_id=lid))
    invitation.accepted_at = utcnow()
    audit.record(
        "member.joined",
        business_id=invitation.business_id,
        actor_id=user.id,
        target_type="membership",
        target_id=membership.id,
        role=invitation.role,
    )
    return membership


def get_membership(tenant, membership_id: int) -> BusinessMembership:
    membership = BusinessMembership.query.filter_by(id=membership_id, business_id=tenant.business_id).first()
    if not membership:
        raise NotFound("Team member not found")
    return membership


def update_membership(tenant, membership: BusinessMembership, data: dict) -> None:
    """Owner-only changes. Owners cannot be demoted or deactivated here, and nobody can edit themselves."""
    if membership.id == tenant.membership.id:
        raise Forbidden("You cannot change your own role, status or access")
    if membership.role == "owner":
        raise Forbidden("Owner accounts cannot be changed from the team screen")
    changes = {}
    if data.get("role") is not None:
        if data["role"] not in ("manager", "staff"):
            raise ValidationError("Role must be manager or staff", fields={"role": "Invalid"})
        if data["role"] != membership.role:
            changes["role"] = [membership.role, data["role"]]
            membership.role = data["role"]
    if data.get("status") is not None:
        if data["status"] not in ("active", "deactivated"):
            raise ValidationError("Invalid status", fields={"status": "Invalid"})
        if data["status"] != membership.status:
            if data["status"] == "active":
                from .. import billing

                billing.check_limit(tenant.business, "members")
            changes["status"] = [membership.status, data["status"]]
            membership.status = data["status"]
    if data.get("all_locations") is not None or data.get("location_ids") is not None:
        all_locations = data.get("all_locations") if data.get("all_locations") is not None else membership.all_locations
        set_location_access(membership, all_locations, data.get("location_ids") or [])
        changes["locations"] = "all" if all_locations else data.get("location_ids")
    if changes:
        audit.record(
            "member.updated",
            business_id=tenant.business_id,
            target_type="membership",
            target_id=membership.id,
            **changes,
        )
