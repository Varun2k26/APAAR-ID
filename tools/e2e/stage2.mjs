// Stage 2: student resolves conflict side, AICTE adjudicates, wallet + offline verify + tamper +
// revocation, consent, regulator, university degree, audit chain, access log, registry outage.
import { BASE, launch, newPage, problems, shot, sleep, waitText, clickText, login, studentLogin } from "./lib.mjs";

const go = (p, path) => p.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
const browser = await launch();
const step = (s) => console.log("•", s);
try {
  // 1. Vignesh (reported by two colleges) answers the conflict
  const vig = await newPage(browser, "vignesh");
  await studentLogin(vig, "Vignesh Murugan");
  await waitText(vig, "Two institutions have reported you");
  await shot(vig, "12_student_conflict_banner");
  await vig.evaluate(() => [...document.querySelectorAll("div.rounded")].find((d) => d.innerText.includes("Aarohan Institute") && d.querySelector("button")).querySelector("button").click());
  await sleep(1200);
  step("student answered: " + (await vig.evaluate(() => document.body.innerText.includes("You told us you study here"))));

  // 2. AICTE adjudicates
  const aicte = await newPage(browser, "aicte");
  await login(aicte, "aicte.admin");
  await go(aicte, "/aicte/conflicts");
  await waitText(aicte, "Student responded");
  await aicte.evaluate(() => [...document.querySelectorAll("tr")].find((r) => r.innerText.includes("Student responded")).click());
  await waitText(aicte, "Decision");
  await shot(aicte, "13_aicte_adjudicate");
  await clickText(aicte, "Confirm selected enrolment");
  await sleep(1200);
  step("toast: " + (await aicte.evaluate(() => [...document.querySelectorAll(".fixed")].map((e) => e.innerText).join("|"))));

  // anomalies detail
  await go(aicte, "/aicte/anomalies");
  await waitText(aicte, "Fill rate rose");
  await aicte.evaluate(() => [...document.querySelectorAll("tr")].find((r) => r.innerText.includes("Fill rate rose")).click());
  await waitText(aicte, "Fill rate by year");
  await shot(aicte, "14_anomaly_explained");
  await aicte.keyboard.press("Escape");
  await go(aicte, "/aicte/anomalies?kind=CATEGORY_SHIFT");
  await waitText(aicte, "share rose");
  await aicte.evaluate(() => [...document.querySelectorAll("tr")].find((r) => r.innerText.includes("share rose")).click());
  await waitText(aicte, "Category shares");
  await shot(aicte, "15_category_shift");

  // 3. Kavya issues a credential, shares only name + programme
  const kav = await newPage(browser, "kavya");
  await studentLogin(kav, "Kavya Senthil");
  await go(kav, "/student/wallet");
  await waitText(kav, "Request credential");
  await clickText(kav, "Request credential");
  await waitText(kav, "Information to share");
  await shot(kav, "16_wallet_qr");
  const url = await kav.evaluate(() => document.querySelector("a[href*='/verify#vp=']").href);
  step("verify url length " + url.length);

  // 4. Public verifier (separate, anonymous context)
  const ver = await newPage(browser, "verifier");
  await ver.goto(url, { waitUntil: "domcontentloaded" });
  await waitText(ver, "Valid enrolment", 20000);
  await shot(ver, "17_verify_valid");
  const shown = await ver.evaluate(() => document.body.innerText);
  step("verifier shows category? " + /Category\s/.test(shown) + " · shows name? " + shown.includes("Kavya Senthil"));

  // tamper: change a disclosed value
  const tampered = await ver.evaluate((u) => {
    const vp = decodeURIComponent(u.split("#vp=")[1]);
    const [jwt, d1, ...rest] = vp.split("~");
    const arr = JSON.parse(atob(d1.replace(/-/g, "+").replace(/_/g, "/")));
    arr[2] = "Someone Else";
    const forged = btoa(JSON.stringify(arr)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    return [jwt, forged, ...rest].join("~");
  }, url);
  await ver.goto(`${BASE}/verify`, { waitUntil: "domcontentloaded" });
  await ver.waitForSelector("textarea");
  await ver.evaluate((v) => {
    const ta = document.querySelector("textarea");
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(ta, v);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }, tampered);
  await clickText(ver, "Verify");
  await waitText(ver, "is not valid");
  await shot(ver, "18_verify_tampered");

  // 5. Offline: block the network, verify the genuine QR again from cache
  await ver.setOfflineMode(true);
  await ver.goto(`${BASE}/verify`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await ver.setOfflineMode(false);
  // (SPA shell needs the network to load; emulate "offline after load" instead)
  await ver.goto(url, { waitUntil: "domcontentloaded" });
  await waitText(ver, "Valid enrolment", 20000);
  await ver.setOfflineMode(true);
  await clickText(ver, "Verify");
  await waitText(ver, "offline", 15000);
  await shot(ver, "19_verify_offline");
  await ver.setOfflineMode(false);

  // 6. Online verification by an "HR system" lands in Kavya's access log
  await clickText(ver, "Verify with the registry");
  await waitText(ver, "Confirmed by the registry");

  // 7. Dakshin admin asks Kavya for access -> denied until consent -> approved -> sees only those fields
  const dak = await newPage(browser, "admin-dakshin");
  await login(dak, "admin.dakshin");
  await go(dak, "/institution/requests");
  await waitText(dak, "Request access");
  const kavApaar = await kav.evaluate(async () => (await (await fetch("/api/v1/me/record", { headers: { Authorization: "Bearer " + localStorage.getItem("spine.token") } })).json()).apaar_id);
  await dak.evaluate((a) => {
    const set = (el, v) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, v); el.dispatchEvent(new Event("input", { bubbles: true })); };
    const inputs = document.querySelectorAll("input");
    set(inputs[0], a); set(inputs[1], "Lateral entry admission verification");
  }, kavApaar);
  await clickText(dak, "Send request");
  await sleep(1000);
  await go(kav, "/student");
  await waitText(kav, "Requests to access your record");
  await shot(kav, "20_student_consent_request");
  await clickText(kav, "Allow");
  await sleep(800);
  await go(dak, "/institution/requests");
  await waitText(dak, "View record");
  await clickText(dak, "View record");
  await waitText(dak, "Shared with the student");
  await shot(dak, "21_consented_record");

  // 8. Kavya's access log
  await go(kav, "/student/access");
  await waitText(kav, "Access history");
  await sleep(800);
  await shot(kav, "22_access_log");
  const log = await kav.evaluate(() => document.body.innerText);
  step("access log has: VERIFY_ONLINE=" + log.includes("Verified your credential with the registry") + " consent=" + log.includes("You granted access") + " read=" + log.includes("Viewed your record"));

  // 9. Revoke Kavya's credential via API as her institution, re-verify
  const inst = await newPage(browser, "admin-aarohan");
  await login(inst, "admin.aarohan");
  const credId = await kav.evaluate(async () => (await (await fetch("/api/v1/me/credentials", { headers: { Authorization: "Bearer " + localStorage.getItem("spine.token") } })).json())[0].id);
  const r = await inst.evaluate(async (id) => (await fetch(`/api/v1/credentials/${id}/revoke`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + localStorage.getItem("spine.token") }, body: JSON.stringify({ reason: "demo revocation" }) })).status, credId);
  step("revoke status " + r);
  await ver.goto(url, { waitUntil: "domcontentloaded" });
  await waitText(ver, "revoked", 20000);
  await shot(ver, "23_verify_revoked");

  // 10. Regulator
  const reg = await newPage(browser, "regulator");
  await login(reg, "naac.auditor");
  await waitText(reg, "Audit queries");
  await reg.evaluate(() => {
    const sel = document.querySelector("select");
    const opt = [...sel.options].find((o) => o.text.includes("Gyanodaya"));
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(sel, opt.value);
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    const inp = document.querySelector("input");
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(inp, "NAAC accreditation cycle 2026: enrolment verification");
    inp.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await clickText(reg, "Run query");
  await waitText(reg, "Reference", 20000);
  await shot(reg, "24_regulator_query");

  // 11. University issues Divya's degree
  const uni = await newPage(browser, "registrar");
  await login(uni, "registrar.tnstu");
  await waitText(uni, "Divya Krishnan");
  await uni.evaluate(() => [...document.querySelectorAll("tr")].find((r) => r.innerText.includes("Divya Krishnan")).querySelector("button").click());
  await waitText(uni, "Sign and issue");
  await clickText(uni, "Sign and issue");
  await sleep(2000);
  await shot(uni, "25_university_issued");
  const divya = await newPage(browser, "divya");
  await studentLogin(divya, "Divya Krishnan");
  await go(divya, "/student/wallet");
  await waitText(divya, "Bachelor of Technology");
  await shot(divya, "26_degree_wallet");

  // 12. Audit chain
  await go(aicte, "/aicte/audit");
  await waitText(aicte, "Check integrity");
  await clickText(aicte, "Check integrity");
  await waitText(aicte, "Integrity check passed", 30000);
  await shot(aicte, "27_audit_chain");

  // 13. Registry outage -> graceful degradation on the add-student form
  await go(aicte, "/aicte/system");
  await waitText(aicte, "Simulate outage");
  await clickText(aicte, "Simulate outage");
  await sleep(800);
  await shot(aicte, "28_registry_down");
  await go(inst, "/institution/add");
  await waitText(inst, "Add a student");
  const demo = await inst.evaluate(async () => (await fetch("/api/v1/dev/demo-accounts")).json());
  // use a spare registry identity from demo CSV 1 row 3 (valid, not yet uploaded? rows 1-6 were uploaded) -> pick via API-free path: reuse csv row 2 of the Dakshin file? Use a fresh name; registry is down so it is accepted as pending
  await inst.evaluate(() => {
    const set = (label, v) => {
      const l = [...document.querySelectorAll("label")].find((x) => x.innerText.trim().startsWith(label));
      const el = l.parentElement.querySelector("input,select");
      const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
      el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
    };
    set("Roll number", "26CSE555"); set("APAAR ID", "391417776315"); set("Full name", "Outage Demo"); set("Date of birth", "2008-04-04");
    set("Programme", "BTECH-CSE"); set("Date of admission", "2026-11-20");
  });
  await clickText(inst, "Submit");
  await waitText(inst, "Returned for correction", 20000);
  await shot(inst, "29_outage_submission");
  step("outage submission findings: " + (await inst.evaluate(() => [...document.querySelectorAll("li")].map((l) => l.innerText).filter((t) => /R4\d/.test(t)).join(" | "))));
  await go(aicte, "/aicte/system");
  await waitText(aicte, "Restore");
  await clickText(aicte, "Restore");
} catch (e) {
  console.error("STAGE FAILED:", e.message);
} finally {
  console.log("PROBLEMS:\n" + (problems.join("\n") || "none"));
  await browser.close();
}
