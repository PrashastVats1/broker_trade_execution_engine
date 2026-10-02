import { useEffect, useState } from "react";
import {
  createExecution,
  getBrokerStatus,
  getExecution,
  listBrokers,
  reconcileExecution,
  startBrokerAuth,
} from "./api";
import { BrokerSelector } from "./components/BrokerSelector";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { ExecutionPanel } from "./components/ExecutionPanel";
import { OrderResults } from "./components/OrderResults";
import { PortfolioEditor } from "./components/PortfolioEditor";
import { buildExecutionRequest, emptyRow, parsePortfolioCsv, validatePortfolio } from "./portfolio";
import type { PortfolioRow } from "./portfolio";
import { isTerminalExecution } from "./statusText";
import type { ExecutionView } from "./types";

export function App() {
  const [brokers, setBrokers] = useState<string[]>([]);
  const [broker, setBroker] = useState("mock");
  const [rows, setRows] = useState<PortfolioRow[]>([emptyRow()]);
  const [connected, setConnected] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [connectionMessage, setConnectionMessage] = useState(
    "Select Mock Broker and connect. No credentials are required.",
  );
  const [authorizationUrl, setAuthorizationUrl] = useState<string | null>(null);
  const [execution, setExecution] = useState<ExecutionView | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [activity, setActivity] = useState<"connect" | "execute" | "reconcile" | null>(null);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void listBrokers()
      .then((items) => {
        const names = items.map((item) => item.name);
        setBrokers(names);
        setBroker((current) => (names.includes(current) ? current : names[0] ?? current));
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "The broker list could not be loaded.");
      });
  }, []);

  const executionId = execution?.id;
  const executionStatus = execution?.status;
  useEffect(() => {
    if (!executionId || !executionStatus || isTerminalExecution(executionStatus)) {
      setPolling(false);
      return;
    }
    let attempts = 0;
    let stopped = false;
    setPolling(true);
    const timer = window.setInterval(() => {
      attempts += 1;
      if (attempts > 20) {
        window.clearInterval(timer);
        setPolling(false);
        setError("Execution status polling stopped after 30 seconds.");
        return;
      }
      void getExecution(executionId)
        .then((next) => {
          if (!stopped) {
            setExecution(next);
          }
        })
        .catch((reason: unknown) => {
          if (stopped) {
            return;
          }
          window.clearInterval(timer);
          setPolling(false);
          setError(reason instanceof Error ? reason.message : "Execution status could not be read.");
        });
    }, 1500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [executionId, executionStatus]);

  function selectBroker(next: string) {
    setBroker(next);
    setConnected(false);
    setConfigured(null);
    setAuthorizationUrl(null);
    setConnectionMessage("Connection must be checked again for the selected broker.");
  }

  async function connect() {
    setActivity("connect");
    setError("");
    setAuthorizationUrl(null);
    try {
      const status = await getBrokerStatus(broker);
      setConfigured(status.configured);
      if (status.configured) {
        setConnected(true);
        setConnectionMessage(
          status.mode === "mock"
            ? "Mock broker is ready. No credentials are required."
            : "The backend reports a configured token. This broker is not live-certified.",
        );
        return;
      }
      setConnected(false);
      try {
        const auth = await startBrokerAuth(broker);
        setAuthorizationUrl(auth.authorization_url);
        setConnectionMessage(
          "Authentication required. This page does not store broker tokens.",
        );
      } catch (reason: unknown) {
        setConnectionMessage(
          reason instanceof Error ? reason.message : "Authentication required.",
        );
      }
    } catch (reason: unknown) {
      setConnected(false);
      setError(reason instanceof Error ? reason.message : "Broker status could not be checked.");
    } finally {
      setActivity(null);
    }
  }

  async function upload(file: File) {
    setError("");
    try {
      setRows(parsePortfolioCsv(await file.text()));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "CSV could not be read.");
    }
  }

  async function execute() {
    const validation = validatePortfolio(rows);
    if (!connected) {
      setError("Connect the selected broker before executing.");
      return;
    }
    if (validation.length > 0) {
      setError(validation.join(" "));
      return;
    }
    const key = crypto.randomUUID();
    setActivity("execute");
    setError("");
    setIdempotencyKey(key);
    try {
      const created = await createExecution(buildExecutionRequest(broker, rows), key);
      setExecution(created);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Execution could not be submitted.");
    } finally {
      setActivity(null);
    }
  }

  async function reconcile() {
    if (!execution) {
      return;
    }
    setActivity("reconcile");
    setError("");
    try {
      setExecution(await reconcileExecution(execution.id));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Reconciliation could not be completed.");
    } finally {
      setActivity(null);
    }
  }

  return (
    <main>
      <h1>Portfolio Trade Execution Engine</h1>
      <p>Live trading is disabled by default. Use Mock Broker for the demo.</p>
      {error ? <p className="error">{error}</p> : null}
      <PortfolioEditor
        rows={rows}
        disabled={activity !== null}
        onChange={setRows}
        onUpload={(file) => void upload(file)}
      />
      <BrokerSelector
        brokers={brokers}
        value={broker}
        disabled={activity !== null}
        onChange={selectBroker}
      />
      <ConnectionStatus
        connected={connected}
        configured={configured}
        checking={activity === "connect"}
        message={connectionMessage}
        authorizationUrl={authorizationUrl}
        onConnect={() => void connect()}
      />
      <ExecutionPanel
        idempotencyKey={idempotencyKey}
        execution={execution}
        executing={activity === "execute" || activity === "reconcile"}
        canExecute={connected && validatePortfolio(rows).length === 0 && activity === null}
        polling={polling}
        onExecute={() => void execute()}
        onReconcile={() => void reconcile()}
      />
      <OrderResults orders={execution?.orders ?? []} />
    </main>
  );
}
