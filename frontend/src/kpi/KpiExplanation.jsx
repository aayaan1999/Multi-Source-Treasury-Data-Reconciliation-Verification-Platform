import { useEffect, useState } from "react";
import { api } from "../api";

/**
 * "Why it looks like this" for one KPI (specs/kpi-explanations.md). The explanation built by code from the
 * data shows at once; the local AI model is then asked to reword it, and its wording replaces it only if
 * every number and claim matched the data (checked on the server). Either way the panel says which
 * one you're reading, and the exact wording is one click away.
 */
export default function KpiExplanation({ kpiKey }) {
  const [exact, setExact] = useState(null);
  const [reworded, setReworded] = useState(null);
  const [pending, setPending] = useState(true);
  const [failed, setFailed] = useState(false);
  const [showExact, setShowExact] = useState(false);

  useEffect(() => {
    let live = true;
    setExact(null);
    setReworded(null);
    setPending(true);
    setFailed(false);
    setShowExact(false);
    api.kpiExplanation(kpiKey, false).then((r) => live && setExact(r)).catch(() => live && setFailed(true));
    api.kpiExplanation(kpiKey, true)
      .then((r) => live && setReworded(r))
      .catch(() => {})
      .finally(() => live && setPending(false));
    return () => {
      live = false;
    };
  }, [kpiKey]);

  if (failed && !reworded) return <p className="text-sm text-ink2">The explanation couldn't be loaded.</p>;
  if (!exact && !reworded) return <p className="text-sm text-ink2">Working out the explanation…</p>;

  const byModel = reworded?.source === "model";
  const text = byModel && !showExact ? reworded.text : (exact || reworded).text;
  return (
    <div>
      <p className="text-base leading-relaxed text-ink">{text}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink2">
        {byModel ? (
          <>
            <span className="rounded-full px-2 py-0.5 font-medium" style={{ background: "var(--series-1-soft)", color: "var(--ink)" }}>
              {showExact ? "Exact wording, from the data" : `Reworded by the local AI model (${reworded.model}), checked against the data`}
            </span>
            <button type="button" onClick={() => setShowExact((s) => !s)} className="underline underline-offset-2 hover:text-ink">
              {showExact ? "Show the easier wording" : "Show the exact wording"}
            </button>
          </>
        ) : (
          <span className="rounded-full px-2 py-0.5 font-medium" style={{ background: "var(--series-1-soft)", color: "var(--ink)" }}>
            Written from the data
          </span>
        )}
        {pending && <span>Checking whether the local AI model can put this more simply…</span>}
        {!pending && !byModel && reworded?.note && <span>Not reworded: {reworded.note}.</span>}
      </div>
    </div>
  );
}
