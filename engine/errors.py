"""Error types. Every failure mode of the engine is one of these, and every one of them
carries enough detail to say what conflicted.

The engine never degrades. If it cannot satisfy a constraint it raises. Silently emitting
a layout that violates a constraint would make claims 1 and 2 unfalsifiable, so it is not
an option the code offers.
"""


class SpecError(ValueError):
    """The spec is malformed or refers to something that does not exist."""


class FontError(SpecError):
    """The requested font is not one of the supported fonts, or the file is unreadable."""


class UnsupportedCharacter(SpecError):
    """A codepoint in the text has no glyph in the chosen font.

    Substituting a fallback width here would be a guess, and a guess is exactly what
    breaks claim 1. The engine refuses instead.
    """

    def __init__(self, char: str, codepoint: int, font_name: str, context: str):
        self.char = char
        self.codepoint = codepoint
        self.font_name = font_name
        self.context = context
        super().__init__(
            f"font {font_name!r} has no glyph for U+{codepoint:04X} "
            f"({char!r}) in text {context!r}. Choose a font that covers it."
        )


class Unsatisfiable(Exception):
    """The constraint system has no solution.

    ``cycle`` is the list of constraint descriptions that form the conflict, in order,
    so the message names the actual contradiction rather than reporting failure in the
    abstract.
    """

    def __init__(self, axis: str, cycle: list[str]):
        self.axis = axis
        self.cycle = list(cycle)
        joined = "\n  ".join(self.cycle)
        super().__init__(
            f"constraints on the {axis} axis cannot all hold. "
            f"These {len(self.cycle)} constraints form a conflicting cycle:\n  {joined}"
        )


class TextDoesNotFit(Unsatisfiable):
    """A text run cannot be made to fit its container under its overflow policy."""

    def __init__(self, text: str, needed: float, available: float, box: str):
        self.text = text
        self.needed = needed
        self.available = available
        self.box = box
        Exception.__init__(
            self,
            f"text {text!r} needs {needed:.2f}px in box {box!r} which has only "
            f"{available:.2f}px of content width, and its overflow policy is 'strict'. "
            f"Widen the box, shorten the text, reduce the font size, or set "
            f"overflow='wrap' or overflow='ellipsis'."
        )
        self.axis = "x"
        self.cycle = [
            f"box {box!r} content width <= {available:.2f}",
            f"text {text!r} measured width >= {needed:.2f}",
        ]
