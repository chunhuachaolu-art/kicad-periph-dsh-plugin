"""Generate the repository example boards (script-synthesized, deterministic).

Both example boards are original content authored by this repository's
generator: no third-party board files are copied or derived from, so the
examples ship under the repository MIT license with no additional
attribution requirements (the previously used KiCad demo boards are
CC-BY-SA 4.0 and are therefore not redistributable inside an MIT repo).

Outputs (regenerating overwrites in place, byte-for-byte):

* ``examples/diffpair_showcase/`` -- a two-copper-layer board whose net
  names exercise every suffix style of the ``kicad-doc-v1`` differential
  pair convention: ``+``/``-`` symbol tails, ``_P``/``_N``, ``-P``/``-N``
  and ``.P``/``.N`` separator styles, bare ``P``/``N`` tails (including
  a multi-level base), an unpaired half of each style, a suffixless twin,
  a mixed-style near pair, and a ``+``-in-the-middle negative control.
* ``examples/small_mcu/`` -- a second, plainer board (connector, passives,
  one differential pair and one unpaired half).

Each board directory contains a ``.kicad_pcb`` (KiCad 9 file format,
loadable by KiCad 8/9/10), a minimal ``.kicad_pro`` (default design rules)
and, for the showcase board, an empty ``.kicad_sch`` (ERC target).
The dirty DRC fixture is NOT generated here: tests build it on the fly by
copying the showcase project and raising ``min_clearance`` (see
``tests/make_dirty_fixture.py``).

Geometry is column-isolated so every route is a straight F.Cu run in its
own column; with the default rules (0.2 mm clearance) the boards are DRC
clean (0 violations) and fully connected (0 unconnected items).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

# Standard KiCad 2-layer stack: F.Cu/B.Cu + 18 non-copper layers = 20.
LAYERS = [
    (0, "F.Cu", "signal"),
    (31, "B.Cu", "signal"),
    (32, "B.Adhes", "user"),
    (33, "F.Adhes", "user"),
    (34, "B.Paste", "user"),
    (35, "F.Paste", "user"),
    (36, "B.SilkS", "user"),
    (37, "F.SilkS", "user"),
    (38, "B.Mask", "user"),
    (39, "F.Mask", "user"),
    (40, "Dwgs.User", "user"),
    (41, "Cmts.User", "user"),
    (42, "Eco1.User", "user"),
    (43, "Eco2.User", "user"),
    (44, "Edge.Cuts", "user"),
    (45, "Margin", "user"),
    (46, "B.CrtYd", "user"),
    (47, "F.CrtYd", "user"),
    (48, "B.Fab", "user"),
    (49, "F.Fab", "user"),
]

# KiCad's own default board design rules (as written by KiCad 9 for a new
# board); values are tool defaults, not tuned for any experiment.
DEFAULT_RULES = {
    "allow_blind_buried_vias": False,
    "allow_microvias": False,
    "max_error": 0.01,
    "min_clearance": 0.2,
    "min_connection": 0.0,
    "min_copper_edge_clearance": 0.01,
    "min_groove_width": 0.0,
    "min_hole_clearance": 0.0,
    "min_hole_to_hole": 0.25,
    "min_microvia_diameter": 0.508,
    "min_microvia_drill": 0.2032,
    "min_resolved_spokes": 2,
    "min_silk_clearance": 0.0,
    "min_text_height": 0.8,
    "min_text_thickness": 0.08,
    "min_through_hole_diameter": 0.508,
    "min_track_width": 0.2032,
    "min_via_annular_width": 0.05,
    "min_via_diameter": 0.889,
    "solder_mask_to_copper_clearance": 0.0,
    "use_height_for_length_calcs": True,
}


def _uid(seed: str) -> str:
    """Deterministic UUID-shaped id (stable across regenerations)."""
    import hashlib

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


class BoardWriter:
    """Accumulates s-expr lines for one .kicad_pcb file."""

    def __init__(self, title: str):
        self.title = title
        self.lines: list[str] = []
        self._indent = 1
        self._emit("(kicad_pcb")
        self._emit('(version 20241229)')
        self._emit('(generator "pcbnew")')
        self._emit('(generator_version "9.0")')
        self._emit("(general (thickness 1.6) (legacy_teardrops no))")
        self._emit('(paper "A4")')
        self._emit(f'(title_block (title "{title}") (comment 1 "script-generated example board, repository MIT license"))')

    def _emit(self, text: str) -> None:
        pad = "\t" * self._indent
        self.lines.append(pad + text)

    def close_header(self, outline: tuple[float, float, float, float]) -> None:
        self._emit("(layers")
        self._indent += 1
        for index, name, kind in LAYERS:
            self._emit(f'({index} "{name}" {kind})')
        self._indent -= 1
        self._emit(")")
        self._emit("(setup (pad_to_mask_clearance 0) (allow_soldermask_bridges_in_footprints no))")
        x1, y1, x2, y2 = outline
        self._emit(
            f'(gr_rect (start {_fmt(x1)} {_fmt(y1)}) (end {_fmt(x2)} {_fmt(y2)}) '
            f'(stroke (width 0.05) (type solid)) (fill none) (layer "Edge.Cuts") (uuid "{_uid(self.title + '-edge')}"))'
        )

    def net(self, number: int, name: str) -> None:
        self._emit(f'(net {number} "{name}")')

    def smd_resistor(self, ref: str, cx: float, cy: float, net_a: tuple[int, str], net_b: tuple[int, str]) -> None:
        self._emit(f'(footprint "Generated:R_pair_0603" (layer "F.Cu") (uuid "{_uid(ref)}") (at {_fmt(cx)} {_fmt(cy)}) (attr smd)')
        self._indent += 1
        for key, value, y in (("Reference", ref, -1.4), ("Value", "R_pair", 1.4)):
            self._emit(
                f'(property "{key}" "{value}" (at 0 {_fmt(y)} 0) (layer "F.Fab") (uuid "{_uid(ref + key)}") '
                f'(effects (font (size 1 1) (thickness 0.15))))'
            )
        self._emit(
            f'(fp_line (start -1.6 -0.8) (end 1.6 0.8) (stroke (width 0.05) (type solid)) (fill none) '
            f'(layer "F.Fab") (uuid "{_uid(ref + 'fab1')}"))'
        )
        self._emit(
            f'(fp_line (start 1.6 -0.8) (end -1.6 0.8) (stroke (width 0.05) (type solid)) (fill none) '
            f'(layer "F.Fab") (uuid "{_uid(ref + 'fab2')}"))'
        )
        self._emit(
            f'(fp_rect (start -2.0 -1.0) (end 2.0 1.0) (stroke (width 0.05) (type solid)) (fill none) '
            f'(layer "F.CrtYd") (uuid "{_uid(ref + 'crtyd')}"))'
        )
        for pad, (dx, net) in ((1, (-0.75, net_a)), (2, (0.75, net_b))):
            number, name = net
            self._emit(
                f'(pad "{pad}" smd rect (at {_fmt(dx)} 0) (size 0.8 0.75) '
                f'(layers "F.Cu" "F.Paste" "F.Mask") (net {number} "{name}") (pintype "passive"))'
            )
        self._indent -= 1
        self._emit(")")

    def thru_connector(self, ref: str, cx: float, cy: float, pads: list[tuple[float, tuple[int, str] | None]]) -> None:
        self._emit(f'(footprint "Generated:Conn_pin_hdr" (layer "F.Cu") (uuid "{_uid(ref)}") (at {_fmt(cx)} {_fmt(cy)})')
        self._indent += 1
        for key, value, y in (("Reference", ref, -2.4), ("Value", "Conn", 2.4)):
            self._emit(
                f'(property "{key}" "{value}" (at 0 {_fmt(y)} 0) (layer "F.Fab") (uuid "{_uid(ref + key)}") '
                f'(effects (font (size 1 1) (thickness 0.15))))'
            )
        self._emit(
            f'(fp_rect (start {_fmt(-3.5)} -2.0) (end {_fmt(3.5)} 2.0) (stroke (width 0.05) (type solid)) (fill none) '
            f'(layer "F.CrtYd") (uuid "{_uid(ref + 'crtyd')}"))'
        )
        for index, (dx, net) in enumerate(pads, start=1):
            net_clause = ""
            if net is not None:
                number, name = net
                net_clause = f' (net {number} "{name}")'
            self._emit(
                f'(pad "{index}" thru_hole circle (at {_fmt(dx)} 0) (size 1.9 1.9) (drill 1.0) '
                f'(layers "*.Cu" "*.Mask"){net_clause} (pintype "passive"))'
            )
        self._indent -= 1
        self._emit(")")

    def mounting_hole(self, ref: str, cx: float, cy: float) -> None:
        self._emit(f'(footprint "Generated:MountingHole_3p2" (layer "F.Cu") (uuid "{_uid(ref)}") (at {_fmt(cx)} {_fmt(cy)})')
        self._indent += 1
        for key, value, y in (("Reference", ref, -4.0), ("Value", "MH", 4.0)):
            self._emit(
                f'(property "{key}" "{value}" (at 0 {_fmt(y)} 0) (layer "F.Fab") (uuid "{_uid(ref + key)}") '
                f'(effects (font (size 1 1) (thickness 0.15))))'
            )
        self._emit(
            f'(fp_circle (center 0 0) (end 3.6 0) (stroke (width 0.05) (type solid)) (fill none) '
            f'(layer "F.CrtYd") (uuid "{_uid(ref + 'crtyd')}"))'
        )
        self._emit(
            f'(pad "1" thru_hole circle (at 0 0) (size 6 6) (drill 3.2) '
            f'(layers "*.Cu" "*.Mask") (pintype "passive"))'
        )
        self._indent -= 1
        self._emit(")")

    def segment(self, net: int, x1: float, y1: float, x2: float, y2: float) -> None:
        self._emit(
            f'(segment (start {_fmt(x1)} {_fmt(y1)}) (end {_fmt(x2)} {_fmt(y2)}) (width 0.25) '
            f'(layer "F.Cu") (net {net}) (uuid "{_uid(f"seg-{net}-{x1}-{y1}-{x2}-{y2}")}"))'
        )

    def finish(self) -> str:
        return "\n".join(self.lines) + "\n)\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_pro(directory: Path, stem: str) -> None:
    pro = {
        "board": {
            "design_settings": {
                "rules": dict(DEFAULT_RULES),
                # self-contained example boards ship without their source
                # footprint libraries, so the "footprint not found in any
                # library" check is an environment issue, not a board
                # defect -- silence it in the project context
                "rule_severities": {"lib_footprint_issues": "ignore"},
            }
        },
        "meta": {"filename": f"{stem}.kicad_pro"},
    }
    _write(directory / f"{stem}.kicad_pro", json.dumps(pro, indent=2) + "\n")


def _write_sch(directory: Path, stem: str, title: str) -> None:
    text = (
        "(kicad_sch\n"
        '\t(version 20250114)\n'
        '\t(generator "eeschema")\n'
        '\t(generator_version "9.0")\n'
        f'\t(uuid "{_uid(stem + "-sch")}")\n'
        '\t(paper "A4")\n'
        f'\t(title_block (title "{title}") (comment 1 "script-generated example schematic, repository MIT license"))\n'
        "\t(lib_symbols)\n"
        '\t(sheet_instances (path "/" (page "1")))\n'
        ")\n"
    )
    _write(directory / f"{stem}.kicad_sch", text)


def build_showcase() -> None:
    nets = [
        "CLK+", "CLK-", "DATA_P", "DATA_N", "CLK-P", "CLK-N",
        "USB.P", "USB.N", "USB_DP", "USB_DN", "LONE_P", "PIEZO_IN",
        "SENSE+", "AUX_P", "AUX-N", "DATA", "DATA+CLK", "GND", "VCC",
    ]
    ids = {name: number for number, name in enumerate(nets, start=1)}
    n = lambda name: (ids[name], name)  # noqa: E731

    board = BoardWriter("diffpair suffix showcase")
    board.close_header(outline=(10.0, 10.0, 152.0, 60.0))
    board.net(0, "")
    for name in nets:
        board.net(ids[name], name)

    row_y = 35.0
    parts = [
        ("R1", 20.0, ("CLK+", "CLK-")),
        ("R2", 30.0, ("DATA_P", "DATA_N")),
        ("R3", 40.0, ("CLK-P", "CLK-N")),
        ("R4", 50.0, ("USB.P", "USB.N")),
        ("R5", 60.0, ("USB_DP", "USB_DN")),
        ("R6", 70.0, ("LONE_P", "GND")),
        ("R7", 80.0, ("PIEZO_IN", "GND")),
        ("R8", 90.0, ("SENSE+", "GND")),
        ("R9", 100.0, ("AUX_P", "GND")),
        ("R10", 110.0, ("AUX-N", "GND")),
        ("R11", 120.0, ("DATA", "DATA+CLK")),
    ]
    for ref, cx, (a, b) in parts:
        board.smd_resistor(ref, cx, row_y, n(a), n(b))
    # J1 at column 130: pad1 VCC (x=128.75), pad2 GND (x=131.25)
    board.thru_connector("J1", 130.0, row_y, [(-1.25, n("VCC")), (1.25, n("GND"))])
    # C1 above row A at column 20; MH1 right of J1
    board.smd_resistor("C1", 20.0, 20.0, n("VCC"), n("GND"))
    board.mounting_hole("MH1", 144.0, row_y)

    gnd, vcc = ids["GND"], ids["VCC"]
    # VCC: J1 pad1 up the column, left under C1, up into C1 pad1
    board.segment(vcc, 128.75, row_y, 128.75, 21.0)
    board.segment(vcc, 128.75, 21.0, 19.25, 21.0)
    board.segment(vcc, 19.25, 21.0, 19.25, 20.0)
    # GND: column drops from every row-A GND pad to the y=45 trunk
    for _, cx, (a, b) in parts:
        if b == "GND":
            board.segment(gnd, cx + 0.75, row_y, cx + 0.75, 45.0)
    board.segment(gnd, 131.25, row_y, 131.25, 45.0)
    board.segment(gnd, 70.75, 45.0, 135.0, 45.0)
    # GND: C1 pad2 escapes above row A, drops right of J1 into the trunk
    board.segment(gnd, 20.75, 20.0, 20.75, 19.0)
    board.segment(gnd, 20.75, 19.0, 135.0, 19.0)
    board.segment(gnd, 135.0, 19.0, 135.0, 45.0)

    _write(EXAMPLES / "diffpair_showcase" / "diffpair_showcase.kicad_pcb", board.finish())
    _write_pro(EXAMPLES / "diffpair_showcase", "diffpair_showcase")
    _write_sch(EXAMPLES / "diffpair_showcase", "diffpair_showcase", "diffpair suffix showcase")


def build_small_mcu() -> None:
    nets = ["DM_P", "DM_N", "SW_N", "LED_K", "3V3", "GND", "SDA", "SCL"]
    ids = {name: number for number, name in enumerate(nets, start=1)}
    n = lambda name: (ids[name], name)  # noqa: E731

    board = BoardWriter("small mcu breakout")
    board.close_header(outline=(10.0, 10.0, 90.0, 60.0))
    board.net(0, "")
    for name in nets:
        board.net(ids[name], name)

    row_y = 35.0
    parts = [
        ("R1", 20.0, ("DM_P", "DM_N")),
        ("R2", 30.0, ("SW_N", "GND")),
        ("R3", 40.0, ("LED_K", "3V3")),
    ]
    for ref, cx, (a, b) in parts:
        board.smd_resistor(ref, cx, row_y, n(a), n(b))
    # J1 4-pin at column 60, 2.5 mm pin pitch: pads at x = 56.25..63.75
    board.thru_connector(
        "J1", 60.0, row_y, [(-3.75, n("3V3")), (-1.25, n("GND")), (1.25, n("SDA")), (3.75, n("SCL"))]
    )
    board.smd_resistor("C1", 20.0, 20.0, n("3V3"), n("GND"))
    board.mounting_hole("MH1", 78.0, row_y)

    gnd, v33 = ids["GND"], ids["3V3"]
    # 3V3: J1 pad1 up the column, left under C1, up into C1 pad1
    board.segment(v33, 56.25, row_y, 56.25, 21.0)
    board.segment(v33, 56.25, 21.0, 19.25, 21.0)
    board.segment(v33, 19.25, 21.0, 19.25, 20.0)
    # 3V3: branch down to R3 pad2 from the y=21 run
    board.segment(v33, 40.75, 21.0, 40.75, row_y)
    # GND: R2 pad2 drop, J1 pad2 drop, trunk at y=45
    board.segment(gnd, 30.75, row_y, 30.75, 45.0)
    board.segment(gnd, 58.75, row_y, 58.75, 45.0)
    board.segment(gnd, 30.75, 45.0, 68.0, 45.0)
    # GND: C1 pad2 escapes above row A, drops right of J1 into the trunk
    board.segment(gnd, 20.75, 20.0, 20.75, 19.0)
    board.segment(gnd, 20.75, 19.0, 68.0, 19.0)
    board.segment(gnd, 68.0, 19.0, 68.0, 45.0)

    _write(EXAMPLES / "small_mcu" / "small_mcu.kicad_pcb", board.finish())
    _write_pro(EXAMPLES / "small_mcu", "small_mcu")


def main() -> None:
    build_showcase()
    build_small_mcu()
    print(f"wrote example boards under {EXAMPLES}")


if __name__ == "__main__":
    main()
