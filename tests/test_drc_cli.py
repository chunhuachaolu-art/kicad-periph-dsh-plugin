"""End-to-end CLI tests for the drc/erc subcommands (need kicad-cli).

Test boards are the script-generated example boards under ``examples/``
(see README "Example boards"; original content, repository MIT license).
The dirty board is built at test time by copying the showcase example and
raising ``min_clearance`` to 5 mm (``tests/make_dirty_fixture.py``) so
that real DRC violations are reported -- no dirty board ships in the repo.

Notes on determinism: kicad-cli 10.0.5 DRC violation *sets* can vary
slightly between runs on boards with many near-threshold pairs (observed
on a dense third-party board during development), so dirty-board
assertions check bucket consistency rather than exact totals, and the
byte-stability test uses the clean example board whose zero-violation
result is stable.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pcb_periph.canonical import dumps_canonical  # noqa: E402
from pcb_periph.kicad_cli import KicadCliError, find_kicad_cli  # noqa: E402

from make_dirty_fixture import build_dirty  # noqa: E402

CLEAN_PCB = os.path.join(
    REPO_ROOT, "examples", "diffpair_showcase", "diffpair_showcase.kicad_pcb"
)
CLEAN_SCH = os.path.join(
    REPO_ROOT, "examples", "diffpair_showcase", "diffpair_showcase.kicad_sch"
)


def _dirty_pcb() -> str:
    """Build the dirty board once per test session, in a temp directory."""
    global _DIRTY_PCB_CACHE
    try:
        return _DIRTY_PCB_CACHE
    except NameError:
        work = tempfile.mkdtemp(prefix="pcb-periph-dirty-")
        dirty_dir = build_dirty(
            os.path.join(REPO_ROOT, "examples", "diffpair_showcase"),
            os.path.join(work, "diffpair_showcase_dirty"),
        )
        _DIRTY_PCB_CACHE = os.path.join(dirty_dir, "diffpair_showcase.kicad_pcb")
        return _DIRTY_PCB_CACHE


def _need_kicad_cli():
    try:
        find_kicad_cli()
    except KicadCliError:
        raise unittest.SkipTest("kicad-cli not found on this machine")


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
        timeout=600,
    )


def _payload(proc):
    return json.loads(proc.stdout)


def test_version_line_mentions_tool():
    proc = _run_cli(["--version"])
    assert proc.returncode == 0, proc.stderr
    assert "pcb-periph-dsh" in proc.stdout


def test_help_documents_exit_codes():
    proc = _run_cli(["drc", "--help"])
    assert proc.returncode == 0, proc.stderr
    for code, meaning in (
        ("0", "no violations"),
        ("1", "violations found"),
        ("2", "tool or configuration error"),
        ("3", "input file unreadable"),
    ):
        assert code in proc.stdout and meaning in proc.stdout


def test_drc_clean_board_exit_zero():
    _need_kicad_cli()
    with tempfile.TemporaryDirectory() as raw_dir:
        proc = _run_cli(["drc", CLEAN_PCB, "--raw-dir", raw_dir])
    assert proc.returncode == 0, proc.stderr
    payload = _payload(proc)
    assert payload["schema_version"] == "1.0.0"
    assert payload["command"] == "drc"
    assert payload["kicad_version"]
    board = payload["boards"][0]
    assert board["status"] == "ok"
    assert board["board"].endswith("diffpair_showcase.kicad_pcb")
    assert "\\" not in board["board"]
    assert board["violations"]["total"] == 0
    assert payload["summary"]["violations"] == 0


def test_drc_dirty_board_reports_real_counts():
    _need_kicad_cli()
    dirty = _dirty_pcb()
    with tempfile.TemporaryDirectory() as raw_dir:
        proc = _run_cli(["drc", dirty, "--raw-dir", raw_dir])
        assert proc.returncode == 1, proc.stderr
        payload = _payload(proc)
        board = payload["boards"][0]
        assert board["status"] == "ok"
        tally = board["violations"]
        assert tally["total"] > 0
        assert sum(tally["by_severity"].values()) == tally["total"]
        assert sum(tally["by_type"].values()) == tally["total"]
        assert tally["by_severity"].get("error", 0) > 0
        assert tally["by_type"].get("clearance", 0) > 0
        assert payload["summary"]["violations"] == tally["total"]
        # the raw kicad-cli report anchor must point at a real file (anchors
        # are relative to the working directory, or absolute across drives)
        raw_anchor = board["raw_report"]
        raw_path = (
            raw_anchor
            if os.path.isabs(raw_anchor)
            else os.path.normpath(os.path.join(REPO_ROOT, raw_anchor))
        )
        assert os.path.isfile(raw_path), raw_path


def test_drc_batch_over_two_boards():
    _need_kicad_cli()
    dirty = _dirty_pcb()
    with tempfile.TemporaryDirectory() as raw_dir:
        proc = _run_cli(["drc", CLEAN_PCB, dirty, "--raw-dir", raw_dir])
    assert proc.returncode == 1, proc.stderr
    payload = _payload(proc)
    assert payload["summary"]["boards"] == 2
    assert payload["summary"]["boards_ok"] == 2
    totals = [b["violations"]["total"] for b in payload["boards"]]
    assert totals[0] == 0 and totals[1] > 0
    assert payload["summary"]["violations"] == totals[1]


def test_drc_missing_board_exits_three():
    _need_kicad_cli()
    missing = os.path.join(REPO_ROOT, "examples", "no_such_board.kicad_pcb")
    proc = _run_cli(["drc", missing, "--raw-dir", tempfile.mkdtemp()])
    assert proc.returncode == 3, proc.stderr
    board = _payload(proc)["boards"][0]
    assert board["status"] == "unreadable"
    assert "not found" in board["error"]


def test_drc_wrong_suffix_exits_two():
    _need_kicad_cli()
    other = os.path.join(tempfile.mkdtemp(), "not_a_board.txt")
    with open(other, "w", encoding="utf-8") as handle:
        handle.write("(not a board)\n")
    proc = _run_cli(["drc", other])
    assert proc.returncode == 2, proc.stderr
    board = _payload(proc)["boards"][0]
    assert board["status"] == "config_error"


def test_bad_kicad_cli_env_exits_two():
    bogus = os.path.join(tempfile.mkdtemp(), "kicad-cli-does-not-exist.exe")
    proc = _run_cli(["drc", CLEAN_PCB], env_overrides={"KICAD_CLI": bogus})
    assert proc.returncode == 2, proc.stdout
    assert "KICAD_CLI" in proc.stderr


def test_double_run_canonical_output_byte_equal():
    _need_kicad_cli()
    work = tempfile.mkdtemp()
    out1 = os.path.join(work, "run1.json")
    out2 = os.path.join(work, "run2.json")
    raw_dir = os.path.join(work, "raw")
    common = ["drc", CLEAN_PCB, "--canonical", "--raw-dir", raw_dir]
    proc1 = _run_cli([*common, "--out", out1])
    proc2 = _run_cli([*common, "--out", out2])
    assert proc1.returncode == 0 and proc2.returncode == 0, proc1.stderr + proc2.stderr
    bytes1 = open(out1, "rb").read()
    bytes2 = open(out2, "rb").read()
    assert bytes1 == bytes2
    digest = hashlib.sha256(bytes1).hexdigest()
    assert digest == hashlib.sha256(bytes2).hexdigest()
    # a non-canonical run canonicalized in post must reproduce the same bytes
    out3 = os.path.join(work, "run3.json")
    proc3 = _run_cli(["drc", CLEAN_PCB, "--raw-dir", raw_dir, "--out", out3])
    assert proc3.returncode == 0, proc3.stderr
    assert b"timing_ms" not in bytes1
    with open(out3, encoding="utf-8") as handle:
        payload3 = json.load(handle)
    assert payload3["timing_ms"] >= 0
    assert dumps_canonical(payload3).encode("utf-8") == bytes1


def test_erc_clean_schematic_exit_zero():
    _need_kicad_cli()
    with tempfile.TemporaryDirectory() as raw_dir:
        proc = _run_cli(["erc", CLEAN_SCH, "--raw-dir", raw_dir])
    assert proc.returncode == 0, proc.stderr
    payload = _payload(proc)
    assert payload["command"] == "erc"
    sch = payload["schematics"][0]
    assert sch["status"] == "ok"
    assert sch["schematic"].endswith("diffpair_showcase.kicad_sch")
    assert sch["violations"]["total"] == 0
    assert sch["sheets"] >= 1
    assert payload["summary"]["violations"] == 0


def test_erc_missing_input_exits_three():
    _need_kicad_cli()
    missing = os.path.join(REPO_ROOT, "examples", "no_such_sheet.kicad_sch")
    proc = _run_cli(["erc", missing])
    assert proc.returncode == 3, proc.stderr
