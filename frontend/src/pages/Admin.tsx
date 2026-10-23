import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { api, ApiError, qs } from "../api/client";
import type { AuditEntry, BillingSummary, Business, Envelope, Paged } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, Button, Card, EmptyState, Loading, Modal, PageHeader, Pagination, QueryState, Select, StatCard, Status, TextInput } from "../components/ui";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "../lib/format";
import { TwoFactorCard } from "./TwoFactor";

interface AdminRow extends Business {
  created_at: string;
  billing: BillingSummary;
  suspended: boolean;
  suspended_reason: string | null;
  members: number;
  customers: number;
  owner_email: string | null;
}

interface AdminDetail extends AdminRow {
  owners: { name: string; email: string; status: string }[];
  limits: Record<string, number | null>;
  usage: Record<string, number>;
  history: AuditEntry[];
}

interface Overview {
  businesses: number;
  by_status: Record<string, number>;
  active_last_30_days: number;
  users: number;
  customers: number;
  mrr_cents: number;
}

const STATUS_LABELS: Record<string, string> = {
  trialing: "Trial",
  trial_expired: "Trial ended",
  active: "Active",
  past_due: "Past due",
  canceled: "Cancelled",
  suspended: "Suspended",
};

function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function AdminPage() {
  const { session, signOut } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);
  const debounced = useDebounced(q);
  const overview = useQuery({
    queryKey: ["admin-overview"],
    queryFn: async () => (await api<Envelope<Overview>>("/admin/overview")).data,
    retry: false,
  });
  const list = useQuery({
    queryKey: ["admin-businesses", debounced, status, page],
    queryFn: () => api<Paged<AdminRow>>(`/admin/businesses${qs({ q: debounced, status, page })}`),
    placeholderData: keepPreviousData,
    retry: false,
  });
  useEffect(() => setPage(1), [debounced, status]);

  if (!session) return <Navigate to="/signin" replace />;
  if (!session.user.is_platform_admin)
    return (
      <main className="content">
        <EmptyState title="Platform admins only" description="This area is for the people who operate LoyalLoop." action={<Link className="btn" to="/">Go home</Link>} />
      </main>
    );

  const mfaRequired = overview.error instanceof ApiError && overview.error.code === "admin_mfa_required";

  return (
    <div className="admin-shell">
      <header className="topbar">
        <strong>LoyalLoop · Platform admin</strong>
        <div className="topbar-spacer" />
        {session.active_business && (
          <Link className="btn btn-sm" to="/">
            Back to {session.active_business.name}
          </Link>
        )}
        <Button size="sm" variant="ghost" onClick={() => signOut().then(() => navigate("/signin"))}>
          <LogOut size={16} aria-hidden="true" /> Sign out
        </Button>
      </header>
      <main id="main" className="content">
        <PageHeader
          title="Platform admin"
          description="Business-level metadata only. Customer records are never shown here. Every action is audit-logged."
        />
        {mfaRequired ? (
          <div className="stack" style={{ maxWidth: 560 }}>
            <Alert kind="warning" title="Two-factor required">
              Platform administrators must turn on two-factor authentication before using this console.
            </Alert>
            <TwoFactorCard />
          </div>
        ) : (
          <>
            {overview.data && (
              <div className="stats-grid">
                <StatCard label="Businesses" value={formatNumber(overview.data.businesses)} hint={`${overview.data.active_last_30_days} active in 30 days`} />
                <StatCard label="Monthly recurring revenue" value={formatMoney(overview.data.mrr_cents)} hint="Active + past-due paid plans" />
                <StatCard label="On trial" value={formatNumber(overview.data.by_status.trialing ?? 0)} hint={`${overview.data.by_status.trial_expired ?? 0} expired`} />
                <StatCard label="Merchant users" value={formatNumber(overview.data.users)} />
                <StatCard label="End customers" value={formatNumber(overview.data.customers)} hint="Across all businesses" />
              </div>
            )}
            <Card bodyless>
              <div className="toolbar">
                <div className="field grow">
                  <label htmlFor="admin-q">Search</label>
                  <input id="admin-q" className="input" type="search" placeholder="Business name, slug or owner email" value={q} onChange={(e) => setQ(e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="admin-status">Status</label>
                  <select id="admin-status" className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
                    <option value="">All</option>
                    {Object.entries(STATUS_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <QueryState isLoading={list.isLoading} error={list.error}>
                {list.data?.data.length === 0 ? (
                  <EmptyState title="No businesses match" />
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Business</th>
                          <th>Owner</th>
                          <th>Plan</th>
                          <th className="num">Customers</th>
                          <th className="num">Team</th>
                          <th>Created</th>
                          <th>
                            <span className="visually-hidden">Actions</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {list.data?.data.map((b) => (
                          <tr key={b.id}>
                            <td>
                              <strong>{b.name}</strong>
                              {b.is_demo && <span className="tag" style={{ marginLeft: 8 }}>Demo</span>}
                              <div className="muted small mono">{b.slug}</div>
                            </td>
                            <td className="small">{b.owner_email ?? "—"}</td>
                            <td>
                              {b.billing.plan_name}
                              <div>
                                <Status value={b.suspended ? "revoked" : b.billing.status} label={b.suspended ? "Suspended" : STATUS_LABELS[b.billing.status]} />
                              </div>
                            </td>
                            <td className="num">{formatNumber(b.customers)}</td>
                            <td className="num">{b.members}</td>
                            <td className="small muted">{formatDate(b.created_at)}</td>
                            <td className="num">
                              <Button size="sm" onClick={() => setSelected(b.id)} aria-label={`Manage ${b.name}`}>
                                Manage
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {list.data && list.data.meta.total > 0 && (
                  <Pagination page={list.data.meta.page} pages={list.data.meta.pages} total={list.data.meta.total} onPage={setPage} />
                )}
              </QueryState>
            </Card>
          </>
        )}
      </main>
      <Modal open={selected !== null} title="Manage business" onClose={() => setSelected(null)}>
        {selected !== null && <BusinessAdmin id={selected} />}
      </Modal>
    </div>
  );
}

function BusinessAdmin({ id }: { id: number }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [plan, setPlan] = useState("starter");
  const [days, setDays] = useState("14");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const detail = useQuery({
    queryKey: ["admin-business", id],
    queryFn: async () => (await api<Envelope<AdminDetail>>(`/admin/businesses/${id}`)).data,
  });

  async function act(key: string, path: string, body: Record<string, unknown>, done: string) {
    if (reason.trim().length < 5) {
      setMessage({ kind: "error", text: "Enter a reason (at least 5 characters). It is recorded in the audit log." });
      return;
    }
    setBusy(key);
    setMessage(null);
    try {
      await api(path, { method: "POST", body: { ...body, reason } });
      setMessage({ kind: "success", text: done });
      setReason("");
      qc.invalidateQueries({ queryKey: ["admin-business", id] });
      qc.invalidateQueries({ queryKey: ["admin-businesses"] });
      qc.invalidateQueries({ queryKey: ["admin-overview"] });
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : "Action failed" });
    } finally {
      setBusy(null);
    }
  }

  if (detail.isLoading) return <Loading />;
  if (detail.error) return <Alert kind="error">{(detail.error as Error).message}</Alert>;
  const b = detail.data!;

  return (
    <div className="stack">
      <div>
        <h3>{b.name}</h3>
        <p className="muted small">
          {b.billing.plan_name} · {b.suspended ? "Suspended" : STATUS_LABELS[b.billing.status]}
          {b.billing.trial_ends_at && b.billing.status === "trialing" && ` · trial ends ${formatDate(b.billing.trial_ends_at)}`}
        </p>
        {b.suspended && <Alert kind="error">Suspended: {b.suspended_reason}</Alert>}
      </div>
      <dl className="dl small">
        <dt>Owners</dt>
        <dd>{b.owners.map((o) => `${o.name} <${o.email}>`).join(", ") || "—"}</dd>
        {(["customers", "locations", "members"] as const).map((k) => (
          <div key={k} style={{ display: "contents" }}>
            <dt style={{ textTransform: "capitalize" }}>{k}</dt>
            <dd>
              {formatNumber(b.usage[k])} / {b.limits[k] === null ? "unlimited" : formatNumber(b.limits[k])}
            </dd>
          </div>
        ))}
      </dl>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      <TextInput label="Reason (required, audit-logged)" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="row">
        {b.suspended ? (
          <Button loading={busy === "unsuspend"} onClick={() => act("unsuspend", `/admin/businesses/${id}/unsuspend`, {}, "Business reinstated.")}>
            Reinstate business
          </Button>
        ) : (
          <Button variant="danger" loading={busy === "suspend"} onClick={() => act("suspend", `/admin/businesses/${id}/suspend`, {}, "Business suspended.")}>
            Suspend business
          </Button>
        )}
      </div>
      <div className="grid grid-2">
        <div className="stack">
          <Select label="Set plan" value={plan} onChange={(e) => setPlan(e.target.value)}>
            <option value="starter">Starter</option>
            <option value="growth">Growth</option>
            <option value="pro">Pro</option>
          </Select>
          <Button loading={busy === "plan"} onClick={() => act("plan", `/admin/businesses/${id}/plan`, { plan, status: "active" }, "Plan updated.")}>
            Apply plan
          </Button>
        </div>
        <div className="stack">
          <TextInput label="Extend trial (days)" type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} />
          <Button loading={busy === "trial"} onClick={() => act("trial", `/admin/businesses/${id}/plan`, { extend_trial_days: Number(days) }, "Trial extended.")}>
            Extend trial
          </Button>
        </div>
      </div>
      {b.history.length > 0 && (
        <div>
          <h3 style={{ marginBottom: 8 }}>Recent admin & billing activity</h3>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {b.history.map((h) => (
              <li key={h.id}>
                <span className="mono">{h.action}</span> by {h.actor} · {formatDateTime(h.created_at)}
                {typeof h.details.reason === "string" && <span className="muted"> — {h.details.reason}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
