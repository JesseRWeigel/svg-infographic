"""Turn a spec into geometry.

Two things happen here, in this order.

1. Text is measured and broken into lines. Breaking comes first, because the number of lines
   determines how tall a box must be, and a box's height is an input to the vertical
   constraint system. The available width for breaking is known before solving, because a
   block is as wide as the canvas minus padding.

2. Every remaining relationship is handed to the difference-constraint solver, one system
   for x and one for y. Nothing here computes a final coordinate by arithmetic. The solver
   assigns all of them, so a relationship that cannot hold surfaces as a named conflict
   instead of as an overlap in the output.

The invariants that claims 1 and 2 rest on:

  Claim 1  every line handed to the renderer was measured against the exact content width
           the solver assigns to its box, and a line that could not be made to fit under its
           overflow policy raised instead of being emitted.
  Claim 2  every pair of text runs is separated on at least one axis by a constraint with a
           strictly positive weight, so their em boxes cannot touch.

Neither invariant is trusted on the strength of that paragraph. tests/detectors.py re-derives
both from the emitted SVG using a different font parser.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SpecError, TextDoesNotFit
from .fontmetrics import Font, get_font
from .solver import System
from .spec import BarChart, Block, Doc, KpiRow, Paragraph, Steps

# ---- rhythm ------------------------------------------------------------------
# Fixed constants. Nothing here is derived from the output, so the same spec produces the
# same numbers on every run and every machine.

DOC_PAD = 22.0
BLOCK_GAP = 18.0
PANEL_PAD = 14.0
CARD_PAD = 12.0
COL_GAP = 12.0
CARD_GAP = 12.0
STEP_GAP = 10.0
MIN_BAR = 28.0
BAR_H_RATIO = 0.92
LABEL_COL_MAX = 0.42
LINE_RATIO = 1.42
MIN_LEADING = 2.0
ELLIPSIS = "…"


def _r2(v: float) -> float:
    """Round to the emit precision.

    Applied to every quantity that becomes a constraint weight, so the weights are exactly
    the numbers that end up in the file and the solver's guarantees are guarantees about the
    emitted geometry rather than about some higher-precision intermediate.
    """
    return round(v, 2) + 0.0


@dataclass(frozen=True)
class LineMetrics:
    ascent: float
    descent: float
    line_height: float

    @property
    def em_box(self) -> float:
        return _r2(self.ascent + self.descent)


def metrics_for(font: Font, size: float) -> LineMetrics:
    a = _r2(font.ascent_px(size))
    d = _r2(font.descent_px(size))
    lh = _r2(max(size * LINE_RATIO, a + d + MIN_LEADING))
    return LineMetrics(a, d, lh)


# ---- line breaking -----------------------------------------------------------

_CJK_RANGES = (
    (0x1100, 0x11FF),
    (0x2E80, 0x9FFF),
    (0xA960, 0xA97F),
    (0xAC00, 0xD7FF),
    (0xF900, 0xFAFF),
    (0xFE30, 0xFE4F),
    (0xFF00, 0xFF60),
    (0xFFE0, 0xFFE6),
    (0x20000, 0x3FFFF),
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def tokenize(text: str) -> list[str]:
    """Split into break-opportunity tokens: space runs, single CJK characters, other runs.

    Latin scripts break at spaces. CJK has no spaces and breaks between characters, so a run
    of Han text needs per-character tokens or it becomes one unbreakable word as wide as the
    whole string.
    """
    out: list[str] = []
    cur = ""
    cur_kind = ""
    for raw in text:
        ch = " " if raw == "\t" else raw
        kind = "space" if ch == " " else ("cjk" if _is_cjk(ch) else "word")
        if kind == "cjk":
            if cur:
                out.append(cur)
                cur, cur_kind = "", ""
            out.append(ch)
            continue
        if kind != cur_kind and cur:
            out.append(cur)
            cur = ""
        cur_kind = kind
        cur += ch
    if cur:
        out.append(cur)
    return out


def _char_break(font: Font, token: str, size: float, avail: float) -> list[str]:
    """Split one unbreakable token at character boundaries.

    A URL or a chemical name can be wider than any box. A browser handles that with
    overflow-wrap: break-word, and so does this: the token is cut wherever it stops fitting.
    """
    lines: list[str] = []
    cur = ""
    for ch in token:
        cand = cur + ch
        if cur and font.measure(cand, size) > avail:
            lines.append(cur)
            cur = ch
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def break_lines(
    font: Font, text: str, size: float, avail: float, overflow: str, box: str
) -> list[str]:
    """Break ``text`` into lines each measuring at most ``avail`` px.

    The result is re-measured before it leaves this function. A line that still exceeds
    ``avail`` raises, because emitting it would silently break claim 1.
    """
    if avail <= 0:
        raise TextDoesNotFit(text, font.measure(text, size), avail, box)

    if overflow == "strict":
        w = font.measure(text, size)
        if w > avail:
            raise TextDoesNotFit(text, w, avail, box)
        lines = [text]
    elif overflow == "ellipsis":
        lines = [_ellipsize(font, text, size, avail, box)]
    elif overflow == "wrap":
        lines = []
        for hard in text.split("\n"):
            lines.extend(_wrap_one(font, hard, size, avail))
    else:
        raise SpecError(f"unknown overflow policy {overflow!r}")

    for ln in lines:
        w = font.measure(ln, size)
        if w > avail + 1e-9:
            raise TextDoesNotFit(ln, w, avail, box)
    return lines


def _wrap_one(font: Font, text: str, size: float, avail: float) -> list[str]:
    lines: list[str] = []
    cur = ""
    for tok in tokenize(text):
        cand = cur + tok
        if font.measure(cand.rstrip(" "), size) <= avail:
            cur = cand
            continue
        if cur.rstrip(" "):
            lines.append(cur.rstrip(" "))
        cur = ""
        if not tok.strip(" "):
            continue
        if font.measure(tok, size) > avail:
            pieces = _char_break(font, tok, size, avail)
            lines.extend(pieces[:-1])
            cur = pieces[-1]
        else:
            cur = tok
    if cur.rstrip(" "):
        lines.append(cur.rstrip(" "))
    return lines or [""]


def _ellipsize(font: Font, text: str, size: float, avail: float, box: str) -> str:
    flat = text.replace("\n", " ")
    if font.measure(flat, size) <= avail:
        return flat
    ell = ELLIPSIS if font.has_char(ELLIPSIS) else "..."
    ell_w = font.measure(ell, size)
    if ell_w > avail:
        raise TextDoesNotFit(text, ell_w, avail, box)
    keep = ""
    for ch in flat:
        if font.measure(keep + ch, size) + ell_w > avail:
            break
        keep += ch
    return keep.rstrip(" ") + ell


# ---- layout output -----------------------------------------------------------


@dataclass(frozen=True)
class Box:
    """A container the solver assigned.

    ``pad_x`` and ``pad_y`` are separate because horizontal and vertical insets are not the
    same thing here: a frame that only exists to carry a text stack has no vertical inset,
    while a card has both. The content rectangle derived from them is the container that
    claim 1 is about, and it is emitted into the SVG so an outside checker can read it.
    """

    id: str
    x: float
    y: float
    w: float
    h: float
    pad_x: float
    pad_y: float
    role: str

    @property
    def content(self) -> tuple[float, float, float, float]:
        return (
            _r2(self.x + self.pad_x),
            _r2(self.y + self.pad_y),
            _r2(self.w - 2 * self.pad_x),
            _r2(self.h - 2 * self.pad_y),
        )


@dataclass(frozen=True)
class TextRun:
    id: str
    box: str
    content: str
    x: float
    baseline: float
    size: float
    font: str
    anchor: str  # start | middle | end
    role: str
    width: float
    ascent: float
    descent: float
    # The horizontal slice the solver assigned to this run. For most runs it is the whole
    # content width of its box; for a bar label it is the label column, for a bar value the
    # value column, for a step's text the text column beside the badge. Claim 1 is a claim
    # about this interval, so it is emitted into the SVG for an outside checker to read.
    fit_x0: float = 0.0
    fit_x1: float = 0.0

    @property
    def x0(self) -> float:
        if self.anchor == "start":
            return self.x
        if self.anchor == "end":
            return _r2(self.x - self.width)
        return _r2(self.x - self.width / 2.0)

    @property
    def x1(self) -> float:
        return _r2(self.x0 + self.width)

    @property
    def y0(self) -> float:
        return _r2(self.baseline - self.ascent)

    @property
    def y1(self) -> float:
        return _r2(self.baseline + self.descent)


@dataclass(frozen=True)
class Shape:
    kind: str
    x: float
    y: float
    w: float
    h: float
    role: str
    accent: int = 0
    rx: float = 0.0


@dataclass(frozen=True)
class Layout:
    doc_id: str
    width: float
    height: float
    theme: str
    accent: int
    font: str
    title: str
    boxes: tuple[Box, ...]
    texts: tuple[TextRun, ...]
    shapes: tuple[Shape, ...]

    def box_by_id(self, bid: str) -> Box:
        for b in self.boxes:
            if b.id == bid:
                return b
        raise KeyError(bid)


# ---- helpers shared between sizing and solving -------------------------------


def _content_width(doc: Doc) -> float:
    return _r2(doc.width - 2 * DOC_PAD)


def _card_share(doc: Doc, n: int) -> float:
    return _r2((_content_width(doc) - (n - 1) * CARD_GAP) / n)


def _format_value(v: float, unit: str) -> str:
    """Deterministic number formatting. No locale, no scientific notation."""
    if float(v).is_integer() and abs(v) < 1e15:
        s = str(int(v))
    else:
        s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s + unit


# ---- the builder -------------------------------------------------------------


class _Builder:
    def __init__(self, doc: Doc):
        self.doc = doc
        self.font = get_font(doc.font)
        self.bold = get_font("DejaVu Sans Bold") if doc.font == "DejaVu Sans" else self.font
        self.ys = System("y")
        self.n = 0
        # (id, x, w, top_var, pad_x, pad_y, role); the bottom variable is id + ":bot"
        self.boxes: list[tuple[str, float, float, str, float, float, str]] = []
        self.texts: list[dict] = []
        # (kind, x, y_var, dy, w, h, role, accent, rx)
        self.shapes: list[tuple[str, float, str, float, float, float, str, int, float]] = []

    def uid(self) -> str:
        self.n += 1
        return f"t{self.n}"

    def box(
        self,
        bid: str,
        x: float,
        w: float,
        top_var: str,
        pad_x: float = 0.0,
        pad_y: float = 0.0,
        role: str = "frame",
    ) -> None:
        self.boxes.append((bid, _r2(x), _r2(w), top_var, _r2(pad_x), _r2(pad_y), role))

    def place_lines(
        self,
        box_id: str,
        lines: list[str],
        font: Font,
        size: float,
        anchor: str,
        x: float,
        role: str,
        top_var: str,
        top_offset: float,
        fit: tuple[float, float] | None = None,
    ) -> tuple[str, float]:
        """Declare one text run per line, stacked below ``top_var + top_offset``.

        One SVG element per line, never a tspan, so a browser can measure each line on its
        own and the overflow check has one number per element to compare.
        """
        lm = metrics_for(font, size)
        prev = ""
        for i, ln in enumerate(lines):
            bv = f"{box_id}:{role}:{i}:base"
            if i == 0:
                self.ys.exactly(
                    top_var,
                    bv,
                    _r2(top_offset + lm.ascent),
                    f"{box_id} first {role} baseline sits exactly "
                    f"{_r2(top_offset + lm.ascent)}px below the box top "
                    f"({_r2(top_offset)}px inset plus {lm.ascent}px ascent)",
                )
            else:
                self.ys.exactly(
                    prev,
                    bv,
                    lm.line_height,
                    f"{box_id} {role} line {i} sits {lm.line_height}px below line {i - 1}, "
                    f"clearing the {lm.em_box}px em box by {_r2(lm.line_height - lm.em_box)}px",
                )
            self.texts.append(
                dict(
                    id=self.uid(),
                    box=box_id,
                    content=ln,
                    x=_r2(x),
                    base_var=bv,
                    size=size,
                    font=font.name,
                    anchor=anchor,
                    role=role,
                    width=_r2(font.measure(ln, size)),
                    ascent=lm.ascent,
                    descent=lm.descent,
                    fit=None if fit is None else (_r2(fit[0]), _r2(fit[1])),
                )
            )
            prev = bv
        return prev, lm.descent


# ---- column solvers ----------------------------------------------------------


def _solve_bar_columns(doc: Doc, label_w: float, value_w: float, tag: str):
    """Assign the three bar-chart columns.

    Raises Unsatisfiable, naming the conflict, when the label and value columns leave less
    than MIN_BAR for the bars.
    """
    xs = System("x")
    left = _r2(DOC_PAD + PANEL_PAD)
    right = _r2(doc.width - DOC_PAD - PANEL_PAD)
    xs.pin("cl", left, f"{tag} panel content starts at x={left}")
    xs.pin("cr", right, f"{tag} panel content ends at x={right}")
    xs.exactly("cl", "lab_r", label_w, f"{tag} label column is exactly {label_w}px, its widest measured label")
    xs.exactly("lab_r", "bar_l", COL_GAP, f"{tag} keeps a {COL_GAP}px gap between labels and bars")
    xs.exactly("val_r", "cr", 0.0, f"{tag} value column is flush with the panel's right edge")
    xs.exactly("val_l", "val_r", value_w, f"{tag} value column is exactly {value_w}px, its widest measured value")
    xs.exactly("bar_r", "val_l", COL_GAP, f"{tag} keeps a {COL_GAP}px gap between bars and values")
    xs.at_least("bar_l", "bar_r", MIN_BAR, f"{tag} bars need at least {MIN_BAR}px of track")
    sol = xs.solve()
    return tuple(_r2(sol[k]) for k in ("cl", "lab_r", "bar_l", "bar_r", "val_l", "cr"))


def _solve_card_columns(doc: Doc, n: int, mins: list[float], tag: str):
    xs = System("x")
    left = DOC_PAD
    right = _r2(doc.width - DOC_PAD)
    share = _card_share(doc, n)
    xs.pin("cl", left, f"{tag} starts at x={left}")
    xs.pin("cr", right, f"{tag} ends at x={right}")
    prev = "cl"
    for i in range(n):
        li, ri = f"l{i}", f"r{i}"
        gap = 0.0 if i == 0 else CARD_GAP
        xs.exactly(prev, li, gap, f"{tag} card {i} starts {gap}px after the previous card")
        xs.exactly(li, ri, share, f"{tag} cards share the row equally at {share}px each")
        xs.at_least(
            li,
            ri,
            mins[i],
            f"{tag} card {i} needs at least {mins[i]}px for its widest measured line plus padding",
        )
        prev = ri
    xs.at_least(prev, "cr", 0.0, f"{tag} the last card must not run past the row's right edge")
    sol = xs.solve()
    return [_r2(sol[f"l{i}"]) for i in range(n)], share


# ---- top level ---------------------------------------------------------------


def layout(doc: Doc) -> Layout:
    """Solve a spec into geometry, or raise with a description of what conflicted."""
    if not isinstance(doc, Doc):
        raise SpecError(f"layout() needs a Doc, got {type(doc).__name__}")

    b = _Builder(doc)
    font, bold, ys = b.font, b.bold, b.ys
    cw = _content_width(doc)
    ys.pin("doc:top", 0.0, "the canvas top edge is y = 0")

    # header
    hdr = "box_header"
    b.box(hdr, DOC_PAD, cw, f"{hdr}:top", role="frame")
    ys.exactly("doc:top", f"{hdr}:top", DOC_PAD, f"header starts {DOC_PAD}px below the canvas top")
    title_lines = break_lines(font, doc.title, doc.title_size, cw, "wrap", hdr)
    last, desc = b.place_lines(hdr, title_lines, bold, doc.title_size, "start", DOC_PAD, "title", f"{hdr}:top", 0.0)
    ys.exactly(last, f"{hdr}:bot", desc, "header frame ends at the title's last descender")
    prev_bot = f"{hdr}:bot"

    if doc.subtitle:
        sb = "box_subtitle"
        ys.exactly(prev_bot, f"{sb}:top", 6.0, "subtitle starts 6px below the title's descender")
        b.box(sb, DOC_PAD, cw, f"{sb}:top", role="frame")
        sub_lines = break_lines(font, doc.subtitle, 14.0, cw, "wrap", sb)
        last, desc = b.place_lines(sb, sub_lines, font, 14.0, "start", DOC_PAD, "subtitle", f"{sb}:top", 0.0)
        ys.exactly(last, f"{sb}:bot", desc, "subtitle frame ends at its last descender")
        prev_bot = f"{sb}:bot"

    for bi, blk in enumerate(doc.blocks):
        top = f"blk{bi}:top"
        ys.exactly(prev_bot, top, BLOCK_GAP, f"block {bi} starts {BLOCK_GAP}px below what precedes it")
        prev_bot = _emit_block(b, doc, bi, blk, top)

    if doc.footer:
        fb = "box_footer"
        ys.exactly(prev_bot, f"{fb}:top", BLOCK_GAP, f"footer starts {BLOCK_GAP}px below the last block")
        b.box(fb, DOC_PAD, cw, f"{fb}:top", role="frame")
        fl = break_lines(font, doc.footer, 11.0, cw, "wrap", fb)
        last, desc = b.place_lines(fb, fl, font, 11.0, "start", DOC_PAD, "footer", f"{fb}:top", 0.0)
        ys.exactly(last, f"{fb}:bot", desc, "footer frame ends at its last descender")
        prev_bot = f"{fb}:bot"

    ys.exactly(prev_bot, "doc:bot", DOC_PAD, f"the canvas keeps {DOC_PAD}px below the last content")
    sol = ys.solve()

    height = _r2(sol["doc:bot"])
    boxes = tuple(
        Box(
            id=bid,
            x=x,
            y=_r2(sol[top_var]),
            w=w,
            h=_r2(sol[f"{bid}:bot"] - sol[top_var]),
            pad_x=px,
            pad_y=py,
            role=role,
        )
        for (bid, x, w, top_var, px, py, role) in b.boxes
    )
    by_id = {bx.id: bx for bx in boxes}
    texts_list = []
    for t in b.texts:
        bx = by_id[t["box"]]
        cx, _cy, cw_, _ch = bx.content
        fit = t["fit"] if t["fit"] is not None else (cx, _r2(cx + cw_))
        texts_list.append(
            TextRun(
                id=t["id"],
                box=t["box"],
                content=t["content"],
                x=t["x"],
                baseline=_r2(sol[t["base_var"]]),
                size=t["size"],
                font=t["font"],
                anchor=t["anchor"],
                role=t["role"],
                width=t["width"],
                ascent=t["ascent"],
                descent=t["descent"],
                fit_x0=fit[0],
                fit_x1=fit[1],
            )
        )
    texts = tuple(texts_list)
    shapes = tuple(
        Shape(kind=k, x=x, y=_r2(sol[yv] + dy), w=w, h=h, role=role, accent=acc, rx=rx)
        for (k, x, yv, dy, w, h, role, acc, rx) in b.shapes
    )
    return Layout(
        doc_id=doc.id,
        width=_r2(doc.width),
        height=height,
        theme=doc.theme,
        accent=doc.accent,
        font=doc.font,
        title=doc.title,
        boxes=boxes,
        texts=texts,
        shapes=shapes,
    )


def _emit_block(b: _Builder, doc: Doc, bi: int, blk: Block, top: str) -> str:
    if isinstance(blk, Paragraph):
        return _emit_paragraph(b, doc, bi, blk, top)
    if isinstance(blk, BarChart):
        return _emit_bars(b, doc, bi, blk, top)
    if isinstance(blk, KpiRow):
        return _emit_kpis(b, doc, bi, blk, top)
    if isinstance(blk, Steps):
        return _emit_steps(b, doc, bi, blk, top)
    raise SpecError(f"no layout rule for block type {type(blk).__name__}")


def _emit_paragraph(b: _Builder, doc: Doc, bi: int, blk: Paragraph, top: str) -> str:
    ys = b.ys
    bid = f"box_p{bi}"
    pad = PANEL_PAD if blk.emphasis else 0.0
    w = _content_width(doc)
    avail = _r2(w - 2 * pad)
    font = b.bold if blk.emphasis else b.font
    lines = break_lines(font, blk.text, blk.size, avail, blk.overflow, bid)
    b.box(bid, DOC_PAD, w, f"{bid}:top", pad, pad, "panel" if blk.emphasis else "frame")
    ys.exactly(top, f"{bid}:top", 0.0, f"paragraph block {bi} box top is the block top")
    last, desc = b.place_lines(bid, lines, font, blk.size, "start", _r2(DOC_PAD + pad), "para", f"{bid}:top", pad)
    ys.exactly(last, f"{bid}:bot", _r2(desc + pad), f"paragraph block {bi} keeps {pad}px below its last descender")
    return f"{bid}:bot"


def _emit_bars(b: _Builder, doc: Doc, bi: int, blk: BarChart, top: str) -> str:
    ys, font, bold = b.ys, b.font, b.bold
    bid = f"box_bars{bi}"
    tag = f"bar chart {bi}"
    panel_w = _content_width(doc)
    inner = _r2(panel_w - 2 * PANEL_PAD)

    peak = max(x.value for x in blk.bars)
    value_strs = [_format_value(x.value, blk.unit) for x in blk.bars]
    value_w = _r2(max(font.measure(s, blk.size) for s in value_strs))

    label_cap = _r2(inner * LABEL_COL_MAX)
    label_lines = [break_lines(font, x.label, blk.size, label_cap, blk.label_overflow, bid) for x in blk.bars]
    label_w = _r2(max((font.measure(ln, blk.size) for lns in label_lines for ln in lns), default=0.0))

    cl, lab_r, bar_l, bar_r, val_l, cr = _solve_bar_columns(doc, label_w, value_w, tag)
    track = _r2(bar_r - bar_l)
    lm = metrics_for(font, blk.size)

    b.box(bid, DOC_PAD, panel_w, f"{bid}:top", PANEL_PAD, PANEL_PAD, "panel")
    ys.exactly(top, f"{bid}:top", 0.0, f"{tag} panel top is the block top")

    cursor = f"{bid}:top"
    first_gap = PANEL_PAD
    if blk.caption:
        cap_lines = break_lines(bold, blk.caption, 15.0, inner, "wrap", bid)
        last, desc = b.place_lines(bid, cap_lines, bold, 15.0, "start", cl, "caption", f"{bid}:top", PANEL_PAD)
        cursor = f"{bid}:rows"
        ys.exactly(last, cursor, _r2(desc + 10.0), f"{tag} first row starts 10px below the caption's descender")
        first_gap = 0.0

    prev_row = cursor
    for ri, bar in enumerate(blk.bars):
        rid = f"{bid}r{ri}"
        rtop = f"{rid}:top"
        ys.exactly(
            prev_row,
            rtop,
            _r2(first_gap) if ri == 0 else 0.0,
            f"{tag} row {ri} begins where row {ri - 1} ends" if ri else f"{tag} row 0 begins {_r2(first_gap)}px into the panel",
        )
        lines = label_lines[ri]
        b.box(rid, cl, _r2(cr - cl), rtop, 0.0, 0.0, "frame")
        b.place_lines(rid, lines, font, blk.size, "start", cl, "barlabel", rtop, 0.0, fit=(cl, lab_r))
        b.place_lines(rid, [value_strs[ri]], font, blk.size, "end", cr, "barvalue", rtop, 0.0, fit=(val_l, cr))

        bar_h = _r2(lm.em_box * BAR_H_RATIO)
        dy = _r2((lm.em_box - bar_h) / 2.0)
        b.shapes.append(("rect", bar_l, rtop, dy, track, bar_h, "track", 0, _r2(bar_h / 2)))
        frac = 0.0 if peak <= 0 else bar.value / peak
        b.shapes.append(("rect", bar_l, rtop, dy, _r2(max(2.0, track * frac)), bar_h, "bar", doc.accent, _r2(bar_h / 2)))

        nlines = max(len(lines), 1)
        span = _r2(lm.line_height * nlines)
        ys.exactly(rtop, f"{rid}:bot", span, f"{tag} row {ri} is {span}px tall, {nlines} line(s) of {lm.line_height}px")
        prev_row = f"{rid}:bot"

    ys.exactly(prev_row, f"{bid}:bot", PANEL_PAD, f"{tag} panel keeps {PANEL_PAD}px below its last row")
    return f"{bid}:bot"


def _emit_kpis(b: _Builder, doc: Doc, bi: int, blk: KpiRow, top: str) -> str:
    ys, font, bold = b.ys, b.font, b.bold
    tag = f"kpi row {bi}"
    n = len(blk.cards)
    share = _card_share(doc, n)
    inner = _r2(share - 2 * CARD_PAD)
    if inner <= 0:
        raise TextDoesNotFit(blk.cards[0].value, _r2(2 * CARD_PAD), share, f"box_k{bi}c0")

    note_size = _r2(blk.label_size - 1)
    per_card = []
    mins = []
    for ci, c in enumerate(blk.cards):
        bidc = f"box_k{bi}c{ci}"
        vl = break_lines(bold, c.value, blk.value_size, inner, "ellipsis", bidc)
        ll = break_lines(font, c.label, blk.label_size, inner, "wrap", bidc)
        nl = break_lines(font, c.note, note_size, inner, "wrap", bidc) if c.note else []
        per_card.append((vl, ll, nl))
        widest = max(
            [bold.measure(s, blk.value_size) for s in vl]
            + [font.measure(s, blk.label_size) for s in ll]
            + [font.measure(s, note_size) for s in nl]
        )
        mins.append(_r2(widest + 2 * CARD_PAD))

    lefts, share = _solve_card_columns(doc, n, mins, tag)

    rowtop = f"box_kpirow{bi}:top"
    rowbot = f"box_kpirow{bi}:bot"
    ys.exactly(top, rowtop, 0.0, f"{tag} top is the block top")
    ys.at_least(rowtop, rowbot, 0.0, f"{tag} bottom is at or below its top")

    for ci, c in enumerate(blk.cards):
        bidc = f"box_k{bi}c{ci}"
        vl, ll, nl = per_card[ci]
        b.box(bidc, lefts[ci], share, f"{bidc}:top", CARD_PAD, CARD_PAD, "card")
        ys.exactly(rowtop, f"{bidc}:top", 0.0, f"{tag} card {ci} top aligns with the row top")
        cx = _r2(lefts[ci] + CARD_PAD)

        last, desc = b.place_lines(bidc, vl, bold, blk.value_size, "start", cx, "kpivalue", f"{bidc}:top", CARD_PAD)
        lv = f"{bidc}:labtop"
        ys.exactly(last, lv, _r2(desc + 4.0), f"{tag} card {ci} label starts 4px below the value's descender")
        b.box(f"{bidc}L", lefts[ci], share, lv, CARD_PAD, 0.0, "frame")
        last, desc = b.place_lines(f"{bidc}L", ll, font, blk.label_size, "start", cx, "kpilabel", lv, 0.0)
        ys.exactly(last, f"{bidc}L:bot", desc, f"{tag} card {ci} label frame ends at its descender")

        if nl:
            nv = f"{bidc}:notetop"
            ys.exactly(last, nv, _r2(desc + 3.0), f"{tag} card {ci} note starts 3px below the label's descender")
            b.box(f"{bidc}N", lefts[ci], share, nv, CARD_PAD, 0.0, "frame")
            last, desc = b.place_lines(f"{bidc}N", nl, font, note_size, "start", cx, "kpinote", nv, 0.0)
            ys.exactly(last, f"{bidc}N:bot", desc, f"{tag} card {ci} note frame ends at its descender")

        content_bot = f"{bidc}:content"
        ys.exactly(last, content_bot, _r2(desc + CARD_PAD), f"{tag} card {ci} keeps {CARD_PAD}px below its last descender")
        ys.at_least(content_bot, rowbot, 0.0, f"{tag} the row is at least as tall as card {ci}'s content")
        # Every card box ends at the row bottom, so the cards are drawn the same height and
        # each card's content is provably inside its own box.
        ys.exactly(rowbot, f"{bidc}:bot", 0.0, f"{tag} card {ci} is as tall as the row")

    return rowbot


def _emit_steps(b: _Builder, doc: Doc, bi: int, blk: Steps, top: str) -> str:
    ys, font, bold = b.ys, b.font, b.bold
    tag = f"steps {bi}"
    bid = f"box_s{bi}"
    panel_w = _content_width(doc)
    badge = _r2(max(22.0, blk.size * 1.8))
    text_x = _r2(DOC_PAD + PANEL_PAD + badge + COL_GAP)
    avail = _r2(doc.width - DOC_PAD - PANEL_PAD - text_x)
    if avail <= 0:
        raise TextDoesNotFit(blk.items[0], _r2(badge + COL_GAP), panel_w, bid)

    b.box(bid, DOC_PAD, panel_w, f"{bid}:top", PANEL_PAD, PANEL_PAD, "panel")
    ys.exactly(top, f"{bid}:top", 0.0, f"{tag} panel top is the block top")

    cursor = f"{bid}:top"
    first_gap = PANEL_PAD
    if blk.caption:
        cap = break_lines(bold, blk.caption, 15.0, _r2(panel_w - 2 * PANEL_PAD), "wrap", bid)
        last, desc = b.place_lines(bid, cap, bold, 15.0, "start", _r2(DOC_PAD + PANEL_PAD), "caption", f"{bid}:top", PANEL_PAD)
        cursor = f"{bid}:items"
        ys.exactly(last, cursor, _r2(desc + 10.0), f"{tag} first step starts 10px below the caption's descender")
        first_gap = 0.0

    lm = metrics_for(font, blk.size)
    nm = metrics_for(bold, blk.size)
    prev = cursor
    for si, item in enumerate(blk.items):
        sid = f"{bid}i{si}"
        stop = f"{sid}:top"
        gap = _r2(first_gap) if si == 0 else STEP_GAP
        ys.exactly(prev, stop, gap, f"{tag} step {si} starts {gap}px below what precedes it")
        lines = break_lines(font, item, blk.size, avail, "wrap", sid)
        b.box(sid, _r2(DOC_PAD + PANEL_PAD), _r2(panel_w - 2 * PANEL_PAD), stop, 0.0, 0.0, "frame")
        b.shapes.append(("rect", _r2(DOC_PAD + PANEL_PAD), stop, 0.0, badge, badge, "badge", doc.accent, _r2(badge / 2)))
        b.place_lines(
            sid,
            [str(si + 1)],
            bold,
            blk.size,
            "middle",
            _r2(DOC_PAD + PANEL_PAD + badge / 2),
            "stepnum",
            stop,
            _r2(max(0.0, (badge - nm.em_box) / 2.0)),
            fit=(_r2(DOC_PAD + PANEL_PAD), _r2(DOC_PAD + PANEL_PAD + badge)),
        )
        text_inset = _r2(max(0.0, (badge - lm.em_box) / 2.0))
        last, desc = b.place_lines(
            sid, lines, font, blk.size, "start", text_x, "steptext", stop, text_inset,
            fit=(text_x, _r2(doc.width - DOC_PAD - PANEL_PAD)),
        )
        span = _r2(max(badge, text_inset + lm.line_height * len(lines) + desc))
        ys.exactly(stop, f"{sid}:bot", span, f"{tag} step {si} is {span}px tall")
        prev = f"{sid}:bot"

    ys.exactly(prev, f"{bid}:bot", PANEL_PAD, f"{tag} panel keeps {PANEL_PAD}px below its last step")
    return f"{bid}:bot"
