import AskPanel from "../ask/AskPanel";
import TopBar from "../components/TopBar";

/**
 * The AI assistant tab (specs/ask-a-question.md), laid out as in the client demo deck
 * (project-docs/client-demo/AppBay-Client-Demo.pdf, slide 12): the chat and its side panel are in AskPanel.
 */
export default function Ask() {
  return (
    <>
      <TopBar />
      <main className="mx-auto max-w-7xl px-4 pb-16 pt-7">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Ask about your data</h1>
          <span className="pill-brand">AI data assistant</span>
        </div>
        <AskPanel />
      </main>
    </>
  );
}
