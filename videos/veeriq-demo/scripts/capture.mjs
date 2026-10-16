// Records the real VeerIQ app for the submission video: a visible cursor, a highlight before every click,
// and a marks file so the edit can cut on real moments. Two takes:
//   live    the flagship poisoned run with a live model and live ArmorIQ (retries until ArmorIQ blocks the trap)
//   import  the warehouse sample through /import (the import UI runs a labelled scripted planner)
//   judges  the four-step start page judges use: damage, rollback vs VeerIQ (live model + live ArmorIQ),
//           the judge approving the $12,400 repair, and in-browser verification (retries until ArmorIQ blocks)
// Usage: node scripts/capture.mjs live|import|judges   (app on http://localhost:5173, System · Live)
import { chromium } from "../../../../VeerIQ/frontend/node_modules/playwright/index.mjs";
import fs from "node:fs";
import path from "node:path";

const BASE = "http://localhost:5173";
const TAKE = process.argv[2] || "live";
const OUT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../assets/footage");
fs.mkdirSync(OUT, { recursive: true });

const OVERLAY = () => {
  const css = `
  #__cur{position:fixed;z-index:2147483647;width:24px;height:24px;margin:-4px 0 0 -4px;pointer-events:none;
    transition:transform .08s;filter:drop-shadow(0 2px 4px rgba(0,0,0,.6))}
  #__cur.down{transform:scale(.82)}
  #__ring{position:fixed;z-index:2147483646;pointer-events:none;border:3px solid #FBBF24;border-radius:12px;
    opacity:0;transition:opacity .25s;animation:__p 1s ease-in-out infinite}
  #__tag{position:fixed;z-index:2147483646;pointer-events:none;background:#FBBF24;color:#111;font:600 17px/1 -apple-system,Helvetica,sans-serif;
    padding:9px 14px;border-radius:999px;opacity:0;transition:opacity .25s;white-space:nowrap}
  @keyframes __p{0%,100%{box-shadow:0 0 0 4px rgba(251,191,36,.25),0 0 22px rgba(251,191,36,.45)}50%{box-shadow:0 0 0 10px rgba(251,191,36,.12),0 0 36px rgba(251,191,36,.7)}}`;
  const add = () => {
    if (document.getElementById("__cur") || !document.body) return;
    const s = document.createElement("style"); s.textContent = css; document.head.appendChild(s);
    const c = document.createElement("div"); c.id = "__cur";
    c.innerHTML = '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M3 2l7 19 2.6-7.6L20 11z" fill="#fff" stroke="#111" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    c.style.left = (window.__cx ?? -50) + "px"; c.style.top = (window.__cy ?? -50) + "px";
    const r = document.createElement("div"); r.id = "__ring";
    const t = document.createElement("div"); t.id = "__tag";
    document.body.append(c, r, t);
  };
  document.addEventListener("DOMContentLoaded", add);
  window.addEventListener("mousemove", (e) => { window.__cx = e.clientX; window.__cy = e.clientY; add();
    const c = document.getElementById("__cur"); if (c) { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; } }, true);
  window.addEventListener("mousedown", () => document.getElementById("__cur")?.classList.add("down"), true);
  window.addEventListener("mouseup", () => document.getElementById("__cur")?.classList.remove("down"), true);
  window.__hl = (x, y, w, h, label) => { add(); const r = document.getElementById("__ring"), t = document.getElementById("__tag");
    Object.assign(r.style, { left: x - 8 + "px", top: y - 8 + "px", width: w + 16 + "px", height: h + 16 + "px", opacity: 1 });
    t.textContent = label; t.style.opacity = label ? 1 : 0; const above = y > 80;
    Object.assign(t.style, { left: x + w / 2 + "px", top: (above ? y - 56 : y + h + 20) + "px", transform: "translateX(-50%)" }); };
  window.__unhl = () => { for (const id of ["__ring", "__tag"]) { const e = document.getElementById(id); if (e) e.style.opacity = 0; } };
};

async function session(name) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: path.join(OUT, ".raw-" + name), size: { width: 1920, height: 1080 } } });
  await ctx.addInitScript(OVERLAY);
  const page = await ctx.newPage();
  page.setDefaultTimeout(20000);
  const t0 = Date.now(), marks = {}, now = () => +((Date.now() - t0) / 1000).toFixed(2);
  let mx = 960, my = 600;
  const mark = (k) => { marks[k] = now(); };
  async function moveTo(x, y, ms = 700) {
    const steps = Math.max(10, Math.round(ms / 16));
    for (let i = 1; i <= steps; i++) { const k = i / steps, e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      await page.mouse.move(mx + (x - mx) * e, my + (y - my) * e); await page.waitForTimeout(ms / steps); }
    mx = x; my = y;
  }
  // Highlight the target, glide the cursor onto it, then click (or press and hold).
  async function act(loc, label, { holdMs = 0, showMs = 1100, click = true } = {}) {
    await loc.scrollIntoViewIfNeeded();
    const b = await loc.boundingBox();
    await page.evaluate(([x, y, w, h, l]) => window.__hl(x, y, w, h, l), [b.x, b.y, b.width, b.height, label]);
    await page.waitForTimeout(450);
    await moveTo(b.x + Math.min(b.width / 2, 160), b.y + b.height / 2, 750);
    await page.waitForTimeout(showMs);
    if (click) { await page.mouse.down(); await page.waitForTimeout(holdMs || 90); await page.mouse.up(); }
    await page.evaluate(() => window.__unhl()).catch(() => {});
  }
  async function spot(loc, label = "", ms = 1800) {   // highlight without clicking
    await loc.scrollIntoViewIfNeeded(); const b = await loc.boundingBox();
    await page.evaluate(([x, y, w, h, l]) => window.__hl(x, y, w, h, l), [b.x, b.y, b.width, b.height, label]);
    await page.waitForTimeout(ms); await page.evaluate(() => window.__unhl());
  }
  async function scrollTo(loc, offset = 120, ms = 1300) {
    const h = await loc.first().elementHandle();
    await page.evaluate(([el, off, ms]) => new Promise((res) => {
      const start = window.scrollY, target = Math.max(0, el.getBoundingClientRect().top + start - off), t = performance.now();
      const step = (n) => { const k = Math.min(1, (n - t) / ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        window.scrollTo(0, start + (target - start) * e); k < 1 ? requestAnimationFrame(step) : res(); };
      requestAnimationFrame(step); }), [h, offset, ms]);
  }
  const scrollTop = (ms = 1200) => page.evaluate((ms) => new Promise((res) => { const s = window.scrollY, t = performance.now();
    const step = (n) => { const k = Math.min(1, (n - t) / ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      window.scrollTo(0, s * (1 - e)); k < 1 ? requestAnimationFrame(step) : res(); }; requestAnimationFrame(step); }), ms);
  async function finish(ok) {
    const video = page.video(); await ctx.close();
    if (ok) { await video.saveAs(path.join(OUT, name + ".webm")); fs.writeFileSync(path.join(OUT, name + ".marks.json"), JSON.stringify(marks, null, 1)); }
    await browser.close(); fs.rmSync(path.join(OUT, ".raw-" + name), { recursive: true, force: true });
  }
  return { page, mark, marks, act, spot, scrollTo, scrollTop, moveTo, finish, now };
}

async function liveTake(n) {
  const s = await session("live"), p = s.page;
  await p.goto(BASE); await p.mouse.move(960, 600);
  await p.getByText("Repair the damage.").waitFor(); s.mark("home");
  await p.waitForTimeout(2200);
  await s.act(p.getByRole("button", { name: "Review grant" }).first(), "Click: Review grant");
  // The dialog opens either on the grant itself or on "already repaired": wait for one of them, then reset if needed.
  await p.getByRole("button", { name: /Reset and review grant|Hold to authorize/ }).first().waitFor();
  const reset = p.getByRole("button", { name: "Reset and review grant" });
  if (await reset.count()) await s.act(reset, "Click: Reset and review grant", { showMs: 700 });
  await p.getByRole("button", { name: /Hold to authorize/ }).waitFor(); s.mark("grant");
  await p.waitForTimeout(800);
  await s.spot(p.getByText(/The agent may repair 2 orders/), "", 2600);
  await s.act(p.getByText("Live LLM", { exact: true }), "Click: Live LLM (real model)", { showMs: 700 });
  s.mark("hold");
  await s.act(p.getByRole("button", { name: /Hold to authorize/ }), "Press & hold: Authorize & start", { holdMs: 2200, showMs: 700 });
  await p.waitForURL(/runs\//, { timeout: 30000 }); s.mark("runStart");
  await p.mouse.move(1880, 1040);
  await p.getByText("What the agent did").first().waitFor({ timeout: 60000 });
  await p.waitForTimeout(1200);
  await s.scrollTo(p.getByText("What the agent did").first(), 90, 1200);
  const deadline = Date.now() + 240000; let blockAt = null;
  while (Date.now() < deadline) {
    const top = (await p.innerText("main")).slice(0, 500);
    if (!blockAt && (await p.getByText("Stopped by ArmorIQ").count())) { blockAt = s.now(); s.marks.blockSeen = blockAt; }
    if (/\b(Repaired|Partially repaired|Failed|Stopped)\b/.test(top) && !/Running|Starting/.test(top.slice(0, 200))) break;
    await p.evaluate(() => window.scrollBy({ top: 140, behavior: "smooth" })); await p.waitForTimeout(2500);
  }
  s.mark("runEnd");
  const txt = await p.innerText("main");
  const ok = /Repaired/.test(txt.slice(0, 400)) && /Stopped by ArmorIQ/.test(txt) && /Live ArmorIQ/.test(txt) && /Live LLM/.test(txt);
  console.log(`live take ${n}: ok=${ok} url=${p.url()}`);
  if (!ok) { await s.finish(false); return false; }
  s.marks.runUrl = p.url();
  await s.scrollTop(1300); s.mark("resultTop"); await p.waitForTimeout(1500);
  await s.spot(p.getByText("The agent tried. The boundary held.").locator(".."), "", 3200); s.mark("boundaryHeld");
  await s.scrollTo(p.getByRole("heading", { name: "Repaired" }).first().or(p.getByText("Show the blocked request").first()), 140, 1400); s.mark("gates");
  await p.waitForTimeout(3000);
  await s.scrollTo(p.getByText("Must stay true").first(), 300, 1400); s.mark("orders");
  await p.waitForTimeout(3500);
  s.mark("end"); await p.waitForTimeout(600);
  await s.finish(true); return true;
}

async function importTake() {
  const s = await session("import"), p = s.page;
  await p.goto(BASE + "/import"); await p.mouse.move(960, 600);
  await p.getByText("Bring your data.").waitFor(); s.mark("home"); await p.waitForTimeout(2200);
  await s.act(p.getByRole("button", { name: "Warehouse stock locations" }), "Click: load the warehouse sample");
  s.mark("loaded"); await p.waitForTimeout(1200);
  await s.scrollTo(p.getByText("Map the columns").first(), 110, 1500); s.mark("map"); await p.waitForTimeout(1800);
  await s.scrollTo(p.getByText("Map the protection flags").first(), 110, 1300); await p.waitForTimeout(1600);
  await s.scrollTo(p.getByText("Repairable columns").first(), 110, 1300); await p.waitForTimeout(1600);
  await s.act(p.getByRole("button", { name: "Validate and preview" }), "Click: Validate and preview"); s.mark("validate");
  await p.getByText("Validated comparison").waitFor();
  await s.scrollTo(p.getByText("Validated comparison").first(), 120, 1300); s.mark("preview"); await p.waitForTimeout(3000);
  await s.act(p.getByRole("button", { name: /Review repair permission/ }), "Click: Review repair permission"); s.mark("review");
  await p.getByText("Authorize this exact repair scope").waitFor();
  await s.scrollTo(p.getByText("Authorize this exact repair scope").first(), 120, 1300); await p.waitForTimeout(2200);
  const auth = p.getByRole("button", { name: /Authorize and start scripted recovery/ });
  await s.act(auth, "Press & hold: Authorize the exact scope", { holdMs: 2200, showMs: 700 }); s.mark("authorize");
  await p.getByText(/Imported recovery result/).waitFor({ timeout: 90000 });
  // The result panel appears while the run is still working; wait for the finished outcome.
  await p.waitForFunction(() => { const m = document.querySelector("main"); const t = m ? m.innerText : "";
    const i = t.indexOf("Imported recovery result"); const r = t.slice(i, i + 600);
    return i >= 0 && !/Agent working|is running/.test(r) && /[1-9] recorded commit/.test(r); }, null, { timeout: 120000 });
  await p.waitForTimeout(800);
  await s.scrollTo(p.getByText(/Imported recovery result/).first(), 110, 1400); s.mark("result"); await p.waitForTimeout(3000);
  const dl = p.getByText(/Download signed recovery evidence/).first();
  if (await dl.count()) { await s.spot(dl, "Signed evidence for every run", 2600); s.mark("evidence"); }
  const txt = await p.innerText("main"); console.log("import result:", (txt.match(/Imported recovery result[\s\S]{0,300}/) || [""])[0].replace(/\n/g, " | "));
  s.mark("end"); await p.waitForTimeout(600);
  await s.finish(true);
}


async function judgesTake(n) {
  const s = await session("judges"), p = s.page;
  await p.goto(BASE); await p.mouse.move(960, 600);
  await p.getByText("Ctrl+Z for").waitFor(); s.mark("home");
  await p.waitForTimeout(2600);
  await s.act(p.getByRole("button", { name: /Start the demo|Start over with fresh data/ }), "Click: Start the demo");
  await p.getByText("A bad change just wrecked this store's orders.").waitFor({ timeout: 30000 });
  await p.waitForTimeout(900); s.mark("s1");
  await s.scrollTo(p.getByText("Damaged by the incident").first(), 160, 1300);
  await s.spot(p.getByText("Damaged by the incident").locator("xpath=ancestor::section[1]"), "", 2600);
  await s.spot(p.getByText("Decided after the backup (must stay)").locator("xpath=ancestor::section[1]"), "", 2800);
  await s.act(p.getByRole("button", { name: "Undo the damage" }), "Click: Undo the damage");
  await p.getByText("Two ways to undo it.").waitFor(); await p.waitForTimeout(700); s.mark("s2");
  await s.scrollTo(p.getByText("Option A: restore the backup").first(), 150, 1300);
  await s.spot(p.getByText("Option A: restore the backup").locator("xpath=ancestor::section[1]"), "", 3200);
  s.mark("runClick");
  await s.act(p.getByRole("button", { name: "Run the AI repair" }), "Click: Run the AI repair (live model)");
  await p.getByText("Option B: VeerIQ").waitFor({ timeout: 30000 }); s.mark("runStart");
  await p.mouse.move(1880, 1040);
  const deadline = Date.now() + 240000; let blocked = false, status = "";
  while (Date.now() < deadline) {
    if (!blocked && (await p.getByText("The agent took the bait. ArmorIQ stopped it.").count())) { blocked = true; s.mark("blockSeen"); }
    status = (await p.getByText(/^(succeeded|failed|blocked|partially succeeded|cancelled)$/i).count()) ? "done" : "";
    if (status) break;
    await p.waitForTimeout(1000);
  }
  s.mark("runEnd");
  const ok = blocked && (await p.getByText(/^succeeded$/i).count()) > 0;
  console.log(`judges take ${n}: blocked=${blocked} ok=${ok}`);
  if (!ok) { await s.finish(false); return false; }
  await p.waitForTimeout(1200);
  await s.scrollTo(p.getByText("Option B: VeerIQ").first(), 150, 1200);
  await s.spot(p.getByText("The agent took the bait. ArmorIQ stopped it.").locator(".."), "", 2600); s.mark("blockSpot");
  await s.spot(p.getByText("Option B: VeerIQ").locator("xpath=ancestor::section[1]"), "", 3000); s.mark("kept");
  await s.act(p.getByRole("button", { name: "Next: the $12,400 repair" }), "Click: Next");
  await p.getByText("One repair is $12,400. You are the second key.").waitFor(); await p.waitForTimeout(800); s.mark("s3");
  await s.act(p.getByRole("button", { name: "Ask for the $12,400 repair" }), "Click: Ask for the $12,400 repair"); s.mark("reviewClick");
  await p.getByRole("button", { name: "Become the approver" }).waitFor({ timeout: 60000 }); s.mark("awaiting");
  await p.waitForTimeout(800);
  await s.spot(p.getByText("The $12,400 repair").locator("xpath=ancestor::section[1]"), "", 2600);
  await s.act(p.getByRole("button", { name: "Become the approver" }), "Click: Become the approver"); s.mark("approver");
  await p.getByRole("button", { name: "Approve this exact change" }).waitFor();
  await s.act(p.getByRole("button", { name: "Approve this exact change" }), "Click: Approve this exact change"); s.mark("approve");
  await p.getByText("Approved and committed, in one locked transaction.").waitFor({ timeout: 60000 }); s.mark("committed");
  await p.waitForTimeout(2400);
  await s.act(p.getByRole("button", { name: "Check our work", exact: true }), "Click: Check our work");
  await p.getByText("Don't trust our screen. Check it.").waitFor(); await p.waitForTimeout(700); s.mark("s4");
  await s.act(p.getByRole("button", { name: "Verify in my browser" }), "Click: Verify in my browser"); s.mark("verifyClick");
  await p.getByText(/events chained in order/).first().waitFor({ timeout: 30000 }); s.mark("verified");
  await p.waitForTimeout(2200);
  await s.act(p.getByRole("button", { name: "Change one number and check again" }), "Click: change one cent"); s.mark("tamperClick");
  await p.getByText("rejected").first().waitFor(); s.mark("tampered");
  await p.waitForTimeout(3200);
  await s.scrollTo(p.getByText("Not just once: 84 live runs").first(), 150, 1300); s.mark("score");
  await p.waitForTimeout(3000);
  await s.scrollTo(p.getByText("Plug it into your own agent (MCP)").first(), 150, 1300);
  await s.act(p.getByRole("button", { name: "Authorize a task and get my install command" }), "Click: get my install command"); s.mark("installClick");
  await p.getByText("Add to Cursor").waitFor({ timeout: 30000 }); await p.waitForTimeout(3000); s.mark("install");
  s.mark("end"); await p.waitForTimeout(600);
  await s.finish(true); return true;
}

if (TAKE === "judges") { for (let n = 1; n <= 6; n++) if (await judgesTake(n)) process.exit(0); console.error("no judges take with an ArmorIQ block"); process.exit(1); }
if (TAKE === "live") { for (let n = 1; n <= 3; n++) if (await liveTake(n)) process.exit(0); console.error("no live take with an ArmorIQ block"); process.exit(1); }
else await importTake();
