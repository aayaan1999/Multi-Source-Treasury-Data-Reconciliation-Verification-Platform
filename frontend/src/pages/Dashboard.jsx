import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api";
import AlertStrip from "../components/AlertStrip";
import CountryBreakdown from "../components/CountryBreakdown";
import KpiTile from "../components/KpiTile";
import RefreshNow from "../components/RefreshNow";
import TopBar from "../components/TopBar";
import TrendPanel from "../components/TrendPanel";
import { buildAlerts } from "../kpi/alerts";
import { formatDay, formatValue, isNum } from "../kpi/format";
import { KPIS, KPI_BY_KEY, TREND_KEYS } from "../kpi/kpiConfig";

function Section({ title, children, action }) {
  return (
    <section className="mt-10">
      <div className="mb-3.5 flex items-center justify-between gap-3 border-l-2 border-accent pl-3">
        <h2 className="text-base font-semibold tracking-tight text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Message({ title, children, action }) {
  return (
    <div className="card mx-auto mt-16 max-w-md rounded-xl border border-hair bg-surface p-6 text-center">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      <p className="mt-2 text-sm text-ink2">{children}</p>
      {action}
    </div>
  );
}

// Table twin of the trend panels: every value the charts show, reachable without hovering.
function TrendTable({ rows }) {
  return (
    <div className="card overflow-x-auto rounded-xl border border-hair bg-surface">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-hair bg-page/60 text-ink2">
            <th className="px-4 py-2.5 font-medium">Date</th>
            {TREND_KEYS.map((k) => (
              <th key={k} className="px-4 py-2.5 font-medium">{KPI_BY_KEY[k].short}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...rows].reverse().map((r) => (
            <tr key={r.calculation_date} className="border-b border-hair transition-colors last:border-0 hover:bg-page">
              <td className="px-4 py-2 text-ink">{formatDay(r.calculation_date)}</td>
              {TREND_KEYS.map((k) => (
                <td key={k} className="px-4 py-2 tabular-nums text-ink">{formatValue(KPI_BY_KEY[k], r[k])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState({ status: "loading" });
  const [selected, setSelected] = useState(null);
  const [tableView, setTableView] = useState(false);
  const [refreshCount, setRefreshCount] = useState(0);   // bumped by Refresh Now so the country view reloads too

  const load = useCallback(async () => {
    setData({ status: "loading" });
    try {
      // `latest` drives the default view (no aggregation on page load, just a read of the precomputed row);
      // `history` feeds the trend, the change-since-last-period arrows and the date selector.
      const [latest, history] = await Promise.all([api.kpiLatest(), api.kpiHistory(730)]);
      setData({ status: "ready", latest, history });
      setSelected(latest.calculation_date);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setData({ status: "empty" });
      else setData({ status: "error", message: e.message });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const view = useMemo(() => {
    if (data.status !== "ready") return null;
    const history = [...data.history].sort((a, b) => a.calculation_date.localeCompare(b.calculation_date));
    const index = history.findIndex((r) => r.calculation_date === selected);
    const row = selected === data.latest.calculation_date ? data.latest : history[index] ?? data.latest;
    return {
      row,
      previous: index > 0 ? history[index - 1] : null,
      upTo: index >= 0 ? history.slice(0, index + 1) : history,
      dates: history.map((r) => r.calculation_date).reverse(),
    };
  }, [data, selected]);

  const alerts = useMemo(
    () => (view ? buildAlerts(view.row, { checkStale: view.row.calculation_date === data.latest.calculation_date }) : []),
    [view, data],
  );

  if (data.status === "loading") {
    return (
      <>
        <TopBar />
        <p className="mt-16 text-center text-ink2" role="status">Loading the latest numbers…</p>
      </>
    );
  }
  if (data.status === "empty") {
    return (
      <>
        <TopBar />
        <Message title="No numbers yet">
          The KPI table is empty. Upload the source files to start the pipeline; the numbers appear here once it has finished.
        </Message>
      </>
    );
  }
  if (data.status === "error") {
    return (
      <>
        <TopBar />
        <Message
          title="Couldn't load the dashboard"
          action={<button type="button" onClick={load} className="mt-4 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition hover:brightness-110">Try again</button>}
        >
          {data.message}
        </Message>
      </>
    );
  }

  const { row, previous, upTo, dates } = view;
  const historyDays = upTo.length;

  return (
    <>
      <TopBar asOf={row.calculation_date} dates={dates} selected={row.calculation_date} onSelect={setSelected} />
      <main className="mx-auto max-w-7xl px-4 pb-16 pt-6">
        <span className="kicker mb-2">Executive overview</span>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Executive summary</h1>
          <RefreshNow onRefreshed={() => { load(); setRefreshCount((n) => n + 1); }} />
        </div>

        <ul className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4" aria-label="Key indicators">
          {KPIS.map((kpi) => (
            <KpiTile
              key={kpi.key}
              kpi={kpi}
              value={row[kpi.key]}
              previous={previous?.[kpi.key]}
              previousDate={previous?.calculation_date}
              assumptions={(row.assumptions_applied ?? []).filter((a) => a.includes(kpi.key))}
            />
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted">
          Status colours use demo thresholds, and tiles marked “Assumption” rest on placeholder inputs. Both are pending
          confirmation with the bank; neither is verified accounting.
        </p>

        <Section
          title="Trend"
          action={
            <button
              type="button"
              onClick={() => setTableView((v) => !v)}
              aria-pressed={tableView}
              className="rounded-md border border-hair px-2.5 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink"
            >
              {tableView ? "Show charts" : "Show as table"}
            </button>
          }
        >
          {tableView ? (
            <TrendTable rows={upTo} />
          ) : (
            <ul className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {TREND_KEYS.map((key) => (
                <TrendPanel
                  key={key}
                  kpi={KPI_BY_KEY[key]}
                  data={upTo.filter((r) => isNum(r[key])).map((r) => ({ date: r.calculation_date, value: r[key] }))}
                />
              ))}
            </ul>
          )}
          {historyDays < 2 && (
            <p className="mt-3 text-sm text-ink2">
              {historyDays} day of history so far. The lines fill in as the pipeline runs each day; nothing here is estimated.
            </p>
          )}
        </Section>

        <Section title="What needs attention">
          <AlertStrip alerts={alerts} />
        </Section>

        <Section title="By country">
          <CountryBreakdown reloadKey={refreshCount} />
        </Section>
      </main>
    </>
  );
}
