"""Claim 2: no two labels collide.

Collision is tested on em boxes rather than on glyph ink. The em box of a run is its measured
advance width by its ascent-plus-descent height, which is larger than the ink, so two runs
whose em boxes are clear of each other cannot have touching glyphs either. Ink boxes would be
the weaker claim and the easier one to pass.

Empty runs are excluded. A string with no characters draws nothing, has zero width, and two of
them at the same coordinate is not a collision anyone can see.
"""

from __future__ import annotations

import unittest

from corpus.specs import CORPUS
from engine.render import render_spec
from tests import detectors as D


class TestCorpusCollisions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = [D.parse(render_spec(s), s.id) for s in CORPUS]

    def test_no_two_labels_intersect(self):
        bad = []
        for doc in self.docs:
            for a, b, sep in D.collisions(doc):
                bad.append(f"  {doc.id}: {a} and {b} overlap, separation {sep:.4f}px")
        self.assertEqual(bad, [], f"{len(bad)} collision(s):\n" + "\n".join(bad[:20]))
        sep, where = min((D.min_separation(d) for d in self.docs), key=lambda t: t[0])
        pairs = sum(
            len([t for t in d.texts if t.content.strip()]) * (len([t for t in d.texts if t.content.strip()]) - 1) // 2
            for d in self.docs
        )
        print(f"\n    {pairs} label pairs checked, 0 intersections")
        print(f"    minimum label separation: {sep:.4f}px  ({where})")
        self.assertGreater(sep, 0.0, "labels touch somewhere in the corpus")

    def test_separation_is_symmetric(self):
        doc = self.docs[-1]
        runs = [t for t in doc.texts if t.content.strip()][:12]
        for i in range(len(runs)):
            for j in range(len(runs)):
                self.assertAlmostEqual(
                    D.separation(runs[i], runs[j]), D.separation(runs[j], runs[i]), places=9
                )


_SAME_SPOT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 60" width="300" height="60" data-spec-id="collision-control">
  <rect id="box-b1" x="0" y="0" width="300" height="60" data-content="0 0 300 60"/>
  <text id="a" x="20" y="30" font-family="DejaVu Sans" font-size="14" font-weight="400" text-anchor="start" data-box="b1" data-role="para" data-measured="40" data-ascent="10.64" data-descent="3.36" data-fit="0 300">first</text>
  <text id="b" x="20" y="30" font-family="DejaVu Sans" font-size="14" font-weight="400" text-anchor="start" data-box="b1" data-role="para" data-measured="45" data-ascent="10.64" data-descent="3.36" data-fit="0 300">second</text>
</svg>
"""

_PARTIAL_LAP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 60" width="300" height="60" data-spec-id="collision-control-2">
  <rect id="box-b1" x="0" y="0" width="300" height="60" data-content="0 0 300 60"/>
  <text id="a" x="20" y="30" font-family="DejaVu Sans" font-size="14" font-weight="400" text-anchor="start" data-box="b1" data-role="para" data-measured="60" data-ascent="10.64" data-descent="3.36" data-fit="0 300">overlapping</text>
  <text id="b" x="60" y="35" font-family="DejaVu Sans" font-size="14" font-weight="400" text-anchor="start" data-box="b1" data-role="para" data-measured="60" data-ascent="10.64" data-descent="3.36" data-fit="0 300">overlapping</text>
</svg>
"""

_EXACTLY_TOUCHING = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 60" width="400" height="60" data-spec-id="collision-control-3">
  <rect id="box-b1" x="0" y="0" width="400" height="60" data-content="0 0 400 60"/>
  <text id="a" x="0" y="30" font-family="DejaVu Sans" font-size="14" font-weight="400" text-anchor="start" data-box="b1" data-role="para" data-measured="0" data-ascent="10.64" data-descent="3.36" data-fit="0 400">iiiii</text>
  <text id="b" x="19.4482421875" y="30" font-family="DejaVu Sans" font-size="14" font-weight="400" text-anchor="start" data-box="b1" data-role="para" data-measured="0" data-ascent="10.64" data-descent="3.36" data-fit="0 400">iiiii</text>
</svg>
"""


class TestCollisionDetectorFires(unittest.TestCase):
    """Negative controls: labels are forced to overlap and the detector must say so."""

    def test_identical_coordinates_are_reported(self):
        doc = D.parse(_SAME_SPOT)
        found = D.collisions(doc)
        self.assertEqual(len(found), 1, f"detector missed two labels at the same point: {found}")
        sep, _ = D.min_separation(doc)
        self.assertLess(sep, 0.0)
        print(f"\n    negative control: two labels at one point reported, separation {sep:.4f}px")

    def test_partial_overlap_is_reported(self):
        found = D.collisions(D.parse(_PARTIAL_LAP))
        self.assertEqual(len(found), 1, f"detector missed a partial overlap: {found}")

    def test_edges_that_exactly_touch_count_as_a_collision(self):
        """Zero separation is a collision, not a pass.

        The second run starts exactly where the first ends, to the width of five 'i' glyphs at
        14px. A detector using a strictly-less-than test would let this through, and touching
        em boxes are the boundary case that a rounding bug lands on.
        """
        doc = D.parse(_EXACTLY_TOUCHING)
        found = D.collisions(doc)
        self.assertEqual(len(found), 1, f"exactly touching labels were not reported: {found}")
        self.assertAlmostEqual(found[0][2], 0.0, places=6)

    def test_detector_is_silent_on_a_clean_document(self):
        doc = D.parse(render_spec(CORPUS[-1]), CORPUS[-1].id)
        self.assertEqual(D.collisions(doc), [])


if __name__ == "__main__":
    unittest.main()
