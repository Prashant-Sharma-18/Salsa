import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import App from "../App";
import type { SessionInfo } from "../api/types";

export const ownerSession: SessionInfo = {
  user: { id: 1, email: "owner@example.com", display_name: "Olivia Owner", email_verified: true, is_platform_admin: false, timezone: "UTC", mfa_enabled: false },
  csrf_token: "csrf-test",
  mfa_setup_required: false,
  billing: { plan: "trial", plan_name: "Free trial", status: "trialing", in_good_standing: true, trial_ends_at: "2099-01-01T00:00:00Z", current_period_end: null },
  businesses: [{ id: 1, name: "Test Cafe", role: "owner" }],
  active_business: { id: 1, name: "Test Cafe", slug: "test-cafe", timezone: "UTC", is_demo: true, plan: "trial", require_mfa: false },
  role: "owner",
  permissions: [
    "business.manage", "program.view", "program.manage", "locations.view", "locations.manage", "members.view", "members.manage",
    "customers.view", "customers.create", "customers.edit", "customers.privacy", "purchases.create", "ledger.adjust", "ledger.reverse",
    "rewards.view", "rewards.manage", "redemptions.issue", "redemptions.complete", "redemptions.cancel", "referrals.view",
    "referrals.manage", "analytics.view", "exports.run", "audit.view", "expiry.run", "billing.manage", "customers.import",
  ],
  location_access: { all: true, location_ids: [] },
};

const program = {
  id: 1, name: "Test Rewards", description: "", status: "active", brand_color: "#1769aa", logo_url: "", contact_email: "",
  contact_phone: "", earning_enabled: true, points_per_dollar: 1, min_spend_cents: 0, redemption_enabled: true,
  referrals_enabled: true, referrer_reward_points: 100, referee_reward_points: 50, referral_min_spend_cents: 0,
  points_expiry_days: null, rules: ["Earn 1 point for every $1 spent."], updated_at: "2026-01-01T00:00:00Z",
};

const customer = {
  id: 7, display_name: "Ava Thompson", email: "ava@example.com", phone: null, status: "active", enrolled_at: "2026-01-01T00:00:00Z",
  points_balance: 120, referral_code: "ABCD2345", marketing_opt_in: false, is_demo: true, enrolled_location_id: 1,
  last_activity_at: "2026-01-02T00:00:00Z", recent_ledger: [], open_redemptions: [], referred_by: null, referrals_made: [], consent_history: [],
};

const metrics = { enrollments: 1, active_customers: 1, points_issued: 10, points_redeemed: 0, rewards_redeemed: 0, referrals: 0, qualified_referrals: 0 };
const paged = (data: unknown[]) => ({ data, meta: { page: 1, page_size: 25, total: data.length, pages: 1, status_counts: {} } });

/** Very small fake API keyed by path prefix. */
export function fakeApi(session: SessionInfo | null, extra: [RegExp, unknown][] = []) {
  const routes: [RegExp, unknown][] = [
    ...extra,
    [/^\/auth\/me/, { data: session }],
    [/^\/meta/, { data: { app_name: "LoyalLoop", demo_mode: false, demo_seeded: false, dev_mailbox: false } }],
    [/^\/dashboard/, { data: { range: { start: "2026-01-01", end: "2026-01-30" }, activity: [], summary: metrics, totals: { enrolled_customers: 1 } } }],
    [/^\/customers\/\d+\/ledger/, paged([])],
    [/^\/customers\/\d+/, { data: customer }],
    [/^\/customers/, paged([customer])],
    [/^\/locations/, { data: [{ id: 1, name: "Main", address: "", status: "active", accessible: true, created_at: "2026-01-01T00:00:00Z" }] }],
    [/^\/programs\/current/, { data: program }],
    [/^\/rewards/, { data: [] }],
    [/^\/redemptions/, paged([])],
    [/^\/referrals/, paged([])],
    [/^\/analytics\/summary/, { data: { range: { start: "2026-01-01", end: "2026-01-30", timezone: "UTC" }, metrics, series: [], definitions: metrics } }],
    [/^\/members/, { data: { members: [], invitations: [] } }],
    [/^\/audit-logs/, paged([])],
  ];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input).replace(/^\/api\/v1/, "");
    const match = routes.find(([re]) => re.test(url));
    const body = match ? match[1] : { error: { code: "not_found", message: "Not found" } };
    return new Response(JSON.stringify(body), { status: match ? 200 : 404, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function renderApp(path: string, session: SessionInfo | null = ownerSession, extra: [RegExp, unknown][] = []) {
  fakeApi(session, extra);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
