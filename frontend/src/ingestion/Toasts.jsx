import { useCallback, useEffect, useRef, useState } from "react";

const TONE = {
  info: "var(--ink-2)",
  success: "var(--good)",
  warning: "var(--warning)",
  error: "var(--critical)",
};

/**
 * Small toast queue for the Data ingestion screen. push(text, tone) shows a message in the corner for a few
 * seconds and returns its id; update(id, text, tone) changes one in place (e.g. "Triggering…" becoming
 * "Started"), which restarts its timer.
 */
export function useToasts(ms = 4500) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef({});
  const nextId = useRef(1);

  const dismiss = useCallback((id) => {
    clearTimeout(timers.current[id]);
    delete timers.current[id];
    setToasts((all) => all.filter((t) => t.id !== id));
  }, []);

  const arm = useCallback((id, sticky) => {
    clearTimeout(timers.current[id]);
    if (!sticky) timers.current[id] = setTimeout(() => dismiss(id), ms);
  }, [dismiss, ms]);

  const push = useCallback((text, tone = "info", { sticky = false } = {}) => {
    const id = nextId.current++;
    setToasts((all) => [...all, { id, text, tone }]);
    arm(id, sticky);
    return id;
  }, [arm]);

  const update = useCallback((id, text, tone = "info") => {
    setToasts((all) => (all.some((t) => t.id === id) ? all.map((t) => (t.id === id ? { ...t, text, tone } : t)) : [...all, { id, text, tone }]));
    arm(id, false);
  }, [arm]);

  useEffect(() => () => Object.values(timers.current).forEach(clearTimeout), []);

  return { toasts, push, update, dismiss };
}

export function Toasts({ toasts, onDismiss }) {
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-40 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
      {toasts.map((t) => (
        <div key={t.id} role="status" className="toast-in pointer-events-auto flex items-start gap-3 rounded-lg border border-hair bg-surface p-3 text-sm text-ink shadow-[var(--shadow-hover)]"
          style={{ borderLeft: `4px solid ${TONE[t.tone] || TONE.info}` }}>
          {t.tone === "info" && <Spinner />}
          <span className="flex-1">{t.text}</span>
          <button type="button" onClick={() => onDismiss(t.id)} aria-label="Dismiss" className="text-muted hover:text-ink">✕</button>
        </div>
      ))}
    </div>
  );
}

export function Spinner({ size = 14 }) {
  return (
    <svg className="spin shrink-0" viewBox="0 0 24 24" width={size} height={size} aria-hidden fill="none" stroke="currentColor" strokeWidth="3">
      <circle cx="12" cy="12" r="9" opacity="0.25" />
      <path d="M21 12a9 9 0 00-9-9" strokeLinecap="round" />
    </svg>
  );
}
