"""The typed data spec.

The model's job is to produce one of these. It says what the infographic contains and
nothing about where anything goes. No coordinates, no widths, no font sizes chosen to make
a label fit. Geometry is the solver's output, which is what makes claims 1 and 2 provable:
if the model cannot place anything, the model cannot make anything overlap or overflow.

Every field is validated on construction. A spec that names a font the engine has not
measured, or a negative bar value, or an unknown overflow policy, is rejected before layout
starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Union

from .errors import SpecError
from .fontmetrics import SUPPORTED_FONTS

Overflow = Literal["wrap", "ellipsis", "strict"]
_OVERFLOW = ("wrap", "ellipsis", "strict")
_THEMES = ("light", "dark")


def _check_overflow(v: str) -> str:
    if v not in _OVERFLOW:
        raise SpecError(f"overflow must be one of {_OVERFLOW}, got {v!r}")
    return v


def _check_text(v: object, what: str) -> str:
    if not isinstance(v, str):
        raise SpecError(f"{what} must be a string, got {type(v).__name__}")
    if "\r" in v:
        raise SpecError(f"{what} must not contain a carriage return")
    return v


@dataclass(frozen=True)
class Paragraph:
    """A run of prose in its own full-width box."""

    text: str
    size: float = 14.0
    overflow: str = "wrap"
    emphasis: bool = False

    def __post_init__(self) -> None:
        _check_text(self.text, "Paragraph.text")
        _check_overflow(self.overflow)
        if not 4.0 <= self.size <= 96.0:
            raise SpecError(f"Paragraph.size must be in [4, 96], got {self.size}")


@dataclass(frozen=True)
class Bar:
    label: str
    value: float

    def __post_init__(self) -> None:
        _check_text(self.label, "Bar.label")
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
            raise SpecError("Bar.value must be a number")
        if self.value < 0:
            raise SpecError(
                f"Bar.value must be >= 0, got {self.value}. Bar length is a fraction of the "
                f"largest value in the chart, which is not defined for a negative one. "
                f"Use a diverging chart type or shift the data."
            )


@dataclass(frozen=True)
class BarChart:
    """Horizontal bars. Label column on the left, value column on the right, bars between.

    The three columns are laid out by the constraint solver, so a label column that would
    squeeze the bars below their minimum length is a refusal and not a squeezed chart.
    """

    caption: str
    bars: tuple[Bar, ...]
    unit: str = ""
    size: float = 13.0
    label_overflow: str = "ellipsis"

    def __post_init__(self) -> None:
        _check_text(self.caption, "BarChart.caption")
        _check_text(self.unit, "BarChart.unit")
        _check_overflow(self.label_overflow)
        if not self.bars:
            raise SpecError(
                "BarChart.bars must not be empty. A chart with no rows has no scale, so the "
                "engine cannot assign bar lengths."
            )
        if len(self.bars) > 40:
            raise SpecError(f"BarChart supports at most 40 bars, got {len(self.bars)}")
        if not 4.0 <= self.size <= 48.0:
            raise SpecError(f"BarChart.size must be in [4, 48], got {self.size}")


@dataclass(frozen=True)
class Kpi:
    label: str
    value: str
    note: str = ""

    def __post_init__(self) -> None:
        _check_text(self.label, "Kpi.label")
        _check_text(self.value, "Kpi.value")
        _check_text(self.note, "Kpi.note")


@dataclass(frozen=True)
class KpiRow:
    """Equal-width cards in a row. Refuses rather than shrinking a card below its content."""

    cards: tuple[Kpi, ...]
    value_size: float = 26.0
    label_size: float = 12.0

    def __post_init__(self) -> None:
        if not self.cards:
            raise SpecError(
                "KpiRow.cards must not be empty. The row width is split between its cards, "
                "which is undefined for zero cards."
            )
        if len(self.cards) > 8:
            raise SpecError(f"KpiRow supports at most 8 cards, got {len(self.cards)}")
        if not 6.0 <= self.value_size <= 72.0:
            raise SpecError("KpiRow.value_size must be in [6, 72]")
        if not 4.0 <= self.label_size <= 48.0:
            raise SpecError("KpiRow.label_size must be in [4, 48]")


@dataclass(frozen=True)
class Steps:
    """A numbered vertical flow. Each step wraps inside its own box."""

    caption: str
    items: tuple[str, ...]
    size: float = 13.0

    def __post_init__(self) -> None:
        _check_text(self.caption, "Steps.caption")
        if not self.items:
            raise SpecError(
                "Steps.items must not be empty. A numbered flow with no steps has nothing to "
                "number."
            )
        for i, it in enumerate(self.items):
            _check_text(it, f"Steps.items[{i}]")
        if not 4.0 <= self.size <= 48.0:
            raise SpecError("Steps.size must be in [4, 48]")


Block = Union[Paragraph, BarChart, KpiRow, Steps]


@dataclass(frozen=True)
class Doc:
    """A whole infographic.

    ``width`` is the only geometric number the spec carries, because a poster has to be some
    width. Height is whatever the solver needs.
    """

    id: str
    title: str
    blocks: tuple[Block, ...]
    subtitle: str = ""
    footer: str = ""
    width: float = 720.0
    font: str = "DejaVu Sans"
    theme: str = "light"
    title_size: float = 26.0
    accent: int = 0

    def __post_init__(self) -> None:
        _check_text(self.id, "Doc.id")
        if not self.id or any(c.isspace() for c in self.id):
            raise SpecError(f"Doc.id must be a non-empty whitespace-free string, got {self.id!r}")
        _check_text(self.title, "Doc.title")
        _check_text(self.subtitle, "Doc.subtitle")
        _check_text(self.footer, "Doc.footer")
        if self.font not in SUPPORTED_FONTS:
            raise SpecError(
                f"font {self.font!r} is not measured by this engine. Supported: "
                f"{', '.join(SUPPORTED_FONTS)}. The engine refuses to lay out an "
                f"unmeasured font rather than estimate its widths."
            )
        if self.theme not in _THEMES:
            raise SpecError(f"theme must be one of {_THEMES}, got {self.theme!r}")
        if not 160.0 <= self.width <= 4000.0:
            raise SpecError(f"Doc.width must be in [160, 4000], got {self.width}")
        if not self.blocks:
            raise SpecError(
                "Doc.blocks must not be empty. An infographic with a title and nothing else "
                "has no content to lay out, so the engine refuses rather than emitting a "
                "canvas that only contains its own heading."
            )
        if not 8.0 <= self.title_size <= 96.0:
            raise SpecError("Doc.title_size must be in [8, 96]")
        if not isinstance(self.accent, int) or not 0 <= self.accent <= 4:
            raise SpecError("Doc.accent must be an int in [0, 4]")
        for i, b in enumerate(self.blocks):
            if not isinstance(b, (Paragraph, BarChart, KpiRow, Steps)):
                raise SpecError(f"Doc.blocks[{i}] is not a known block type: {type(b).__name__}")


# ---- JSON round trip --------------------------------------------------------
# The docs page edits a spec as JSON, so the same shape has to survive a round trip. Keys
# are emitted in sorted order and tuples become lists, which keeps the JSON byte-stable.

_BLOCK_TYPES = {
    "paragraph": Paragraph,
    "bars": BarChart,
    "kpis": KpiRow,
    "steps": Steps,
}
_BLOCK_NAMES = {v: k for k, v in _BLOCK_TYPES.items()}


def block_to_json(b: Block) -> dict:
    d: dict = {"type": _BLOCK_NAMES[type(b)]}
    if isinstance(b, BarChart):
        d.update(
            caption=b.caption,
            unit=b.unit,
            size=b.size,
            label_overflow=b.label_overflow,
            bars=[{"label": x.label, "value": x.value} for x in b.bars],
        )
    elif isinstance(b, KpiRow):
        d.update(
            value_size=b.value_size,
            label_size=b.label_size,
            cards=[{"label": c.label, "value": c.value, "note": c.note} for c in b.cards],
        )
    elif isinstance(b, Steps):
        d.update(caption=b.caption, size=b.size, items=list(b.items))
    else:
        d.update(text=b.text, size=b.size, overflow=b.overflow, emphasis=b.emphasis)
    return d


def block_from_json(d: dict) -> Block:
    kind = d.get("type")
    if kind not in _BLOCK_TYPES:
        raise SpecError(f"unknown block type {kind!r}; expected one of {sorted(_BLOCK_TYPES)}")
    if kind == "bars":
        return BarChart(
            caption=d.get("caption", ""),
            unit=d.get("unit", ""),
            size=d.get("size", 13.0),
            label_overflow=d.get("label_overflow", "ellipsis"),
            bars=tuple(Bar(x["label"], x["value"]) for x in d.get("bars", ())),
        )
    if kind == "kpis":
        return KpiRow(
            value_size=d.get("value_size", 26.0),
            label_size=d.get("label_size", 12.0),
            cards=tuple(
                Kpi(c["label"], c["value"], c.get("note", "")) for c in d.get("cards", ())
            ),
        )
    if kind == "steps":
        return Steps(
            caption=d.get("caption", ""),
            size=d.get("size", 13.0),
            items=tuple(d.get("items", ())),
        )
    return Paragraph(
        text=d.get("text", ""),
        size=d.get("size", 14.0),
        overflow=d.get("overflow", "wrap"),
        emphasis=bool(d.get("emphasis", False)),
    )


def doc_to_json(doc: Doc) -> dict:
    return {
        "accent": doc.accent,
        "blocks": [block_to_json(b) for b in doc.blocks],
        "font": doc.font,
        "footer": doc.footer,
        "id": doc.id,
        "subtitle": doc.subtitle,
        "theme": doc.theme,
        "title": doc.title,
        "title_size": doc.title_size,
        "width": doc.width,
    }


def doc_from_json(d: dict) -> Doc:
    return Doc(
        id=d.get("id", "spec"),
        title=d.get("title", ""),
        subtitle=d.get("subtitle", ""),
        footer=d.get("footer", ""),
        width=d.get("width", 720.0),
        font=d.get("font", "DejaVu Sans"),
        theme=d.get("theme", "light"),
        title_size=d.get("title_size", 26.0),
        accent=d.get("accent", 0),
        blocks=tuple(block_from_json(b) for b in d.get("blocks", ())),
    )
