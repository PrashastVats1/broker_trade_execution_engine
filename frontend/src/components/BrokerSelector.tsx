const LABELS: Record<string, string> = {
  mock: "Mock Broker",
  zerodha: "Zerodha",
  dhan: "DhanHQ",
  angel_one: "Angel One",
  groww: "Groww",
  upstox: "Upstox",
};

interface BrokerSelectorProps {
  brokers: string[];
  value: string;
  disabled: boolean;
  onChange: (broker: string) => void;
}

export function brokerLabel(name: string): string {
  return LABELS[name] ?? name;
}

export function BrokerSelector({ brokers, value, disabled, onChange }: BrokerSelectorProps) {
  return (
    <section>
      <h2>Broker</h2>
      <label htmlFor="broker">Selected broker</label>
      <select
        id="broker"
        value={value}
        disabled={disabled || brokers.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        {brokers.map((broker) => (
          <option key={broker} value={broker}>
            {brokerLabel(broker)}
          </option>
        ))}
      </select>
      <p className="note">Real brokers are contract-tested, not live-certified.</p>
    </section>
  );
}
