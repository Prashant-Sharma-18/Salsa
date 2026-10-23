import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ownerSession, renderApp } from "./utils";

describe("two-factor sign-in", () => {
  it("asks for an authentication code after the password when MFA is on", async () => {
    renderApp("/signin", null, [[/^\/auth\/signin/, { data: { mfa_required: true, mfa_token: "challenge" } }]]);
    await userEvent.type(await screen.findByLabelText("Email"), "owner@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-1");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Two-factor verification" })).toBeInTheDocument();
    expect(screen.getByLabelText("Authentication code")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Use a recovery code instead" }));
    expect(screen.getByLabelText("Recovery code")).toBeInTheDocument();
  });

  it("blocks business pages until required two-factor is set up", async () => {
    renderApp("/customers", { ...ownerSession, mfa_setup_required: true });
    expect(await screen.findByRole("heading", { name: "Two-factor authentication required" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "Customers" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up two-factor" })).toHaveAttribute("href", "/account");
  });

  it("shows the two-factor card on the account page", async () => {
    renderApp("/account", ownerSession, [[/^\/auth\/mfa/, { data: { enabled: false, recovery_codes_remaining: 0 } }]]);
    expect(await screen.findByRole("heading", { name: "Two-factor authentication" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Require two-factor authentication for owners and managers/)).toBeInTheDocument();
  });
});
