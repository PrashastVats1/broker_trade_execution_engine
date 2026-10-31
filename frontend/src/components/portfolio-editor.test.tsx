import { createRoot, type Root } from "react-dom/client";
import { act, type ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { DEMO_PORTFOLIO } from "../portfolio";
import { PortfolioEditor } from "./PortfolioEditor";

let root: Root | null = null;

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  document.body.innerHTML = "";
});

function render(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root?.render(node);
  });
  return container;
}

describe("portfolio editor", () => {
  it("shows the imported symbols and quantities instead of placeholder labels", () => {
    const container = render(
      <PortfolioEditor rows={DEMO_PORTFOLIO} disabled={false} onChange={() => undefined} onUpload={() => undefined} />,
    );
    const text = container.textContent ?? "";

    expect(text).toContain("DEMO DATA");
    expect(text).not.toContain("Symbol 1");
    expect(text).not.toContain("Exchange 1");
    expect(text).not.toContain("ISIN 1");

    const symbols = [...container.querySelectorAll("input[aria-label^='Symbol']")].map(
      (input) => (input as HTMLInputElement).value,
    );
    const quantities = [...container.querySelectorAll("input[aria-label^='Quantity']")].map(
      (input) => (input as HTMLInputElement).value,
    );
    const isins = [...container.querySelectorAll("input[aria-label^='Optional ISIN']")].map(
      (input) => (input as HTMLInputElement).value,
    );

    expect(symbols).toEqual(["INFY", "TCS", "HDFCBANK", "RELIANCE", "ITC", "SBIN"]);
    expect(quantities).toEqual(["10", "5", "8", "4", "12", "10"]);
    expect(isins.every((isin) => isin === "")).toBe(true);
  });
});
