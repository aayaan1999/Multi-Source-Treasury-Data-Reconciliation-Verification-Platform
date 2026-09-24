import { CheckIcon, DashIcon, WarningIcon } from "../components/icons";

const GROUP_LABEL = {
  "fraud-investigation": "Fraud Investigation",
  compliance: "Compliance Review",
  operations: "Operations Review",
  cfo: "CFO",
  "reconciliation-team": "Assignee",
};

/**
 * Horizontal steps: Flagged -> the one candidate-group review this record's flagCategory routed
 * to -> Outcome (specs/screen-06-report-workflow.md section 2.2, specs/camunda-bpmn-process-design.md
 * section 3's flow). Only one of the three review groups is ever "current" for a given task - the
 * BPMN's gateway is exclusive, not parallel.
 */
export default function ApprovalChain({ candidateGroup, taskState }) {
  const reviewLabel = GROUP_LABEL[candidateGroup] || candidateGroup || "Review";
  const steps = [
    { label: "Flagged", state: "done" },
    { label: reviewLabel, state: taskState === "COMPLETED" ? "done" : "current" },
    { label: "Outcome recorded", state: taskState === "COMPLETED" ? "done" : "pending" },
  ];
  return (
    <ol className="flex flex-wrap items-center gap-1" aria-label="Approval chain">
      {steps.map((step, i) => (
        <li key={step.label} className="flex items-center gap-1">
          {i > 0 && <span aria-hidden className="mx-1 h-px w-6 bg-hair" />}
          <span
            className="inline-flex items-center gap-1.5 rounded-full border border-hair px-2.5 py-1 text-xs font-medium"
            style={
              step.state === "done"
                ? { background: "color-mix(in srgb, var(--good) 14%, transparent)", color: "var(--good)" }
                : step.state === "current"
                ? { background: "color-mix(in srgb, var(--series-1) 14%, transparent)", color: "var(--series-1)" }
                : undefined
            }
          >
            {step.state === "done" ? <CheckIcon color="var(--good)" /> : step.state === "current" ? <WarningIcon color="var(--series-1)" /> : <DashIcon />}
            {step.label}
          </span>
        </li>
      ))}
    </ol>
  );
}
