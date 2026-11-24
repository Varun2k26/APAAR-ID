// Stage 1: login screens, AICTE overview with live feed, CSV upload with errors, fix-in-place,
// and a second college uploading a duplicate while AICTE watches.
import { BASE, DEMO, launch, newPage, problems, shot, sleep, waitText, clickText, login } from "./lib.mjs";

const browser = await launch();
try {
  const pub = await newPage(browser, "public");
  await pub.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
  await waitText(pub, "Demo accounts");
  await shot(pub, "01_login");

  const aicte = await newPage(browser, "aicte");
  await login(aicte, "aicte.admin");
  await waitText(aicte, "National overview");
  await waitText(aicte, "Live");
  await shot(aicte, "02_aicte_overview");

  // Operator at Aarohan uploads the CSV with mistakes
  const op = await newPage(browser, "op-aarohan");
  await login(op, "operator.aarohan");
  await shot(op, "03_institution_dashboard");
  await op.goto(`${BASE}/institution/upload`, { waitUntil: "domcontentloaded" }); await op.waitForSelector("input[type=file]");
  const input = await op.$('input[type="file"]');
  await input.uploadFile(`${DEMO}1_aarohan_new_admissions.csv`);
  await waitText(op, "rows read");
  await shot(op, "04_upload_precheck");
  await clickText(op, "Submit 14 rows");
  await waitText(op, "Returned for correction", 30000);
  await shot(op, "05_upload_report");
  const reportText = await op.evaluate(() => document.body.innerText);
  console.log("report has:", ["R40", "R42", "R44", "R31", "R30", "R02", "R23", "R32"].map((c) => `${c}:${reportText.includes(c)}`).join(" "));

  // Fix the lateral-entry row in place
  await op.goto(`${BASE}/institution/issues`, { waitUntil: "domcontentloaded" });
  await waitText(op, "Returned rows");
  await shot(op, "06_issue_queue");
  const fixed = await op.evaluate(() => {
    const rows = [...document.querySelectorAll("tr")].filter((r) => r.innerText.includes("R23"));
    if (!rows[0]) return false;
    rows[0].querySelector("button").click();
    return true;
  });
  console.log("found R23 row:", fixed);
  await waitText(op, "Resubmit row");
  // change year_of_study select (the one highlighted) to 2
  await op.evaluate(() => {
    const labels = [...document.querySelectorAll("label")];
    const l = labels.find((x) => x.innerText.trim() === "Year of study");
    const sel = l.parentElement.querySelector("select");
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
    setter.call(sel, "2");
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await shot(op, "07_fix_form");
  await clickText(op, "Resubmit row");
  await sleep(1500);
  await shot(op, "08_after_fix");
  console.log("toast:", await op.evaluate(() => [...document.querySelectorAll(".fixed")].map((e) => e.innerText).join("|")));

  // Second college uploads a student who is already at Aarohan: AICTE sees it live
  const before = await aicte.evaluate(() => document.body.innerText.split("Duplicate enrolment found").length - 1);
  const op2 = await newPage(browser, "op-dakshin");
  await login(op2, "operator.dakshin");
  await op2.goto(`${BASE}/institution/upload`, { waitUntil: "domcontentloaded" }); await op2.waitForSelector("input[type=file]");
  await (await op2.$('input[type="file"]')).uploadFile(`${DEMO}2_dakshin_upload_with_duplicates.csv`);
  await waitText(op2, "rows read");
  await clickText(op2, "Submit 5 rows");
  await waitText(op2, "Returned for correction", 30000);
  await shot(op2, "09_dakshin_report_conflict");
  await sleep(3500);
  const after = await aicte.evaluate(() => document.body.innerText.split("Duplicate enrolment found").length - 1);
  console.log(`AICTE live feed 'Duplicate enrolment found' count: ${before} -> ${after}`);
  await shot(aicte, "10_aicte_live_feed_after");
  await op2.goto(`${BASE}/institution/conflicts`, { waitUntil: "domcontentloaded" });
  await waitText(op2, "Another AICTE institution");
  await shot(op2, "11_dakshin_conflicts_minimised");
} catch (e) {
  console.error("STAGE FAILED:", e.message);
} finally {
  console.log("PROBLEMS:\n" + (problems.join("\n") || "none"));
  await browser.close();
}
