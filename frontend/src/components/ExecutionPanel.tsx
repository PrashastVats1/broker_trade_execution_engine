import type { ExecutionView } from "../types";
import { executionStatusText } from "../statusText";
import { StatusBadge } from "./StatusBadge";

interface ExecutionPanelProps {
  idempotencyKey: string | null;
  execution: ExecutionView | null;
  executing: boolean;
  canExecute: boolean;
  polling: boolean;
  onExecute: () => void;
  onReconcile: () => void;
}

export function ExecutionPanel({
  idempotencyKey,
  execution,
  executing,
  canExecute,
  polling,
  onExecute,
  onReconcile,
}: ExecutionPanelProps) {
  return (
    <section>
      <h2>Execution</h2>
      <div className="actions">
        <button className="primary" type="button" disabled={!canExecute || executing} onClick={onExecute}>
          {executing ? "Executing..." : "Execute portfolio"}
        </button>
      </div>
      <p>Idempotency key: {idempotencyKey ?? "Generated when you execute."}</p>
      {polling ? <p>Waiting for execution status...</p> : null}
      {execution ? (
        <>
          <p>Execution ID: {execution.id}</p>
          <p>Broker: {execution.broker}</p>
          <p>Created: {new Date(execution.created_at).toLocaleString()}</p>
          <p>
            Execution status: <StatusBadge status={execution.status} />
          </p>
          <p>{executionStatusText(execution.status)}</p>
          {execution.status === "RECONCILIATION_REQUIRED" ? (
            <button type="button" name="reconcile" disabled={executing} onClick={onReconcile}>
              Reconcile execution
            </button>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
