"""End-to-end smoke test against a running server (MVP success criteria 1-8).

Usage (server started with DEMO_MODE=true so the dev mailbox is available):
    python scripts/smoke_e2e.py http://127.0.0.1:5000
"""

import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000").rstrip("/")


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = None

    def call(self, method, path, body=None, idem=None, expect=(200, 201, 202)):
        headers = {"Accept": "application/json"}
        data = None
        if method != "GET":
            headers["Content-Type"] = "application/json"
            data = json.dumps(body or {}).encode()
            if self.csrf:
                headers["X-CSRF-Token"] = self.csrf
        if idem:
            headers["Idempotency-Key"] = idem
        req = urllib.request.Request(BASE + "/api/v1" + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        payload = json.loads(raw) if raw and raw[:1] in (b"{", b"[") else raw.decode()
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict) and payload["data"].get("csrf_token"):
            self.csrf = payload["data"]["csrf_token"]
        if status not in expect:
            raise AssertionError(f"{method} {path} -> {status}: {payload}")
        return status, payload


def mailbox_link(client, fragment, recipient):
    _, box = client.call("GET", "/dev/outbox")
    for msg in box["data"]:
        if msg["recipient"] == recipient:
            m = re.search(r"https?://\S+", msg["body"])
            if m and fragment in m.group(0):
                return m.group(0)
    raise AssertionError(f"no {fragment} email for {recipient}")


def step(n, text):
    print(f"[{n}] {text}")


def main():
    suffix = uuid.uuid4().hex[:6]
    owner = Client()
    email = f"owner-{suffix}@example.com"

    step(1, "Create a business account")
    owner.call("POST", "/auth/signup", {"display_name": "E2E Owner", "email": email, "password": "e2e-password-123"})
    token = mailbox_link(owner, "/verify-email", email).split("token=")[1]
    owner.call("POST", "/auth/verify-email", {"token": token})
    _, s = owner.call(
        "POST", "/businesses", {"name": f"E2E Cafe {suffix}", "location_name": "Main St", "points_per_dollar": 2}
    )
    slug = s["data"]["active_business"]["slug"]

    step(2, "Configure program earning/redemption rules")
    owner.call(
        "PATCH",
        "/programs/current",
        {
            "points_per_dollar": 10,
            "min_spend": "2.00",
            "referrer_reward_points": 100,
            "referee_reward_points": 25,
            "referral_min_spend": "5.00",
        },
    )
    _, reward = owner.call("POST", "/rewards", {"name": "Free latte", "reward_type": "free_item", "points_cost": 200})

    step(3, "Add a location and invite a staff member")
    _, loc2 = owner.call("POST", "/locations", {"name": "Second St"})
    staff_email = f"staff-{suffix}@example.com"
    owner.call(
        "POST",
        "/members/invitations",
        {"email": staff_email, "role": "staff", "all_locations": False, "location_ids": [loc2["data"]["id"]]},
    )
    invite_token = mailbox_link(owner, "/invite/", staff_email).rsplit("/", 1)[1]
    staff = Client()
    staff.call(
        "POST",
        f"/auth/invitations/{invite_token}/accept",
        {"display_name": "E2E Staff", "password": "staff-password-1"},
    )
    staff.call(
        "POST",
        f"/auth/invitations/{invite_token}/accept",
        {"display_name": "X", "password": "staff-password-1"},
        expect=(409,),
    )

    step(4, "Staff enrolls customers (one referred)")
    _, alice = staff.call(
        "POST",
        "/customers",
        {"display_name": "Alice", "email": f"alice-{suffix}@example.com", "location_id": loc2["data"]["id"]},
    )
    _, bob = staff.call(
        "POST",
        "/customers",
        {"display_name": "Bob", "email": f"bob-{suffix}@example.com", "referral_code": alice["data"]["referral_code"]},
    )
    assert bob["data"]["referral"]["status"] == "signed_up"

    step(5, "Staff records purchases; duplicate submission is not double-counted")
    key = str(uuid.uuid4())
    _, p = staff.call(
        "POST",
        "/purchases",
        {
            "customer_id": alice["data"]["id"],
            "amount": "25.50",
            "location_id": loc2["data"]["id"],
            "external_ref": "R-1",
        },
        idem=key,
    )
    assert p["data"]["purchase"]["points_awarded"] == 255, p
    staff.call(
        "POST",
        "/purchases",
        {
            "customer_id": alice["data"]["id"],
            "amount": "25.50",
            "location_id": loc2["data"]["id"],
            "external_ref": "R-1",
        },
        idem=key,
        expect=(200,),
    )
    staff.call(
        "POST",
        "/purchases",
        {"customer_id": bob["data"]["id"], "amount": "8.00", "location_id": loc2["data"]["id"]},
        idem=str(uuid.uuid4()),
    )
    main_loc = [loc for loc in owner.call("GET", "/locations")[1]["data"] if loc["name"] == "Main St"][0]
    staff.call(
        "POST",
        "/purchases",
        {"customer_id": bob["data"]["id"], "amount": "8.00", "location_id": main_loc["id"]},
        idem=str(uuid.uuid4()),
        expect=(403,),
    )

    step(6, "Redeem a reward and validate the code")
    _, red = staff.call(
        "POST",
        "/redemptions",
        {"customer_id": alice["data"]["id"], "reward_id": reward["data"]["id"], "location_id": loc2["data"]["id"]},
        idem=str(uuid.uuid4()),
    )
    code = red["data"]["code"]
    _, found = staff.call("GET", f"/redemptions/lookup?code={code}")
    assert found["data"]["status"] == "issued"
    staff.call("POST", f"/redemptions/{red['data']['id']}/complete", {"location_id": loc2["data"]["id"]})
    staff.call("POST", f"/redemptions/{red['data']['id']}/complete", {"location_id": loc2["data"]["id"]}, expect=(409,))
    staff.call(
        "POST",
        "/redemptions",
        {"customer_id": alice["data"]["id"], "reward_id": reward["data"]["id"], "location_id": loc2["data"]["id"]},
        idem=str(uuid.uuid4()),
        expect=(409,),
    )

    step(7, "Referral qualified and rewarded")
    _, refs = owner.call("GET", "/referrals")
    assert refs["data"][0]["status"] == "rewarded", refs
    _, a = owner.call("GET", f"/customers/{alice['data']['id']}")
    assert a["data"]["points_balance"] == 255 - 200 + 100, a["data"]["points_balance"]

    step(8, "Transaction history, analytics, exports and audit")
    _, ledger = owner.call("GET", f"/customers/{alice['data']['id']}/ledger")
    assert [e["entry_type"] for e in ledger["data"]] == ["redemption", "referral_bonus", "award"]
    _, summary = owner.call("GET", "/analytics/summary")
    m = summary["data"]["metrics"]
    assert m["enrollments"] == 2 and m["rewards_redeemed"] == 1 and m["qualified_referrals"] == 1, m
    _, csv = owner.call("GET", "/exports/customers.csv")
    assert "Alice" in csv
    staff.call("GET", "/exports/customers.csv", expect=(403,))
    _, audit = owner.call("GET", "/audit-logs")
    assert any(row["action"] == "export.customers" for row in audit["data"])

    step(9, "Customer portal via magic link")
    staff.call("POST", f"/customers/{alice['data']['id']}/portal-link")
    portal_token = mailbox_link(owner, "/portal/access", f"alice-{suffix}@example.com").split("token=")[1]
    customer = Client()
    customer.call("POST", "/customer-portal/session", {"token": portal_token})
    _, me = customer.call("GET", "/customer-portal/me")
    assert me["data"]["customer"]["points_balance"] == 155
    assert "Bob" not in json.dumps(me)
    Client().call("POST", "/customer-portal/session", {"token": portal_token}, expect=(400,))

    step(10, "Public join page and SPA served")
    Client().call("GET", f"/public/programs/{slug}")
    with urllib.request.urlopen(BASE + "/customers") as resp:
        assert b'<div id="root">' in resp.read()
    print("E2E smoke test passed")


if __name__ == "__main__":
    main()
