import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Coins, Download, Gift, ScanLine, Share2, UserPlus, Users } from "lucide-react";
import { api, downloadFile, qs } from "../api/client";
import type { Envelope, Metrics, SeriesPoint } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PointsChart } from "../components/BarChart";
import { defaultRange, RangeFilter, type RangeValue } from "../components/Filters";
import { Alert, Button, Card, PageHeader, QueryState, StatCard, type Tone } from "../components/ui";
import { formatNumber } from "../lib/format";

interface AnalyticsData {
  range: { start: string; end: string; timezone: string };
  metrics: Metrics;
  series: SeriesPoint[];
  definitions: Record<keyof Metrics, string>;
}

const STAT_ICONS: Record<keyof Metrics, [typeof Users, Tone]> = {
  enrollments: [UserPlus, "blue"],
  active_customers: [Users, "violet"],
  points_issued: [Coins, "green"],
  points_redeemed: [Gift, "amber"],
  rewards_redeemed: [ScanLine, "rose"],
  referrals: [Share2, "blue"],
  qualified_referrals: [Share2, "green"],
};

const LABELS: Record<keyof Metrics, string> = {
  enrollments: "Enrollments",
  active_customers: "Active customers",
  points_issued: "Points issued",
  points_redeemed: "Points redeemed",
  rewards_redeemed: "Rewards redeemed",
  referrals: "Referred sign-ups",
  qualified_referrals: "Qualified referrals",
};

export function AnalyticsPage() {
  const { can, session } = useAuth();
  const [range, setRange] = useState<RangeValue>(defaultRange());
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["analytics", range],
    queryFn: async () => (await api<Envelope<AnalyticsData>>(`/analytics/summary${qs({ ...range })}`)).data,
  });
  const data = query.data;
  const slug = session?.active_business?.slug ?? "business";

  async function exportCsv(kind: "customers" | "ledger") {
    setExportError(null);
    setExporting(kind);
    try {
      if (kind === "customers") await downloadFile("/exports/customers.csv", `customers-${slug}.csv`);
      else await downloadFile(`/exports/ledger.csv${qs({ ...range })}`, `ledger-${slug}-${range.start}-${range.end}.csv`);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Analytics & exports"
        description={data ? `Dates are in ${data.range.timezone}. Metrics are calculated from recorded transactions.` : undefined}
        actions={
          can("exports.run") && (
            <>
              <Button loading={exporting === "customers"} onClick={() => exportCsv("customers")}>
                <Download size={16} aria-hidden="true" /> Customers CSV
              </Button>
              <Button loading={exporting === "ledger"} onClick={() => exportCsv("ledger")}>
                <Download size={16} aria-hidden="true" /> Ledger CSV (range)
              </Button>
            </>
          )
        }
      />
      {exportError && (
        <div style={{ marginBottom: 16 }}>
          <Alert kind="error">{exportError}</Alert>
        </div>
      )}
      <RangeFilter value={range} onChange={setRange} />
      <QueryState isLoading={query.isLoading} error={query.error}>
        {data && (
          <>
            {session?.active_business?.is_demo && (
              <div style={{ marginBottom: 16 }}>
                <Alert kind="warning">These figures come from sample demo data.</Alert>
              </div>
            )}
            <div className="stats-grid">
              {(Object.keys(LABELS) as (keyof Metrics)[]).slice(0, 5).map((k) => {
                const [Icon, tone] = STAT_ICONS[k];
                return <StatCard key={k} label={LABELS[k]} value={formatNumber(data.metrics[k])} icon={<Icon size={18} />} tone={tone} />;
              })}
            </div>
            <div className="grid grid-sidebar">
              <Card title="Points per day">
                {data.series.every((d) => !d.points_issued && !d.points_redeemed) ? (
                  <p className="muted">No points activity in this range.</p>
                ) : (
                  <PointsChart series={data.series} />
                )}
              </Card>
              <Card title="Referrals">
                <dl className="dl">
                  <dt>{LABELS.referrals}</dt>
                  <dd>{formatNumber(data.metrics.referrals)}</dd>
                  <dt>{LABELS.qualified_referrals}</dt>
                  <dd>{formatNumber(data.metrics.qualified_referrals)}</dd>
                </dl>
              </Card>
            </div>
            <div style={{ marginTop: 16 }}>
              <Card title="How each metric is calculated">
                <dl className="dl">
                  {(Object.keys(LABELS) as (keyof Metrics)[]).map((k) => (
                    <div key={k} style={{ display: "contents" }}>
                      <dt>{LABELS[k]}</dt>
                      <dd>{data.definitions[k]}</dd>
                    </div>
                  ))}
                </dl>
              </Card>
            </div>
          </>
        )}
      </QueryState>
    </>
  );
}
