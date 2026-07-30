"""Text measurement by reading the font file.

SVG has no text layout. You write ``<text x="10" y="20">hello</text>`` and the renderer
decides how wide that is. A layout engine that wants to guarantee text fits its box must
therefore compute the same number the renderer will compute, which means reading the
font's own metrics.

This module parses TrueType/OpenType directly with ``struct``. It reads:

  head  unitsPerEm, the scale that turns font units into em fractions
  maxp  numGlyphs
  hhea  numberOfHMetrics, how many entries the hmtx table actually stores
  hmtx  per-glyph advance width in font units
  cmap  codepoint to glyph id, subtable formats 4 and 12
  OS/2  typographic ascender/descender/lineGap, for line height
  name  the family name, so the emitted SVG can name the font it was measured against

Advance width is the correct quantity. It is how far the pen moves after drawing a glyph,
which is what determines the length of a run of text. Bounding-box width (xMax - xMin from
``glyf``) is a different and wrong number: it excludes side bearings, so summing it
underestimates, and for a space glyph it is zero.

What this deliberately does not do:

  Kerning. DejaVu Sans carries both a legacy ``kern`` table and GPOS kern pairs, and a
  browser applies them by default. Rather than reimplement GPOS, the renderer emits
  ``font-kerning="none"`` and ``font-variant-ligatures="none"`` on every text element so
  that the rendered advance is exactly the sum of hmtx advances. tests/test_fontmetrics.py
  checks that assumption against a real browser, so if it were wrong the suite would fail
  rather than the guarantee quietly weakening.

  Bidi and complex shaping. Arabic, Devanagari and friends need a shaping engine. Any
  codepoint whose script needs reordering or contextual forms is out of scope, and the
  supported set is documented in the README.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

from .errors import FontError, UnsupportedCharacter

# Fonts this engine will lay out text in. Nothing else is accepted: a width table for one
# font applied to another font is a guess, and the whole point is to not guess.
#
# Paths are searched in order. FONT_SEARCH_PATH (colon separated) is prepended if set, so
# the engine works on a machine that keeps its fonts somewhere else.
_FONT_FILES: dict[str, tuple[str, ...]] = {
    "DejaVu Sans": ("dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"),
    "DejaVu Sans Bold": ("dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"),
    "DejaVu Sans Mono": ("dejavu/DejaVuSansMono.ttf", "DejaVuSansMono.ttf"),
    "Droid Sans Fallback": (
        "droid/DroidSansFallbackFull.ttf",
        "DroidSansFallbackFull.ttf",
    ),
}

_SEARCH_ROOTS: tuple[str, ...] = (
    "/usr/share/fonts/truetype",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "/Library/Fonts",
    "/System/Library/Fonts",
)

SUPPORTED_FONTS: tuple[str, ...] = tuple(sorted(_FONT_FILES))


def _roots() -> list[Path]:
    extra = os.environ.get("FONT_SEARCH_PATH", "")
    roots = [Path(p) for p in extra.split(":") if p]
    roots += [Path(p) for p in _SEARCH_ROOTS]
    return roots


def resolve_font_path(name: str) -> Path:
    if name not in _FONT_FILES:
        raise FontError(
            f"font {name!r} is not supported. This engine measures text from real font "
            f"metrics and refuses to lay out a font it has not measured. Supported: "
            f"{', '.join(SUPPORTED_FONTS)}."
        )
    tried = []
    for root in _roots():
        for rel in _FONT_FILES[name]:
            cand = root / rel
            tried.append(str(cand))
            if cand.is_file():
                return cand
    raise FontError(
        f"font {name!r} is supported but its file was not found on this machine. "
        f"Looked in:\n  " + "\n  ".join(tried[:8]) + "\n"
        f"Set FONT_SEARCH_PATH to a directory containing it."
    )


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from(">H", b, o)[0]


def _s16(b: bytes, o: int) -> int:
    return struct.unpack_from(">h", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def _parse_table_directory(data: bytes) -> dict[str, tuple[int, int]]:
    if len(data) < 12:
        raise FontError("font file is too short to hold a table directory")
    tag = data[:4]
    if tag == b"ttcf":
        raise FontError("TrueType collections (.ttc) are not supported")
    if tag not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
        raise FontError(f"unrecognised sfnt version {tag!r}")
    num_tables = _u16(data, 4)
    tables: dict[str, tuple[int, int]] = {}
    for i in range(num_tables):
        off = 12 + i * 16
        name = data[off : off + 4].decode("latin-1")
        toff = _u32(data, off + 8)
        tlen = _u32(data, off + 12)
        tables[name] = (toff, tlen)
    return tables


def _parse_cmap_format4(data: bytes, base: int) -> dict[int, int]:
    seg_x2 = _u16(data, base + 6)
    seg = seg_x2 // 2
    ends = base + 14
    starts = ends + seg_x2 + 2
    deltas = starts + seg_x2
    ranges = deltas + seg_x2
    out: dict[int, int] = {}
    for i in range(seg):
        end = _u16(data, ends + i * 2)
        start = _u16(data, starts + i * 2)
        delta = _s16(data, deltas + i * 2)
        range_off = _u16(data, ranges + i * 2)
        if start > end:
            continue
        for cp in range(start, end + 1):
            if cp == 0xFFFF:
                continue
            if range_off == 0:
                gid = (cp + delta) & 0xFFFF
            else:
                gi = ranges + i * 2 + range_off + (cp - start) * 2
                if gi + 1 >= len(data):
                    continue
                gid = _u16(data, gi)
                if gid != 0:
                    gid = (gid + delta) & 0xFFFF
            if gid:
                out[cp] = gid
    return out


def _parse_cmap_format12(data: bytes, base: int) -> dict[int, int]:
    n_groups = _u32(data, base + 12)
    out: dict[int, int] = {}
    for i in range(n_groups):
        off = base + 16 + i * 12
        start = _u32(data, off)
        end = _u32(data, off + 4)
        gid = _u32(data, off + 8)
        if end - start > 0x20000:
            # A pathological group would blow up memory. Real fonts do not have one.
            raise FontError(f"cmap format 12 group spans {end - start} codepoints")
        for k in range(end - start + 1):
            out[start + k] = gid + k
    return out


def _parse_cmap_format6(data: bytes, base: int) -> dict[int, int]:
    first = _u16(data, base + 6)
    count = _u16(data, base + 8)
    return {
        first + i: _u16(data, base + 10 + i * 2)
        for i in range(count)
        if _u16(data, base + 10 + i * 2)
    }


def _parse_cmap(data: bytes, off: int) -> dict[int, int]:
    """Merge the usable Unicode subtables, preferring wider coverage.

    Preference order below is by (platform, encoding). A format 12 table covers the
    supplementary planes and a format 4 table does not, so when both exist the format 12
    entries win. Iteration is over a sorted, explicit list, so the result does not depend
    on dict ordering anywhere.
    """
    n = _u16(data, off + 2)
    subtables = []
    for i in range(n):
        rec = off + 4 + i * 8
        plat = _u16(data, rec)
        enc = _u16(data, rec + 2)
        sub_off = off + _u32(data, rec + 4)
        fmt = _u16(data, sub_off)
        subtables.append((plat, enc, fmt, sub_off))
    subtables.sort()

    def rank(plat: int, enc: int, fmt: int) -> int:
        if (plat, enc) == (3, 10) or (plat, enc) == (0, 4) or (plat, enc) == (0, 6):
            return 3  # full Unicode
        if (plat, enc) in ((3, 1), (0, 3)):
            return 2  # BMP
        if plat == 0:
            return 1
        return 0

    merged: dict[int, int] = {}
    for plat, enc, fmt, sub_off in sorted(
        subtables, key=lambda t: (rank(t[0], t[1], t[2]), t[2], t[0], t[1])
    ):
        if rank(plat, enc, fmt) == 0:
            continue
        if fmt == 4:
            merged.update(_parse_cmap_format4(data, sub_off))
        elif fmt == 12:
            merged.update(_parse_cmap_format12(data, sub_off))
        elif fmt == 6:
            merged.update(_parse_cmap_format6(data, sub_off))
    if not merged:
        raise FontError("font has no usable Unicode cmap subtable")
    return merged


def _parse_name(data: bytes, off: int) -> str:
    count = _u16(data, off + 2)
    string_off = off + _u16(data, off + 4)
    best = ""
    for i in range(count):
        rec = off + 6 + i * 12
        plat = _u16(data, rec)
        enc = _u16(data, rec + 2)
        name_id = _u16(data, rec + 6)
        length = _u16(data, rec + 8)
        s_off = _u16(data, rec + 10)
        if name_id != 1:
            continue
        raw = data[string_off + s_off : string_off + s_off + length]
        try:
            if plat == 3 or (plat == 0 and enc in (3, 4, 6)):
                val = raw.decode("utf-16-be")
            else:
                val = raw.decode("latin-1")
        except UnicodeDecodeError:
            continue
        if plat == 3:
            return val
        best = best or val
    return best


@dataclass(frozen=True)
class Font:
    """A parsed font, able to measure a string in px at a given size."""

    name: str
    path: str
    units_per_em: int
    ascender: int
    descender: int
    line_gap: int
    advances: tuple[int, ...]  # per glyph id, font units
    cmap: dict[int, int]
    family_from_file: str

    # ---- glyph lookup -------------------------------------------------------

    def has_char(self, ch: str) -> bool:
        return ord(ch) in self.cmap

    def missing_chars(self, text: str) -> list[str]:
        """Characters with no glyph, in first-appearance order, deduplicated."""
        seen: dict[str, None] = {}
        for ch in text:
            if ch in ("\n", "\t"):
                continue
            if ord(ch) not in self.cmap and ch not in seen:
                seen[ch] = None
        return list(seen)

    def advance_units(self, ch: str) -> int:
        cp = ord(ch)
        gid = self.cmap.get(cp)
        if gid is None:
            raise UnsupportedCharacter(ch, cp, self.name, ch)
        if gid >= len(self.advances):
            raise FontError(f"glyph {gid} is outside hmtx for {self.name!r}")
        return self.advances[gid]

    # ---- measurement --------------------------------------------------------

    def measure(self, text: str, size: float) -> float:
        """Width in px of ``text`` set at ``size`` px, unkerned.

        Integer font units are summed first and scaled once at the end, so the result does
        not accumulate float error and is identical on any platform with IEEE doubles.
        """
        total = 0
        missing = self.missing_chars(text)
        if missing:
            ch = missing[0]
            raise UnsupportedCharacter(ch, ord(ch), self.name, text)
        for ch in text:
            total += self.advance_units(ch)
        return total * size / self.units_per_em

    def measure_units(self, text: str) -> int:
        return sum(self.advance_units(ch) for ch in text)

    def ascent_px(self, size: float) -> float:
        return self.ascender * size / self.units_per_em

    def descent_px(self, size: float) -> float:
        return abs(self.descender) * size / self.units_per_em

    def natural_line_height(self, size: float) -> float:
        return (
            (self.ascender + abs(self.descender) + self.line_gap)
            * size
            / self.units_per_em
        )


def _load(path: Path, name: str) -> Font:
    data = path.read_bytes()
    tables = _parse_table_directory(data)
    for required in ("head", "hhea", "hmtx", "maxp", "cmap"):
        if required not in tables:
            raise FontError(f"{path.name} is missing the {required!r} table")

    head_off = tables["head"][0]
    units_per_em = _u16(data, head_off + 18)
    if units_per_em == 0:
        raise FontError("unitsPerEm is zero")

    maxp_off = tables["maxp"][0]
    num_glyphs = _u16(data, maxp_off + 4)

    hhea_off = tables["hhea"][0]
    hhea_ascender = _s16(data, hhea_off + 4)
    hhea_descender = _s16(data, hhea_off + 6)
    hhea_line_gap = _s16(data, hhea_off + 8)
    num_h_metrics = _u16(data, hhea_off + 34)
    if num_h_metrics == 0:
        raise FontError("numberOfHMetrics is zero")

    ascender, descender, line_gap = hhea_ascender, hhea_descender, hhea_line_gap
    if "OS/2" in tables:
        os2_off = tables["OS/2"][0]
        version = _u16(data, os2_off)
        if version >= 0:
            typo_asc = _s16(data, os2_off + 68)
            typo_desc = _s16(data, os2_off + 70)
            typo_gap = _s16(data, os2_off + 72)
            if typo_asc > 0:
                ascender, descender, line_gap = typo_asc, typo_desc, typo_gap

    # hmtx stores numberOfHMetrics (advance, lsb) pairs, then monospaced tail glyphs that
    # all reuse the last advance. Missing that tail rule is the classic hmtx bug.
    hmtx_off, hmtx_len = tables["hmtx"]
    advances: list[int] = []
    for i in range(num_h_metrics):
        o = hmtx_off + i * 4
        if o + 2 > hmtx_off + hmtx_len:
            raise FontError("hmtx table is shorter than numberOfHMetrics implies")
        advances.append(_u16(data, o))
    last = advances[-1]
    advances.extend([last] * max(0, num_glyphs - num_h_metrics))

    cmap = _parse_cmap(data, tables["cmap"][0])
    family = _parse_name(data, tables["name"][0]) if "name" in tables else ""

    return Font(
        name=name,
        path=str(path),
        units_per_em=units_per_em,
        ascender=ascender,
        descender=descender,
        line_gap=line_gap,
        advances=tuple(advances),
        cmap=cmap,
        family_from_file=family,
    )


_CACHE: dict[str, Font] = {}


def get_font(name: str) -> Font:
    """Load a supported font by name. Cached, so repeated layout does not re-parse."""
    if name not in _CACHE:
        _CACHE[name] = _load(resolve_font_path(name), name)
    return _CACHE[name]


def css_family(name: str) -> str:
    """The font-family string to emit in SVG for a supported font name.

    The bold face is a separate file here, but in CSS it is the same family at weight 700,
    so the renderer needs both the family and the weight.
    """
    if name == "DejaVu Sans Bold":
        return "DejaVu Sans"
    return name


def css_weight(name: str) -> str:
    return "700" if name.endswith(" Bold") else "400"
