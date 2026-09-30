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
const MAX_BYTES = 100 * 1024 ** 2;           // the server's limit (UPLOAD_MAX_BYTES)
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
 * the server; "Run All Sources" and each card's Sync start the Databricks pipeline job. Connecting,
 * disconnecting and syncing update this page in place - no reload.
 */
export default function Ingestion() {
  const { user } = useAuth() || {};
  const canManage = CAN_RUN.has(user?.role);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);        // the source whose form is open
  const [running, setRunning] = useState(false);       // "Run All Sources" in flight
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
              {canManage && (
                <button type="button" onClick={runAll} disabled={running} className="btn-dark inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-60">
                  {running && <Spinner />}
                  {running ? "Triggering…" : "Run All Sources"}
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
                <Upload formats={data.upload_formats} expected={data.upload_files || []} canUpload={canManage} notify={push} />
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

/** "LOANS.CSV" -> "CSV", "branches.v2.json" -> "JSON"; "" for a name with no type ("README", ".env"). */
export function fileType(name) {
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1 ? name.slice(dot + 1).toUpperCase() : "";
}

/** Which of the pipeline's files a name is ("Transactions_2026-09-30.csv" -> "transactions.csv"), or null.
 * The same rule as the server's (backend/app/routers/ingestion.py upload_table). */
export function pipelineFile(name, expected) {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || name.slice(dot + 1).toLowerCase() !== "csv") return null;
  const stem = name.slice(0, dot).trim().toLowerCase();
  const tables = expected.map((f) => f.replace(/\.csv$/i, "")).sort((x, y) => y.length - x.length);
  const table = tables.find((t) => stem === t || (stem.startsWith(t) && "_- .".includes(stem[t.length])));
  return table ? `${table}.csv` : null;
}

/**
 * Drop or pick the day's core banking files (specs/screen-data-ingestion.md section 3b). Each is checked here first (a CSV,
 * one of the pipeline's eight files, not empty, not too big, not already added), then sent to the
 * server, which checks its columns and writes it into the pipeline's landing folder; the pipeline starts
 * by itself about 2 minutes after the last file. The CFO and the Platform Administrator can upload.
 */
function Upload({ formats, expected, canUpload, notify }) {
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const input = useRef(null);
  const mounted = useRef(true);

  // A reply that comes after the page has gone updates nothing.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const patch = (id, change) => mounted.current && setFiles((current) => current.map((c) => (c.id === id ? { ...c, ...change } : c)));

  function add(list) {
    if (!canUpload) return;
    const seen = new Set(files.filter((f) => !f.problem).map((f) => `${f.name}|${f.size}`));
    const next = Array.from(list || []).map((file, i) => {
      const ext = fileType(file.name);
      const key = `${file.name}|${file.size}`;
      const target = pipelineFile(file.name, expected);
      const problem = !ext ? "No file type (add .csv)"
        : !formats.includes(ext) ? `${ext} isn't accepted: the pipeline reads CSV files`
        : !target ? `Not one of the pipeline's files (${expected.join(", ")})`
        : file.size === 0 ? "The file is empty"
        : file.size > MAX_BYTES ? "Larger than 100 MB"
        : seen.has(key) ? "Already added"
        : null;
      if (!problem) seen.add(key);
      return { id: `${Date.now()}-${i}-${file.name}`, name: file.name, size: file.size, ext, target, status: problem ? "refused" : "sending", problem, file };
    });
    setFiles((current) => [...next.map(({ file, ...f }) => f), ...current]);
    next.filter((f) => !f.problem).forEach((f) => send(f.id, f.name, f.file));
  }

  // A file that would replace many existing records comes back 409 and waits for "Send anyway".
  const held = useRef({});
  async function send(id, name, file, confirmed = false) {
    patch(id, { status: "sending", problem: null, warning: null });
    try {
      const r = await api.uploadFile(file, { confirmed });
      delete held.current[id];
      patch(id, { status: "sent", message: r.message });
      if (mounted.current) notify?.(`${name}: ${r.message}`, "success");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        held.current[id] = file;
        patch(id, { status: "held", warning: err.message });
        if (mounted.current) notify?.(`${name} is waiting for you: it would replace most of the data`, "info");
        return;
      }
      patch(id, { status: "failed", problem: err.message });
      if (mounted.current) notify?.(`${name} wasn't sent: ${err.message}`, "error");
    }
  }

  return (
    <section aria-labelledby="upload-title">
      <div className="mb-3">
        <div className="flex items-center justify-between gap-2">
          <h2 id="upload-title" className="bar-heading text-lg font-semibold text-ink">Upload files</h2>
        </div>
        <p className="mt-1 text-sm text-ink2">
          Drop the day's core banking files. They go straight into the pipeline's landing folder, and each file's reply says when the pipeline runs.
        </p>
      </div>
      <div className="card rounded-xl border border-hair bg-surface p-4">
        <div
          aria-disabled={!canUpload}
          onDragOver={(e) => {
            e.preventDefault();
            if (canUpload) setDragging(true);
          }}
          onDragLeave={(e) => {
            // Moving over the text or button inside the zone isn't leaving it.
            if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false);
          }}
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
          <p className="mt-1 text-sm text-ink2">or pick them from your computer. CSV, up to 100 MB each.</p>
          {canUpload ? (
            <button type="button" onClick={() => input.current?.click()} className="btn-brand mt-3 rounded-md px-4 py-2 text-sm">Browse files</button>
          ) : (
            <p className="mt-3 text-sm font-medium text-ink2">Only the CFO or the Platform Administrator can upload files.</p>
          )}
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
          <div className="mt-3 flex flex-wrap justify-center gap-1.5" aria-label="Files the pipeline reads">
            {expected.map((f) => <span key={f} className="rounded-md bg-page px-2 py-0.5 text-xs font-semibold text-ink2">{f}</span>)}
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
                    <span className="shrink-0 text-xs text-muted">{f.status === "sending" ? "Sending…" : f.status === "sent" ? "Sent" : ""}</span>
                  </div>
                  {f.warning ? (
                    <div className="mt-1 text-xs">
                      <p className="border-l-2 pl-2 text-ink" style={{ borderColor: "var(--warning)" }}>{f.warning}</p>
                      <div className="mt-1.5 flex gap-2">
                        <button type="button" className="rounded-md border border-hair px-2 py-1 font-semibold text-ink"
                          onClick={() => send(f.id, f.name, held.current[f.id], true)}>Send anyway</button>
                        <button type="button" className="rounded-md px-2 py-1 text-ink2"
                          onClick={() => { delete held.current[f.id]; patch(f.id, { status: "refused", warning: null, problem: "Not sent" }); }}>Don't send</button>
                      </div>
                    </div>
                  ) : f.problem ? (
                    <p className="text-xs" style={{ color: "var(--critical)" }}>{f.problem}</p>
                  ) : (
                    <>
                      <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-page">
                        <span className={`block h-full rounded-full ${f.status === "sending" ? "animate-pulse" : ""}`}
                          style={{ width: f.status === "sent" ? "100%" : "60%", background: "var(--brand-yellow)" }} />
                      </span>
                      {f.message && <p className="mt-1 text-xs text-muted">{f.message}</p>}
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
          { key: "source", header: "Source", sort: true, render: (r) => <span className="font-medium">{r.source}</span> },
          { key: "type", header: "Type", sort: true },
          { key: "data", header: "Data", sort: true },
          { key: "received", header: "Records received", align: "right", sort: true, render: (r) => formatNumber(r.received, 0) },
          {
            key: "status",
            header: "Status",
            sort: (r) => (PILL[r.status] || [r.status])[0],
            render: (r) => (
              <span className="inline-flex flex-col items-start gap-0.5">
                <StatusPill status={r.status} />
                {r.reason && <span className="text-xs text-ink2">{r.reason}</span>}
                {!r.reason && r.held > 0 && <span className="text-xs text-ink2">{formatNumber(r.held, 0)} held back</span>}
              </span>
            ),
          },
          { key: "at", header: "Last run", sort: true, render: (r) => <span className="text-ink2">{formatDateTime(r.at)}</span> },
        ]}
        rows={recent.items}
        defaultSort={{ key: "at", dir: "desc" }}
        rowKey={(r) => `${r.source}|${r.data}|${r.at}`}
      />
    </section>
  );
}
