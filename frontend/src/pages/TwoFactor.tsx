import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { Envelope } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, Button, Card, TextInput } from "../components/ui";

interface MfaStatus {
  enabled: boolean;
  recovery_codes_remaining: number;
}

interface SetupData {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [saved, setSaved] = useState(false);
  function download() {
    const blob = new Blob([`LoyalLoop recovery codes\n\n${codes.join("\n")}\n\nEach code works once.\n`], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "loyalloop-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="stack">
      <Alert kind="warning" title="Save your recovery codes now">
        Each code lets you sign in once if you lose your phone. They won't be shown again.
      </Alert>
      <ul className="mono" style={{ columns: 2, margin: 0, paddingLeft: 18 }} aria-label="Recovery codes">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <div className="row">
        <Button onClick={download}>Download codes</Button>
        <Button onClick={() => navigator.clipboard?.writeText(codes.join("\n")).catch(() => undefined)}>Copy</Button>
      </div>
      <label className="checkbox">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        <span>I have saved these codes somewhere safe</span>
      </label>
      <div className="form-actions">
        <Button variant="primary" disabled={!saved} onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  );
}

export function TwoFactorCard() {
  const { session, refresh } = useAuth();
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["mfa-status"],
    queryFn: async () => (await api<Envelope<MfaStatus>>("/auth/mfa")).data,
  });
  const [setup, setSetup] = useState<SetupData | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [mode, setMode] = useState<null | "disable" | "regenerate">(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isDemo = session?.active_business?.is_demo && session.user.email.endsWith("@demo.loyalloop.test");

  function reset() {
    setSetup(null);
    setMode(null);
    setCode("");
    setPassword("");
    setError(null);
  }

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError(err instanceof ApiError ? Object.values(err.fields)[0] ?? err.message : "Something went wrong");
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function startSetup() {
    const res = await run(() => api<Envelope<SetupData>>("/auth/mfa/setup", { method: "POST" }));
    if (res) setSetup(res.data);
  }

  async function confirmSetup(e: React.FormEvent) {
    e.preventDefault();
    const res = await run(() => api<Envelope<{ recovery_codes: string[] }>>("/auth/mfa/enable", { method: "POST", body: { code } }));
    if (res) {
      setCodes(res.data.recovery_codes);
      reset();
      qc.invalidateQueries({ queryKey: ["mfa-status"] });
      refresh();
    }
  }

  async function confirmSensitive(e: React.FormEvent) {
    e.preventDefault();
    const isRecovery = code.includes("-") || code.length > 6;
    const body = { password, ...(isRecovery ? { recovery_code: code } : { code }) };
    if (mode === "disable") {
      const res = await run(() => api("/auth/mfa/disable", { method: "POST", body }));
      if (res) {
        reset();
        qc.invalidateQueries({ queryKey: ["mfa-status"] });
        refresh();
      }
    } else {
      const res = await run(() => api<Envelope<{ recovery_codes: string[] }>>("/auth/mfa/recovery-codes", { method: "POST", body }));
      if (res) {
        setCodes(res.data.recovery_codes);
        reset();
        qc.invalidateQueries({ queryKey: ["mfa-status"] });
      }
    }
  }

  const enabled = status.data?.enabled ?? session?.user.mfa_enabled;

  return (
    <Card title="Two-factor authentication">
      {codes ? (
        <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />
      ) : setup ? (
        <form className="form" onSubmit={confirmSetup} noValidate>
          <p>1. Scan this QR code with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy).</p>
          <img src={setup.qr_svg} alt="QR code for your authenticator app" width={180} height={180} style={{ border: "1px solid var(--color-border)", borderRadius: 4 }} />
          <details className="small">
            <summary>Can't scan? Enter this key instead</summary>
            <code style={{ wordBreak: "break-all" }}>{setup.secret}</code>
          </details>
          <p>2. Enter the 6-digit code the app shows.</p>
          {error && <Alert kind="error">{error}</Alert>}
          <TextInput label="Authentication code" value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="mono" />
          <div className="form-actions">
            <Button onClick={reset}>Cancel</Button>
            <Button type="submit" variant="primary" loading={busy} disabled={code.length < 6}>
              Turn on two-factor
            </Button>
          </div>
        </form>
      ) : mode ? (
        <form className="form" onSubmit={confirmSensitive} noValidate>
          <p>{mode === "disable" ? "Confirm it's you to turn off two-factor authentication." : "Confirm it's you to create new recovery codes. Old codes will stop working."}</p>
          {error && <Alert kind="error">{error}</Alert>}
          <TextInput label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <TextInput label="Authentication code or recovery code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" className="mono" />
          <div className="form-actions">
            <Button onClick={reset}>Cancel</Button>
            <Button type="submit" variant={mode === "disable" ? "danger" : "primary"} loading={busy} disabled={!password || !code}>
              {mode === "disable" ? "Turn off two-factor" : "Create new codes"}
            </Button>
          </div>
        </form>
      ) : enabled ? (
        <div className="stack">
          <p className="row">
            <ShieldCheck size={18} className="text-success" aria-hidden="true" />
            <span>
              <strong className="text-success">On.</strong> You'll enter a code from your authenticator app when you sign in.
            </span>
          </p>
          <p className="muted small">{status.data?.recovery_codes_remaining ?? "—"} unused recovery codes.</p>
          {error && <Alert kind="error">{error}</Alert>}
          <div className="row">
            <Button size="sm" onClick={() => setMode("regenerate")}>
              New recovery codes
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMode("disable")}>
              Turn off
            </Button>
          </div>
        </div>
      ) : (
        <div className="stack">
          <p>Protect your account with a code from your phone in addition to your password. Strongly recommended for owners and managers.</p>
          {isDemo && <Alert kind="info">Two-factor can't be turned on for shared demo accounts.</Alert>}
          {error && <Alert kind="error">{error}</Alert>}
          <div>
            <Button variant="primary" loading={busy} disabled={!!isDemo} onClick={startSetup}>
              Set up two-factor
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
