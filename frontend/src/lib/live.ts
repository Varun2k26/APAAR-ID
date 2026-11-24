import { useEffect, useRef, useState } from "react";
import { getToken } from "./api";

export type SpineEvent = { id: number; type: string; institution_id: number | null; payload: any; actor: string; at: string };

/** Subscribes to the SSE stream (outbox relay). Calls onEvent for each new event. */
export function useLiveEvents(onEvent?: (e: SpineEvent) => void) {
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;
  useEffect(() => {
    const token = getToken();
    if (!token) return;
    const es = new EventSource(`/api/v1/events/stream?token=${encodeURIComponent(token)}`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.addEventListener("spine", (m) => {
      try { cb.current?.(JSON.parse((m as MessageEvent).data)); } catch { /* ignore */ }
    });
    return () => es.close();
  }, []);
  return connected;
}

export const EVENT_LABEL: Record<string, string> = {
  ENROLLMENT_CREATED: "Enrolment reported", ENROLLMENT_UPDATED: "Enrolment updated", SUBMISSION_PROCESSED: "Submission received",
  CONFLICT_OPENED: "Duplicate enrolment found", CONFLICT_RESOLVED: "Duplicate enrolment resolved", CONFLICT_STUDENT_CONFIRMED: "Student responded",
  ANOMALY_RAISED: "Anomaly detected", INTAKE_ALERT: "Intake limit exceeded", ISSUE_RAISED: "Row returned", CATEGORY_CHANGED: "Category changed",
  CONSENT_REQUESTED: "Access requested", CONSENT_DECIDED: "Access request answered", TRANSFER_REQUESTED: "Transfer requested",
  TRANSFER_COMPLETED: "Transfer completed", APAAR_LINKED: "APAAR ID linked", STATUS_CHANGED: "Status changed",
  CREDENTIAL_ISSUED: "Credential issued", CORRECTION_REQUESTED: "Correction requested",
  ENROLLMENT_DROP: "Withdrawn", ENROLLMENT_GRADUATE: "Graduated", ENROLLMENT_SUSPEND: "Suspended", ENROLLMENT_REINSTATE: "Reinstated",
  ENROLLMENT_RE_ENROL: "Re-enrolled", CONFLICT_LOSER: "Enrolment voided after review", CONFLICT_WINNER: "Enrolment confirmed after review",
};
