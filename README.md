# svg-infographic

A layout engine where the model produces a typed data spec and a constraint solver produces the
geometry. Three properties are guaranteed and measured rather than hoped for:

1. **Text never overflows its container.**
2. **Labels never collide with each other.**
3. **The same spec always renders identically, byte for byte.**

Catalog task **MEDIA-031**.

The model's job is to write a `Doc`: a title, some KPI cards, a bar chart, a numbered flow, some
prose. It never picks a coordinate, a width, or a font size chosen to make something fit. That is
what makes the three properties provable, because a model that cannot place anything cannot make
anything overlap.

```python
from engine.spec import Bar, BarChart, Doc, Kpi, KpiRow, Steps
from engine.render import render_spec

svg = render_spec(Doc(
    id="phases",
    title="Where the time goes",
    subtitle="Measured across 40 builds",
    blocks=(
        KpiRow(cards=(Kpi("Specs", "35", "in the corpus"), Kpi("Overflows", "0", "measured"))),
        BarChart(caption="Time per phase", unit="ms",
                 bars=(Bar("measure text", 12), Bar("solve constraints", 31), Bar("render", 6))),
        Steps(caption="Pipeline", items=("Measure.", "Break.", "Solve.", "Emit.")),
    ),
))
```

Thirty-five real outputs are in [`examples/`](examples/), and the page at
[`docs/index.html`](docs/index.html) shows them inline with the browser's own measurement of every
text element on it.

## Why SVG text measurement is the hard part

SVG has no text layout. You write `<text x="10" y="20">hello</text>` and the renderer decides how
wide that is. Nothing in the file says. An engine that wants to promise a label fits its box has to
compute the same number the renderer will compute, which means reading the font.

So `engine/fontmetrics.py` parses TrueType directly with `struct`:

| table | what it gives |
|---|---|
| `head` | `unitsPerEm`, the scale that turns font units into em fractions |
| `maxp` | `numGlyphs` |
| `hhea` | `numberOfHMetrics`, how many entries `hmtx` actually stores |
| `hmtx` | per-glyph advance width, the quantity that determines a run's length |
| `cmap` | codepoint to glyph id, subtable formats 4, 6 and 12 |
| `OS/2` | typographic and windows vertical metrics |
| `loca`, `glyf` | each glyph's own bounding box, for ink extents |

Advance width is the right quantity. It is how far the pen moves after drawing a glyph. Glyph
bounding-box width is a different and wrong number: it excludes side bearings, so summing it
underestimates, and it is zero for a space.

The tempting shortcut, `len(text) * constant`, is not close. Measured at 16px in DejaVu Sans:

```
'WWWWWWWWWW' is 158.20px, 'iiiiiiiiii' is 44.45px, ratio 3.56
len(text) * 8 is off by up to 80% on ten-character strings
```

Two things this deliberately does not do. Kerning and ligatures are switched off in the emitted SVG
rather than reimplemented from GPOS, so the rendered advance is exactly the sum of `hmtx` advances.
Complex scripts that need shaping, reordering or contextual forms are out of scope; see
[Limitations](#limitations).

## How the metrics were verified independently

Three separate checks, none of which shares code with the parser:

1. **Against fontTools.** Every codepoint in every supported font, advance by advance. fontTools is
   a separate implementation by other people. `tests/test_fontmetrics.py` reports
   `font metrics: 43739 codepoint advances matched fontTools exactly`, with zero mismatches, and
   also checks `unitsPerEm`, the full cmap codepoint set, and the `hmtx` tail rule where glyphs
   beyond `numberOfHMetrics` reuse the last advance.
2. **Against a real browser.** `tools/browser_check.js` measures `getComputedTextLength()` on all
   449 text elements of the published page and compares each one with the width the engine wrote
   into the file. Worst disagreement: **0.01375px**, which is Chromium's 1/64px subpixel grid.
3. **Against an invariant.** In a monospaced font any two equal-length strings must measure equal,
   which is true of `DejaVu Sans Mono` here to the last bit and would not be true of a parser that
   mixed up glyph ids.

The independent checker in `tests/detectors.py` imports nothing from `engine/`. It reads the emitted
SVG off disk, re-measures every string with fontTools, and derives each container from the
rectangle actually drawn in the file, so the engine cannot claim a container it did not paint.

## The solver

`engine/solver.py` is a difference-constraint solver. Every relationship the layout needs has the
form

```
v_j - v_i >= w
```

which covers minimum sizes, minimum gaps, maximum sizes (rewritten with a negative weight) and
equalities (both directions at once). Such a system has an exact textbook solution: build a graph
with an edge `i -> j` of weight `w` per constraint, add a source with a zero edge to every variable,
and compute longest paths with Bellman-Ford. The result is the componentwise-minimal solution, and
the system is unsatisfiable exactly when the graph has a positive-weight cycle.

That last property is why this solver rather than an arithmetic pass. When constraints conflict, the
cycle *is* the explanation, and it gets reported verbatim:

```
Unsatisfiable: constraints on the x axis cannot all hold. These 8 constraints form a conflicting cycle:
  bar chart 0 value column is exactly 265.42px, its widest measured value
  bar chart 0 keeps a 12.0px gap between bars and values
  bar chart 0 bars need at least 28.0px of track
  bar chart 0 keeps a 12.0px gap between labels and bars
  bar chart 0 label column is exactly 43.87px, its widest measured label
  bar chart 0 panel content starts at x=36.0
  bar chart 0 panel content ends at x=164.0
  bar chart 0 value column is flush with the panel's right edge
```

The engine never degrades. There is no code path that emits a layout violating a constraint, because
such a layout would make claims 1 and 2 unfalsifiable. Refusal is a feature, and 14 specs in the
corpus exist to prove it fires.

## Determinism

No wall clock, no process id, no randomness, no iteration over a set or over a dict whose order
depends on input order, and every coordinate rounded to two decimals before it is emitted. Rounding
is directional: positions round to nearest, but anything the layout commits to as "at least this
wide" rounds away from zero, and anything it divides out as an allowance rounds towards zero. Both
directions matter, and inverting one of them is attack 3 below.

## Running it

```
python3 -m unittest discover -s tests -t .   # 41 tests, no dependencies beyond fontTools
python3 tools/measure.py                     # the headline numbers, exit 1 if any claim breaks
python3 tools/build_docs.py                  # regenerate examples/ and docs/index.html
node tools/browser_check.js                  # measure the page in a real Chromium
bash scripts/verify.sh                       # all of the above, exit 0 only on real success
bash scripts/attack_verify.sh                # break the engine four ways, confirm verify notices
```

Requirements: Python 3.11+, `fonttools` (with `brotli` for the WOFF2 subsets the page embeds), Node
for the browser stage, and a `playwright-core` install with Chromium. The browser stage is not
optional in `verify.sh`: if Node or Chromium is missing the script fails, because a skipped check is
"could not verify" and never "verified".

## Tests

| file | what it establishes |
|---|---|
| `tests/test_fontmetrics.py` | every advance matches fontTools; missing glyphs are refused rather than guessed |
| `tests/test_overflow.py` | claim 1 over the corpus, plus three negative controls |
| `tests/test_collision.py` | claim 2 over the corpus, plus three negative controls |
| `tests/test_determinism.py` | claim 3, including across processes with different `PYTHONHASHSEED` |
| `tests/test_refusal.py` | 14 unsatisfiable specs raise with a description; solver unit tests |
| `tests/test_sweep.py` | every canvas width from 160 to 1400 and every font size from 4 to 48 either lays out cleanly or refuses |

Every detector has a negative control, because a detector that never fires proves nothing:

- text 300px wide placed in a 52px box, and the detector must report it (it reports 295.6px)
- text placed below its box, and the detector must report a bottom overflow
- a `data-fit` column that claims to be wider than the rectangle it sits in, which is how an engine
  could hide an overflow by lying about its container
- two labels at identical coordinates (reported, separation -18.36px)
- two labels partially overlapping
- two labels whose edges touch exactly, where a strictly-less-than test would wrongly pass
- 35 specs producing 35 distinct outputs, so the determinism test cannot pass on a constant

## Three things a browser changed about this engine

Each was found by measuring the published page, not by reading the code. In each case the engine was
right about the font and wrong about the renderer.

| what was wrong | error | fix |
|---|---|---|
| Chromium hints every glyph advance to a whole pixel, so a 45-character line rendered wider than the sum of its advances | 12.05px | `text-rendering: geometricPrecision`, after which the two agree to 0.014px |
| `font-kerning="none"` as an SVG presentation attribute is ignored; computed style came back `auto` | n/a | set it in a `style` attribute, where it takes effect |
| the box the renderer reports covers the font's full line metrics, not the typographic ascender and descender | 518 elements outside their containers | reserve the union of the hhea, typographic and windows metrics, plus the ink of the glyphs being set, plus one pixel for the renderer's rounding |

A fourth came from attacking the verify script rather than the engine, and it is described under
[Attacking the verify script](#attacking-the-verify-script).

## Attacking the verify script

A verify command that passes on a broken implementation is worse than none. `scripts/attack_verify.sh`
copies the tree, breaks it, and runs the real `verify.sh` in the copy. Real output:

```
  verify correctly failed on 'text measurement replaced with len(text) * 8' (exit 1)
  verify correctly failed on 'collision-avoidance pass disabled' (exit 1)
  verify correctly failed on 'measured widths rounded down instead of up' (exit 1)
  verify correctly failed on 'renderer emits a constant' (exit 1)

every attack was caught
```

The first run of that script found a genuine hole. Attack 3, inverting `_ceil2` so measured widths
round down instead of up, produced containers a hundredth of a pixel narrower than their content,
and the checker's 0.02px tolerance swallowed it whole: `verify exit code: 0`. The tolerance existed
on the reasoning that a container edge and a text edge each round to the 0.01px grid, which was
wrong, because every constraint weight already sits on that grid. It is now 0.001px, float noise and
nothing more, and the attack fails as it should. That fix is the reason claim 1's worst-case margin
below can be read as exact rather than as within-tolerance.

## Status

`bash scripts/verify.sh`, exit code **0**. Real output, trimmed only where noted.

```
svg-infographic verify
project: ~/Projects/thousand/projects/svg-infographic

=== 1. python: what is available ===
Python 3.12.3
fontTools 4.62.1 (the independent parser the checks compare against)

=== 2. fonts the engine will measure ===
  DejaVu Sans              5918 codepoints  upem 2048  /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
  DejaVu Sans Bold         5898 codepoints  upem 2048  /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
  DejaVu Sans Mono         3322 codepoints  upem 2048  /usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf
  Droid Sans Fallback     28601 codepoints  upem 256   /usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf

=== 3. test suite ===
[... 41 tests, verbose list trimmed ...]
Ran 41 tests in 2.028s

OK

    negative control: two labels at one point reported, separation -18.3584px

    5461 label pairs checked, 0 intersections
    minimum label separation: 1.0000px  (c09-tiny-canvas t2(para) vs t3(para) 'This single sentence' / 'deliberately far lon')
    PYTHONHASHSEED 0 / 1 / 12345 all gave sha256 098a51c4ae36524d
    35 corpus specs produced 35 distinct outputs

    100 renders of c28-mixed-dark: sha256 bd76c7ef781c88c5, all identical

    font metrics: 43739 codepoint advances matched fontTools exactly

    len(text) * 8 is off by up to 80% on ten-character strings

    'WWWWWWWWWW' is 158.20px, 'iiiiiiiiii' is 44.45px, ratio 3.56

    393 text elements across 35 specs, 0 overflows
    worst-case clearance on any edge: 0.0000px  (c01-hello/t1 title left 'Hello')
    worst-case clearance on a trailing edge: 0.0000px  (c01-hello/t1 title bottom 'Hello')

    negative control: detector reported 295.6px of right overflow

    14 unsatisfiable specs all refused with a description

    width sweep: 491 layouts (12837 text elements), 43 refusals, 0 overflows, 0 collisions
    sweep worst clearance 0.0000px (sweep-209-1/t8 caption top 'Bars')
    sweep minimum separation 1.0000px (sweep-209-1 t29(footer) vs t30(footer) 'No width may silentl' / 'overflow.')
    font size sweep: 41 sizes from 4.0 to 48.0px, 0 overflows, 0 collisions

=== 4. measured claims ===
specs rendered                     35
containers assigned by the solver  268
text elements measured             393 (389 with ink)
label pairs compared               5461
refusal cases                      14
engine vs fontTools disagreements  0

CLAIM 1  overflowing elements      0 of 393
CLAIM 1  worst-case margin         +0.0000 px  (c01-hello/t1 title left 'Hello')
CLAIM 1  worst trailing-edge margin +0.0000 px  (c01-hello/t1 title bottom 'Hello')
CLAIM 1  container edges checked   1572
CLAIM 1    edges outside container 0
CLAIM 1    edges exactly flush     807  (container sized to its content)
CLAIM 1    smallest positive gap   +0.0514 px

CLAIM 2  intersecting label pairs  0 of 5461
CLAIM 2  minimum label separation  +1.0000 px  (c09-tiny-canvas t2(para) vs t3(para) 'This single sentence' / 'deliberately far lon')

=== 5. build the page ===
wrote 35 svg files to examples/
wrote docs/index.html, 446 KiB, fonts 63 KiB
page: ~/Projects/thousand/projects/svg-infographic/docs/index.html (457343 bytes)
page self-check: engine marker, both theme mechanisms, no remote assets

=== 6. real browser measurement ===
serving docs on port 41131 (kernel-assigned)
  ok   server answers
  ok   served bytes contain a generated SVG from this engine
  ok   served bytes carry the expected title
  ok   served page references no remote host
  ok   measurement ran on the right page
  ok   no script errors on the page
  ok   the embedded DejaVu Sans subset actually loaded
  ok   all generated SVGs are inline in the page
  ok   text elements measured
  ok   CLAIM 1: no text overflows its container in the browser
  ok   CLAIM 2: no two labels intersect in the browser
  ok   engine font arithmetic matches the browser's own text engine
  ok   minimum label separation is positive
  ok   CLAIM 1 by getBBox(), the renderer's own ink box, inside the container plus declared overhang
  ok   CLAIM 2 by getBBox(), the renderer's own ink boxes never intersect
  ok   enough bbox pairs compared
  ok   the page's own checker counted the same elements
  ok   the page's own checker agrees on the overflow count
  ok   the page's own checker agrees on minimum separation
  ok   data-theme light and dark give different palettes
  ok   theme probe ran under prefers-color-scheme: light
  ok   --bg resolves under prefers-color-scheme: light
  ok   data-theme still overrides under prefers-color-scheme: light
  ok   data-theme=dark overrides prefers-color-scheme: light
  ok   theme probe ran under prefers-color-scheme: dark
  ok   --bg resolves under prefers-color-scheme: dark
  ok   data-theme still overrides under prefers-color-scheme: dark
  ok   data-theme=light overrides prefers-color-scheme: dark
  ok   overflow probe ran at 390px
  ok   no element escapes the page at 390px
  ok   documentElement does not scroll sideways at 390px
  ok   body overflow-x is not hidden at 390px
  ok   overflow probe ran at 320px
  ok   no element escapes the page at 320px
  ok   documentElement does not scroll sideways at 320px
  ok   body overflow-x is not hidden at 320px
  ok   measurement ran at 390px
  ok   CLAIM 1 still holds at a 390px viewport
  ok   viewport width does not change the measured clearance
  ok   the page made no remote requests

--- browser measurement ---
{
  "svgs": 37,
  "text_elements": 449,
  "containers": 310,
  "empty_runs": 4,
  "browser_overflows": 0,
  "browser_worst_clearance_px": 0,
  "browser_worst_clearance_where": "c13-bars-many/t51 top \"row 24\"",
  "browser_worst_horizontal_clearance_px": 0,
  "browser_worst_horizontal_clearance_where": "c29-mixed-light/t1 left \"Everything at once, ligh\"",
  "browser_worst_vertical_clearance_px": 0,
  "bbox_overflows": 0,
  "bbox_worst_clearance_px": 0.02,
  "bbox_worst_clearance_where": "c33-tiny-text/t2 left \"This single sentence is \"",
  "bbox_pairs": 6217,
  "bbox_collisions": 0,
  "bbox_min_separation_px": 3.04,
  "engine_vs_browser_worst_delta_px": 0.01375,
  "engine_vs_browser_worst_delta_where": "c09-tiny-canvas/t6 \"many lines and every one of\"",
  "label_pairs": 6217,
  "browser_collisions": 0,
  "browser_min_separation_px": 1,
  "browser_min_separation_where": "c09-tiny-canvas t2 vs t3",
  "failures": 0
}

all browser checks passed

=== 7. determinism across two fresh processes ===
PYTHONHASHSEED=0      098a51c4ae36524d31128445a77dfca74a5b261a0fb2b739e114c0defb8fa97b
PYTHONHASHSEED=99991  098a51c4ae36524d31128445a77dfca74a5b261a0fb2b739e114c0defb8fa97b
byte-identical across processes

=== 8. no secrets, no absolute home paths in committed files ===
scanned files under svg-infographic/, findings: 0

=== VERIFIED ===
All claims measured and holding. Page: ~/Projects/thousand/projects/svg-infographic/docs/index.html
```

### Reading those numbers

**Claim 1, worst-case overflow margin: +0.0000px, 0 of 393 elements outside, 0 of 1572 container
edges outside.** The margin is zero rather than positive because 807 of the 1572 edges are flush by
construction: the solver sizes a container to exactly the content it measured, and text is set flush
with the left and top of it. Of the edges that are not flush, the tightest has **+0.0514px**. Zero
is the correct number here and it is never negative, which is the whole claim. Attack 3 above is
what makes that distinction load-bearing.

**Claim 2, minimum label separation: +1.0000px**, between two consecutive wrapped lines of the
9px paragraph in `c09-tiny-canvas`. That is the engine's `MIN_LEADING`, the smallest clear space it
will leave between two stacked line boxes. Across 5461 pairs nothing is closer and nothing touches.

**Claim 1 in the browser: 0 of 449 elements, worst clearance 0.0000px**, and separately **0 of 449
by `getBBox()`** with a worst clearance of 0.02px. Both measurements were taken at a 1280px viewport
and repeated at 390px with identical results, because the graphics keep their intrinsic size and
scroll inside their own container rather than being rescaled.

**Claim 3: 100 identical renders**, sha256 `bd76c7ef781c88c5…`, 35 specs producing 35 distinct
digests, and the same total digest under three different `PYTHONHASHSEED` values in separate
processes.

## Running the verify

```bash
bash scripts/verify.sh
```

Every measurement runs with no dependencies except step 6, which measures the rendered page in a
real browser. That step FAILS rather than skipping when `playwright-core` is not reachable,
because a check that did not run reports the same success as one that ran and passed.

```bash
npm install --no-save playwright-core && npx playwright install chromium
# or point at an existing install
PLAYWRIGHT_CORE=/path/to/playwright-core bash scripts/verify.sh
```

## Limitations

**Fonts.** Four are supported, and nothing else: `DejaVu Sans`, `DejaVu Sans Bold`,
`DejaVu Sans Mono`, `Droid Sans Fallback`. A spec naming any other font is rejected on construction
with a message saying so. This is deliberate. A width table for one font applied to another is a
guess, and a guess is exactly what breaks claim 1. Adding a font means adding its file path to
`_FONT_FILES` in `engine/fontmetrics.py`; the parser handles any TrueType file with a `glyf`
outline table, so the list is short because these are the fonts installed here, not because of a
limit in the code.

**Font files must be present.** The engine locates them under `/usr/share/fonts/truetype` and a few
other standard roots, overridable with `FONT_SEARCH_PATH`. If the file is missing the engine raises
with the list of paths it tried. The published page does not depend on this: it embeds subset WOFF2
copies of the fonts it measured, which is why the browser measurement is meaningful on a machine
with different fonts installed.

**One font per document, and characters outside it are refused.** There is no font fallback. A
document in `Droid Sans Fallback` cannot contain Latin letters, because that font has no Latin
glyphs, and a document in `DejaVu Sans` cannot contain Han. Both cases raise
`UnsupportedCharacter` naming the codepoint. Falling back silently would mean measuring with one
font and rendering with another, which is the same class of bug as guessing. It also means the CJK
example in the corpus has no digits in it, since `Droid Sans Fallback` has none, and a numbered
`Steps` block in that font is a refusal case.

**Emoji are monochrome.** `DejaVu Sans` covers U+1F600 through U+1F643 and a good deal of the
symbol blocks as outline glyphs, so they measure and render like any other glyph. There is no
colour emoji font here, and a codepoint outside DejaVu's coverage is refused rather than substituted.

**Complex scripts are out of scope.** Arabic, Hebrew, Devanagari, Thai and anything else needing
bidi reordering, contextual forms or mark positioning will measure as a naive left-to-right sum of
advances, which is wrong. The engine does not currently detect this and refuse, which it should;
that is the most significant gap in it. Latin, Greek, Cyrillic, CJK and symbols are correct.

**Kerning is off, not implemented.** The emitted SVG carries `font-kerning: none` and
`font-variant-ligatures: none` so that the rendered advance equals the measured sum. Text is
therefore very slightly looser than the same font would be with kerning on. Implementing GPOS
kerning and measuring with it would be the fix.

**`getBBox()` containment carries two stated allowances.** A renderer's reported bounding box is not
the advance box. It includes the glyph ink, which reaches outside the advance box wherever a side
bearing is negative (up to 0.05em for `J` in DejaVu Sans, and a full em for combining marks), and
Chromium then rounds the box it reports outward by up to one pixel. So the browser check asserts the
ink box is inside the container widened by the run's own overhang, which the engine declares per
element in `data-ink` and which is verified against fontTools at build time, plus one pixel for that
rounding. The advance box, which is what the engine reserves and what claim 1 is about, is inside
with no allowance at all.

**Blocks are a vertical stack.** Four block types, one column. There is no multi-column layout, no
float, no image, no legend, no axis with ticks. Adding a block type means adding a constraint-building
function; adding a second column means giving the x system per-column variables, which the solver
already supports and the current block set does not use.

**Chromium is the only renderer measured.** Firefox and WebKit will have their own subpixel and
bounding-box behaviour. `resvg`, `librsvg` and Inkscape were not tested at all.

**The `RENDER_SLACK` and `VERT_SLACK` constants are calibrated, not derived.** They are 0.05px and
1.0px, chosen from measurements of Chromium and stated in `engine/layout.py` with the numbers that
motivated them. A renderer quantizing more coarsely than Chromium could exceed them, and the browser
check is what would say so.

## Layout

```
engine/
  fontmetrics.py   TrueType parser: cmap, hmtx, head, hhea, OS/2, loca, glyf
  solver.py        difference-constraint solver, Bellman-Ford longest paths
  spec.py          the typed spec, validated on construction, with a JSON round trip
  layout.py        line breaking and constraint building, one system per axis
  render.py        deterministic SVG emission
  errors.py        every failure carries what conflicted
corpus/specs.py    35 specs that must render, 14 that must refuse
tests/
  detectors.py     independent measurement, imports nothing from engine/
  test_*.py        41 tests
tools/
  measure.py       the headline numbers
  build_docs.py    render the corpus, subset the fonts, build the page
  browser_check.js measure the page in a real Chromium
scripts/
  verify.sh        everything, exit 0 only on real success
  attack_verify.sh break the engine four ways and confirm verify notices
examples/          35 generated SVGs
docs/index.html    self-contained page, no remote assets
```

## Licence

MIT, see [LICENSE](LICENSE). The fonts are not part of this repository; the page embeds subset
copies of DejaVu Sans (Bitstream Vera and Arev licences, both permissive) and Droid Sans Fallback
(Apache 2.0).

## The page is now a pure function of its committed inputs

`docs/index.html` used to change on every build even when nothing changed. fontTools' WOFF2
subsetting is not reproducible: given a byte-identical character set, three consecutive builds
produced subsets of 5096, 5096 and 5088 bytes with three different digests. Pinning
`PYTHONHASHSEED` stabilised the length but not the bytes, so at least two sources of variation are
involved.

This never touched the engine's own determinism, which is measured separately and holds (100
renders of one spec, a single digest, byte-identical across processes). It only affected the
compressed font blob. But it rewrote four `@font-face` lines on every build, so any verify run left
the repository dirty and the committed page was an arbitrary pick among equally valid outputs.

Font subsets are now build **inputs**, committed under `assets/fonts/`, with a hash of the exact
character set in each filename. Changing the corpus text regenerates them automatically, and a
stale subset can never be silently reused for text it does not cover. `verify.sh` builds the page
twice and requires the two to be byte-identical; disabling the cache makes that check fail at byte
489, which is how it was confirmed to be live rather than decorative.
