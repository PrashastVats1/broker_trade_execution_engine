import type { ExecutionRequestBody } from "./types";

export interface PortfolioRow {
  symbol: string;
  exchange: string;
  quantity: string;
  isin: string;
}

const SYMBOL = /^[A-Z0-9][A-Z0-9&._-]{0,29}$/;
const ISIN = /^IN[A-Z0-9]{10}$/;

export function emptyRow(): PortfolioRow {
  return { symbol: "", exchange: "NSE", quantity: "", isin: "" };
}

export function validatePortfolio(rows: PortfolioRow[]): string[] {
  if (rows.length === 0) {
    return ["Add at least one position."];
  }
  return rows.flatMap((row, index) => {
    const label = `Row ${index + 1}`;
    const errors: string[] = [];
    const symbol = row.symbol.trim().toUpperCase();
    const exchange = row.exchange.trim().toUpperCase();
    const quantity = row.quantity.trim();
    const isin = row.isin.trim().toUpperCase();
    if (!symbol) {
      errors.push(`${label}: symbol is required.`);
    } else if (!SYMBOL.test(symbol)) {
      errors.push(`${label}: symbol is invalid.`);
    }
    if (exchange !== "NSE" && exchange !== "BSE") {
      errors.push(`${label}: exchange must be NSE or BSE.`);
    }
    if (!/^\d+$/.test(quantity) || Number(quantity) <= 0) {
      errors.push(`${label}: quantity must be a whole number greater than zero.`);
    }
    if (isin && !ISIN.test(isin)) {
      errors.push(`${label}: ISIN is invalid.`);
    }
    return errors;
  });
}

export function parsePortfolioCsv(text: string): PortfolioRow[] {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
  if (lines.length < 2) {
    throw new Error("CSV must include a header and at least one position.");
  }
  const header = lines[0].split(",").map((cell) => cell.trim().toLowerCase());
  const symbolIndex = header.indexOf("symbol");
  const exchangeIndex = header.indexOf("exchange");
  const quantityIndex = header.indexOf("quantity");
  const isinIndex = header.indexOf("isin");
  if (symbolIndex < 0 || exchangeIndex < 0 || quantityIndex < 0) {
    throw new Error("CSV must include symbol, exchange, and quantity columns.");
  }
  return lines.slice(1).map((line) => {
    const cells = line.split(",").map((cell) => cell.trim());
    return {
      symbol: (cells[symbolIndex] ?? "").toUpperCase(),
      exchange: (cells[exchangeIndex] ?? "").toUpperCase(),
      quantity: cells[quantityIndex] ?? "",
      isin: isinIndex >= 0 ? (cells[isinIndex] ?? "").toUpperCase() : "",
    };
  });
}

export function buildExecutionRequest(
  broker: string,
  rows: PortfolioRow[],
): ExecutionRequestBody {
  const errors = validatePortfolio(rows);
  if (errors.length > 0) {
    throw new Error(errors.join(" "));
  }
  return {
    broker,
    workflow: "FIRST_TIME",
    portfolio: rows.map((row) => {
      const position: ExecutionRequestBody["portfolio"][number] = {
        symbol: row.symbol.trim().toUpperCase(),
        exchange: row.exchange.trim().toUpperCase(),
        quantity: Number(row.quantity.trim()),
      };
      const isin = row.isin.trim().toUpperCase();
      if (isin) {
        position.isin = isin;
      }
      return position;
    }),
  };
}
