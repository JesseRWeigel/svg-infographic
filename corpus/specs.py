"""The test corpus.

Two lists. ``CORPUS`` holds specs that must lay out, and every text element in every one of
them is measured against its container by tests/test_overflow.py. ``REFUSALS`` holds specs
that must raise, paired with a substring the message has to contain, so a refusal that
happens for the wrong reason still fails the test.

The adversarial cases are the point of the corpus, not decoration:

  narrow-vs-wide      "WWWWWWWWWW" against "iiiiiiiiii" at the same length. A width estimate
                      of len(text) * constant gets these wrong by a factor of three and a
                      half, and a corpus without them cannot tell a real measurement from a
                      fake one.
  unbroken            a 180-character word with no break opportunity, wider than the canvas.
  longer-than-canvas  a string many times the canvas width.
  cjk                 Han and Hiragana, which have no spaces and break per character.
  emoji               U+1F600 and friends, four-byte codepoints that DejaVu Sans does cover
                      as monochrome glyphs, which means the cmap parser has to handle format
                      12 subtables and not just the BMP.
  single-char         one character, and the empty string, which have no interior to wrap.
  tiny-canvas         a 200px canvas, where almost nothing fits.
"""

from __future__ import annotations

from engine.spec import Bar, BarChart, Doc, Kpi, KpiRow, Paragraph, Steps

W = "WWWWWWWWWW"
I = "iiiiiiiiii"
UNBROKEN = "Pneumonoultramicroscopicsilicovolcanoconiosis" * 4
LONG = (
    "This single sentence is deliberately far longer than the canvas it has to fit inside, "
    "so the wrapper has to break it across many lines and every one of those lines has to "
    "come out narrower than the container the constraint solver assigned to it, otherwise "
    "claim one is false and the overflow test says so."
)
CJK = "中文排版没有空格所以必须逐字断行，这一行会被引擎按字符切开。"
JP = "日本語のテキストもスペースがないため、文字単位で改行します。"
EMOJI = "😀 😁 😂 😃 ☺ ☹ ✓ ✗ → ← ↑ ↓ ★ ☆ ♥ ♦ ♠ ♣ ✦ ✧"


def _kpi(*triples):
    return KpiRow(cards=tuple(Kpi(*t) for t in triples))


def _bars(caption, pairs, **kw):
    return BarChart(caption=caption, bars=tuple(Bar(a, b) for a, b in pairs), **kw)


CORPUS: tuple[Doc, ...] = (
    Doc(
        id="c01-hello",
        title="Hello",
        blocks=(Paragraph(text="One short paragraph."),),
    ),
    Doc(
        id="c02-single-char",
        title="A",
        subtitle="B",
        footer="C",
        blocks=(Paragraph(text="D"), _kpi(("E", "F", "G"))),
    ),
    Doc(
        id="c03-empty-strings",
        title="Empty content still has to lay out",
        subtitle="",
        footer="",
        blocks=(Paragraph(text=""), _kpi(("", "", ""))),
    ),
    Doc(
        id="c04-w-vs-i",
        title="WWWWWWWWWW against iiiiiiiiii",
        subtitle="Same character count, three and a half times the width",
        blocks=(
            _bars("Ten characters each", [(W, 10), (I, 10), ("MMMMMMMMMM", 10), ("llllllllll", 10)]),
            _kpi((W, I, W), (I, W, I)),
        ),
    ),
    Doc(
        id="c05-unbroken",
        title="An unbreakable word",
        blocks=(Paragraph(text=UNBROKEN),),
    ),
    Doc(
        id="c06-longer-than-canvas",
        title="A string longer than the whole canvas",
        blocks=(Paragraph(text=LONG),),
    ),
    Doc(
        id="c07-cjk",
        title="中文与日本語の組版",
        subtitle="スペースなし、文字単位で改行",
        font="Droid Sans Fallback",
        blocks=(
            Paragraph(text=CJK),
            Paragraph(text=JP, emphasis=True),
            KpiRow(cards=(Kpi("速度", "十倍", "測定済み"), Kpi("誤差", "零", "測定済み"))),
        ),
    ),
    Doc(
        id="c08-emoji",
        title="Pictographs and symbols",
        blocks=(Paragraph(text=EMOJI), _kpi(("😀", "grin", "U+1F600"), ("★", "star", "U+2605"))),
    ),
    Doc(
        id="c09-tiny-canvas",
        title="Narrow",
        width=200,
        blocks=(Paragraph(text=LONG, size=9),),
    ),
    Doc(
        id="c10-wide-canvas",
        title="A very wide canvas",
        width=1600,
        blocks=(Paragraph(text=LONG), _bars("Wide bars", [("alpha", 1), ("beta", 2), ("gamma", 3)])),
    ),
    Doc(
        id="c11-bars-basic",
        title="Language share",
        subtitle="Lines of code in this repository",
        blocks=(_bars("By language", [("Python", 1840), ("JavaScript", 610), ("Shell", 90), ("HTML", 420)], unit=" LOC"),),
    ),
    Doc(
        id="c12-bars-zero",
        title="Every bar is zero",
        blocks=(_bars("All zero", [("a", 0), ("b", 0), ("c", 0)]),),
    ),
    Doc(
        id="c13-bars-many",
        title="Forty bars",
        blocks=(_bars("Forty", [(f"row {i:02d}", i * 3 + 1) for i in range(40)]),),
    ),
    Doc(
        id="c14-bars-long-labels",
        title="Labels wider than the label column",
        blocks=(
            _bars(
                "Ellipsized",
                [
                    ("A label that is much wider than the label column will ever be", 5),
                    (UNBROKEN[:80], 3),
                    ("short", 8),
                ],
            ),
        ),
    ),
    Doc(
        id="c15-bars-wrapped-labels",
        title="Labels that wrap instead of ellipsizing",
        blocks=(
            BarChart(
                caption="Wrapped labels",
                label_overflow="wrap",
                bars=(
                    Bar("A label that is much wider than the label column will ever be", 5),
                    Bar("another fairly long label for the second row of this chart", 9),
                    Bar("short", 2),
                ),
            ),
        ),
    ),
    Doc(
        id="c16-bars-huge-values",
        title="Large and fractional values",
        blocks=(_bars("Values", [("tiny", 0.01), ("big", 123456789), ("mid", 3.14159)], unit=" u"),),
    ),
    Doc(
        id="c17-kpi-one",
        title="One card",
        blocks=(_kpi(("Total", "1", "since launch")),),
    ),
    Doc(
        id="c18-kpi-eight",
        title="Eight cards",
        width=1200,
        blocks=(_kpi(*[(f"m{i}", str(i * 11), f"note {i}") for i in range(8)]),),
    ),
    Doc(
        id="c19-kpi-uneven",
        title="Cards with very different content lengths",
        blocks=(
            _kpi(
                ("Short", "1", ""),
                ("A label long enough to wrap onto several lines inside its card", "22.5%", "with a note that also wraps"),
                ("Mid", "300", "note"),
            ),
        ),
    ),
    Doc(
        id="c20-kpi-wide-values",
        title="Values that must be ellipsized",
        blocks=(_kpi(("Ratio", "1234567890123456789012345", "too wide"), ("Fine", "42", "")),),
    ),
    Doc(
        id="c21-steps-one",
        title="A single step",
        blocks=(Steps(caption="", items=("Do the thing.",)),),
    ),
    Doc(
        id="c22-steps-many",
        title="Twelve steps",
        blocks=(Steps(caption="Procedure", items=tuple(f"Step number {i} of the procedure, which has a reasonably long description." for i in range(1, 13))),),
    ),
    Doc(
        id="c23-steps-long",
        title="A step with an unbreakable token",
        blocks=(Steps(caption="Watch the wrap", items=("Install " + UNBROKEN[:120] + " and restart.", "Short step.")),),
    ),
    Doc(
        id="c24-para-strict-fits",
        title="Strict overflow that does fit",
        blocks=(Paragraph(text="Short enough.", overflow="strict"),),
    ),
    Doc(
        id="c25-para-ellipsis",
        title="Ellipsis policy",
        blocks=(Paragraph(text=LONG, overflow="ellipsis"),),
    ),
    Doc(
        id="c26-para-newlines",
        title="Hard line breaks",
        blocks=(Paragraph(text="first line\nsecond line\n\nfourth line after a blank one"),),
    ),
    Doc(
        id="c27-para-emphasis",
        title="Emphasised paragraph in a panel",
        blocks=(Paragraph(text=LONG, emphasis=True), Paragraph(text="Plain follow-up.")),
    ),
    Doc(
        id="c28-mixed-dark",
        title="Everything at once, dark",
        subtitle="Every block type in one document",
        footer="Rendered dark. The same spec with theme='light' differs only in colour.",
        theme="dark",
        accent=1,
        blocks=(
            _kpi(("Specs", "34", "in the corpus"), ("Text runs", "1200+", "all measured"), ("Overflows", "0", "")),
            _bars("Phases", [("measure", 12), ("solve", 31), ("render", 6)], unit="ms"),
            Steps(caption="Pipeline", items=("Measure.", "Break.", "Solve.", "Emit.")),
            Paragraph(text="A refusal is a feature.", emphasis=True),
        ),
    ),
    Doc(
        id="c29-mixed-light",
        title="Everything at once, light",
        subtitle="Every block type in one document",
        footer="Rendered light.",
        theme="light",
        accent=2,
        blocks=(
            _kpi(("Specs", "34", "in the corpus"), ("Text runs", "1200+", "all measured"), ("Overflows", "0", "")),
            _bars("Phases", [("measure", 12), ("solve", 31), ("render", 6)], unit="ms"),
            Steps(caption="Pipeline", items=("Measure.", "Break.", "Solve.", "Emit.")),
            Paragraph(text="A refusal is a feature.", emphasis=True),
        ),
    ),
    Doc(
        id="c30-accents",
        title="Accent four",
        accent=4,
        blocks=(_bars("Accent", [("one", 1), ("two", 2)]), Steps(caption="", items=("Numbered badge uses the accent.",))),
    ),
    Doc(
        id="c31-mono",
        title="Monospaced font",
        font="DejaVu Sans Mono",
        blocks=(Paragraph(text="Every glyph in this font has the same advance width, which is a useful control: the measured width of any two equal-length strings must match exactly."), _bars("Mono bars", [("iiii", 4), ("WWWW", 4)])),
    ),
    Doc(
        id="c32-big-title",
        title="A title at 48 point that has to wrap across more than one line inside the canvas",
        title_size=48,
        blocks=(Paragraph(text="Body text follows."),),
    ),
    Doc(
        id="c33-tiny-text",
        title="Four point body text",
        blocks=(Paragraph(text=LONG, size=4),),
    ),
    Doc(
        id="c34-mixed-scripts",
        title="Latin, Cyrillic and Greek together",
        blocks=(
            Paragraph(text="Latin, Кириллица, Ελληνικά, and back to Latin, all in one run."),
            _kpi(("Кириллица", "Да", "yes"), ("Ελληνικά", "Ναι", "yes")),
        ),
    ),
    Doc(
        id="c35-punct-and-spaces",
        title="   leading and trailing spaces   ",
        subtitle="double  spaces   between   words",
        blocks=(Paragraph(text="  a  b  c  "), Paragraph(text="tabs\tand\tmore\ttabs")),
    ),
)


# (spec factory, substring the raised message must contain)
# Each entry is a callable so construction-time refusals are caught too.
REFUSALS: tuple[tuple[str, callable, str], ...] = (
    (
        "strict text wider than its box",
        lambda: Doc(
            id="r01",
            title="Strict",
            blocks=(Paragraph(text=LONG, overflow="strict"),),
        ),
        "overflow policy is 'strict'",
    ),
    (
        "bars squeezed below their minimum track",
        lambda: Doc(
            id="r02",
            title="Squeeze",
            width=200,
            blocks=(
                BarChart(
                    caption="No room",
                    label_overflow="wrap",
                    bars=(Bar("label", 1),),
                    unit=" a very long unit string that eats the whole row",
                ),
            ),
        ),
        "bars need at least",
    ),
    (
        "kpi cards squeezed until one character will not fit",
        lambda: Doc(
            id="r03",
            title="Too many cards",
            width=260,
            blocks=(_kpi(*[(f"label {i}", "0", "") for i in range(8)]),),
        ),
        "needs at least",
    ),
    (
        "font the engine has not measured",
        lambda: Doc(id="r04", title="X", font="Comic Sans MS", blocks=(Paragraph(text="y"),)),
        "not measured by this engine",
    ),
    (
        "character with no glyph in the chosen font",
        lambda: Doc(id="r05", title="中文 in DejaVu Sans", blocks=(Paragraph(text="中文"),)),
        "has no glyph for U+4E2D",
    ),
    (
        "emoji outside the chosen font",
        lambda: Doc(id="r06", title="絵文字", font="Droid Sans Fallback", blocks=(Paragraph(text="😀"),)),
        "has no glyph for U+1F600",
    ),
    (
        "a step number the chosen font has no digit for",
        lambda: Doc(
            id="r13",
            title="手順",
            font="Droid Sans Fallback",
            blocks=(Steps(caption="手順", items=(CJK,)),),
        ),
        "has no glyph for U+0031",
    ),
    (
        "Latin text in a CJK-only font",
        lambda: Doc(id="r14", title="漢字", font="Droid Sans Fallback", blocks=(Paragraph(text="Latin"),)),
        "has no glyph for U+004C",
    ),
    (
        "unknown overflow policy",
        lambda: Doc(id="r07", title="x", blocks=(Paragraph(text="y", overflow="clip"),)),
        "overflow must be one of",
    ),
    (
        "negative bar value",
        lambda: Doc(id="r08", title="x", blocks=(BarChart(caption="c", bars=(Bar("a", -1),)),)),
        "must be >= 0",
    ),
    (
        "no blocks at all",
        lambda: Doc(id="r09", title="x", blocks=()),
        "must not be empty",
    ),
    (
        "canvas narrower than the engine's minimum",
        lambda: Doc(id="r10", title="x", width=100, blocks=(Paragraph(text="y"),)),
        "width must be in",
    ),
    (
        "steps on a canvas with no room beside the badge",
        lambda: Doc(id="r11", title="x", width=160, blocks=(Steps(caption="", items=("a",), size=48),)),
        "for the step text, which must be greater than 0",
    ),
    (
        "unknown theme",
        lambda: Doc(id="r12", title="x", theme="sepia", blocks=(Paragraph(text="y"),)),
        "theme must be one of",
    ),
)


def all_specs() -> tuple[Doc, ...]:
    return CORPUS
