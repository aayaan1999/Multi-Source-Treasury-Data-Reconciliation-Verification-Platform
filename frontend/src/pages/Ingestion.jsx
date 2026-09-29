import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import AssumptionBadge from "../components/AssumptionBadge";
import DataTable from "../components/DataTable";
import { LoadError, Loading } from "../components/PageShell";
import TopBar from "../components/TopBar";
import SourceModal from "../ingestion/SourceModal";
import { Spinner, Toasts, useToasts } from "../ingestion/Toasts";
import { formatDateTime, formatNumber } from "../kpi/format";

const CAN_RUN = new Set(["approver", "admin"]);          // same as Refresh now (specs/refresh-now.md)
const MAX_BYTES = 2 * 1024 ** 3;
const DEMO_NOTE = ["Demo content until the bank's schedules and loads are recorded (backlog ING-2..6)."];

/** A failed pipeline start, in words: not connected to Databricks is expected in the demo, not an error. */
function runProblem(e) {
  return e instanceof ApiError && e.status === 503
    ? "The app isn't connected to the Databricks pipeline yet, so no run was started."
    : e.message;
}

function clock(iso) {
  return iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "";
}

function Demo() {
  return <AssumptionBadge label="Demo data" heading="Demo content" items={DEMO_NOTE} footer="Shown so the screen is complete; not the bank's real sources yet." />;
}

/**
 * Data ingestion (specs/screen-data-ingestion.md; layout from the client demo deck, slide 3): what came in,
 * from where, and whether it worked. The stat cards and "Recent ingestions" are the real latest pipeline
 * run when there is one. Sources are connected through their own form (ingestion/SourceModal) and saved on
 * the server; "Run all sources now" and each card's Sync start the Databricks pipeline job. Connecting,
 * disconnecting and syncing update this page in place - no reload.
 */
export default function Ingestion() {
  const { user } = useAuth() || {};
  const canManage = CAN_RUN.has(user?.role);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);        // the source whose form is open
  const [running, setRunning] = useState(false);       // "Run all sources now" in flight
  const [syncing, setSyncing] = useState(null);        // key of the source being synced
  const { toasts, push, update, dismiss } = useToasts();

  const load = useCallback(() => {
    setError(null);
    api.ingestionOverview().then(setData).catch(setError);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // One source changed: replace its card and recount "Sources connected", without reloading the page.
  const replaceSource = useCallback((next) => {
    setData((d) => {
      const items = d.connectors.items.map((s) => (s.key === next.key ? next : s));
      const missing = items.filter((s) => s.status !== "connected").map((s) => s.name);
      return { ...d, connectors: { ...d.connectors, items }, sources: { ...d.sources, connected: items.length - missing.length, missing } };
    });
  }, []);

  async function startRun(label, call) {
    const id = push(`Triggering Databricks ingestion pipeline${label ? ` for ${label}` : ""}…`, "info", { sticky: true });
    try {
      const r = await call();
      update(id, `${r.message} (run ${r.run_id}). The figures update when it finishes, in a few minutes.`, "success");
    } catch (e) {
      update(id, runProblem(e), "error");
    }
  }

  async function runAll() {
    setRunning(true);
    await startRun("", () => api.runAllSources());
    setRunning(false);
  }

  async function sync(source) {
    setSyncing(source.key);
    await startRun(source.name, () => api.syncSource(source.key));
    setSyncing(null);
  }

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
          {data && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md border border-hair bg-surface px-3 py-2 text-sm font-medium text-ink" title="When the pipeline runs (databricks.yml)">
                Schedule: {data.trigger.toLowerCase()}
              </span>
              {canManage && (
                <button type="button" onClick={runAll} disabled={running} className="btn-dark inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-60">
                  {running && <Spinner />}
                  {running ? "Triggering…" : "Run all sources now"}
                </button>
              )}
            </div>
          )}
        </div>
        {error && <LoadError error={error} onRetry={load} />}
        {!data && !error && <Loading what="the latest loads" />}
        {data && (
          <>
            <Stats data={data} />
            <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
              <div className="space-y-8">
                <Upload formats={data.upload_formats} notify={push} />
                <Schedules schedules={data.schedules} />
              </div>
              <div className="space-y-8">
                <Connectors connectors={data.connectors} canManage={canManage} syncing={syncing} onOpen={setEditing} onSync={sync} />
                <Recent recent={data.recent} />
              </div>
            </div>
          </>
        )}
      </main>
      {editing && (
        <SourceModal
          source={editing}
          notify={push}
          onClose={() => setEditing(null)}
          onSync={sync}
          onSaved={(next, message) => {
            replaceSource(next);
            setEditing(null);
            push(`${next.name} connected. ${message}`, next.credentials === "not_stored" ? "warning" : "success");
          }}
          onDisconnected={(next) => {
            replaceSource(next);
            setEditing(null);
            push(`${next.name} disconnected`, "success");
          }}
        />
      )}
      <Toasts toasts={toasts} onDismiss={dismiss} />
    </>
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
function Upload({ formats, notify }) {
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
      setTimeout(() => {
        clearInterval(timer);
        setFiles((current) => current.map((c) => (c.id === f.id ? { ...c, progress: 100 } : c)));
        notify?.(`${f.name} uploaded (demo): checked in the browser, not sent to the pipeline yet`, "success");
      }, 1500);
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

// A colour per source for its logo tile (a placeholder until real logos are added).
const TILE = { core_files: "#20242c", salesforce: "#0b76d1", postgresql: "#336791", rest_api: "#6b5bd2", aws_s3: "#d9761a", snowflake: "#1a9ed6" };

function IconButton({ label, onClick, disabled, busy, children }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-label={label} title={label}
      className="grid h-8 w-8 place-items-center rounded-md border border-hair text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink disabled:cursor-not-allowed disabled:opacity-50">
      {busy ? <Spinner /> : children}
    </button>
  );
}

/** One card per source: Connect when disconnected; Connected with Configure and Sync when connected. */
function Connectors({ connectors, canManage, syncing, onOpen, onSync }) {
  const noRights = canManage ? undefined : "Only the CFO or an admin can connect sources";
  return (
    <section>
      <SectionHead title="Connect a source" text="Live connectors pull on a schedule or when new data arrives." demo={connectors.demo} />
      <ul className="grid gap-3 sm:grid-cols-2" aria-label="Sources">
        {connectors.items.map((c) => {
          const connected = c.status === "connected";
          return (
            <li key={c.key} aria-label={c.name}
              className="card card-interactive flex items-center gap-3 rounded-xl border border-hair bg-surface p-3">
              <span aria-hidden className="grid h-10 min-w-10 place-items-center rounded-lg px-1.5 text-xs font-bold text-white" style={{ background: TILE[c.key] || "var(--brand-dark)" }}>
                {c.code}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-ink">{c.name}</span>
                  <StatusPill status={connected ? "connected" : "disconnected"} />
                </div>
                <div className="truncate text-sm text-ink2" title={c.detail}>{c.detail}</div>
                {c.credentials === "not_stored" && <div className="text-xs" style={{ color: "var(--warning)" }}>Saved without credentials</div>}
              </div>
              {connected ? (
                <div className="flex shrink-0 gap-1.5">
                  <IconButton label={`Configure ${c.name}`} onClick={() => onOpen(c)} disabled={!canManage}>
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></svg>
                  </IconButton>
                  <IconButton label={`Sync ${c.name}`} onClick={() => onSync(c)} disabled={!canManage || !!syncing} busy={syncing === c.key}>
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 12a8 8 0 01-14.3 4.9M4 12a8 8 0 0114.3-4.9M18 3v4h-4M6 21v-4h4" /></svg>
                  </IconButton>
                </div>
              ) : (
                <button type="button" onClick={() => onOpen(c)} disabled={!canManage} title={noRights}
                  className="btn-dark shrink-0 rounded-md px-3 py-1.5 text-sm transition disabled:cursor-not-allowed disabled:opacity-50">
                  Connect
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const PILL = {
  connected: ["Connected", "var(--good)"],
  disconnected: ["Disconnected", "var(--serious)"],
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
