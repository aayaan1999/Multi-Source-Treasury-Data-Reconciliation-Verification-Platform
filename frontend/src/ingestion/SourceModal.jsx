import { useMemo, useState } from "react";
import { api } from "../api";
import Modal from "../components/Modal";
import { Spinner } from "./Toasts";
import { filledValues, formProblems, initialValues } from "./forms";

const INPUT = "w-full rounded-md border bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted transition-colors focus:border-accent focus:outline-none";
const BTN = "inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50";

/**
 * Connect or configure one source. The form is drawn from the source's field list (app/connectors.py);
 * "Connect & Save" stays disabled until every required field is filled and well-formed. Passwords, keys
 * and tokens are never shown back: a connected source's form starts with them empty.
 */
export default function SourceModal({ source, onClose, onSaved, onDisconnected, onSync, notify }) {
  const [values, setValues] = useState(() => initialValues(source));
  const [touched, setTouched] = useState({});
  const [busy, setBusy] = useState("");            // "", "test", "save", "disconnect"
  const [result, setResult] = useState(null);      // { ok, text }
  const problems = useMemo(() => formProblems(source.fields, values), [source.fields, values]);
  const valid = Object.keys(problems).length === 0;
  const connected = source.status === "connected";

  function set(key, value) {
    setValues((v) => ({ ...v, [key]: value }));
    setResult(null);
  }

  async function run(kind, action) {
    setBusy(kind);
    setResult(null);
    try {
      await action();
    } catch (e) {
      setResult({ ok: false, text: e.message });
    } finally {
      setBusy("");
    }
  }

  const test = () => run("test", async () => {
    const r = await api.testSource(source.key, filledValues(source.fields, values));
    setResult({ ok: r.ok, text: r.message });
    notify(`${source.name}: details checked`, "success");
  });

  const save = (e) => {
    e.preventDefault();
    setTouched(Object.fromEntries(source.fields.map((f) => [f.key, true])));
    if (!valid) return;
    run("save", async () => {
      const r = await api.connectSource(source.key, filledValues(source.fields, values));
      onSaved(r.source, r.message);
    });
  };

  const disconnect = () => run("disconnect", async () => {
    const r = await api.disconnectSource(source.key);
    onDisconnected(r.source);
  });

  if (source.builtin) {
    return (
      <Modal title={source.name} onClose={onClose}>
        <p className="text-sm text-ink2">{source.detail}</p>
        <p className="mt-2 text-sm text-ink2">
          Part of the pipeline itself: files dropped in the landing volume start a run automatically. There is nothing
          to configure here.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className={`${BTN} border border-hair text-ink hover:bg-page`}>Close</button>
          <button type="button" onClick={() => { onSync(source); onClose(); }} className={`${BTN} btn-dark`}>Sync now</button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={connected ? `Configure ${source.name}` : `Connect ${source.name}`} onClose={busy ? () => {} : onClose}>
      <form onSubmit={save} noValidate className="grid gap-4">
        <p className="text-sm text-ink2">
          {connected
            ? "Saved settings are filled in. Passwords, keys and tokens aren't kept by the app, so enter them again to save changes."
            : `Enter the details the Databricks pipeline uses to pull data from ${source.name}. Passwords, keys and tokens go to the pipeline's secret store, never to the app's database.`}
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          {source.fields.map((f) => {
            const id = `src-${source.key}-${f.key}`;
            const problem = touched[f.key] && problems[f.key];
            return (
              <div key={f.key} className={f.kind === "url" ? "sm:col-span-2" : ""}>
                <label htmlFor={id} className="mb-1 flex items-center gap-1.5 text-sm font-medium text-ink">
                  {f.label}
                  {!f.required && <span className="text-xs font-normal text-muted">(optional)</span>}
                  {f.kind === "secret" && <span className="text-xs font-normal text-muted">· kept secret</span>}
                </label>
                <input
                  id={id}
                  type={f.kind === "secret" ? "password" : f.kind === "url" ? "url" : "text"}
                  inputMode={f.kind === "port" ? "numeric" : undefined}
                  autoComplete={f.kind === "secret" ? "new-password" : "off"}
                  value={values[f.key]}
                  placeholder={f.placeholder}
                  aria-invalid={problem ? "true" : undefined}
                  aria-describedby={problem ? `${id}-problem` : undefined}
                  onChange={(e) => set(f.key, e.target.value)}
                  onBlur={() => setTouched((t) => ({ ...t, [f.key]: true }))}
                  className={`${INPUT} ${problem ? "border-[var(--critical)]" : "border-hair"}`}
                />
                {problem && <p id={`${id}-problem`} className="mt-1 text-xs" style={{ color: "var(--critical)" }}>{problem}</p>}
              </div>
            );
          })}
        </div>

        {result && (
          <p role="status" className="rounded-md px-3 py-2 text-sm"
            style={{ color: result.ok ? "var(--good)" : "var(--critical)", background: `color-mix(in srgb, ${result.ok ? "var(--good)" : "var(--critical)"} 10%, transparent)` }}>
            {result.ok ? "✓ " : ""}{result.text}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-hair pt-4">
          <div>
            {connected && (
              <button type="button" onClick={disconnect} disabled={!!busy} className={`${BTN} border border-hair text-[var(--critical)] hover:bg-page`}>
                {busy === "disconnect" && <Spinner />}Disconnect
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onClose} disabled={!!busy} className={`${BTN} border border-hair text-ink hover:bg-page`}>Cancel</button>
            <button type="button" onClick={test} disabled={!valid || !!busy} className={`${BTN} border border-hair text-ink hover:border-accent/40 hover:bg-page`}>
              {busy === "test" && <Spinner />}Test connection
            </button>
            <button type="submit" disabled={!valid || !!busy} className={`${BTN} btn-dark`}>
              {busy === "save" && <Spinner />}{busy === "save" ? "Connecting…" : "Connect & Save"}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
