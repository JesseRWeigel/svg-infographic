#!/usr/bin/env python3
"""Print the headline numbers, one per line, from the emitted SVGs.

Kept separate from the test suite so verify.sh can print the figures whether or not the tests
are chatty, and so the same numbers can be pasted into the README without hand-copying.

Exit status is 1 if any claim is violated, so this is a check and not only a report.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus.specs import CORPUS, REFUSALS  # noqa: E402
from engine.render import render_spec  # noqa: E402
from tests import detectors as D  # noqa: E402


def main() -> int:
    docs = [D.parse(render_spec(s), s.id) for s in CORPUS]
    texts = sum(len(d.texts) for d in docs)
    drawn = sum(len([t for t in d.texts if t.content.strip()]) for d in docs)
    boxes = sum(len(d.boxes) for d in docs)
    overflows = [o for d in docs for o in D.overflows(d)]
    collisions = [c for d in docs for c in D.collisions(d)]
    disagreements = [x for d in docs for x in D.metric_disagreements(d)]
    worst, worst_where = min((D.worst_margin(d) for d in docs), key=lambda t: t[0])
    trail, trail_where = min((D.worst_trailing_margin(d) for d in docs), key=lambda t: t[0])
    sep, sep_where = min((D.min_separation(d) for d in docs), key=lambda t: t[0])
    pairs = sum(
        (lambda n: n * (n - 1) // 2)(len([t for t in d.texts if t.content.strip()])) for d in docs
    )

    hist = [D.margin_histogram(d) for d in docs]
    outside = sum(h[0] for h in hist)
    flush = sum(h[1] for h in hist)
    smallest_pos = min(h[2] for h in hist)

    print(f"specs rendered                     {len(docs)}")
    print(f"containers assigned by the solver  {boxes}")
    print(f"text elements measured             {texts} ({drawn} with ink)")
    print(f"label pairs compared               {pairs}")
    print(f"refusal cases                      {len(REFUSALS)}")
    print(f"engine vs fontTools disagreements  {len(disagreements)}")
    print()
    print(f"CLAIM 1  overflowing elements      {len(overflows)} of {texts}")
    print(f"CLAIM 1  worst-case margin         {worst:+.4f} px  ({worst_where})")
    print(f"CLAIM 1  worst trailing-edge margin {trail:+.4f} px  ({trail_where})")
    print(f"CLAIM 1  container edges checked   {4 * texts}")
    print(f"CLAIM 1    edges outside container {outside}")
    print(f"CLAIM 1    edges exactly flush     {flush}  (container sized to its content)")
    print(f"CLAIM 1    smallest positive gap   {smallest_pos:+.4f} px")
    print()
    print(f"CLAIM 2  intersecting label pairs  {len(collisions)} of {pairs}")
    print(f"CLAIM 2  minimum label separation  {sep:+.4f} px  ({sep_where})")

    bad = 0
    if overflows:
        bad = 1
        print("\nFAIL: text outside its container")
        for o in overflows[:10]:
            print(f"  {o.doc}/{o.text_id} {o.role} {o.side} by {o.amount:.4f}px: {o.content[:50]!r}")
    if collisions:
        bad = 1
        print("\nFAIL: labels intersect")
        for a, b, s in collisions[:10]:
            print(f"  {a} and {b} separated by {s:.4f}px")
    if disagreements:
        bad = 1
        print("\nFAIL: the engine's numbers disagree with an independent parse")
        for x in disagreements[:10]:
            print(f"  {x}")
    if worst < -D.TOL:
        bad = 1
        print(f"\nFAIL: worst-case margin {worst:.4f}px is outside the {D.TOL}px rounding tolerance")
    if sep <= 0:
        bad = 1
        print(f"\nFAIL: minimum label separation {sep:.4f}px is not positive")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
