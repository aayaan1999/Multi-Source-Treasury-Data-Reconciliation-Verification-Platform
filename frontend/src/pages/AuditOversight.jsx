import { useState } from "react";
import { api } from "../api";
import DataTable from "../components/DataTable";
import PageShell, { Loading, LoadError } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import useAsync from "../hooks/useAsync";
import { formatDateTime } from "../kpi/format";

function BreachAlerts() {
  const { status, data, error, reload } = useAsync(() => api.breaches({ status: "OPEN" }), []);
  if (status === "loading") return <Loading what="breach alerts" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  return (
    <DataTable
      caption="Open breaches"
      columns={[
        { key: "metric_name", header: "Metric" },
        { key: "actual_value", header: "Actual", align: "right" },
        { key: "threshold_value", header: "Threshold", align: "right" },
        { key: "detected_at", header: "Detected", render: (b) => formatDateTime(b.detected_at) },
        { key: "assigned_to_name", header: "Assigned to", render: (b) => b.assigned_to_name || "Unassigned" },
      ]}
      rows={data}
      rowKey={(b) => b.breach_id}
      rowFlag={() => ({ kind: "watch", label: "Open" })}
      emptyText="No open breaches."
    />
  );
}

function AuditTrail() {
  const [objectId, setObjectId] = useState("");
  const { status, data, error, reload } = useAsync(() => api.auditLog({ object_id: objectId || undefined, limit: 100 }), [objectId]);
  return (
    <>
      <div className="mb-3">
        <input
          type="text"
          value={objectId}
          onChange={(e) => setObjectId(e.target.value)}
          placeholder="Filter by object id (source_table:record_key:flag_label)"
          className="w-full max-w-md rounded-md border border-hair bg-surface px-3 py-1.5 text-sm text-ink sm:w-auto"
        />
      </div>
      {status === "loading" ? (
        <Loading what="the audit trail" />
      ) : status === "error" && !data ? (
        <LoadError error={error} onRetry={reload} />
      ) : (
        <DataTable
          caption="Audit trail"
          columns={[
            { key: "timestamp", header: "When", render: (a) => formatDateTime(a.timestamp) },
            { key: "user_name", header: "Who", render: (a) => a.user_name || "—" },
            { key: "action", header: "Action" },
            { key: "object_id", header: "Record" },
            { key: "new_value", header: "New value" },
          ]}
          rows={data}
          rowKey={(a) => a.log_id}
          emptyText="No audit events yet."
        />
      )}
    </>
  );
}

function ManagementStats() {
  const { status, data } = useAsync(() => api.workflowStats(), []);
  if (status !== "ready") return null;
  const { submissions, open_breaches_by_age, avg_turnaround_seconds } = data;
  const total = (submissions.on_time || 0) + (submissions.late || 0);
  const onTimePct = total ? Math.round((submissions.on_time / total) * 100) : null;
  const turnaround = avg_turnaround_seconds != null ? `${(avg_turnaround_seconds / 3600).toFixed(1)}h` : "—";
  return (
    <ul className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4" aria-label="Workflow management summary">
      <StatBox label="On-time submissions" value={onTimePct != null ? `${onTimePct}%` : "—"} hint={`${submissions.on_time || 0} on time, ${submissions.late || 0} late`} />
      <StatBox label="Overdue, not submitted" value={submissions.overdue_open || 0} status={submissions.overdue_open > 0 ? "action" : "good"} />
      <StatBox label="Avg. turnaround" value={turnaround} hint="First comment or event to decision" />
      <StatBox
        label="Open breaches"
        value={Object.values(open_breaches_by_age).reduce((a, b) => a + b, 0)}
        hint={Object.entries(open_breaches_by_age).map(([k, v]) => `${v} ${k}`).join(", ") || "None open"}
      />
    </ul>
  );
}

export default function AuditOversight() {
  return (
    <PageShell
      title="Audit & Oversight"
      subtitle="Risk-limit breaches, the permanent record of every review decision, and how the team is doing overall."
    >
      <Section id="stats" title="Management view" description="How review is going: on-time vs late, how long reviews take, and how old the open breaches are.">
        <ManagementStats />
      </Section>

      <Section id="breaches" title="Breach alerts" description="Regulatory and risk limits that have been crossed. Each new breach is detected automatically and becomes a task on the Tasks tab; this section is the full history.">
        <BreachAlerts />
      </Section>

      <Section id="audit" title="Audit trail" description="A permanent record of every comment and decision made on the Tasks tab. Nothing here can be edited or deleted.">
        <AuditTrail />
      </Section>
    </PageShell>
  );
}
