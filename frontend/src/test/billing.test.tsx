import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ownerSession, renderApp } from "./utils";

const overview = {
  plan: "starter", plan_name: "Starter", status: "active", in_good_standing: true, trial_ends_at: null,
  current_period_end: "2099-01-01T00:00:00Z", provider: "dev", has_billing_account: false, trial_days: 14,
  limits: { locations: 1, customers: 500, members: 3 }, usage: { locations: 1, customers: 450, members: 2 },
  plans: [
    { id: "starter", name: "Starter", price_cents: 2900, description: "One location", limits: { locations: 1, customers: 500, members: 3 } },
    { id: "pro", name: "Pro", price_cents: 19900, description: "Chains", limits: { locations: null, customers: null, members: null } },
  ],
};

describe("billing", () => {
  it("shows plan, usage and simulated plan switching", async () => {
    renderApp("/settings/billing", ownerSession, [[/^\/billing/, { data: overview }]]);
    expect(await screen.findByRole("heading", { level: 1, name: "Billing" })).toBeInTheDocument();
    expect(screen.getByText("Simulated billing")).toBeInTheDocument();
    expect(screen.getByText("450 of 500")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Current plan" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Switch to Pro (simulated)" })).toBeInTheDocument();
  });

  it("warns when the trial has ended", async () => {
    renderApp("/", {
      ...ownerSession,
      active_business: { ...ownerSession.active_business!, is_demo: false },
      billing: { plan: "trial", plan_name: "Free trial", status: "trial_expired", in_good_standing: false, trial_ends_at: "2020-01-01T00:00:00Z", current_period_end: null },
    });
    expect(await screen.findByText(/Your free trial has ended/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Billing" })).toHaveAttribute("href", "/settings/billing");
  });

  it("hides billing from staff", async () => {
    renderApp("/settings/billing", { ...ownerSession, role: "staff", permissions: ["customers.view"] });
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
  });
});

describe("counter sign", () => {
  it("renders a printable sign with the join QR code", async () => {
    renderApp("/print/join-sign", ownerSession, [
      [/^\/programs\/current\/sign/, { data: { business_name: "Test Cafe", program_name: "Test Rewards", brand_color: "#1769aa", logo_url: "", rules: ["Earn 1 point for every $1 spent.", "Points do not expire."], join_url: "http://localhost:5173/join/test-cafe", status: "active" } }],
    ]);
    expect(await screen.findByRole("heading", { name: "Join Test Rewards" })).toBeInTheDocument();
    expect(screen.getByAltText(/QR code linking to/)).toHaveAttribute("src", "/api/v1/programs/current/join-qr.svg");
    expect(screen.getByText("localhost:5173/join/test-cafe")).toBeInTheDocument();
    expect(screen.queryByText("Points do not expire.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print sign" })).toBeInTheDocument();
  });
});
