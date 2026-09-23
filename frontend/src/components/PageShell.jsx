import { useState } from "react";
import TopBar from "./TopBar";

/** Top bar + page title + content column shared by every screen after the first. */
export default function PageShell({ title, eyebrow, subtitle, asOf, actions, children }) {
  return (
    <>
      <TopBar asOf={asOf} />
      <main className="mx-auto max-w-7xl px-4 pb-16 pt-7">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            {eyebrow && <span className="kicker mb-2">{eyebrow}</span>}
            <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
            {subtitle && <p className="mt-1 max-w-3xl text-sm text-ink2">{subtitle}</p>}
          </div>
          {actions}
        </div>
        {children}
      </main>
    </>
  );
}

export function Loading({ what = "the numbers" }) {
  return <p className="mt-16 text-center text-ink2" role="status">Loading {what}…</p>;
}

export function Notice({ title, children, action }) {
  return (
    <div className="card mx-auto mt-16 max-w-md rounded-xl border border-hair bg-surface p-6 text-center">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      <p className="mt-2 text-sm text-ink2">{children}</p>
      {action}
    </div>
  );
}

/** A failed load: the server's own message plus a retry. A 404 from the Gold tables means the pipeline hasn't loaded yet. */
export function LoadError({ error, onRetry, emptyTitle = "No numbers yet" }) {
  if (error?.status === 404) {
    return <Notice title={emptyTitle}>{error.message}. The numbers appear here once the pipeline has loaded the database.</Notice>;
  }
  return (
    <Notice
      title="Couldn't load this screen"
      action={<button type="button" onClick={onRetry} className="mt-4 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:brightness-110">Try again</button>}
    >
      {error?.message}
    </Notice>
  );
}

/** Small "download" button with a busy state and an inline error. */
export function ExportButton({ label, onExport }) {
  const [state, setState] = useState({ busy: false, error: "" });
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <button
        type="button"
        disabled={state.busy}
        onClick={async () => {
          setState({ busy: true, error: "" });
          try {
            await onExport();
            setState({ busy: false, error: "" });
          } catch (e) {
            setState({ busy: false, error: e.message });
          }
        }}
        className="rounded-md border border-hair px-3 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60"
      >
        {state.busy ? "Preparing…" : label}
      </button>
      {state.error && (
        <span role="alert" className="text-xs text-ink">
          <span style={{ color: "var(--critical)" }}>✕ </span>
          {state.error}
        </span>
      )}
    </span>
  );
}
