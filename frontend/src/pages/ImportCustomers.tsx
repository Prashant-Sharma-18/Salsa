import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileUp, Upload } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { Envelope } from "../api/types";
import { Alert, Button, Card, Checkbox, PageHeader, StatCard } from "../components/ui";
import { formatNumber, MONTHS } from "../lib/format";

interface ImportResult {
  summary: { rows: number; create: number; skip: number; error: number; opening_points: number; marketing_opt_ins: number };
  errors: { line: number; name: string | null; errors: string[] }[];
  skipped: { line: number; name: string; reason: string }[];
  sample: {
    display_name: string;
    email: string | null;
    phone: string | null;
    birth_month: number | null;
    birth_day: number | null;
    points: number;
    marketing_opt_in: boolean;
  }[];
  unknown_columns: string[];
  limit: { limit: number | null; current: number; over_limit: boolean };
  imported: boolean;
}

const TEMPLATE = "name,email,phone,birthday,points,marketing\nAva Thompson,ava@example.com,(503) 555-0101,03-14,250,yes\nLiam Carter,liam@example.com,,,0,no\n";

function downloadTemplate() {
  const url = URL.createObjectURL(new Blob([TEMPLATE], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "customer-import-template.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export function ImportCustomersPage() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [csv, setCsv] = useState<string | null>(null);
  const [importPoints, setImportPoints] = useState(true);
  const [importConsent, setImportConsent] = useState(false);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [done, setDone] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);
  const [dragging, setDragging] = useState(false);

  async function readFile(file: File) {
    setError(null);
    setPreview(null);
    setDone(null);
    if (file.size > 2_000_000) {
      setError("That file is larger than 2 MB. Split it into smaller files.");
      return;
    }
    setFileName(file.name);
    setCsv(await file.text());
  }

  async function send(dryRun: boolean) {
    if (!csv) return;
    setBusy(dryRun ? "preview" : "import");
    setError(null);
    try {
      const res = await api<Envelope<ImportResult>>("/customers/import", {
        method: "POST",
        body: { csv, dry_run: dryRun, import_points: importPoints, import_consent: importConsent },
      });
      if (dryRun) setPreview(res.data);
      else {
        setDone(res.data);
        setPreview(null);
        qc.invalidateQueries({ queryKey: ["customers"] });
        qc.invalidateQueries({ queryKey: ["dashboard"] });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Import failed");
    } finally {
      setBusy(null);
    }
  }

  function reset() {
    setCsv(null);
    setFileName(null);
    setPreview(null);
    setDone(null);
    setError(null);
    if (input.current) input.current.value = "";
  }

  if (done) {
    return (
      <>
        <PageHeader title="Import customers" />
        <Card>
          <div className="empty-state" style={{ padding: "24px 0" }}>
            <CheckCircle2 size={28} aria-hidden="true" />
            <h3>Imported {formatNumber(done.summary.create)} customers</h3>
            <p>
              {done.summary.skip > 0 && `${done.summary.skip} skipped as duplicates. `}
              {done.summary.opening_points > 0 && `${formatNumber(done.summary.opening_points)} opening points added. `}
              Everything is recorded in the audit log.
            </p>
            <div className="row" style={{ justifyContent: "center", marginTop: 20 }}>
              <Link className="btn btn-primary" to="/customers">
                View customers
              </Link>
              <Button onClick={reset}>Import another file</Button>
            </div>
          </div>
        </Card>
      </>
    );
  }

  const canImport = preview && preview.summary.error === 0 && preview.summary.create > 0 && !preview.limit.over_limit;

  return (
    <>
      <PageHeader
        title="Import customers"
        description="Bring your existing customer list over from a spreadsheet or another loyalty tool."
        actions={
          <Button onClick={downloadTemplate}>
            <Download size={16} aria-hidden="true" /> Download template
          </Button>
        }
      />
      <div className="grid grid-sidebar">
        <div className="stack">
          <Card title="1. Choose a CSV file">
            <div
              className={`dropzone ${dragging ? "dragging" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const file = e.dataTransfer.files[0];
                if (file) readFile(file);
              }}
            >
              <span className="icon-tile" aria-hidden="true">
                <FileUp size={20} />
              </span>
              <div>
                <strong>{fileName ?? "Drop a .csv file here"}</strong>
                <div className="muted small">{fileName ? "Choose another file to replace it" : "or browse your computer · up to 5,000 rows"}</div>
              </div>
              <label className="btn" htmlFor="import-file">
                Browse
              </label>
              <input
                ref={input}
                id="import-file"
                type="file"
                accept=".csv,text/csv"
                className="visually-hidden"
                onChange={(e) => e.target.files?.[0] && readFile(e.target.files[0])}
              />
            </div>
            <div className="stack" style={{ marginTop: 20, gap: 12 }}>
              <Checkbox
                label="Import opening points balances"
                hint="Uses the 'points' column. Each balance is added as an audited adjustment."
                checked={importPoints}
                onChange={(e) => {
                  setImportPoints(e.target.checked);
                  setPreview(null);
                }}
              />
              <Checkbox
                label="These customers agreed to receive marketing emails"
                hint="Only tick this if you collected their consent. Without it, everyone is imported as not opted in."
                checked={importConsent}
                onChange={(e) => {
                  setImportConsent(e.target.checked);
                  setPreview(null);
                }}
              />
            </div>
            {error && (
              <div style={{ marginTop: 16 }}>
                <Alert kind="error">{error}</Alert>
              </div>
            )}
            <div className="form-actions" style={{ marginTop: 20 }}>
              <Button variant="primary" disabled={!csv} loading={busy === "preview"} onClick={() => send(true)}>
                Preview import
              </Button>
            </div>
          </Card>

          {preview && (
            <Card title="2. Review">
              <div className="stats-grid" style={{ marginBottom: 20 }}>
                <StatCard label="Will be added" value={formatNumber(preview.summary.create)} tone="green" />
                <StatCard label="Skipped" value={formatNumber(preview.summary.skip)} hint="Already customers or duplicates" tone="amber" />
                <StatCard label="Need fixing" value={formatNumber(preview.summary.error)} tone="rose" />
              </div>
              <div className="stack" style={{ gap: 12 }}>
                {preview.unknown_columns.length > 0 && (
                  <Alert kind="info">Ignored columns: {preview.unknown_columns.join(", ")}.</Alert>
                )}
                {preview.limit.over_limit && (
                  <Alert kind="error">
                    This would bring you to {formatNumber(preview.limit.current + preview.summary.create)} customers, above your plan's limit of{" "}
                    {formatNumber(preview.limit.limit)}. <Link to="/settings/billing">Upgrade</Link> or import fewer rows.
                  </Alert>
                )}
                {preview.summary.error > 0 && (
                  <Alert kind="warning">Fix these rows in your spreadsheet and choose the file again. Nothing is imported until every row is valid.</Alert>
                )}
              </div>

              {preview.errors.length > 0 && (
                <div className="table-wrap" style={{ marginTop: 16 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Row</th>
                        <th>Name</th>
                        <th>Problem</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.errors.map((e) => (
                        <tr key={e.line}>
                          <td className="mono">{e.line}</td>
                          <td>{e.name ?? "—"}</td>
                          <td className="text-danger small">{e.errors.join(" · ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {preview.sample.length > 0 && preview.summary.error === 0 && (
                <>
                  <h3 style={{ margin: "20px 0 8px" }}>First customers to be added</h3>
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Contact</th>
                          <th>Birthday</th>
                          <th className="num">Points</th>
                          <th>Marketing</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.sample.map((r, i) => (
                          <tr key={i}>
                            <td>{r.display_name}</td>
                            <td className="small">
                              {r.email ?? "—"}
                              {r.phone && <div className="muted">{r.phone}</div>}
                            </td>
                            <td className="small">{r.birth_month && r.birth_day ? `${MONTHS[r.birth_month - 1]} ${r.birth_day}` : "—"}</td>
                            <td className="num">{formatNumber(r.points)}</td>
                            <td className="small">{r.marketing_opt_in ? "Opted in" : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}

              {preview.skipped.length > 0 && (
                <details className="small" style={{ marginTop: 16 }}>
                  <summary>Show {preview.skipped.length} skipped rows</summary>
                  <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                    {preview.skipped.map((s) => (
                      <li key={s.line}>
                        Row {s.line} · {s.name} — {s.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              <div className="form-actions" style={{ marginTop: 20 }}>
                <Button onClick={reset}>Start over</Button>
                <Button variant="primary" disabled={!canImport} loading={busy === "import"} onClick={() => send(false)}>
                  <Upload size={16} aria-hidden="true" /> Import {formatNumber(preview.summary.create)} customers
                </Button>
              </div>
            </Card>
          )}
        </div>

        <Card title="File format">
          <p className="small muted" style={{ marginBottom: 12 }}>
            Export from Excel, Google Sheets, Square, Shopify or another loyalty tool as CSV. Column names are matched automatically.
          </p>
          <ul className="rules small">
            <li>
              <strong>name</strong> (or first name + last name) — required
            </li>
            <li>
              <strong>email</strong> and/or <strong>phone</strong> — at least one
            </li>
            <li>
              <strong>birthday</strong> — optional, e.g. 03-14 or 1990-03-14 (the year is ignored)
            </li>
            <li>
              <strong>points</strong> — optional opening balance
            </li>
            <li>
              <strong>marketing</strong> — optional yes / no
            </li>
          </ul>
          <p className="small muted" style={{ marginTop: 12 }}>
            Existing customers (same email) are never changed. The whole file is imported in one go, or not at all.
          </p>
        </Card>
      </div>
    </>
  );
}
