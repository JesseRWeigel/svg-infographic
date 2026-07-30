"""Claim 1: text never overflows its container.

Every text element of every spec in the corpus is re-measured from the emitted SVG with
fontTools and compared against the container rectangle the solver assigned. The negative
control at the bottom exists because a detector that never fires proves nothing.
"""

from __future__ import annotations

import unittest

from corpus.specs import CORPUS
from engine.render import render_spec
from tests import detectors as D


class TestCorpusOverflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = [D.parse(render_spec(s), s.id) for s in CORPUS]

    def test_corpus_is_large_and_varied(self):
        self.assertGreaterEqual(len(CORPUS), 30, "the corpus is smaller than the brief requires")
        ids = [s.id for s in CORPUS]
        self.assertEqual(len(ids), len(set(ids)), "duplicate spec ids")

    def test_no_text_escapes_its_container(self):
        bad = []
        for doc in self.docs:
            bad.extend(D.overflows(doc))
        if bad:
            lines = "\n".join(
                f"  {o.doc}/{o.text_id} {o.role} runs {o.amount:.4f}px past its {o.side} edge: {o.content[:60]!r}"
                for o in bad[:20]
            )
            self.fail(f"{len(bad)} overflow(s) found:\n{lines}")
        n = sum(len(d.texts) for d in self.docs)
        worst, where = min((D.worst_margin(d) for d in self.docs), key=lambda t: t[0])
        trail, twhere = min((D.worst_trailing_margin(d) for d in self.docs), key=lambda t: t[0])
        print(f"\n    {n} text elements across {len(self.docs)} specs, 0 overflows")
        print(f"    worst-case clearance on any edge: {worst:.4f}px  ({where})")
        print(f"    worst-case clearance on a trailing edge: {trail:.4f}px  ({twhere})")

    def test_engine_metrics_agree_with_an_independent_parse(self):
        """The width the engine wrote into the file must be the width fontTools computes.

        Without this an engine could measure correctly, then emit a different number, and the
        container check would compare the right text against the wrong container.
        """
        bad = []
        for doc in self.docs:
            bad.extend(D.metric_disagreements(doc))
        self.assertEqual(bad, [], "engine metrics disagree with fontTools:\n" + "\n".join(bad[:10]))

    def test_adversarial_content_is_present(self):
        """The corpus is only evidence if it contains the cases that break naive engines."""
        blob = "".join(t.content for d in self.docs for t in d.texts)
        self.assertIn("WWWWWWWWWW", blob, "no all-wide string in the corpus")
        self.assertIn("iiiiiiiiii", blob, "no all-narrow string in the corpus")
        self.assertIn("中", blob, "no CJK in the corpus")
        self.assertIn("\U0001f600", blob, "no supplementary-plane emoji in the corpus")
        self.assertTrue(
            any(t.content == "" for d in self.docs for t in d.texts), "no empty string in the corpus"
        )
        self.assertTrue(
            any(len(t.content) == 1 for d in self.docs for t in d.texts), "no single character in the corpus"
        )
        longest = max(len(t.content) for d in self.docs for t in d.texts)
        self.assertGreater(longest, 40, "no long run in the corpus")
        widest_canvas = max(d.width for d in self.docs)
        self.assertGreaterEqual(widest_canvas, 1600, "no wide canvas in the corpus")
        self.assertLessEqual(min(d.width for d in self.docs), 200, "no narrow canvas in the corpus")


_TOO_WIDE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 60" width="300" height="60" data-spec-id="negative-control">
  <rect id="box-b1" x="10" y="10" width="60" height="40" data-content="14 14 52 32"/>
  <text id="n1" x="14" y="34" font-family="DejaVu Sans" font-size="16" font-weight="400" text-anchor="start" data-box="b1" data-role="para" data-measured="52" data-ascent="12.16" data-descent="3.84" data-fit="14 66">This string is far wider than fifty-two pixels.</text>
</svg>
"""

_TOO_TALL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 60" width="300" height="60" data-spec-id="negative-control-v">
  <rect id="box-b1" x="10" y="10" width="280" height="12" data-content="10 10 280 12"/>
  <text id="n1" x="10" y="40" font-family="DejaVu Sans" font-size="16" font-weight="400" text-anchor="start" data-box="b1" data-role="para" data-measured="30" data-ascent="12.16" data-descent="3.84" data-fit="10 290">short</text>
</svg>
"""

_LYING_FIT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 60" width="300" height="60" data-spec-id="negative-control-fit">
  <rect id="box-b1" x="10" y="10" width="60" height="40" data-content="14 14 52 32"/>
  <text id="n1" x="14" y="34" font-family="DejaVu Sans" font-size="16" font-weight="400" text-anchor="start" data-box="b1" data-role="para" data-measured="52" data-ascent="12.16" data-descent="3.84" data-fit="14 900">This string is far wider than fifty-two pixels.</text>
</svg>
"""


class TestOverflowDetectorFires(unittest.TestCase):
    """Negative controls. Text is deliberately placed outside its container.

    Three separate ways of being wrong, because a detector could catch one and miss another:
    too wide, too tall, and a container that claims to be wider than the rectangle it sits in.
    """

    def test_horizontal_overflow_is_reported(self):
        doc = D.parse(_TOO_WIDE)
        found = D.overflows(doc)
        sides = {o.side for o in found}
        self.assertIn("right", sides, f"detector missed a text 300px wide in a 52px box: {found}")
        amount = next(o.amount for o in found if o.side == "right")
        self.assertGreater(amount, 200.0)
        margin, _ = D.worst_margin(doc)
        self.assertLess(margin, -200.0)
        print(f"\n    negative control: detector reported {amount:.1f}px of right overflow")

    def test_vertical_overflow_is_reported(self):
        found = D.overflows(D.parse(_TOO_TALL))
        self.assertIn("bottom", {o.side for o in found}, f"detector missed vertical overflow: {found}")

    def test_a_container_wider_than_its_box_is_reported(self):
        """An engine could hide an overflow by claiming a wider assigned column.

        The checker derives the box from the drawn rectangle, so a data-fit that escapes it is
        itself a violation.
        """
        found = D.overflows(D.parse(_LYING_FIT))
        self.assertIn("fit-outside-box", {o.side for o in found}, f"detector trusted a bogus data-fit: {found}")

    def test_detector_is_silent_on_a_clean_document(self):
        """The other half of a working detector: it does not fire on correct output."""
        doc = D.parse(render_spec(CORPUS[0]), CORPUS[0].id)
        self.assertEqual(D.overflows(doc), [])


if __name__ == "__main__":
    unittest.main()
