import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Printer } from "lucide-react";
import { api } from "../api/client";
import type { Envelope } from "../api/types";
import { Alert, Button, ErrorMessage, Loading } from "../components/ui";

interface SignData {
  business_name: string;
  program_name: string;
  brand_color: string;
  logo_url: string;
  rules: string[];
  join_url: string;
  status: string;
}

/** Printable counter sign (US Letter / A4) with a QR code to the public join page. */
export function PrintSignPage() {
  const query = useQuery({
    queryKey: ["sign"],
    queryFn: async () => (await api<Envelope<SignData>>("/programs/current/sign")).data,
  });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorMessage error={query.error} />;
  const d = query.data!;
  const rules = d.rules.filter((r) => !r.startsWith("Points do not expire")).slice(0, 3);

  return (
    <div className="print-page">
      <div className="print-toolbar no-print">
        <Link to="/settings/program" className="btn">
          Back to settings
        </Link>
        <Button variant="primary" onClick={() => window.print()}>
          <Printer size={16} aria-hidden="true" /> Print sign
        </Button>
        {d.status !== "active" && <Alert kind="warning">Your program is {d.status}; the join page won't accept members until it's active.</Alert>}
      </div>
      <article className="sign" style={{ borderTopColor: d.brand_color }}>
        {d.logo_url && <img src={d.logo_url} alt="" className="sign-logo" />}
        <p className="sign-business">{d.business_name}</p>
        <h1 className="sign-title">Join {d.program_name}</h1>
        <p className="sign-subtitle">Earn rewards every visit. Scan to join in seconds.</p>
        <img src="/api/v1/programs/current/join-qr.svg" alt={`QR code linking to ${d.join_url}`} className="sign-qr" />
        <ul className="sign-rules">
          {rules.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        <p className="sign-url">{d.join_url.replace(/^https?:\/\//, "")}</p>
      </article>
    </div>
  );
}
