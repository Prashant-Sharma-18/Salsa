import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ownerSession, renderApp } from "./utils";

const promo = {
  id: 1, name: "Double Tuesdays", description: "", promo_type: "multiplier", multiplier_percent: 200, bonus_points: null,
  starts_on: "2026-10-01", ends_on: null, days_of_week: [1], location_ids: [], min_spend_cents: 0, status: "active", created_at: "2026-10-01T00:00:00Z",
};
const session = { ...ownerSession, permissions: [...ownerSession.permissions, "promotions.view", "promotions.manage"] };

describe("promotions", () => {
  it("lists promotions with plain-language schedules", async () => {
    renderApp("/promotions", session, [[/^\/promotions/, { data: [promo] }]]);
    expect(await screen.findByText("Double Tuesdays")).toBeInTheDocument();
    expect(screen.getByText("2x points")).toBeInTheDocument();
    expect(screen.getByText(/Tue · from Oct 1, 2026/)).toBeInTheDocument();
  });

  it("validates the promotion form", async () => {
    renderApp("/promotions", session, [[/^\/promotions/, { data: [] }]]);
    await userEvent.click(await screen.findByRole("button", { name: "New promotion" }));
    await userEvent.selectOptions(screen.getByLabelText("Type"), "bonus");
    await userEvent.type(screen.getByLabelText("Name"), "Big order bonus");
    await userEvent.click(screen.getByRole("button", { name: "Create promotion" }));
    expect(await screen.findByText("Enter whole bonus points")).toBeInTheDocument();
  });

  it("shows today's promotions and the boosted estimate at checkout", async () => {
    renderApp("/checkout?customer=7", session, [[/^\/promotions\/active/, { data: [promo] }]]);
    expect(await screen.findByText(/Double Tuesdays \(2x points\)/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Purchase total ($)"), "10.00");
    expect(await screen.findByText(/Estimated: 20 points/)).toBeInTheDocument();
  });
});
