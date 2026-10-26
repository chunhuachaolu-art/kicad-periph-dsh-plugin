"""Build a dirty-board DRC fixture from a clean example board.

Takes a full copy of a clean example-board directory (``.kicad_pcb`` +
``.kicad_pro``) and raises the board design rule ``min_clearance`` to
5 mm in the copied ``.kicad_pro``, which makes kicad-cli DRC report a
large number of real ``clearance`` violations. The clean example is
never modified.

Usable as a module (``build_dirty(src, dst)`` -- the test suite builds
its dirty fixture in a temp directory at test time, so no dirty board
ships in the repository) or from the command line::

    python tests/make_dirty_fixture.py --src examples/diffpair_showcase --dst <dir>
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

MIN_CLEARANCE = 5.0


def build_dirty(src: Path | str, dst: Path | str, min_clearance: float = MIN_CLEARANCE) -> Path:
    """Copy board directory *src* to *dst* with a 5 mm min clearance."""
    src, dst = Path(src), Path(dst)
    pro_files = list(src.glob("*.kicad_pro"))
    if not pro_files:
        raise FileNotFoundError(f"no .kicad_pro under {src}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    pro = dst / pro_files[0].name
    data = json.loads(pro.read_text(encoding="utf-8"))
    rules = data["board"]["design_settings"]["rules"]
    rules["min_clearance"] = min_clearance
    pro.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return dst


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", type=Path, required=True, help="clean example board directory")
    parser.add_argument("--dst", type=Path, required=True, help="destination directory")
    args = parser.parse_args()
    build_dirty(args.src, args.dst)
    print(f"wrote {args.dst} with min_clearance={MIN_CLEARANCE}")


if __name__ == "__main__":
    main()
