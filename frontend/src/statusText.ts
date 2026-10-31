export function executionStatusText(status: string): string {
  switch (status) {
    case "SUCCESS":
      return "Execution completed.";
    case "PARTIAL_SUCCESS":
      return "Some orders were executed. Others were not completed.";
    case "RECONCILIATION_REQUIRED":
      return "A broker outcome is ambiguous and requires reconciliation. No automatic resubmission was performed.";
    case "FAILED":
      return "Execution failed.";
    case "PENDING":
    case "RUNNING":
      return "Waiting for execution status...";
    default:
      return status;
  }
}

export function orderStatusNote(status: string, errorMessage: string | null): string {
  if (status === "UNKNOWN") {
    return "The broker outcome could not be determined safely. No automatic resubmission was performed.";
  }
  if (status === "SKIPPED") {
    return (
      errorMessage ??
      "Not submitted because an earlier order entered UNKNOWN state. This is not a broker rejection."
    );
  }
  return errorMessage ?? "";
}

export function isTerminalExecution(status: string): boolean {
  return (
    status === "SUCCESS" ||
    status === "PARTIAL_SUCCESS" ||
    status === "FAILED" ||
    status === "RECONCILIATION_REQUIRED"
  );
}
