import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import DataTable from "../components/DataTable";
import { ExportButton } from "../components/PageShell";
import { formatDateTime, formatDay, formatDayShort } from "../kpi/format";
import { DRILL, barsFor, formatCell, NUMERIC_UNITS, refinedFilters, summarise } from "./answer";
import { clearAskHistory, loadAskHistory, loadMoreAskHistory, openPrevious, runAsk, useAskHistory } from "./store";

const EXAMPLES = ["Records rejected in the latest load", "NPL ratio by country", "Top 5 branches by profit", "Open limit breaches", "What is our capital adequacy ratio?"];
const MAX_LENGTH = 300;
const CHIP = "rounded-full border border-hair bg-surface px-3 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:text-ink disabled:opacity-60";
const BUTTON = "rounded-md border border-hair bg-surface px-3 py-1.5 text-sm font-medium text-ink transition-colors hover:border-accent/40 disabled:opacity-60";

/**
 * The AI assistant tab (specs/ask-a-question.md, CHT-3; layout from the client demo deck, slide 12): a
 * chat on the left - your question in a dark bubble, the answer beside the assistant's mark with a
 * one-line summary, the table or bars, a link to the screen with the rows behind it and the sources -
 * and on the right what it reads from, your scope, how answers work and your recent questions.
 *
 * The model on the server only picks which approved question it is; every number comes from the
 * database. The "What I understood" chips can be changed or removed, which re-runs without the model.
 * Every answer is saved on the server for the user who asked it: this login's answers are in the chat,
 * earlier ones under Recent questions (the newest 5, then 10 more per "Show more"); opening one puts it
 * back in the chat as it was saved. The history lives in ./store, so switching tabs keeps it.
 */
export default function AskPanel() {
  const { answers, busy } = useAskHistory();
  const [question, setQuestion] = useState("");
  const endRef = useRef(null);
  const chat = [...answers].reverse();          // the store is newest first; a chat reads top to bottom

  useEffect(() => {
    loadAskHistory();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [answers.length, answers[0]?.pending]);

  function submit(e) {
    e.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    runAsk({ question: text });
    setQuestion("");
  }

  return (
    <div className="mt-5 grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <section aria-label="Conversation" className="card flex min-h-[34rem] flex-col rounded-xl border border-hair bg-surface">
        <div className="flex-1 space-y-6 overflow-y-auto p-5 lg:max-h-[68vh]" aria-live="polite">
          {chat.length === 0 && <Welcome />}
          {chat.map((a) => (
            <Exchange key={a.id} answer={a} busy={busy} onAsk={(q) => runAsk({ question: q })} onRefine={(query, filters) => runAsk({ question: a.question, query, filters }, a.id)} />
          ))}
          <div ref={endRef} />
        </div>
        <form onSubmit={submit} className="border-t border-hair p-5 pt-4">
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button key={example} type="button" disabled={busy} onClick={() => runAsk({ question: example })} className={CHIP}>
                {example}
              </button>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2 rounded-xl border border-ink/60 bg-surface p-1.5 pl-4 focus-within:border-accent">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={MAX_LENGTH}
              aria-label="Ask a question about your data or reports"
              placeholder="Ask a question about your data or reports…"
              className="min-w-0 flex-1 bg-transparent py-2 text-[0.95rem] text-ink placeholder:text-muted focus:outline-none"
            />
            <button type="submit" aria-label="Ask" disabled={busy || !question.trim()} className="btn-brand grid h-10 w-10 place-items-center rounded-lg transition disabled:opacity-50">
              <ArrowIcon />
            </button>
          </div>
        </form>
      </section>
      <Sidebar />
    </div>
  );
}

function Welcome() {
  return (
    <div className="flex gap-3">
      <Mark />
      <div className="max-w-xl rounded-xl border border-hair p-4 text-sm text-ink">
        Ask about the ingested data and the reports in plain language - KPIs, countries, branches, segments, products,
        IFRS 9 stages, exposures, ageing, data quality or limit breaches. Every answer comes from the same verified tables
        as the reports, with its sources.
      </div>
    </div>
  );
}

function Mark() {
  return (
    <span aria-hidden className="chat-mark grid h-8 w-8 shrink-0 place-items-center rounded-lg">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2l2.2 7.8L22 12l-7.8 2.2L12 22l-2.2-7.8L2 12l7.8-2.2z" /></svg>
    </span>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

/** One question (right, dark bubble) and its answer (left, beside the assistant's mark). */
function Exchange({ answer, busy, onAsk, onRefine }) {
  return (
    <article aria-busy={answer.pending ? "true" : undefined} className="space-y-3">
      <div className="flex justify-end">
        <p className="chat-question max-w-[85%] rounded-xl px-4 py-2.5 text-sm font-medium">{answer.question || answer.understood?.label}</p>
      </div>
      <div className="flex gap-3">
        <Mark />
        <div className="min-w-0 max-w-full flex-1 rounded-xl border border-hair p-4 lg:max-w-[46rem]">
          <AnswerBody answer={answer} busy={busy} onAsk={onAsk} onRefine={onRefine} />
        </div>
      </div>
    </article>
  );
}

function AnswerBody({ answer, busy, onAsk, onRefine }) {
  if (answer.pending) return <p className="text-sm text-ink2">Working it out…</p>;
  if (answer.status === "error") return <p role="alert" className="text-sm" style={{ color: "var(--critical)" }}>{answer.message}</p>;
  if (answer.status === "unsupported") return <Explanation explanation={answer.explanation} examples={answer.examples} busy={busy} onAsk={onAsk} onRefine={onRefine} />;
  if (answer.status === "clarify") {
    return (
      <div>
        <p className="text-sm font-semibold text-ink">{answer.clarify.question}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {answer.clarify.options.map((option) => (
            <button key={option.label} type="button" disabled={busy} onClick={() => onRefine(option.query, option.filters)} className={BUTTON}>{option.label}</button>
          ))}
        </div>
      </div>
    );
  }
  if (answer.status !== "answer") return null;
  return <Answer answer={answer} busy={busy} onAsk={onAsk} onRefine={onRefine} />;
}

function Answer({ answer, busy, onAsk, onRefine }) {
  const { understood } = answer;
  const bars = barsFor(answer);
  const [asTable, setAsTable] = useState(false);
  const summary = summarise(answer);
  const drill = DRILL[understood.query];
  return (
    <>
      <p className="text-[0.95rem] text-ink">
        <b>{summary.lead}</b> {summary.rest}
        {drill && (
          <>
            {" "}
            <Link to={drill.to} className="font-semibold text-ink underline decoration-[var(--brand-yellow)] decoration-2 underline-offset-4">{drill.label}</Link>
          </>
        )}
      </p>
      {answer.notices?.map((notice) => (
        <div key={notice.code + notice.message} className="mt-3 rounded-lg border-l-4 bg-page px-3 py-2" style={{ borderColor: "var(--brand-yellow)" }} role="note">
          <div className="text-xs font-semibold uppercase tracking-wider text-ink2">{notice.title}</div>
          <p className="mt-0.5 text-sm text-ink">{notice.message}</p>
          {notice.suggestions?.length > 0 && <Suggestions items={notice.suggestions} busy={busy} onAsk={onAsk} onRefine={onRefine} />}
        </div>
      ))}
      <div className="mt-3">
        {bars && !asTable ? <Bars bars={bars} caption={understood.label} /> : (
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
        )}
        {bars && (
          <button type="button" onClick={() => setAsTable(!asTable)} className="mt-2 text-xs text-ink2 underline-offset-4 hover:text-ink hover:underline">
            {asTable ? "Show as chart" : "Show as table"}
          </button>
        )}
      </div>
      <Chips understood={understood} busy={busy} onRefine={onRefine} />
      {answer.ignored?.length > 0 && <p className="mt-2 text-xs text-ink2">Not applied to this question: {answer.ignored.join(", ")}</p>}
      {answer.notes?.map((note) => <p key={note} className="mt-1 text-xs text-muted">{note}</p>)}
      <footer className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-hair pt-3 text-xs text-muted">
        <span className="flex flex-wrap items-center gap-1.5">
          Sources:
          <span className="rounded-md border border-hair px-2 py-0.5 text-ink2" title={`Data as of ${formatDay(answer.source.as_of)}`}>
            {answer.source.table} · {formatDayShort(answer.source.as_of)}
          </span>
          <span className="rounded-md border border-hair px-2 py-0.5 text-ink2">Approved query · {understood.label}</span>
        </span>
        <ExportButton label="Export to Excel" onExport={() => api.exportAsk({ question: answer.question, query: understood.query, filters: understood.filters })} />
      </footer>
    </>
  );
}

/** One measure across named rows as horizontal bars; the value is always written next to its bar. */
function Bars({ bars, caption }) {
  return (
    <ul aria-label={caption} className="space-y-2">
      {bars.map((b, i) => (
        <li key={b.label} className="grid grid-cols-[minmax(6rem,11rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate text-ink2" title={b.label}>{b.label}</span>
          <span className="h-2.5 rounded-full bg-page">
            <span
              className="block h-full rounded-full"
              style={{ width: `${Math.max(2, b.share * 100)}%`, background: b.negative ? "var(--critical)" : i === 0 ? "var(--brand-yellow)" : "var(--ink)" }}
            />
          </span>
          <span className="text-right tabular-nums text-ink">{b.value}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Why a question couldn't be answered as asked (specs/ask-a-question.md section 6.7): what went wrong in
 * plain words, how the assistant works, and buttons for what to ask instead - never a table that answers
 * a different question.
 */
function Explanation({ explanation, examples, busy, onAsk, onRefine }) {
  const e = explanation || {
    title: "That's not a question about the bank's reports",
    why: "I can only answer questions about the bank's reports.",
    suggestions: (examples || []).map((q) => ({ label: q, question: q })),
  };
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wider text-ink2">Why I couldn't answer this</div>
      <p className="mt-1 text-base font-semibold text-ink">{e.title}</p>
      <p className="mt-1 text-sm text-ink2">{e.why}</p>
      {e.suggestions?.length > 0 && (
        <>
          <div className="mt-3 text-xs font-semibold uppercase tracking-wider text-ink2">You could ask</div>
          <Suggestions items={e.suggestions} busy={busy} onAsk={onAsk} onRefine={onRefine} />
        </>
      )}
      {e.how && <p className="mt-3 rounded-lg bg-page p-3 text-xs text-ink2">{e.how}</p>}
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
          <button key={s.label} type="button" disabled={busy} onClick={() => (s.query ? onRefine(s.query, s.filters) : onAsk(s.question))} className={BUTTON}>
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
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span className="text-xs text-muted">What I understood:</span>
      <ul className="flex flex-wrap gap-2" aria-label="What I understood">
        {understood.chips.map((chip) => (
          <li key={chip.key} className="inline-flex items-center gap-1.5 rounded-md border border-hair bg-page px-2 py-0.5 text-xs text-ink">
            <span className="text-muted">{chip.label}</span>
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

// ---- the right-hand panel ------------------------------------------------------------------------------

function PanelSection({ title, children, id }) {
  return (
    <section aria-labelledby={id} className="border-b border-hair p-5 last:border-0">
      <h2 id={id} className="text-xs font-semibold uppercase tracking-[0.12em] text-ink2">{title}</h2>
      {children}
    </section>
  );
}

function when(iso) {
  if (!iso) return "";
  return iso.length > 10 ? formatDateTime(iso) : formatDay(iso);
}

/** Querying, Scope, How answers work, Recent questions (GET /ask/context and the saved history). */
function Sidebar() {
  const [context, setContext] = useState(null);
  const [contextError, setContextError] = useState(false);
  const { answers, previous, hasMore, loadingMore, historyError, busy } = useAskHistory();

  useEffect(() => {
    let live = true;
    api.askContext().then((c) => live && setContext(c)).catch(() => live && setContextError(true));
    return () => {
      live = false;
    };
  }, []);

  return (
    <aside className="card rounded-xl border border-hair bg-surface" aria-label="About the assistant">
      <PanelSection title="Querying" id="ask-querying">
        {contextError && <p className="mt-2 text-sm text-ink2">Couldn't load what the assistant reads from.</p>}
        {!context && !contextError && <p className="mt-2 text-sm text-ink2">Loading…</p>}
        <ul className="mt-2 space-y-2.5">
          {context?.areas.map((a) => (
            <li key={a.key} className="flex items-start justify-between gap-3 text-sm" title={a.answerable ? "The assistant answers from this" : "Not answerable yet - on the backlog"}>
              <span className="flex items-center gap-2">
                <span
                  aria-hidden
                  className={`grid h-4 w-4 place-items-center rounded-[4px] border ${a.answerable ? "border-transparent" : "border-hair"}`}
                  style={a.answerable ? { background: "var(--ink)", color: "var(--surface-1)" } : undefined}
                >
                  {a.answerable && <svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2.5 6.2l2.3 2.3 4.7-5" /></svg>}
                </span>
                <span className={a.answerable ? "font-semibold text-ink" : "text-ink2"}>{a.label}</span>
                <span className="sr-only">{a.answerable ? "(answers from this)" : "(not answerable yet)"}</span>
              </span>
              <span className="text-right text-ink2">{a.as_of && a.key === "load" ? formatDateTime(a.as_of) : a.detail}</span>
            </li>
          ))}
        </ul>
        {context?.areas.some((a) => !a.answerable) && (
          <p className="mt-3 text-xs text-muted">Unticked areas are shown for context; questions about them come later.</p>
        )}
      </PanelSection>

      <PanelSection title="Scope" id="ask-scope">
        <dl className="mt-2 space-y-2 text-sm">
          {[
            ["Countries", context?.scope.countries.join(", ") || "—"],
            ["Period", context?.scope.period || "—"],
            ["Access", context?.scope.access || "—"],
          ].map(([term, value]) => (
            <div key={term} className="flex justify-between gap-3">
              <dt className="text-ink2">{term}</dt>
              <dd className="text-right font-semibold text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      </PanelSection>

      <PanelSection title="How answers work" id="ask-how">
        <p className="mt-2 text-sm text-ink2">
          Answers are read from the same verified tables as the reports. The model running inside the bank only picks which
          approved question you mean - it never writes a number. Every number carries its source, and each question is
          written to the audit trail.
        </p>
      </PanelSection>

      <PanelSection title="Recent questions" id="ask-recent">
        {historyError && <p role="alert" className="mt-2 text-sm" style={{ color: "var(--critical)" }}>{historyError}</p>}
        {previous.length === 0 && !hasMore && !historyError && <p className="mt-2 text-sm text-muted">Your earlier questions appear here.</p>}
        <ul className="mt-2 space-y-1">
          {previous.map((a) => (
            <li key={a.id}>
              <button type="button" onClick={() => openPrevious(a.id)} className="w-full rounded-md px-2 py-1.5 text-left text-sm text-ink2 transition-colors hover:bg-page hover:text-ink" title={a.asked_at ? `Asked ${when(a.asked_at)} - open this answer` : "Open this answer"}>
                {a.question || a.understood?.label}
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          {hasMore ? (
            <button type="button" disabled={loadingMore} onClick={loadMoreAskHistory} className={BUTTON}>
              {loadingMore ? "Loading…" : "Show more"}
            </button>
          ) : <span />}
          {(answers.length > 0 || previous.length > 0) && (
            <button type="button" disabled={busy} onClick={clearAskHistory} className="text-xs text-muted underline-offset-4 hover:text-ink hover:underline disabled:opacity-60">
              Clear these answers
            </button>
          )}
        </div>
      </PanelSection>
    </aside>
  );
}
