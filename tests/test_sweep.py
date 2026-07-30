"""A property sweep, not a fixed corpus.

The corpus catches the cases someone thought of. This sweeps a continuous parameter instead and
asserts the only invariant that matters: for every input, the engine either produces a layout
with no overflow and no collision, or it refuses. There is no third outcome.

Rounding bugs live here. A share of available space that rounds the wrong way overruns its row
at some widths and not others, so a test at one width passes while the engine is broken at the
next pixel.
"""

from __future__ import annotations

import unittest

from engine.errors import SpecError, Unsatisfiable
from engine.render import render_spec
from engine.spec import Bar, BarChart, Doc, Kpi, KpiRow, Paragraph, Steps
from tests import detectors as D

PROSE = (
    "Some prose long enough that it has to wrap at every width in this sweep, including the "
    "narrow ones where only a word or two fits on a line."
)


def _doc(width: float, cards: int) -> Doc:
    return Doc(
        id=f"sweep-{width:.0f}-{cards}",
        title="Width sweep",
        subtitle="Every width from 160 to 1400",
        footer="No width may silently overflow.",
        width=width,
        blocks=(
            KpiRow(cards=tuple(Kpi(f"card {i}", str(i * 7), "note") for i in range(cards))),
            BarChart(caption="Bars", unit="ms", bars=(Bar("alpha", 3), Bar("beta", 8), Bar("a much longer label", 5))),
            Steps(caption="Steps", items=("First step here.", "Second step, a little longer than the first.")),
            Paragraph(text=PROSE),
        ),
    )


class TestWidthSweep(unittest.TestCase):
    def test_every_width_either_lays_out_cleanly_or_refuses(self):
        laid_out = 0
        refused = 0
        worst = float("inf")
        worst_where = ""
        min_sep = float("inf")
        sep_where = ""
        checked_texts = 0
        for width in range(160, 1401, 7):
            for cards in (1, 3, 5):
                try:
                    svg = render_spec(_doc(float(width), cards))
                except (Unsatisfiable, SpecError) as exc:
                    refused += 1
                    self.assertGreater(len(str(exc)), 40, f"width {width}: refusal without a reason")
                    continue
                doc = D.parse(svg, f"sweep-{width}-{cards}")
                checked_texts += len(doc.texts)
                over = D.overflows(doc)
                self.assertEqual(
                    over,
                    [],
                    f"width {width} with {cards} cards overflowed: "
                    + "; ".join(f"{o.role} {o.side} by {o.amount:.3f}px {o.content[:30]!r}" for o in over[:4]),
                )
                coll = D.collisions(doc)
                self.assertEqual(coll, [], f"width {width} with {cards} cards collided: {coll[:3]}")
                m, where = D.worst_margin(doc)
                if m < worst:
                    worst, worst_where = m, where
                s, sw = D.min_separation(doc)
                if s < min_sep:
                    min_sep, sep_where = s, sw
                laid_out += 1
        self.assertGreater(laid_out, 300, "the sweep laid out suspiciously few documents")
        self.assertGreater(refused, 0, "no width refused, so the refusal path is untested here")
        print(
            f"\n    width sweep: {laid_out} layouts ({checked_texts} text elements), "
            f"{refused} refusals, 0 overflows, 0 collisions"
        )
        print(f"    sweep worst clearance {worst:.4f}px ({worst_where})")
        print(f"    sweep minimum separation {min_sep:.4f}px ({sep_where})")

    def test_font_size_sweep(self):
        """The other continuous parameter. Line height, ascent and descent all scale with it."""
        clean = 0
        for size_tenths in range(40, 481, 11):
            size = size_tenths / 10.0
            spec = Doc(
                id=f"size-{size_tenths}",
                title="Size sweep",
                blocks=(Paragraph(text=PROSE, size=size), Steps(caption="", items=("A step.",), size=min(size, 48.0))),
            )
            try:
                doc = D.parse(render_spec(spec), spec.id)
            except (Unsatisfiable, SpecError):
                continue
            self.assertEqual(D.overflows(doc), [], f"size {size} overflowed")
            self.assertEqual(D.collisions(doc), [], f"size {size} collided")
            clean += 1
        self.assertGreater(clean, 30, "font size sweep covered too few sizes")
        print(f"    font size sweep: {clean} sizes from 4.0 to 48.0px, 0 overflows, 0 collisions")


if __name__ == "__main__":
    unittest.main()
