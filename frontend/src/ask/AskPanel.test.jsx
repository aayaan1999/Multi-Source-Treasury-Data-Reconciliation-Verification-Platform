import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AskPanel from "./AskPanel";
import { formatCell, refinedFilters } from "./answer";
import { clearAskHistory } from "./store";
import { api } from "../api";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { ask: vi.fn(), exportAsk: vi.fn() } };
});

const ANSWER = {
  status: "answer",
  question: "top 2 branches by profit",
  understood: {
    query: "branch_ranking",
    label: "Branches ranked",
    filters: { metric: "profit", top_n: 2, order: "desc" },
    chips: [
      { key: "metric", label: "Measure", text: "Profit", value: "profit", removable: false, options: [{ value: "profit", text: "Profit" }, { value: "revenue", text: "Revenue" }] },
      { key: "order", label: "Order", text: "Highest first", value: "desc", removable: false, options: [{ value: "desc", text: "Highest first" }, { value: "asc", text: "Lowest first" }] },
      { key: "top_n", label: "Show", text: "Top 2", value: 2, removable: true, options: [] },
    ],
  },
  columns: [
    { key: "rank", label: "Rank", unit: "number" },
    { key: "branch_name", label: "Branch", unit: "text" },
    { key: "profit_usd", label: "Profit", unit: "usd" },
  ],
  rows: [{ rank: 1, branch_name: "Riyadh Central", profit_usd: 125000 }, { rank: 2, branch_name: "Doha Main", profit_usd: 98000.4 }],
  source: { table: "branch_performance_summary", as_of: "2026-09-28" },
  notes: [],
  ignored: [],
  examples: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  clearAskHistory();
});

async function askIt(text) {
  fireEvent.change(screen.getByLabelText("Ask a question about the reports"), { target: { value: text } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Ask" })));
}

describe("answer helpers", () => {
  it("formats cells by unit, including a unit carried on the row", () => {
    expect(formatCell(125000, "usd")).toBe("$125,000");
    expect(formatCell(12.345, "pct")).toBe("12.3%");
    expect(formatCell(1234, "count")).toBe("1,234");
    expect(formatCell("2026-09-28", "date")).toMatch(/^28 Sept? 2026$/);   // the en-GB month abbreviation varies by ICU version
    expect(formatCell(13.5, "row", { unit: "pct" })).toBe("13.5%");
    expect(formatCell(null, "usd")).toBe("—");
  });

  it("changes or removes one filter and leaves the rest", () => {
    const f = { metric: "profit", order: "desc", top_n: 5, date_from: "2026-08-01", date_to: "2026-08-31", period_label: "August 2026" };
    expect(refinedFilters(f, "top_n", null)).toEqual({ metric: "profit", order: "desc", date_from: "2026-08-01", date_to: "2026-08-31", period_label: "August 2026" });
    expect(refinedFilters(f, "period", null)).toEqual({ metric: "profit", order: "desc", top_n: 5 });
    expect(refinedFilters(f, "metric", "revenue").metric).toBe("revenue");
    expect(refinedFilters(f, "metric", "")).not.toHaveProperty("order");
  });
});

describe("Ask panel", () => {
  it("shows the table, what was understood and the source, and exports the same query", async () => {
    let resolve;
    api.ask.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<AskPanel />);
    await askIt("top 2 branches by profit");
    expect(screen.getByText("Working it out…")).toBeTruthy();
    await act(async () => resolve(ANSWER));

    expect(api.ask).toHaveBeenCalledWith({ question: "top 2 branches by profit" });
    const table = screen.getByRole("table");
    expect(within(table).getByText("Riyadh Central")).toBeTruthy();
    expect(within(table).getByText("$125,000")).toBeTruthy();
    const chips = screen.getByRole("list", { name: "What I understood" });
    expect(within(chips).getByText("Top 2")).toBeTruthy();
    expect(screen.getByText(/branch_performance_summary · data as of 28 Sept? 2026/)).toBeTruthy();

    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Export to Excel" })));
    expect(api.exportAsk).toHaveBeenCalledWith({ question: "top 2 branches by profit", query: "branch_ranking", filters: ANSWER.understood.filters });
  });

  it("changing or removing a chip re-runs that question with the new filters", async () => {
    api.ask.mockResolvedValue(ANSWER);
    render(<AskPanel />);
    await askIt("top 2 branches by profit");
    await act(async () => fireEvent.change(screen.getByLabelText("Measure"), { target: { value: "revenue" } }));
    expect(api.ask).toHaveBeenLastCalledWith({ question: "top 2 branches by profit", query: "branch_ranking", filters: { metric: "revenue", top_n: 2, order: "desc" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Remove show Top 2" })));
    expect(api.ask).toHaveBeenLastCalledWith({ question: "top 2 branches by profit", query: "branch_ranking", filters: { metric: "profit", order: "desc" } });
    expect(screen.getAllByRole("article")).toHaveLength(1);   // refined in place, not added
  });

  it("asks back with buttons instead of guessing", async () => {
    api.ask.mockResolvedValueOnce({
      status: "clarify", question: "rank the branches", understood: { query: "branch_ranking", label: "Branches ranked" },
      clarify: { question: "Which measure should branches ranked use?", options: [{ label: "Profit", query: "branch_ranking", filters: { metric: "profit" } }] },
    }).mockResolvedValueOnce(ANSWER);
    render(<AskPanel />);
    await askIt("rank the branches");
    expect(screen.getByText("Which measure should branches ranked use?")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Profit" })));
    expect(api.ask).toHaveBeenLastCalledWith({ question: "rank the branches", query: "branch_ranking", filters: { metric: "profit" } });
    expect(screen.getByRole("table")).toBeTruthy();
  });

  it("says what it can answer when the question is off-topic", async () => {
    api.ask.mockResolvedValue({ status: "unsupported", question: "tell me a joke", examples: ["NPL ratio by country"] });
    render(<AskPanel />);
    await askIt("tell me a joke");
    expect(screen.getByText(/I can only answer questions about the bank's reports/)).toBeTruthy();
    expect(within(screen.getByRole("article")).getByRole("button", { name: "NPL ratio by country" })).toBeTruthy();
  });

  // The bug reported on 2026-09-28: switching tabs unmounts the panel, and the answers used to go with it.
  it("keeps the answers when you switch tabs and come back", async () => {
    api.ask.mockResolvedValue(ANSWER);
    const first = render(<AskPanel />);
    await askIt("top 2 branches by profit");
    first.unmount();                                   // another tab
    render(<AskPanel />);                              // back to Ask a question
    expect(screen.getByText("“top 2 branches by profit”")).toBeTruthy();
    expect(within(screen.getByRole("table")).getByText("Riyadh Central")).toBeTruthy();
  });

  it("shows an answer that arrived while you were on another tab", async () => {
    let resolve;
    api.ask.mockReturnValue(new Promise((r) => { resolve = r; }));
    const first = render(<AskPanel />);
    await askIt("top 2 branches by profit");
    first.unmount();
    await act(async () => resolve(ANSWER));            // lands while the panel isn't on screen
    render(<AskPanel />);
    expect(within(screen.getByRole("table")).getByText("Riyadh Central")).toBeTruthy();
  });

  it("keeps the answers across a page refresh, and clears them on request", async () => {
    api.ask.mockResolvedValue(ANSWER);
    render(<AskPanel />);
    await askIt("top 2 branches by profit");
    expect(JSON.parse(sessionStorage.getItem("bdp_ask_history"))[0].question).toBe("top 2 branches by profit");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Clear these answers" })));
    expect(screen.queryByRole("article")).toBeNull();
    expect(sessionStorage.getItem("bdp_ask_history")).toBeNull();
  });

  it("explains why it couldn't answer, how it works, and offers what to ask instead", async () => {
    api.ask.mockResolvedValueOnce({
      status: "unsupported", question: "branches except Beirut by profit",
      explanation: {
        code: "negation", title: "I can't leave things out yet",
        why: "Your question says “except”. I can narrow a report to the places you name, but not exclude them.",
        how: "How this works: I match your question to one of the bank's approved reports.",
        suggestions: [{ label: "Show all branches instead", query: "branch_ranking", filters: { metric: "profit", order: "desc" } },
                      { label: "Open Scenario modelling", href: "/scenario" }],
      },
    }).mockResolvedValueOnce(ANSWER);
    render(<MemoryRouter><AskPanel /></MemoryRouter>);
    await askIt("branches except Beirut by profit");
    const card = screen.getByRole("article");
    expect(within(card).getByText("Why I couldn't answer this")).toBeTruthy();
    expect(within(card).getByText("I can't leave things out yet")).toBeTruthy();
    expect(within(card).getByText(/not exclude them/)).toBeTruthy();
    expect(within(card).getByText(/^How this works/)).toBeTruthy();
    expect(within(card).queryByRole("table")).toBeNull();                       // never a misleading table
    expect(within(card).getByRole("link", { name: "Open Scenario modelling →" }).getAttribute("href")).toBe("/scenario");
    await act(async () => fireEvent.click(within(card).getByRole("button", { name: "Show all branches instead" })));
    expect(api.ask).toHaveBeenLastCalledWith({ question: "branches except Beirut by profit", query: "branch_ranking", filters: { metric: "profit", order: "desc" } });
  });

  it("shows a notice above a table when part of the question wasn't applied", async () => {
    api.ask.mockResolvedValue({
      ...ANSWER, question: "branches with profit above 1 million",
      notices: [{ code: "threshold", title: "Your limit isn't applied", message: "I can't filter by “above 1 million” yet, so this shows every row." }],
    });
    render(<AskPanel />);
    await askIt("branches with profit above 1 million");
    const note = screen.getByRole("note");
    expect(within(note).getByText("Your limit isn't applied")).toBeTruthy();
    expect(within(note).getByText(/above 1 million/)).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
  });

  it("says plainly when the model server isn't running", async () => {
    const { ApiError } = await import("../api");
    api.ask.mockRejectedValue(new ApiError(503, "Ask a question isn't available right now"));
    render(<AskPanel />);
    await askIt("NPL ratio by country");
    expect(screen.getByRole("alert").textContent).toMatch(/isn't available right now/);
  });
});
