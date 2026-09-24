import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PipelineSection from "./PipelineSection";

const ITEMS = [
  {
    recon_id: 1, ingest_batch_id: "CORE_CSV-20260924T100000Z-bbbb0002", source_system: "CORE_CSV", source_country: "Lebanon",
    source_table: "transactions", received_rows: 6, clean_rows: 5, rejected_rows: 1, amount_column: "amount",
    unreadable_amount_rows: 0, has_gap: true, status: "OPEN", detected_at: "2026-09-24T10:00:00Z",
    amounts_by_currency: { USD: { received: 64800, clean: 63800, gap: 1000 }, LBP: { received: 2e6, clean: 2e6, gap: 0 } },
  },
  {
    recon_id: 2, ingest_batch_id: "CORE_CSV-20260924T100000Z-bbbb0002", source_system: "CORE_CSV", source_country: "Saudi Arabia",
    source_table: "transactions", received_rows: 5, clean_rows: 5, rejected_rows: 0, amount_column: "amount",
    unreadable_amount_rows: 0, has_gap: false, status: "MATCHED", detected_at: "2026-09-24T10:00:00Z",
    amounts_by_currency: { SAR: { received: 57000, clean: 57000, gap: 0 } },
  },
];

vi.mock("../api", () => ({
  api: {
    pipelineReconciliation: vi.fn(async () => ITEMS),
    pipelineRecords: vi.fn(async (id) => ({
      item: ITEMS.find((i) => i.recon_id === id),
      records_available: true,
      records: id === 1 ? [
        { record_key: "T0009", flag_label: "INVALID_CHANNEL", description: "channel 'Cheque' is not valid" },
        { record_key: "T0009", flag_label: "ORPHAN_ACCOUNT", description: "account_id 'ACC004' has no match" },
      ] : [],
    })),
  },
}));

describe("Received vs kept, per source", () => {
  it("shows only gaps by default, with the summary counts, and all items when unticked", async () => {
    render(<PipelineSection />);
    const table = await screen.findByRole("table", { name: "Received vs kept, per source" });
    expect(within(table).getByText("Lebanon")).toBeTruthy();
    expect(within(table).queryByText("Saudi Arabia")).toBeNull();
    expect(within(table).getByText("USD 1,000")).toBeTruthy();
    expect(screen.getByText("Items with a gap").closest("li").textContent).toContain("1");

    await userEvent.click(screen.getByLabelText("Gaps only"));
    expect(within(screen.getByRole("table", { name: "Received vs kept, per source" })).getByText("Saudi Arabia")).toBeTruthy();
  });

  it("shows a missing delivery (completeness check) as a gap with its note", async () => {
    const missing = { ...ITEMS[1], recon_id: 3, source_country: "Qatar", received_rows: 0, clean_rows: 0, rejected_rows: 0,
      amounts_by_currency: null, has_gap: true, status: "OPEN", note: "No rows delivered" };
    const { api } = await import("../api");
    api.pipelineReconciliation.mockResolvedValueOnce([...ITEMS, missing]);
    render(<PipelineSection />);
    const table = await screen.findByRole("table", { name: "Received vs kept, per source" });
    expect(within(table).getByText("No rows delivered")).toBeTruthy();
  });

  it("opens an item onto its amounts per currency and the records that were dropped", async () => {
    render(<PipelineSection />);
    const table = await screen.findByRole("table", { name: "Received vs kept, per source" });
    await userEvent.click(within(table).getAllByRole("button")[0]);

    const records = await screen.findByRole("table", { name: "Rejected records" });
    expect(within(records).getAllByText("T0009")).toHaveLength(2);
    expect(within(records).getByText("ORPHAN_ACCOUNT")).toBeTruthy();
    const amounts = screen.getByRole("table", { name: "Amount per currency" });
    expect(within(amounts).getByText("63,800")).toBeTruthy();
  });
});
