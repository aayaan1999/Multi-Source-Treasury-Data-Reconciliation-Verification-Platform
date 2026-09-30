import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Login from "./Login";

vi.mock("../auth", () => ({ useAuth: () => ({ user: null, login: vi.fn(), notice: null }) }));

describe("sign-in page", () => {
  it("shows sample charts beside the form, not a list of people", () => {
    render(<MemoryRouter><Login /></MemoryRouter>);
    expect(screen.getByRole("img", { name: /Sample charts/ })).toBeTruthy();
    expect(screen.getByText("Capital adequacy")).toBeTruthy();
    expect(screen.getByText("Records reconciled")).toBeTruthy();
    expect(screen.getByText("Sample figures")).toBeTruthy();
    expect(screen.queryByText("Chief Risk Officer")).toBeNull();
    expect(screen.getAllByText("Bank Data Platform").length).toBeGreaterThan(0);
  });
});
