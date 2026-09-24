import PageShell from "../components/PageShell";
import CoreSystemSection from "../reconciliation/CoreSystemSection";
import PipelineSection from "../reconciliation/PipelineSection";

/**
 * Two checks (specs/pipeline-reconciliation.md, specs/reconciliation-groups.md): did every source's
 * data survive our cleaning, and does our data match the bank's core system? Each section loads on its
 * own, so one failing never blanks the other. Decisions happen in Tasks; this tab is the overview.
 */
export default function Reconciliation() {
  return (
    <PageShell
      title="Reconciliation"
      eyebrow="Multi-source reconciliation"
      subtitle="Two checks: did every source's data survive our cleaning (received vs kept), and does our data match the bank's core system?"
    >
      <PipelineSection />

      <div className="mt-14 border-t border-hair pt-8">
        <h2 className="text-lg font-semibold tracking-tight text-ink">Our data vs the core banking system</h2>
        <p className="mt-0.5 text-sm text-ink2">
          Differences between our own records and the bank's core system. Harmless ones clear themselves; the rest are grouped by
          cause and decided in Tasks, with important ones always on their own. Each run is signed off by two people.
        </p>
      </div>

      <CoreSystemSection />
    </PageShell>
  );
}
