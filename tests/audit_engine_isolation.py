"""Engine-isolation audit: identifier-level blacklist comparison (D-J3-1).

Ships with the repository. Compares the identifiers defined by a private
source tree (the engine this tool was clean-room written against -- pass
its root via ``--source-root``; nothing about it is baked into this file)
against every identifier that occurs in the release tree, and fails on any
intersection.

How it works:

* ``--source-root`` is walked for ``*.py`` files; module-level class,
  function and assigned-constant identifiers are collected with the
  ``ast`` module (direct children of module and class bodies only --
  function *locals* are noise, engine symbols live at module level;
  ``__dunder__`` names and ``test_*`` helpers are dropped).
* Generic English words that any PCB tool would legitimately use
  ("netlist", "footprint", "clearance", ...), plus names our public
  JSON schema shares with generic tooling ("schema_version",
  "kicad_version", ...), are excluded as bare words. Operationally a
  blacklist entry must be a *compound* identifier (underscore or
  camel-hump joined) at least 8 characters long with at least one
  component outside the stopword list -- single English words like
  "append" or "reader" and all-generic compounds like "schema_version"
  are vocabulary, not engine symbols, while made-up compounds such as
  "execute_widget" or "WidgetExecutorError" would be kept.
* The release tree (repo root minus ``out/``, ``venv/``, ``.git/``,
  caches and the internal PROGRESS ledger) is scanned: ``*.py``
  identifiers come from ``tokenize`` NAME tokens, other text files
  (``*.md``, ``*.json``, ``*.txt``, ``*.sch``) contribute word tokens.
* Any blacklist identifier occurring in the release tree is reported and
  the process exits 1; a clean run exits 0 and writes the comparison
  report (``out/audit/engine-isolation.json`` by default).

Example::

    python tests/audit_engine_isolation.py --source-root /path/to/engine
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import tokenize
from pathlib import Path

# Words excluded from the blacklist: generic domain/tool vocabulary that a
# clean-room implementation of the same public task is expected to share.
STOPWORDS = {
    "about", "absolute", "anchor", "args", "author", "base", "block",
    "board", "boards", "boards_ok", "build", "cache", "canonical",
    "check", "checks", "child", "class", "clean", "clearance", "cli",
    "code", "command", "common", "compare", "config", "content",
    "context", "copy", "count", "counts", "current", "custom", "data",
    "default", "describe", "description", "detector", "dict", "digest",
    "display", "document", "drill", "dump", "duplicate", "duration",
    "edge", "emit", "empty", "enable", "entry", "error", "errors",
    "exists", "exit", "expect", "expected", "extract", "field", "fields",
    "file", "files", "filter", "find", "first", "flag", "format",
    "found", "generate", "generated", "generator", "group", "groups",
    "handle", "header", "help", "hole", "id", "index", "info", "input",
    "instance", "item", "items", "iter", "key", "keys", "kicad",
    "kicad_cli", "kicad_version", "layer", "layers", "layout", "lead",
    "line", "lines", "list", "load", "loaded", "local", "lock", "main",
    "make", "manifest", "map", "mask", "match", "matched", "matches",
    "matching", "matrix", "merge", "message", "metadata", "method",
    "min_clearance", "mode", "model", "module", "name", "named",
    "names", "net", "nets", "netlist", "none", "norm", "note", "number",
    "object", "open", "option", "options", "order", "origin", "other", "out",
    "output", "pack", "pad", "pads", "page", "pair", "pairs", "parse",
    "parser", "parsing", "path", "paths", "pattern", "pin", "pins",
    "pitch", "place", "plain", "point", "points", "pool", "port",
    "position", "positive", "positive_suffix", "prefix", "prepare",
    "present", "pretty", "primary", "print", "probe", "process",
    "profile", "property", "raw_report", "read", "report", "reports", "result",
    "results", "return", "review", "root", "row", "rule", "rules",
    "run_drc", "runner", "run", "runs", "runtime", "safe", "sample",
    "scan", "schema", "schema_version", "script", "search", "secondary",
    "segment", "segments", "select", "selection", "semantic",
    "separator", "sequence", "serial", "series", "set", "shape",
    "share", "sheet", "sheets", "short", "signal", "silent", "size",
    "skip", "slot", "smoke", "sort", "sorted", "source", "span",
    "spec", "stable", "stack", "stage", "standard", "start", "state",
    "stats", "status", "stderr", "stdout", "step", "stop", "store",
    "stream", "string", "style", "summary", "support", "symbol",
    "system", "table", "tag", "target", "temp", "template", "term",
    "test", "tests", "text", "thread", "threshold", "time", "timing",
    "timing_ms", "title", "token", "tokens", "tool", "tools", "top",
    "total", "track", "tracks", "tree", "true", "type", "types",
    "unconnected", "update", "usage", "used", "user", "value",
    "values", "variant", "vendor", "verify", "version", "via", "vias",
    "violation", "violations", "walk", "warn", "warning", "width",
    "wire", "work", "write", "zone",
}

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SCAN_EXCLUDE_DIRS = {"out", "venv", ".git", ".pytest_cache", "__pycache__", "node_modules"}
_SCAN_EXCLUDE_FILES = {"PROGRESS.md"}
_SCAN_SUFFIXES = {".py", ".md", ".json", ".txt", ".sch"}


def _collect(names: set[str], node: ast.AST) -> None:
    """Add the identifiers *node* defines at this level (no recursion)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(node.name)
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Tuple):
                for element in target.elts:
                    if isinstance(element, ast.Name):
                        names.add(element.id)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names.add(node.target.id)


_CAMEL_RE = re.compile(r"[a-z][A-Z]")


def _generic_identifier(name: str) -> bool:
    """True when *name* is bare vocabulary rather than an engine symbol."""
    if len(name) < 8 or name.lower() in STOPWORDS or name.startswith("test_"):
        return True
    snake = re.split(r"_+", name)
    parts = []
    for piece in snake:
        parts.extend(p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z0-9]+", piece) if p)
    meaningful = [p for p in parts if len(p) >= 3]
    if len(meaningful) < 2:
        return True
    return all(p in STOPWORDS for p in meaningful)


def extract_source_identifiers(root: Path) -> set[str]:
    """Module-level class/function/constant identifiers under *root*."""
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            _collect(found, node)
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    _collect(found, child)
    return {
        name
        for name in found
        if not (name.startswith("__") and name.endswith("__"))
        and not _generic_identifier(name)
    }


def release_identifiers(root: Path) -> dict[str, set[str]]:
    """Map release-tree file -> identifier/word tokens found in it."""
    tokens_by_file: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        if any(part in _SCAN_EXCLUDE_DIRS for part in path.parts):
            continue
        if path.name in _SCAN_EXCLUDE_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".py":
            names = set()
            reader = tokenize.generate_tokens(
                iter(text.splitlines(keepends=True)).__next__
            )
            try:
                for token in reader:
                    if token.type == tokenize.NAME:
                        names.add(token.string)
            except (tokenize.TokenError, IndentationError):
                pass
            tokens_by_file[path.relative_to(root).as_posix()] = names
        else:
            tokens_by_file[path.relative_to(root).as_posix()] = set(_WORD_RE.findall(text))
    return tokens_by_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-root", type=Path, required=True,
                        help="root of the private engine source tree to blacklist")
    parser.add_argument("--scan-root", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="release tree to scan (default: repository root)")
    parser.add_argument("--out", type=Path, default=None,
                        help="report path (default: <scan-root>/out/audit/engine-isolation.json)")
    args = parser.parse_args()

    blacklist = extract_source_identifiers(args.source_root)
    tokens_by_file = release_identifiers(args.scan_root)

    hits: dict[str, list[str]] = {}
    for file, tokens in sorted(tokens_by_file.items()):
        matched = sorted(tokens & blacklist)
        if matched:
            hits[file] = matched

    report = {
        "source_root": str(args.source_root),
        "blacklist_size": len(blacklist),
        "scanned_files": len(tokens_by_file),
        "hit_files": len(hits),
        "hits": hits,
        "verdict": "PASS" if not hits else "FAIL",
    }
    out = args.out or (args.scan_root / "out" / "audit" / "engine-isolation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"blacklist={report['blacklist_size']} scanned={report['scanned_files']} "
          f"hits={report['hit_files']} verdict={report['verdict']}")
    for file, matched in hits.items():
        print(f"  {file}: {', '.join(matched)}")
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
