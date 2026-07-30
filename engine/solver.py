"""A difference-constraint solver, one axis at a time.

Every geometric relationship this layout engine needs has the form

    v_j - v_i >= w        (j is at least w further along the axis than i)

which covers minimum sizes (right - left >= content width), minimum gaps
(next_left - prev_right >= gap), maximum sizes (rewritten as left - right >= -limit) and
equalities (both directions at once). A system of such constraints is a *difference
constraint system*, and it has a textbook exact solution: build a graph with an edge
i -> j of weight w for each constraint, add a source with a zero edge to every variable,
and compute longest paths with Bellman-Ford. The resulting distances are the
componentwise-minimal solution, and the system is unsatisfiable exactly when the graph has
a positive-weight cycle.

That last property is the reason for choosing this solver over an ad-hoc arithmetic pass.
When the constraints conflict, the cycle *is* the explanation: it is the specific chain of
requirements that contradict each other, and the engine reports it verbatim instead of
emitting a layout that violates something.

Determinism: variables are kept in insertion order, constraints in insertion order, and
relaxation walks that fixed list. No dict iteration order, no randomness, no wall clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import Unsatisfiable

# Slack allowed when checking a constraint for a positive cycle. Constraint weights are
# derived from float text measurements, so an exactly-tight cycle (a == b, b == a) must not
# be mistaken for a conflict because of a 1e-15 residue. One micropixel is far below the
# 0.01px emit precision and far above double rounding error at these magnitudes.
EPS = 1e-6


@dataclass(frozen=True)
class Constraint:
    lo: str  # variable i
    hi: str  # variable j
    weight: float  # require v_hi - v_lo >= weight
    why: str  # human description, used verbatim in a conflict report


class System:
    """A set of variables and difference constraints on one axis."""

    def __init__(self, axis: str):
        self.axis = axis
        self._vars: list[str] = []
        self._index: dict[str, int] = {}
        self._constraints: list[Constraint] = []

    # ---- building -----------------------------------------------------------

    def var(self, name: str) -> str:
        if name not in self._index:
            self._index[name] = len(self._vars)
            self._vars.append(name)
        return name

    def at_least(self, lo: str, hi: str, weight: float, why: str) -> None:
        """v_hi - v_lo >= weight"""
        self.var(lo)
        self.var(hi)
        self._constraints.append(Constraint(lo, hi, float(weight), why))

    def at_most(self, lo: str, hi: str, weight: float, why: str) -> None:
        """v_hi - v_lo <= weight"""
        self.at_least(hi, lo, -float(weight), why)

    def exactly(self, lo: str, hi: str, weight: float, why: str) -> None:
        """v_hi - v_lo == weight"""
        self.at_least(lo, hi, weight, why)
        self.at_least(hi, lo, -weight, why)

    def pin(self, name: str, value: float, why: str) -> None:
        """v_name == value, expressed against the implicit origin variable."""
        self.var(_ORIGIN)
        self.exactly(_ORIGIN, name, value, why)

    @property
    def variables(self) -> tuple[str, ...]:
        return tuple(self._vars)

    @property
    def constraints(self) -> tuple[Constraint, ...]:
        return tuple(self._constraints)

    # ---- solving ------------------------------------------------------------

    def solve(self) -> dict[str, float]:
        """Return the minimal assignment, or raise Unsatisfiable with the conflict cycle."""
        self.var(_ORIGIN)
        n = len(self._vars)
        idx = self._index
        edges = [
            (idx[c.lo], idx[c.hi], c.weight, k)
            for k, c in enumerate(self._constraints)
        ]
        origin = idx[_ORIGIN]

        # Longest paths from the origin. Every variable starts reachable at 0, which encodes
        # "v >= origin" and makes the solution the minimal nonnegative one.
        dist = [0.0] * n
        pred_edge: list[int] = [-1] * n

        changed_edge = -1
        for it in range(n):
            changed_edge = -1
            for u, v, w, k in edges:
                if dist[u] + w > dist[v] + EPS:
                    dist[v] = dist[u] + w
                    pred_edge[v] = k
                    changed_edge = k
            if changed_edge < 0:
                break

        if changed_edge >= 0:
            raise Unsatisfiable(self.axis, self._extract_cycle(changed_edge, pred_edge))

        base = dist[origin]
        return {name: dist[idx[name]] - base for name in self._vars if name != _ORIGIN}

    def _extract_cycle(self, seed_edge: int, pred_edge: list[int]) -> list[str]:
        """Walk predecessors back from a still-relaxable edge to name the positive cycle.

        After n passes any edge that still relaxes is reachable from a positive cycle, and
        walking predecessors n times lands inside it. The walk is then closed to produce the
        cycle in forward order.
        """
        idx = self._index
        node = idx[self._constraints[seed_edge].hi]
        for _ in range(len(self._vars)):
            k = pred_edge[node]
            if k < 0:
                break
            node = idx[self._constraints[k].lo]

        cycle_edges: list[int] = []
        seen: set[int] = set()
        cur = node
        while cur not in seen:
            seen.add(cur)
            k = pred_edge[cur]
            if k < 0:
                break
            cycle_edges.append(k)
            cur = idx[self._constraints[k].lo]

        if not cycle_edges:
            cycle_edges = [seed_edge]
        descriptions = [self._constraints[k].why for k in reversed(cycle_edges)]
        # Deduplicate consecutive repeats so the report reads cleanly without losing any
        # distinct constraint.
        out: list[str] = []
        for d in descriptions:
            if not out or out[-1] != d:
                out.append(d)
        return out


_ORIGIN = "@origin"
