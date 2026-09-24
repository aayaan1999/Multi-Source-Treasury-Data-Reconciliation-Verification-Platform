import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import EntityMatchPanel from "./EntityMatchPanel";
import { completeTask } from "./tasklistApi";

vi.mock("../api", () => ({
  api: {
    entityMatch: vi.fn(async () => ({
      candidate_id: 4, score: 0.93, reasons: ["names 93% alike", "same branch"],
      customers: [
        { customer_id: "CN0010", name: "Khalil Trading SAL", segment: "Corporate", branch_name: "Beirut Main", country: "Lebanon", loans: [{ currency: "USD", loan_count: 2, outstanding: 900000 }] },
        { customer_id: "CN0201", name: "Khalil Trdg", segment: "Corporate", branch_name: "Beirut Main", country: "Lebanon", loans: [] },
      ],
    })),
    exceptionComments: vi.fn(async () => []),
    addExceptionComment: vi.fn(async () => ({})),
    logTaskCompletion: vi.fn(async () => ({})),
  },
}));
vi.mock("./tasklistApi", () => ({ completeTask: vi.fn(async () => null) }));

beforeEach(() => vi.clearAllMocks());

describe("possible duplicate popup", () => {
  it("shows both records side by side and 'Same company' needs a comment", async () => {
    const onDone = vi.fn();
    render(<EntityMatchPanel task={{ id: "t1", vars: { recordKey: "4" } }} user={{ user_id: 1 }} onDone={onDone} onClose={() => {}} />);
    const table = await screen.findByRole("table", { name: "The two records" });
    expect(within(table).getByText("Khalil Trading SAL")).toBeTruthy();
    expect(within(table).getByText("2 loans, 900,000 USD")).toBeTruthy();
    expect(within(table).getByText("No loans")).toBeTruthy();
    expect(screen.getByText(/names 93% alike · same branch/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Same company" }));
    expect(completeTask).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Comment"), "same trade licence");
    await userEvent.click(screen.getByRole("button", { name: "Same company" }));
    expect(completeTask).toHaveBeenCalledWith("t1", { outcome: "APPROVED", correctedValue: "", reviewedByUserId: 1 });
    expect(onDone).toHaveBeenCalled();
  });
});
