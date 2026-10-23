from flask import Blueprint, current_app, g, jsonify, make_response

from ..email import link, queue_email
from ..errors import ApiError, Forbidden, NotFound, Unauthorized, ValidationError
from ..extensions import db, limiter
from ..models import AuthToken, Business, BusinessMembership, User, UserSession, utcnow
from ..security import (
    ROLE_PERMISSIONS,
    check_csrf,
    clear_cookie,
    create_user_session,
    hash_password,
    hash_token,
    load_user_session,
    login_required,
    new_token,
    verify_password,
)
from ..services import audit, businesses
from ..validation import Fields, body

bp = Blueprint("auth", __name__, url_prefix="/auth")

AUTH_LIMIT = "10 per minute;50 per hour"


def _memberships(user: User):
    return (
        BusinessMembership.query.filter_by(user_id=user.id, status="active")
        .join(Business)
        .order_by(Business.name)
        .all()
    )


def session_payload(session: UserSession) -> dict:
    user = session.user
    memberships = _memberships(user)
    active = next((m for m in memberships if m.business_id == session.active_business_id), None)
    if not active and memberships:
        active = memberships[0]
        session.active_business_id = active.business_id
        db.session.commit()
    return {
        "user": user.to_dict(),
        "csrf_token": session.csrf_token,
        "businesses": [{"id": m.business.id, "name": m.business.name, "role": m.role} for m in memberships],
        "active_business": active.business.to_dict() if active else None,
        "role": active.role if active else None,
        "permissions": sorted(ROLE_PERMISSIONS[active.role]) if active else [],
        "location_access": (
            {"all": active.role == "owner" or active.all_locations, "location_ids": active.location_ids}
            if active
            else None
        ),
    }


def _send_verification(user: User):
    token = new_token()
    db.session.add(
        AuthToken(
            user_id=user.id,
            purpose="verify_email",
            token_hash=hash_token(token),
            expires_at=utcnow() + current_app.config["EMAIL_VERIFY_TTL"],
        )
    )
    queue_email(
        "verify_email",
        user.email,
        f"Verify your {current_app.config['APP_NAME']} email",
        f"Confirm your email address:\n{link('/verify-email?token=' + token)}\n\nThis link expires in 48 hours.",
    )


def _consume_token(token: str, purpose: str) -> AuthToken:
    record = AuthToken.query.filter_by(token_hash=hash_token(token or ""), purpose=purpose).first()
    if not record or record.used_at or record.expires_at < utcnow():
        raise ApiError("This link is invalid or has expired. Request a new one.", code="invalid_token")
    record.used_at = utcnow()
    return record


@bp.get("/me")
def me():
    session = load_user_session()
    if not session:
        return jsonify({"data": None})
    return jsonify({"data": session_payload(session)})


@bp.post("/signup")
@limiter.limit(AUTH_LIMIT)
def signup():
    f = Fields(body())
    f.string("display_name", max_len=120)
    f.email("email")
    f.password()
    data = f.check()
    if User.query.filter_by(email=data["email"]).first():
        raise ApiError("An account with this email already exists. Sign in instead.", code="email_taken", status=409)
    user = User(email=data["email"], display_name=data["display_name"], password_hash=hash_password(data["password"]))
    db.session.add(user)
    db.session.flush()
    _send_verification(user)
    response = make_response()
    session = create_user_session(response, user)
    audit.record("user.signed_up", actor_id=user.id, target_type="user", target_id=user.id)
    db.session.commit()
    response.set_data(jsonify({"data": session_payload(session)}).get_data())
    response.status_code = 201
    response.mimetype = "application/json"
    return response


@bp.post("/signin")
@limiter.limit(AUTH_LIMIT)
def signin():
    f = Fields(body())
    f.email("email")
    f.string("password", max_len=128, strip=False)
    data = f.check()
    user = User.query.filter_by(email=data["email"]).first()
    if not verify_password(user.password_hash if user else None, data["password"]):
        raise ApiError("Incorrect email or password", code="invalid_credentials", status=401)
    if user.is_demo and not current_app.config["DEMO_MODE"]:
        raise ApiError("Demo accounts are disabled in this environment", code="demo_disabled", status=403)
    response = make_response()
    session = create_user_session(response, user)
    db.session.commit()
    response.set_data(jsonify({"data": session_payload(session)}).get_data())
    response.mimetype = "application/json"
    return response


@bp.post("/demo-login")
@limiter.limit(AUTH_LIMIT)
def demo_login():
    """Local demo only: sign in as a seeded demo user without typing a password."""
    if not current_app.config["DEMO_MODE"] or current_app.config["APP_ENV"] == "production":
        raise NotFound()
    f = Fields(body())
    role = f.choice("role", ("owner", "manager", "staff"))
    f.check()
    business = Business.query.filter_by(is_demo=True).first()
    if not business:
        raise ApiError("Demo data has not been seeded. Run: flask seed-demo", code="demo_not_seeded", status=409)
    membership = (
        BusinessMembership.query.join(User)
        .filter(BusinessMembership.business_id == business.id, BusinessMembership.role == role, User.is_demo.is_(True))
        .first()
    )
    if not membership:
        raise NotFound("Demo user not found")
    response = make_response()
    session = create_user_session(response, membership.user, active_business_id=business.id)
    db.session.commit()
    response.set_data(jsonify({"data": session_payload(session)}).get_data())
    response.mimetype = "application/json"
    return response


@bp.post("/signout")
@login_required
def signout():
    session = load_user_session()
    session.revoked_at = utcnow()
    db.session.commit()
    response = jsonify({"data": {"signed_out": True}})
    clear_cookie(response, current_app.config["SESSION_COOKIE_NAME"])
    return response


@bp.post("/switch-business")
@login_required
def switch_business():
    f = Fields(body())
    business_id = f.integer("business_id")
    f.check()
    membership = BusinessMembership.query.filter_by(business_id=business_id, user_id=g.user.id, status="active").first()
    if not membership:
        raise Forbidden("You are not a member of that business")
    session = load_user_session()
    session.active_business_id = business_id
    db.session.commit()
    return jsonify({"data": session_payload(session)})


@bp.post("/verify-email")
@limiter.limit(AUTH_LIMIT)
def verify_email():
    f = Fields(body())
    token = f.string("token", max_len=200)
    f.check()
    record = _consume_token(token, "verify_email")
    user = db.session.get(User, record.user_id)
    user.email_verified_at = user.email_verified_at or utcnow()
    db.session.commit()
    return jsonify({"data": {"verified": True}})


@bp.post("/verify-email/resend")
@limiter.limit("3 per hour")
@login_required
def resend_verification():
    if g.user.email_verified_at:
        return jsonify({"data": {"sent": False, "already_verified": True}})
    _send_verification(g.user)
    db.session.commit()
    return jsonify({"data": {"sent": True}})


@bp.post("/password-reset/request")
@limiter.limit("5 per hour")
def password_reset_request():
    f = Fields(body())
    email = f.email("email")
    f.check()
    user = User.query.filter_by(email=email).first()
    if user and not user.is_demo:
        token = new_token()
        db.session.add(
            AuthToken(
                user_id=user.id,
                purpose="password_reset",
                token_hash=hash_token(token),
                expires_at=utcnow() + current_app.config["PASSWORD_RESET_TTL"],
            )
        )
        queue_email(
            "password_reset",
            user.email,
            "Reset your password",
            f"Reset your password (link expires in 1 hour, single use):\n{link('/reset-password?token=' + token)}\n\n"
            "If you did not request this, you can ignore this email.",
        )
        db.session.commit()
    # Same response whether or not the account exists.
    return jsonify({"data": {"message": "If an account exists for that email, a reset link has been sent."}})


@bp.post("/password-reset/confirm")
@limiter.limit(AUTH_LIMIT)
def password_reset_confirm():
    f = Fields(body())
    token = f.string("token", max_len=200)
    f.password()
    data = f.check()
    record = _consume_token(token, "password_reset")
    user = db.session.get(User, record.user_id)
    user.password_hash = hash_password(data["password"])
    user.email_verified_at = user.email_verified_at or utcnow()  # they proved control of the inbox
    UserSession.query.filter_by(user_id=user.id, revoked_at=None).update({"revoked_at": utcnow()})
    audit.record("user.password_reset", actor_id=user.id, target_type="user", target_id=user.id)
    db.session.commit()
    return jsonify({"data": {"reset": True}})


@bp.patch("/account")
@login_required
def update_account():
    f = Fields(body())
    f.string("display_name", required=False, max_len=120)
    f.string("timezone", required=False, max_len=64)
    data = f.check()
    if data.get("display_name"):
        g.user.display_name = data["display_name"]
    if data.get("timezone"):
        g.user.timezone = data["timezone"]
    db.session.commit()
    return jsonify({"data": g.user.to_dict()})


@bp.post("/change-password")
@login_required
@limiter.limit(AUTH_LIMIT)
def change_password():
    f = Fields(body())
    f.string("current_password", max_len=128, strip=False)
    f.password("new_password")
    data = f.check()
    if g.user.is_demo:
        raise Forbidden("Demo account passwords cannot be changed")
    if not verify_password(g.user.password_hash, data["current_password"]):
        raise ValidationError("Current password is incorrect", fields={"current_password": "Incorrect password"})
    g.user.password_hash = hash_password(data["new_password"])
    current = load_user_session()
    UserSession.query.filter(
        UserSession.user_id == g.user.id, UserSession.id != current.id, UserSession.revoked_at.is_(None)
    ).update({"revoked_at": utcnow()})
    audit.record("user.password_changed", target_type="user", target_id=g.user.id)
    db.session.commit()
    return jsonify({"data": {"changed": True}})


# ------------------------------------------------------------------- invitations


@bp.get("/invitations/<token>")
@limiter.limit("30 per minute")
def invitation_preview(token):
    invitation = businesses.find_invitation(token)
    return jsonify(
        {
            "data": {
                "business_name": invitation.business.name,
                "email": invitation.email,
                "role": invitation.role,
                "account_exists": User.query.filter_by(email=invitation.email).first() is not None,
                "expires_at": invitation.to_dict()["expires_at"],
            }
        }
    )


@bp.post("/invitations/<token>/accept")
@limiter.limit(AUTH_LIMIT)
def invitation_accept(token):
    invitation = businesses.find_invitation(token)
    existing = User.query.filter_by(email=invitation.email).first()
    response = make_response()
    if existing:
        session = load_user_session()
        if not session or session.user_id != existing.id:
            raise Unauthorized(f"Sign in as {invitation.email} to accept this invitation")
        check_csrf(session.csrf_token)
        user = existing
    else:
        f = Fields(body())
        f.string("display_name", max_len=120)
        f.password()
        data = f.check()
        user = User(
            email=invitation.email,
            display_name=data["display_name"],
            password_hash=hash_password(data["password"]),
            email_verified_at=utcnow(),  # the invite link proves inbox control
        )
        db.session.add(user)
        db.session.flush()
        session = create_user_session(response, user)
    businesses.accept_invitation(invitation, user)
    session.active_business_id = invitation.business_id
    db.session.commit()
    response.set_data(jsonify({"data": session_payload(session)}).get_data())
    response.mimetype = "application/json"
    return response
