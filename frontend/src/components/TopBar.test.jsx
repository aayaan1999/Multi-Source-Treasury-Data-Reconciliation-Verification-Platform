import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import TopBar from "./TopBar";

vi.mock("../auth", async () => {
  const { userFor } = await import("../test/users");
  return { useAuth: () => ({ user: userFor("approver"), logout: vi.fn() }) };   // the CFO has the Analysis & reporting group
});

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function show(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TopBar />
      <Routes><Route path="*" element={<Where />} /></Routes>
    </MemoryRouter>,
  );
}

const group = () => screen.getByRole("button", { name: "Analysis & reporting" });

describe("screen menu", () => {
  it("groups Branch & segment, Scenario modelling and Regulatory reporting under one dropdown", () => {
    show();
    const nav = screen.getByRole("navigation", { name: "Screens" });
    expect(within(nav).queryByRole("link", { name: "Scenario modelling" })).toBeNull();   // hidden until opened
    expect(within(nav).getByRole("link", { name: "Reconciliation" })).toBeTruthy();
    expect(group().getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(group());
    const menu = screen.getByRole("menu", { name: "Analysis & reporting" });
    expect(within(menu).getAllByRole("menuitem").map((a) => a.textContent)).toEqual(["Branch & segment", "Scenario modelling", "Regulatory reporting"]);

    fireEvent.click(within(menu).getByRole("menuitem", { name: "Scenario modelling" }));
    expect(screen.getByTestId("where").textContent).toBe("/scenario");
    expect(screen.queryByRole("menu")).toBeNull();                                       // closes after choosing
  });

  it("is highlighted while one of its screens is open, including a report inside Regulatory reporting", () => {
    const { unmount } = show("/reports/3");
    expect(group().className).toMatch(/bg-accent/);
    unmount();
    show("/portfolio");
    expect(group().className).not.toMatch(/bg-accent/);
  });

  it("closes on Escape or a click elsewhere, and the arrow keys move through it", async () => {
    show();
    fireEvent.click(group());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(group());
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();

    await act(async () => {
      fireEvent.keyDown(group(), { key: "ArrowDown" });
      await new Promise((r) => setTimeout(r));
    });
    const items = screen.getAllByRole("menuitem");
    expect(document.activeElement).toBe(items[0]);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[1]);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowUp" });
    fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowUp" });
    expect(document.activeElement).toBe(items[2]);                                     // wraps around
  });
});
