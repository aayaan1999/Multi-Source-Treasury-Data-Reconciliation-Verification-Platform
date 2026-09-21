import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const AXIS_TEXT = { fill: "var(--muted)", fontSize: 11 };

function MonthTooltip({ active, payload, minimum }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-hair bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="text-ink2">{p.month === 0 ? "Today" : `Month ${p.month}`}</div>
      <div className="mt-1 flex items-center gap-2">
        <span aria-hidden className="inline-block h-0.5 w-3 rounded" style={{ background: "var(--series-1)" }} />
        <strong className="text-sm text-ink">{p.car.toFixed(2)}%</strong>
        <span className="text-ink2">capital ratio</span>
      </div>
      {p.car < minimum && <div className="mt-1 text-ink">Below the {minimum}% minimum</div>}
    </div>
  );
}

/** The sentence that turns a percentage into a deadline. */
export function breachSentence(breachMonth, minimum) {
  if (breachMonth === null) return `No breach of the ${minimum}% minimum within 12 months.`;
  if (breachMonth === 0) return `Already below the ${minimum}% minimum today.`;
  return `You breach the ${minimum}% minimum in month ${breachMonth}.`;
}

/** Capital ratio month by month under the stress, with the regulatory minimum as a dashed line (a threshold) and the crossing month marked. */
export default function ProjectionChart({ projection, minimum, breachMonth }) {
  const values = projection.map((p) => p.car);
  const lo = Math.min(...values, minimum);
  const hi = Math.max(...values, minimum);
  const pad = Math.max(0.5, (hi - lo) * 0.15);
  const breach = breachMonth === null ? null : projection[breachMonth];
  return (
    <div role="img" aria-label={`Projected capital ratio over 12 months. ${breachSentence(breachMonth, minimum)}`} style={{ height: 260 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={projection} margin={{ top: 12, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis dataKey="month" tickLine={false} axisLine={{ stroke: "var(--axis)" }} tick={AXIS_TEXT} tickFormatter={(m) => (m === 0 ? "Now" : `M${m}`)} />
          <YAxis domain={[Math.floor((lo - pad) * 2) / 2, Math.ceil((hi + pad) * 2) / 2]} tickLine={false} axisLine={false} tick={AXIS_TEXT} width={44}
            tickFormatter={(v) => `${Number(v.toFixed(1))}%`} />
          <ReferenceLine y={minimum} stroke="var(--muted)" strokeDasharray="4 4" strokeWidth={1} />
          <Tooltip cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} content={(props) => <MonthTooltip {...props} minimum={minimum} />} />
          <Line type="linear" dataKey="car" stroke="var(--series-1)" strokeWidth={2} isAnimationActive={false}
            dot={{ r: 3, fill: "var(--series-1)", stroke: "var(--surface-1)", strokeWidth: 2 }}
            activeDot={{ r: 5, fill: "var(--series-1)", stroke: "var(--surface-1)", strokeWidth: 2 }} />
          {breach && <ReferenceDot x={breach.month} y={breach.car} r={7} fill="var(--negative)" stroke="var(--surface-1)" strokeWidth={2} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
