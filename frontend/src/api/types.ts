export type Role = "owner" | "manager" | "staff";

export interface Envelope<T> {
  data: T;
}

export interface Paged<T> {
  data: T[];
  meta: { page: number; page_size: number; total: number; pages: number; status_counts?: Record<string, number> };
}

export interface User {
  id: number;
  email: string;
  display_name: string;
  email_verified: boolean;
  is_platform_admin: boolean;
  timezone: string;
}

export interface Business {
  id: number;
  name: string;
  slug: string;
  timezone: string;
  is_demo: boolean;
  plan: string;
}

export interface SessionInfo {
  user: User;
  csrf_token: string;
  businesses: { id: number; name: string; role: Role }[];
  active_business: Business | null;
  role: Role | null;
  permissions: string[];
  location_access: { all: boolean; location_ids: number[] } | null;
}

export interface Location {
  id: number;
  name: string;
  address: string;
  status: "active" | "archived";
  accessible?: boolean;
  created_at: string;
}

export interface Program {
  id: number;
  name: string;
  description: string;
  status: "draft" | "active" | "paused";
  brand_color: string;
  logo_url: string;
  contact_email: string;
  contact_phone: string;
  earning_enabled: boolean;
  points_per_dollar: number;
  min_spend_cents: number;
  redemption_enabled: boolean;
  referrals_enabled: boolean;
  referrer_reward_points: number;
  referee_reward_points: number;
  referral_min_spend_cents: number;
  points_expiry_days: number | null;
  rules: string[];
  updated_at: string;
}

export interface Customer {
  id: number;
  display_name: string;
  email: string | null;
  phone: string | null;
  status: "active" | "inactive" | "anonymized";
  enrolled_at: string;
  points_balance: number;
  referral_code: string;
  marketing_opt_in: boolean;
  is_demo: boolean;
}

export interface LedgerEntry {
  id: number;
  customer_id: number;
  location_id: number | null;
  entry_type: "award" | "redemption" | "reversal" | "adjustment" | "expiration" | "referral_bonus";
  points: number;
  balance_after: number;
  reason: string;
  source_type: string | null;
  source_id: number | null;
  actor: string | null;
  reverses_entry_id: number | null;
  created_at: string;
  reversed?: boolean;
  customer_name?: string;
}

export interface Reward {
  id: number;
  name: string;
  description: string;
  reward_type: "fixed_discount" | "free_item" | "custom";
  value_cents: number | null;
  points_cost: number;
  status: "active" | "archived";
  stock_limit: number | null;
  stock_remaining: number | null;
  terms: string;
  updated_at: string;
}

export interface Redemption {
  id: number;
  code: string;
  status: "issued" | "redeemed" | "expired" | "cancelled";
  points_cost: number;
  reward: { id: number; name: string; terms: string };
  customer?: { id: number; display_name: string; points_balance: number };
  location_id: number | null;
  issued_via: string;
  completed_at: string | null;
  cancelled_at: string | null;
  expires_at: string;
  created_at: string;
  duplicate?: boolean;
}

export interface Referral {
  id: number;
  referrer: { id: number; display_name: string };
  referred: { id: number; display_name: string } | null;
  status: "created" | "clicked" | "signed_up" | "qualified" | "rewarded" | "rejected";
  source: string;
  rejection_reason: string | null;
  signed_up_at: string | null;
  qualified_at: string | null;
  rewarded_at: string | null;
  created_at: string;
}

export interface ConsentRecord {
  id: number;
  consent_type: string;
  granted: boolean;
  source: string;
  created_at: string;
}

export interface CustomerDetail extends Customer {
  enrolled_location_id: number | null;
  last_activity_at: string;
  recent_ledger: LedgerEntry[];
  open_redemptions: Redemption[];
  referred_by: Referral | null;
  referrals_made: Referral[];
  consent_history: ConsentRecord[];
}

export interface Member {
  id: number;
  user: { id: number; display_name: string; email: string };
  role: Role;
  status: "active" | "deactivated";
  all_locations: boolean;
  location_ids: number[];
  created_at: string;
}

export interface Invitation {
  id: number;
  email: string;
  role: Role;
  status: "pending" | "accepted" | "expired" | "revoked";
  expires_at: string;
  created_at: string;
}

export interface Metrics {
  enrollments: number;
  active_customers: number;
  points_issued: number;
  points_redeemed: number;
  rewards_redeemed: number;
  referrals: number;
  qualified_referrals: number;
}

export interface SeriesPoint {
  date: string;
  points_issued: number;
  points_redeemed: number;
  enrollments: number;
}

export interface AuditEntry {
  id: number;
  action: string;
  actor: string;
  target_type: string | null;
  target_id: number | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface Meta {
  app_name: string;
  demo_mode: boolean;
  demo_seeded: boolean;
  dev_mailbox: boolean;
}
