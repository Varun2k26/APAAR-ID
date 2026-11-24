import puppeteer from "puppeteer-core";
export const BASE = process.env.BASE_URL || "http://localhost:8000";
export const SHOTS = new URL("./shots/", import.meta.url).pathname;
export const DEMO = process.env.DEMO_DIR || new URL("../../data/demo/", import.meta.url).pathname;
export const problems = [];

export async function launch() {
  return puppeteer.launch({
    executablePath: process.env.CHROME_PATH || "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    headless: "new", args: ["--no-first-run", "--disable-features=BraveRewards"], defaultViewport: { width: 1440, height: 900 },
  });
}

export async function newPage(browser, tag) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push(`[${tag}] pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") problems.push(`[${tag}] console: ${m.text()}`); });
  page.on("response", (r) => { if (r.status() >= 400 && r.url().includes("/api/")) problems.push(`[${tag}] HTTP ${r.status()} ${r.request().method()} ${r.url().replace(BASE, "")}`); });
  return page;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function waitText(page, text, timeout = 15000) {
  await page.waitForFunction((t) => document.body && document.body.innerText.toLowerCase().includes(t.toLowerCase()), { timeout }, text);
}

export async function clickText(page, text, selector = "button, a, label") {
  const ok = await page.evaluate((t, sel) => {
    const els = [...document.querySelectorAll(sel)].filter((e) => e.innerText && e.innerText.trim().includes(t) && e.offsetParent !== null);
    els.sort((a, b) => a.innerText.length - b.innerText.length);
    if (!els[0]) return false;
    els[0].click();
    return true;
  }, text, selector);
  if (!ok) throw new Error(`no clickable element with text "${text}"`);
  await sleep(400);
}

export async function shot(page, name) {
  await sleep(600);
  await page.screenshot({ path: `${SHOTS}${name}.png`, fullPage: false });
}

export async function login(page, username) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
  await waitText(page, username);
  await page.evaluate((u) => {
    const row = [...document.querySelectorAll("tr")].find((r) => r.innerText.includes(u));
    row.querySelector("button").click();
  }, username);
  await sleep(800);
  if (await page.evaluate(() => document.body.innerText.includes("2-step verification"))) {
    await page.evaluate(() => [...document.querySelectorAll("button")].find((b) => /^\d{6}$/.test(b.innerText.trim())).click());
    await sleep(200);
    await clickText(page, "Continue");
  }
  await page.waitForFunction(() => !location.pathname.startsWith("/login"), { timeout: 10000 });
  await sleep(1200);
}

export async function studentLogin(page, name) {
  await page.goto(`${BASE}/mock-digilocker`, { waitUntil: "networkidle0" });
  await waitText(page, name);
  await clickText(page, name);
  await clickText(page, "Allow");
  await page.waitForFunction(() => location.pathname === "/student", { timeout: 10000 });
  await sleep(1200);
}
