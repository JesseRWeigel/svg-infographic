"""Claim 3: the same spec always renders identically, byte for byte.

Four things are checked, and the second and third are what stop the test from passing on a
renderer that emits a constant:

  1. rendering one spec 100 times gives 100 identical byte strings
  2. every spec in the corpus gives a distinct byte string from every other
  3. a spec that differs in one field gives different output
  4. a fresh interpreter, with hash randomisation left on, produces the same bytes

Point 4 matters because PYTHONHASHSEED varies per process by default. A renderer that iterates
a set or a dict keyed by strings can be perfectly repeatable inside one process and unstable
across runs, which is the failure mode users actually hit.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from corpus.specs import CORPUS
from engine.render import render_spec
from engine.spec import doc_from_json, doc_to_json

ROOT = Path(__file__).resolve().parent.parent


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class TestDeterminism(unittest.TestCase):
    def test_one_hundred_renders_are_byte_identical(self):
        spec = CORPUS[27]
        first = render_spec(spec)
        for i in range(1, 100):
            again = render_spec(spec)
            self.assertEqual(
                again,
                first,
                f"render {i} of {spec.id} differs from render 0 "
                f"({sha(again)[:12]} vs {sha(first)[:12]})",
            )
        print(f"\n    100 renders of {spec.id}: sha256 {sha(first)[:16]}, all identical")

    def test_every_corpus_spec_renders_once_and_the_same_way(self):
        seen: dict[str, str] = {}
        for spec in CORPUS:
            a = render_spec(spec)
            b = render_spec(spec)
            self.assertEqual(a, b, f"{spec.id} is not repeatable")
            digest = sha(a)
            self.assertNotIn(
                digest,
                seen,
                f"{spec.id} and {seen.get(digest)} produced identical bytes, so this test "
                f"could be passed by a renderer that ignores its input",
            )
            seen[digest] = spec.id
        print(f"    {len(seen)} corpus specs produced {len(seen)} distinct outputs")

    def test_a_one_field_change_changes_the_output(self):
        # The base has to contain every block type, because a field can be legitimately
        # invisible in a document that has nothing it applies to. Changing ``accent`` on a spec
        # with no bars and no step badges really does produce identical bytes, and that is
        # correct rather than a determinism bug.
        base = next(s for s in CORPUS if s.id == "c29-mixed-light")
        variants = [
            replace(base, title=base.title + "."),
            replace(base, width=base.width + 1),
            replace(base, theme="dark"),
            replace(base, accent=3),
            replace(base, title_size=base.title_size + 1),
            replace(base, subtitle="added"),
            replace(base, footer="added"),
        ]
        base_out = render_spec(base)
        for v in variants:
            self.assertNotEqual(render_spec(v), base_out, "a changed field left the output identical")

    def test_output_contains_no_timestamp_or_absolute_path(self):
        """A version string or a build date would be a per-run difference waiting to happen."""
        blob = "".join(render_spec(s) for s in CORPUS)
        home = os.environ.get("HOME", "/home")
        self.assertNotIn(home, blob, "an absolute home path leaked into the SVG")
        self.assertNotIn("/usr/share/fonts", blob, "a font file path leaked into the SVG")
        for token in ("20" + "25-", "20" + "26-", "GMT", "UTC"):
            self.assertNotIn(token, blob, f"{token!r} looks like a timestamp in the output")

    def test_a_fresh_process_with_a_different_hash_seed_matches(self):
        """Cross-process determinism, which is the only kind users see.

        Two child processes are run with different PYTHONHASHSEED values. If any code path
        depends on set or dict ordering of strings, the two disagree.
        """
        script = (
            "import hashlib,sys;sys.path.insert(0,'.');"
            "from corpus.specs import CORPUS;from engine.render import render_spec;"
            "print(hashlib.sha256(''.join(render_spec(s) for s in CORPUS).encode()).hexdigest())"
        )
        digests = []
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            p = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True
            )
            self.assertEqual(p.returncode, 0, f"child process failed:\n{p.stderr}")
            digests.append(p.stdout.strip())
        self.assertEqual(
            len(set(digests)), 1, f"hash seed changed the output: {digests}"
        )
        print(f"    PYTHONHASHSEED 0 / 1 / 12345 all gave sha256 {digests[0][:16]}")

    def test_json_round_trip_preserves_the_render(self):
        """The docs page edits a spec as JSON, so the round trip has to be exact."""
        for spec in CORPUS:
            again = doc_from_json(json.loads(json.dumps(doc_to_json(spec))))
            self.assertEqual(
                render_spec(again), render_spec(spec), f"{spec.id} did not survive a JSON round trip"
            )

    def test_coordinates_are_rounded_to_two_decimals(self):
        """Unbounded float formatting is the usual way platform differences get in."""
        import re

        blob = "".join(render_spec(s) for s in CORPUS)
        for m in re.finditer(r'(?:x|y|width|height|rx)="(-?\d+(?:\.\d+)?)"', blob):
            frac = m.group(1).split(".")
            if len(frac) == 2:
                self.assertLessEqual(
                    len(frac[1]), 2, f"coordinate {m.group(1)} has more than two decimals"
                )
        self.assertNotIn("e-0", blob, "scientific notation in the output")


if __name__ == "__main__":
    unittest.main()
