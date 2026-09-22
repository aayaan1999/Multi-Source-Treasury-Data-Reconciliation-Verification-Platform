import { Link } from "react-router-dom";
import { api } from "../api";
import DataTable from "../components/DataTable";
import { CheckIcon, CrossIcon, DashIcon, WarningIcon } from "../components/icons";
import PageShell, { LoadError, Loading } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import useAsync from "../hooks/useAsync";
import { STATUS_META } from "../kpi/status";
import { calendarCounts, daysLeftText, statusLabel, urgency } from "../reports/calendar";

const ICON = { good: CheckIcon, watch: WarningIcon, action: CrossIcon, unknown: DashIcon };

export default function Reports() {
  const { status, data, error, reload } = useAsync(() => api.reports(), []);
  const title = "Regulatory reporting";
  const subtitle = "What is due, what is done, and every number traced back to where it came from.";

  if (status === "loading") return <PageShell title={title}><Loading what="the report calendar" /></PageShell>;
  if (status === "error" && !data) return <PageShell title={title}><LoadError error={error} onRetry={reload} emptyTitle="No reports yet" /></PageShell>;

  const today = new Date();
  const counts = calendarCounts(data, today);
  const columns = [
    { key: "name", header: "Report", render: (r) => (r.has_lines
      ? <Link to={`/reports/${r.report_instance_id}`} className="font-medium text-ink underline decoration-hair underline-offset-4 hover:decoration-ink">{r.name}</Link>
      : <span className="text-ink">{r.name}</span>) },
    { key: "frequency", header: "Frequency" },
    { key: "period", header: "Period" },
    { key: "due", header: "Due", render: (r) => r.due_date },
    { key: "left", header: "Days left", render: (r) => {
      const u = urgency(r, today);
      const Icon = ICON[u] ?? DashIcon;
      return <span className="inline-flex items-center gap-1.5"><Icon color={STATUS_META[u]?.color} />{daysLeftText(r, today)}</span>;
    } },
    { key: "status", header: "Status", render: (r) => statusLabel(r.status) },
    { key: "owner", header: "Owner", render: (r) => r.owner_department ?? "—" },
    { key: "open", header: "Return", render: (r) => (r.has_lines ? <Link to={`/reports/${r.report_instance_id}`} className="text-ink underline underline-offset-4">Open</Link> : <span className="text-ink2">Not built yet</span>) },
  ];

  return (
    <PageShell title={title} subtitle={subtitle}>
      <ul className="mt-6 grid grid-cols-2 gap-5 lg:grid-cols-4" aria-label="Reporting summary">
        <StatBox label="Due this month" value={counts.dueThisMonth} hint="Reports with a due date this month" />
        <StatBox label="Submitted" value={counts.submitted} hint="Sent to the regulator" />
        <StatBox label="Pending approval" value={counts.pendingApproval} hint="Draft, under review or approved, not yet sent" />
        <StatBox label="Overdue" value={counts.overdue} hint="Past the due date, not submitted" status={counts.overdue ? "action" : "good"} />
      </ul>
      <Section id="calendar" title="Report calendar" description="Red: overdue or under 5 days left. Amber: under 10 days. Green: on time or submitted. Only reports with a built return can be opened.">
        <DataTable
          caption="Report calendar"
          columns={columns}
          rows={data}
          rowKey={(r) => String(r.report_instance_id)}
          rowFlag={(r) => {
            const u = urgency(r, today);
            return u === "action" ? { kind: "loss", label: "Urgent" } : u === "watch" ? { kind: "watch", label: "Soon" } : null;
          }}
          emptyText="No reports are scheduled yet."
        />
      </Section>
    </PageShell>
  );
}
