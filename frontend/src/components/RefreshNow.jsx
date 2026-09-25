import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";

const POLL_MS = 15000;
const CAN_REFRESH = new Set(["approver", "admin"]);   // the CFO (the demo approver) and admins

function clock(iso) {
  return iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "";
}

/** The line next to the button, from GET /refresh/status (specs/refresh-now.md). */
export function refreshLabel(status) {
  const run = status?.last_run;
  if (!run) return "No pipeline runs yet";
  if (status.running) return `Refreshing… started ${clock(run.started_at)}`;
  if (run.result === "SUCCESS") return `Updated ${clock(run.ended_at)}`;
  if (run.result) return `Last refresh ${run.result.toLowerCase()} at ${clock(run.ended_at)}`;
  return `Last run: ${run.state?.toLowerCase() ?? "unknown"}`;
}

/**
 * Refresh Now (FLOW-6): starts the Databricks pipeline instead of waiting for its next trigger,
 * then polls every 15 s. When a run it watched finishes successfully it calls onRefreshed, so the
 * page reloads its numbers. A run takes minutes, not seconds, and the label says so as it goes.
 * Only the CFO/admin see the button; everyone sees when the data was last updated.
 */
export default function RefreshNow({ onRefreshed }) {
  const { user } = useAuth() || {};
  const canRefresh = CAN_REFRESH.has(user?.role);
  const [status, setStatus] = useState(null);
  const [notSetUp, setNotSetUp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const wasRunning = useRef(false);

  const check = useCallback(async () => {
    try {
      const next = await api.refreshStatus();
      setStatus(next);
      setError("");
      if (wasRunning.current && !next.running && next.last_run?.result === "SUCCESS") onRefreshed?.();
      wasRunning.current = next.running;
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) setNotSetUp(true);
      else setError(e.message);
    }
  }, [onRefreshed]);

  useEffect(() => {
    check();
  }, [check]);

  useEffect(() => {
    if (!status?.running) return undefined;
    const timer = setInterval(check, POLL_MS);
    return () => clearInterval(timer);
  }, [status?.running, check]);

  async function start() {
    setBusy(true);
    setError("");
    try {
      await api.refreshNow();
      wasRunning.current = true;
      setStatus((s) => ({ running: true, last_run: { ...(s?.last_run || {}), state: "PENDING", started_at: new Date().toISOString() } }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  // Not set up yet (no Databricks settings in backend/.env): the button still shows, and clicking it
  // says so, so the dashboard looks finished before the pipeline is connected.
  if (notSetUp && !canRefresh) return null;

  return (
    <div className="flex flex-wrap items-center gap-3" aria-live="polite">
      {status && <span className="text-sm text-ink2">{refreshLabel(status)}</span>}
      {notSetUp && !error && <span className="text-xs text-muted">Not connected to the pipeline yet</span>}
      {canRefresh && (
        <button
          type="button"
          onClick={start}
          disabled={busy || status?.running}
          className="rounded-md border border-hair px-3 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60"
        >
          {status?.running ? "Refreshing…" : "Refresh now"}
        </button>
      )}
      {error && <span role="alert" className="text-sm" style={{ color: "var(--critical)" }}>{error}</span>}
    </div>
  );
}
