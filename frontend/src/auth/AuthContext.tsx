import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setCsrfToken } from "../api/client";
import type { Envelope, Meta, SessionInfo } from "../api/types";

interface AuthValue {
  session: SessionInfo | null;
  meta: Meta | null;
  loading: boolean;
  error: Error | null;
  can: (perm: string) => boolean;
  setSession: (s: SessionInfo | null) => void;
  refresh: () => Promise<unknown>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const sessionQuery = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const res = await api<Envelope<SessionInfo | null>>("/auth/me");
      setCsrfToken(res.data?.csrf_token ?? null);
      return res.data;
    },
    staleTime: 60_000,
  });
  const metaQuery = useQuery({
    queryKey: ["meta"],
    queryFn: async () => (await api<Envelope<Meta>>("/meta")).data,
    staleTime: Infinity,
  });

  const session = sessionQuery.data ?? null;

  const setSession = useCallback(
    (s: SessionInfo | null) => {
      setCsrfToken(s?.csrf_token ?? null);
      // Business-scoped caches must never leak across a sign-in or business switch.
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "session" && q.queryKey[0] !== "meta" });
      qc.setQueryData(["session"], s);
    },
    [qc],
  );

  const signOut = useCallback(async () => {
    try {
      await api("/auth/signout", { method: "POST" });
    } finally {
      setSession(null);
    }
  }, [setSession]);

  const value = useMemo<AuthValue>(
    () => ({
      session,
      meta: metaQuery.data ?? null,
      loading: sessionQuery.isLoading,
      error: (sessionQuery.error as Error) ?? null,
      can: (perm: string) => !!session?.permissions.includes(perm),
      setSession,
      refresh: () => sessionQuery.refetch(),
      signOut,
    }),
    [session, metaQuery.data, sessionQuery, setSession, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
