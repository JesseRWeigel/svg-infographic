"""Refusal is a feature.

When the constraints cannot all hold, the engine raises and names the conflict. It never emits
a layout that violates a constraint, because a violated constraint is exactly the thing claims
1 and 2 promise cannot happen.

Every case here checks two things: that it raised, and that the message contains a specific
substring. Without the second half, a refusal for the wrong reason would still pass, and so
would a bare ``raise Exception``.
"""

from __future__ import annotations

import unittest

from corpus.specs import REFUSALS
from engine.errors import Unsatisfiable
from engine.render import render_spec
from engine.solver import System


class TestRefusalCorpus(unittest.TestCase):
    def test_every_unsatisfiable_spec_raises_with_a_description(self):
        for name, make, needle in REFUSALS:
            with self.subTest(case=name):
                try:
                    out = make()
                    svg = render_spec(out)
                except Exception as exc:
                    msg = str(exc)
                    self.assertIn(
                        needle,
                        msg,
                        f"{name}: refused, but the message does not explain the conflict.\n"
                        f"expected to contain {needle!r}, got:\n{msg}",
                    )
                    self.assertGreater(len(msg), 40, f"{name}: message is too terse to act on")
                    continue
                self.fail(f"{name}: no refusal, emitted {len(svg)} bytes of SVG instead")
        print(f"\n    {len(REFUSALS)} unsatisfiable specs all refused with a description")

    def test_refusals_name_more_than_one_constraint_when_a_cycle_is_involved(self):
        """A conflict report that says only "infeasible" is useless.

        For the solver-level refusals the message has to list the chain of constraints that
        contradict each other, so a reader can see which one to relax.
        """
        found = 0
        for name, make, _ in REFUSALS:
            try:
                render_spec(make())
            except Unsatisfiable as exc:
                found += 1
                self.assertGreaterEqual(
                    len(exc.cycle), 2, f"{name}: conflict report lists only {exc.cycle}"
                )
                for line in exc.cycle:
                    self.assertGreater(len(line), 12, f"{name}: unhelpful constraint text {line!r}")
            except Exception:
                pass
        self.assertGreaterEqual(found, 3, "expected several solver-level refusals in the corpus")


class TestSolverDirectly(unittest.TestCase):
    def test_a_satisfiable_system_gets_the_minimal_solution(self):
        s = System("x")
        s.pin("l", 0.0, "left edge")
        s.at_least("l", "a", 8.0, "left padding is at least 8")
        s.at_least("a", "b", 100.0, "content is at least 100 wide")
        sol = s.solve()
        self.assertEqual(sol["l"], 0.0)
        self.assertEqual(sol["a"], 8.0)
        self.assertEqual(sol["b"], 108.0)

    def test_a_positive_cycle_is_reported_with_its_constraints(self):
        s = System("x")
        s.pin("l", 0.0, "left edge at 0")
        s.exactly("l", "r", 100.0, "the box is exactly 100 wide")
        s.at_least("l", "a", 8.0, "left padding is at least 8")
        s.at_least("a", "b", 300.0, "the text is at least 300 wide")
        s.at_least("b", "r", 8.0, "right padding is at least 8")
        with self.assertRaises(Unsatisfiable) as cm:
            s.solve()
        cycle = cm.exception.cycle
        self.assertIn("the text is at least 300 wide", cycle)
        self.assertIn("the box is exactly 100 wide", cycle)
        self.assertIn("x axis", str(cm.exception))

    def test_a_tight_equality_chain_is_not_mistaken_for_a_conflict(self):
        """Equalities are two opposing inequalities, so a naive cycle check flags every one.

        This is the false-positive side of the solver and it needs its own test, otherwise the
        engine would refuse perfectly good specs.
        """
        s = System("y")
        s.pin("t", 0.0, "top")
        prev = "t"
        for i in range(200):
            s.exactly(prev, f"v{i}", 1.37, f"row {i} is exactly 1.37 tall")
            prev = f"v{i}"
        sol = s.solve()
        self.assertAlmostEqual(sol["v199"], 1.37 * 200, places=6)

    def test_an_upper_bound_that_is_satisfiable_is_accepted(self):
        s = System("x")
        s.pin("l", 0.0, "left")
        s.at_least("l", "r", 50.0, "at least 50 wide")
        s.at_most("l", "r", 200.0, "at most 200 wide")
        sol = s.solve()
        self.assertEqual(sol["r"], 50.0)

    def test_contradictory_bounds_are_refused(self):
        s = System("x")
        s.pin("l", 0.0, "left")
        s.at_least("l", "r", 200.0, "at least 200 wide")
        s.at_most("l", "r", 50.0, "at most 50 wide")
        with self.assertRaises(Unsatisfiable) as cm:
            s.solve()
        self.assertIn("at least 200 wide", cm.exception.cycle)
        self.assertIn("at most 50 wide", cm.exception.cycle)


if __name__ == "__main__":
    unittest.main()
