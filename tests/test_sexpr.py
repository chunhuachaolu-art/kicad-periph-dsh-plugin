"""Unit tests for the s-expression reader (no fixtures, no kicad-cli).

These tests are written pytest-style (plain ``test_*`` functions with bare
asserts) and can also be executed with the bundled stdlib runner
``tests/run_tests.py``.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from pcb_periph.sexpr import (  # noqa: E402
    SexprError,
    atom,
    child,
    children,
    parse,
    tag,
    to_number,
)


@contextmanager
def _expect_error(exc_type):
    """Minimal ``pytest.raises`` stand-in (stdlib-runner compatible)."""
    caught = None
    try:
        yield
    except exc_type as exc:  # re-raised below when it did not happen
        caught = exc
    if caught is None:
        raise AssertionError(f"expected {exc_type.__name__} to be raised")


def test_parse_basic_structure():
    node = parse('(kicad_pcb (version 20241229) (generator "pcbnew"))')
    assert tag(node) == "kicad_pcb"
    version = child(node, "version")
    assert atom(version, 1) == "20241229"
    assert children(node, "version")[0] is version
    assert child(node, "missing") is None


def test_parse_quoted_strings_and_escapes():
    node = parse(r'(net 5 "/bus/data \"A\"+")')
    assert atom(node, 1) == "5"
    assert atom(node, 2) == '/bus/data "A"+'
    # backslash escapes and embedded whitespace round-trip
    node = parse(r'(descr "line1\nline2\ttab\\slash")')
    assert atom(node, 1) == "line1\nline2\ttab\\slash"


def test_parse_deep_nesting_does_not_recurse_crash():
    depth = 5000
    node = parse("(" * depth + "x" + ")" * depth)
    seen = 0
    while isinstance(node, list):
        node = node[-1]
        seen += 1
    assert seen == depth


def test_parse_errors():
    for bad in ("", "(a", "a)", "(a))", ")(", "(a) (b)"):
        with _expect_error(SexprError):
            parse(bad)


def test_tokenize_rejects_unterminated_string():
    with _expect_error(SexprError):
        parse('(net 1 "oops)')


def test_to_number_int_float_and_non_numeric():
    assert to_number("20241229") == 20241229
    assert to_number("-13") == -13
    assert to_number("126.619") == 126.619
    assert to_number("-0.5") == -0.5
    assert to_number(".5") == 0.5
    assert to_number("1e3") == 1000.0
    # hex layer masks and alphanumeric symbols stay strings
    assert to_number("0x00000000_000000fc_ffffffff") is None
    assert to_number("thru_hole") is None
    assert to_number("+12V") is None
    assert to_number("") is None
    assert to_number(None) is None


def test_atoms_may_contain_quotes_inside_symbols_never():
    # bare symbols stop at whitespace/parens/quotes; everything else is fair
    node = parse("(sym a-b_c.d:e/f~g')")
    assert node[1:] == ["a-b_c.d:e/f~g'"]
