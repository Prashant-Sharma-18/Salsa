import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Envelope } from "../api/types";
import { Alert, Card, Loading, PageHeader } from "../components/ui";

interface Message {
  id: number;
  kind: string;
  recipient: string;
  subject: string;
  body: string;
  created_at: string;
}

/** Local development only: the backend returns 404 unless DEMO_MODE is on outside production. */
export function DevMailboxPage() {
  const query = useQuery({
    queryKey: ["dev-outbox"],
    queryFn: async () => (await api<Envelope<Message[]>>("/dev/outbox")).data,
    refetchInterval: 5000,
  });

  function linkify(text: string) {
    return text.split(/(https?:\/\/\S+)/g).map((part, i) =>
      part.startsWith("http") ? (
        <a key={i} href={part.replace(/^https?:\/\/[^/]+/, "")}>
          {part}
        </a>
      ) : (
        <span key={i}>{part}</span>
      ),
    );
  }

  return (
    <main className="content">
      <PageHeader title="Dev mailbox" description="Emails queued by the app in local demo mode. Never enabled in production." />
      {query.isLoading && <Loading />}
      {query.error && <Alert kind="error">The dev mailbox is disabled in this environment.</Alert>}
      <div className="stack">
        {query.data?.length === 0 && <p className="muted">No emails yet.</p>}
        {query.data?.map((m) => (
          <Card key={m.id} title={m.subject}>
            <p className="muted small" style={{ marginBottom: 8 }}>
              To {m.recipient} · {m.kind} · {new Date(m.created_at).toLocaleString()}
            </p>
            <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "inherit" }}>{linkify(m.body)}</pre>
          </Card>
        ))}
      </div>
    </main>
  );
}
