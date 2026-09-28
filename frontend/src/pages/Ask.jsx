import AskPanel from "../ask/AskPanel";
import TopBar from "../components/TopBar";

const PILLARS = [
  ["Plain English", "ask the way you'd ask a colleague"],
  ["Approved questions only", "a fixed, read-only query behind every answer"],
  ["Straight from the database", "no number is written by the AI"],
  ["On the record", "every question and export is audited"],
];

const STEPS = [
  ["01", "You ask", "Type a question, or pick one of the examples."],
  ["02", "It works out the question", "A model running inside the bank picks which approved report you mean. Nothing leaves the bank."],
  ["03", "It reads the details", "Dates, countries, branches and “top 5” are read from your words by fixed rules, and shown back to you as chips."],
  ["04", "The database answers", "The approved query runs and returns the table, with its source and date. Unsure? It asks instead of guessing."],
];

/**
 * The Ask a question tab (specs/ask-a-question.md). Styled after the client demo overview
 * (project-docs/client-demo/Client-Demo-Overview.html): the .ask-* classes in index.css.
 */
export default function Ask() {
  return (
    <>
      <TopBar />
      <div className="ask-page">
        <main className="mx-auto max-w-7xl px-4 pb-16 pt-7">
          <section className="ask-hero" aria-labelledby="ask-title">
            <div className="ask-eyebrow">Ask a question · Bank data platform</div>
            <h1 id="ask-title">
              Ask the Numbers.
              <br />
              <em>Get the Verified Table.</em>
            </h1>
            <div className="ask-goldbar" />
            <p>
              Type a question about the bank's figures - KPIs, countries, branches, segments, products, IFRS 9 stages,
              exposures, ageing, data quality or limit breaches - and get a table you can check, change and export.
            </p>
            <div className="ask-pillars">
              {PILLARS.map(([title, text]) => (
                <div key={title}>
                  <b>{title}</b>
                  <span>{text}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="mt-9" aria-labelledby="ask-now">
            <div className="ask-eyebrow">Your question</div>
            <h2 id="ask-now" className="ask-h2">What would you like to know?</h2>
            <div className="ask-rule" />
            <AskPanel />
          </section>

          <section className="mt-10" aria-labelledby="ask-how">
            <div className="ask-eyebrow">How it works</div>
            <h2 id="ask-how" className="ask-h2">Every Answer Comes From the Database.</h2>
            <div className="ask-rule" />
            <div className="ask-flow">
              {STEPS.map(([n, title, text]) => (
                <div key={n}>
                  <span className="n">{n}</span>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </div>
              ))}
            </div>
          </section>
        </main>
      </div>
    </>
  );
}
