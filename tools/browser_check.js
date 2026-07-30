#!/usr/bin/env node
/*
 * Measure the published page in a real browser.
 *
 * This project has a specific reason to need one. A browser is the authority on how wide a
 * string is; everything else is a prediction of what it will do. So every text element in
 * every SVG on the page is re-measured with getComputedTextLength() and compared against the
 * container the solver assigned, and the numbers go on the page.
 *
 * Care taken, and why:
 *
 *   own browser        the shared Playwright instance is used by other agents, which can
 *                      navigate it away mid-check and leave the measurements describing
 *                      someone else's page. This drives its own Chromium through
 *                      playwright-core and asserts document.title inside every evaluation.
 *   port 0             a stale server on a fixed port serves another project's page and
 *                      returns a cheerful 200. The server here binds to port 0 and the check
 *                      asserts on served content, not on a status code.
 *   own measurement    the page ships its own inline checker. This script does not trust it:
 *                      it walks the DOM itself and then compares its numbers with the page's,
 *                      so a bug in either shows up as a disagreement.
 *   no overflow hedge  the horizontal-overflow probe walks elements and compares
 *                      getBoundingClientRect().right against clientWidth, skipping anything
 *                      inside a scroll container, because content scrolling inside its own box
 *                      is correct and only content escaping the page is not.
 */

"use strict";

const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const DOCS = path.join(ROOT, "docs");
const PW = path.join(ROOT, "..", "a11y-sweep", "node_modules", "playwright-core");
const TITLE = "svg-infographic: a layout engine that measures its own text";
const MARKER = "data-engine=\"svg-infographic\"";

const TYPES = { ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml", ".css": "text/css", ".js": "text/javascript" };

const failures = [];
function check(ok, label, detail) {
  if (!ok) failures.push(detail ? `${label}: ${detail}` : label);
  console.log(`${ok ? "  ok  " : "  FAIL"} ${label}${detail && !ok ? " -> " + detail : ""}`);
  return ok;
}
function n(v, d) { return Number.isFinite(v) ? v.toFixed(d) : String(v); }

function serve() {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const rel = decodeURIComponent(req.url.split("?")[0]);
      const file = path.join(DOCS, rel === "/" ? "index.html" : rel);
      if (!file.startsWith(DOCS)) { res.writeHead(403).end(); return; }
      fs.readFile(file, (err, buf) => {
        if (err) { res.writeHead(404).end("not found"); return; }
        res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
        res.end(buf);
      });
    });
    server.on("error", reject);
    // Port 0 asks the kernel for a port nothing else holds.
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

function fetchText(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let body = "";
      res.on("data", (c) => (body += c));
      res.on("end", () => resolve({ status: res.statusCode, body }));
    }).on("error", reject);
  });
}

// Runs inside the page. Returns its own measurement of every text element.
const PROBE = function (expectedTitle) {
  if (document.title !== expectedTitle) return { error: "wrong page: " + document.title };
  const out = {
    title: document.title,
    svgs: 0, elements: 0, boxes: 0, overflows: [], worst: Infinity, worstWhere: "",
    worstH: Infinity, worstHWhere: "", worstV: Infinity, worstVWhere: "",
    worstDelta: 0, worstDeltaWhere: "", pairs: 0, collisions: [], minSep: Infinity, minSepWhere: "",
    fontLoaded: document.fonts ? document.fonts.check('16px "DejaVu Sans"') : null,
    emptyRuns: 0,
    // getBBox() is derived entirely by the renderer, with no input from the engine's own
    // ascent, descent or width attributes, so it is the one measurement here that could
    // contradict every number the engine wrote.
    bboxOverflows: [], bboxWorst: Infinity, bboxWorstWhere: "",
    bboxPairs: 0, bboxCollisions: [], bboxMinSep: Infinity, bboxMinSepWhere: ""
  };
  const TOL = 0.05;
  const svgs = document.querySelectorAll('svg[data-engine="svg-infographic"]');
  out.svgs = svgs.length;
  for (const svg of svgs) {
    const runs = [];
    const bboxRuns = [];
    const boxes = svg.querySelectorAll("rect[data-content]");
    out.boxes += boxes.length;
    for (const t of svg.querySelectorAll("text")) {
      const content = t.textContent;
      const boxId = t.getAttribute("data-box");
      const box = svg.querySelector("#box-" + CSS.escape(boxId));
      if (!box) { out.overflows.push({ id: t.id, side: "missing-box", amount: Infinity }); continue; }
      out.elements++;
      const len = t.getComputedTextLength();
      const claimed = parseFloat(t.getAttribute("data-measured"));
      if (content.trim() === "") { out.emptyRuns++; }
      else {
        const d = Math.abs(len - claimed);
        if (d > out.worstDelta) {
          out.worstDelta = d;
          out.worstDeltaWhere = svg.dataset.specId + "/" + t.id + " " + JSON.stringify(content.slice(0, 30));
        }
      }
      const anchor = t.getAttribute("text-anchor") || "start";
      const x = parseFloat(t.getAttribute("x"));
      const x0 = anchor === "start" ? x : anchor === "end" ? x - len : x - len / 2;
      const x1 = x0 + len;
      const asc = parseFloat(t.getAttribute("data-ascent"));
      const desc = parseFloat(t.getAttribute("data-descent"));
      const base = parseFloat(t.getAttribute("y"));
      const y0 = base - asc, y1 = base + desc;
      const c = box.getAttribute("data-content").trim().split(/\s+/).map(Number);
      const fit = t.getAttribute("data-fit").trim().split(/\s+/).map(Number);
      const left = Math.max(c[0], fit[0]), right = Math.min(c[0] + c[2], fit[1]);
      const top = c[1], bottom = c[1] + c[3];
      const sides = { left: x0 - left, right: right - x1, top: y0 - top, bottom: bottom - y1 };
      for (const [side, m] of Object.entries(sides)) {
        if (m < -TOL) {
          out.overflows.push({
            spec: svg.dataset.specId, id: t.id, side, amount: -m,
            content: content.slice(0, 40), role: t.getAttribute("data-role")
          });
        }
        if (m < out.worst) {
          out.worst = m;
          out.worstWhere = svg.dataset.specId + "/" + t.id + " " + side + " " + JSON.stringify(content.slice(0, 24));
        }
        const bucket = side === "left" || side === "right" ? "H" : "V";
        if (m < out["worst" + bucket]) {
          out["worst" + bucket] = m;
          out["worst" + bucket + "Where"] =
            svg.dataset.specId + "/" + t.id + " " + side + " " + JSON.stringify(content.slice(0, 24));
        }
      }

      // Second, independent pass: the renderer's own bounding box.
      if (content.trim() !== "") {
        let bb = null;
        try { bb = t.getBBox(); } catch (e) { bb = null; }
        if (bb && bb.width > 0) {
          // The container the ink is allowed to occupy: the assigned column, widened by the
          // run's own declared side-bearing overhang and by one pixel for the renderer's
          // outward quantization of the box it reports. Both allowances are stated, not
          // guessed: the overhang comes off the element as data-ink and was verified against
          // fontTools at build time, and the one pixel is what Chromium was measured doing.
          const ink = (t.getAttribute("data-ink") || "0 0").trim().split(/\s+/).map(Number);
          const BBOX_ROUND = 1.0;
          const bl = left - ink[0] - BBOX_ROUND;
          const br = right + ink[1] + BBOX_ROUND;
          const bsides = {
            left: bb.x - bl, right: br - (bb.x + bb.width),
            top: bb.y - top, bottom: bottom - (bb.y + bb.height)
          };
          for (const [side, m] of Object.entries(bsides)) {
            if (m < -TOL) {
              out.bboxOverflows.push({
                spec: svg.dataset.specId, id: t.id, side, amount: -m,
                content: content.slice(0, 40), role: t.getAttribute("data-role")
              });
            }
            if (m < out.bboxWorst) {
              out.bboxWorst = m;
              out.bboxWorstWhere =
                svg.dataset.specId + "/" + t.id + " " + side + " " + JSON.stringify(content.slice(0, 24));
            }
          }
          bboxRuns.push({ id: t.id, x0: bb.x, x1: bb.x + bb.width, y0: bb.y, y1: bb.y + bb.height, spec: svg.dataset.specId });
        }
      }
      if (content.trim() !== "" && len > 0) runs.push({ id: t.id, x0, x1, y0, y1, spec: svg.dataset.specId });
    }
    for (let a = 0; a < runs.length; a++) {
      for (let b = a + 1; b < runs.length; b++) {
        const p = runs[a], q = runs[b];
        const dx = Math.max(p.x0 - q.x1, q.x0 - p.x1);
        const dy = Math.max(p.y0 - q.y1, q.y0 - p.y1);
        const sep = Math.max(dx, dy);
        out.pairs++;
        if (sep <= 0) out.collisions.push({ spec: p.spec, a: p.id, b: q.id, sep });
        if (sep < out.minSep) { out.minSep = sep; out.minSepWhere = p.spec + " " + p.id + " vs " + q.id; }
      }
    }
    for (let a = 0; a < bboxRuns.length; a++) {
      for (let b = a + 1; b < bboxRuns.length; b++) {
        const p = bboxRuns[a], q = bboxRuns[b];
        const dx = Math.max(p.x0 - q.x1, q.x0 - p.x1);
        const dy = Math.max(p.y0 - q.y1, q.y0 - p.y1);
        const sep = Math.max(dx, dy);
        out.bboxPairs++;
        if (sep <= 0) out.bboxCollisions.push({ spec: p.spec, a: p.id, b: q.id, sep });
        if (sep < out.bboxMinSep) { out.bboxMinSep = sep; out.bboxMinSepWhere = p.spec + " " + p.id + " vs " + q.id; }
      }
    }
  }
  if (document.title !== expectedTitle) return { error: "page changed during measurement" };
  return out;
};

const OVERFLOW_PROBE = function (expectedTitle) {
  if (document.title !== expectedTitle) return { error: "wrong page" };
  const scrollable = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === "auto" || ox === "scroll") return true;
    }
    return false;
  };
  const limit = document.documentElement.clientWidth;
  const bad = [];
  for (const el of document.querySelectorAll("body *")) {
    if (scrollable(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (r.right > limit + 0.5 || r.left < -0.5) {
      bad.push({ tag: el.tagName.toLowerCase(), cls: el.className && String(el.className).slice(0, 40), right: r.right, left: r.left });
    }
  }
  return {
    clientWidth: limit,
    scrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    offenders: bad.slice(0, 12),
    count: bad.length
  };
};

const THEME_PROBE = function (expectedTitle) {
  if (document.title !== expectedTitle) return { error: "wrong page" };
  const read = () => {
    const cs = getComputedStyle(document.documentElement);
    return {
      bg: cs.getPropertyValue("--bg").trim(),
      igbg: cs.getPropertyValue("--ig-bg").trim(),
      body: getComputedStyle(document.body).backgroundColor
    };
  };
  const results = { system: read() };
  document.documentElement.setAttribute("data-theme", "light");
  results.forcedLight = read();
  document.documentElement.setAttribute("data-theme", "dark");
  results.forcedDark = read();
  document.documentElement.removeAttribute("data-theme");
  results.after = read();
  return results;
};

(async () => {
  if (!fs.existsSync(path.join(DOCS, "index.html"))) {
    console.error("docs/index.html is missing. Run tools/build_docs.py first.");
    process.exit(2);
  }
  const { chromium } = require(PW);
  const server = await serve();
  const port = server.address().port;
  const base = `http://127.0.0.1:${port}/`;
  console.log(`serving ${path.relative(ROOT, DOCS)} on port ${port} (kernel-assigned)`);

  // Assert on the served bytes, not on a status code. A stale server on a fixed port answers
  // 200 with someone else's page.
  const served = await fetchText(base);
  check(served.status === 200, "server answers", `status ${served.status}`);
  check(served.body.includes(MARKER), "served bytes contain a generated SVG from this engine");
  check(served.body.includes("<title>" + TITLE + "</title>"), "served bytes carry the expected title");
  check(!/https?:\/\/(?!127\.0\.0\.1|www\.w3\.org)/.test(served.body.replace(/xmlns[^"]*"[^"]*"/g, "")),
    "served page references no remote host");

  const browser = await chromium.launch({ headless: true });
  const requests = [];
  let result = null, overflow = null, themes = null, pageNumbers = null, consoleErrors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    page.on("request", (r) => requests.push(r.url()));
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

    // Navigate and measure as one step. Between them another agent's browser could move.
    await page.goto(base, { waitUntil: "load" });
    await page.waitForFunction(() => window.__igBrowserCheck !== undefined, { timeout: 20000 });

    result = await page.evaluate(PROBE, TITLE);
    pageNumbers = await page.evaluate((t) => {
      if (document.title !== t) return { error: "wrong page" };
      return window.__igBrowserCheck;
    }, TITLE);
    themes = await page.evaluate(THEME_PROBE, TITLE);

    check(!result.error, "measurement ran on the right page", result.error);
    check(consoleErrors.length === 0, "no script errors on the page", consoleErrors.slice(0, 3).join(" | "));
    check(result.fontLoaded === true, "the embedded DejaVu Sans subset actually loaded",
      `document.fonts.check returned ${result.fontLoaded}`);
    check(result.svgs >= 35, "all generated SVGs are inline in the page", `found ${result.svgs}`);
    check(result.elements > 300, "text elements measured", `found ${result.elements}`);
    check(result.overflows.length === 0, "CLAIM 1: no text overflows its container in the browser",
      JSON.stringify(result.overflows.slice(0, 4)));
    check(result.collisions.length === 0, "CLAIM 2: no two labels intersect in the browser",
      JSON.stringify(result.collisions.slice(0, 4)));
    check(result.worstDelta < 0.05,
      "engine font arithmetic matches the browser's own text engine",
      `worst disagreement ${n(result.worstDelta, 4)}px at ${result.worstDeltaWhere}`);
    check(result.minSep > 0, "minimum label separation is positive", `${n(result.minSep, 4)}px`);
    check(result.bboxOverflows.length === 0,
      "CLAIM 1 by getBBox(), the renderer's own ink box, inside the container plus declared overhang",
      JSON.stringify(result.bboxOverflows.slice(0, 4)));
    check(result.bboxCollisions.length === 0,
      "CLAIM 2 by getBBox(), the renderer's own ink boxes never intersect",
      JSON.stringify(result.bboxCollisions.slice(0, 4)));
    check(result.bboxPairs > 3000, "enough bbox pairs compared", `${result.bboxPairs}`);

    // The page's inline checker must agree with this script's independent walk.
    if (pageNumbers && !pageNumbers.error) {
      check(pageNumbers.elements === result.elements,
        "the page's own checker counted the same elements",
        `page ${pageNumbers.elements} vs script ${result.elements}`);
      check(pageNumbers.overflows === result.overflows.length,
        "the page's own checker agrees on the overflow count",
        `page ${pageNumbers.overflows} vs script ${result.overflows.length}`);
      check(Math.abs(pageNumbers.minSep - result.minSep) < 0.001,
        "the page's own checker agrees on minimum separation",
        `page ${n(pageNumbers.minSep, 4)} vs script ${n(result.minSep, 4)}`);
    } else {
      check(false, "the page's own checker produced numbers", JSON.stringify(pageNumbers));
    }

    // Theme, both directions.
    check(themes.forcedLight.bg !== themes.forcedDark.bg,
      "data-theme light and dark give different palettes",
      `${themes.forcedLight.bg} vs ${themes.forcedDark.bg}`);
    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      const t = await page.evaluate(THEME_PROBE, TITLE);
      check(!t.error, `theme probe ran under prefers-color-scheme: ${scheme}`, t.error);
      check(t.system.bg !== "", `--bg resolves under prefers-color-scheme: ${scheme}`);
      check(t.forcedLight.bg !== t.forcedDark.bg,
        `data-theme still overrides under prefers-color-scheme: ${scheme}`,
        `${t.forcedLight.bg} vs ${t.forcedDark.bg}`);
      // The override has to work against the media query, not only with it.
      const opposite = scheme === "dark" ? "forcedLight" : "forcedDark";
      check(t[opposite].bg !== t.system.bg,
        `data-theme=${opposite === "forcedLight" ? "light" : "dark"} overrides prefers-color-scheme: ${scheme}`,
        `${t[opposite].bg} vs system ${t.system.bg}`);
    }
    await page.emulateMedia({ colorScheme: null });

    // Narrow viewport. Wide graphics must scroll inside their own container, never the body.
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 780 });
      await page.waitForTimeout(120);
      overflow = await page.evaluate(OVERFLOW_PROBE, TITLE);
      check(!overflow.error, `overflow probe ran at ${width}px`, overflow.error);
      check(overflow.count === 0, `no element escapes the page at ${width}px`,
        JSON.stringify(overflow.offenders));
      check(overflow.scrollWidth <= overflow.clientWidth + 0.5,
        `documentElement does not scroll sideways at ${width}px`,
        `scrollWidth ${overflow.scrollWidth} vs clientWidth ${overflow.clientWidth}`);
      const hidden = await page.evaluate((t) => {
        if (document.title !== t) return "wrong page";
        return getComputedStyle(document.body).overflowX;
      }, TITLE);
      check(hidden !== "hidden", `body overflow-x is not hidden at ${width}px`, `got ${hidden}`);
    }

    // The graphics must still be measurable at a narrow viewport, which is where a
    // max-width rule would have quietly rescaled them.
    await page.setViewportSize({ width: 390, height: 780 });
    const narrow = await page.evaluate(PROBE, TITLE);
    check(!narrow.error, "measurement ran at 390px", narrow.error);
    check(narrow.overflows.length === 0, "CLAIM 1 still holds at a 390px viewport",
      JSON.stringify(narrow.overflows.slice(0, 3)));
    check(Math.abs(narrow.worst - result.worst) < 0.001,
      "viewport width does not change the measured clearance",
      `${n(narrow.worst, 4)} at 390px vs ${n(result.worst, 4)} at 1280px`);

    const remote = requests.filter((u) => !u.startsWith(base) && !u.startsWith("data:"));
    check(remote.length === 0, "the page made no remote requests", remote.slice(0, 4).join(", "));
  } finally {
    await browser.close();
    server.close();
  }

  const summary = {
    svgs: result && result.svgs,
    text_elements: result && result.elements,
    containers: result && result.boxes,
    empty_runs: result && result.emptyRuns,
    browser_overflows: result && result.overflows.length,
    browser_worst_clearance_px: result && Number(n(result.worst, 4)),
    browser_worst_clearance_where: result && result.worstWhere,
    browser_worst_horizontal_clearance_px: result && Number(n(result.worstH, 4)),
    browser_worst_horizontal_clearance_where: result && result.worstHWhere,
    browser_worst_vertical_clearance_px: result && Number(n(result.worstV, 4)),
    bbox_overflows: result && result.bboxOverflows.length,
    bbox_worst_clearance_px: result && Number(n(result.bboxWorst, 4)),
    bbox_worst_clearance_where: result && result.bboxWorstWhere,
    bbox_pairs: result && result.bboxPairs,
    bbox_collisions: result && result.bboxCollisions.length,
    bbox_min_separation_px: result && Number(n(result.bboxMinSep, 4)),
    engine_vs_browser_worst_delta_px: result && Number(n(result.worstDelta, 6)),
    engine_vs_browser_worst_delta_where: result && result.worstDeltaWhere,
    label_pairs: result && result.pairs,
    browser_collisions: result && result.collisions.length,
    browser_min_separation_px: result && Number(n(result.minSep, 4)),
    browser_min_separation_where: result && result.minSepWhere,
    failures: failures.length
  };
  console.log("\n--- browser measurement ---");
  console.log(JSON.stringify(summary, null, 2));
  if (failures.length) {
    console.error(`\n${failures.length} browser check(s) failed:`);
    failures.forEach((f) => console.error("  " + f));
    process.exit(1);
  }
  console.log("\nall browser checks passed");
})().catch((err) => {
  console.error("browser check crashed:", err && err.stack ? err.stack : err);
  process.exit(3);
});
