import type { MockScenarioName } from "../types";

interface MockScenarioSelectorProps {
  value: MockScenarioName;
  disabled: boolean;
  onChange: (scenario: MockScenarioName) => void;
}

export function MockScenarioSelector({ value, disabled, onChange }: MockScenarioSelectorProps) {
  const simulated = value === "EXECUTED_BUT_RESPONSE_TIMEOUT";

  return (
    <section>
      <h2>Mock Broker scenario</h2>
      <label htmlFor="mock-scenario">Demo scenario</label>
      <select
        id="mock-scenario"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as MockScenarioName)}
      >
        <option value="NORMAL">Normal Execution</option>
        <option value="EXECUTED_BUT_RESPONSE_TIMEOUT">Executed but Response Timed Out</option>
      </select>
      {simulated ? (
        <p className="note">
          Simulated failure. Mock Broker fills the first order, records the broker
          order ID, then drops the response. The application stores that order as
          UNKNOWN and does not retry it. Later orders are not submitted. Reconcile
          looks up the original fill and must not create another broker order.
        </p>
      ) : (
        <p className="note">Normal Execution fills every submitted mock order.</p>
      )}
    </section>
  );
}
