import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const AXIS_TEXT = { fill: "var(--muted)", fontSize: 11 };
const COLOR = { total: "var(--muted)", down: "var(--negative)", up: "var(--series-1)", none: "var(--muted)" };

/** Rows for the waterfall: today's ratio, one step per factor, the final ratio. Each step floats between where the ratio was and where it ends up. */
export function waterfallRows(start, steps, end) {
  const rows = [{ name: "Today", label: "Today", base: 0, value: start, kind: "total", text: `${start.toFixed(2)}%`, note: null }];
  let running = start;
  for (const s of steps) {
    const next = running + s.delta;
    const kind = Math.abs(s.delta) < 0.005 ? "none" : s.delta < 0 ? "down" : "up";
    const sign = kind === "none" ? "" : s.delta < 0 ? "−" : "+";
    rows.push({
      name: s.key, label: s.label, base: Math.min(running, next), value: Math.abs(s.delta), kind,
      text: `${sign}${Math.abs(s.delta).toFixed(2)} pts`, note: s.note ?? null,
    });
    running = next;
  }
  rows.push({ name: "After", label: "After stress", base: 0, value: end, kind: "total", text: `${end.toFixed(2)}%`, note: null });
  return rows;
}

function StepTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="rounded-lg border border-hair bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="font-medium text-ink">{r.label}</div>
      <div className="mt-1 text-sm text-ink"><strong>{r.text}</strong></div>
      {r.note && <div className="mt-1 max-w-56 text-ink2">{r.note}</div>}
    </div>
  );
}

/**
 * Capital-ratio waterfall: where the ratio starts, the drop each stressed factor causes (in calculation order), where it
 * ends. Totals are neutral grey, a fall is red, a rise is blue, and every bar carries its number, so colour never works
 * alone. The zero-based axis keeps the two total bars honest.
 */
export default function Waterfall({ start, steps, end, minimum }) {
  const data = waterfallRows(start, steps, end);
  const top = Math.max(...data.map((r) => r.base + r.value), minimum) * 1.18;
  return (
    <div role="img" aria-label={`Capital ratio waterfall from ${start.toFixed(2)}% to ${end.toFixed(2)}%`} style={{ height: 300 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 24, right: 12, bottom: 4, left: 0 }} barCategoryGap={16}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "var(--axis)" }} tick={AXIS_TEXT} interval={0} />
          <YAxis domain={[0, top]} tickLine={false} axisLine={false} tick={AXIS_TEXT} width={40} tickFormatter={(v) => `${Math.round(v)}%`} />
          <ReferenceLine y={minimum} stroke="var(--muted)" strokeDasharray="4 4" strokeWidth={1} />
          <Tooltip cursor={{ fill: "var(--grid)", opacity: 0.4 }} content={(props) => <StepTooltip {...props} />} />
          <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
          <Bar dataKey="value" stackId="w" barSize={34} radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {data.map((r) => (
              <Cell key={r.name} fill={COLOR[r.kind]} />
            ))}
            <LabelList dataKey="text" position="top" style={{ fill: "var(--ink)", fontSize: 12 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
