"""General-purpose netlist extraction from ``.kicad_pcb`` files.

This module implements the ``netlist`` subcommand: it parses a board file
with the pure-stdlib s-expression reader (:mod:`pcb_periph.sexpr`) and
emits a *general-purpose* netlist JSON document -- layers, footprints,
pads with their nets, named nets with their pad reference lists, and
differential-pair candidates found by suffix scanning.

Design notes
------------
* **No KiCad installation is needed.** Unlike ``drc``/``erc`` this command
  never shells out to ``kicad-cli``; parsing is plain text processing.
* The netlist is read from the board file alone, so the result is
  identical whether the board sits in a full project directory (with a
  ``.kicad_pro``) or stands alone -- unlike DRC results (see the README
  section "Board context sensitivity").
* The payload contains **no timestamps**; the only volatile field is the
  top-level ``timing_ms`` stripped by the canonical form.
* Paths recorded in the payload are anchors relative to the working
  directory (see :func:`pcb_periph.canonical.path_anchor`).
* Differential-pair candidates come from the same engine as the
  ``diffpair`` subcommand (:mod:`pcb_periph.diffpair`): the rule set
  ``kicad-doc-v1`` implements the suffix convention documented in the
  KiCad PCB Editor manual (``+``/``-`` and ``P``/``N``, the latter both
  with a ``_``/``-``/``.`` separator and bare). Every output records the
  ``rule_set`` name it was produced with. (Before the ``diffpair``
  command existed, this scan used a minimal ``basic`` rule set with only
  ``+``/``-`` and ``_P``/``_N``; the default switched to
  ``kicad-doc-v1`` when the checker landed -- see README.)
"""

from __future__ import annotations

import os
import time

from . import TOOL_NAME, __version__
from .canonical import path_anchor
from .diffpair import (
    RULE_SET_NAME,
    RULE_SETS,
    check_diffpairs,
    suffix_groups,
)
from .sexpr import SexprError, atom, child, children, parse_file, tag, to_number

SCHEMA_VERSION = "1.0.0"

STATUS_OK = "ok"
STATUS_UNREADABLE = "unreadable"
STATUS_CONFIG_ERROR = "config_error"
STATUS_PARSE_ERROR = "parse_error"

EXIT_OK = 0
EXIT_TOOL = 2
EXIT_UNREADABLE = 3

INPUT_SUFFIX = ".kicad_pcb"

#: Default differential-pair rule set: the documented KiCad suffix
#: convention, implemented in :mod:`pcb_periph.diffpair` and shared with
#: the ``diffpair`` subcommand. ``none`` disables the candidate scan.
DEFAULT_RULE_SET = RULE_SET_NAME


def _resolve_rule_set(rule_set: str) -> str:
    """Validate a rule-set name and return it unchanged."""
    if rule_set not in RULE_SETS:
        known = ", ".join(sorted(RULE_SETS))
        raise ValueError(
            f"unknown diffpair rule set {rule_set!r} (known: {known})"
        ) from None
    return rule_set


def scan_diffpairs(net_names, rule_set=DEFAULT_RULE_SET) -> dict:
    """Scan *net_names* (iterable) for differential-pair candidates.

    Thin adapter over :func:`pcb_periph.diffpair.check_diffpairs`: pad
    counts are not known here, so every net counts one pad. Returns
    ``{"rule_set", "suffix_groups", "pairs", "unpaired", "suspicious"}``.
    """
    _resolve_rule_set(rule_set)
    counts = {name: 1 for name in net_names}
    check = check_diffpairs(counts)
    return {
        "rule_set": rule_set,
        "suffix_groups": suffix_groups(),
        "pairs": check["pairs"],
        "unpaired": check["unpaired"],
        "suspicious": check["suspicious"],
    }


def _footprint_reference(fp_node: list, fallback: str) -> str:
    """Extract the Reference designator from a footprint node.

    KiCad 6+ stores it as ``(property "Reference" "C104" ...)``; legacy
    files used ``(fp_text reference "C104" ...)``. Both are supported.
    """
    for prop in children(fp_node, "property"):
        if atom(prop, 1) == "Reference":
            value = atom(prop, 2)
            if value is not None:
                return value
    for text in children(fp_node, "fp_text"):
        if atom(text, 1) == "reference":
            value = atom(text, 2)
            if value is not None:
                return value
    return fallback


def _position(at_node: list | None) -> dict:
    """Convert an ``(at X Y [angle])`` node to a position dict."""
    position: dict = {}
    if at_node is None:
        return position
    for key, index in (("x", 1), ("y", 2), ("rotation", 3)):
        value = to_number(atom(at_node, index))
        if value is not None:
            position[key] = value
    return position


def _pad_net(pad_node: list, declared_nets: dict[int, str]):
    """Return ``{"id", "name"}`` for a pad node, or ``None`` for no net.

    Net id 0 and empty net names both mean "no net" (the board's unnamed
    residual net); a pad may also carry no ``(net ...)`` child at all.
    """
    net_node = child(pad_node, "net")
    if net_node is None:
        return None
    net_id = to_number(atom(net_node, 1))
    if net_id is None:
        return None
    name = atom(net_node, 2)
    if name is None:
        name = declared_nets.get(net_id, "")
    if net_id == 0 or not name:
        return None
    return {"id": net_id, "name": name}


def build_board_item(
    path: str, *, rule_set=DEFAULT_RULE_SET, base: str | None = None
) -> dict:
    """Parse one board file and return its netlist payload item.

    Raises nothing for unusable inputs; the item carries a ``status`` and
    ``error`` instead (mirroring the ``drc``/``erc`` payload shape).
    """
    rule_set_name = _resolve_rule_set(rule_set)

    item: dict = {"board": path_anchor(path, base or os.getcwd())}
    if not os.path.exists(path):
        item["status"] = STATUS_UNREADABLE
        item["error"] = "file not found"
        return item
    if not os.path.isfile(path):
        item["status"] = STATUS_UNREADABLE
        item["error"] = "not a regular file"
        return item
    if not os.access(path, os.R_OK):
        item["status"] = STATUS_UNREADABLE
        item["error"] = "file not readable"
        return item
    if not path.lower().endswith(INPUT_SUFFIX):
        item["status"] = STATUS_CONFIG_ERROR
        item["error"] = f"expected a {INPUT_SUFFIX} input"
        return item
    try:
        root = parse_file(path)
    except (OSError, ValueError, SexprError) as exc:
        item["status"] = STATUS_PARSE_ERROR
        item["error"] = f"s-expression parse failed: {exc}"
        return item
    if tag(root) != "kicad_pcb":
        item["status"] = STATUS_PARSE_ERROR
        item["error"] = (
            f"not a board file: top-level node is {tag(root)!r}, "
            "expected 'kicad_pcb'"
        )
        return item

    # -- source identification ------------------------------------------
    source: dict = {}
    version = to_number(atom(child(root, "version") or [], 1))
    if version is not None:
        source["version"] = version
    generator = atom(child(root, "generator") or [], 1)
    if generator is not None:
        source["generator"] = generator
    generator_version = atom(child(root, "generator_version") or [], 1)
    if generator_version is not None:
        source["generator_version"] = generator_version

    # -- layers ----------------------------------------------------------
    layers: list[dict] = []
    layers_node = child(root, "layers")
    if layers_node is not None:
        for entry in layers_node[1:]:
            if not isinstance(entry, list) or not entry:
                continue
            index = to_number(atom(entry, 0))
            layer: dict = {"index": index, "name": atom(entry, 1)}
            kind = atom(entry, 2)
            if kind is not None:
                layer["type"] = kind
            nickname = atom(entry, 3)
            if nickname is not None:
                layer["user"] = nickname
            layers.append(layer)

    # -- net declarations (top-level ``(net id "name")`` nodes) ---------
    declared_nets: dict[int, str] = {}
    for net_node in children(root, "net"):
        net_id = to_number(atom(net_node, 1))
        name = atom(net_node, 2)
        if net_id is not None and name is not None:
            declared_nets[net_id] = name

    # -- footprints and pads ---------------------------------------------
    footprints: list[dict] = []
    pads: list[dict] = []
    nets: dict[str, list[str]] = {}
    pads_no_net = 0
    for position, fp_node in enumerate(children(root, "footprint")):
        reference = _footprint_reference(
            fp_node, fallback=f"FP{position}"
        )
        layer_node = child(fp_node, "layer")
        footprint: dict = {
            "reference": reference,
            "library_id": atom(fp_node, 1),
            "layer": atom(layer_node or [], 1) if layer_node else None,
            "position": _position(child(fp_node, "at")),
            "pads": 0,
        }
        for pad_node in children(fp_node, "pad"):
            pad_number = atom(pad_node, 1)
            net = _pad_net(pad_node, declared_nets)
            if net is None:
                pads_no_net += 1
            else:
                nets.setdefault(net["name"], []).append(
                    f"{reference}-{pad_number}"
                )
            pads.append(
                {
                    "footprint": reference,
                    "pad": pad_number,
                    "type": atom(pad_node, 2),
                    "shape": atom(pad_node, 3),
                    "net": net,
                }
            )
            footprint["pads"] += 1
        footprints.append(footprint)

    # -- differential-pair candidates ------------------------------------
    # Same engine as the ``diffpair`` subcommand; ``none`` skips the scan.
    if rule_set_name in RULE_SETS and RULE_SETS[rule_set_name]:
        check = check_diffpairs(
            {name: len(refs) for name, refs in nets.items()}
        )
        diffpair = {
            "rule_set": rule_set_name,
            "suffix_groups": suffix_groups(),
            "pairs": check["pairs"],
            "unpaired": check["unpaired"],
            "suspicious": check["suspicious"],
        }
    else:
        diffpair = {
            "rule_set": rule_set_name,
            "suffix_groups": [],
            "pairs": [],
            "unpaired": [],
            "suspicious": [],
        }

    stats = {
        "layers": len(layers),
        "footprints": len(footprints),
        "pads": len(pads),
        "pads_no_net": pads_no_net,
        "pads_with_net": len(pads) - pads_no_net,
        "nets_declared": len(declared_nets),
        "nets_named": len(nets),
        "diffpair_pairs": len(diffpair["pairs"]),
        "diffpair_unpaired": len(diffpair["unpaired"]),
        "diffpair_suspicious": len(diffpair["suspicious"]),
    }

    item.update(
        {
            "status": STATUS_OK,
            "source": source,
            "layers": layers,
            "footprints": footprints,
            "pads": pads,
            "nets": nets,
            "pads_no_net": pads_no_net,
            "diffpair_candidates": diffpair,
            "stats": stats,
        }
    )
    return item


def run_netlist(
    inputs: list[str], *, rule_set=DEFAULT_RULE_SET, cwd: str | None = None
) -> tuple[dict, int]:
    """Build the netlist payload for *inputs*.

    Returns ``(payload, exit_code)`` with the documented precedence:
    3 (unreadable input) > 2 (suffix/parse error) > 0. There is no
    "violations found" exit for this command.
    """
    base = os.path.abspath(cwd or os.getcwd())
    started = time.perf_counter()
    items = [
        build_board_item(path, rule_set=rule_set, base=base) for path in inputs
    ]
    ok_count = 0
    exit_code = EXIT_OK
    totals: dict[str, int] = {}
    for item in items:
        if item["status"] == STATUS_OK:
            ok_count += 1
            for key, value in item["stats"].items():
                totals[key] = totals.get(key, 0) + value
        elif item["status"] == STATUS_UNREADABLE:
            exit_code = max(exit_code, EXIT_UNREADABLE)
        else:
            exit_code = max(exit_code, EXIT_TOOL)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "tool_version": __version__,
        "command": "netlist",
        "diffpair_rule_set": _resolve_rule_set(rule_set),
        "boards": items,
        "summary": {"boards": len(inputs), "boards_ok": ok_count, **totals},
        # volatile (stripped by the canonical form):
        "timing_ms": int((time.perf_counter() - started) * 1000),
    }
    return payload, exit_code
