import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { landingOf } from "../access";
import { useAuth } from "../auth";
import appbayLogo from "../assets/appbay-logo.jpg";

// Sample figures for the sign-in page's picture of the platform - not the bank's data.
const CAR_TREND = [16.9, 17.1, 17.0, 17.4, 17.3, 17.6, 17.8, 17.7, 18.0, 18.1, 18.2, 18.4];
const RECONCILED = [97.9, 98.6, 99.1, 98.8, 99.4, 99.6, 99.8];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function SampleCard({ title, value, change, children }) {
  return (
    <div className="rounded-xl border border-white/15 bg-white/5 p-4 backdrop-blur-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-white/60">{title}</p>
      <p className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-white">{value}</span>
        <span className="text-xs font-medium" style={{ color: "var(--brand-yellow)" }}>{change}</span>
      </p>
      <div className="mt-3">{children}</div>
    </div>
  );
}

/** A 12-month trend line with a soft fill. */
function TrendChart({ values }) {
  const w = 220, h = 70, lo = Math.min(...values) - 0.3, hi = Math.max(...values) + 0.3;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, h - ((v - lo) / (hi - lo)) * h]);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-[70px] w-full" preserveAspectRatio="none" aria-hidden>
      <defs>
        <linearGradient id="car-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--brand-yellow)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="var(--brand-yellow)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${w},${h} L0,${h} Z`} fill="url(#car-fill)" />
      <path d={line} fill="none" stroke="var(--brand-yellow)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Daily bars, the latest day highlighted. */
function BarChart({ values, labels }) {
  const lo = 97;
  return (
    <div className="flex h-[70px] items-end gap-1.5" aria-hidden>
      {values.map((v, i) => (
        <div key={labels[i]} className="flex flex-1 flex-col items-center gap-1">
          <span
            className="w-full rounded-sm"
            style={{ height: `${((v - lo) / (100 - lo)) * 52 + 4}px`,
                     background: i === values.length - 1 ? "var(--brand-yellow)" : "rgba(255,255,255,0.35)" }}
          />
          <span className="text-[10px] leading-none text-white/50">{labels[i]}</span>
        </div>
      ))}
    </div>
  );
}

export default function Login() {
  const { user, login, notice } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Back to the page they asked for, else Data ingestion (or their home screen if they don't use it).
  if (user) return <Navigate to={location.state?.from?.pathname || landingOf(user)} replace />;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const signedIn = await login(email.trim(), password);
      navigate(location.state?.from?.pathname || landingOf(signedIn), { replace: true });
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
        style={{ background: "var(--brand-dark)" }}
      >
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 20%, white 1px, transparent 1px), radial-gradient(circle at 60% 70%, white 1px, transparent 1px)",
            backgroundSize: "48px 48px, 64px 64px",
          }}
        />

        <div className="relative flex items-center gap-4">
          <img src={appbayLogo} alt="AppBay" className="h-12 w-auto shrink-0" />
          <span className="border-l border-white/20 pl-4 text-lg font-semibold tracking-tight">Bank Data Platform</span>
        </div>

        <div className="relative max-w-md">
          <h1 className="text-[2.2rem] font-semibold leading-[1.15] tracking-tight">
            One system for regulatory reporting, <span style={{ color: "var(--brand-yellow)" }}>risk & workflow.</span>
          </h1>
          <p className="mt-4 text-base leading-relaxed text-white/75">
            Nightly data reconciliation, KPI monitoring, scenario modelling and a governed
            approval trail — in one place.
          </p>

          <div className="mt-10 grid grid-cols-2 gap-3" role="img" aria-label="Sample charts: capital adequacy trend and daily reconciliation rate">
            <SampleCard title="Capital adequacy" value="18.4%" change="+1.5 pts in 12 months">
              <TrendChart values={CAR_TREND} />
            </SampleCard>
            <SampleCard title="Records reconciled" value="99.8%" change="today">
              <BarChart values={RECONCILED} labels={DAYS} />
            </SampleCard>
          </div>
          <p className="mt-2 text-xs text-white/40">Sample figures</p>
        </div>

      </section>

      {/* Form panel */}
      <section className="flex items-center justify-center bg-page px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <img src={appbayLogo} alt="AppBay" className="h-9 w-auto shrink-0 rounded-md" />
            <span className="text-base font-semibold tracking-tight text-ink">Bank Data Platform</span>
          </div>

          <h2 className="text-2xl font-semibold tracking-tight text-ink">Sign in</h2>

          {notice && (
            <p role="status" className="mt-5 rounded-lg border border-hair bg-surface p-3 text-sm text-ink">{notice}</p>
          )}

          <form onSubmit={submit} className="mt-7">
            <label className="block text-sm font-medium text-ink2">
              Email
              <input
                className={field}
                type="email"
                autoComplete="username"
                placeholder="cfo@bankx.demo"
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
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3.5 py-2.5 font-medium text-on-accent shadow-sm transition hover:brightness-110 disabled:opacity-60"
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

        </div>
      </section>
    </main>
  );
}
