import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  CreditCard,
  Gift,
  LayoutDashboard,
  LogOut,
  MapPin,
  Megaphone,
  Menu,
  ScanLine,
  Settings,
  ShoppingBag,
  Share2,
  ShieldCheck,
  UserCircle,
  Users,
  UsersRound,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";
import type { Envelope, SessionInfo } from "../api/types";
import { Alert, Avatar, EmptyState } from "./ui";

type NavItem = { to: string; label: string; icon: typeof Users; perm?: string };

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: "Front desk",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard },
      { to: "/checkout", label: "Record purchase", icon: ShoppingBag, perm: "purchases.create" },
      { to: "/redemptions", label: "Validate redemption", icon: ScanLine, perm: "redemptions.complete" },
      { to: "/customers", label: "Customers", icon: Users, perm: "customers.view" },
    ],
  },
  {
    section: "Program",
    items: [
      { to: "/rewards", label: "Rewards", icon: Gift, perm: "rewards.view" },
      { to: "/referrals", label: "Referrals", icon: Share2, perm: "referrals.view" },
      { to: "/promotions", label: "Promotions", icon: Megaphone, perm: "promotions.view" },
      { to: "/analytics", label: "Analytics & exports", icon: BarChart3, perm: "analytics.view" },
      { to: "/settings/program", label: "Program settings", icon: Settings, perm: "program.manage" },
    ],
  },
  {
    section: "Business",
    items: [
      { to: "/locations", label: "Locations", icon: MapPin, perm: "locations.view" },
      { to: "/team", label: "Staff & permissions", icon: UsersRound, perm: "members.view" },
      { to: "/audit", label: "Audit log", icon: ShieldCheck, perm: "audit.view" },
      { to: "/settings/billing", label: "Billing", icon: CreditCard, perm: "billing.manage" },
      { to: "/account", label: "Account & privacy", icon: UserCircle },
    ],
  },
];

export function AppLayout() {
  const { session, meta, can, signOut, setSession } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => setOpen(false), [location.pathname]);

  if (!session) return null;
  const business = session.active_business;

  async function switchBusiness(id: number) {
    const res = await api<Envelope<SessionInfo>>("/auth/switch-business", { method: "POST", body: { business_id: id } });
    setSession(res.data);
    navigate("/");
  }

  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Main navigation">
        <Link className="brand" to="/">
          <BrandMark />
          {meta?.app_name ?? "LoyalLoop"}
        </Link>
        <nav className="nav">
          {NAV.map((group) => {
            const items = group.items.filter((i) => !i.perm || can(i.perm));
            if (!items.length) return null;
            return (
              <div key={group.section}>
                <div className="nav-section">{group.section}</div>
                {items.map(({ to, label, icon: Icon }) => (
                  <NavLink key={to} to={to} end={to === "/"} className="nav-link">
                    <Icon size={18} aria-hidden="true" />
                    {label}
                  </NavLink>
                ))}
              </div>
            );
          })}
          {session.user.is_platform_admin && (
            <div>
              <div className="nav-section">Platform</div>
              <NavLink to="/admin" className="nav-link">
                <ShieldCheck size={18} aria-hidden="true" />
                Platform admin
              </NavLink>
            </div>
          )}
        </nav>
        <div className="sidebar-footer">
          <Avatar name={session.user.display_name} />
          <div className="who">
            <strong>{session.user.display_name}</strong>
            <span>{session.role}</span>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="Sign out"
            title="Sign out"
            onClick={() => signOut().then(() => navigate("/signin"))}
          >
            <LogOut size={18} aria-hidden="true" />
          </button>
        </div>
      </aside>
      {open && <div className="sidebar-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />}
      <div className="main-col">
        <header className="topbar">
          <button
            type="button"
            className="icon-button menu-button"
            aria-label="Open navigation"
            aria-expanded={open}
            onClick={() => setOpen(true)}
          >
            <Menu size={20} />
          </button>
          <span className="business-name">{business?.name}</span>
          {business?.is_demo && (
            <span className="demo-pill" title="All customers, transactions and analytics here are sample data.">
              Demo data
              <span className="visually-hidden">Demo business — all customers, transactions and analytics here are sample data.</span>
            </span>
          )}
          <div className="topbar-spacer" />
          {session.businesses.length > 1 && (
            <label className="row small">
              <span className="visually-hidden">Switch business</span>
              <select
                className="select"
                value={business?.id}
                onChange={(e) => switchBusiness(Number(e.target.value))}
                style={{ minHeight: 36, width: "auto" }}
              >
                {session.businesses.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </header>
        <main id="main" className="content" tabIndex={-1}>
          <BillingBanner />
          {!session.user.email_verified && !meta?.demo_mode && (
            <div style={{ marginBottom: 16 }}>
              <Alert kind="warning">
                Please verify your email address. Some actions (like inviting staff) are unavailable until you do.{" "}
                <Link to="/account">Resend verification</Link>
              </Alert>
            </div>
          )}
          {!session.user.email_verified && meta?.demo_mode && (
            <div style={{ marginBottom: 16 }}>
              <Alert kind="warning">
                Your email is not verified yet. In local demo mode, open the <Link to="/dev/mailbox">dev mailbox</Link> to find the
                verification link.
              </Alert>
            </div>
          )}
          {business?.suspended ? (
            <EmptyState
              icon={<ShieldCheck size={28} aria-hidden="true" />}
              title="This business account is suspended"
              description="Access is paused and no data has been deleted. Please contact support to resolve this."
            />
          ) : session.mfa_setup_required && location.pathname !== "/account" ? (
            <EmptyState
              icon={<ShieldCheck size={28} aria-hidden="true" />}
              title="Two-factor authentication required"
              description={`${business?.name} requires owners and managers to use two-factor authentication. Set it up to continue.`}
              action={
                <Link className="btn btn-primary" to="/account">
                  Set up two-factor
                </Link>
              }
            />
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </div>
  );
}

function BillingBanner() {
  const { session, can } = useAuth();
  const billing = session?.billing;
  if (!billing || session?.active_business?.is_demo) return null;
  const link = can("billing.manage") ? (
    <>
      {" "}
      <Link to="/settings/billing">Go to Billing</Link>
    </>
  ) : (
    " Ask the business owner to update billing."
  );
  let content: { kind: "warning" | "error"; text: string } | null = null;
  if (billing.status === "trial_expired") {
    content = { kind: "error", text: "Your free trial has ended. The account is read-only until a plan is chosen." };
  } else if (billing.status === "canceled") {
    content = { kind: "error", text: "Your subscription is cancelled. The account is read-only." };
  } else if (billing.status === "past_due") {
    content = { kind: "warning", text: "Your last payment failed. Update your payment details to avoid interruption." };
  } else if (billing.status === "trialing" && billing.trial_ends_at) {
    const days = Math.ceil((new Date(billing.trial_ends_at).getTime() - Date.now()) / 86_400_000);
    if (days <= 5) content = { kind: "warning", text: `Your free trial ends in ${days} day${days === 1 ? "" : "s"}.` };
  }
  if (!content) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <Alert kind={content.kind}>
        {content.text}
        {link}
      </Alert>
    </div>
  );
}

export function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg width="16" height="16" viewBox="0 0 16 16">
        <circle cx="8" cy="8" r="5" fill="none" stroke="#fff" strokeWidth="2.4" />
        <circle cx="8" cy="3" r="1.6" fill="#fff" />
      </svg>
    </span>
  );
}
