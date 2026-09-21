import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatDay, formatDayShort, formatPct, formatValue } from "../kpi/format";

const AXIS_TEXT = { fill: "var(--muted)", fontSize: 11 };

function TrendTooltip({ active, payload, kpi }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-lg border border-hair bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="text-ink2">{formatDay(point.date)}</div>
      <div className="mt-1 flex items-center gap-2">
        <span aria-hidden className="inline-block h-0.5 w-3 rounded" style={{ background: "var(--series-1)" }} />
        <strong className="text-sm text-ink">{formatValue(kpi, point.value)}</strong>
        <span className="text-ink2">{kpi.short}</span>
      </div>
    </div>
  );
}

// Room around the data (and the limit line) so a single point or a flat line isn't pinned to an edge.
function yDomain(values) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = hi - lo || Math.max(1, Math.abs(hi) * 0.1);
  return [Math.floor((lo - pad * 0.5) * 10) / 10, Math.ceil((hi + pad * 0.5) * 10) / 10];
}

/** One ratio over time. Single series, single axis: measures with different scales get their own panel. */
export default function TrendPanel({ kpi, data }) {
  const points = data.map((d) => ({ date: d.date, value: d.value, label: formatDayShort(d.date) }));
  const current = points.at(-1);
  const domain = yDomain([...points.map((p) => p.value), ...(kpi.limit != null ? [kpi.limit] : [])]);

  return (
    <li className="rounded-xl border border-hair bg-surface p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-ink2">{kpi.short}</h3>
        <span className="text-lg font-semibold text-ink">{formatValue(kpi, current?.value)}</span>
      </div>
      {/* The limit is explained here, not labelled on the plot: an in-chart label lands on top of the data line. */}
      <p className="mt-0.5 flex min-h-4 items-center gap-1.5 text-xs text-muted">
        {kpi.limit != null && (
          <>
            <svg aria-hidden width="16" height="4" className="shrink-0">
              <line x1="0" y1="2" x2="16" y2="2" stroke="var(--muted)" strokeWidth="1.5" strokeDasharray="4 3" />
            </svg>
            {kpi.limitLabel} {formatPct(kpi.limit)}
          </>
        )}
      </p>
      <div className="mt-1" role="img" aria-label={`${kpi.short} over ${points.length} ${points.length === 1 ? "day" : "days"}`}>
        <ResponsiveContainer width="100%" height={168}>
          <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
            <XAxis
              dataKey="label" tickLine={false} tick={AXIS_TEXT} axisLine={{ stroke: "var(--axis)" }}
              padding={{ left: 28, right: 28 }} interval="preserveStartEnd"
            />
            <YAxis
              domain={domain} tickLine={false} axisLine={false} tick={AXIS_TEXT} width={36} tickCount={4}
              tickFormatter={(v) => Number(v.toFixed(1)).toString()}
            />
            {kpi.limit != null && (
              <ReferenceLine y={kpi.limit} stroke="var(--muted)" strokeDasharray="4 4" strokeWidth={1} />
            )}
            <Tooltip cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} content={(props) => <TrendTooltip {...props} kpi={kpi} />} />
            <Line
              type="monotone" dataKey="value" stroke="var(--series-1)" strokeWidth={2} isAnimationActive={false}
              dot={{ r: 4, fill: "var(--series-1)", stroke: "var(--surface-1)", strokeWidth: 2 }}
              activeDot={{ r: 5, fill: "var(--series-1)", stroke: "var(--surface-1)", strokeWidth: 2 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </li>
  );
}
