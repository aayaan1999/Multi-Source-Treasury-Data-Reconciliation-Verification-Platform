import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import AssumptionBadge from "../components/AssumptionBadge";
import DataTable from "../components/DataTable";
import { LoadError, Loading } from "../components/PageShell";
import TopBar from "../components/TopBar";
import { formatDateTime, formatNumber } from "../kpi/format";

const CAN_RUN = new Set(["approver", "admin"]);          // same as Refresh now (specs/refresh-now.md)
const MAX_BYTES = 2 * 1024 ** 3;
const DEMO_NOTE = ["No connector registry yet: these connectors, schedules and results are demo content until the bank's sources are connected (backlog ING-1..6)."];

function clock(iso) {
  return iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "";
}

function Demo() {
  return <AssumptionBadge label="Demo data" heading="Demo content" items={DEMO_NOTE} footer="Shown so the screen is complete; not the bank's real sources yet." />;
}

/**
 * Data ingestion (specs/screen-data-ingestion.md; layout from the client demo deck, slide 3): what came in,
 * from where, and whether it worked. The stat cards and "Recent ingestions" are the real latest pipeline
 * run when there is one; connectors, schedules and file upload are demo content, labelled as such.
 */
export default function Ingestion() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setError(null);
    api.ingestionOverview().then(setData).catch(setError);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <TopBar />
      <main className="mx-auto max-w-7xl px-4 pb-16 pt-7">
        <span className="pill-brand mb-2">Data ingestion</span>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-ink">Bring data in</h1>
            <p className="mt-1 max-w-3xl text-sm text-ink2">
              Upload files or connect a source system. Every load is tagged with its source, country and run, then checked
              before it reaches a report.
            </p>
          </div>
          {data && <RunControls trigger={data.trigger} />}
        </div>
        {error && <LoadError error={error} onRetry={load} />}
        {!data && !error && <Loading what="the latest loads" />}
        {data && (
          <>
            <Stats data={data} />
            <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
              <div className="space-y-8">
                <Upload formats={data.upload_formats} />
                <Schedules schedules={data.schedules} />
              </div>
              <div className="space-y-8">
                <Connectors connectors={data.connectors} />
                <Recent recent={data.recent} />
              </div>
            </div>
          </>
        )}
      </main>
    </>
  );
}

/** "Schedule" (the pipeline's real trigger) and "Run all sources now" (Refresh now, FLOW-6). */
function RunControls({ trigger }) {
  const { user } = useAuth() || {};
  const [state, setState] = useState({ busy: false, message: "" });
  async function run() {
    setState({ busy: true, message: "" });
    try {
      await api.refreshNow();
      setState({ busy: false, message: "Started - the pipeline takes a few minutes; the figures update when it finishes." });
    } catch (e) {
      const notSetUp = e instanceof ApiError && e.status === 503;
      setState({ busy: false, message: notSetUp ? "The app isn't connected to the Databricks pipeline yet, so it can't start a run from here." : e.message });
    }
  }
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md border border-hair bg-surface px-3 py-2 text-sm font-medium text-ink" title="When the pipeline runs (databricks.yml)">
          Schedule: {trigger.toLowerCase()}
        </span>
        {CAN_RUN.has(user?.role) && (
          <button type="button" onClick={run} disabled={state.busy} className="btn-dark rounded-md px-4 py-2 text-sm transition disabled:opacity-60">
            {state.busy ? "Starting…" : "Run all sources now"}
          </button>
        )}
      </div>
      {state.message && <p className="max-w-sm text-right text-xs text-ink2" role="status">{state.message}</p>}
    </div>
  );
}

function StatCard({ label, value, suffix, hint, bad, demo }) {
  return (
    <li className={`card top-edge relative rounded-xl border border-hair bg-surface p-4 ${bad ? "bad" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm text-ink2">{label}</span>
        {demo && <Demo />}
      </div>
      <div className="mt-2 text-3xl font-semibold tracking-tight text-ink tabular-nums">
        {value}
        {suffix && <span className="ml-1 text-lg font-normal text-muted">{suffix}</span>}
      </div>
      {hint && <p className="mt-1 text-sm" style={{ color: bad ? "var(--critical)" : "var(--ink-2)" }}>{hint}</p>}
    </li>
  );
}

function Stats({ data }) {
  const { stats, sources } = data;
  return (
    <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard label="Sources connected" value={sources.connected} suffix={`/ ${sources.total}`} demo={sources.demo}
        hint={sources.missing.length ? `${sources.missing.join(", ")} not yet connected` : "All connected"} />
      <StatCard label="Files in latest run" value={formatNumber(stats.files, 0)} demo={stats.demo}
        hint={stats.run_at ? `Last at ${formatDateTime(stats.run_at)}` : "No run yet"} />
      <StatCard label="Records ingested" value={formatNumber(stats.received, 0)} demo={stats.demo}
        hint={`${formatNumber(stats.kept, 0)} kept · ${formatNumber(stats.held, 0)} held back with a reason`} />
      <StatCard label="Failed loads" value={formatNumber(stats.failed, 0)} demo={stats.demo} bad={stats.failed > 0}
        hint={stats.failed_example || "None"} />
    </ul>
  );
}

function SectionHead({ title, text, demo }) {
  return (
    <div className="mb-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="bar-heading text-lg font-semibold text-ink">{title}</h2>
        {demo && <Demo />}
      </div>
      <p className="mt-1 text-sm text-ink2">{text}</p>
    </div>
  );
}

/**
 * Drop or pick files. Demo only (backlog ING-3): each file's type and size are checked here and a progress
 * bar shown, but nothing is sent - the file never leaves the browser.
 */
function Upload({ formats }) {
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const input = useRef(null);
  const timers = useRef([]);

  useEffect(() => () => timers.current.forEach(clearInterval), []);

  function add(list) {
    const next = Array.from(list || []).map((file, i) => {
      const ext = (file.name.split(".").pop() || "").toUpperCase();
      const problem = !formats.includes(ext) ? `${ext || "This file type"} isn't accepted` : file.size > MAX_BYTES ? "Larger than 2 GB" : null;
      return { id: `${Date.now()}-${i}-${file.name}`, name: file.name, ext, progress: problem ? 0 : 5, problem };
    });
    setFiles((current) => [...next, ...current]);
    next.filter((f) => !f.problem).forEach((f) => {
      const timer = setInterval(() => {
        setFiles((current) => current.map((c) => (c.id === f.id ? { ...c, progress: Math.min(100, c.progress + 19) } : c)));
      }, 250);
      timers.current.push(timer);
      setTimeout(() => clearInterval(timer), 1500);
    });
  }

  return (
    <section aria-labelledby="upload-title">
      <div className="mb-3">
        <div className="flex items-center justify-between gap-2">
          <h2 id="upload-title" className="bar-heading text-lg font-semibold text-ink">Upload files</h2>
          <Demo />
        </div>
        <p className="mt-1 text-sm text-ink2">Drop a file for a one-off load, or when a source can only export files.</p>
      </div>
      <div className="card rounded-xl border border-hair bg-surface p-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            add(e.dataTransfer?.files);
          }}
          className={`rounded-xl border-2 border-dashed p-6 text-center transition-colors ${dragging ? "border-[var(--brand-yellow)] bg-page" : "border-hair"}`}
        >
          <span aria-hidden className="mx-auto grid h-12 w-12 place-items-center rounded-xl" style={{ background: "var(--brand-dark)", color: "var(--brand-yellow)" }}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" /></svg>
          </span>
          <p className="mt-3 text-base font-semibold text-ink">Drag &amp; drop files here</p>
          <p className="mt-1 text-sm text-ink2">or pick them from your computer. Up to 2 GB per file.</p>
          <button type="button" onClick={() => input.current?.click()} className="btn-brand mt-3 rounded-md px-4 py-2 text-sm">Browse files</button>
          <input
            ref={input}
            type="file"
            multiple
            hidden
            aria-label="Choose files to upload"
            accept={formats.map((f) => `.${f.toLowerCase()}`).join(",")}
            onChange={(e) => {
              add(e.target.files);
              e.target.value = "";
            }}
          />
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            {formats.map((f) => <span key={f} className="rounded-md bg-page px-2 py-0.5 text-xs font-semibold text-ink2">{f}</span>)}
          </div>
        </div>
        {files.length > 0 && (
          <ul className="mt-3 space-y-2" aria-label="Files">
            {files.map((f) => (
              <li key={f.id} className="flex items-center gap-3 rounded-lg border border-hair p-2.5">
                <span className="rounded-md bg-page px-2 py-1 text-xs font-semibold text-ink2">{f.ext || "?"}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex justify-between gap-2 text-sm">
                    <span className="truncate font-medium text-ink">{f.name}</span>
                    <span className="shrink-0 text-xs text-muted">{f.problem ? "" : `${f.progress}%`}</span>
                  </div>
                  {f.problem ? (
                    <p className="text-xs" style={{ color: "var(--critical)" }}>{f.problem}</p>
                  ) : (
                    <>
                      <span className="mt-1 block h-1.5 rounded-full bg-page">
                        <span className="block h-full rounded-full" style={{ width: `${f.progress}%`, background: "var(--brand-yellow)" }} />
                      </span>
                      {f.progress >= 100 && <p className="mt-1 text-xs text-muted">Checked - not sent: file upload isn't connected to the pipeline yet.</p>}
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Schedules({ schedules }) {
  return (
    <section>
      <SectionHead title="Scheduled pulls" text="Connectors run on their own; no one has to remember." demo={schedules.demo} />
      <DataTable
        caption="Scheduled pulls"
        columns={[
          { key: "source", header: "Source", render: (r) => <span className="font-medium">{r.source}</span> },
          { key: "runs", header: "Runs" },
          { key: "next_at", header: "Next pull", render: (r) => <span className="text-ink2">{formatDateTime(r.next_at)}</span> },
        ]}
        rows={schedules.items}
        rowKey={(r) => r.source}
      />
    </section>
  );
}

function Connectors({ connectors }) {
  const [asked, setAsked] = useState(null);
  return (
    <section>
      <SectionHead title="Connect a source" text="Live connectors pull on a schedule or when new data arrives." demo={connectors.demo} />
      <ul className="grid gap-3 sm:grid-cols-2">
        {connectors.items.map((c) => (
          <li key={c.code} className="card flex items-center gap-3 rounded-xl border border-hair bg-surface p-3">
            <span className="grid h-10 min-w-10 place-items-center rounded-lg bg-page px-1.5 text-xs font-bold text-ink">{c.code}</span>
            <div className="min-w-0 flex-1">
              <div className="font-semibold text-ink">{c.name}</div>
              <div className="truncate text-sm text-ink2">{c.detail}</div>
            </div>
            {c.status === "connected" ? (
              <StatusPill status="connected" />
            ) : (
              <button type="button" onClick={() => setAsked(c.name)} className="btn-dark rounded-md px-3 py-1.5 text-sm">Connect</button>
            )}
          </li>
        ))}
      </ul>
      {asked && (
        <p className="mt-2 text-sm text-ink2" role="status">
          Connecting {asked} needs its connection details and a connector for its format - planned (backlog ING-1), not
          available in this demo yet.
        </p>
      )}
    </section>
  );
}

const PILL = {
  connected: ["Connected", "var(--good)"],
  success: ["Success", "var(--good)"],
  processing: ["Processing", "var(--warning)"],
  failed: ["Failed", "var(--critical)"],
};

function StatusPill({ status }) {
  const [label, color] = PILL[status] || [status, "var(--muted)"];
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium"
      style={{ background: `color-mix(in srgb, ${color} 14%, transparent)`, color }}>
      <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

function Recent({ recent }) {
  return (
    <section>
      <SectionHead title="Recent ingestions" text="Every load, with what it received and whether it succeeded." demo={recent.demo} />
      <DataTable
        caption="Recent ingestions"
        columns={[
          { key: "source", header: "Source", render: (r) => <span className="font-medium">{r.source}</span> },
          { key: "type", header: "Type" },
          { key: "data", header: "Data" },
          { key: "received", header: "Records received", align: "right", render: (r) => formatNumber(r.received, 0) },
          {
            key: "status",
            header: "Status",
            render: (r) => (
              <span className="inline-flex flex-col items-start gap-0.5">
                <StatusPill status={r.status} />
                {r.reason && <span className="text-xs text-ink2">{r.reason}</span>}
                {!r.reason && r.held > 0 && <span className="text-xs text-ink2">{formatNumber(r.held, 0)} held back</span>}
              </span>
            ),
          },
          { key: "at", header: "Last run", render: (r) => <span className="text-ink2">{formatDateTime(r.at)}</span> },
        ]}
        rows={recent.items}
        rowKey={(r) => `${r.source}|${r.data}|${r.at}`}
      />
    </section>
  );
}
