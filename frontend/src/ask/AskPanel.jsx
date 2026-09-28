import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import DataTable from "../components/DataTable";
import { ExportButton } from "../components/PageShell";
import { formatDay } from "../kpi/format";
import { formatCell, NUMERIC_UNITS, refinedFilters } from "./answer";
import { clearAskHistory, runAsk, useAskHistory } from "./store";

const EXAMPLES = ["NPL ratio by country", "Top 5 branches by profit", "What is our capital adequacy ratio?", "IFRS 9 staging", "Open limit breaches"];
const MAX_LENGTH = 300;
const BUTTON = "ask-chip px-3 py-1.5 text-sm font-semibold transition-colors disabled:opacity-60";

/**
 * Ask a Question (specs/ask-a-question.md, CHT-3): a typed question becomes one approved query's
 * table. The model on the server only picks which question it is; every number comes from the
 * database. Chips show what was understood and can be changed or removed, which re-runs without the
 * model. Answers stay listed (newest first, up to 20) until the browser tab closes or you log out -
 * the history lives in ./store, not in this component, so switching tabs keeps it. Styled by the
 * .ask-* classes (the client demo overview's look), on the Ask a question tab.
 */
export default function AskPanel() {
  const [question, setQuestion] = useState("");
  const { answers, busy } = useAskHistory();
  const run = runAsk;

  function submit(e) {
    e.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    run({ question: text });
    setQuestion("");
  }

  return (
    <div>
      <form onSubmit={submit} className="ask-card">
        <label htmlFor="ask-question" className="ask-label">Ask a question about the reports</label>
        <div className="mt-2 flex flex-wrap items-stretch gap-2">
          <input
            id="ask-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={MAX_LENGTH}
            placeholder="e.g. NPL ratio by country, or top 5 branches by profit"
            className="min-w-[16rem] flex-1 border border-hair bg-page px-3 py-2.5 text-[0.95rem] text-ink placeholder:text-muted focus:border-accent focus:outline-none"
          />
          <button type="submit" disabled={busy || !question.trim()} className="ask-primary px-5 py-2.5 text-sm transition disabled:opacity-60">
            Ask
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="ask-label gold mr-1">Try</span>
          {EXAMPLES.map((example) => (
            <button key={example} type="button" disabled={busy} onClick={() => run({ question: example })} className="ask-chip rounded-full px-3 py-1 text-xs transition-colors disabled:opacity-60">
              {example}
            </button>
          ))}
        </div>
      </form>
      {answers.length > 0 && (
        <div className="mt-4 flex justify-end">
          <button type="button" disabled={busy} onClick={clearAskHistory} className="text-xs text-muted underline-offset-4 hover:text-ink hover:underline disabled:opacity-60">
            Clear these answers
          </button>
        </div>
      )}
      <div className="mt-2 space-y-5" aria-live="polite">
        {answers.map((a, i) => (
          <AnswerCard key={a.id} answer={a} gold={i % 2 === 1} busy={busy} onAsk={(q) => run({ question: q })} onRefine={(query, filters) => run({ question: a.question, query, filters }, a.id)} />
        ))}
      </div>
    </div>
  );
}

function AnswerCard({ answer, gold, busy, onAsk, onRefine }) {
  const { understood } = answer;
  return (
    <article className={`ask-card${gold ? " gold" : ""}`} aria-busy={answer.pending ? "true" : undefined}>
      <header>
        {understood?.label && <div className="ask-label">{understood.label}</div>}
        <h3 className="mt-1 text-base font-extrabold text-ink">{answer.question ? `“${answer.question}”` : understood?.label}</h3>
      </header>

      {answer.pending && <p className="mt-3 text-sm text-ink2">Working it out…</p>}

      {!answer.pending && answer.status === "error" && (
        <p role="alert" className="mt-3 text-sm" style={{ color: "var(--critical)" }}>{answer.message}</p>
      )}

      {!answer.pending && answer.status === "unsupported" && (
        <Explanation explanation={answer.explanation} examples={answer.examples} busy={busy} onAsk={onAsk} onRefine={onRefine} />
      )}

      {!answer.pending && answer.status === "clarify" && (
        <div className="ask-card soft mt-3">
          <div className="ask-label gold">One question first</div>
          <p className="mt-1 text-sm font-semibold text-ink">{answer.clarify.question}</p>
          <div className="mt-3 flex flex-wrap gap-2">
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
          {answer.notices?.map((notice) => (
            <div key={notice.code + notice.message} className="ask-notice mt-3" role="note">
              <div className="ask-label gold">{notice.title}</div>
              <p className="mt-0.5 text-sm text-ink">{notice.message}</p>
              {notice.suggestions?.length > 0 && <Suggestions items={notice.suggestions} busy={busy} onAsk={onAsk} onRefine={onRefine} />}
            </div>
          ))}
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
          <footer className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-hair pt-3 text-xs text-muted">
            <span>
              <span className="ask-label mr-2">Source</span>
              {answer.source.table} · data as of {formatDay(answer.source.as_of)}
            </span>
            <ExportButton label="Export to Excel" onExport={() => api.exportAsk({ question: answer.question, query: understood.query, filters: understood.filters })} />
          </footer>
          {answer.notes?.map((note) => <p key={note} className="mt-1 text-xs text-muted">{note}</p>)}
        </>
      )}
    </article>
  );
}

/**
 * Why a question couldn't be answered as asked (specs/ask-a-question.md section 6.7): what went wrong in
 * plain words, how the panel works, and buttons for what to ask instead - never a table that answers a
 * different question.
 */
function Explanation({ explanation, examples, busy, onAsk, onRefine }) {
  const e = explanation || {
    title: "That's not a question about the bank's reports",
    why: "I can only answer questions about the bank's reports.",
    suggestions: (examples || []).map((q) => ({ label: q, question: q })),
  };
  return (
    <div className="mt-3">
      <div className="ask-label gold">Why I couldn't answer this</div>
      <p className="mt-1 text-base font-extrabold text-ink">{e.title}</p>
      <p className="mt-1 text-sm text-ink2">{e.why}</p>
      {e.suggestions?.length > 0 && (
        <>
          <div className="ask-label mt-3">You could ask</div>
          <Suggestions items={e.suggestions} busy={busy} onAsk={onAsk} onRefine={onRefine} />
        </>
      )}
      {e.how && <p className="ask-card soft mt-3 text-xs text-ink2">{e.how}</p>}
    </div>
  );
}

/** Buttons: a question to ask, a ready-made query to run in place, or another tab. */
function Suggestions({ items, busy, onAsk, onRefine }) {
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {items.map((s) =>
        s.href ? (
          <Link key={s.label} to={s.href} className={`${BUTTON} inline-block`}>{s.label} →</Link>
        ) : (
          <button
            key={s.label}
            type="button"
            disabled={busy}
            onClick={() => (s.query ? onRefine(s.query, s.filters) : onAsk(s.question))}
            className={BUTTON}
          >
            {s.label}
          </button>
        ),
      )}
    </div>
  );
}

function Chips({ understood, busy, onRefine }) {
  const change = (key, value) => onRefine(understood.query, refinedFilters(understood.filters, key, value));
  return (
    <div className="mt-3">
      <div className="ask-label gold">What I understood</div>
      <ul className="mt-1.5 flex flex-wrap gap-2" aria-label="What I understood">
        {understood.chips.map((chip) => (
          <li key={chip.key} className="inline-flex items-center gap-1.5 border border-hair bg-page px-2.5 py-1 text-xs text-ink">
            <span className="font-bold uppercase tracking-wider text-muted" style={{ fontSize: "0.62rem" }}>{chip.label}</span>
            {chip.options.length > 0 ? (
              <select
                aria-label={chip.label}
                value={chip.value ?? ""}
                disabled={busy}
                onChange={(e) => change(chip.key, e.target.value)}
                className="bg-transparent text-xs font-semibold text-ink focus:outline-none"
              >
                {chip.options.map((o) => <option key={o.value} value={o.value}>{o.text}</option>)}
              </select>
            ) : (
              <span className="font-semibold">{chip.text}</span>
            )}
            {chip.removable && (
              <button type="button" disabled={busy} onClick={() => change(chip.key, null)} aria-label={`Remove ${chip.label.toLowerCase()} ${chip.text}`} className="text-muted hover:text-ink">
                ×
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
