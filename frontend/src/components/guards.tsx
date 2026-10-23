import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, Loading } from "./ui";
import { Lock } from "lucide-react";

/** Signed-in user with an active business. Server still enforces every permission. */
export function RequireBusiness({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!session) return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  if (!session.active_business) return <Navigate to={session.user.is_platform_admin ? "/admin" : "/onboarding"} replace />;
  return <>{children}</>;
}

export function RequireUser({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  if (loading) return <Loading />;
  if (!session) return <Navigate to="/signin" replace />;
  return <>{children}</>;
}

export function RequirePerm({ perm, children }: { perm: string; children: ReactNode }) {
  const { can } = useAuth();
  if (!can(perm))
    return (
      <EmptyState
        icon={<Lock size={28} aria-hidden="true" />}
        title="You don't have access to this page"
        description="Ask the business owner if you need this permission."
      />
    );
  return <>{children}</>;
}
