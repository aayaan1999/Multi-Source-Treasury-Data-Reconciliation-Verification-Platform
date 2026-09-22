import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

const ROLES = [
  { label: "Analyst", desc: "Prepares data & flags exceptions" },
  { label: "Reviewer", desc: "Checks and comments" },
  { label: "Approver", desc: "Signs off for submission" },
  { label: "Admin", desc: "Manages users & config" },
];

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={location.state?.from?.pathname || "/"} replace />;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email.trim(), password);
      navigate(location.state?.from?.pathname || "/", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const field =
    "mt-1.5 w-full rounded-lg border border-hair bg-page px-3.5 py-2.5 text-ink shadow-sm outline-none transition focus:border-transparent focus:ring-2 focus:ring-accent/60";

  return (
    <main className="grid min-h-screen grid-cols-1 lg:grid-cols-[1.1fr_1fr]">
      {/* Brand panel */}
      <section
        className="relative hidden flex-col justify-between overflow-hidden p-10 text-white lg:flex"
        style={{ background: "linear-gradient(155deg, #123a66 0%, #1b4d8f 45%, #2a78d6 100%)" }}
      >
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 20%, white 1px, transparent 1px), radial-gradient(circle at 60% 70%, white 1px, transparent 1px)",
            backgroundSize: "48px 48px, 64px 64px",
          }}
        />

        <div className="relative flex items-center gap-2.5">
          <svg viewBox="0 0 32 32" className="h-8 w-8 shrink-0">
            <rect width="32" height="32" rx="7" fill="white" fillOpacity="0.15" />
            <path d="M16 6 L27 11.5 V13.5 H5 V11.5 Z" fill="white" />
            <rect x="7" y="15" width="3" height="10" fill="white" />
            <rect x="14.5" y="15" width="3" height="10" fill="white" />
            <rect x="22" y="15" width="3" height="10" fill="white" />
            <rect x="5" y="26" width="22" height="2.5" fill="white" />
          </svg>
          <span className="text-lg font-semibold tracking-tight">Bank Data Platform</span>
        </div>

        <div className="relative max-w-md">
          <h1 className="text-[2.2rem] font-semibold leading-[1.15] tracking-tight">
            One system for regulatory reporting, risk & workflow.
          </h1>
          <p className="mt-4 text-base leading-relaxed text-white/75">
            Nightly data reconciliation, KPI monitoring, scenario modelling and a governed
            approval trail — in one place.
          </p>

          <div className="mt-10 grid grid-cols-2 gap-3">
            {ROLES.map((r) => (
              <div
                key={r.label}
                className="rounded-lg border border-white/15 bg-white/5 px-3.5 py-3 backdrop-blur-sm"
              >
                <p className="text-sm font-medium text-white">{r.label}</p>
                <p className="mt-0.5 text-xs text-white/60">{r.desc}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="relative text-xs text-white/50">
          Demo environment · sample data only
        </p>
      </section>

      {/* Form panel */}
      <section className="flex items-center justify-center bg-page px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0">
              <rect width="32" height="32" rx="7" fill="#2a78d6" />
              <path d="M16 6 L27 11.5 V13.5 H5 V11.5 Z" fill="#ffffff" />
              <rect x="7" y="15" width="3" height="10" fill="#ffffff" />
              <rect x="14.5" y="15" width="3" height="10" fill="#ffffff" />
              <rect x="22" y="15" width="3" height="10" fill="#ffffff" />
              <rect x="5" y="26" width="22" height="2.5" fill="#ffffff" />
            </svg>
            <span className="text-base font-semibold tracking-tight text-ink">Bank Data Platform</span>
          </div>

          <h2 className="text-2xl font-semibold tracking-tight text-ink">Welcome back</h2>
          <p className="mt-1.5 text-sm text-ink2">
            Sign in with a demo account — analyst, reviewer, approver or admin.
          </p>

          <form onSubmit={submit} className="mt-7">
            <label className="block text-sm font-medium text-ink2">
              Email
              <input
                className={field}
                type="email"
                autoComplete="username"
                placeholder="analyst@bankx.demo"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>

            <label className="mt-4 block text-sm font-medium text-ink2">
              Password
              <span className="relative mt-1.5 block">
                <input
                  className={`${field} mt-0 pr-11`}
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-ink2 hover:text-ink"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                      <path d="M3 3l18 18M10.6 10.6a3 3 0 004.24 4.24M9.5 5.1A10.4 10.4 0 0112 5c6 0 9.5 6 9.5 7-.3.5-1 1.6-2.1 2.8M6.5 6.6C4 8.2 2.5 10.6 2.5 12c0 1 3.5 7 9.5 7 1.3 0 2.5-.3 3.6-.8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                      <path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7z" strokeLinecap="round" strokeLinejoin="round" />
                      <circle cx="12" cy="12" r="3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </button>
              </span>
            </label>

            {error && (
              <p role="alert" className="mt-4 flex items-start gap-1.5 text-sm text-ink">
                <span className="font-medium" style={{ color: "var(--critical)" }}>✕</span>
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3.5 py-2.5 font-medium text-white shadow-sm transition hover:brightness-110 disabled:opacity-60"
            >
              {busy && (
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z" />
                </svg>
              )}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-8 text-center text-xs text-muted">
            Demo environment · sample banking data only
          </p>
        </div>
      </section>
    </main>
  );
}
