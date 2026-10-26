"""pcbnew-side reference dump for netlist cross-checking (test-side only).

This script MUST run under the KiCad-bundled interpreter, because it
imports ``pcbnew`` -- the GPL-licensed KiCad Python bindings. It is a
development-time cross-check harness and is never imported (or shipped)
by the ``pcb_periph`` package, whose parser is clean-room, pure stdlib.

Usage::

    F:/kicad/bin/python.exe netlist_pcbnew_probe.py BOARD.kicad_pcb

Loads *BOARD* read-only and prints one JSON document on stdout:

* ``kicad_version``  -- build version of the loading pcbnew
* ``footprints``     -- footprint count
* ``pads``           -- total pad count
* ``nets_total_incl_empty`` -- net codes in the board's net info
  (includes the unnamed net 0)
* ``nets_named``     -- sorted list of non-empty net names
* ``no_net_pads``    -- pads on net code 0 / with an empty net name
* ``pad_nets``       -- ``"REF-PAD" -> net name`` ("" means no net)

Exit codes: 0 ok, 2 bad usage, 4 board could not be loaded.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: netlist_pcbnew_probe.py BOARD.kicad_pcb", file=sys.stderr)
        return 2
    path = sys.argv[1]

    import pcbnew  # GPL-licensed: test harness only, never in pcb_periph

    board = pcbnew.LoadBoard(path)
    if board is None:
        print(f"pcbnew could not load: {path}", file=sys.stderr)
        return 4

    pad_nets: dict = {}
    no_net_pads = 0
    footprints = board.GetFootprints()
    for footprint in footprints:
        reference = footprint.GetReference()
        for pad in footprint.Pads():
            name = pad.GetNetname()
            pad_nets[f"{reference}-{pad.GetNumber()}"] = name
            if pad.GetNetCode() == 0 or not name:
                no_net_pads += 1

    nets_by_code = board.GetNetInfo().NetsByNetcode()
    net_names = sorted(item.GetNetname() for item in nets_by_code.values())

    print(
        json.dumps(
            {
                "kicad_version": pcbnew.GetBuildVersion(),
                "footprints": len(footprints),
                "pads": len(pad_nets),
                "nets_total_incl_empty": len(nets_by_code),
                "nets_named": [name for name in net_names if name],
                "no_net_pads": no_net_pads,
                "pad_nets": pad_nets,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
