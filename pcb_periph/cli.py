"""Command line interface: ``python -m pcb_periph {drc,erc,netlist,diffpair} [options] INPUT...``"""

from __future__ import annotations

import argparse
import os
import sys

from . import TOOL_NAME, __version__
from .canonical import dumps, dumps_canonical
from .diffpair import RULE_SETS, run_diffpair
from .kicad_cli import KicadCliError, find_kicad_cli, probe_version
from .netlist import DEFAULT_RULE_SET, run_netlist
from .runner import EXIT_TOOL, run_command

EXIT_CODES_HELP = """\
exit codes:
  0  no violations found
  1  violations found (including unconnected items)
  2  tool or configuration error (kicad-cli not found / failed, bad options)
  3  input file unreadable (missing, not a regular file, unreadable)
"""

NETLIST_EXIT_CODES_HELP = """\
exit codes (netlist):
  0  all boards parsed
  2  configuration error (wrong input suffix, file is not parseable s-expression)
  3  input file unreadable (missing, not a regular file, unreadable)
"""

DIFFPAIR_EXIT_CODES_HELP = """\
exit codes (diffpair):
  0  check completed (zero pairs is still a completed check; unpaired
     halves and suspicious findings do not change the exit code)
  2  input or configuration error (invalid JSON, not a netlist document,
     wrong suffix, not parseable as a .kicad_pcb s-expression)
  3  input file unreadable (missing, not a regular file, unreadable)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Headless KiCad design-check bridge: DRC/ERC via kicad-cli "
            "plus a dependency-free .kicad_pcb netlist parser; emits "
            "normalized JSON and CI-friendly exit codes."
        ),
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"{TOOL_NAME} {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for command, help_text, metavar in (
        ("drc", "Run KiCad board DRC on one or more .kicad_pcb files.", "BOARD"),
        ("erc", "Run KiCad schematic ERC on one or more .kicad_sch files.", "SCHEMATIC"),
    ):
        sub_parser = sub.add_parser(
            command,
            help=help_text,
            description=help_text,
            epilog=EXIT_CODES_HELP,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub_parser.add_argument(
            "inputs",
            nargs="+",
            metavar=metavar,
            help=f"{metavar.capitalize()} file path(s); may be repeated for batch runs",
        )
        sub_parser.add_argument(
            "--out",
            metavar="FILE",
            help="write the JSON report to FILE instead of stdout",
        )
        sub_parser.add_argument(
            "--raw-dir",
            metavar="DIR",
            help=(
                "directory for the raw kicad-cli JSON reports "
                "(default: directory of --out, or the working directory)"
            ),
        )
        sub_parser.add_argument(
            "--canonical",
            action="store_true",
            help=(
                "emit the canonical form (strip volatile fields such as "
                "timing_ms) so that identical inputs+options produce "
                "byte-identical output"
            ),
        )
        sub_parser.add_argument(
            "--runs",
            type=int,
            metavar="N",
            default=1,
            help=(
                "run kicad-cli N times per input and record whether all "
                "runs produced identical counts (default: 1)"
            ),
        )
        sub_parser.add_argument(
            "--timeout",
            type=float,
            metavar="SECONDS",
            default=600.0,
            help="per-run kicad-cli timeout in seconds (default: 600)",
        )
        sub_parser.add_argument(
            "--kicad-cli",
            metavar="PATH",
            help=(
                "explicit kicad-cli executable path (overrides the "
                "KICAD_CLI environment variable)"
            ),
        )

    net_help = (
        "Parse one or more .kicad_pcb files into a general-purpose "
        "netlist JSON (layers, footprints, pads, nets, diffpair "
        "candidates). Pure text parsing -- no kicad-cli, no KiCad "
        "installation needed."
    )
    net_parser = sub.add_parser(
        "netlist",
        help=net_help,
        description=net_help,
        epilog=NETLIST_EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    net_parser.add_argument(
        "inputs",
        nargs="+",
        metavar="BOARD",
        help="Board file path(s); may be repeated for batch runs",
    )
    net_parser.add_argument(
        "--out",
        metavar="FILE",
        help="write the JSON report to FILE instead of stdout",
    )
    net_parser.add_argument(
        "--canonical",
        action="store_true",
        help=(
            "emit the canonical form (strip volatile fields such as "
            "timing_ms) so that identical inputs+options produce "
            "byte-identical output"
        ),
    )
    net_parser.add_argument(
        "--diffpair-rules",
        metavar="NAME",
        default=DEFAULT_RULE_SET,
        choices=sorted(RULE_SETS),
        help=(
            "differential-pair suffix rule set used for the candidate "
            "scan (default: %(default)s; 'none' disables scanning). "
            "'kicad-doc-v1' implements the suffix convention documented "
            "in the KiCad PCB Editor manual: +/- and P/N (P/N both with "
            "a _ - . separator and bare)"
        ),
    )

    diff_help = (
        "Check the differential pairs of one board: pair nets by the "
        "KiCad-documented +/- and P/N suffix convention (rule set "
        "kicad-doc-v1) and report complete pairs, unpaired halves and "
        "suspicious near-pair names. Pure name checking -- no kicad-cli, "
        "no KiCad installation needed."
    )
    diff_parser = sub.add_parser(
        "diffpair",
        help=diff_help,
        description=diff_help,
        epilog=DIFFPAIR_EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source_group = diff_parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--netlist",
        metavar="FILE",
        help=(
            "read the nets from a netlist-subcommand JSON report "
            "(must contain exactly one successfully parsed board)"
        ),
    )
    source_group.add_argument(
        "--board",
        metavar="BOARD",
        help=".kicad_pcb board file (parsed through the netlist pipeline first)",
    )
    diff_parser.add_argument(
        "--out",
        metavar="FILE",
        help="write the JSON report to FILE instead of stdout",
    )
    diff_parser.add_argument(
        "--canonical",
        action="store_true",
        help=(
            "emit the canonical form (strip volatile fields such as "
            "timing_ms) so that identical inputs+options produce "
            "byte-identical output"
        ),
    )
    return parser


def _emit(text: str, out_path: str | None) -> None:
    if out_path:
        parent = os.path.dirname(os.path.abspath(out_path))
        os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        stream = sys.stdout
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass
        stream.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "netlist":
        # Pure text parsing: no kicad-cli discovery, no probes, no auxiliary files.
        payload, exit_code = run_netlist(
            args.inputs, rule_set=args.diffpair_rules
        )
        text = dumps_canonical(payload) if args.canonical else dumps(payload)
        _emit(text, args.out)
        return exit_code

    if args.command == "diffpair":
        # Pure name checking: no kicad-cli discovery, no probes, no auxiliary files.
        payload, exit_code = run_diffpair(
            netlist=args.netlist, board=args.board
        )
        text = dumps_canonical(payload) if args.canonical else dumps(payload)
        _emit(text, args.out)
        return exit_code

    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")

    try:
        kicad_cli = find_kicad_cli(args.kicad_cli)
        kicad_version = probe_version(kicad_cli, timeout=min(args.timeout, 60.0))
    except KicadCliError as exc:
        print(f"{TOOL_NAME}: error: {exc}", file=sys.stderr)
        return EXIT_TOOL

    if args.raw_dir:
        raw_dir = os.path.abspath(args.raw_dir)
    elif args.out:
        raw_dir = os.path.dirname(os.path.abspath(args.out)) or os.getcwd()
    else:
        raw_dir = os.getcwd()
    os.makedirs(raw_dir, exist_ok=True)

    payload, exit_code = run_command(
        args.command,
        args.inputs,
        kicad_cli=kicad_cli,
        kicad_version=kicad_version,
        raw_dir=raw_dir,
        runs=args.runs,
        timeout=args.timeout,
    )

    text = dumps_canonical(payload) if args.canonical else dumps(payload)
    _emit(text, args.out)
    return exit_code
