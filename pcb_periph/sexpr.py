"""Reader for KiCad's s-expression file syntax (pure standard library).

KiCad board/schematic files are plain-text s-expressions: nested
parenthesized lists whose leaves are either bare atoms (symbols such as
``kicad_pcb``, ``thru_hole`` or numbers such as ``20241229``) or quoted
strings with backslash escapes. This module parses that syntax into plain
Python structures:

* a node is a ``list`` whose first element is the node tag (a string) and
  whose remaining elements are child nodes (lists) or leaf atoms (strings);
* both quoted strings and bare symbols become Python ``str`` values --
  callers convert numeric atoms on demand with :func:`to_number`.

The tokenizer is a single anchored regex plus a small unescape routine for
quoted strings; the parser is an explicit stack, so arbitrarily deep
nesting cannot hit the recursion limit. Lexical or structural errors raise
:class:`SexprError` with a line/column position.
"""

from __future__ import annotations

import re
from typing import Iterator

__all__ = [
    "SexprError",
    "atom",
    "child",
    "children",
    "parse",
    "parse_file",
    "tag",
    "to_number",
]

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<lparen>\()
    | (?P<rparen>\))
    | (?P<string>"(?:[^"\\]|\\.)*")
    | (?P<symbol>[^\s()"]+)
    """,
    re.VERBOSE,
)

_INT_RE = re.compile(r"^[-+]?\d+$")
_FLOAT_RE = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")

_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


class SexprError(ValueError):
    """The input is not well-formed s-expression text."""


def _unescape(body: str) -> str:
    """Decode backslash escapes inside a quoted-string token body."""
    if "\\" not in body:
        return body
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            nxt = body[index + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    column = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, column


def tokenize(text: str) -> Iterator[tuple[int, str, str]]:
    """Yield ``(offset, kind, value)`` token triples.

    ``kind`` is ``"("`` or ``")"`` for parentheses (``value`` mirrors the
    kind) or ``"atom"`` for leaf atoms (``value`` is the decoded text).
    ``offset`` is the character position of the token start, for error
    reporting.
    """
    pos = 0
    length = len(text)
    while pos < length:
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            line, col = _line_col(text, pos)
            snippet = text[pos : pos + 20]
            raise SexprError(
                f"lexical error at line {line}, column {col}: {snippet!r}"
            )
        start = pos
        pos = match.end()
        kind = match.lastgroup
        if kind == "ws":
            continue
        if kind in ("lparen", "rparen"):
            yield start, match.group(), match.group()
        elif kind == "string":
            yield start, "atom", _unescape(match.group()[1:-1])
        else:  # symbol
            yield start, "atom", match.group()


def parse(text: str) -> list:
    """Parse *text* and return the single top-level node.

    Raises :class:`SexprError` for unbalanced parentheses, trailing garbage
    or an empty document.
    """
    root: list = []
    stack: list[list] = [root]
    opened_at: list[int] = []
    for offset, kind, value in tokenize(text):
        if kind == "(":
            node: list = []
            stack[-1].append(node)
            stack.append(node)
            opened_at.append(offset)
        elif kind == ")":
            if len(stack) == 1:
                line, col = _line_col(text, offset)
                raise SexprError(
                    f"unbalanced ')' at line {line}, column {col}"
                )
            stack.pop()
            opened_at.pop()
        else:
            stack[-1].append(value)
    if len(stack) != 1:
        line, col = _line_col(text, opened_at[-1])
        raise SexprError(f"unclosed '(' opened at line {line}, column {col}")
    if len(root) != 1 or not isinstance(root[0], list):
        raise SexprError("expected exactly one top-level node")
    return root[0]


def parse_file(path: str) -> list:
    """Read *path* (UTF-8, BOM-tolerant) and parse it as s-expression."""
    with open(path, encoding="utf-8-sig") as handle:
        return parse(handle.read())


def tag(node: list) -> str | None:
    """Return the tag of *node* (its first element) if it is a string."""
    if node and isinstance(node[0], str):
        return node[0]
    return None


def children(node: list, name: str) -> list[list]:
    """Return direct child nodes of *node* whose tag equals *name*."""
    return [
        child_node
        for child_node in node[1:]
        if isinstance(child_node, list) and tag(child_node) == name
    ]


def child(node: list, name: str):
    """Return the first direct child node tagged *name*, or ``None``."""
    for child_node in node[1:]:
        if isinstance(child_node, list) and tag(child_node) == name:
            return child_node
    return None


def atom(node: list, index: int) -> str | None:
    """Return leaf atom *index* of *node* if present and string-like."""
    try:
        value = node[index]
    except IndexError:
        return None
    return value if isinstance(value, str) else None


def to_number(text: str | None) -> int | float | None:
    """Convert an atom to int or float; return ``None`` if not numeric.

    Hex masks such as ``0x00000000_000000fc_ffffffff`` and mixed
    alphanumeric atoms intentionally stay non-numeric.
    """
    if not isinstance(text, str) or not text:
        return None
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    return None
