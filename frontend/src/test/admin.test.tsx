import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ownerSession, renderApp } from "./utils";

const adminSession = { ...ownerSession, user: { ...ownerSession.user, is_platform_admin: true }, active_business: null, businesses: [], role: null, permissions: [], billing: null };
const overview = { businesses: 3, by_status: { trialing: 2, active: 1 }, active_last_30_days: 2, users: 5, customers: 40, mrr_cents: 7900 };
const row = {
  id: 9, name: "Bean There", slug: "bean-there", timezone: "UTC", is_demo: false, plan: "growth", require_mfa: false,
  created_at: "2026-10-01T00:00:00Z", suspended: false, suspended_reason: null, members: 2, customers: 40, owner_email: "owner@bean.example",
  billing: { plan: "growth", plan_name: "Growth", status: "active", in_good_standing: true, trial_ends_at: null, current_period_end: null },
};

describe("platform admin", () => {
  it("shows overview metrics and businesses", async () => {
    renderApp("/admin", adminSession, [
      [/^\/admin\/overview/, { data: overview }],
      [/^\/admin\/businesses/, { data: [row], meta: { page: 1, page_size: 25, total: 1, pages: 1 } }],
    ]);
    expect(await screen.findByRole("heading", { level: 1, name: "Platform admin" })).toBeInTheDocument();
    expect(await screen.findByText("$79.00")).toBeInTheDocument();
    expect(screen.getByText("Bean There")).toBeInTheDocument();
    expect(screen.getByText("owner@bean.example")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage Bean There" })).toBeInTheDocument();
  });

  it("redirects an admin without a business to the console", async () => {
    renderApp("/", adminSession, [
      [/^\/admin\/overview/, { data: overview }],
      [/^\/admin\/businesses/, { data: [], meta: { page: 1, page_size: 25, total: 0, pages: 1 } }],
    ]);
    expect(await screen.findByRole("heading", { level: 1, name: "Platform admin" })).toBeInTheDocument();
  });

  it("keeps non-admins out", async () => {
    renderApp("/admin");
    expect(await screen.findByText("Platform admins only")).toBeInTheDocument();
  });

  it("shows a suspension screen to members of a suspended business", async () => {
    renderApp("/customers", { ...ownerSession, active_business: { ...ownerSession.active_business!, suspended: true } });
    expect(await screen.findByText("This business account is suspended")).toBeInTheDocument();
  });
});
