"""Emit SVG.

Claim 3 lives here: the same spec must produce byte-identical output on every run and every
machine. That rules out a short list of things, each of which is a real way people break it:

  no wall clock, no process id, no version string that changes
  no unseeded randomness
  no iteration over a set or over a dict whose insertion order depends on input order
  no unbounded float formatting, because repr of a double is platform-stable in CPython but
    the point of rounding first is that the emitted number is the number the constraints
    were solved with
  no attribute order that depends on anything but the code below
  LF line endings, no trailing whitespace

Colours are emitted as ``var(--ig-name, #fallback)``. The fallback makes a standalone .svg
file open correctly with no stylesheet, and the custom property lets the docs page retheme
every embedded graphic at once without regenerating anything. The fallback baked in is chosen
by the spec's ``theme`` field, so a dark spec is dark on its own.
"""

from __future__ import annotations

from .layout import Box, Layout, Shape, TextRun
from .fontmetrics import css_family, css_weight

ENGINE = "svg-infographic"

_PALETTES = {
    "light": {
        "bg": "#ffffff",
        "panel": "#f4f6f9",
        "panel-line": "#e0e5ec",
        "card": "#ffffff",
        "card-line": "#dde3ea",
        "fg": "#14161a",
        "muted": "#5b6472",
        "track": "#e5e9ef",
        "badge-fg": "#ffffff",
    },
    "dark": {
        "bg": "#0f1115",
        "panel": "#171a20",
        "panel-line": "#282e38",
        "card": "#13161c",
        "card-line": "#2b313b",
        "fg": "#e9ebef",
        "muted": "#9aa3b2",
        "track": "#232936",
        "badge-fg": "#0f1115",
    },
}

_ACCENTS = {
    "light": ("#2f6df6", "#0f9d6b", "#c2410c", "#7c3aed", "#0e7490"),
    "dark": ("#6d9bff", "#34d399", "#fb923c", "#a78bfa", "#22d3ee"),
}

_ROLE_COLOR = {
    "title": "fg",
    "subtitle": "muted",
    "footer": "muted",
    "para": "fg",
    "caption": "fg",
    "barlabel": "fg",
    "barvalue": "muted",
    "kpivalue": "fg",
    "kpilabel": "fg",
    "kpinote": "muted",
    "stepnum": "badge-fg",
    "steptext": "fg",
}


def fmt(v: float) -> str:
    """Fixed 2-decimal formatting with trailing zeros removed.

    Every coordinate in the file goes through this. Two decimals is well below one device
    pixel at any sane zoom and it removes the last place a platform could differ.
    """
    s = f"{v:.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _esc_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _color(theme: str, key: str) -> str:
    return f"var(--ig-{key}, {_PALETTES[theme][key]})"


def _accent(theme: str, i: int) -> str:
    return f"var(--ig-accent-{i}, {_ACCENTS[theme][i]})"


def _attrs(pairs: list[tuple[str, str]]) -> str:
    return " ".join(f'{k}="{v}"' for k, v in pairs)


def _box_svg(bx: Box, theme: str) -> str | None:
    cx, cy, cw, ch = bx.content
    common = [
        ("id", f"box-{_esc_attr(bx.id)}"),
        ("class", f"ig-box ig-box-{bx.role}"),
        ("x", fmt(bx.x)),
        ("y", fmt(bx.y)),
        ("width", fmt(bx.w)),
        ("height", fmt(bx.h)),
        ("data-role", bx.role),
        ("data-pad-x", fmt(bx.pad_x)),
        ("data-pad-y", fmt(bx.pad_y)),
        ("data-content", f"{fmt(cx)} {fmt(cy)} {fmt(cw)} {fmt(ch)}"),
    ]
    if bx.role == "panel":
        common += [("rx", "10"), ("fill", _color(theme, "panel")), ("stroke", _color(theme, "panel-line"))]
    elif bx.role == "card":
        common += [("rx", "10"), ("fill", _color(theme, "card")), ("stroke", _color(theme, "card-line"))]
    else:
        # A frame carries geometry only. It still has to be in the file, because it is the
        # container an outside checker compares the text against.
        common += [("fill", "none"), ("stroke", "none")]
    return f"  <rect {_attrs(common)}/>"


def _shape_svg(sh: Shape, theme: str, accent: int) -> str:
    if sh.role == "track":
        fill = _color(theme, "track")
    elif sh.role == "badge":
        fill = _accent(theme, accent)
    else:
        fill = _accent(theme, sh.accent)
    pairs = [
        ("class", f"ig-shape ig-shape-{sh.role}"),
        ("x", fmt(sh.x)),
        ("y", fmt(sh.y)),
        ("width", fmt(sh.w)),
        ("height", fmt(sh.h)),
    ]
    if sh.rx:
        pairs.append(("rx", fmt(sh.rx)))
    pairs.append(("fill", fill))
    return f"  <rect {_attrs(pairs)}/>"


def _text_svg(t: TextRun, theme: str) -> str:
    color = _color(theme, _ROLE_COLOR.get(t.role, "fg"))
    pairs = [
        ("id", _esc_attr(t.id)),
        ("class", f"ig-text ig-role-{t.role}"),
        ("x", fmt(t.x)),
        ("y", fmt(t.baseline)),
        ("font-family", _esc_attr(css_family(t.font))),
        ("font-size", fmt(t.size)),
        ("font-weight", css_weight(t.font)),
        ("text-anchor", t.anchor),
        # Kerning and ligatures are switched off so the rendered advance is exactly the sum
        # of hmtx advances this engine measured. Leaving them on would mean the renderer
        # applies GPOS adjustments the measurement never saw.
        ("font-kerning", "none"),
        ("font-variant-ligatures", "none"),
        ("letter-spacing", "0"),
        ("xml:space", "preserve"),
        ("fill", color),
        ("data-box", _esc_attr(t.box)),
        ("data-role", t.role),
        ("data-measured", fmt(t.width)),
        ("data-ascent", fmt(t.ascent)),
        ("data-descent", fmt(t.descent)),
        ("data-fit", f"{fmt(t.fit_x0)} {fmt(t.fit_x1)}"),
    ]
    return f"  <text {_attrs(pairs)}>{_esc_text(t.content)}</text>"


def render(lay: Layout) -> str:
    """Serialise a solved layout. Pure function of its input."""
    theme = lay.theme
    lines: list[str] = []
    lines.append(
        "<svg "
        + _attrs(
            [
                ("xmlns", "http://www.w3.org/2000/svg"),
                ("viewBox", f"0 0 {fmt(lay.width)} {fmt(lay.height)}"),
                ("width", fmt(lay.width)),
                ("height", fmt(lay.height)),
                ("role", "img"),
                ("aria-label", _esc_attr(lay.title)),
                ("data-engine", ENGINE),
                ("data-spec-id", _esc_attr(lay.doc_id)),
                ("data-theme", theme),
                ("data-font", _esc_attr(lay.font)),
                ("id", f"ig-{_esc_attr(lay.doc_id)}"),
            ]
        )
        + ">"
    )
    lines.append(f"  <title>{_esc_text(lay.title)}</title>")
    lines.append(
        "  <rect "
        + _attrs(
            [
                ("class", "ig-bg"),
                ("x", "0"),
                ("y", "0"),
                ("width", fmt(lay.width)),
                ("height", fmt(lay.height)),
                ("fill", _color(theme, "bg")),
            ]
        )
        + "/>"
    )
    for bx in lay.boxes:
        s = _box_svg(bx, theme)
        if s:
            lines.append(s)
    for sh in lay.shapes:
        lines.append(_shape_svg(sh, theme, lay.accent))
    for t in lay.texts:
        lines.append(_text_svg(t, theme))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def render_spec(doc) -> str:
    from .layout import layout

    return render(layout(doc))
