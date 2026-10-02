export interface BrokerSummary {
  name: string;
  mode: string;
  live_certified: boolean;
}

export interface BrokerStatus {
  name: string;
  mode: string;
  configured: boolean;
  live_certified: boolean;
}

export interface AuthStart {
  authorization_url: string;
}

export type ExecutionStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCESS"
  | "PARTIAL_SUCCESS"
  | "FAILED"
  | "RECONCILIATION_REQUIRED";

export type OrderStatus =
  | "PENDING"
  | "SUBMITTING"
  | "SUBMITTED"
  | "OPEN"
  | "PARTIALLY_FILLED"
  | "EXECUTED"
  | "REJECTED"
  | "FAILED"
  | "CANCELLED"
  | "UNKNOWN"
  | "SKIPPED";

export interface OrderView {
  id: string;
  client_order_id: string;
  symbol: string;
  exchange: string;
  side: "BUY" | "SELL";
  quantity: number;
  filled_quantity: number;
  status: OrderStatus;
  broker_order_id: string | null;
  average_price: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface ExecutionView {
  id: string;
  broker: string;
  workflow: "FIRST_TIME" | "REBALANCE";
  status: ExecutionStatus;
  notification_status: string;
  created_at: string;
  updated_at: string;
  orders: OrderView[];
}

export interface PortfolioPosition {
  symbol: string;
  exchange: string;
  quantity: number;
  isin?: string;
}

export interface ExecutionRequestBody {
  broker: string;
  workflow: "FIRST_TIME";
  portfolio: PortfolioPosition[];
}
