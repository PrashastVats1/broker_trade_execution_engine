import { createRoot, type Root } from "react-dom/client";
import { act, type ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { ExecutionPanel } from "./ExecutionPanel";
import { OrderResults } from "./OrderResults";
import type { ExecutionView, OrderView } from "../types";

function order(status: OrderView["status"], symbol: string): OrderView {
  return {
    id: symbol,
    client_order_id: symbol,
    symbol,
    exchange: "NSE",
    side: "BUY",
    quantity: 5,
    filled_quantity: status === "EXECUTED" ? 5 : 0,
    status,
    broker_order_id: status === "UNKNOWN" ? null : "broker-1",
    average_price: null,
    error_code: null,
    error_message:
      status === "SKIPPED" ? "Not submitted because an earlier order has an ambiguous broker outcome" : null,
  };
}

const execution: ExecutionView = {
  id: "execution-1",
  broker: "mock",
  workflow: "FIRST_TIME",
  status: "RECONCILIATION_REQUIRED",
  notification_status: "SENT",
  created_at: "2026-10-02T00:00:00Z",
  updated_at: "2026-10-02T00:00:00Z",
  orders: [order("EXECUTED", "INFY"), order("UNKNOWN", "TCS"), order("SKIPPED", "HDFCBANK")],
};

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

describe("order rendering", () => {
  it("shows UNKNOWN and SKIPPED orders without calling them failed", () => {
    const container = render(<OrderResults orders={execution.orders} />);
    const text = container.textContent ?? "";

    expect(text).toContain("TCS");
    expect(text).toContain("UNKNOWN");
    expect(text).toContain("could not be determined safely");
    expect(text).toContain("HDFCBANK");
    expect(text).toContain("SKIPPED");
    expect(text).toContain("Not submitted");
    expect(text.toLowerCase()).not.toContain("tcs buy 5failed");
  });
});

describe("reconciliation action", () => {
  it("calls reconcile once and does not submit another execution", () => {
    const calls: string[] = [];
    const container = render(
      <ExecutionPanel
        idempotencyKey="key-1"
        execution={execution}
        executing={false}
        canExecute
        polling={false}
        onExecute={() => calls.push("execute")}
        onReconcile={() => calls.push("reconcile")}
      />,
    );

    const button = container.querySelector("button[name='reconcile']");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Reconcile button is missing.");
    }
    act(() => {
      button.click();
    });

    expect(calls).toEqual(["reconcile"]);
    expect(container.textContent).toContain("RECONCILIATION_REQUIRED");
  });
});
