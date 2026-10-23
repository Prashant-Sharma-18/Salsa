import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { formatMoney, formatPoints } from "../lib/format";
import { ownerSession, renderApp } from "./utils";

describe("formatting", () => {
  it("formats integer cents as dollars", () => {
    expect(formatMoney(1299)).toBe("$12.99");
    expect(formatMoney(0)).toBe("$0.00");
  });
  it("formats signed points", () => {
    expect(formatPoints(50, true)).toBe("+50");
    expect(formatPoints(-1200, true)).toBe("−1,200");
  });
});

describe("main pages render without runtime errors", () => {
  const pages: [string, string][] = [
    ["/", "Welcome, Olivia"],
    ["/customers", "Customers"],
    ["/customers/new", "Enroll customer"],
    ["/customers/7", "Ava Thompson"],
    ["/checkout", "Record purchase"],
    ["/redemptions", "Validate redemption"],
    ["/rewards", "Rewards catalog"],
    ["/referrals", "Referrals"],
    ["/analytics", "Analytics & exports"],
    ["/settings/program", "Program settings"],
    ["/locations", "Locations"],
    ["/team", "Staff & permissions"],
    ["/audit", "Audit log"],
    ["/account", "Account & privacy"],
  ];
  it.each(pages)("%s", async (path, heading) => {
    renderApp(path);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it("redirects signed-out users to sign in", async () => {
    renderApp("/customers", null);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows a demo data label for demo businesses", async () => {
    renderApp("/");
    expect(await screen.findByText(/all customers, transactions and analytics here are sample data/i)).toBeInTheDocument();
  });

  it("hides pages a staff member lacks permission for", async () => {
    const staff = { ...ownerSession, role: "staff" as const, permissions: ["customers.view", "purchases.create"] };
    renderApp("/settings/program", staff);
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Program settings" })).not.toBeInTheDocument();
  });
});

describe("form validation feedback", () => {
  it("sign in shows required errors", async () => {
    renderApp("/signin", null);
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findAllByText("Required")).toHaveLength(2);
    await userEvent.type(screen.getByLabelText("Email"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
  });

  it("sign up enforces password length", async () => {
    renderApp("/signup", null);
    await userEvent.type(await screen.findByLabelText("Your name"), "Pat");
    await userEvent.type(screen.getByLabelText("Work email"), "pat@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Use at least 10 characters")).toBeInTheDocument();
  });

  it("enrollment requires an email or phone", async () => {
    renderApp("/customers/new");
    await userEvent.type(await screen.findByLabelText("Name"), "Walk In");
    await userEvent.click(screen.getByRole("button", { name: "Enroll customer" }));
    expect(await screen.findByText("Provide an email or phone number")).toBeInTheDocument();
  });

  it("purchase amount must be valid money", async () => {
    renderApp("/checkout?customer=7");
    const amount = await screen.findByLabelText("Purchase total ($)");
    await userEvent.type(amount, "12.345");
    await userEvent.click(screen.getByRole("button", { name: "Award points" }));
    await waitFor(() => expect(screen.getByText("Enter an amount like 12.50")).toBeInTheDocument());
  });
});
