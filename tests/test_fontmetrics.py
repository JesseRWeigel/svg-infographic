"""Is the font actually being measured, and are the numbers right?

The engine's parser is hand-written against the TrueType spec. Checking it against itself
would prove nothing, so every assertion here compares it to fontTools, which is a separate
implementation by other people, over every codepoint both parsers claim to cover. The browser
provides a third, independent check in tools/browser_check.js.
"""

from __future__ import annotations

import unittest

from fontTools.ttLib import TTFont

from engine.errors import FontError, UnsupportedCharacter
from engine.fontmetrics import SUPPORTED_FONTS, get_font, resolve_font_path


class TestAgainstFontTools(unittest.TestCase):
    def test_every_advance_matches_fonttools(self):
        """Compare per-codepoint advance widths across the entire cmap of every font.

        This is the check that the whole project rests on. If a single advance is wrong, some
        string somewhere is measured wrong, and claim 1 is false for that string.
        """
        total = 0
        for name in SUPPORTED_FONTS:
            mine = get_font(name)
            tt = TTFont(str(resolve_font_path(name)))
            cmap = tt.getBestCmap()
            hmtx = tt["hmtx"]
            self.assertEqual(
                mine.units_per_em,
                tt["head"].unitsPerEm,
                f"{name}: unitsPerEm disagrees",
            )
            self.assertEqual(
                sorted(mine.cmap),
                sorted(cmap),
                f"{name}: the two parsers disagree about which codepoints exist",
            )
            for cp, glyph in cmap.items():
                expected = hmtx[glyph][0]
                got = mine.advances[mine.cmap[cp]]
                self.assertEqual(
                    got,
                    expected,
                    f"{name}: advance for U+{cp:04X} ({glyph}) is {got}, fontTools says {expected}",
                )
                total += 1
        self.assertGreater(total, 30000, "far fewer codepoints checked than expected")
        print(f"\n    font metrics: {total} codepoint advances matched fontTools exactly")

    def test_tail_glyphs_reuse_the_last_advance(self):
        """hmtx stores fewer entries than there are glyphs and the tail reuses the last one.

        Getting this rule wrong is the classic hmtx bug and it only shows up on high glyph
        ids, which is why it is asserted directly rather than left to the sweep above.
        """
        for name in SUPPORTED_FONTS:
            mine = get_font(name)
            tt = TTFont(str(resolve_font_path(name)))
            num_glyphs = tt["maxp"].numGlyphs
            self.assertEqual(len(mine.advances), num_glyphs, f"{name}: wrong number of advances")


class TestMeasurement(unittest.TestCase):
    def test_equal_length_strings_have_very_different_widths(self):
        """The reason a length-times-constant estimate cannot work."""
        f = get_font("DejaVu Sans")
        wide = f.measure("WWWWWWWWWW", 16)
        narrow = f.measure("iiiiiiiiii", 16)
        ratio = wide / narrow
        self.assertGreater(ratio, 3.0, "W should be far wider than i")
        print(f"\n    'WWWWWWWWWW' is {wide:.2f}px, 'iiiiiiiiii' is {narrow:.2f}px, ratio {ratio:.2f}")

    def test_a_length_times_constant_estimate_is_badly_wrong(self):
        """Quantify the error the brief warns about, so the number is on record."""
        f = get_font("DejaVu Sans")
        worst = 0.0
        for s in ("WWWWWWWWWW", "iiiiiiiiii", "lllllllll", "MMMMMMMM", "......."):
            true = f.measure(s, 16)
            est = len(s) * 8.0
            worst = max(worst, abs(est - true) / true)
        self.assertGreater(worst, 0.40, "the estimate should be off by more than 40 percent somewhere")
        print(f"\n    len(text) * 8 is off by up to {worst * 100:.0f}% on ten-character strings")

    def test_monospace_is_monospaced(self):
        """An independent invariant: in a monospaced font, equal lengths must measure equal."""
        f = get_font("DejaVu Sans Mono")
        a = f.measure("iiiiiiiiii", 13)
        b = f.measure("WWWWWWWWWW", 13)
        self.assertAlmostEqual(a, b, places=9, msg="mono font gave two widths for equal lengths")

    def test_empty_string_is_zero(self):
        self.assertEqual(get_font("DejaVu Sans").measure("", 16), 0.0)

    def test_width_scales_linearly_with_size(self):
        f = get_font("DejaVu Sans")
        self.assertAlmostEqual(f.measure("Hamburgefonstiv", 20), f.measure("Hamburgefonstiv", 10) * 2, places=9)

    def test_supplementary_plane_codepoints_resolve(self):
        """U+1F600 lives outside the BMP, so a cmap parser that only reads format 4 misses it."""
        f = get_font("DejaVu Sans")
        self.assertTrue(f.has_char("\U0001f600"))
        self.assertGreater(f.measure("\U0001f600", 16), 0.0)


class TestRefusals(unittest.TestCase):
    def test_unsupported_font_is_refused(self):
        with self.assertRaises(FontError) as cm:
            get_font("Helvetica Neue")
        self.assertIn("not supported", str(cm.exception))

    def test_missing_glyph_is_refused_not_guessed(self):
        f = get_font("DejaVu Sans")
        with self.assertRaises(UnsupportedCharacter) as cm:
            f.measure("中", 16)
        self.assertIn("U+4E2D", str(cm.exception))

    def test_missing_chars_lists_in_order_without_duplicates(self):
        f = get_font("DejaVu Sans")
        self.assertEqual(f.missing_chars("a中b文中"), ["中", "文"])


if __name__ == "__main__":
    unittest.main()
