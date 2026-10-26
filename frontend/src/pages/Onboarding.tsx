import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api } from "../api/client";
import type { Envelope, SessionInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, applyServerErrors, Button, Card, Select, TextInput } from "../components/ui";

const TIMEZONES = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Phoenix",
  "America/Los_Angeles",
  "America/Anchorage",
  "Pacific/Honolulu",
];

const schema = z.object({
  name: z.string().trim().min(2, "Enter your business name").max(120),
  timezone: z.string().min(1),
  location_name: z.string().trim().min(1, "Required").max(120),
  location_address: z.string().max(255).optional(),
  program_name: z.string().max(120).optional(),
  points_per_dollar: z.coerce.number().int("Whole numbers only").min(1, "At least 1").max(100, "At most 100"),
  first_reward_name: z.string().max(120).optional(),
  first_reward_points: z
    .union([z.literal(""), z.coerce.number().int("Whole numbers only").min(1, "At least 1")])
    .optional(),
});
type FormInput = z.input<typeof schema>;
type Values = z.output<typeof schema>;

const STEPS = ["Business", "First location", "Program basics"];
const STEP_FIELDS: (keyof Values)[][] = [
  ["name", "timezone"],
  ["location_name", "location_address"],
  ["program_name", "points_per_dollar", "first_reward_name", "first_reward_points"],
];

export function OnboardingPage() {
  const { session, setSession, signOut } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<FormInput, unknown, Values>({
    resolver: zodResolver(schema),
    defaultValues: { timezone: "America/New_York", points_per_dollar: 1, first_reward_points: "" },
  });
  if (!session) return <Navigate to="/signin" replace />;

  const errors = form.formState.errors;
  const name = form.watch("name");

  async function next() {
    if (await form.trigger(STEP_FIELDS[step])) setStep((s) => s + 1);
  }

  async function onSubmit(values: Values) {
    setError(null);
    try {
      const body = {
        ...values,
        program_name: values.program_name || undefined,
        first_reward_name: values.first_reward_name || undefined,
        first_reward_points: values.first_reward_points === "" ? undefined : values.first_reward_points,
      };
      const res = await api<Envelope<SessionInfo>>("/businesses", { method: "POST", body });
      setSession(res.data);
      navigate("/", { replace: true });
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
      const failedStep = STEP_FIELDS.findIndex((fields) => fields.some((f) => form.getFieldState(f).error));
      if (failedStep >= 0) setStep(failedStep);
    }
  }

  return (
    <main className="auth-page">
      <div className="wizard">
        <h1 style={{ marginBottom: 4 }}>Set up your loyalty program</h1>
        <p className="muted" style={{ marginBottom: 24 }}>
          Three quick steps. You can change everything later in settings.
        </p>
        <ol className="steps">
          {STEPS.map((label, i) => (
            <li key={label} className={i < step ? "done" : i === step ? "current" : ""} aria-current={i === step ? "step" : undefined}>
              {i + 1}. {label}
            </li>
          ))}
        </ol>
        <Card>
          <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
            {error && <Alert kind="error">{error}</Alert>}
            {step === 0 && (
              <>
                <TextInput label="Business name" autoFocus {...form.register("name")} error={errors.name?.message} />
                <Select label="Time zone" hint="Reports and dates use this time zone." {...form.register("timezone")}>
                  {TIMEZONES.map((tz) => (
                    <option key={tz} value={tz}>
                      {tz.replace("_", " ")}
                    </option>
                  ))}
                </Select>
              </>
            )}
            {step === 1 && (
              <>
                <TextInput label="Location name" placeholder="e.g. Downtown" autoFocus {...form.register("location_name")} error={errors.location_name?.message} />
                <TextInput label="Address (optional)" {...form.register("location_address")} error={errors.location_address?.message} />
              </>
            )}
            {step === 2 && (
              <>
                <TextInput label="Program name" placeholder={name ? `${name} Rewards` : "Rewards"} {...form.register("program_name")} />
                <TextInput
                  label="Points per $1 spent"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={100}
                  hint="Partial dollars are rounded down."
                  {...form.register("points_per_dollar")}
                  error={errors.points_per_dollar?.message}
                />
                <div className="grid grid-2">
                  <TextInput label="First reward (optional)" placeholder="Free coffee" {...form.register("first_reward_name")} />
                  <TextInput
                    label="Reward cost in points"
                    type="number"
                    inputMode="numeric"
                    {...form.register("first_reward_points")}
                    error={errors.first_reward_points?.message}
                  />
                </div>
              </>
            )}
            <div className="form-actions" style={{ justifyContent: "space-between" }}>
              {step > 0 ? (
                <Button onClick={() => setStep((s) => s - 1)}>Back</Button>
              ) : (
                <Button variant="ghost" onClick={() => signOut().then(() => navigate("/signin"))}>
                  Sign out
                </Button>
              )}
              {step < STEPS.length - 1 ? (
                <Button key="next" variant="primary" onClick={next}>
                  Continue
                </Button>
              ) : (
                <Button key="submit" type="submit" variant="primary" loading={form.formState.isSubmitting}>
                  Create program
                </Button>
              )}
            </div>
          </form>
        </Card>
        <p className="muted small" style={{ marginTop: 16 }}>
          Next: invite staff from <strong>Staff &amp; permissions</strong> once your email is verified.
        </p>
      </div>
    </main>
  );
}
