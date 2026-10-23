import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { AuditEntry, Paged } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Card, EmptyState, PageHeader, Pagination, QueryState } from "../components/ui";
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
                      <td className="small muted">{formatDateTime(a.created_at, session?.user.timezone)}</td>
                      <td>{a.actor}</td>
                      <td className="mono small">{a.action}</td>
                      <td className="small">
                        {a.target_type && `${a.target_type} #${a.target_id}`}
                        {Object.keys(a.details).length > 0 && (
                          <div className="muted">
                            {Object.entries(a.details)
                              .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
                              .join(" · ")}
                          </div>
                        )}
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
