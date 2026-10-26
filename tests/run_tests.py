"""Minimal stdlib test runner for the pytest-style tests in this directory.

The test modules use plain ``test_*`` functions with bare asserts, so they
run unchanged under pytest::

    python -m pytest tests/

This runner exists for environments (such as the development sandbox for
this repository) where pytest cannot be installed; it discovers
``test_*.py`` modules next to it, calls every ``test_*`` callable and
reports pass/fail/skip, exiting nonzero on failure.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load_module(path: str):
    name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    modules = sorted(
        entry for entry in os.listdir(HERE) if entry.startswith("test_") and entry.endswith(".py")
    )
    if not modules:
        print("no test modules found")
        return 1
    passed = failed = skipped = 0
    failures = []
    for entry in modules:
        module = load_module(os.path.join(HERE, entry))
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            func = getattr(module, name)
            if not callable(func):
                continue
            label = f"{entry}::{name}"
            try:
                func()
            except unittest.SkipTest as exc:
                skipped += 1
                print(f"SKIP  {label} ({exc})")
            except Exception:
                failed += 1
                failures.append(label)
                print(f"FAIL  {label}")
                traceback.print_exc()
            else:
                passed += 1
                print(f"PASS  {label}")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
