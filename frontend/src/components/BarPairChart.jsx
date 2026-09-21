import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatUsd, formatUsdCompact } from "../kpi/format";

const AXIS_TEXT = { fill: "var(--muted)", fontSize: 11 };

function PairTooltip({ active, payload, series, formatFull, ratioLabel }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="rounded-lg border border-hair bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="font-medium text-ink">{row.label}</div>
      {series.map((s) => (
        <div key={s.key} className="mt-1 flex items-center gap-2">
          <span aria-hidden className="inline-block h-0.5 w-3 rounded" style={{ background: s.color }} />
          <strong className="text-sm text-ink">{formatFull(row[s.key])}</strong>
          <span className="text-ink2">{s.label}</span>
        </div>
      ))}
      {ratioLabel && series.length === 2 && row[series[0].key] > 0 && (
        <div className="mt-1 text-ink2">{((row[series[1].key] / row[series[0].key]) * 100).toFixed(1)}% {ratioLabel}</div>
      )}
    </div>
  );
}


/**
 * Horizontal grouped bars, one group per category. `series` is [{ key, label, color }] (two series: total and bad).
 * Thin bars (10px) with a 4px rounded tip, a 2px gap inside each group, hairline grid. Clicking a bar (or its row in
 * the table view) calls onSelect(name); the selected category stays full strength while others soften.
 */
export default function BarPairChart({
  data, series, selected, onSelect, labelWidth = 104, cellColor,
  format = formatUsdCompact,     // axis ticks and bar-tip labels
  formatFull = formatUsd,        // tooltip
  ratioLabel = "of the total",   // second series as a % of the first, in the tooltip (null to omit)
}) {
  // Direct labels at the bar tips, but never "0": an empty bar needs no number.
  const tipLabel = (value) => (value > 0 ? format(value) : "");
  const height = Math.max(120, data.length * (series.length * 12 + 20) + 34);
  const dim = (name) => (selected && selected !== name ? 0.35 : 1);
  return (
    <div role="img" aria-label={`Bar chart of ${data.length} categories`} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 56, bottom: 0, left: 0 }} barGap={2} barCategoryGap={10}>
          <CartesianGrid horizontal={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis type="number" tickLine={false} axisLine={{ stroke: "var(--axis)" }} tick={AXIS_TEXT} tickFormatter={format} />
          <YAxis type="category" dataKey="label" width={labelWidth} tickLine={false} axisLine={false} tick={AXIS_TEXT} />
          <Tooltip cursor={{ fill: "var(--grid)", opacity: 0.4 }} content={(props) => <PairTooltip {...props} series={series} formatFull={formatFull} ratioLabel={ratioLabel} />} />
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              fill={s.color}
              barSize={10}
              radius={[0, 4, 4, 0]}
              isAnimationActive={false}
              onClick={onSelect ? (bar) => onSelect(bar.name) : undefined}
              cursor={onSelect ? "pointer" : undefined}
            >
              {data.map((d) => (
                <Cell key={d.name} fill={cellColor?.(d.name, s) ?? s.color} fillOpacity={dim(d.name)} />
              ))}
              <LabelList dataKey={s.key} position="right" formatter={tipLabel} style={{ fill: "var(--ink-2)", fontSize: 11 }} />
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
