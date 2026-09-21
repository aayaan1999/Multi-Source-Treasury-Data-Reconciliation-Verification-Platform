import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { formatPercentValue, formatUsd, formatUsdCompact } from "../kpi/format";
import { QUADRANTS } from "../performance/derive";

const AXIS_TEXT = { fill: "var(--muted)", fontSize: 11 };
const AXIS_LABEL = { fill: "var(--ink-2)", fontSize: 12 };

function ScatterTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const b = payload[0].payload;
  return (
    <div className="rounded-lg border border-hair bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="font-medium text-ink">{b.branch_name || b.branch_id} <span className="text-ink2">({b.region})</span></div>
      <div className="mt-1 text-ink2">Revenue <strong className="text-ink">{formatUsd(b.revenue_usd)}</strong></div>
      <div className="text-ink2">Cost-to-income <strong className="text-ink">{formatPercentValue(b.cost_to_income_pct)}</strong></div>
      <div className="text-ink2">Deposits <strong className="text-ink">{formatUsd(b.deposits_usd)}</strong></div>
      <div className="mt-1 text-ink">{QUADRANTS[b.quadrant].name}</div>
    </div>
  );
}

/**
 * One dot per branch: revenue (x) against cost-to-income (y), dot area = deposits held, split into four groups at the
 * median of the branches shown. Each dot sits inside a 24px invisible hit target, so a small dot is still easy to hover.
 * The closure candidates are labelled directly; the rest are reached through the tooltip and the table view.
 */
export default function EfficiencyScatter({ points, revenueMid, ratioMid, onSelect }) {
  const maxDeposits = Math.max(1, ...points.map((p) => p.deposits_usd || 0));
  const Dot = ({ cx, cy, payload }) => {
    const r = 6 + 12 * Math.sqrt((payload.deposits_usd || 0) / maxDeposits);
    return (
      <g style={{ cursor: onSelect ? "pointer" : "default" }} onClick={() => onSelect?.(payload)}>
        <circle cx={cx} cy={cy} r={Math.max(r, 12)} fill="transparent" />
        <circle cx={cx} cy={cy} r={r} fill="var(--series-1)" fillOpacity={0.75} stroke="var(--surface-1)" strokeWidth={2} />
        {payload.quadrant === "closure" && (
          <text x={cx + r + 4} y={cy + 4} fill="var(--ink)" fontSize={11}>{payload.branch_name || payload.branch_id}</text>
        )}
      </g>
    );
  };
  const corner = "pointer-events-none absolute text-xs text-ink2";
  return (
    <div className="relative" role="img" aria-label={`Scatter chart of ${points.length} branches: revenue against cost-to-income`}>
      <span className={`${corner} left-16 top-1`}>{QUADRANTS.closure.name}</span>
      <span className={`${corner} right-4 top-1 text-right`}>{QUADRANTS.wasteful.name}</span>
      <span className={`${corner} bottom-12 left-16`}>{QUADRANTS.small.name}</span>
      <span className={`${corner} bottom-12 right-4 text-right`}>{QUADRANTS.star.name}</span>
      <ResponsiveContainer width="100%" height={360}>
        <ScatterChart margin={{ top: 22, right: 24, bottom: 34, left: 8 }}>
          <CartesianGrid stroke="var(--grid)" strokeWidth={1} />
          <XAxis type="number" dataKey="revenue_usd" name="Revenue" tickLine={false} axisLine={{ stroke: "var(--axis)" }} tick={AXIS_TEXT}
            tickFormatter={formatUsdCompact} label={{ value: "Revenue (USD)", position: "insideBottom", offset: -18, ...AXIS_LABEL }} />
          <YAxis type="number" dataKey="cost_to_income_pct" name="Cost-to-income" tickLine={false} axisLine={{ stroke: "var(--axis)" }} tick={AXIS_TEXT}
            tickFormatter={(v) => `${Math.round(v)}%`} width={54} label={{ value: "Cost-to-income", angle: -90, position: "insideLeft", offset: 6, ...AXIS_LABEL }} />
          {revenueMid !== null && <ReferenceLine x={revenueMid} stroke="var(--axis)" strokeWidth={1.5} />}
          {ratioMid !== null && <ReferenceLine y={ratioMid} stroke="var(--axis)" strokeWidth={1.5} />}
          <Tooltip cursor={{ stroke: "var(--axis)", strokeDasharray: "3 3" }} content={(props) => <ScatterTooltip {...props} />} />
          <Scatter data={points} shape={Dot} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
