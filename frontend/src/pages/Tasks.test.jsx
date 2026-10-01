import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Tasks from "./Tasks";
import { userFor } from "../test/users";

vi.mock("../auth", () => ({ useAuth: () => ({ user: userFor("analyst"), logout: vi.fn() }) }));
// Every other call the page makes answers "nothing" (digest, policy, carried tasks...).
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: new Proxy({}, { get: () => vi.fn(async () => []) }) };
});
// Two of the analyst's tasks, created on different days (midday UTC: the same day in any time zone).
vi.mock("../workflow/tasklistApi", () => ({
  claimTask: vi.fn(), completeTask: vi.fn(), getVariables: vi.fn(async () => ({})),
  searchTasks: vi.fn(async () => [
    { id: "1", name: "Team review", creationDate: "2026-09-28T12:00:00.000+0000", candidateGroups: ["operations"],
      vars: { recordType: "reconciliation", recordKey: "11", title: "Lebanon accounts: 1 row not loaded" } },
    { id: "2", name: "Team review", creationDate: "2026-09-30T12:00:00.000+0000", candidateGroups: ["operations"],
      vars: { recordType: "reconciliation", recordKey: "12", title: "Lebanon transactions: 3 rows not loaded" } },
  ]),
}));

async function show() {
  await act(async () => render(<MemoryRouter><Tasks /></MemoryRouter>));
}
const rows = () => within(screen.getByRole("table", { name: "My tasks" })).getAllByRole("row").slice(1);

describe("Tasks: created-date filter", () => {
  it("shows when each task was created, and filters by a range of days, both included", async () => {
    await show();
    expect(rows()).toHaveLength(2);
    expect(screen.getByRole("columnheader", { name: /Created/ })).toBeTruthy();
    expect(rows()[0].textContent + rows()[1].textContent).toMatch(/28 Sept?\.? 2026|28 Sep 2026/);

    fireEvent.change(screen.getByLabelText("Created from"), { target: { value: "2026-09-30" } });
    expect(rows()).toHaveLength(1);
    expect(rows()[0].textContent).toMatch(/\b12\b/);                     // the 30 Sep task

    fireEvent.change(screen.getByLabelText("Created from"), { target: { value: "2026-09-28" } });
    fireEvent.change(screen.getByLabelText("Created to"), { target: { value: "2026-09-28" } });
    expect(rows()).toHaveLength(1);
    expect(rows()[0].textContent).toMatch(/\b11\b/);                     // the 28 Sep task
  });

  it("says plainly when no task was created in the period, and Clear dates brings them all back", async () => {
    await show();
    fireEvent.change(screen.getByLabelText("Created from"), { target: { value: "2026-10-05" } });
    expect(screen.getByText(/No tasks of yours were created in that period/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear dates" }));
    expect(rows()).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Clear dates" })).toBeNull();
  });
});
