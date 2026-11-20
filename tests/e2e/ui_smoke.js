// UI smoke: no changes in Keitaro (dry-run create; editor works on the local draft and never presses Push).
// The editor part needs a campaign with an offer flow whose name contains "adrobot-test".
const puppeteer = require("puppeteer-core");
const BASE = process.env.ADROBOT_URL || "http://127.0.0.1:8000";
const OUT = process.argv[2] || ".";
const OFFER_Q = process.env.ADROBOT_OFFER_QUERY || "flex", OFFER_ID = process.env.ADROBOT_OFFER_ID || "18813";
const results = [];
const check = (name, ok, extra = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`); };

(async () => {
  const browser = await puppeteer.launch({
    executablePath: process.env.BROWSER_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true, args: ["--disable-gpu"], defaultViewport: { width: 1200, height: 900 },
  });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", m => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", e => consoleErrors.push(e.message));

  // ---------- create page
  await page.goto(BASE + "/create", { waitUntil: "networkidle0" });

  await page.click("#create-btn");
  check("empty form -> client validation", (await page.$eval("#create-error", e => !e.hidden && e.textContent)) === "Укажите название кампании");

  await page.type("#name", "adrobot-test-ui");
  await page.type("#geo", "au, XX1");
  await page.type("#offer", OFFER_Q);
  await page.waitForSelector(".ac-list .ac-item", { visible: true, timeout: 10000 });
  const acText = await page.$eval(".ac-list .ac-item", e => e.textContent);
  check("offer autocomplete shows results", acText.includes(OFFER_ID), `"${acText}"`);
  await page.keyboard.press("Enter");
  check("autocomplete selection sets offer id", (await page.$eval("#offer_id", e => e.value)) === OFFER_ID);

  await page.click("#dry_run");
  await page.click("#create-btn");
  await page.waitForFunction(() => !document.querySelector("#create-error").hidden && !document.querySelector("#create-btn").disabled, { timeout: 15000 });
  const geoErr = await page.$eval("#create-error", e => e.textContent);
  check("invalid geo -> server error shown", geoErr.includes("XX1"), `"${geoErr}"`);

  await page.$eval("#geo", e => (e.value = ""));
  await page.type("#geo", "au,mx");
  await page.click("#create-btn");
  await page.waitForSelector("#result:not([hidden])", { timeout: 15000 });
  const title = await page.$eval("#result-title", e => e.textContent);
  const streams = await page.$$eval("#r-streams li", ls => ls.map(l => l.textContent));
  check("dry-run result rendered", title.startsWith("Предпросмотр") && streams.length === 2, JSON.stringify(streams));
  check("flow 1 has AU,MX -> google", streams[0].includes("AU,MX") && streams[0].includes("google.com"));
  check("payload preview visible", !(await page.$eval("#r-payloads", e => e.hidden)));
  await page.screenshot({ path: OUT + "/ui-create-dry.png" });

  // ---------- editor
  await page.goto(BASE + "/edit", { waitUntil: "networkidle0" });
  await page.type("#campaign-search", process.env.ADROBOT_CAMPAIGN || "adrobot-test");
  await page.waitForSelector(".ac-list .ac-item", { visible: true, timeout: 10000 });
  await page.keyboard.press("Enter");
  await page.waitForSelector("#campaign:not([hidden]) .flow", { timeout: 15000 });
  check("campaign search -> opens editor", /\/edit\/\d+$/.test(page.url()), page.url());
  const flows = await page.$$eval(".flow", fs => fs.length);
  check("two flows rendered", flows === 2);
  check("clean flow: Push and Cancel disabled", await page.$eval(".push-btn", b => b.disabled) && await page.$eval(".cancel-btn", b => b.disabled));

  // duplicate offer -> error (nothing changes)
  const firstOffer = await page.$eval(".offers li", li => li.dataset.offer);
  await page.type(".add-offer .ac-input", firstOffer);
  await page.waitForSelector(".add-offer .ac-list .ac-item", { visible: true, timeout: 10000 });
  await page.keyboard.press("Enter");
  await page.click(".add-btn");
  await page.waitForFunction(() => document.querySelector("#flash").classList.contains("alert-error"), { timeout: 15000 });
  const flash = await page.$eval("#flash", e => e.className + " | " + e.textContent);
  check("duplicate offer -> error flash", flash.includes("alert-error"), `"${flash}"`);

  // draft workflow, local only (never pressing Push): remove -> yellow flow, grey offer 0% -> Bring back -> clean
  await page.click(".remove-offer");
  await page.waitForSelector(".flow.dirty .offers li.grey", { timeout: 15000 });
  check("remove -> flow yellow, offer grey 0%", (await page.$eval(".offers li.grey .share", e => e.textContent)) === "0%");
  check("Push and Cancel enabled when dirty", !(await page.$eval(".push-btn", b => b.disabled)) && !(await page.$eval(".cancel-btn", b => b.disabled)));
  await page.screenshot({ path: OUT + "/ui-edit-dirty.png" });
  await page.click(".bring-back");
  await page.waitForSelector(".flow:not(.dirty) .offers li:not(.grey)", { timeout: 15000 });
  check("bring back -> flow clean again", true);

  // remove again, then Cancel (confirm dialog accepted)
  await page.click(".remove-offer");
  await page.waitForSelector(".flow.dirty", { timeout: 15000 });
  page.once("dialog", d => d.accept());
  await page.click(".cancel-btn");
  await page.waitForSelector(".flow:not(.dirty) .offers li:not(.grey)", { timeout: 15000 });
  check("cancel -> flow clean again", true);

  await page.goto(BASE + "/edit/999999999", { waitUntil: "networkidle0" });
  await page.waitForFunction(() => document.querySelector("#flash").classList.contains("alert-error"), { timeout: 15000 });
  check("unknown campaign -> error", (await page.$eval("#flash", e => e.textContent)).toLowerCase().includes("not found"));

  check("no JS errors in console", consoleErrors.filter(e => !e.startsWith("Failed to load resource")).length === 0, JSON.stringify(consoleErrors));
  await browser.close();
  console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
  process.exit(results.every(Boolean) ? 0 : 1);
})().catch(e => { console.error(e); process.exit(2); });
