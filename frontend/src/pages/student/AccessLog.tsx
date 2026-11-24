import { api } from "../../lib/api";
import { Empty, Loading, PageHeader, Panel, useAsync, when } from "../../components/ui";

const ACTION: Record<string, string> = {
  RECORD_READ: "Viewed your record", RECORD_READ_DENIED: "Attempted to view your record (refused: no consent)",
  ENROLLMENT_CREATE: "Reported your enrolment", ENROLLMENT_UPDATE: "Updated your enrolment", ENROLLMENT_STATUS: "Changed your enrolment status",
  VERIFY_ONLINE: "Verified your credential with the registry", CONSENT_REQUEST: "Requested access to your record",
  CONSENT_APPROVE: "You granted access", CONSENT_DENY: "You declined access", CONSENT_REVOKE: "You withdrew access",
  INCLUDED_IN_AUDIT: "Included your record in an audit (without your name, date of birth or APAAR ID)", CREDENTIAL_ISSUE: "Issued a credential",
  CREDENTIAL_REVOKE: "Revoked a credential", LOGIN: "Signed in", CONFLICT_STUDENT_CONFIRM: "You answered a duplicate enrolment query",
  CONFLICT_RESOLVE: "Decided a duplicate enrolment case", TRANSFER_REQUEST: "Requested your transfer", TRANSFER_RELEASE: "Released you for transfer",
  DEGREE_ISSUE: "Issued your degree", CORRECTION_REQUEST: "You requested a correction", CORRECTION_DECIDE: "Decided your correction request",
  REGISTRY_RECHECK: "Re-checked your APAAR with the registry",
};
const ROLE: Record<string, string> = { STUDENT: "You", INSTITUTION_ADMIN: "Institution", DATA_OPERATOR: "Institution", ERP_CLIENT: "Institution system",
  AICTE_ADMIN: "AICTE", REGULATOR: "Regulator", UNIVERSITY_REGISTRAR: "University", VERIFIER: "Verifier", SYSTEM: "System" };

export default function AccessLog() {
  const log = useAsync(() => api.get("/api/v1/me/access-log"), []);
  return (
    <div>
      <PageHeader title="Access history" description="Everyone who has viewed, changed or verified your record. Checks made with your QR code on another person's device are private and do not appear here." />
      <Panel flush>
        {log.loading ? <Loading /> : !log.data?.length ? <Empty>No activity.</Empty> : (
          <div className="overflow-x-auto"><table className="tbl">
            <thead><tr><th>Date</th><th>Who</th><th>What</th><th>Reason</th></tr></thead>
            <tbody>{log.data.map((a: any) => (
              <tr key={a.id}>
                <td className="whitespace-nowrap text-[13px]">{when(a.at)}</td>
                <td className="text-[13px]"><div className="text-ink-900">{a.role === "STUDENT" ? "You" : a.actor.replace(/^verifier:/, "")}</div><div className="text-ink-500">{ROLE[a.role] ?? a.role}</div></td>
                <td className="text-[13px]">{ACTION[a.action] ?? a.action}{a.details?.fields_disclosed && <div className="text-ink-500">Saw: {a.details.fields_disclosed.join(", ").replace(/_/g, " ")}</div>}</td>
                <td className="text-[13px] text-ink-600">{a.purpose ?? "—"}{a.details?.basis && <div className="text-ink-500">Basis: {a.details.basis}</div>}</td>
              </tr>))}</tbody>
          </table></div>)}
      </Panel>
    </div>
  );
}
