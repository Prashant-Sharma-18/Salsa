import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { AuditEntry, Paged } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Avatar, Card, EmptyState, PageHeader, Pagination, QueryState } from "../components/ui";
import { formatDateTime } from "../lib/format";

const FILTERS = [
  ["", "All actions"],
  ["points", "Points adjustments, reversals, expiry"],
  ["redemption", "Redemptions"],
  ["member", "Team and roles"],
  ["export", "Exports"],
  ["customer", "Customer records"],
  ["program", "Program settings"],
];

export function AuditLogPage() {
  const { session } = useAuth();
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["audit", action, page],
    queryFn: () => api<Paged<AuditEntry>>(`/audit-logs${qs({ action, page })}`),
  });

  return (
    <>
      <PageHeader title="Audit log" description="A permanent record of sensitive actions in this business." />
      <Card bodyless>
        <div className="toolbar">
          <div className="field">
            <label htmlFor="audit-filter">Show</label>
            <select id="audit-filter" className="select" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
              {FILTERS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>
        </div>
        <QueryState isLoading={query.isLoading} error={query.error}>
          {query.data?.data.length === 0 ? (
            <EmptyState title="No matching audit entries" />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Who</th>
                    <th>Action</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data?.data.map((a) => (
                    <tr key={a.id}>
                      <td className="small muted" style={{ whiteSpace: "nowrap" }}>{formatDateTime(a.created_at, session?.user.timezone)}</td>
                      <td>
                        <div className="person">
                          <Avatar name={a.actor} size="sm" />
                          <span>{a.actor}</span>
                        </div>
                      </td>
                      <td>
                        <div style={{ fontWeight: 550 }}>{describeAction(a.action)}</div>
                        <div className="muted small mono">{a.action}</div>
                      </td>
                      <td className="small">
                        {a.target_type && (
                          <div>
                            {humanize(a.target_type)} #{a.target_id}
                          </div>
                        )}
                        {detailText(a.details) && <div className="muted">{detailText(a.details)}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {query.data && query.data.meta.total > 0 && (
            <Pagination page={query.data.meta.page} pages={query.data.meta.pages} total={query.data.meta.total} onPage={setPage} />
          )}
        </QueryState>
      </Card>
    </>
  );
}

const ACTION_LABELS: Record<string, string> = {
  "points.adjusted": "Adjusted points",
  "points.reversed": "Reversed a ledger entry",
  "points.expired": "Expired inactive balances",
  "points.birthday_bonuses": "Awarded birthday bonuses",
  "redemption.issued": "Issued a reward code",
  "redemption.completed": "Completed a redemption",
  "redemption.cancelled": "Cancelled a redemption",
  "customer.enrolled": "Enrolled a customer",
  "customer.updated": "Updated a customer",
  "customer.anonymized": "Deleted a customer's personal data",
  "customer.data_exported": "Exported a customer's data",
  "customers.imported": "Imported customers from CSV",
  "export.customers": "Exported customers (CSV)",
  "export.ledger": "Exported the ledger (CSV)",
  "member.invited": "Invited a team member",
  "member.joined": "Joined the team",
  "member.updated": "Changed a team member",
  "member.invitation_revoked": "Revoked an invitation",
  "program.updated": "Changed program settings",
  "reward.created": "Added a reward",
  "reward.updated": "Updated a reward",
  "reward.deleted": "Deleted a reward",
  "promotion.created": "Created a promotion",
  "promotion.updated": "Updated a promotion",
  "referral.rejected": "Rejected a referral",
  "location.created": "Added a location",
  "location.updated": "Updated a location",
  "business.created": "Created the business",
  "business.updated": "Updated business details",
  "business.require_mfa_changed": "Changed the two-factor requirement",
  "billing.plan_changed": "Plan changed",
  "admin.business_suspended": "Platform admin suspended the business",
  "admin.business_unsuspended": "Platform admin reinstated the business",
  "admin.plan_changed": "Platform admin changed the plan",
  "admin.trial_extended": "Platform admin extended the trial",
};

function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function describeAction(action: string): string {
  return ACTION_LABELS[action] ?? humanize(action.split(".").pop() ?? action);
}

/** Readable detail line; internal id fields are hidden. */
function detailText(details: Record<string, unknown>): string {
  return Object.entries(details)
    .filter(([k, v]) => !k.endsWith("_id") && v !== null && v !== "" && !(typeof v === "object" && !Array.isArray(v)))
    .map(([k, v]) => `${humanize(k)}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
    .join(" · ");
}
