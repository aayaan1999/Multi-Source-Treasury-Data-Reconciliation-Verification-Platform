/**
 * "Important" on a reconciliation task that needs the CFO's approval whatever the team decides
 * (specs/reconciliation-approvals.md section 2: a missing record, a key field, a large difference). With
 * a reason, the tag says it in full.
 */
export default function ImportantTag({ reason }) {
  return (
    <span
      className="ml-2 inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold align-middle"
      style={{ background: "color-mix(in srgb, var(--critical) 14%, transparent)", color: "var(--critical)" }}
      title={`Needs the CFO's approval${reason ? `: ${reason}` : ""}`}
    >
      <span aria-hidden>!</span>
      {reason ? `Important: ${reason}` : "Important"}
    </span>
  );
}
