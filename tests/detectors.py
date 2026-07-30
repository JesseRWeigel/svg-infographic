"""Independent measurement of an emitted SVG.

Nothing in this file imports ``engine``. It reads the SVG that was written to disk, parses
the font with fontTools instead of with the engine's own parser, and re-derives every number
the claims depend on. That separation is the point: a checker that shares the measurement
code with the thing it checks inherits its bugs and reports clean on output that is not.

What it derives, and from what:

  text width        fontTools hmtx advances summed over the string, scaled by unitsPerEm.
                    Compared against the engine's own ``data-measured`` attribute, so a
                    disagreement between the two parsers is itself a failure.
  line box height   the union of the font's hhea, OS/2 typographic and OS/2 windows vertical
                    metrics, the ink extents of the glyphs in the run taken from fontTools'
                    glyf bounds, and the engine's one-pixel renderer allowance. That definition
                    is shared with the engine on purpose, because it is a design decision rather
                    than a derivation; what is independent is every number that goes into it.
  container         the ``data-content`` rectangle on the ``<rect>`` the text names in
                    ``data-box``, intersected with the ``data-fit`` column the solver
                    assigned. Both come off the drawn geometry, so the engine cannot claim a
                    container bigger than the one in the file.

The only thing taken on trust from the engine is which container a run belongs to, and that
is unavoidable: claim 1 is a statement about the container the solver assigned. Containment
of every box inside the canvas is checked here too, so a runaway container is still caught.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont

SVG_NS = "{http://www.w3.org/2000/svg}"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"

# Written out again here on purpose. If the engine's table were imported, a wrong path in it
# would be wrong in both places at once.
_FILES = {
    ("DejaVu Sans", "400"): "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ("DejaVu Sans", "700"): "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ("DejaVu Sans Mono", "400"): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ("DejaVu Sans Mono", "700"): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ("Droid Sans Fallback", "400"): "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ("Droid Sans Fallback", "700"): "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
}

_CACHE: dict[tuple[str, str], "FTFont"] = {}


VERT_SLACK = 1.0  # must match engine.layout.VERT_SLACK


@dataclass
class FTFont:
    upem: int
    ascent: float
    descent: float
    advances: dict[int, int]  # codepoint -> advance in font units
    ink: dict[int, tuple[int, int]]  # codepoint -> (yMin, yMax) in font units
    xink: dict[int, tuple[int, int]]  # codepoint -> (xMin, xMax) in font units

    def width(self, text: str, size: float) -> float:
        total = 0
        for ch in text:
            a = self.advances.get(ord(ch))
            if a is None:
                raise KeyError(f"fontTools finds no glyph for U+{ord(ch):04X} ({ch!r})")
            total += a
        return total * size / self.upem

    def required_ascent(self, text: str, size: float) -> float:
        up = max([self.ink.get(ord(c), (0, 0))[1] for c in text] + [self.ascent])
        return up * size / self.upem + VERT_SLACK

    def required_descent(self, text: str, size: float) -> float:
        down = max([-self.ink.get(ord(c), (0, 0))[0] for c in text] + [abs(self.descent)])
        return down * size / self.upem + VERT_SLACK

    def ink_overhang(self, text: str, size: float) -> tuple[float, float]:
        """(left, right) px of paint outside the advance box, computed from fontTools bounds."""
        pen = 0
        left = 0
        right = 0
        for ch in text:
            cp = ord(ch)
            box = self.xink.get(cp)
            adv = self.advances.get(cp, 0)
            if box is not None and box[0] != box[1]:
                if pen + box[0] < -left:
                    left = -(pen + box[0])
                if pen + box[1] > right:
                    right = pen + box[1]
            pen += adv
        return (max(0, left) * size / self.upem, max(0, right - pen) * size / self.upem)


def font_for(family: str, weight: str) -> FTFont:
    key = (family, weight)
    if key in _CACHE:
        return _CACHE[key]
    path = _FILES.get(key)
    if path is None:
        raise KeyError(f"the checker has no font file for {family!r} weight {weight!r}")
    tt = TTFont(path)
    cmap = tt.getBestCmap()
    hmtx = tt["hmtx"]
    upem = tt["head"].unitsPerEm
    asc = tt["hhea"].ascent
    desc = abs(tt["hhea"].descent)
    if "OS/2" in tt:
        os2 = tt["OS/2"]
        if getattr(os2, "sTypoAscender", 0) > 0:
            asc = max(asc, os2.sTypoAscender)
            desc = max(desc, abs(os2.sTypoDescender))
        asc = max(asc, getattr(os2, "usWinAscent", 0))
        desc = max(desc, getattr(os2, "usWinDescent", 0))
    advances = {cp: hmtx[g][0] for cp, g in cmap.items()}
    glyf = tt["glyf"] if "glyf" in tt else None
    ink: dict[int, tuple[int, int]] = {}
    xink: dict[int, tuple[int, int]] = {}
    for cp, name in cmap.items():
        if glyf is None:
            ink[cp] = (-desc, asc)
            xink[cp] = (0, 0)
            continue
        g = glyf[name]
        ink[cp] = (getattr(g, "yMin", 0) or 0, getattr(g, "yMax", 0) or 0)
        xink[cp] = (getattr(g, "xMin", 0) or 0, getattr(g, "xMax", 0) or 0)
    f = FTFont(upem=upem, ascent=asc, descent=-desc, advances=advances, ink=ink, xink=xink)
    _CACHE[key] = f
    return f


# ---- SVG parsing -------------------------------------------------------------


@dataclass
class BoxEl:
    id: str
    x: float
    y: float
    w: float
    h: float
    cx: float
    cy: float
    cw: float
    ch: float


@dataclass
class TextEl:
    id: str
    box: str
    role: str
    content: str
    x: float
    baseline: float
    size: float
    family: str
    weight: str
    anchor: str
    claimed_width: float
    claimed_ascent: float
    claimed_descent: float
    fit_x0: float
    fit_x1: float
    claimed_ink_left: float = 0.0
    claimed_ink_right: float = 0.0
    # filled by measure()
    width: float = 0.0
    ascent: float = 0.0
    descent: float = 0.0

    @property
    def x0(self) -> float:
        if self.anchor == "start":
            return self.x
        if self.anchor == "end":
            return self.x - self.width
        return self.x - self.width / 2.0

    @property
    def x1(self) -> float:
        return self.x0 + self.width

    @property
    def y0(self) -> float:
        return self.baseline - self.ascent

    @property
    def y1(self) -> float:
        return self.baseline + self.descent

    # What the run genuinely needs, from this checker's own parse.
    required_ascent: float = 0.0
    required_descent: float = 0.0
    ink_left: float = 0.0
    ink_right: float = 0.0

    def measure(self) -> None:
        f = font_for(self.family, self.weight)
        self.width = f.width(self.content, self.size)
        self.ink_left, self.ink_right = f.ink_overhang(self.content, self.size)
        self.required_ascent = f.required_ascent(self.content, self.size)
        self.required_descent = f.required_descent(self.content, self.size)
        # Containment is checked against whichever box is larger: what the engine claims to
        # have reserved, or what this checker says the glyphs need. If the engine under-reserved,
        # the larger box is the checker's and the overflow shows up.
        self.ascent = max(self.claimed_ascent, self.required_ascent)
        self.descent = max(self.claimed_descent, self.required_descent)


@dataclass
class Doc:
    id: str
    width: float
    height: float
    boxes: dict[str, BoxEl]
    texts: list[TextEl]


def parse(svg: str, source: str = "<string>") -> Doc:
    # The stdlib XML parser expands internal entities, which is the billion-laughs hazard.
    # This checker only ever reads files this repository generated, and the generator emits no
    # doctype and no entity declarations, so refusing both closes the hole without adding a
    # dependency. If either ever appears, that is itself a bug worth failing on.
    head = svg[:4096].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in svg.upper():
        raise ValueError(f"{source}: refusing to parse XML containing a doctype or entity declaration")
    root = ET.fromstring(svg)
    if not root.tag.endswith("svg"):
        raise ValueError(f"{source}: root element is {root.tag}, not svg")
    width = float(root.get("width"))
    height = float(root.get("height"))
    boxes: dict[str, BoxEl] = {}
    texts: list[TextEl] = []
    for el in root.iter():
        if el.tag == SVG_NS + "rect" and el.get("data-content"):
            cx, cy, cw, ch = (float(v) for v in el.get("data-content").split())
            bid = el.get("id", "")[len("box-") :]
            boxes[bid] = BoxEl(
                id=bid,
                x=float(el.get("x")),
                y=float(el.get("y")),
                w=float(el.get("width")),
                h=float(el.get("height")),
                cx=cx,
                cy=cy,
                cw=cw,
                ch=ch,
            )
        elif el.tag == SVG_NS + "text":
            fit = el.get("data-fit", "0 0").split()
            ink = el.get("data-ink", "0 0").split()
            t = TextEl(
                id=el.get("id", ""),
                box=el.get("data-box", ""),
                role=el.get("data-role", ""),
                content=el.text or "",
                x=float(el.get("x")),
                baseline=float(el.get("y")),
                size=float(el.get("font-size")),
                family=el.get("font-family"),
                weight=el.get("font-weight", "400"),
                anchor=el.get("text-anchor", "start"),
                claimed_width=float(el.get("data-measured", "nan")),
                claimed_ascent=float(el.get("data-ascent", "nan")),
                claimed_descent=float(el.get("data-descent", "nan")),
                fit_x0=float(fit[0]),
                fit_x1=float(fit[1]),
                claimed_ink_left=float(ink[0]),
                claimed_ink_right=float(ink[1]),
            )
            t.measure()
            texts.append(t)
    return Doc(id=root.get("data-spec-id", ""), width=width, height=height, boxes=boxes, texts=texts)


def load(path: str | Path) -> Doc:
    p = Path(path)
    return parse(p.read_text(encoding="utf-8"), str(p))


# ---- claim 1: nothing overflows ---------------------------------------------

# Tolerance for the comparison, and it is deliberately far below the emit precision.
#
# An earlier version allowed 0.02px, on the reasoning that a container edge and a text edge each
# round to the 0.01px grid. scripts/attack_verify.sh proved that wrong: inverting one rounding
# function so measured widths round *down* instead of up produced containers a hair narrower
# than their content, and 0.02px of slack swallowed it whole. Verify passed on a broken engine.
#
# The correct tolerance is float noise and nothing more. Every constraint weight sits on the
# 0.01px grid, so every solved coordinate does too, and measured widths round away from zero.
# A genuine overflow of half the emit precision is still an overflow.
TOL = 0.001


@dataclass
class Overflow:
    doc: str
    text_id: str
    role: str
    content: str
    side: str
    amount: float  # how far outside, in px


def overflows(doc: Doc) -> list[Overflow]:
    """Every way a text element escapes the container the solver assigned it."""
    out: list[Overflow] = []
    for t in doc.texts:
        if t.box not in doc.boxes:
            out.append(Overflow(doc.id, t.id, t.role, t.content, "missing-box", float("inf")))
            continue
        b = doc.boxes[t.box]
        left = max(b.cx, t.fit_x0)
        right = min(b.cx + b.cw, t.fit_x1)
        top, bottom = b.cy, b.cy + b.ch
        if t.x0 < left - TOL:
            out.append(Overflow(doc.id, t.id, t.role, t.content, "left", left - t.x0))
        if t.x1 > right + TOL:
            out.append(Overflow(doc.id, t.id, t.role, t.content, "right", t.x1 - right))
        if t.y0 < top - TOL:
            out.append(Overflow(doc.id, t.id, t.role, t.content, "top", top - t.y0))
        if t.y1 > bottom + TOL:
            out.append(Overflow(doc.id, t.id, t.role, t.content, "bottom", t.y1 - bottom))
        if t.fit_x0 < b.cx - TOL or t.fit_x1 > b.cx + b.cw + TOL:
            out.append(
                Overflow(doc.id, t.id, t.role, t.content, "fit-outside-box", max(b.cx - t.fit_x0, t.fit_x1 - (b.cx + b.cw)))
            )
    for b in doc.boxes.values():
        if b.x < -TOL or b.y < -TOL or b.x + b.w > doc.width + TOL or b.y + b.h > doc.height + TOL:
            out.append(Overflow(doc.id, b.id, "box", "", "box-outside-canvas", 0.0))
    return out


def worst_margin(doc: Doc) -> tuple[float, str]:
    """The smallest clearance between any text edge and its container edge.

    Positive means everything fits with room to spare. This is the number that gets printed,
    because "no overflows" is only as strong as how close the tightest case came.
    """
    worst = float("inf")
    where = ""
    for t in doc.texts:
        if t.box not in doc.boxes:
            return (float("-inf"), f"{doc.id}/{t.id} names a box that is not in the file")
        b = doc.boxes[t.box]
        left = max(b.cx, t.fit_x0)
        right = min(b.cx + b.cw, t.fit_x1)
        for name, m in (
            ("left", t.x0 - left),
            ("right", right - t.x1),
            ("top", t.y0 - b.cy),
            ("bottom", (b.cy + b.ch) - t.y1),
        ):
            if m < worst:
                worst = m
                where = f"{doc.id}/{t.id} {t.role} {name} {t.content[:34]!r}"
    # Snap double noise to zero. A container sized to exactly its content gives a margin of 0,
    # and -2e-15 printed as "-0.0000" would read as an overflow that is not there.
    return (0.0 if abs(worst) < 1e-9 else worst), where


def worst_trailing_margin(doc: Doc) -> tuple[float, str]:
    """The smallest clearance on the edges text actually grows towards.

    Text is set flush with the left and top of its container by design, so those margins are
    zero on purpose and say nothing. The right and bottom edges are where an overflow would
    appear, so this is the number that shows how close the tightest case came.
    """
    worst = float("inf")
    where = ""
    for t in doc.texts:
        if t.box not in doc.boxes:
            continue
        b = doc.boxes[t.box]
        right = min(b.cx + b.cw, t.fit_x1)
        for name, m in (("right", right - t.x1), ("bottom", (b.cy + b.ch) - t.y1)):
            if m < worst:
                worst = m
                where = f"{doc.id}/{t.id} {t.role} {name} {t.content[:34]!r}"
    # Snap double noise to zero. A container sized to exactly its content gives a margin of 0,
    # and -2e-15 printed as "-0.0000" would read as an overflow that is not there.
    return (0.0 if abs(worst) < 1e-9 else worst), where


def margin_histogram(doc: Doc) -> tuple[int, int, float]:
    """(edges outside, edges exactly flush, smallest strictly positive clearance).

    A worst-case margin of zero is the expected result here, because the solver sizes a
    container to exactly the content it measured. Splitting the edges out says how many are
    flush by construction and how much room the rest have, which a single minimum cannot.
    """
    outside = 0
    flush = 0
    smallest_positive = float("inf")
    for t in doc.texts:
        if t.box not in doc.boxes:
            continue
        b = doc.boxes[t.box]
        left = max(b.cx, t.fit_x0)
        right = min(b.cx + b.cw, t.fit_x1)
        for m in (t.x0 - left, right - t.x1, t.y0 - b.cy, (b.cy + b.ch) - t.y1):
            if m < -1e-9:
                outside += 1
            elif m < 1e-9:
                flush += 1
            elif m < smallest_positive:
                smallest_positive = m
    return outside, flush, smallest_positive


def metric_disagreements(doc: Doc, tol: float = 0.011) -> list[str]:
    """Where the engine's own numbers differ from this checker's independent parse.

    Width has to match: the engine rounds up to 0.01px, so anything beyond that tolerance is a
    parser disagreement. Ascent and descent only have to be *at least* what the glyphs need,
    because the engine reserves one value for a whole stack of lines while this checker looks at
    one line at a time. Over-reserving is checked too, loosely, so a bug that inflates the
    reserve until everything trivially fits does not pass.
    """
    bad = []
    for t in doc.texts:
        if abs(t.width - t.claimed_width) > tol:
            bad.append(
                f"{doc.id}/{t.id} width: engine says {t.claimed_width}, fontTools says "
                f"{t.width:.4f} for {t.content[:40]!r} at {t.size}px {t.family} {t.weight}"
            )
        if t.claimed_ascent < t.required_ascent - tol:
            bad.append(
                f"{doc.id}/{t.id} reserved only {t.claimed_ascent} above the baseline but "
                f"{t.content[:30]!r} at {t.size}px needs {t.required_ascent:.4f}"
            )
        if t.claimed_descent < t.required_descent - tol:
            bad.append(
                f"{doc.id}/{t.id} reserved only {t.claimed_descent} below the baseline but "
                f"{t.content[:30]!r} at {t.size}px needs {t.required_descent:.4f}"
            )
        for side, claimed, actual in (
            ("left", t.claimed_ink_left, t.ink_left),
            ("right", t.claimed_ink_right, t.ink_right),
        ):
            if claimed < actual - tol or claimed > actual + 0.011:
                bad.append(
                    f"{doc.id}/{t.id} declares {claimed}px of {side} ink overhang but fontTools "
                    f"computes {actual:.4f}px for {t.content[:30]!r} at {t.size}px"
                )
        slack = max(t.claimed_ascent - t.required_ascent, t.claimed_descent - t.required_descent)
        if slack > 0.5 * t.size + 2.0:
            bad.append(
                f"{doc.id}/{t.id} reserved {slack:.2f}px more than needed at {t.size}px, which "
                f"looks like the reserve was inflated rather than measured"
            )
    return bad


# ---- claim 2: no two labels collide ------------------------------------------


def _drawn(doc: Doc) -> list[TextEl]:
    """Runs that actually mark the canvas. An empty string has no ink and no box."""
    return [t for t in doc.texts if t.content.strip() != "" and t.width > 0]


def separation(a: TextEl, b: TextEl) -> float:
    """Signed clearance between two em boxes.

    Positive is the gap on whichever axis they are apart. Zero or negative means the boxes
    touch or overlap, which is a collision.
    """
    dx = max(a.x0 - b.x1, b.x0 - a.x1)
    dy = max(a.y0 - b.y1, b.y0 - a.y1)
    return max(dx, dy)


def collisions(doc: Doc) -> list[tuple[str, str, float]]:
    runs = _drawn(doc)
    out = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            s = separation(runs[i], runs[j])
            if s <= 0:
                out.append((runs[i].id, runs[j].id, s))
    return out


def min_separation(doc: Doc) -> tuple[float, str]:
    runs = _drawn(doc)
    best = float("inf")
    where = ""
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            s = separation(runs[i], runs[j])
            if s < best:
                best = s
                where = (
                    f"{doc.id} {runs[i].id}({runs[i].role}) vs {runs[j].id}({runs[j].role}) "
                    f"{runs[i].content[:20]!r} / {runs[j].content[:20]!r}"
                )
    if not where:
        return float("inf"), f"{doc.id} has fewer than two drawn text runs"
    return best, where
