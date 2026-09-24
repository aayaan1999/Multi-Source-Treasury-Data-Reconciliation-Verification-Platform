import { useState } from "react";
import { api } from "../api";
import DataTable from "../components/DataTable";
import { Loading, LoadError } from "../components/PageShell";
import Section from "../components/Section";
import useAsync from "../hooks/useAsync";

const TYPE_LABEL = { SUSPICIOUS: "Suspicious", THRESHOLD: "Threshold", OPERATIONAL: "Operational" };

/** "How tasks are created", in plain words, from app_settings (specs/task-cases.md section 5). */
export function policyLines(settings) {
  const sev = settings["task.severity"];
  const due = settings["task.due_days"];
  if (!sev || !due) return [];
  const base = Object.entries(sev.base).map(([t, n]) => `${TYPE_LABEL[t] || t} ${n}`).join(", ");
  return [
    "Transaction flags on the same account and day, of the same kind (Suspicious, Threshold or Operational), become one case and one task. Suspicious goes to Fraud Investigation, Threshold to Compliance, Operational to Operations.",
    `Severity score: ${base}; +1 when a case has ${sev.many_flags_at} or more flags; +1 when it has ${sev.many_rules_at} or more different rules.`,
    `High (score ${sev.high_min}+) and Medium (${sev.medium_min}+) cases become tasks. Low cases go to the daily digest below; anyone can raise one as a task.`,
    `Deadlines: High ${due.HIGH} days, Medium ${due.MEDIUM}, Low ${due.LOW}; data-quality issues ${due.DATA_QUALITY}; reconciliation items ${due.RECONCILIATION}; breaches their limit's resolution days.`,
    "Data-quality issues, reconciliation items and breaches stay one task each.",
  ];
}

export function TaskPolicy() {
  const { status, data } = useAsync(() => api.taskPolicy(), []);
  if (status !== "ready" && !data) return null;
  const settings = Object.fromEntries(data.map((r) => [r.key, r.value]));
  const placeholder = data.some((r) => r.is_placeholder);
  return (
    <details className="card mt-6 rounded-xl border border-hair bg-surface p-4 text-sm">
      <summary className="cursor-pointer font-medium text-ink">How tasks are created</summary>
      <ul className="mt-3 list-disc space-y-1.5 pl-5 text-ink2">
        {policyLines(settings).map((line) => <li key={line}>{line}</li>)}
      </ul>
      {placeholder && <p className="mt-3 text-xs text-muted">These values are demo placeholders until the bank confirms its own policy.</p>}
    </details>
  );
}

/** Low-severity cases: listed, not tasks. "Raise as task" hands one to the bridge. */
export function Digest() {
  const { status, data, error, reload } = useAsync(() => api.digest(), []);
  const [raised, setRaised] = useState(() => new Set());
  const [raiseError, setRaiseError] = useState("");

  async function raise(caseId) {
    setRaiseError("");
    try {
      await api.raiseDigestCase(caseId);
      setRaised((s) => new Set(s).add(caseId));
    } catch (e) {
      setRaiseError(e.message);
    }
  }

  return (
    <Section id="digest" title="Daily digest" description="Low-severity cases: kept on record, not assigned as tasks. Raise one if it needs a closer look.">
      {status === "loading" && <Loading what="the digest" />}
      {status === "error" && !data && <LoadError error={error} onRetry={reload} />}
      {data && (
        <DataTable
          caption="Daily digest"
          columns={[
            { key: "account_id", header: "Account" },
            { key: "case_date", header: "Date" },
            { key: "flag_type", header: "Type", render: (c) => TYPE_LABEL[c.flag_type] || c.flag_type },
            { key: "flag_count", header: "Flags", align: "right" },
            {
              key: "raise", header: "",
              render: (c) => raised.has(c.case_id)
                ? <span className="text-sm text-ink2">Raised: appears in Tasks shortly</span>
                : <button type="button" onClick={() => raise(c.case_id)} className="rounded-md border border-hair px-2.5 py-1 text-sm text-ink hover:border-accent/40 hover:bg-page">Raise as task</button>,
            },
          ]}
          rows={data}
          rowKey={(c) => c.case_id}
          emptyText="Nothing in the digest."
        />
      )}
      {raiseError && <p role="alert" className="mt-2 text-sm" style={{ color: "var(--critical)" }}>{raiseError}</p>}
    </Section>
  );
}
