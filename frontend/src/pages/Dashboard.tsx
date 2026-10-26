import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, Coins, Gift, ScanLine, Share2, ShoppingBag, UserPlus, Users } from "lucide-react";
import { api, qs } from "../api/client";
import type { Envelope, LedgerEntry, Metrics, SeriesPoint } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PointsChart } from "../components/BarChart";
import { defaultRange, RangeFilter, type RangeValue } from "../components/Filters";
import { Avatar, Card, EmptyState, PageHeader, QueryState, StatCard } from "../components/ui";
import { ENTRY_LABELS, formatDateTime, formatNumber, formatPoints } from "../lib/format";

interface DashboardData {
  range: { start: string; end: string };
  activity: LedgerEntry[];
  summary: Metrics | null;
  totals: { enrolled_customers: number } | null;
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function DashboardPage() {
  const { session, can } = useAuth();
  const [range, setRange] = useState<RangeValue>(defaultRange());
  const query = useQuery({
    queryKey: ["dashboard", range],
    queryFn: async () => (await api<Envelope<DashboardData>>(`/dashboard${qs({ ...range })}`)).data,
  });
  const series = useQuery({
    queryKey: ["analytics", range],
    queryFn: async () => (await api<Envelope<{ series: SeriesPoint[] }>>(`/analytics/summary${qs({ ...range })}`)).data,
    enabled: can("analytics.view"),
  });
  const tz = session?.user.timezone;
  const data = query.data;
  const firstName = session?.user.display_name.split(" ")[0];

  const actions = [
    can("purchases.create") && { to: "/checkout", icon: ShoppingBag, title: "Record purchase", sub: "Award points at checkout", tone: "" },
    can("redemptions.complete") && { to: "/redemptions", icon: ScanLine, title: "Validate code", sub: "Redeem a customer reward", tone: "green" },
    can("customers.create") && { to: "/customers/new", icon: UserPlus, title: "Enroll customer", sub: "Add someone to the program", tone: "violet" },
  ].filter(Boolean) as { to: string; icon: typeof Users; title: string; sub: string; tone: string }[];

  return (
    <>
      <PageHeader title={`${greeting()}, ${firstName}`} description={`Here's how ${session?.active_business?.name} is doing.`} />

      {actions.length > 0 && (
        <div className="quick-actions">
          {actions.map(({ to, icon: Icon, title, sub, tone }) => (
            <Link key={to} to={to} className="quick-action">
              <span className={`icon-tile ${tone}`} aria-hidden="true">
                <Icon size={18} />
              </span>
              <span className="qa-text">
                <strong>{title}</strong>
                <span>{sub}</span>
              </span>
            </Link>
          ))}
        </div>
      )}

      <RangeFilter value={range} onChange={setRange} />

      <QueryState isLoading={query.isLoading} error={query.error}>
        {data?.summary && data.totals && (
          <div className="stats-grid">
            <StatCard
              label="Enrolled customers"
              value={formatNumber(data.totals.enrolled_customers)}
              hint={`+${data.summary.enrollments} in this period`}
              icon={<Users size={18} />}
            />
            <StatCard
              label="Points issued"
              value={formatNumber(data.summary.points_issued)}
              hint="Purchases, bonuses & adjustments"
              icon={<Coins size={18} />}
              tone="green"
            />
            <StatCard
              label="Points redeemed"
              value={formatNumber(data.summary.points_redeemed)}
              hint="Net of refunds"
              icon={<Gift size={18} />}
              tone="amber"
            />
            <StatCard
              label="Rewards redeemed"
              value={formatNumber(data.summary.rewards_redeemed)}
              hint="Completed at the counter"
              icon={<ScanLine size={18} />}
              tone="violet"
            />
            <StatCard
              label="Referral conversions"
              value={formatNumber(data.summary.qualified_referrals)}
              hint={`${data.summary.referrals} referred sign-ups`}
              icon={<Share2 size={18} />}
              tone="rose"
            />
          </div>
        )}

        <div className={`grid ${can("analytics.view") ? "grid-sidebar" : ""}`}>
          {can("analytics.view") && (
            <Card title="Points activity" actions={<Link to="/analytics">View analytics</Link>}>
              {series.data && series.data.series.some((d) => d.points_issued || d.points_redeemed) ? (
                <PointsChart series={series.data.series} />
              ) : (
                <p className="muted">No points activity in this period yet.</p>
              )}
            </Card>
          )}
          <Card title="Recent activity" bodyless>
            {data && data.activity.length === 0 ? (
              <EmptyState
                icon={<Activity size={28} aria-hidden="true" />}
                title="No activity yet"
                description="Points awarded, redemptions and adjustments appear here as soon as you record your first purchase."
                action={
                  can("purchases.create") ? (
                    <Link className="btn btn-primary" to="/checkout">
                      Record a purchase
                    </Link>
                  ) : undefined
                }
              />
            ) : (
              <ul className="activity-list">
                {data?.activity.slice(0, can("analytics.view") ? 8 : 15).map((e) => (
                  <li key={e.id}>
                    <Avatar name={e.customer_name} size="sm" />
                    <div className="activity-main">
                      <div className="activity-title">
                        <Link to={`/customers/${e.customer_id}`}>{e.customer_name}</Link>
                      </div>
                      <div className="activity-sub" title={e.reason}>
                        {ENTRY_LABELS[e.entry_type]} · {formatDateTime(e.created_at, tz)}
                      </div>
                    </div>
                    <span className={`activity-points ${e.points > 0 ? "points-pos" : "points-neg"}`}>{formatPoints(e.points, true)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </QueryState>
    </>
  );
}
