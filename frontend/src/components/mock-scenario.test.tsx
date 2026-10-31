import { createRoot, type Root } from "react-dom/client";
import { act, type ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { MockScenarioSelector } from "./MockScenarioSelector";

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

describe("mock scenario selector", () => {
  it("defaults to normal execution without the timeout warning", () => {
    const container = render(
      <MockScenarioSelector value="NORMAL" disabled={false} onChange={() => undefined} />,
    );

    expect(container.textContent).toContain("Normal Execution");
    expect(container.textContent).not.toContain("Simulated failure");
  });

  it("explains the lost-response scenario without submitting an order", () => {
    const calls: string[] = [];
    const container = render(
      <MockScenarioSelector
        value="EXECUTED_BUT_RESPONSE_TIMEOUT"
        disabled={false}
        onChange={(scenario) => calls.push(scenario)}
      />,
    );

    expect(container.textContent).toContain("Simulated failure");
    expect(container.textContent).toContain("does not retry");
    expect(container.textContent).not.toContain("Execute portfolio");
    expect(calls).toEqual([]);
  });
});
