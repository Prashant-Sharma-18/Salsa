import itertools
import re

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import NotificationOutbox

_counter = itertools.count(1)


class Api:
    """Test client wrapper that tracks the CSRF token like the frontend does."""

    def __init__(self, app):
        self.client = app.test_client()
        self.csrf = None

    def _headers(self, headers=None, idem=None):
        h = dict(headers or {})
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        if idem:
            h["Idempotency-Key"] = idem
        return h

    def _track(self, resp):
        data = resp.get_json(silent=True) or {}
        if isinstance(data.get("data"), dict) and data["data"].get("csrf_token"):
            self.csrf = data["data"]["csrf_token"]
        return resp

    def get(self, path, **kw):
        return self._track(self.client.get("/api/v1" + path, headers=self._headers(kw.pop("headers", None)), **kw))

    def post(self, path, json=None, idem=None, **kw):
        return self._track(
            self.client.post(
                "/api/v1" + path,
                json=json if json is not None else {},
                headers=self._headers(kw.pop("headers", None), idem),
                **kw,
            )
        )

    def patch(self, path, json=None, **kw):
        return self._track(
            self.client.patch("/api/v1" + path, json=json or {}, headers=self._headers(kw.pop("headers", None)), **kw)
        )

    def delete(self, path, **kw):
        return self._track(self.client.delete("/api/v1" + path, headers=self._headers(kw.pop("headers", None)), **kw))


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def new_api(app):
    def factory():
        return Api(app)

    return factory


def last_email_link(path_fragment: str, recipient: str | None = None) -> str:
    query = NotificationOutbox.query.order_by(NotificationOutbox.id.desc())
    if recipient:
        query = query.filter_by(recipient=recipient)
    for msg in query:
        match = re.search(r"https?://\S+", msg.body)
        if match and path_fragment in match.group(0):
            return match.group(0)
    raise AssertionError(f"No email link containing {path_fragment}")


def token_from(url: str) -> str:
    return url.rsplit("token=", 1)[1] if "token=" in url else url.rsplit("/", 1)[1]


def signup(api: Api, email=None, name="Test User", password="correct-horse-1"):
    email = email or f"user{next(_counter)}@example.com"
    resp = api.post("/auth/signup", {"display_name": name, "email": email, "password": password})
    assert resp.status_code == 201, resp.get_json()
    return email


def verify_email(api: Api, email: str):
    token = token_from(last_email_link("/verify-email", email))
    assert api.post("/auth/verify-email", {"token": token}).status_code == 200


def create_business(api: Api, name="Biz", points_per_dollar=1):
    resp = api.post(
        "/businesses",
        {"name": name, "location_name": "Main", "points_per_dollar": points_per_dollar},
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]["active_business"]


@pytest.fixture
def owner(new_api):
    """Signed-in, verified owner with a business, one location and a program (1 pt per $1)."""
    api = new_api()
    email = signup(api, name="Owner One")
    verify_email(api, email)
    business = create_business(api, "Alpha Cafe")
    api.email = email
    api.business = business
    api.location_id = api.get("/locations").get_json()["data"][0]["id"]
    return api


def enroll(api: Api, name="Customer", email=None, **extra):
    email = email if email is not None else f"cust{next(_counter)}@example.com"
    payload = {"display_name": name, "email": email, **extra}
    resp = api.post("/customers", payload)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]


def purchase(api: Api, customer_id: int, amount: str, location_id: int, key=None, **extra):
    key = key or f"key-{next(_counter):08d}"
    return api.post(
        "/purchases", {"customer_id": customer_id, "amount": amount, "location_id": location_id, **extra}, idem=key
    )


def invite_and_join(owner_api: Api, new_api, role="staff", all_locations=True, location_ids=None):
    email = f"{role}{next(_counter)}@example.com"
    resp = owner_api.post(
        "/members/invitations",
        {"email": email, "role": role, "all_locations": all_locations, "location_ids": location_ids or []},
    )
    assert resp.status_code == 201, resp.get_json()
    token = token_from(last_email_link("/invite/", email))
    member = new_api()
    resp = member.post(
        f"/auth/invitations/{token}/accept", {"display_name": role.title(), "password": "member-pass-123"}
    )
    assert resp.status_code == 200, resp.get_json()
    return member
