export function StatusBadge({ status }: { status: string }) {
  return <strong className={status}>{status}</strong>;
}
