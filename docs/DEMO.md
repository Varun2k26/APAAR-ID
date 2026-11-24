# Demo script (about 10 minutes)

Start with `./dev.sh --reset`. Use two browser windows (or one normal and one private) so two roles
can be signed in at once. Every account is a one-click button on the sign-in page.

## 1. The national picture (AICTE admin, MFA)
- Sign in as **AICTE admin** and enter the code shown under the field (TOTP).
- National overview:
  - 23k+ students reported at student level, APAAR coverage, seat utilisation.
  - The trend chart shows 2021–25 from aggregate returns and 2026 live, the shift from "we admitted 120" to verifiable rows.
- Leave this window open on the overview. The **Live feed** is connected.

## 2. A college uploads, with mistakes (Data operator, Aarohan)
- In the second window, sign in as **Data operator · Aarohan** → Upload CSV → demo file `1_aarohan_new_admissions.csv`.
- The pre-check runs in the browser before anything is sent: bad checksum, two values in one field, a repeated roll number.
- Upload. The row-level report:
  - **R40** typo in the APAAR
  - **R42** an APAAR that belongs to someone else (the registry's name/DOB is not revealed)
  - **R44** no APAAR yet, so a provisional ID is issued
  - **R31** SC claimed by an OCI student
  - **R30** EWS + OBC-NCL claimed together
  - **R02** duplicate roll number
  - **R23** lateral entry in year 1
  - **R32** foreign seat for a resident Indian
- 7 rows are accepted and 7 quarantined. *"Fix 7 rows, not re-upload 700."*
- Errors to fix → R23 → set year of study to 2 → Resubmit. Accepted.

## 3. The same student at two colleges, live (Data operator, Dakshin)
- Sign out, then sign in as **Data operator · Dakshin** and upload `2_dakshin_upload_with_duplicates.csv`.
- **R10**: Vignesh is already active at Aarohan, so this record is stored as a **CONFLICT** and not decided by who was first.
- **R11**: "R. Karthik" has no APAAR, but name, DOB and parent match a student at Aarohan, so a fuzzy conflict goes to review.
  *Point:* leaving out the APAAR does not hide a duplicate.
- Switch to the AICTE window: both conflicts appeared in the live feed within a second, with no refresh.
- Dakshin's Conflicts page shows the other college only as "Another AICTE institution" (data minimisation).

## 4. The student decides where they study
- Sign in as a student through **DigiLocker (simulated)**: pick Vignesh Murugan, OTP 123456.
- The red banner shows two colleges have reported him. He clicks "I study here" on Aarohan.
- AICTE → Duplicate conflicts → the "student answered" row → confirm the selected enrolment. Dakshin's record becomes VOID.

## 5. Statistical anomalies, explained
- AICTE → Anomalies.
- **Gyanodaya, Kanpur**: fill rate 30% → 95% (3.2×), the 5-year bar chart, robust z vs own history and peers, and *why it matters* (padded admissions for scholarships). Measured on fill rate, so an approved expansion would not trigger it.
- **Vindhya, Indore**: EWS share 8% → 50%, history vs this year.
- **Hampi, Mysuru** is *not* flagged even though it has 76 students on 60 seats: 60 regular + 3 TFW + 8 FN + 5 lateral is legal. Open Institutions → Hampi → the programme table shows each supernumerary bucket against its own cap.

## 6. Verifiable credential, selective disclosure, offline
- Student **Kavya Senthil** → Credentials wallet → Issue enrolment credential.
- Only name, institution, programme, admission year and status are shared. Category, DOB and gender stay hidden. Tap the QR to enlarge it.
- Open verifier → **Valid**, with the four checks listed. Nothing was sent to a server.
- Paste the link with one character changed → **Not valid: a disclosed field was altered**.
- Turn off Wi-Fi and verify again: it still works from the cached trust list and status list.
- Click "Verify online via the AICTE API". That check *is* logged.

## 7. Consent and "who accessed my data"
- **Institution admin · Dakshin** → Transfers & consent → ask Kavya for name + programme.
  Until she answers, the API refuses to return her record (403), and the refusal is itself logged.
- Kavya approves → Dakshin can read exactly those fields → Kavya revokes → 403 again.
- Kavya → *Who accessed my data*: the denied attempt, the consented read, the online verification, all from the hash-chained log.

## 8. Regulator, university, audit
- **Regulator (NAAC)** → pick a college + purpose → pseudonymised records. Every included student sees this query in their own log.
- **University registrar** → Divya Krishnan → Issue degree → a PDF with the APAAR and a QR that verifies offline. The degree is signed by the *university*, because affiliated colleges don't award degrees.
- **AICTE → Audit log → Verify the whole chain** → intact. (The test suite edits a row and the check reports exactly which entry.)
- **AICTE → System → Simulate outage**, then add a student: accepted with "verification pending". Restore: the background job re-checks it.

## Questions you can expect
- *Why not first-come-wins?* It rewards whichever fraudster submits faster.
- *What if a student has no APAAR?* They get a provisional ID, but are still fuzzy-matched, and colleges with a high provisional share are flagged.
- *Real-time?* About one second, using an outbox + SSE. The same event shape scales to Kafka/ClickHouse.
- *Privacy?* Consent is enforced when data is read, selective disclosure keeps category hidden by default, and the student sees every access.
