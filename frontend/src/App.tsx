import { Link, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import { RequireBusiness, RequirePerm, RequireUser } from "./components/guards";
import { EmptyState } from "./components/ui";
import { AccountPage } from "./pages/Account";
import { AnalyticsPage } from "./pages/Analytics";
import { AuditLogPage } from "./pages/AuditLog";
import {
  AcceptInvitePage,
  ForgotPasswordPage,
  ResetPasswordPage,
  SignInPage,
  SignUpPage,
  VerifyEmailPage,
} from "./pages/auth/AuthPages";
import { CheckoutPage } from "./pages/Checkout";
import { CustomerDetailPage } from "./pages/CustomerDetail";
import { CustomersPage, EnrollCustomerPage } from "./pages/Customers";
import { DashboardPage } from "./pages/Dashboard";
import { DevMailboxPage } from "./pages/DevMailbox";
import { LocationsPage } from "./pages/Locations";
import { OnboardingPage } from "./pages/Onboarding";
import { JoinPage, PortalAccessPage, PortalHomePage, PortalRequestPage } from "./pages/portal/Portal";
import { ProgramSettingsPage } from "./pages/ProgramSettings";
import { RedemptionsPage } from "./pages/Redemptions";
import { ReferralsPage } from "./pages/Referrals";
import { RewardsPage } from "./pages/Rewards";
import { TeamPage } from "./pages/Team";

function NotFound() {
  return (
    <main className="content">
      <EmptyState title="Page not found" description="The page you were looking for doesn't exist." action={<Link className="btn" to="/">Go home</Link>} />
    </main>
  );
}

const gated = (perm: string, element: JSX.Element) => <RequirePerm perm={perm}>{element}</RequirePerm>;

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/signin" element={<SignInPage />} />
      <Route path="/signup" element={<SignUpPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/invite/:token" element={<AcceptInvitePage />} />
      <Route path="/join/:slug" element={<JoinPage />} />
      <Route path="/portal/access" element={<PortalAccessPage />} />
      <Route path="/portal/me" element={<PortalHomePage />} />
      <Route path="/portal/:slug" element={<PortalRequestPage />} />
      <Route path="/dev/mailbox" element={<DevMailboxPage />} />
      <Route
        path="/onboarding"
        element={
          <RequireUser>
            <OnboardingPage />
          </RequireUser>
        }
      />

      {/* Merchant app */}
      <Route
        element={
          <RequireBusiness>
            <AppLayout />
          </RequireBusiness>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="checkout" element={gated("purchases.create", <CheckoutPage />)} />
        <Route path="redemptions" element={gated("redemptions.complete", <RedemptionsPage />)} />
        <Route path="customers" element={gated("customers.view", <CustomersPage />)} />
        <Route path="customers/new" element={gated("customers.create", <EnrollCustomerPage />)} />
        <Route path="customers/:id" element={gated("customers.view", <CustomerDetailPage />)} />
        <Route path="rewards" element={gated("rewards.view", <RewardsPage />)} />
        <Route path="referrals" element={gated("referrals.view", <ReferralsPage />)} />
        <Route path="analytics" element={gated("analytics.view", <AnalyticsPage />)} />
        <Route path="settings/program" element={gated("program.manage", <ProgramSettingsPage />)} />
        <Route path="locations" element={gated("locations.view", <LocationsPage />)} />
        <Route path="team" element={gated("members.view", <TeamPage />)} />
        <Route path="audit" element={gated("audit.view", <AuditLogPage />)} />
        <Route path="account" element={<AccountPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
