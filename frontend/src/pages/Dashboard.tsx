import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, ScanLine, ShoppingBag, UserPlus } from "lucide-react";
import { api, qs } from "../api/client";
import type { Envelope, LedgerEntry, Metrics } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { defaultRange, RangeFilter, type RangeValue } from "../components/Filters";
import { Card, EmptyState, PageHeader, QueryState, StatCard } from "../components/ui";
import { ENTRY_LABELS, formatDateTime, formatNumber, formatPoints } from "../lib/format";

interface DashboardData {
  range: { start: string; end: string };
  activity: LedgerEntry[];
  summary: Metrics | null;
  totals: { enrolled_customers: number } | null;
}

export function DashboardPage() {
  const { session, can } = useAuth();
  const [range, setRange] = useState<RangeValue>(defaultRange());
  const query = useQuery({
    queryKey: ["dashboard", range],
    queryFn: async () => (await api<Envelope<DashboardData>>(`/dashboard${qs({ ...range })}`)).data,
  });
  const tz = session?.user.timezone;
  const data = query.data;

  return (
    <>
      <PageHeader
        title={`Welcome, ${session?.user.display_name.split(" ")[0]}`}
        description="Program activity at a glance."
        actions={
          <>
            {can("customers.create") && (
              <Link className="btn" to="/customers/new">
                <UserPlus size={16} aria-hidden="true" /> Enroll customer
              </Link>
            )}
            {can("redemptions.complete") && (
              <Link className="btn" to="/redemptions">
                <ScanLine size={16} aria-hidden="true" /> Validate code
              </Link>
            )}
            {can("purchases.create") && (
              <Link className="btn btn-primary" to="/checkout">
                <ShoppingBag size={16} aria-hidden="true" /> Record purchase
              </Link>
            )}
          </>
        }
      />
      <Card bodyless className="" title={undefined}>
        <RangeFilter value={range} onChange={setRange} />
      </Card>
      <div style={{ height: 16 }} />
      <QueryState isLoading={query.isLoading} error={query.error}>
        {data?.summary && data.totals && (
          <div className="stats-grid">
            <StatCard label="Enrolled customers" value={formatNumber(data.totals.enrolled_customers)} hint={`${data.summary.enrollments} new in range`} />
            <StatCard label="Points issued" value={formatNumber(data.summary.points_issued)} hint="In selected range" />
            <StatCard label="Points redeemed" value={formatNumber(data.summary.points_redeemed)} hint="Net of refunds" />
            <StatCard label="Rewards redeemed" value={formatNumber(data.summary.rewards_redeemed)} hint="Completed by staff" />
            <StatCard label="Referral conversions" value={formatNumber(data.summary.qualified_referrals)} hint={`${data.summary.referrals} referred sign-ups`} />
          </div>
        )}
        <Card title="Recent activity" bodyless actions={can("analytics.view") ? <Link to="/analytics">Full analytics</Link> : undefined}>
          {data && data.activity.length === 0 ? (
            <EmptyState
              icon={<Activity size={28} aria-hidden="true" />}
              title="No activity yet"
              description="Points awarded, redemptions and adjustments will appear here as soon as you record your first purchase."
              action={
                can("purchases.create") ? (
                  <Link className="btn btn-primary" to="/checkout">
                    Record a purchase
                  </Link>
                ) : undefined
              }
            />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Customer</th>
                    <th>Activity</th>
                    <th className="num">Points</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.activity.map((e) => (
                    <tr key={e.id}>
                      <td className="muted small">{formatDateTime(e.created_at, tz)}</td>
                      <td>
                        <Link to={`/customers/${e.customer_id}`}>{e.customer_name}</Link>
                      </td>
                      <td>
                        {ENTRY_LABELS[e.entry_type]}
                        <div className="muted small">{e.reason}</div>
                      </td>
                      <td className={`num ${e.points > 0 ? "text-success" : ""}`}>{formatPoints(e.points, true)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </QueryState>
    </>
  );
}
