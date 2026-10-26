"""Reproducibility smoke check: fixed input -> fixed canonical output.

Runs the pure-parsing subcommands (``netlist``, ``diffpair``) over every
example board twice, asserts the two canonical outputs are byte-identical,
and prints the sha256 digests (first 16 hex chars). ``drc`` is included
when a ``kicad-cli`` is discoverable; it is skipped otherwise. The script
writes nothing into the repository apart from the optional baseline file
(``--baseline``, default ``out/w5/smoke-baseline.json``), so re-running
it is side-effect free.

Usage (from the repository root)::

    python scripts/smoke_check.py [--baseline PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pcb_periph", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO_ROOT,
        timeout=600,
    )


def _double_run(args: list[str]) -> dict:
    with tempfile.TemporaryDirectory() as work:
        out1, out2 = (os.path.join(work, f"run{i}.json") for i in (1, 2))
        first = _run([*args, "--canonical", "--out", out1])
        second = _run([*args, "--canonical", "--out", out2])
        if first.returncode != 0 or second.returncode != 0:
            return {"ok": False, "error": (first.stderr or second.stderr).strip()}
        digest1 = hashlib.sha256(open(out1, "rb").read()).hexdigest()[:16]
        digest2 = hashlib.sha256(open(out2, "rb").read()).hexdigest()[:16]
        return {
            "ok": digest1 == digest2,
            "sha256_16": digest1,
            "byte_identical": digest1 == digest2,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path,
                        default=REPO_ROOT / "out" / "w5" / "smoke-baseline.json",
                        help="where to write the digest table (empty string skips)")
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from pcb_periph.kicad_cli import find_kicad_cli  # noqa: F401

        have_kicad = True
    except Exception:
        have_kicad = False

    results: dict[str, dict] = {}
    boards = sorted(REPO_ROOT.glob("examples/*/*.kicad_pcb"))
    if not boards:
        print("no example boards found under examples/")
        return 2
    for board in boards:
        rel = board.relative_to(REPO_ROOT).as_posix()
        results[f"netlist {rel}"] = _double_run(["netlist", str(board)])
        results[f"diffpair --board {rel}"] = _double_run(["diffpair", "--board", str(board)])
        if have_kicad:
            results[f"drc {rel}"] = _double_run(
                ["drc", str(board), "--raw-dir", os.path.join(tempfile.gettempdir(), "pcb-periph-smoke-raw")]
            )
    schematic = REPO_ROOT / "examples" / "diffpair_showcase" / "diffpair_showcase.kicad_sch"
    if have_kicad and schematic.is_file():
        results[f"erc {schematic.relative_to(REPO_ROOT).as_posix()}"] = _double_run(
            ["erc", str(schematic), "--raw-dir", os.path.join(tempfile.gettempdir(), "pcb-periph-smoke-raw")]
        )

    all_ok = True
    for name, res in results.items():
        if res.get("ok"):
            print(f"{name}: stable, sha256[:16]={res['sha256_16']}")
        else:
            all_ok = False
            print(f"{name}: FAILED ({res.get('error', 'digest drift between runs')})")

    if args.baseline and str(args.baseline):
        payload = {
            "python": sys.version.split()[0],
            "kicad_included": have_kicad,
            "results": results,
            "all_stable": all_ok,
        }
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"baseline written to {args.baseline}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
