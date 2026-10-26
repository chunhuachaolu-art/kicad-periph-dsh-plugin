"""Unit tests for canonical serialization helpers (no kicad-cli needed).

These tests are written pytest-style (plain ``test_*`` functions with bare
asserts) and can also be executed with the bundled stdlib runner
``tests/run_tests.py``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from pcb_periph.canonical import (  # noqa: E402
    VOLATILE_FIELDS,
    canonicalize,
    dumps,
    path_anchor,
)
from pcb_periph.runner import _raw_report_name  # noqa: E402


def test_dumps_is_deterministic_and_sorted():
    payload = {"b": 1, "a": {"z": [1, 2], "m": {"k": "v"}}}
    first = dumps(payload)
    second = dumps(payload)
    assert first == second
    assert first.startswith("{\n  \"a\"")
    assert first.endswith("}\n")
    # non-ASCII must round-trip (ensure_ascii=False)
    assert "板" in dumps({"name": "板"})


def test_canonicalize_strips_volatile_fields_only():
    payload = {
        "schema_version": "1.0.0",
        "timing_ms": 12345,
        "boards": [{"board": "x.kicad_pcb", "violations": {"total": 2}}],
    }
    result = canonicalize(payload)
    assert "timing_ms" not in result
    assert result["schema_version"] == "1.0.0"
    assert result["boards"][0]["violations"]["total"] == 2
    # the input payload is not mutated
    assert payload["timing_ms"] == 12345
    assert VOLATILE_FIELDS == ("timing_ms",)


def test_path_anchor_uses_forward_slashes():
    base = os.path.abspath(os.sep.join(("C:", "work", "repo")))
    target = os.path.join(base, "sub", "board.kicad_pcb")
    anchor = path_anchor(target, base)
    assert anchor == "sub/board.kicad_pcb"
    assert "\\" not in anchor


def test_path_anchor_absolute_on_foreign_drive():
    base = os.path.abspath(os.sep.join(("Z:", "nowhere")))
    target = os.path.abspath(os.sep.join(("Y:", "elsewhere", "b.kicad_pcb")))
    anchor = path_anchor(target, base)
    assert anchor.endswith("b.kicad_pcb")
    assert "\\" not in anchor


def test_raw_report_name_scheme():
    assert _raw_report_name("brd", "drc", 1) == "brd.drc-raw.json"
    assert _raw_report_name("brd", "erc", 2) == "brd.erc-raw.2.json"
    assert _raw_report_name("brd", "drc", 5) == "brd.drc-raw.5.json"
