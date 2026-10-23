"""Tenant isolation and role/location authorization."""

from .conftest import create_business, enroll, invite_and_join, purchase, signup, verify_email


def _second_owner(new_api):
    api = new_api()
    email = signup(api, name="Owner Two")
    verify_email(api, email)
    create_business(api, "Beta Salon")
    api.location_id = api.get("/locations").get_json()["data"][0]["id"]
    return api


def test_cross_tenant_access_is_denied(owner, new_api):
    # Business A data
    customer = enroll(owner, "Alice A")
    purchase(owner, customer["id"], "50.00", owner.location_id)
    reward = owner.post("/rewards", {"name": "Free tea", "reward_type": "free_item", "points_cost": 10}).get_json()[
        "data"
    ]
    redemption = owner.post(
        "/redemptions",
        {"customer_id": customer["id"], "reward_id": reward["id"], "location_id": owner.location_id},
        idem="redeem-aaaa-1",
    ).get_json()["data"]
    referrer_b_target = enroll(owner, "Bob A")
    referral = owner.post(
        "/referrals", {"referrer_customer_id": referrer_b_target["id"], "email": "f@example.com"}
    ).get_json()["data"]
    entry_id = owner.get(f"/customers/{customer['id']}/ledger").get_json()["data"][0]["id"]

    other = _second_owner(new_api)
    cid = customer["id"]
    attempts = [
        other.get(f"/customers/{cid}"),
        other.get(f"/customers/{cid}/ledger"),
        other.patch(f"/customers/{cid}", {"display_name": "Hacked"}),
        other.post(f"/customers/{cid}/adjustments", {"points": 100, "reason": "steal"}),
        other.get(f"/customers/{cid}/privacy-export"),
        other.post(f"/customers/{cid}/anonymize", {"confirm": "DELETE"}),
        other.post(f"/ledger/{entry_id}/reverse", {"reason": "mischief"}),
        other.patch(f"/rewards/{reward['id']}", {"points_cost": 1}),
        other.delete(f"/rewards/{reward['id']}"),
        other.post(f"/redemptions/{redemption['id']}/complete", {"location_id": other.location_id}),
        other.post(f"/redemptions/{redemption['id']}/cancel", {"reason": "mischief"}),
        other.get(f"/redemptions/lookup?code={redemption['code']}"),
        other.post(f"/referrals/{referral['id']}/reject", {"reason": "mischief"}),
        purchase(other, cid, "10.00", other.location_id),
        other.post(
            "/redemptions",
            {"customer_id": cid, "reward_id": reward["id"], "location_id": other.location_id},
            idem="redeem-bbbb-1",
        ),
        purchase(other, enroll(other, "Own")["id"], "10.00", owner.location_id),  # A's location id
        other.post("/referrals", {"referrer_customer_id": cid, "email": "x@example.com"}),
    ]
    for resp in attempts:
        assert resp.status_code == 404, (resp.request.path, resp.status_code, resp.get_json())

    # Lists, analytics and exports only contain the caller's own data
    assert other.get("/customers").get_json()["meta"]["total"] == 1
    assert other.get("/rewards").get_json()["data"] == []
    assert other.get("/referrals").get_json()["meta"]["total"] == 0
    assert other.get("/redemptions").get_json()["meta"]["total"] == 0
    assert "Alice A" not in other.get("/exports/customers.csv").get_data(as_text=True)
    assert other.get("/analytics/summary").get_json()["data"]["metrics"]["points_issued"] == 0
    # Location filter for a foreign location is rejected
    assert other.get(f"/analytics/summary?location_id={owner.location_id}").status_code == 422

    # Cannot switch into a business without membership
    assert other.post("/auth/switch-business", {"business_id": owner.business["id"]}).status_code == 403

    # Business A unchanged
    assert owner.get(f"/customers/{cid}").get_json()["data"]["display_name"] == "Alice A"


def test_staff_cannot_perform_owner_or_manager_operations(owner, new_api):
    staff = invite_and_join(owner, new_api, "staff")
    customer = enroll(staff, "Walk In")
    forbidden = [
        staff.patch("/programs/current", {"points_per_dollar": 50}),
        staff.post("/locations", {"name": "Rogue"}),
        staff.post("/members/invitations", {"email": "pal@example.com", "role": "manager"}),
        staff.get("/members"),
        staff.post(f"/customers/{customer['id']}/adjustments", {"points": 1000, "reason": "bonus"}),
        staff.get("/exports/customers.csv"),
        staff.get("/analytics/summary"),
        staff.post("/rewards", {"name": "x", "reward_type": "custom", "points_cost": 1}),
        staff.post(f"/customers/{customer['id']}/anonymize", {"confirm": "DELETE"}),
        staff.get("/audit-logs"),
        staff.patch("/businesses/current", {"name": "Mine now"}),
    ]
    for resp in forbidden:
        assert resp.status_code == 403, (resp.request.path, resp.status_code)
    # Staff can do checkout work
    assert purchase(staff, customer["id"], "12.00", owner.location_id).status_code == 201


def test_manager_cannot_escalate_privileges(owner, new_api):
    manager = invite_and_join(owner, new_api, "manager")
    members = owner.get("/members").get_json()["data"]["members"]
    manager_membership = next(m for m in members if m["role"] == "manager")
    owner_membership = next(m for m in members if m["role"] == "owner")
    assert manager.post("/members/invitations", {"email": "p@example.com", "role": "manager"}).status_code == 403
    assert manager.patch(f"/members/{manager_membership['id']}", {"role": "manager"}).status_code == 403
    assert manager.patch(f"/members/{owner_membership['id']}", {"status": "deactivated"}).status_code == 403
    assert manager.patch("/programs/current", {"points_per_dollar": 99}).status_code == 403
    # Owner cannot edit own membership or other owners
    assert owner.patch(f"/members/{owner_membership['id']}", {"role": "staff"}).status_code == 403


def test_deactivated_member_loses_access_immediately(owner, new_api):
    staff = invite_and_join(owner, new_api, "staff")
    assert staff.get("/customers").status_code == 200
    members = owner.get("/members").get_json()["data"]["members"]
    staff_membership = next(m for m in members if m["role"] == "staff")
    assert owner.patch(f"/members/{staff_membership['id']}", {"status": "deactivated"}).status_code == 200
    assert staff.get("/customers").status_code == 403


def test_role_change_takes_effect(owner, new_api):
    staff = invite_and_join(owner, new_api, "staff")
    members = owner.get("/members").get_json()["data"]["members"]
    staff_membership = next(m for m in members if m["role"] == "staff")
    assert staff.get("/analytics/summary").status_code == 403
    owner.patch(f"/members/{staff_membership['id']}", {"role": "manager"})
    assert staff.get("/analytics/summary").status_code == 200


def test_staff_location_permissions_enforced(owner, new_api):
    second = owner.post("/locations", {"name": "Second"}).get_json()["data"]
    staff = invite_and_join(owner, new_api, "staff", all_locations=False, location_ids=[owner.location_id])
    customer = enroll(staff, "Loc Test")
    assert purchase(staff, customer["id"], "10.00", owner.location_id).status_code == 201
    resp = purchase(staff, customer["id"], "10.00", second["id"])
    assert resp.status_code == 403
    locations = staff.get("/locations").get_json()["data"]
    assert {loc["id"]: loc["accessible"] for loc in locations} == {owner.location_id: True, second["id"]: False}


def test_audit_log_records_sensitive_actions(owner):
    customer = enroll(owner, "Audited")
    owner.post(f"/customers/{customer['id']}/adjustments", {"points": 5, "reason": "Goodwill gesture"})
    owner.get("/exports/customers.csv")
    owner.patch("/programs/current", {"points_per_dollar": 3})
    actions = {row["action"] for row in owner.get("/audit-logs").get_json()["data"]}
    assert {"points.adjusted", "export.customers", "program.updated"} <= actions
