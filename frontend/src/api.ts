import type {
  AuthStart,
  BrokerStatus,
  BrokerSummary,
  ExecutionRequestBody,
  ExecutionView,
  MockScenarioName,
  MockScenarioSelection,
} from "./types";

export function apiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  return (configured || "http://localhost:8000").replace(/\/$/, "");
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function errorMessage(response: Response): Promise<string> {
  const fallback = `Request failed (${response.status}).`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.trim()) {
      return body.detail.slice(0, 500);
    }
    if (Array.isArray(body.detail)) {
      const messages = body.detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item ? String(item.msg) : "",
        )
        .filter(Boolean);
      if (messages.length > 0) {
        return messages.join(" ").slice(0, 500);
      }
    }
  } catch {
    return fallback;
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, init);
  } catch {
    throw new ApiError(0, "The API could not be reached.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return (await response.json()) as T;
}

export function listBrokers(): Promise<BrokerSummary[]> {
  return request<BrokerSummary[]>("/api/v1/brokers");
}

export function getBrokerStatus(broker: string): Promise<BrokerStatus> {
  return request<BrokerStatus>(`/api/v1/brokers/${broker}/status`);
}

export function getMockScenario(): Promise<MockScenarioSelection> {
  return request<MockScenarioSelection>("/api/v1/brokers/mock/scenario");
}

export function setMockScenario(scenario: MockScenarioName): Promise<MockScenarioSelection> {
  return request<MockScenarioSelection>("/api/v1/brokers/mock/scenario", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario }),
  });
}

export function startBrokerAuth(broker: string): Promise<AuthStart> {
  return request<AuthStart>(`/api/v1/brokers/${broker}/auth/start`);
}

export function createExecution(
  body: ExecutionRequestBody,
  idempotencyKey: string,
): Promise<ExecutionView> {
  return request<ExecutionView>("/api/v1/executions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(body),
  });
}

export function getExecution(executionId: string): Promise<ExecutionView> {
  return request<ExecutionView>(`/api/v1/executions/${executionId}`);
}

export function reconcileExecution(executionId: string): Promise<ExecutionView> {
  return request<ExecutionView>(`/api/v1/executions/${executionId}/reconcile`, {
    method: "POST",
  });
}
