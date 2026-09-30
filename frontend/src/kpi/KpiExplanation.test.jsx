import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import KpiExplanation from "./KpiExplanation";
import { api } from "../api";

vi.mock("../api", () => ({ api: { kpiExplanation: vi.fn() } }));

const EXACT = { source: "rules", text: "The capital ratio (CAR) is 12.83% on 29 Sep 2026, 0.33 points above the 12.50% limit.", model: "qwen2.5:3b", note: null };
const EASIER = { source: "model", text: "The capital ratio is 12.83%, 0.33 points above its 12.50% limit.", model: "qwen2.5:3b", note: null };

beforeEach(() => vi.clearAllMocks());

describe("why a KPI looks like this", () => {
  it("shows the exact explanation at once, then the checked rewording, with the exact one a click away", async () => {
    let finish;
    api.kpiExplanation.mockImplementation((key, useModel) => (useModel ? new Promise((r) => { finish = r; }) : Promise.resolve(EXACT)));
    render(<KpiExplanation kpiKey="car_pct" />);
    expect(await screen.findByText(EXACT.text)).toBeTruthy();
    expect(screen.getByText(/Checking whether the local AI model/)).toBeTruthy();
    finish(EASIER);
    expect(await screen.findByText(EASIER.text)).toBeTruthy();
    expect(screen.getByText("Reworded by the local AI model (qwen2.5:3b), checked against the data")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Show the exact wording" }));
    expect(screen.getByText(EXACT.text)).toBeTruthy();
    expect(api.kpiExplanation).toHaveBeenCalledWith("car_pct", false);
    expect(api.kpiExplanation).toHaveBeenCalledWith("car_pct", true);
  });

  it("keeps the exact explanation and says why when the rewording was refused", async () => {
    api.kpiExplanation.mockImplementation(async (key, useModel) =>
      (useModel ? { ...EXACT, note: "the model changed the unit of 0.33" } : EXACT));
    render(<KpiExplanation kpiKey="car_pct" />);
    expect(await screen.findByText("Not reworded: the model changed the unit of 0.33.")).toBeTruthy();
    expect(screen.getByText(EXACT.text)).toBeTruthy();
    expect(screen.getByText("Written from the data")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /wording/ })).toBeNull();
  });
});
