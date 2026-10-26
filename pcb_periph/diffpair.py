"""Differential-pair pairing checker (``diffpair`` subcommand core).

The rule set ``kicad-doc-v1`` is a clean-room implementation of the net
naming convention documented in the KiCad 10.0 PCB Editor manual:

    "Differential pairs in KiCad are defined as nets with a common base
    name and a positive and negative suffix. KiCad supports using + and
    −, or P and N as the suffixes."

    https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html

Two suffix groups are recognized, always at the **end** of the net name:

* ``plus_minus`` -- the positive net ends in ``+`` and its counterpart in
  ``-`` (the base is everything before the final character, so
  ``CLK_+``/``CLK_-`` pair on the base ``CLK_`` just like ``CLK+``/``CLK-``).
* ``p_n`` -- the positive net ends in ``P`` and its counterpart in ``N``,
  in two styles:

  - ``separator``: one separator character (``_``, ``-`` or ``.``)
    between base and suffix, e.g. ``DATA_P``/``DATA_N``;
  - ``bare``: the suffix glued directly to the base, e.g. ``DATAP``/
    ``DATAN`` (which also covers multi-level names such as ``USB_DP``/
    ``USB_DN`` pairing on the base ``USB_D``).

A pair is only reported when both nets share the **same base**, the same
suffix group *and* the same suffix style (same separator character);
cross-style names on one base (``DATA_P`` next to ``DATA-N``, or
``DATA_P`` next to ``DATAN``) are reported under ``suspicious`` instead --
for a checker, silently pairing inconsistently suffixed nets would hide
exactly the naming mistake worth flagging.

Boundaries the documentation leaves open are pinned here and covered by
tests (see README "diffpair" for the full decision table):

* matching is **case-sensitive**: only upper-case ``P``/``N`` count, so
  ``DATA_p``/``DATA_n`` is not a pair (and not even suffix-bearing);
* a non-empty base is required: ``+``, ``-``, ``P`` and ``N`` alone are
  not suffix-bearing (``_P`` falls back to the bare style, base ``_``);
* suffixes bind only at the name end -- a ``+`` in the middle of a name
  (``DATA+CLK``) never pairs;
* the symbols are the ASCII ``+``/``-``; the typographic minus used in
  the manual's prose is not a net-name character.

Outputs are fully deterministic: pairs, unpaired halves and suspicious
findings are sorted, and the payload contains no timestamps (the only
volatile field is the top-level ``timing_ms`` stripped by the canonical
form).
"""

from __future__ import annotations

import json
import os
import time

from . import TOOL_NAME, __version__
from .canonical import path_anchor

SCHEMA_VERSION = "1.0.0"

STATUS_OK = "ok"
STATUS_UNREADABLE = "unreadable"
STATUS_CONFIG_ERROR = "config_error"

EXIT_OK = 0
EXIT_TOOL = 2
EXIT_UNREADABLE = 3

#: Name of the documented suffix-convention rule set.
RULE_SET_NAME = "kicad-doc-v1"

SYMBOL_GROUP = "plus_minus"
PN_GROUP = "p_n"
STYLE_SYMBOL = "symbol"
STYLE_SEPARATOR = "separator"
STYLE_BARE = "bare"
POSITIVE = "positive"
NEGATIVE = "negative"

#: Separator characters accepted between the base name and a trailing
#: ``P``/``N`` suffix (pinned: exactly these three).
SUFFIX_SEPARATORS: tuple[str, ...] = ("_", "-", ".")

#: Rule sets accepted by the ``netlist`` candidate scan: the documented
#: convention set, and ``none`` to disable scanning entirely.
RULE_SETS: dict[str, bool] = {RULE_SET_NAME: True, "none": False}


class _InputError(Exception):
    """Carries a status word and message for unusable diffpair inputs."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def suffix_groups() -> list[dict]:
    """Return the suffix-group descriptor embedded in every output."""
    return [
        {
            "group": SYMBOL_GROUP,
            "suffix_style": STYLE_SYMBOL,
            "positive_suffix": "+",
            "negative_suffix": "-",
        },
        {
            "group": PN_GROUP,
            "suffix_style": STYLE_SEPARATOR,
            "positive_suffix": "P",
            "negative_suffix": "N",
            "separators": list(SUFFIX_SEPARATORS),
        },
        {
            "group": PN_GROUP,
            "suffix_style": STYLE_BARE,
            "positive_suffix": "P",
            "negative_suffix": "N",
        },
    ]


def decompose_net_name(name: str) -> dict | None:
    """Decompose *name* into ``base`` + polarity suffix, or ``None``.

    The returned dict carries ``base``, ``group``, ``polarity``,
    ``suffix_style``, ``suffix`` (the full suffix string) and
    ``separator`` (the separator character for the separator style,
    else ``None``). Suffixes bind at the end of the name only, and a
    non-empty base is required.
    """
    if name.endswith("+") and len(name) >= 2:
        return {
            "base": name[:-1],
            "group": SYMBOL_GROUP,
            "polarity": POSITIVE,
            "suffix_style": STYLE_SYMBOL,
            "suffix": "+",
            "separator": None,
        }
    if name.endswith("-") and len(name) >= 2:
        return {
            "base": name[:-1],
            "group": SYMBOL_GROUP,
            "polarity": NEGATIVE,
            "suffix_style": STYLE_SYMBOL,
            "suffix": "-",
            "separator": None,
        }
    if len(name) >= 2 and name[-1] in ("P", "N"):
        polarity = POSITIVE if name[-1] == "P" else NEGATIVE
        if len(name) >= 3 and name[-2] in SUFFIX_SEPARATORS:
            return {
                "base": name[:-2],
                "group": PN_GROUP,
                "polarity": polarity,
                "suffix_style": STYLE_SEPARATOR,
                "suffix": name[-2:],
                "separator": name[-2],
            }
        return {
            "base": name[:-1],
            "group": PN_GROUP,
            "polarity": polarity,
            "suffix_style": STYLE_BARE,
            "suffix": name[-1],
            "separator": None,
        }
    return None


def check_diffpairs(nets: dict[str, int]) -> dict:
    """Pair-check the net names in *nets* (name -> pad count).

    Returns ``{"pairs", "unpaired", "suspicious", "stats"}``:

    * ``pairs`` -- complete pairs: base, both net names, group/style,
      the suffix strings and per-side pad counts;
    * ``unpaired`` -- suffix-bearing nets whose counterpart is missing,
      with polarity and decomposition;
    * ``suspicious`` -- mechanically determinable near-pair clues:

      - ``suffixless_twin``: a plain net named exactly like the base of
        suffix-bearing nets (``DATA`` next to ``DATA_P``/``DATA_N``);
      - ``mixed_suffix_style``: two or more unpaired halves share a base
        but carry different suffix strings (``DATA_P`` next to
        ``DATA-N``, or ``DATA_P`` next to ``DATAN``, or ``DATA_P`` next
        to ``DATA+``) -- inconsistent naming that pairing must not hide.

    * ``stats`` -- the counts summarizing the three lists.
    """
    names = sorted(nets)
    decomposed = {name: decompose_net_name(name) for name in names}
    by_base: dict[str, list[tuple[str, dict]]] = {}
    for name in names:
        part = decomposed[name]
        if part is not None:
            by_base.setdefault(part["base"], []).append((name, part))

    pairs: list[dict] = []
    used: set[str] = set()
    for base in sorted(by_base):
        slots: dict[tuple, dict[str, str]] = {}
        for name, part in by_base[base]:
            key = (part["group"], part["suffix_style"], part["separator"])
            # same base + group + style + polarity implies the same full
            # name, so the slot can hold at most one net
            slots.setdefault(key, {})[part["polarity"]] = name
        for key in sorted(slots, key=lambda item: tuple(str(x) for x in item)):
            slot = slots[key]
            if POSITIVE in slot and NEGATIVE in slot:
                positive, negative = slot[POSITIVE], slot[NEGATIVE]
                part = decomposed[positive]
                pairs.append(
                    {
                        "base": base,
                        "positive": positive,
                        "negative": negative,
                        "group": part["group"],
                        "suffix_style": part["suffix_style"],
                        "separator": part["separator"],
                        "suffixes": {
                            POSITIVE: part["suffix"],
                            NEGATIVE: decomposed[negative]["suffix"],
                        },
                        "pads": {
                            POSITIVE: nets[positive],
                            NEGATIVE: nets[negative],
                        },
                        "pads_total": nets[positive] + nets[negative],
                    }
                )
                used.add(positive)
                used.add(negative)

    unpaired: list[dict] = []
    for name in names:
        part = decomposed[name]
        if part is None or name in used:
            continue
        unpaired.append(
            {
                "net": name,
                "base": part["base"],
                "polarity": part["polarity"],
                "group": part["group"],
                "suffix_style": part["suffix_style"],
                "separator": part["separator"],
                "suffix": part["suffix"],
                "pads": nets[name],
            }
        )

    suffix_nets = {
        base: sorted(name for name, _ in entries)
        for base, entries in by_base.items()
    }
    suspicious: list[dict] = []
    for base in sorted(by_base):
        if base in nets:
            suspicious.append(
                {
                    "kind": "suffixless_twin",
                    "base": base,
                    "net": base,
                    "suffix_nets": suffix_nets[base],
                }
            )
        halves = [
            name for name, _ in by_base[base] if name not in used
        ]
        if len(halves) >= 2:
            halves.sort()
            suspicious.append(
                {
                    "kind": "mixed_suffix_style",
                    "base": base,
                    "nets": halves,
                    "suffixes": [decomposed[name]["suffix"] for name in halves],
                }
            )
    suspicious.sort(key=lambda item: (item["kind"], item["base"]))

    stats = {
        "nets_named": len(names),
        "pairs": len(pairs),
        "nets_in_pairs": 2 * len(pairs),
        "unpaired": len(unpaired),
        "suspicious": len(suspicious),
        "pads_in_pairs": sum(pair["pads_total"] for pair in pairs),
        "pads_in_unpaired": sum(half["pads"] for half in unpaired),
    }
    return {
        "pairs": pairs,
        "unpaired": unpaired,
        "suspicious": suspicious,
        "stats": stats,
    }


def _check_readable(path: str) -> None:
    """Raise :class:`_InputError` (unreadable) for unusable *path*."""
    if not os.path.exists(path):
        raise _InputError(STATUS_UNREADABLE, "file not found")
    if not os.path.isfile(path):
        raise _InputError(STATUS_UNREADABLE, "not a regular file")
    if not os.access(path, os.R_OK):
        raise _InputError(STATUS_UNREADABLE, "file not readable")


def _load_netlist_input(path: str, base: str) -> tuple[dict, dict[str, int]]:
    """Validate a W-2 netlist JSON and derive (input info, pad counts).

    The document must be a netlist-command payload with exactly one
    successfully parsed board item; anything else is a configuration
    error.
    """
    _check_readable(path)
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _InputError(
            STATUS_CONFIG_ERROR, f"not valid JSON: {exc}"
        ) from None
    if not isinstance(doc, dict):
        raise _InputError(
            STATUS_CONFIG_ERROR,
            "not a netlist JSON document: top level is not an object",
        )
    boards = doc.get("boards")
    if not isinstance(boards, list) or not boards:
        raise _InputError(
            STATUS_CONFIG_ERROR,
            "not a netlist JSON document: missing 'boards' list",
        )
    if len(boards) != 1:
        raise _InputError(
            STATUS_CONFIG_ERROR,
            f"expected exactly one board item, found {len(boards)} "
            "(run netlist on a single board, or point --board at the "
            ".kicad_pcb file)",
        )
    item = boards[0]
    if not isinstance(item, dict):
        raise _InputError(
            STATUS_CONFIG_ERROR, "board item is not an object"
        )
    if item.get("status") != STATUS_OK:
        raise _InputError(
            STATUS_CONFIG_ERROR,
            f"netlist board item status is {item.get('status')!r}, "
            "not 'ok'",
        )
    nets = item.get("nets")
    if not isinstance(nets, dict) or not all(
        isinstance(name, str) and isinstance(refs, list)
        for name, refs in nets.items()
    ):
        raise _InputError(
            STATUS_CONFIG_ERROR,
            "netlist board item has no usable 'nets' map",
        )
    input_info = {
        "kind": "netlist",
        "path": path_anchor(path, base),
        "board": item.get("board"),
        "netlist_schema_version": doc.get("schema_version"),
    }
    if isinstance(item.get("source"), dict):
        input_info["source"] = item["source"]
    return input_info, {name: len(refs) for name, refs in nets.items()}


def _load_board_input(path: str, base: str) -> tuple[dict, dict[str, int]]:
    """Parse a .kicad_pcb through the W-2 pipeline; derive pad counts."""
    from .netlist import build_board_item  # deferred: avoids import cycle

    item = build_board_item(path, rule_set="none", base=base)
    status = item.get("status")
    if status == STATUS_UNREADABLE:
        raise _InputError(STATUS_UNREADABLE, item.get("error", "unreadable"))
    if status != STATUS_OK:
        raise _InputError(
            STATUS_CONFIG_ERROR, item.get("error", f"status {status!r}")
        )
    input_info = {
        "kind": "board",
        "path": path_anchor(path, base),
        "source": item.get("source", {}),
    }
    nets = item.get("nets", {})
    return input_info, {name: len(refs) for name, refs in nets.items()}


def run_diffpair(
    *, netlist: str | None = None, board: str | None = None, cwd: str | None = None
) -> tuple[dict, int]:
    """Run the differential-pair check on one input.

    Exactly one of *netlist* (a W-2 netlist JSON) and *board* (a
    ``.kicad_pcb`` parsed through the W-2 pipeline) must be given.
    Returns ``(payload, exit_code)``: 0 check completed (a board with
    zero pairs is a completed check), 2 input/configuration error,
    3 input file unreadable.
    """
    base = os.path.abspath(cwd or os.getcwd())
    started = time.perf_counter()
    try:
        if netlist is not None and board is not None:
            raise _InputError(
                STATUS_CONFIG_ERROR,
                "--netlist and --board are mutually exclusive",
            )
        if netlist is not None:
            input_info, counts = _load_netlist_input(netlist, base)
        elif board is not None:
            input_info, counts = _load_board_input(board, base)
        else:
            raise _InputError(
                STATUS_CONFIG_ERROR,
                "one of --netlist or --board is required",
            )
    except _InputError as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL_NAME,
            "tool_version": __version__,
            "command": "diffpair",
            "status": exc.status,
            "error": exc.message,
            "rule_set": RULE_SET_NAME,
            "input": {
                "kind": "netlist" if netlist is not None else "board",
                "path": path_anchor(netlist or board or "", base),
            },
            "timing_ms": int((time.perf_counter() - started) * 1000),
        }
        exit_code = EXIT_UNREADABLE if exc.status == STATUS_UNREADABLE else EXIT_TOOL
        return payload, exit_code

    check = check_diffpairs(counts)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "tool_version": __version__,
        "command": "diffpair",
        "status": STATUS_OK,
        "rule_set": RULE_SET_NAME,
        "suffix_groups": suffix_groups(),
        "input": input_info,
        "pairs": check["pairs"],
        "unpaired": check["unpaired"],
        "suspicious": check["suspicious"],
        "stats": check["stats"],
        # volatile (stripped by the canonical form):
        "timing_ms": int((time.perf_counter() - started) * 1000),
    }
    return payload, EXIT_OK
