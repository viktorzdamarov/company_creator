// Full editor scenario in the browser against the DEMO server (DEMO_MODE=true): add, Push, Pin, Remove, Bring back, Cancel.
// Creates its own campaign through the API, so it can be run repeatedly.  Run: ADROBOT_URL=http://127.0.0.1:8002 npm run demo
const puppeteer = require("puppeteer-core");
const BASE = process.env.ADROBOT_URL || "http://127.0.0.1:8000";
const OUT = process.argv[2] || ".";
const results = [];
const check = (name, ok, extra = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`); };

(async () => {
  const name = "e2e-" + Date.now();
  const created = await (await fetch(BASE + "/api/campaigns", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, geo: "AU", offer_id: 9001 }),
  })).json();
  const browser = await puppeteer.launch({
    executablePath: process.env.BROWSER_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true, args: ["--disable-gpu"], defaultViewport: { width: 1200, height: 900 },
  });
  const page = await browser.newPage();
  page.on("dialog", d => d.accept());
  const jsErrors = [];
  page.on("pageerror", e => jsErrors.push(e.message));

  const offers = () => page.$$eval(".offers li", ls => ls.map(l => ({
    id: l.dataset.offer, share: l.querySelector(".share").textContent, grey: l.classList.contains("grey"),
    pinned: !!l.querySelector(".pin.on"), tag: (l.querySelector(".tag") || {}).textContent || "",
  })));
  const dirty = () => page.$eval(".flow:nth-child(2)", f => f.classList.contains("dirty"));
  const flash = () => page.$eval("#flash", e => e.textContent);
  const waitFlash = text => page.waitForFunction(t => document.querySelector("#flash").textContent.includes(t), { timeout: 15000 }, text);
  const addOffer = async id => {
    await page.$eval(".add-offer .ac-input", e => (e.value = ""));
    await page.type(".add-offer .ac-input", String(id));
    await page.waitForSelector(".add-offer .ac-list .ac-item", { visible: true, timeout: 10000 });
    await page.keyboard.press("Enter");
    await page.click(".add-btn");
    await waitFlash(`Оффер ${id} добавлен`);
  };
  const clickOffer = async (id, sel, text) => {
    await page.click(`.offers li[data-offer="${id}"] ${sel}`);
    await waitFlash(text);
  };
  const shares = async () => Object.fromEntries((await offers()).map(o => [o.id, o.share]));

  await page.goto(`${BASE}/edit/${created.campaign_id}`, { waitUntil: "networkidle0" });
  await page.waitForSelector("#campaign:not([hidden]) .flow", { timeout: 15000 });
  check("auto Fetch on first open", (await offers()).length === 1 && !(await dirty()));

  await addOffer(9002);
  check("add 9002: yellow, 50/50, nothing published", (await dirty()) && JSON.stringify(await shares()) === '{"9001":"50%","9002":"50%"}');
  await addOffer(9003);
  await addOffer(9004);
  check("4 offers -> 25% each", Object.values(await shares()).every(s => s === "25%"));

  await page.click(".push-btn");
  await waitFlash("Опубликовано");
  check("Push: flow clean again", !(await dirty()));
  await page.click("#reload");
  await waitFlash("загружены");
  check("Fetch streams after Push: 4 active offers", (await offers()).length === 4 && !(await dirty()));

  await clickOffer(9001, ".pin", "закреплена");
  check("pin 9001", (await offers()).find(o => o.id === "9001").pinned);
  await clickOffer(9004, ".remove-offer", "помечен удалённым");
  const s = await shares();
  check("remove 9004: grey 0%, pinned stays 25%, rest 38/37", s["9004"] === "0%" && s["9001"] === "25%" && s["9002"] === "38%" && s["9003"] === "37%", JSON.stringify(s));
  await page.screenshot({ path: OUT + "/ui-demo-dirty.png" });

  await page.click(".push-btn");
  await waitFlash("Опубликовано");
  const archived = (await offers()).find(o => o.id === "9004");
  check("Push: removed offer stays in archive (grey, removed)", archived.grey && archived.tag === "removed");

  await clickOffer(9004, ".bring-back", "возвращён");
  check("Bring back: yellow, 9004 active again, 25% each", (await dirty()) && Object.values(await shares()).every(x => x === "25%"));
  await page.click(".cancel-btn");
  await waitFlash("отменены");
  check("Cancel: 9004 back in archive, flow clean", (await offers()).find(o => o.id === "9004").tag === "removed" && !(await dirty()));

  await addOffer(9005);
  await page.click(".cancel-btn");
  await waitFlash("отменены");
  check("Cancel forgets a never-published offer", !(await offers()).some(o => o.id === "9005"));

  await page.reload({ waitUntil: "networkidle0" });
  await page.waitForSelector(".flow");
  check("state survives page reload (local DB)", (await offers()).length === 4);
  await page.screenshot({ path: OUT + "/ui-demo-final.png" });

  check("no JS errors", jsErrors.length === 0, JSON.stringify(jsErrors));
  await browser.close();
  console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
  process.exit(results.every(Boolean) ? 0 : 1);
})().catch(e => { console.error(e); process.exit(2); });
