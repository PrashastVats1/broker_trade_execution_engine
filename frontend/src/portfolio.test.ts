import { describe, expect, it } from "vitest";
import sampleCsv from "../sample-portfolio.csv?raw";
import { buildExecutionRequest, DEMO_PORTFOLIO, parsePortfolioCsv, validatePortfolio } from "./portfolio";
import { executionStatusText, orderStatusNote } from "./statusText";

describe("portfolio validation", () => {
  it("rejects empty symbols and non-positive quantities", () => {
    expect(
      validatePortfolio([
        { symbol: "", exchange: "NSE", quantity: "0", isin: "" },
        { symbol: "../TCS", exchange: "NSE", quantity: "-1", isin: "" },
      ]),
    ).toEqual([
      "Row 1: symbol is required.",
      "Row 1: quantity must be a whole number greater than zero.",
      "Row 2: symbol is invalid.",
      "Row 2: quantity must be a whole number greater than zero.",
    ]);
  });
});

describe("CSV parsing", () => {
  it("parses the sample columns and ignores the demo comment", () => {
    expect(
      parsePortfolioCsv(`# Demo data only. This is not a live portfolio.
symbol,exchange,quantity
INFY,NSE,10
TCS,NSE,5`),
    ).toEqual([
      { symbol: "INFY", exchange: "NSE", quantity: "10", isin: "" },
      { symbol: "TCS", exchange: "NSE", quantity: "5", isin: "" },
    ]);
  });
});

describe("demo sample portfolio", () => {
  it("loads six synthetic NSE holdings and requests one BUY each", () => {
    const rows = parsePortfolioCsv(sampleCsv);

    expect(rows).toEqual(DEMO_PORTFOLIO);
    expect(validatePortfolio(rows)).toEqual([]);

    const request = buildExecutionRequest("mock", rows);
    expect(request.workflow).toBe("FIRST_TIME");
    expect(request.portfolio).toEqual([
      { symbol: "INFY", exchange: "NSE", quantity: 10 },
      { symbol: "TCS", exchange: "NSE", quantity: 5 },
      { symbol: "HDFCBANK", exchange: "NSE", quantity: 8 },
      { symbol: "RELIANCE", exchange: "NSE", quantity: 4 },
      { symbol: "ITC", exchange: "NSE", quantity: 12 },
      { symbol: "SBIN", exchange: "NSE", quantity: 10 },
    ]);
    expect(request.portfolio.every((position) => !("isin" in position))).toBe(true);
    expect(request).not.toHaveProperty("confirm_live");
  });
});

describe("execution request", () => {
  it("builds one first-time portfolio request without a live-trading flag", () => {
    const request = buildExecutionRequest("mock", [
      { symbol: "infy", exchange: "nse", quantity: "10", isin: "" },
    ]);

    expect(request).toEqual({
      broker: "mock",
      workflow: "FIRST_TIME",
      portfolio: [{ symbol: "INFY", exchange: "NSE", quantity: 10 }],
    });
    expect(request).not.toHaveProperty("confirm_live");
  });
});

describe("status text", () => {
  it("does not describe UNKNOWN as a failure", () => {
    expect(orderStatusNote("UNKNOWN", "order failed at broker")).not.toMatch(/fail/i);
    expect(executionStatusText("RECONCILIATION_REQUIRED")).toMatch(/ambiguous/i);
  });

  it("describes SKIPPED as not submitted", () => {
    expect(orderStatusNote("SKIPPED", null)).toMatch(/Not submitted/);
    expect(orderStatusNote("SKIPPED", null)).toMatch(/not a broker rejection/);
  });
});
