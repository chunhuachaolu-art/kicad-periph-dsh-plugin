"""Canonical JSON serialization for byte-stable outputs.

The default CLI output may contain volatile fields (wall-clock timing).
The *canonical form* is the same payload with every volatile field removed
and keys sorted, serialized deterministically. For a fixed input board, a
fixed kicad-cli version and a fixed working directory, two runs produce
byte-identical canonical JSON, which makes "fixed input -> fixed sha256"
smoke tests possible.
"""

from __future__ import annotations

import copy
import json
import os

#: Top-level payload fields that vary between runs of the same input and are
#: therefore excluded from the canonical form. This is the complete list --
#: the payload intentionally contains no timestamps of any kind.
VOLATILE_FIELDS: tuple[str, ...] = ("timing_ms",)


def path_anchor(path: str, base: str) -> str:
    """Return *path* as a forward-slash path relative to *base*.

    Falls back to the absolute (forward-slashed) path only when the path
    cannot be relativized, e.g. across drive letters on Windows.
    """
    try:
        rel = os.path.relpath(path, base)
    except ValueError:
        rel = os.path.abspath(path)
    return rel.replace(os.sep, "/")


def canonicalize(payload: dict) -> dict:
    """Return a deep copy of *payload* without volatile fields."""
    result = copy.deepcopy(payload)
    for key in VOLATILE_FIELDS:
        result.pop(key, None)
    return result


def dumps(obj) -> str:
    """Serialize *obj* deterministically (sorted keys, UTF-8, LF-terminated)."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def dumps_canonical(payload: dict) -> str:
    """Deterministic serialization of the canonical form of *payload*."""
    return dumps(canonicalize(payload))
