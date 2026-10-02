interface ConnectionStatusProps {
  connected: boolean;
  configured: boolean | null;
  checking: boolean;
  message: string;
  authorizationUrl: string | null;
  onConnect: () => void;
}

export function ConnectionStatus({
  connected,
  configured,
  checking,
  message,
  authorizationUrl,
  onConnect,
}: ConnectionStatusProps) {
  const label = connected ? "Connected" : configured === false ? "Not configured" : "Not connected";
  return (
    <section>
      <h2>Connection</h2>
      <p>
        <strong>{label}</strong>
      </p>
      <p>{message}</p>
      {authorizationUrl ? (
        <p>
          <a href={authorizationUrl}>Open the backend authorization URL</a>
        </p>
      ) : null}
      <button type="button" onClick={onConnect} disabled={checking}>
        {checking ? "Checking..." : "Connect broker"}
      </button>
    </section>
  );
}
