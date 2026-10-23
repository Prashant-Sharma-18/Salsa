import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
}

/** Last line of defence: a rendering crash shows a recovery screen instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Logged to the browser console only; no customer data is sent anywhere.
    console.error("UI error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="auth-page" role="alert">
        <div className="card card-body" style={{ maxWidth: 480, textAlign: "center" }}>
          <h1 style={{ fontSize: 20, marginBottom: 8 }}>Something went wrong</h1>
          <p className="muted" style={{ marginBottom: 16 }}>
            The page hit an unexpected error. Your data is safe. Reload to try again; if it keeps happening, contact support.
          </p>
          <div className="row" style={{ justifyContent: "center" }}>
            <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload page
            </button>
            <a className="btn" href="/">
              Go to dashboard
            </a>
          </div>
        </div>
      </main>
    );
  }
}
