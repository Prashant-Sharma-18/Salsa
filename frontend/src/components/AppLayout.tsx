import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Gift,
  LayoutDashboard,
  LogOut,
  MapPin,
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
import { Alert, Button } from "./ui";

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
        <a className="brand" href="/">
          <span className="brand-mark" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 14 14">
              <circle cx="7" cy="7" r="4.5" fill="none" stroke="#fff" strokeWidth="2" />
            </svg>
          </span>
          {meta?.app_name ?? "LoyalLoop"}
        </a>
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
        </nav>
        <div className="sidebar-footer">
          <div style={{ fontWeight: 500 }}>{session.user.display_name}</div>
          <div className="muted small" style={{ textTransform: "capitalize" }}>
            {session.role} · {business?.name}
          </div>
          <Button size="sm" variant="ghost" onClick={() => signOut().then(() => navigate("/signin"))} style={{ marginTop: 8, paddingLeft: 0 }}>
            <LogOut size={16} aria-hidden="true" /> Sign out
          </Button>
        </div>
      </aside>
      {open && <div className="sidebar-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />}
      <div className="main-col">
        {business?.is_demo && (
          <div className="demo-banner">Demo business — all customers, transactions and analytics here are sample data.</div>
        )}
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
          <strong>{business?.name}</strong>
          <div className="topbar-spacer" />
          {session.businesses.length > 1 && (
            <label className="row small">
              <span className="visually-hidden">Switch business</span>
              <select
                className="select"
                value={business?.id}
                onChange={(e) => switchBusiness(Number(e.target.value))}
                style={{ minHeight: 32, width: "auto" }}
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
          {!session.user.email_verified && !meta?.demo_mode && (
            <div style={{ marginBottom: 16 }}>
              <Alert kind="warning">
                Please verify your email address. Some actions (like inviting staff) are unavailable until you do.{" "}
                <a href="/account">Resend verification</a>
              </Alert>
            </div>
          )}
          {!session.user.email_verified && meta?.demo_mode && (
            <div style={{ marginBottom: 16 }}>
              <Alert kind="warning">
                Your email is not verified yet. In local demo mode, open the <a href="/dev/mailbox">dev mailbox</a> to find the
                verification link.
              </Alert>
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
