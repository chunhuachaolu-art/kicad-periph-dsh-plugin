"""Tests for the ``diffpair`` subcommand and the kicad-doc-v1 rule set.

The rule set is a clean-room implementation of the suffix convention
documented in the KiCad 10.0 PCB Editor manual ("Differential pairs in
KiCad are defined as nets with a common base name and a positive and
negative suffix. KiCad supports using + and - , or P and N as the
suffixes."). The unit tests below cover every mandated suffix form and
pin the boundaries the documentation leaves open (case sensitivity,
separators, mixed styles, multi-level suffixes, empty bases) -- the
pinned choices are documented in the README decision table.

The fixture-board expectation is *derived*, not copied: the example board
``examples/diffpair_showcase`` (script-generated, see
``tests/make_boards.py``) was designed net-name-first to exercise every
suffix style, so under kicad-doc-v1 it yields 5 complete pairs, 5
unpaired halves and 2 suspicious findings. Bare-P/N matching makes any
net ending in P or N suffix-bearing -- the showcase ``PIEZO_IN`` net is a
bare-``N`` half on base ``PIEZO_I`` with no ``PIEZO_IP`` counterpart;
that is the documented convention applied mechanically, and it is exactly
why every output entry carries its ``suffix_style``.

These tests are written pytest-style (plain ``test_*`` functions with
bare asserts) and also run under the bundled stdlib runner
``tests/run_tests.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from pcb_periph.diffpair import (  # noqa: E402
    RULE_SET_NAME,
    RULE_SETS,
    SUFFIX_SEPARATORS,
    check_diffpairs,
    decompose_net_name,
    run_diffpair,
    suffix_groups,
)

CLEAN_PCB = os.path.join(
    REPO_ROOT, "examples", "diffpair_showcase", "diffpair_showcase.kicad_pcb"
)

# by-construction kicad-doc-v1 expectation for the example board (see
# module docstring): 5 pairs covering every suffix style, 5 unpaired
# halves, 2 suspicious findings
FIXTURE_PAIRS = [
    ("CLK-P", "CLK-N"),
    ("CLK+", "CLK-"),
    ("DATA_P", "DATA_N"),
    ("USB.P", "USB.N"),
    ("USB_DP", "USB_DN"),
]
FIXTURE_UNPAIRED_NETS = [
    "AUX-N",
    "AUX_P",
    "LONE_P",
    "PIEZO_IN",
    "SENSE+",
]


def _run_cli(args, env_overrides=None):
    env = {k: v for k, v in os.environ.items() if k != "KICAD_CLI"}
    env.update(env_overrides or {})
    return subprocess.run(
        [sys.executable, "-m", "pcb_periph", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
    )


def _payload(proc):
    return json.loads(proc.stdout)


def _check(counts):
    return check_diffpairs(counts)


# --------------------------------------------------------------------------
# decomposition unit tests (pinned boundaries)


def test_decompose_symbol_suffixes():
    assert decompose_net_name("CLK+") == {
        "base": "CLK", "group": "plus_minus", "polarity": "positive",
        "suffix_style": "symbol", "suffix": "+", "separator": None,
    }
    assert decompose_net_name("CLK-")["polarity"] == "negative"
    assert decompose_net_name("CLK-")["base"] == "CLK"
    # the symbol group takes the last character only: whatever the base
    # ends with (including a separator) is part of the base
    assert decompose_net_name("CLK_+")["base"] == "CLK_"
    assert decompose_net_name("CLK_+")["suffix_style"] == "symbol"


def test_decompose_p_n_separator_forms():
    for separator in SUFFIX_SEPARATORS:
        positive, negative = f"DATA{separator}P", f"DATA{separator}N"
        dp, dn = decompose_net_name(positive), decompose_net_name(negative)
        assert dp["base"] == dn["base"] == "DATA"
        assert dp["suffix_style"] == dn["suffix_style"] == "separator"
        assert dp["separator"] == dn["separator"] == separator
        assert dp["polarity"] == "positive" and dn["polarity"] == "negative"
        assert dp["suffix"] == f"{separator}P" and dn["suffix"] == f"{separator}N"


def test_decompose_p_n_bare_and_multi_level():
    # bare trailing P/N: base is everything before the last character
    assert decompose_net_name("DATAP")["suffix_style"] == "bare"
    assert decompose_net_name("DATAP")["base"] == "DATA"
    # multi-level names decompose at the last level: USB_DP pairs on USB_D
    assert decompose_net_name("USB_DP")["base"] == "USB_D"
    assert decompose_net_name("USB_DN")["base"] == "USB_D"


def test_decompose_case_sensitive_pin():
    # pinned: only upper-case P/N count; lowercase forms are not even
    # suffix-bearing (so they never pair and never appear as halves)
    assert decompose_net_name("DATA_p") is None
    assert decompose_net_name("DATA_n") is None
    assert decompose_net_name("datap") is None
    # the symbol suffixes are single ASCII characters either way
    assert decompose_net_name("DATA+") is not None


def test_decompose_requires_nonempty_base():
    for name in ("+", "-", "P", "N"):
        assert decompose_net_name(name) is None, name
    # "_P" cannot use the separator form (empty base), so it falls back
    # to the bare style with the separator left in the base (pinned)
    part = decompose_net_name("_P")
    assert part["suffix_style"] == "bare" and part["base"] == "_"


def test_suffix_groups_descriptor():
    groups = suffix_groups()
    assert [g["group"] for g in groups] == ["plus_minus", "p_n", "p_n"]
    assert [g["suffix_style"] for g in groups] == [
        "symbol", "separator", "bare",
    ]
    assert groups[1]["separators"] == list(SUFFIX_SEPARATORS)
    assert sorted(RULE_SETS) == ["kicad-doc-v1", "none"]


# --------------------------------------------------------------------------
# pairing tests over synthetic net name lists (dispatch-required forms)


def test_pair_plus_minus():
    result = _check({"CLK+": 3, "CLK-": 2, "BUSY": 1})
    assert len(result["pairs"]) == 1
    pair = result["pairs"][0]
    assert pair["base"] == "CLK"
    assert pair["positive"] == "CLK+" and pair["negative"] == "CLK-"
    assert pair["group"] == "plus_minus"
    assert pair["suffix_style"] == "symbol"
    assert pair["suffixes"] == {"positive": "+", "negative": "-"}
    assert pair["pads"] == {"positive": 3, "negative": 2}
    assert pair["pads_total"] == 5
    assert result["unpaired"] == [] and result["suspicious"] == []
    assert result["stats"] == {
        "nets_named": 3, "pairs": 1, "nets_in_pairs": 2, "unpaired": 0,
        "suspicious": 0, "pads_in_pairs": 5, "pads_in_unpaired": 0,
    }


def test_pair_separator_underscore():
    result = _check({"DATA_P": 2, "DATA_N": 2})
    pair = result["pairs"][0]
    assert pair["base"] == "DATA"
    assert pair["suffix_style"] == "separator" and pair["separator"] == "_"


def test_pair_separator_dash_and_dot():
    for separator in ("-", "."):
        result = _check(
            {f"CLK{separator}P": 1, f"CLK{separator}N": 1, "GND": 4}
        )
        assert len(result["pairs"]) == 1
        assert result["pairs"][0]["separator"] == separator
        assert result["unpaired"] == []


def test_pair_bare_p_n():
    result = _check({"DATAP": 2, "DATAN": 2})
    pair = result["pairs"][0]
    assert pair["base"] == "DATA"
    assert pair["suffix_style"] == "bare" and pair["separator"] is None


def test_pair_multi_level_usb_dp_dn():
    result = _check({"USB_DP": 1, "USB_DN": 1})
    pair = result["pairs"][0]
    assert pair["base"] == "USB_D" and pair["suffix_style"] == "bare"


def test_plus_in_middle_never_pairs():
    # negative case: suffixes bind at the end of the name only
    result = _check({"DATA+CLK": 1, "DATA-CLK": 1, "A+B": 1})
    assert result["pairs"] == []
    assert result["unpaired"] == []
    assert result["suspicious"] == []


def test_single_half_is_unpaired():
    result = _check({"LONE_P": 2, "OTHER": 1})
    assert result["pairs"] == []
    assert [half["net"] for half in result["unpaired"]] == ["LONE_P"]
    half = result["unpaired"][0]
    assert half["polarity"] == "positive"
    assert half["base"] == "LONE"
    assert half["suffix"] == "_P" and half["suffix_style"] == "separator"
    assert half["pads"] == 2
    assert result["suspicious"] == []


def test_bare_half_from_in_word():
    # any net ending in N is a bare negative half -- including ordinary
    # words like PIEZO_IN (pinned mechanical consequence of bare P/N)
    result = _check({"PIEZO_IN": 2})
    half = result["unpaired"][0]
    assert half["net"] == "PIEZO_IN"
    assert half["base"] == "PIEZO_I"
    assert half["suffix_style"] == "bare"
    assert half["polarity"] == "negative"


def test_cross_style_same_base_is_suspicious_not_paired():
    # same base, opposite polarity, but different suffix styles or
    # separators: pairing must not silently absorb the inconsistency
    for names in (
        {"DATA_P": 1, "DATA-N": 1},   # different separators
        {"DATA_P": 1, "DATAN": 1},    # separator vs bare
        {"DATA+": 1, "DATA_N": 1},    # different groups
    ):
        result = _check(names)
        assert result["pairs"] == [], names
        assert len(result["unpaired"]) == 2, names
        kinds = {item["kind"] for item in result["suspicious"]}
        assert kinds == {"mixed_suffix_style"}, names
        entry = result["suspicious"][0]
        assert entry["base"] == "DATA"
        assert sorted(entry["nets"]) == sorted(names)


def test_duplicate_polarity_is_suspicious():
    # two positive halves on one base: same finding kind (their suffix
    # strings necessarily differ, so it is a mixed-style inconsistency)
    result = _check({"DATA_P": 1, "DATA+": 1})
    assert result["pairs"] == []
    assert all(h["polarity"] == "positive" for h in result["unpaired"])
    assert [item["kind"] for item in result["suspicious"]] == [
        "mixed_suffix_style"
    ]


def test_suffixless_twin_is_suspicious():
    result = _check({"DATA": 1, "DATA_P": 2, "DATA_N": 2})
    assert len(result["pairs"]) == 1  # the suffix pair still pairs
    assert result["suspicious"] == [{
        "kind": "suffixless_twin",
        "base": "DATA",
        "net": "DATA",
        "suffix_nets": ["DATA_N", "DATA_P"],
    }]


def test_two_complete_pairs_same_base_different_groups():
    # two independently complete pairs on one base are not suspicious
    result = _check({"DATA+": 1, "DATA-": 1, "DATA_P": 1, "DATA_N": 1})
    assert len(result["pairs"]) == 2
    assert result["unpaired"] == [] and result["suspicious"] == []


def test_check_is_order_independent():
    names = {"CLK+": 1, "CLK-": 1, "DATA_P": 1, "DATA_N": 1, "X": 1}
    first = check_diffpairs(dict(names))
    reversed_input = dict(reversed(list(names.items())))
    assert check_diffpairs(reversed_input) == first


# --------------------------------------------------------------------------
# CLI tests


def test_diffpair_help_documents_exit_codes():
    proc = _run_cli(["diffpair", "--help"])
    assert proc.returncode == 0, proc.stderr
    for text in (
        "0", "check completed",
        "2", "input or configuration error",
        "3", "input file unreadable",
    ):
        assert text in proc.stdout


def test_diffpair_board_fixture():
    proc = _run_cli(["diffpair", "--board", CLEAN_PCB])
    assert proc.returncode == 0, proc.stderr
    payload = _payload(proc)
    assert payload["schema_version"] == "1.0.0"
    assert payload["command"] == "diffpair"
    assert payload["rule_set"] == "kicad-doc-v1"
    assert payload["status"] == "ok"
    assert payload["input"]["kind"] == "board"
    assert payload["input"]["path"].endswith("diffpair_showcase.kicad_pcb")
    assert [
        (p["positive"], p["negative"]) for p in payload["pairs"]
    ] == FIXTURE_PAIRS
    assert [h["net"] for h in payload["unpaired"]] == FIXTURE_UNPAIRED_NETS
    styles = {h["net"]: h["suffix_style"] for h in payload["unpaired"]}
    assert styles["SENSE+"] == "symbol"
    assert styles["PIEZO_IN"] == "bare"
    assert [
        (item["kind"], item["base"]) for item in payload["suspicious"]
    ] == [
        ("mixed_suffix_style", "AUX"),
        ("suffixless_twin", "DATA"),
    ]
    assert payload["stats"]["nets_named"] == 19
    assert payload["stats"]["pairs"] == 5
    assert payload["stats"]["unpaired"] == 5
    assert payload["stats"]["suspicious"] == 2


def test_diffpair_netlist_input_matches_board_input():
    work = tempfile.mkdtemp()
    try:
        netlist_json = os.path.join(work, "netlist.json")
        proc = _run_cli(
            ["netlist", CLEAN_PCB, "--canonical", "--out", netlist_json]
        )
        assert proc.returncode == 0, proc.stderr
        via_netlist = _payload(_run_cli(["diffpair", "--netlist", netlist_json]))
        via_board = _payload(_run_cli(["diffpair", "--board", CLEAN_PCB]))
        assert via_netlist["status"] == "ok"
        for key in ("pairs", "unpaired", "suspicious", "stats"):
            assert via_netlist[key] == via_board[key], key
        assert via_netlist["input"]["kind"] == "netlist"
        assert via_netlist["input"]["board"] == via_board["input"]["path"]
        assert via_netlist["input"]["netlist_schema_version"] == "1.0.0"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_diffpair_netlist_synthetic_document():
    """A hand-built netlist-shaped document drives the same check."""
    work = tempfile.mkdtemp()
    try:
        doc = {
            "schema_version": "1.0.0",
            "command": "netlist",
            "boards": [{
                "status": "ok",
                "board": "synthetic.kicad_pcb",
                "nets": {
                    "CLK+": ["U1-3"], "CLK-": ["U1-4", "R1-1"],
                    "LONE_P": ["U2-1"], "LONE": ["U2-2"],
                },
            }],
        }
        path = os.path.join(work, "synthetic-netlist.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)
        proc = _run_cli(["diffpair", "--netlist", path])
        assert proc.returncode == 0, proc.stderr
        payload = _payload(proc)
        assert [(p["positive"], p["negative"]) for p in payload["pairs"]] == [
            ("CLK+", "CLK-")
        ]
        assert payload["pairs"][0]["pads"] == {"positive": 1, "negative": 2}
        assert [h["net"] for h in payload["unpaired"]] == ["LONE_P"]
        assert payload["suspicious"] == [{
            "kind": "suffixless_twin",
            "base": "LONE",
            "net": "LONE",
            "suffix_nets": ["LONE_P"],
        }]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_diffpair_zero_pairs_exits_zero():
    """A completed check with zero pairs is still exit 0."""
    work = tempfile.mkdtemp()
    try:
        doc = {"schema_version": "1.0.0", "boards": [
            {"status": "ok", "board": "b.kicad_pcb", "nets": {"GND": ["A-1"]}}
        ]}
        path = os.path.join(work, "plain.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)
        proc = _run_cli(["diffpair", "--netlist", path])
        assert proc.returncode == 0, proc.stderr
        assert _payload(proc)["stats"]["pairs"] == 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_diffpair_double_run_canonical_byte_equal():
    work = tempfile.mkdtemp()
    try:
        out1 = os.path.join(work, "run1.json")
        out2 = os.path.join(work, "run2.json")
        common = ["diffpair", "--board", CLEAN_PCB, "--canonical"]
        proc1 = _run_cli([*common, "--out", out1])
        proc2 = _run_cli([*common, "--out", out2])
        assert proc1.returncode == 0 and proc2.returncode == 0
        bytes1 = open(out1, "rb").read()
        bytes2 = open(out2, "rb").read()
        assert bytes1 == bytes2
        assert b"timing_ms" not in bytes1
        digest = hashlib.sha256(bytes1).hexdigest()[:16]
        assert len(digest) == 16

        # the --netlist route is byte-stable too
        netlist_json = os.path.join(work, "netlist.json")
        assert _run_cli(
            ["netlist", CLEAN_PCB, "--canonical", "--out", netlist_json]
        ).returncode == 0
        nl1 = os.path.join(work, "nl-run1.json")
        nl2 = os.path.join(work, "nl-run2.json")
        assert _run_cli(
            ["diffpair", "--netlist", netlist_json, "--canonical", "--out", nl1]
        ).returncode == 0
        assert _run_cli(
            ["diffpair", "--netlist", netlist_json, "--canonical", "--out", nl2]
        ).returncode == 0
        assert open(nl1, "rb").read() == open(nl2, "rb").read()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_diffpair_run_diffpair_api_matches_cli():
    payload, exit_code = run_diffpair(board=CLEAN_PCB, cwd=REPO_ROOT)
    assert exit_code == 0
    cli_payload = _payload(_run_cli(["diffpair", "--board", CLEAN_PCB]))
    for key in ("pairs", "unpaired", "suspicious", "stats"):
        assert payload[key] == cli_payload[key], key


# --------------------------------------------------------------------------
# error paths


def test_diffpair_missing_inputs_exit_three():
    for flag in ("--netlist", "--board"):
        missing = os.path.join(REPO_ROOT, "examples", "no_such_file")
        proc = _run_cli(["diffpair", flag, missing])
        assert proc.returncode == 3, (flag, proc.stderr)
        payload = _payload(proc)
        assert payload["status"] == "unreadable"
        assert "not found" in payload["error"]


def test_diffpair_flag_combination_errors_exit_two():
    # both flags at once / neither flag: argparse rejects, exit code 2
    for args in (
        ["diffpair", "--netlist", "a.json", "--board", "b.kicad_pcb"],
        ["diffpair"],
    ):
        proc = _run_cli(args)
        assert proc.returncode == 2, args
        assert proc.stdout == ""


def test_diffpair_bad_netlist_documents_exit_two():
    work = tempfile.mkdtemp()
    try:
        cases = {
            "not-json.json": "just plain text\n",
            "not-object.json": "[1, 2, 3]",
            "no-boards.json": '{"schema_version": "1.0.0"}',
            "two-boards.json": json.dumps({
                "boards": [
                    {"status": "ok", "board": "a.kicad_pcb", "nets": {}},
                    {"status": "ok", "board": "b.kicad_pcb", "nets": {}},
                ],
            }),
            "board-not-ok.json": json.dumps({
                "boards": [{"status": "unreadable", "error": "file not found"}],
            }),
            "no-nets.json": json.dumps({
                "boards": [{"status": "ok", "board": "a.kicad_pcb"}],
            }),
        }
        for name, text in cases.items():
            path = os.path.join(work, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            proc = _run_cli(["diffpair", "--netlist", path])
            assert proc.returncode == 2, (name, proc.stderr)
            payload = _payload(proc)
            assert payload["status"] == "config_error", name
            assert payload["error"]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_diffpair_bad_board_inputs_exit_two():
    work = tempfile.mkdtemp()
    try:
        wrong_suffix = os.path.join(work, "not_a_board.txt")
        with open(wrong_suffix, "w", encoding="utf-8") as handle:
            handle.write("(whatever)\n")
        garbage = os.path.join(work, "garbage.kicad_pcb")
        with open(garbage, "w", encoding="utf-8") as handle:
            handle.write("just some plain text\n")
        for path in (wrong_suffix, garbage):
            proc = _run_cli(["diffpair", "--board", path])
            assert proc.returncode == 2, path
            payload = _payload(proc)
            assert payload["status"] == "config_error"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_diffpair_never_touches_kicad_cli():
    """diffpair is pure parsing: a bogus KICAD_CLI must not break it."""
    bogus = os.path.join(tempfile.mkdtemp(), "kicad-cli-does-not-exist.exe")
    proc = _run_cli(
        ["diffpair", "--board", CLEAN_PCB], env_overrides={"KICAD_CLI": bogus}
    )
    assert proc.returncode == 0, proc.stderr
    assert _payload(proc)["status"] == "ok"
