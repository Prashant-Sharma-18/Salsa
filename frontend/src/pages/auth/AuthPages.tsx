import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { api, ApiError } from "../../api/client";
import type { Envelope, SessionInfo } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Gift, ShieldCheck, Sparkles } from "lucide-react";
import { BrandMark } from "../../components/AppLayout";
import { Alert, applyServerErrors, Button, Loading, TextInput } from "../../components/ui";

const SUBTITLES: Record<string, string> = {
  "Sign in": "Welcome back. Sign in to your business account.",
  "Create your account": "Launch a loyalty program your customers will actually use.",
};

export function AuthShell({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) {
  const { meta } = useAuth();
  const name = meta?.app_name ?? "LoyalLoop";
  return (
    <div className="auth-split">
      <aside className="auth-panel" aria-hidden="true">
        <div className="brand">
          <BrandMark />
          {name}
        </div>
        <div>
          <h2>Turn first-time visitors into regulars.</h2>
          <p className="lead">Points, rewards and referrals for independent shops, salons, gyms and cafés — set up in minutes.</p>
          <div className="demo-card">
            <div className="demo-card-top">
              <span>Maple Rewards</span>
              <span>Gold</span>
            </div>
            <div className="demo-card-points">1,240 pts</div>
            <div className="demo-card-bar">
              <span />
            </div>
            <div className="demo-card-foot">160 points to a free drink</div>
          </div>
          <ul>
            <li>
              <Sparkles size={18} /> Award points at checkout in seconds — no card data collected.
            </li>
            <li>
              <Gift size={18} /> Rewards, referrals and promotions that run themselves.
            </li>
            <li>
              <ShieldCheck size={18} /> Secure by default: two-factor sign-in, audit log, privacy tools.
            </li>
          </ul>
        </div>
        <p className="auth-foot">© {new Date().getFullYear()} {name}</p>
      </aside>
      <main className="auth-main">
        <div className="auth-card">
          <Link to="/" className="brand">
            <BrandMark />
            {name}
          </Link>
          <h1 className="auth-title">{title}</h1>
          <p className="auth-subtitle">{SUBTITLES[title] ?? ""}</p>
          {children}
          {footer && (
            <p className="muted" style={{ marginTop: 24 }}>
              {footer}
            </p>
          )}
        </div>
      </main>
    </div>
  );
}

const email = z.string().trim().min(1, "Required").email("Enter a valid email address");
const password = z.string().min(10, "Use at least 10 characters").max(128, "Use at most 128 characters");

// ------------------------------------------------------------------- sign in

const signInSchema = z.object({ email, password: z.string().min(1, "Required") });
type SignInValues = z.infer<typeof signInSchema>;

export function SignInPage() {
  const { session, setSession, meta } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [demoLoading, setDemoLoading] = useState<string | null>(null);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const form = useForm<SignInValues>({ resolver: zodResolver(signInSchema) });
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (session) return <Navigate to={from} replace />;

  async function onSubmit(values: SignInValues) {
    setError(null);
    try {
      const res = await api<Envelope<SessionInfo | { mfa_required: true; mfa_token: string }>>("/auth/signin", {
        method: "POST",
        body: values,
      });
      if ("mfa_required" in res.data) {
        setMfaToken(res.data.mfa_token);
        return;
      }
      setSession(res.data);
      navigate(from, { replace: true });
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  async function demo(role: string) {
    setError(null);
    setDemoLoading(role);
    try {
      const res = await api<Envelope<SessionInfo>>("/auth/demo-login", { method: "POST", body: { role } });
      setSession(res.data);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Demo sign-in failed");
    } finally {
      setDemoLoading(null);
    }
  }

  if (mfaToken) {
    return (
      <AuthShell title="Two-factor verification" footer={<button type="button" className="btn btn-ghost btn-sm" onClick={() => setMfaToken(null)}>Back to sign in</button>}>
        <MfaChallengeForm
          token={mfaToken}
          onSuccess={(s) => {
            setSession(s);
            navigate(from, { replace: true });
          }}
          onExpired={(message) => {
            setMfaToken(null);
            setError(message);
          }}
        />
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Sign in" footer={<>New here? <Link to="/signup">Create a business account</Link></>}>
      <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <TextInput label="Email" type="email" autoComplete="email" {...form.register("email")} error={form.formState.errors.email?.message} />
        <TextInput
          label="Password"
          type="password"
          autoComplete="current-password"
          {...form.register("password")}
          error={form.formState.errors.password?.message}
        />
        <Button type="submit" variant="primary" block loading={form.formState.isSubmitting}>
          Sign in
        </Button>
        <Link to="/forgot-password" className="small">
          Forgot your password?
        </Link>
      </form>
      {meta?.demo_mode && (
        <div>
          <div className="auth-divider">or explore the demo</div>
          {meta.demo_seeded ? (
            <>
              <div className="demo-roles">
                {["owner", "manager", "staff", "admin"].map((role) => (
                  <Button key={role} loading={demoLoading === role} onClick={() => demo(role)}>
                    Demo {role}
                  </Button>
                ))}
              </div>
              <p className="muted small" style={{ marginTop: 12 }}>
                Sample business with clearly labelled demo data.
              </p>
            </>
          ) : (
            <p className="muted small">
              Demo data is not seeded. Run <code>flask seed-demo</code> in the backend folder.
            </p>
          )}
        </div>
      )}
    </AuthShell>
  );
}

function MfaChallengeForm({
  token,
  onSuccess,
  onExpired,
}: {
  token: string;
  onSuccess: (s: SessionInfo) => void;
  onExpired: (message: string) => void;
}) {
  const [useRecovery, setUseRecovery] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) {
      setError(useRecovery ? "Enter a recovery code" : "Enter the 6-digit code");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api<Envelope<SessionInfo>>("/auth/mfa/verify", {
        method: "POST",
        body: useRecovery ? { mfa_token: token, recovery_code: value } : { mfa_token: token, code: value },
      });
      onSuccess(res.data);
    } catch (err) {
      if (err instanceof ApiError && (err.code === "mfa_expired" || err.code === "account_locked")) {
        onExpired(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Verification failed");
        setValue("");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit} noValidate>
      <p className="muted">
        {useRecovery
          ? "Enter one of the recovery codes you saved when you set up two-factor authentication."
          : "Enter the 6-digit code from your authenticator app."}
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput
        key={useRecovery ? "recovery" : "code"}
        label={useRecovery ? "Recovery code" : "Authentication code"}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        autoFocus
        autoComplete="one-time-code"
        inputMode={useRecovery ? "text" : "numeric"}
        maxLength={useRecovery ? 20 : 6}
        className="input-lg mono"
      />
      <Button type="submit" variant="primary" block loading={busy}>
        Verify
      </Button>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={() => {
          setUseRecovery((v) => !v);
          setValue("");
          setError(null);
        }}
      >
        {useRecovery ? "Use authenticator app instead" : "Use a recovery code instead"}
      </button>
    </form>
  );
}

// ------------------------------------------------------------------- sign up

const signUpSchema = z.object({
  display_name: z.string().trim().min(1, "Required").max(120),
  email,
  password,
});
type SignUpValues = z.infer<typeof signUpSchema>;

export function SignUpPage() {
  const { session, setSession } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<SignUpValues>({ resolver: zodResolver(signUpSchema) });
  if (session) return <Navigate to="/" replace />;

  async function onSubmit(values: SignUpValues) {
    setError(null);
    try {
      const res = await api<Envelope<SessionInfo>>("/auth/signup", { method: "POST", body: values });
      setSession(res.data);
      navigate("/onboarding", { replace: true });
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  const errors = form.formState.errors;
  return (
    <AuthShell title="Create your account" footer={<>Already have an account? <Link to="/signin">Sign in</Link></>}>
      <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <TextInput label="Your name" autoComplete="name" {...form.register("display_name")} error={errors.display_name?.message} />
        <TextInput label="Work email" type="email" autoComplete="email" {...form.register("email")} error={errors.email?.message} />
        <TextInput
          label="Password"
          type="password"
          autoComplete="new-password"
          hint="At least 10 characters."
          {...form.register("password")}
          error={errors.password?.message}
        />
        <Button type="submit" variant="primary" block loading={form.formState.isSubmitting}>
          Create account
        </Button>
        <p className="muted small">We'll send a link to verify your email address.</p>
      </form>
    </AuthShell>
  );
}

// ------------------------------------------------------------ password reset

export function ForgotPasswordPage() {
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ email: string }>({ resolver: zodResolver(z.object({ email })) });

  async function onSubmit(values: { email: string }) {
    setError(null);
    try {
      const res = await api<Envelope<{ message: string }>>("/auth/password-reset/request", { method: "POST", body: values });
      setSent(res.data.message);
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  return (
    <AuthShell title="Reset your password" footer={<Link to="/signin">Back to sign in</Link>}>
      {sent ? (
        <Alert kind="success">{sent}</Alert>
      ) : (
        <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
          {error && <Alert kind="error">{error}</Alert>}
          <TextInput label="Email" type="email" autoComplete="email" {...form.register("email")} error={form.formState.errors.email?.message} />
          <Button type="submit" variant="primary" block loading={form.formState.isSubmitting}>
            Send reset link
          </Button>
        </form>
      )}
    </AuthShell>
  );
}

const resetSchema = z
  .object({ password, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { message: "Passwords do not match", path: ["confirm"] });

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ password: string; confirm: string }>({ resolver: zodResolver(resetSchema) });

  async function onSubmit(values: { password: string }) {
    setError(null);
    try {
      await api("/auth/password-reset/confirm", { method: "POST", body: { token, password: values.password } });
      setDone(true);
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  return (
    <AuthShell title="Choose a new password">
      {done ? (
        <Alert kind="success" title="Password updated">
          You have been signed out everywhere. <Link to="/signin">Sign in with your new password</Link>.
        </Alert>
      ) : !token ? (
        <Alert kind="error">This reset link is incomplete. Request a new one.</Alert>
      ) : (
        <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
          {error && <Alert kind="error">{error}</Alert>}
          <TextInput label="New password" type="password" autoComplete="new-password" {...form.register("password")} error={form.formState.errors.password?.message} />
          <TextInput label="Confirm password" type="password" autoComplete="new-password" {...form.register("confirm")} error={form.formState.errors.confirm?.message} />
          <Button type="submit" variant="primary" block loading={form.formState.isSubmitting}>
            Update password
          </Button>
        </form>
      )}
    </AuthShell>
  );
}

// ------------------------------------------------------------- verify email

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { refresh } = useAuth();
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("");

  const started = useRef(false);

  useEffect(() => {
    // The token is single-use, so make exactly one request (StrictMode mounts effects twice).
    if (started.current) return;
    started.current = true;
    api("/auth/verify-email", { method: "POST", body: { token } })
      .then(() => {
        setState("ok");
        refresh();
      })
      .catch((err) => {
        setState("error");
        setMessage(err instanceof Error ? err.message : "Verification failed");
      });
  }, [token, refresh]);

  return (
    <AuthShell title="Email verification" footer={<Link to="/">Continue to the app</Link>}>
      {state === "working" && <Loading label="Verifying…" />}
      {state === "ok" && <Alert kind="success">Your email address is verified.</Alert>}
      {state === "error" && <Alert kind="error">{message}</Alert>}
    </AuthShell>
  );
}

// ---------------------------------------------------------- accept invitation

interface InvitePreview {
  business_name: string;
  email: string;
  role: string;
  account_exists: boolean;
  expires_at: string;
}

const inviteSchema = z.object({ display_name: z.string().trim().min(1, "Required"), password });

export function AcceptInvitePage() {
  const { token = "" } = useParams();
  const { session, setSession } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const preview = useQuery({
    queryKey: ["invite", token],
    queryFn: async () => (await api<Envelope<InvitePreview>>(`/auth/invitations/${token}`)).data,
    retry: false,
  });
  const form = useForm<{ display_name: string; password: string }>({ resolver: zodResolver(inviteSchema) });

  async function accept(values?: { display_name: string; password: string }) {
    setError(null);
    try {
      const res = await api<Envelope<SessionInfo>>(`/auth/invitations/${token}/accept`, { method: "POST", body: values ?? {} });
      setSession(res.data);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? applyServerErrors(err, form.setError) : "Could not accept invitation");
    }
  }

  if (preview.isLoading) return <AuthShell title="Team invitation"><Loading /></AuthShell>;
  if (preview.error)
    return (
      <AuthShell title="Team invitation" footer={<Link to="/signin">Go to sign in</Link>}>
        <Alert kind="error">{(preview.error as Error).message}</Alert>
      </AuthShell>
    );
  const invite = preview.data!;
  const signedInAsInvitee = session?.user.email === invite.email;

  return (
    <AuthShell title={`Join ${invite.business_name}`}>
      <p style={{ marginBottom: 16 }}>
        You've been invited as <strong>{invite.role}</strong> using <strong>{invite.email}</strong>.
      </p>
      {error && <div style={{ marginBottom: 16 }}><Alert kind="error">{error}</Alert></div>}
      {invite.account_exists ? (
        signedInAsInvitee ? (
          <Button variant="primary" block onClick={() => accept()}>
            Accept invitation
          </Button>
        ) : (
          <Alert kind="info">
            An account already exists for this email. <Link to="/signin" state={{ from: `/invite/${token}` }}>Sign in as {invite.email}</Link>{" "}
            and open this link again to accept.
          </Alert>
        )
      ) : (
        <form className="form" onSubmit={form.handleSubmit(accept)} noValidate>
          <TextInput label="Your name" autoComplete="name" {...form.register("display_name")} error={form.formState.errors.display_name?.message} />
          <TextInput
            label="Create a password"
            type="password"
            autoComplete="new-password"
            hint="At least 10 characters."
            {...form.register("password")}
            error={form.formState.errors.password?.message}
          />
          <Button type="submit" variant="primary" block loading={form.formState.isSubmitting}>
            Accept and create account
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
