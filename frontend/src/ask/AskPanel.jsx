import { useState } from "react";
import { ApiError, api } from "../api";
import DataTable from "../components/DataTable";
import { ExportButton } from "../components/PageShell";
import { formatDay } from "../kpi/format";
import { formatCell, NUMERIC_UNITS, refinedFilters } from "./answer";

const EXAMPLES = ["NPL ratio by country", "Top 5 branches by profit", "What is our capital adequacy ratio?", "IFRS 9 staging"];
const MAX_LENGTH = 300;
const BUTTON = "rounded-md border border-hair px-2.5 py-1 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60";

let nextId = 1;

/**
 * Ask a Question (specs/ask-a-question.md, CHT-3): a typed question becomes one approved query's
 * table. The model on the server only picks which question it is; every number comes from the
 * database. Chips show what was understood and can be changed or removed, which re-runs without the
 * model. Answers stay listed (newest first) for this visit only.
 */
export default function AskPanel() {
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState([]);
  const [busy, setBusy] = useState(false);

  async function run(body, replaceId) {
    const id = replaceId ?? nextId++;
    const pending = { id, question: body.question, pending: true };
    setAnswers((list) => (replaceId ? list.map((a) => (a.id === id ? { ...a, pending: true } : a)) : [pending, ...list]));
    setBusy(true);
    let result;
    try {
      result = { id, ...(await api.ask(body)) };
    } catch (e) {
      const unavailable = e instanceof ApiError && e.status === 503;
      result = { id, question: body.question, status: "error", message: unavailable ? "Ask a question isn't available right now - the model server isn't running." : e.message };
    }
    setAnswers((list) => list.map((a) => (a.id === id ? result : a)));
    setBusy(false);
  }

  function submit(e) {
    e.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    run({ question: text });
    setQuestion("");
  }

  return (
    <div>
      <form onSubmit={submit} className="card flex flex-wrap items-center gap-2 rounded-xl border border-hair bg-surface p-3">
        <label htmlFor="ask-question" className="sr-only">Ask a question about the reports</label>
        <input
          id="ask-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={MAX_LENGTH}
          placeholder="e.g. NPL ratio by country, or top 5 branches by profit"
          className="min-w-[16rem] flex-1 rounded-md border border-hair bg-page px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-accent focus:outline-none"
        />
        <button type="submit" disabled={busy || !question.trim()} className={`${BUTTON} px-3 py-2`}>
          Ask
        </button>
        <div className="flex w-full flex-wrap items-center gap-2 pt-1 text-xs text-ink2">
          <span>Try:</span>
          {EXAMPLES.map((example) => (
            <button key={example} type="button" disabled={busy} onClick={() => run({ question: example })} className="rounded-full border border-hair px-2.5 py-0.5 hover:border-accent/40 hover:text-ink disabled:opacity-60">
              {example}
            </button>
          ))}
        </div>
      </form>
      <div className="mt-4 space-y-4" aria-live="polite">
        {answers.map((a) => (
          <AnswerCard key={a.id} answer={a} busy={busy} onAsk={(q) => run({ question: q })} onRefine={(query, filters) => run({ question: a.question, query, filters }, a.id)} />
        ))}
      </div>
    </div>
  );
}

function AnswerCard({ answer, busy, onAsk, onRefine }) {
  const { understood } = answer;
  return (
    <article className="card rounded-xl border border-hair bg-surface p-4" aria-busy={answer.pending ? "true" : undefined}>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">{answer.question ? `“${answer.question}”` : understood?.label}</h3>
        {understood?.label && answer.question && <span className="text-xs text-ink2">{understood.label}</span>}
      </header>

      {answer.pending && <p className="mt-3 text-sm text-ink2">Working it out…</p>}

      {!answer.pending && answer.status === "error" && (
        <p role="alert" className="mt-3 text-sm" style={{ color: "var(--critical)" }}>{answer.message}</p>
      )}

      {!answer.pending && answer.status === "unsupported" && (
        <div className="mt-3 text-sm text-ink2">
          <p>I can only answer questions about the bank's reports: KPIs, countries, branches, segments, products, IFRS 9 stages, exposures, ageing, data quality and limit breaches.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {(answer.examples || []).map((example) => (
              <button key={example} type="button" disabled={busy} onClick={() => onAsk(example)} className={BUTTON}>{example}</button>
            ))}
          </div>
        </div>
      )}

      {!answer.pending && answer.status === "clarify" && (
        <div className="mt-3">
          <p className="text-sm text-ink">{answer.clarify.question}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {answer.clarify.options.map((option) => (
              <button key={option.label} type="button" disabled={busy} onClick={() => onRefine(option.query, option.filters)} className={BUTTON}>{option.label}</button>
            ))}
          </div>
        </div>
      )}

      {!answer.pending && answer.status === "answer" && (
        <>
          <Chips understood={understood} busy={busy} onRefine={onRefine} />
          {answer.ignored?.length > 0 && <p className="mt-2 text-xs text-ink2">Not applied to this question: {answer.ignored.join(", ")}</p>}
          <div className="mt-3">
            <DataTable
              caption={understood.label}
              columns={answer.columns.map((c) => ({
                key: c.key,
                header: c.label,
                align: NUMERIC_UNITS.has(c.unit) ? "right" : "left",
                render: (row) => formatCell(row[c.key], c.unit, row),
              }))}
              rows={answer.rows}
              rowKey={(row) => JSON.stringify(row)}
              emptyText="No rows match these filters."
            />
          </div>
          <footer className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-ink2">
            <span>Source: {answer.source.table} · data as of {formatDay(answer.source.as_of)}</span>
            <ExportButton label="Export to Excel" onExport={() => api.exportAsk({ question: answer.question, query: understood.query, filters: understood.filters })} />
          </footer>
          {answer.notes?.map((note) => <p key={note} className="mt-1 text-xs text-muted">{note}</p>)}
        </>
      )}
    </article>
  );
}

function Chips({ understood, busy, onRefine }) {
  const change = (key, value) => onRefine(understood.query, refinedFilters(understood.filters, key, value));
  return (
    <ul className="mt-3 flex flex-wrap gap-2" aria-label="What I understood">
      {understood.chips.map((chip) => (
        <li key={chip.key} className="inline-flex items-center gap-1.5 rounded-full border border-hair bg-page px-2.5 py-0.5 text-xs text-ink">
          <span className="text-ink2">{chip.label}:</span>
          {chip.options.length > 0 ? (
            <select
              aria-label={chip.label}
              value={chip.value ?? ""}
              disabled={busy}
              onChange={(e) => change(chip.key, e.target.value)}
              className="bg-transparent text-xs text-ink focus:outline-none"
            >
              {chip.options.map((o) => <option key={o.value} value={o.value}>{o.text}</option>)}
            </select>
          ) : (
            <span>{chip.text}</span>
          )}
          {chip.removable && (
            <button type="button" disabled={busy} onClick={() => change(chip.key, null)} aria-label={`Remove ${chip.label.toLowerCase()} ${chip.text}`} className="text-ink2 hover:text-ink">
              ×
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
