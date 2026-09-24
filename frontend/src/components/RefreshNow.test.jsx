import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import RefreshNow, { refreshLabel } from "./RefreshNow";
import { api } from "../api";

let role = "approver";
vi.mock("../auth", () => ({ useAuth: () => ({ user: { user_id: 3, role } }) }));
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { refreshStatus: vi.fn(), refreshNow: vi.fn() } };
});

const DONE = { running: false, last_run: { state: "TERMINATED", result: "SUCCESS", started_at: "2026-09-24T10:42:00Z", ended_at: "2026-09-24T10:51:00Z" } };
const RUNNING = { running: true, last_run: { state: "RUNNING", result: null, started_at: "2026-09-24T10:42:00Z", ended_at: null } };

beforeEach(() => {
  role = "approver";
  vi.clearAllMocks();
});
afterEach(() => vi.useRealTimers());

describe("refresh label", () => {
  it("says what the pipeline is doing", () => {
    expect(refreshLabel(RUNNING)).toMatch(/^Refreshing… started \d\d:\d\d$/);
    expect(refreshLabel(DONE)).toMatch(/^Updated \d\d:\d\d$/);
    expect(refreshLabel({ running: false, last_run: { ...DONE.last_run, result: "FAILED" } })).toMatch(/^Last refresh failed at/);
    expect(refreshLabel({ running: false, last_run: null })).toBe("No pipeline runs yet");
  });
});

describe("Refresh Now", () => {
  it("the CFO starts a run, sees it progress, and the page reloads its numbers when it succeeds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.refreshStatus.mockResolvedValueOnce(DONE).mockResolvedValueOnce(RUNNING).mockResolvedValue(DONE);
    api.refreshNow.mockResolvedValue({ run_id: 8 });
    const onRefreshed = vi.fn();
    render(<RefreshNow onRefreshed={onRefreshed} />);

    const button = await screen.findByRole("button", { name: "Refresh now" });
    await act(async () => button.click());
    expect(api.refreshNow).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Refreshing…" }).disabled).toBe(true);   // no second click
    expect(onRefreshed).not.toHaveBeenCalled();

    await act(async () => vi.advanceTimersByTime(15000));   // still running
    expect(onRefreshed).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTime(15000));   // finished
    expect(onRefreshed).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("button", { name: "Refresh now" })).toBeTruthy();
  });

  it("everyone else sees when the data was updated, but no button", async () => {
    role = "analyst";
    api.refreshStatus.mockResolvedValue(DONE);
    render(<RefreshNow />);
    expect(await screen.findByText(/^Updated/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says it isn't set up (to the CFO only) when the backend has no Databricks settings", async () => {
    const { ApiError } = await import("../api");
    api.refreshStatus.mockRejectedValue(new ApiError(503, "Refresh Now isn't set up"));
    render(<RefreshNow />);
    expect(await screen.findByText("Refresh Now isn't set up yet.")).toBeTruthy();
  });
});
