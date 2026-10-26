"""kicad-cli executable detection and version probing.

Probe order (first match wins, every candidate must be an existing file):

1. ``--kicad-cli`` command line option (highest precedence)
2. ``KICAD_CLI`` environment variable
3. built-in fallback location ``F:\\kicad\\bin\\kicad-cli.exe``
4. ``kicad-cli`` on ``PATH`` (``shutil.which``)

If a candidate is selected but does not exist, that is a configuration error
(exit code 2); there is no silent fall-through past an explicit override.
"""

from __future__ import annotations

import os
import shutil
import subprocess

ENV_VAR = "KICAD_CLI"
BUILTIN_FALLBACKS = (r"F:\kicad\bin\kicad-cli.exe",)


class KicadCliError(Exception):
    """kicad-cli could not be located or executed."""


def _first_existing(paths) -> str | None:
    for path in paths:
        if path and os.path.isfile(path):
            return path
    return None


def find_kicad_cli(explicit: str | None = None) -> str:
    """Return the kicad-cli executable path or raise :class:`KicadCliError`."""
    env_value = os.environ.get(ENV_VAR)
    if explicit:
        if not os.path.isfile(explicit):
            raise KicadCliError(
                f"kicad-cli passed via --kicad-cli does not exist: {explicit}"
            )
        return os.path.abspath(explicit)
    if env_value:
        if not os.path.isfile(env_value):
            raise KicadCliError(
                f"kicad-cli passed via ${ENV_VAR} does not exist: {env_value}"
            )
        return os.path.abspath(env_value)
    builtin = _first_existing(BUILTIN_FALLBACKS)
    if builtin:
        return os.path.abspath(builtin)
    on_path = shutil.which("kicad-cli")
    if on_path:
        return os.path.abspath(on_path)
    raise KicadCliError(
        "kicad-cli not found: set the "
        f"{ENV_VAR} environment variable, pass --kicad-cli, "
        f"or add kicad-cli to PATH (built-in fallbacks tried: "
        + ", ".join(BUILTIN_FALLBACKS)
        + ")"
    )


def probe_version(kicad_cli: str, timeout: float = 60.0) -> str:
    """Return the kicad-cli version string (e.g. ``10.0.5``)."""
    try:
        proc = subprocess.run(
            [kicad_cli, "version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KicadCliError(f"kicad-cli failed to execute: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise KicadCliError(
            f"kicad-cli version probe failed (exit {proc.returncode}): "
            + (detail[-1] if detail else "no output")
        )
    out = (proc.stdout or "").strip()
    if not out:
        raise KicadCliError("kicad-cli version probe returned no output")
    return out.splitlines()[-1].strip().split()[-1]
