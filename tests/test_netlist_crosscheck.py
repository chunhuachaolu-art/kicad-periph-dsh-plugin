"""Cross-check: our s-expr netlist vs the KiCad-bundled pcbnew reader.

The shipped ``pcb_periph`` parser never imports ``pcbnew`` (GPL-licensed);
instead, this test runs ``tests/netlist_pcbnew_probe.py`` as a subprocess
under the KiCad-bundled interpreter and reconciles the two independent
readings of the same board file:

* footprint count, pad count, no-net pad count;
* the set of named nets;
* the full ``pad -> net name`` mapping ("" means no net on both sides);
* declared net count vs pcbnew's net-code count (both include the unnamed
  net 0).

Reconciliation semantics ("no net" handling): a pad whose file node has no
``(net ...)`` child, or references net 0 / an empty net name, is counted as
a no-net pad here; pcbnew reports the same pads with net code 0 and an
empty ``GetNetname()``. Auto-generated ``unconnected-(...)`` nets are real
named nets on both sides. Because the netlist is read from the board file
alone, both sides see a lone board copy identically (bare-board context,
no project file needed).

The test skips when the KiCad interpreter is not available (e.g. CI
machines without a KiCad install); it is a dev-side check, not a release
gate. Override the interpreter location with ``$PCBNEW_PYTHON``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from pcb_periph.netlist import run_netlist  # noqa: E402

CLEAN_PCB = os.path.join(
    REPO_ROOT, "examples", "diffpair_showcase", "diffpair_showcase.kicad_pcb"
)
PROBE = os.path.join(REPO_ROOT, "tests", "netlist_pcbnew_probe.py")
DEFAULT_KICAD_PYTHON = r"F:\kicad\bin\python.exe"


def _kicad_python() -> str:
    candidate = os.environ.get("PCBNEW_PYTHON", DEFAULT_KICAD_PYTHON)
    if not (candidate and os.path.isfile(candidate)):
        raise unittest.SkipTest(
            "KiCad-bundled python not found (set $PCBNEW_PYTHON): "
            + candidate
        )
    return candidate


def test_netlist_matches_pcbnew_reading():
    kicad_python = _kicad_python()
    work = tempfile.mkdtemp()
    try:
        # a lone board copy: protects the fixture directory and exercises
        # the bare-board (no project) context on both sides
        board = os.path.join(work, "diffpair_showcase.kicad_pcb")
        shutil.copyfile(CLEAN_PCB, board)

        payload, exit_code = run_netlist([board], cwd=REPO_ROOT)
        assert exit_code == 0, payload["boards"][0].get("error")
        ours = payload["boards"][0]
        assert ours["status"] == "ok"

        proc = subprocess.run(
            [kicad_python, PROBE, board],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        assert proc.returncode == 0, proc.stderr or proc.stdout
        reference = json.loads(proc.stdout)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # -- count reconciliation -------------------------------------------
    assert ours["stats"]["footprints"] == reference["footprints"]
    assert ours["stats"]["pads"] == reference["pads"]
    assert ours["pads_no_net"] == reference["no_net_pads"]
    # both sides count the unnamed net 0 in their totals
    assert ours["stats"]["nets_declared"] == reference["nets_total_incl_empty"]

    # -- named net sets ---------------------------------------------------
    assert sorted(ours["nets"]) == reference["nets_named"]

    # -- full pad -> net mapping -----------------------------------------
    our_pad_nets = {
        f"{pad['footprint']}-{pad['pad']}": pad["net"]["name"] if pad["net"] else ""
        for pad in ours["pads"]
    }
    assert our_pad_nets == reference["pad_nets"]

    # sanity: the pcbnew side really is pcbnew (not some stub output)
    assert reference["kicad_version"].startswith("10.")
