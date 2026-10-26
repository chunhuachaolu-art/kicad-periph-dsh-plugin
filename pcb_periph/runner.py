"""Run kicad-cli DRC/ERC and build the normalized report payload.

Design notes
------------
* The payload contains **no timestamps**; the only volatile field is the
  top-level ``timing_ms`` which the canonical form strips (see
  :mod:`pcb_periph.canonical`).
* All paths recorded in the payload are *anchors*: forward-slash paths
  relative to the process working directory (absolute only when the input
  lives on a different drive and cannot be relativized).
* Violation buckets use the **native kicad-cli taxonomy only**
  (``severity`` and ``type`` strings exactly as reported). No derived
  classification is applied.
* ``runs > 1`` executes kicad-cli several times and records whether all
  runs produced identical count buckets (``stable``). The default is 1.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from . import TOOL_NAME, __version__
from .canonical import path_anchor

SCHEMA_VERSION = "1.0.0"

STATUS_OK = "ok"
STATUS_UNREADABLE = "unreadable"
STATUS_CONFIG_ERROR = "config_error"
STATUS_TOOL_ERROR = "tool_error"

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_TOOL = 2
EXIT_UNREADABLE = 3

COMMAND_SPEC = {
    "drc": {
        "input_suffix": ".kicad_pcb",
        "kicad_cli_args": ("pcb", "drc"),
        "items_key": "boards",
        "item_path_key": "board",
        "summary_count_key": "boards",
    },
    "erc": {
        "input_suffix": ".kicad_sch",
        "kicad_cli_args": ("sch", "erc"),
        "items_key": "schematics",
        "item_path_key": "schematic",
        "summary_count_key": "schematics",
    },
}


def _raw_report_name(stem: str, command: str, run_index: int) -> str:
    if run_index <= 1:
        return f"{stem}.{command}-raw.json"
    return f"{stem}.{command}-raw.{run_index}.json"


def _tally(entries) -> dict:
    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        severity = str(entry.get("severity", "unknown"))
        vtype = str(entry.get("type", "unknown"))
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_type[vtype] = by_type.get(vtype, 0) + 1
    return {
        "total": len(entries),
        "by_severity": by_severity,
        "by_type": by_type,
    }


def _signature(tally: dict) -> str:
    return json.dumps(tally, sort_keys=True)


def _tail(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    return text[-limit:]


def _run_kicad_cli(
    kicad_cli: str,
    command: str,
    input_abs: str,
    raw_abs: str,
    timeout: float,
) -> dict:
    """Run kicad-cli once; return the parsed raw report dict.

    Raises RuntimeError on tool failure (kicad-cli error, timeout,
    missing or unparseable report).
    """
    argv = [
        kicad_cli,
        *COMMAND_SPEC[command]["kicad_cli_args"],
        "--format",
        "json",
        "--output",
        raw_abs,
        input_abs,
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"kicad-cli timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise RuntimeError(f"kicad-cli failed to execute: {exc}") from exc

    if not os.path.isfile(raw_abs):
        detail = _tail(proc.stderr or proc.stdout)
        raise RuntimeError(
            f"kicad-cli produced no report (exit {proc.returncode}): {detail}"
        )
    try:
        with open(raw_abs, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"kicad-cli report unreadable: {exc}") from exc


def _check_input(path: str, command: str) -> tuple[str | None, str]:
    """Classify unusable inputs; returns (status, error) or (None, '')."""
    if not os.path.exists(path):
        return STATUS_UNREADABLE, "file not found"
    if not os.path.isfile(path):
        return STATUS_UNREADABLE, "not a regular file"
    if not os.access(path, os.R_OK):
        return STATUS_UNREADABLE, "file not readable"
    suffix = COMMAND_SPEC[command]["input_suffix"]
    if not path.lower().endswith(suffix):
        return STATUS_CONFIG_ERROR, f"expected a {suffix} input"
    return None, ""


def _unique_stems(inputs: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    stems = []
    for path in inputs:
        stem = os.path.splitext(os.path.basename(path))[0]
        count = seen.get(stem, 0)
        seen[stem] = count + 1
        stems.append(stem if count == 0 else f"{stem}-{count}")
    return stems


def run_command(
    command: str,
    inputs: list[str],
    *,
    kicad_cli: str,
    kicad_version: str,
    raw_dir: str,
    runs: int = 1,
    timeout: float = 600.0,
    cwd: str | None = None,
) -> tuple[dict, int]:
    """Run *command* (``drc`` or ``erc``) over *inputs*.

    Returns ``(payload, exit_code)`` where the exit code follows the
    documented precedence: 3 (unreadable input) > 2 (tool/config error)
    > 1 (violations found) > 0.
    """
    spec = COMMAND_SPEC[command]
    base = os.path.abspath(cwd or os.getcwd())
    stems = _unique_stems(inputs)

    started = time.perf_counter()
    items = []
    exit_code = EXIT_OK
    total_violations = 0
    total_unconnected = 0
    ok_count = 0

    for path, stem in zip(inputs, stems):
        anchor = path_anchor(path, base)
        item: dict = {spec["item_path_key"]: anchor}

        status, error = _check_input(path, command)
        if status is not None:
            item["status"] = status
            item["error"] = error
            exit_code = max(
                exit_code,
                EXIT_UNREADABLE if status == STATUS_UNREADABLE else EXIT_TOOL,
            )
            items.append(item)
            continue

        tallies = []
        raw_anchors = []
        report = None
        failure = None
        for run_index in range(1, runs + 1):
            raw_name = _raw_report_name(stem, command, run_index)
            raw_abs = os.path.join(raw_dir, raw_name)
            try:
                report = _run_kicad_cli(
                    kicad_cli, command, os.path.abspath(path), raw_abs, timeout
                )
            except RuntimeError as exc:
                failure = str(exc)
                break
            raw_anchors.append(path_anchor(raw_abs, base))
            if command == "drc":
                entries = report.get("violations", [])
            else:
                entries = [
                    violation
                    for sheet in report.get("sheets", [])
                    for violation in sheet.get("violations", [])
                ]
            tallies.append(_tally(entries))

        if failure is not None:
            item["status"] = STATUS_TOOL_ERROR
            item["error"] = failure
            exit_code = max(exit_code, EXIT_TOOL)
            items.append(item)
            continue

        tally = tallies[0]
        item["status"] = STATUS_OK
        item["raw_report"] = raw_anchors[0]
        if runs > 1:
            item["raw_reports"] = raw_anchors
            item["runs"] = runs
            item["stable"] = all(
                _signature(other) == _signature(tally) for other in tallies[1:]
            )
        item["violations"] = tally
        item["ignored_checks"] = len(report.get("ignored_checks", []))
        if command == "drc":
            item["unconnected"] = len(report.get("unconnected_items", []))
            total_unconnected += item["unconnected"]
        else:
            item["sheets"] = len(report.get("sheets", []))
        items.append(item)
        ok_count += 1
        total_violations += tally["total"]
        if tally["total"] > 0 or item.get("unconnected", 0) > 0:
            exit_code = max(exit_code, EXIT_VIOLATIONS)

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    summary = {
        spec["summary_count_key"]: len(inputs),
        f"{spec['summary_count_key']}_ok": ok_count,
        "violations": total_violations,
    }
    if command == "drc":
        summary["unconnected"] = total_unconnected

    payload = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "tool_version": __version__,
        "command": command,
        "kicad_version": kicad_version,
        spec["items_key"]: items,
        "summary": summary,
        # volatile (stripped by the canonical form):
        "timing_ms": elapsed_ms,
    }
    return payload, exit_code
