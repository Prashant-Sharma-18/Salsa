import type { SeriesPoint } from "../api/types";
import { formatNumber } from "../lib/format";

/**
 * Simple accessible SVG bar chart (two series side by side per day).
 * A data table alternative is always rendered for screen readers.
 */
export function PointsChart({ series }: { series: SeriesPoint[] }) {
  const width = 720;
  const height = 220;
  const pad = { top: 12, right: 8, bottom: 28, left: 44 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...series.map((d) => Math.max(d.points_issued, d.points_redeemed)));
  const slot = innerW / Math.max(1, series.length);
  const barW = Math.max(1, Math.min(14, slot / 2 - 1));
  const labelEvery = Math.ceil(series.length / 8);

  return (
    <figure style={{ margin: 0 }}>
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Daily points issued and redeemed">
        {[0, 0.5, 1].map((t) => {
          const y = pad.top + innerH - innerH * t;
          return (
            <g key={t}>
              <line className="axis" x1={pad.left} x2={width - pad.right} y1={y} y2={y} />
              <text x={pad.left - 6} y={y + 4} textAnchor="end">
                {formatNumber(Math.round(max * t))}
              </text>
            </g>
          );
        })}
        {series.map((d, i) => {
          const x = pad.left + i * slot + slot / 2;
          const hA = (d.points_issued / max) * innerH;
          const hB = (Math.max(0, d.points_redeemed) / max) * innerH;
          return (
            <g key={d.date}>
              <rect className="bar-a" x={x - barW} y={pad.top + innerH - hA} width={barW} height={hA}>
                <title>{`${d.date}: ${d.points_issued} issued`}</title>
              </rect>
              <rect className="bar-b" x={x} y={pad.top + innerH - hB} width={barW} height={hB}>
                <title>{`${d.date}: ${d.points_redeemed} redeemed`}</title>
              </rect>
              {i % labelEvery === 0 && (
                <text x={x} y={height - 8} textAnchor="middle">
                  {d.date.slice(5)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="legend">
        <span className="a">Points issued</span>
        <span className="b">Points redeemed</span>
      </figcaption>
      <details className="small" style={{ marginTop: 8 }}>
        <summary>View as table</summary>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th className="num">Issued</th>
                <th className="num">Redeemed</th>
                <th className="num">Enrollments</th>
              </tr>
            </thead>
            <tbody>
              {series.map((d) => (
                <tr key={d.date}>
                  <td>{d.date}</td>
                  <td className="num">{formatNumber(d.points_issued)}</td>
                  <td className="num">{formatNumber(d.points_redeemed)}</td>
                  <td className="num">{d.enrollments}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
