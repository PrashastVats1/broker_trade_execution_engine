import type { PortfolioRow } from "../portfolio";
import { emptyRow } from "../portfolio";

interface PortfolioEditorProps {
  rows: PortfolioRow[];
  disabled: boolean;
  onChange: (rows: PortfolioRow[]) => void;
  onUpload: (file: File) => void;
}

export function PortfolioEditor({
  rows,
  disabled,
  onChange,
  onUpload,
}: PortfolioEditorProps) {
  function update(index: number, patch: Partial<PortfolioRow>) {
    onChange(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  }

  return (
    <section>
      <h2>Target portfolio</h2>
      <p className="note">
        Upload the sample CSV to load six synthetic NSE holdings. That file is
        DEMO DATA for the Mock Broker walkthrough, not real positions and not
        investment recommendations. The backend creates one BUY for each row.
        ISIN is optional, so the sample leaves it blank and the request omits it.
      </p>
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Exchange</th>
            <th>ISIN (optional)</th>
            <th>Quantity</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.symbol}-${index}`}>
              <td>
                <input
                  aria-label={`Symbol for row ${index + 1}`}
                  value={row.symbol}
                  disabled={disabled}
                  onChange={(event) => update(index, { symbol: event.target.value.toUpperCase() })}
                />
              </td>
              <td>
                <select
                  aria-label={`Exchange for row ${index + 1}`}
                  value={row.exchange}
                  disabled={disabled}
                  onChange={(event) => update(index, { exchange: event.target.value })}
                >
                  <option value="NSE">NSE</option>
                  <option value="BSE">BSE</option>
                </select>
              </td>
              <td>
                <input
                  aria-label={`Optional ISIN for row ${index + 1}`}
                  value={row.isin}
                  disabled={disabled}
                  onChange={(event) => update(index, { isin: event.target.value.toUpperCase() })}
                />
              </td>
              <td>
                <input
                  aria-label={`Quantity for row ${index + 1}`}
                  inputMode="numeric"
                  value={row.quantity}
                  disabled={disabled}
                  onChange={(event) => update(index, { quantity: event.target.value })}
                />
              </td>
              <td>
                <button
                  type="button"
                  disabled={disabled || rows.length === 1}
                  onClick={() => onChange(rows.filter((_, rowIndex) => rowIndex !== index))}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row-actions">
        <button type="button" disabled={disabled} onClick={() => onChange([...rows, emptyRow()])}>
          Add position
        </button>
        <label htmlFor="portfolio-csv">Upload CSV</label>
        <input
          id="portfolio-csv"
          type="file"
          accept=".csv,text/csv"
          disabled={disabled}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) {
              onUpload(file);
            }
            event.target.value = "";
          }}
        />
      </div>
    </section>
  );
}
