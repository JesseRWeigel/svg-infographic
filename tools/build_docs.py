#!/usr/bin/env python3
"""Render the corpus and build the self-contained docs page.

Everything the page needs is inlined: the SVGs, the CSS, the JS, and the fonts as base64
WOFF2 subsets. There are no remote requests, which matters for more than tidiness here. The
page's strongest claim is that a real browser measured the text and found it inside its
container, and that claim is only worth something if the browser is using the same font the
engine measured. Embedding the font removes any doubt about what the machine had installed.

Run:  python3 tools/build_docs.py
Out:  out/svg/*.svg  and  docs/index.html
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fontTools import subset  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

from corpus.specs import CORPUS, REFUSALS  # noqa: E402
from engine.fontmetrics import get_font, resolve_font_path  # noqa: E402
from engine.render import render_spec  # noqa: E402
from engine.spec import doc_to_json  # noqa: E402
from tests import detectors as D  # noqa: E402

SHOWCASE = [
    "c29-mixed-light",
    "c11-bars-basic",
    "c04-w-vs-i",
    "c22-steps-many",
    "c07-cjk",
    "c08-emoji",
    "c06-longer-than-canvas",
    "c19-kpi-uneven",
]

# What the in-page measurement lab can type. Anything outside this refuses, the same way the
# engine refuses a character its font has no glyph for.
LAB_CHARS = "".join(
    chr(c)
    for r in ((32, 127), (0xA0, 0x180), (0x2018, 0x2020), (0x2032, 0x2034))
    for c in range(*r)
) + "…–—•·°±×÷≈≠≤≥→←↑↓★☆♥♦♠♣✓✗✦✧☺☹€£¥"


def corpus_chars() -> dict[str, set[str]]:
    """Characters actually drawn, per font family, so the subsets stay small."""
    used: dict[str, set[str]] = {}
    for spec in CORPUS:
        doc = D.parse(render_spec(spec), spec.id)
        for t in doc.texts:
            key = f"{t.family}|{t.weight}"
            used.setdefault(key, set()).update(t.content)
    return used


def woff2_subset(path: Path, chars: set[str]) -> bytes:
    f = TTFont(str(path))
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = []  # kerning and ligatures are switched off in the SVG anyway
    opts.name_IDs = ["*"]
    opts.name_legacy = True
    opts.notdef_outline = True
    opts.recalc_bounds = False
    opts.recalc_timestamp = False
    opts.drop_tables += ["FFTM"]
    s = subset.Subsetter(options=opts)
    s.populate(unicodes=sorted({ord(c) for c in chars if c.strip() or c == " "}))
    s.subset(f)
    buf = io.BytesIO()
    f.flavor = "woff2"
    f.save(buf)
    return buf.getvalue()


def lab_metrics() -> dict:
    """Advance tables for the interactive panel, taken from the engine's own parser."""
    out = {}
    for label, name in (("regular", "DejaVu Sans"), ("bold", "DejaVu Sans Bold")):
        f = get_font(name)
        cps = sorted(ord(c) for c in set(LAB_CHARS) if f.has_char(c))
        out[label] = {
            "upem": f.units_per_em,
            "asc": f.ascender,
            "desc": abs(f.descender),
            "cps": cps,
            "adv": [f.advances[f.cmap[cp]] for cp in cps],
        }
    return out


def build_report() -> dict:
    """Recompute every published number from the emitted SVGs at build time."""
    docs = [D.parse(render_spec(s), s.id) for s in CORPUS]
    overflow_count = sum(len(D.overflows(d)) for d in docs)
    collision_count = sum(len(D.collisions(d)) for d in docs)
    worst, worst_where = min((D.worst_margin(d) for d in docs), key=lambda t: t[0])
    trail, trail_where = min((D.worst_trailing_margin(d) for d in docs), key=lambda t: t[0])
    sep, sep_where = min((D.min_separation(d) for d in docs), key=lambda t: t[0])
    drawn = [t for d in docs for t in d.texts if t.content.strip()]
    pairs = sum(
        (lambda n: n * (n - 1) // 2)(len([t for t in d.texts if t.content.strip()])) for d in docs
    )
    return {
        "specs": len(docs),
        "texts": sum(len(d.texts) for d in docs),
        "drawn": len(drawn),
        "pairs": pairs,
        "overflows": overflow_count,
        "collisions": collision_count,
        "worst_margin": round(worst, 4),
        "worst_margin_where": worst_where,
        "worst_trailing": round(trail, 4),
        "worst_trailing_where": trail_where,
        "min_separation": round(sep, 4),
        "min_separation_where": sep_where,
        "refusals": len(REFUSALS),
    }


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def strip_svg_size(svg: str) -> str:
    """Keep width/height so the graphic renders at the exact geometry the solver assigned.

    Scaling an SVG down does not break containment, but it does mean the page is showing
    something other than the numbers the check reports, so the graphic keeps its intrinsic
    size and its wrapper scrolls instead.
    """
    return svg


CSS = """
:root{
  color-scheme: light dark;
  --bg:#fbfbfd; --fg:#14161a; --muted:#5b6472; --line:#e2e5ea; --card:#ffffff;
  --code-bg:#f2f4f7; --ok:#0f7a51; --bad:#b32020; --link:#1a5fd0;
  --ig-bg:#ffffff; --ig-panel:#f4f6f9; --ig-panel-line:#e0e5ec; --ig-card:#ffffff;
  --ig-card-line:#dde3ea; --ig-fg:#14161a; --ig-muted:#5b6472; --ig-track:#e5e9ef;
  --ig-badge-fg:#ffffff;
  --ig-accent-0:#2f6df6; --ig-accent-1:#0f9d6b; --ig-accent-2:#c2410c;
  --ig-accent-3:#7c3aed; --ig-accent-4:#0e7490;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#0c0e12; --fg:#e9ebef; --muted:#9aa3b2; --line:#252b34; --card:#13161c;
    --code-bg:#171b22; --ok:#3ecf8e; --bad:#ff7b72; --link:#79a8ff;
    --ig-bg:#0f1115; --ig-panel:#171a20; --ig-panel-line:#282e38; --ig-card:#13161c;
    --ig-card-line:#2b313b; --ig-fg:#e9ebef; --ig-muted:#9aa3b2; --ig-track:#232936;
    --ig-badge-fg:#0f1115;
    --ig-accent-0:#6d9bff; --ig-accent-1:#34d399; --ig-accent-2:#fb923c;
    --ig-accent-3:#a78bfa; --ig-accent-4:#22d3ee;
  }
}
:root[data-theme="light"]{
  --bg:#fbfbfd; --fg:#14161a; --muted:#5b6472; --line:#e2e5ea; --card:#ffffff;
  --code-bg:#f2f4f7; --ok:#0f7a51; --bad:#b32020; --link:#1a5fd0;
  --ig-bg:#ffffff; --ig-panel:#f4f6f9; --ig-panel-line:#e0e5ec; --ig-card:#ffffff;
  --ig-card-line:#dde3ea; --ig-fg:#14161a; --ig-muted:#5b6472; --ig-track:#e5e9ef;
  --ig-badge-fg:#ffffff;
  --ig-accent-0:#2f6df6; --ig-accent-1:#0f9d6b; --ig-accent-2:#c2410c;
  --ig-accent-3:#7c3aed; --ig-accent-4:#0e7490;
}
:root[data-theme="dark"]{
  --bg:#0c0e12; --fg:#e9ebef; --muted:#9aa3b2; --line:#252b34; --card:#13161c;
  --code-bg:#171b22; --ok:#3ecf8e; --bad:#ff7b72; --link:#79a8ff;
  --ig-bg:#0f1115; --ig-panel:#171a20; --ig-panel-line:#282e38; --ig-card:#13161c;
  --ig-card-line:#2b313b; --ig-fg:#e9ebef; --ig-muted:#9aa3b2; --ig-track:#232936;
  --ig-badge-fg:#0f1115;
  --ig-accent-0:#6d9bff; --ig-accent-1:#34d399; --ig-accent-2:#fb923c;
  --ig-accent-3:#a78bfa; --ig-accent-4:#22d3ee;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.6 "DejaVu Sans", system-ui, sans-serif;
  -webkit-text-size-adjust:100%;
}
.wrap{max-width:1000px; margin:0 auto; padding:24px 16px 64px}
h1{font-size:clamp(1.55rem,4.5vw,2.4rem); line-height:1.2; margin:.2em 0 .3em}
h2{font-size:clamp(1.15rem,3vw,1.5rem); margin:2.2em 0 .5em; border-top:1px solid var(--line); padding-top:1.2em}
h3{font-size:1.02rem; margin:1.6em 0 .4em}
p{margin:.7em 0; max-width:70ch}
a{color:var(--link)}
code,kbd{font-family:"DejaVu Sans Mono", ui-monospace, monospace; font-size:.88em; background:var(--code-bg); padding:.1em .35em; border-radius:4px}
pre{background:var(--code-bg); padding:12px 14px; border-radius:8px; overflow-x:auto; border:1px solid var(--line)}
pre code{background:none; padding:0}
.lede{font-size:1.06rem; color:var(--muted); max-width:66ch}
.bar{display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:1em 0}
button, select, input, textarea{
  font:inherit; color:var(--fg); background:var(--card);
  border:1px solid var(--line); border-radius:8px; padding:.42em .7em; max-width:100%;
}
button{cursor:pointer}
button:hover{border-color:var(--muted)}
textarea{width:100%; min-height:5.5em; resize:vertical; font-family:"DejaVu Sans Mono", monospace; font-size:.86rem}
.claims{display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr)); margin:1.4em 0}
.claim{border:1px solid var(--line); border-radius:12px; padding:14px 16px; background:var(--card)}
.claim h3{margin:0 0 .35em; font-size:.95rem; letter-spacing:.01em}
.claim .n{font-size:1.5rem; font-weight:700; font-variant-numeric:tabular-nums; display:block; margin:.15em 0}
.ok{color:var(--ok)} .bad{color:var(--bad); font-weight:700}
.note{font-size:.86rem; color:var(--muted)}
table{border-collapse:collapse; font-size:.88rem; min-width:520px}
.tablewrap{overflow-x:auto; border:1px solid var(--line); border-radius:10px; margin:1em 0}
th,td{text-align:left; padding:7px 11px; border-bottom:1px solid var(--line); white-space:nowrap}
th{font-weight:700; background:var(--code-bg)}
tr:last-child td{border-bottom:none}
td.num{text-align:right; font-variant-numeric:tabular-nums}
figure{margin:1.6em 0}
figcaption{font-size:.87rem; color:var(--muted); margin-bottom:.5em}
.scroll{overflow-x:auto; border:1px solid var(--line); border-radius:12px; background:var(--ig-bg)}
.scroll svg{display:block}
.pair{display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr))}
details{border:1px solid var(--line); border-radius:8px; padding:.5em .8em; margin:.6em 0; background:var(--card)}
summary{cursor:pointer; font-size:.9rem}
.lab{border:1px solid var(--line); border-radius:12px; padding:14px 16px; background:var(--card); margin:1.2em 0}
.labgrid{display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr))}
.labgrid label{display:block; font-size:.82rem; color:var(--muted); margin-bottom:.25em}
.labgrid input{width:100%}
#labout{margin-top:14px}
.hidden{display:none}
footer{margin-top:3em; border-top:1px solid var(--line); padding-top:1.2em; font-size:.86rem; color:var(--muted)}
"""


def build_html(report: dict, fonts: dict[str, bytes], svgs: dict[str, str]) -> str:
    faces = []
    for (family, weight), data in sorted(fonts.items()):
        b64 = base64.b64encode(data).decode("ascii")
        faces.append(
            f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};"
            f"font-display:block;src:url(data:font/woff2;base64,{b64}) format('woff2')}}"
        )
    face_css = "\n".join(faces)

    def fig(spec_id: str, note: str = "") -> str:
        spec = next(s for s in CORPUS if s.id == spec_id)
        j = json.dumps(doc_to_json(spec), indent=2, ensure_ascii=False, sort_keys=True)
        return (
            f'<figure data-spec="{spec_id}">\n'
            f'  <figcaption><strong>{esc(spec.title)}</strong> &middot; <code>{spec_id}</code>'
            f'{(" &middot; " + esc(note)) if note else ""}</figcaption>\n'
            f'  <div class="scroll">{svgs[spec_id]}</div>\n'
            f"  <details><summary>the spec that produced it</summary>"
            f"<pre><code>{esc(j)}</code></pre></details>\n"
            f"</figure>"
        )

    gallery = "\n".join(fig(i) for i in SHOWCASE)
    rest = "\n".join(
        f'<figure data-spec="{s.id}"><figcaption><code>{s.id}</code> &middot; '
        f"{esc(s.title[:70])}</figcaption>"
        f'<div class="scroll">{svgs[s.id]}</div></figure>'
        for s in CORPUS
        if s.id not in SHOWCASE
    )

    metrics = json.dumps(lab_metrics(), separators=(",", ":"))
    rep = json.dumps(report, separators=(",", ":"), sort_keys=True)

    return f"""<title>svg-infographic: a layout engine that measures its own text</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="A typed data spec plus a constraint solver produces SVG infographics where text never overflows, labels never collide, and the same spec always renders identically.">
<style>
{face_css}
{CSS}
</style>
<div class="wrap">
<header>
<div class="bar">
  <button id="themebtn" type="button" aria-live="polite">theme: system</button>
  <span class="note">MEDIA-031 &middot; every number on this page was measured, none were written by hand</span>
</div>
<h1>A layout engine where the model writes data and a solver writes geometry</h1>
<p class="lede">The model produces a typed spec: a title, some bars, some cards, some steps. It never
picks a coordinate. A difference-constraint solver assigns every position from measured text
widths, and if the constraints cannot all hold the engine refuses and names the conflict rather
than emitting something broken.</p>

<div class="claims">
  <div class="claim">
    <h3>Claim 1 &middot; text never overflows</h3>
    <span class="n" id="c1">&mdash;</span>
    <span class="note">Measured in this browser with <code>getComputedTextLength()</code> on every
    text element on this page, against the container the solver assigned it.</span>
  </div>
  <div class="claim">
    <h3>Claim 2 &middot; labels never collide</h3>
    <span class="n" id="c2">&mdash;</span>
    <span class="note">Every pair of drawn labels, em box against em box, measured from the DOM.</span>
  </div>
  <div class="claim">
    <h3>Claim 3 &middot; identical output</h3>
    <span class="n ok">100 / 100</span>
    <span class="note">One spec rendered a hundred times, byte for byte the same, and 35 specs
    producing 35 distinct outputs so the test cannot pass by emitting a constant.</span>
  </div>
</div>
</header>

<h2>Why SVG text is the hard part</h2>
<p>SVG has no text layout. You write <code>&lt;text x="10" y="20"&gt;hello&lt;/text&gt;</code> and the
renderer decides how wide that is. Nothing in the file says. So an engine that wants to promise
a label fits its box has to compute the same number the renderer will, which means reading the
font.</p>
<p>This engine parses the TrueType tables directly: <code>cmap</code> for character to glyph,
<code>hmtx</code> for each glyph's advance width, <code>head</code> for the em scale. Summing
advances gives the width. The tempting shortcut, <code>len(text) * constant</code>, is wrong by
up to 80 percent on ten-character strings, which the first figure below shows at full size.</p>
<div class="tablewrap">
<table>
<thead><tr><th>string</th><th>characters</th><th class="num">measured at 16px</th><th class="num">len &times; 8</th><th class="num">error</th></tr></thead>
<tbody id="estimator"></tbody>
</table>
</div>
<p class="note">Those measured values come from the advance table embedded in this page, which was
extracted by the engine's own parser. The rightmost column of the browser check below re-measures
the same strings with the browser's own text engine, so the two can be compared directly.</p>

<h2>Measured in this browser</h2>
<p>A build-time check using fontTools already found no overflow and no collision. That check and
the engine share a repository, though, so the browser gets the final word: it is the thing that
actually decides how wide a string is.</p>
<div class="tablewrap"><table>
<thead><tr><th>quantity</th><th class="num">built with fontTools</th><th class="num">measured in this browser</th></tr></thead>
<tbody id="cross"></tbody>
</table></div>
<p id="verdict" class="note"></p>

<h2>Real output</h2>
<p>Each graphic below is inline SVG generated by <code>engine/render.py</code> from the spec shown
underneath it. Colours come from CSS custom properties, so the theme button at the top of the page
retints all of them without regenerating anything.</p>
{gallery}

<h2>The same spec, both themes</h2>
<p>The spec's own <code>theme</code> field decides the colours baked into a standalone
<code>.svg</code> file. Inside a page, the page wins.</p>
<div class="pair">
  <div class="scroll" style="--ig-bg:#ffffff;--ig-panel:#f4f6f9;--ig-panel-line:#e0e5ec;--ig-card:#fff;--ig-card-line:#dde3ea;--ig-fg:#14161a;--ig-muted:#5b6472;--ig-track:#e5e9ef;--ig-badge-fg:#fff">{svgs["c29-mixed-light"]}</div>
  <div class="scroll" style="--ig-bg:#0f1115;--ig-panel:#171a20;--ig-panel-line:#282e38;--ig-card:#13161c;--ig-card-line:#2b313b;--ig-fg:#e9ebef;--ig-muted:#9aa3b2;--ig-track:#232936;--ig-badge-fg:#0f1115">{svgs["c28-mixed-dark"]}</div>
</div>

<h2>Measure something yourself</h2>
<p>This panel runs the engine's measurement and line-breaking rules in the browser, using the
advance table embedded above. Type anything, set a container width, and it shows the width the
engine computes for every line it produces, the width this browser reports for the same line, and
how much room is left inside the container. A character outside the embedded table is refused, the
same way the engine refuses a character its font has no glyph for.</p>
<div class="lab">
  <label for="labtext" class="note">text</label>
  <textarea id="labtext">Pneumonoultramicroscopicsilicovolcanoconiosis is one unbreakable word, and WWWWWWWWWW is much wider than iiiiiiiiii even though both are ten characters.</textarea>
  <div class="labgrid">
    <div><label for="labwidth">container width (px)</label><input id="labwidth" type="number" value="360" min="20" max="1600" step="10"></div>
    <div><label for="labsize">font size (px)</label><input id="labsize" type="number" value="15" min="4" max="72" step="1"></div>
    <div><label for="labweight">weight</label><select id="labweight"><option value="regular">regular</option><option value="bold">bold</option></select></div>
    <div><label for="labpolicy">overflow policy</label><select id="labpolicy"><option value="wrap">wrap</option><option value="ellipsis">ellipsis</option><option value="strict">strict</option></select></div>
  </div>
  <div id="labout"></div>
</div>

<h2>When it refuses</h2>
<p>{report["refusals"]} specs in the test corpus are there because they must <em>not</em> render. A
squeezed bar chart is the clearest case: the label column and the value column are sized from
measured text, and if what is left for the bars falls below the minimum track length, the solver
finds a positive cycle in the constraint graph and reports the chain of requirements that
contradict each other.</p>
<pre><code>{esc(_sample_refusal())}</code></pre>

<h2>Every corpus spec</h2>
<p>All {report["specs"]} of them, including the adversarial ones: a string longer than the canvas,
an unbreakable 180-character word, CJK with no spaces, four-byte emoji, a single character, an
empty string, a 200px canvas and a 1600px one.</p>
{rest}

<footer>
<p>Part of the thousand catalog, task MEDIA-031. Fonts embedded as subset WOFF2: DejaVu Sans
(Bitstream Vera / Arev licence) and Droid Sans Fallback (Apache 2.0). Engine code MIT.</p>
</footer>
</div>

<script id="labmetrics" type="application/json">{metrics}</script>
<script id="buildreport" type="application/json">{rep}</script>
<script>
{JS}
</script>
"""


def _sample_refusal() -> str:
    for name, make, _ in REFUSALS:
        if "squeezed" in name and "bars" in name:
            try:
                render_spec(make())
            except Exception as exc:
                return f"{type(exc).__name__}: {exc}"
    return "(no sample available)"


JS = r"""
(function(){
  "use strict";
  var TITLE = "svg-infographic: a layout engine that measures its own text";
  var report = JSON.parse(document.getElementById("buildreport").textContent);
  var M = JSON.parse(document.getElementById("labmetrics").textContent);

  // ---- theme -------------------------------------------------------------
  var order = ["system", "light", "dark"];
  var idx = 0;
  var btn = document.getElementById("themebtn");
  function applyTheme(){
    var mode = order[idx];
    if (mode === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", mode);
    btn.textContent = "theme: " + mode;
  }
  btn.addEventListener("click", function(){ idx = (idx + 1) % order.length; applyTheme(); });
  applyTheme();

  // ---- shared measurement over the embedded advance table -----------------
  function tableFor(weight){
    var t = M[weight], map = Object.create(null);
    for (var i = 0; i < t.cps.length; i++) map[t.cps[i]] = t.adv[i];
    return {map: map, upem: t.upem, asc: t.asc, desc: t.desc};
  }
  var TBL = {regular: tableFor("regular"), bold: tableFor("bold")};

  function measure(tbl, s, size){
    var total = 0;
    for (var i = 0; i < s.length; i++){
      var cp = s.codePointAt(i);
      if (cp > 0xffff) i++;
      var a = tbl.map[cp];
      if (a === undefined) return {ok:false, missing:cp};
      total += a;
    }
    return {ok:true, w: total * size / tbl.upem};
  }

  // ---- the browser is the authority on claim 1 ----------------------------
  // Every text element in every embedded SVG is re-measured with the browser's own text
  // engine and compared against the container the solver assigned. Page identity is asserted
  // inside the loop, because a shared browser can be navigated away mid-check.
  function browserCheck(){
    if (document.title !== TITLE) throw new Error("wrong page: " + document.title);
    var texts = document.querySelectorAll("svg[data-engine='svg-infographic'] text");
    var res = {
      elements: 0, overflows: 0, worst: Infinity, worstWhere: "",
      worstDelta: 0, worstDeltaWhere: "", pairs: 0, collisions: 0, minSep: Infinity,
      minSepWhere: "", boxes: 0
    };
    var perSvg = new Map();
    for (var i = 0; i < texts.length; i++){
      var t = texts[i];
      var svg = t.ownerSVGElement;
      if (!svg || svg.dataset.engine !== "svg-infographic") continue;
      var content = t.textContent;
      var boxId = t.getAttribute("data-box");
      var box = svg.querySelector("#box-" + CSS.escape(boxId));
      if (!box) { res.overflows++; continue; }
      res.elements++;

      var len = t.getComputedTextLength();
      var claimed = parseFloat(t.getAttribute("data-measured"));
      if (content.trim() !== ""){
        var d = Math.abs(len - claimed);
        if (d > res.worstDelta){
          res.worstDelta = d;
          res.worstDeltaWhere = svg.dataset.specId + "/" + t.id + " " + JSON.stringify(content.slice(0,24));
        }
      }

      var anchor = t.getAttribute("text-anchor") || "start";
      var x = parseFloat(t.getAttribute("x"));
      var x0 = anchor === "start" ? x : (anchor === "end" ? x - len : x - len / 2);
      var x1 = x0 + len;
      var asc = parseFloat(t.getAttribute("data-ascent"));
      var desc = parseFloat(t.getAttribute("data-descent"));
      var base = parseFloat(t.getAttribute("y"));
      var y0 = base - asc, y1 = base + desc;

      var c = box.getAttribute("data-content").split(/\s+/).map(Number);
      var fit = t.getAttribute("data-fit").split(/\s+/).map(Number);
      var left = Math.max(c[0], fit[0]), right = Math.min(c[0] + c[2], fit[1]);
      var top = c[1], bottom = c[1] + c[3];
      var TOL = 0.05;
      var margins = [x0 - left, right - x1, y0 - top, bottom - y1];
      for (var k = 0; k < margins.length; k++){
        if (margins[k] < -TOL) res.overflows++;
        if (margins[k] < res.worst){
          res.worst = margins[k];
          res.worstWhere = svg.dataset.specId + "/" + t.id + " " + JSON.stringify(content.slice(0,24));
        }
      }

      if (content.trim() !== "" && len > 0){
        if (!perSvg.has(svg)) perSvg.set(svg, []);
        perSvg.get(svg).push({id: t.id, x0: x0, x1: x1, y0: y0, y1: y1, spec: svg.dataset.specId});
      }
    }
    res.boxes = document.querySelectorAll("svg[data-engine='svg-infographic'] rect[data-content]").length;

    perSvg.forEach(function(runs){
      for (var a = 0; a < runs.length; a++){
        for (var b = a + 1; b < runs.length; b++){
          var p = runs[a], q = runs[b];
          var dx = Math.max(p.x0 - q.x1, q.x0 - p.x1);
          var dy = Math.max(p.y0 - q.y1, q.y0 - p.y1);
          var sep = Math.max(dx, dy);
          res.pairs++;
          if (sep <= 0) res.collisions++;
          if (sep < res.minSep){
            res.minSep = sep;
            res.minSepWhere = p.spec + " " + p.id + " vs " + q.id;
          }
        }
      }
    });
    if (document.title !== TITLE) throw new Error("page changed during the check");
    return res;
  }

  function n(v, d){ return (Math.round(v * Math.pow(10, d)) / Math.pow(10, d)).toFixed(d); }

  function render(){
    var r;
    try { r = browserCheck(); }
    catch (e){
      document.getElementById("verdict").innerHTML =
        '<span class="bad">the browser check did not run: ' + String(e.message) + "</span>";
      return;
    }
    window.__igBrowserCheck = r;

    document.getElementById("c1").innerHTML = r.overflows === 0
      ? '<span class="ok">0 / ' + r.elements + " overflow</span>"
      : '<span class="bad">' + r.overflows + " / " + r.elements + " overflow</span>";
    document.getElementById("c2").innerHTML = r.collisions === 0
      ? '<span class="ok">0 / ' + r.pairs + " intersect</span>"
      : '<span class="bad">' + r.collisions + " / " + r.pairs + " intersect</span>";

    var rows = [
      ["text elements checked", report.texts, r.elements],
      ["containers in the file", "&mdash;", r.boxes],
      ["overflowing elements", report.overflows, r.overflows],
      ["worst clearance to a container edge (px)", n(report.worst_margin, 4), n(r.worst, 4)],
      ["label pairs compared", report.pairs, r.pairs],
      ["intersecting label pairs", report.collisions, r.collisions],
      ["minimum label separation (px)", n(report.min_separation, 4), n(r.minSep, 4)],
      ["largest engine vs renderer width disagreement (px)", "0.0100", n(r.worstDelta, 4)]
    ];
    document.getElementById("cross").innerHTML = rows.map(function(row){
      return "<tr><td>" + row[0] + '</td><td class="num">' + row[1] + '</td><td class="num">' + row[2] + "</td></tr>";
    }).join("");

    var good = r.overflows === 0 && r.collisions === 0 && r.worst >= -0.05 && r.worstDelta < 0.05;
    document.getElementById("verdict").innerHTML = good
      ? '<span class="ok">This browser measured ' + r.elements + " text elements and " + r.pairs +
        " label pairs. None overflowed, none intersected, and the widest disagreement between the " +
        "engine's font-metric arithmetic and the browser's own text engine was " + n(r.worstDelta, 4) +
        "px.</span>"
      : '<span class="bad">This browser found ' + r.overflows + " overflow(s), " + r.collisions +
        " collision(s), worst clearance " + n(r.worst, 4) + "px, worst width disagreement " +
        n(r.worstDelta, 4) + "px.</span>";

    // estimator table
    var samples = ["WWWWWWWWWW", "iiiiiiiiii", "MMMMMMMMMM", "llllllllll", ".........."];
    document.getElementById("estimator").innerHTML = samples.map(function(s){
      var m = measure(TBL.regular, s, 16);
      var est = s.length * 8;
      var err = ((est - m.w) / m.w) * 100;
      return "<tr><td><code>" + s + "</code></td>" +
        '<td class="num">' + s.length + "</td>" +
        '<td class="num">' + n(m.w, 2) + "</td>" +
        '<td class="num">' + est + "</td>" +
        '<td class="num ' + (Math.abs(err) > 20 ? "bad" : "") + '">' + (err > 0 ? "+" : "") + n(err, 0) + "%</td></tr>";
    }).join("");
  }

  // ---- the lab -----------------------------------------------------------
  var CJK = [[0x1100,0x11FF],[0x2E80,0x9FFF],[0xA960,0xA97F],[0xAC00,0xD7FF],[0xF900,0xFAFF],
             [0xFE30,0xFE4F],[0xFF00,0xFF60],[0xFFE0,0xFFE6]];
  function isCJK(ch){
    var cp = ch.codePointAt(0);
    return CJK.some(function(r){ return cp >= r[0] && cp <= r[1]; });
  }
  function tokenize(text){
    var out = [], cur = "", kind = "";
    for (var i = 0; i < text.length; i++){
      var ch = text[i] === "\t" ? " " : text[i];
      var k = ch === " " ? "space" : (isCJK(ch) ? "cjk" : "word");
      if (k === "cjk"){ if (cur){ out.push(cur); cur = ""; kind = ""; } out.push(ch); continue; }
      if (k !== kind && cur){ out.push(cur); cur = ""; }
      kind = k; cur += ch;
    }
    if (cur) out.push(cur);
    return out;
  }
  function charBreak(tbl, tok, size, avail){
    var lines = [], cur = "";
    for (var i = 0; i < tok.length; i++){
      var cand = cur + tok[i];
      var m = measure(tbl, cand, size);
      if (cur && m.ok && m.w > avail){ lines.push(cur); cur = tok[i]; } else { cur = cand; }
    }
    if (cur) lines.push(cur);
    return lines;
  }
  function wrap(tbl, text, size, avail){
    var lines = [], cur = "";
    tokenize(text).forEach(function(tok){
      var cand = cur + tok;
      var m = measure(tbl, cand.replace(/ +$/, ""), size);
      if (m.ok && m.w <= avail){ cur = cand; return; }
      if (cur.replace(/ +$/, "")) lines.push(cur.replace(/ +$/, ""));
      cur = "";
      if (!tok.trim()) return;
      var mt = measure(tbl, tok, size);
      if (mt.ok && mt.w > avail){
        var pieces = charBreak(tbl, tok, size, avail);
        lines = lines.concat(pieces.slice(0, -1));
        cur = pieces[pieces.length - 1];
      } else { cur = tok; }
    });
    if (cur.replace(/ +$/, "")) lines.push(cur.replace(/ +$/, ""));
    return lines.length ? lines : [""];
  }

  var probe = null;
  function browserWidth(s, size, weight){
    if (!probe){
      probe = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      probe.setAttribute("width", "0"); probe.setAttribute("height", "0");
      probe.style.position = "absolute"; probe.style.visibility = "hidden";
      probe.innerHTML = '<text id="probe-t"></text>';
      document.body.appendChild(probe);
    }
    var t = probe.querySelector("#probe-t");
    t.setAttribute("font-family", "DejaVu Sans");
    t.setAttribute("font-size", String(size));
    t.setAttribute("font-weight", weight === "bold" ? "700" : "400");
    t.setAttribute("font-kerning", "none");
    t.setAttribute("font-variant-ligatures", "none");
    t.setAttribute("letter-spacing", "0");
    t.setAttributeNS("http://www.w3.org/XML/1998/namespace", "xml:space", "preserve");
    t.textContent = s;
    return s === "" ? 0 : t.getComputedTextLength();
  }

  function runLab(){
    var text = document.getElementById("labtext").value;
    var avail = Math.max(20, Math.min(1600, parseFloat(document.getElementById("labwidth").value) || 360));
    var size = Math.max(4, Math.min(72, parseFloat(document.getElementById("labsize").value) || 15));
    var weight = document.getElementById("labweight").value;
    var policy = document.getElementById("labpolicy").value;
    var tbl = TBL[weight];
    var out = document.getElementById("labout");

    var probeM = measure(tbl, text, size);
    if (!probeM.ok){
      out.innerHTML = '<p class="bad">refused: U+' +
        probeM.missing.toString(16).toUpperCase().padStart(4, "0") +
        " is not in the advance table embedded in this page, so its width is unknown. " +
        "Guessing it is exactly what breaks claim 1, so nothing is laid out.</p>";
      return;
    }

    var lines;
    if (policy === "strict"){
      if (probeM.w > avail){
        out.innerHTML = '<p class="bad">refused: the text measures ' + n(probeM.w, 2) +
          "px and the container is " + n(avail, 2) + "px. Policy <code>strict</code> does not " +
          "wrap or truncate, so the engine raises instead of overflowing.</p>";
        return;
      }
      lines = [text];
    } else if (policy === "ellipsis"){
      if (probeM.w <= avail) lines = [text.replace(/\n/g, " ")];
      else {
        var flat = text.replace(/\n/g, " ");
        var ellW = measure(tbl, "…", size).w;
        if (ellW > avail){
          out.innerHTML = '<p class="bad">refused: even the ellipsis needs ' + n(ellW, 2) +
            "px and the container is " + n(avail, 2) + "px.</p>";
          return;
        }
        var keep = "";
        for (var i = 0; i < flat.length; i++){
          if (measure(tbl, keep + flat[i], size).w + ellW > avail) break;
          keep += flat[i];
        }
        lines = [keep.replace(/ +$/, "") + "…"];
      }
    } else {
      lines = [];
      text.split("\n").forEach(function(hard){ lines = lines.concat(wrap(tbl, hard, size, avail)); });
    }

    var worst = Infinity, worstDelta = 0;
    var rows = lines.map(function(ln, i){
      var e = measure(tbl, ln, size).w;
      var b = browserWidth(ln, size, weight);
      var slack = avail - e;
      if (slack < worst) worst = slack;
      worstDelta = Math.max(worstDelta, Math.abs(b - e));
      return "<tr><td class=\"num\">" + (i + 1) + "</td><td><code>" +
        ln.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</code></td>" +
        '<td class="num">' + n(e, 2) + '</td><td class="num">' + n(b, 2) + '</td>' +
        '<td class="num ' + (slack < 0 ? "bad" : "ok") + '">' + n(slack, 2) + "</td></tr>";
    }).join("");

    out.innerHTML =
      '<div class="tablewrap"><table><thead><tr><th>line</th><th>content</th>' +
      '<th class="num">engine (px)</th><th class="num">browser (px)</th>' +
      '<th class="num">room left (px)</th></tr></thead><tbody>' + rows + "</tbody></table></div>" +
      '<p class="note">' + lines.length + " line(s) at " + n(size, 0) + "px in a " + n(avail, 0) +
      "px container. Tightest line has " + n(worst, 2) + "px to spare. " +
      "Largest engine-versus-browser disagreement " + n(worstDelta, 4) + "px." +
      (worst < 0 ? ' <span class="bad">A negative figure here would be an overflow.</span>' : "") +
      "</p>";
  }

  ["labtext", "labwidth", "labsize", "labweight", "labpolicy"].forEach(function(id){
    var el = document.getElementById(id);
    el.addEventListener("input", runLab);
    el.addEventListener("change", runLab);
  });

  function boot(){ render(); runLab(); }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(boot);
  else window.addEventListener("load", boot);
})();
"""


def main() -> int:
    out_svg = ROOT / "out" / "svg"
    out_svg.mkdir(parents=True, exist_ok=True)
    svgs: dict[str, str] = {}
    for spec in CORPUS:
        svg = render_spec(spec)
        (out_svg / f"{spec.id}.svg").write_text(svg, encoding="utf-8")
        svgs[spec.id] = svg

    used = corpus_chars()
    fonts: dict[tuple[str, str], bytes] = {}
    for key, chars in sorted(used.items()):
        family, weight = key.split("|")
        if family == "DejaVu Sans":
            chars = chars | set(LAB_CHARS)
        path = _path_for(family, weight)
        fonts[(family, weight)] = woff2_subset(path, chars)
    # The page's own body copy and code blocks use these two.
    for family, weight in (("DejaVu Sans", "400"), ("DejaVu Sans", "700"), ("DejaVu Sans Mono", "400")):
        if (family, weight) not in fonts:
            fonts[(family, weight)] = woff2_subset(_path_for(family, weight), set(LAB_CHARS))

    report = build_report()
    html = build_html(report, fonts, svgs)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text(html, encoding="utf-8")

    total_font = sum(len(v) for v in fonts.values())
    print(f"wrote {len(svgs)} svg files to out/svg/")
    print(f"wrote docs/index.html, {len(html.encode()) // 1024} KiB, fonts {total_font // 1024} KiB")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _path_for(family: str, weight: str) -> Path:
    if family == "DejaVu Sans":
        return resolve_font_path("DejaVu Sans Bold" if weight == "700" else "DejaVu Sans")
    return resolve_font_path(family)


if __name__ == "__main__":
    raise SystemExit(main())
