# pcb-periph-dsh

[Read this in 中文](README.zh.md)

A headless KiCad design-check bridge for CI: wraps `kicad-cli` DRC/ERC,
emits **normalized JSON** violation counts and **CI-friendly exit codes**,
parses `.kicad_pcb` files into a **general-purpose netlist JSON**
(layers, footprints, pads, nets, differential-pair candidates) with a
dependency-free s-expression reader, and **checks differential-pair
naming** against the suffix convention documented in the KiCad manual.
No MCP server, no running engineering application, no GUI — just a
command line you can drop into any pipeline.

- Python >= 3.13, standard library only (zero runtime dependencies)
- `drc`/`erc` work with any KiCad that ships `kicad-cli` (developed and
  pinned against KiCad 10.0.5); `netlist` and `diffpair` need **no KiCad
  at all**

## Install / run

```
# create the project virtual environment (any Python >= 3.13)
python -m venv venv
venv/Scripts/python -m pcb_periph --help      # Windows
venv/bin/python -m pcb_periph --help          # POSIX
```

### kicad-cli discovery

The executable is probed in this order; the first candidate that exists
wins, and an explicitly selected candidate that does not exist is a hard
configuration error (exit code 2) — no silent fall-through:

1. `--kicad-cli PATH` command line option
2. `KICAD_CLI` environment variable
3. built-in fallback location `F:\kicad\bin\kicad-cli.exe`
4. `kicad-cli` found on `PATH`

### Board context sensitivity (important)

Running DRC on a **bare `.kicad_pcb`** applies the constraint set embedded
in the board file (or KiCad defaults); running it on a board that is part
of a **full project** (with `.kicad_pro` present in its directory) loads
the project's constraint set — including DRC severity overrides — instead.
The same board can legitimately report very different violation counts
between the two modes — e.g. the `diffpair_showcase` example board
measures **0 violations as a full project, 14 warnings as a bare file**
on KiCad 10.0.5 (the project context ignores the
`lib_footprint_issues` check because the example ships without its source
footprint libraries; a development-time observation on a third-party board
showed the same effect in the opposite direction: 69 violations bare,
0 in its full project). Pick the input that matches the check you want;
batch mode accepts either.

`netlist` is **not** affected by this distinction: the netlist lives
entirely inside the `.kicad_pcb` file, so a bare board copy parses to
exactly the same netlist content as the board inside its full project
directory (covered by an explicit test). No `.kicad_pro`, no
`.kicad_prl`, no project context is read.

## Usage

```
pcb-periph-dsh drc [--out FILE] [--raw-dir DIR] [--canonical]
                   [--runs N] [--timeout SECONDS] [--kicad-cli PATH]
                   BOARD [BOARD ...]

pcb-periph-dsh erc [same options] SCHEMATIC [SCHEMATIC ...]

pcb-periph-dsh netlist [--out FILE] [--canonical]
                       [--diffpair-rules NAME]
                       BOARD [BOARD ...]

pcb-periph-dsh diffpair (--netlist FILE | --board BOARD)
                        [--out FILE] [--canonical]
```

Examples:

```
# single board, JSON to stdout
python -m pcb_periph drc myboard.kicad_pcb

# batch, canonical JSON to a file, raw reports kept next to it
python -m pcb_periph drc a.kicad_pcb b.kicad_pcb \
    --out reports/drc.json --canonical

# schematic ERC with a three-run stability check
python -m pcb_periph erc top.kicad_sch --runs 3 --out reports/erc.json

# typical CI gate
pcb-periph-dsh drc board.kicad_pcb --canonical --out drc.json \
    && echo "clean" || echo "DRC findings or error (see drc.json)"

# netlist extraction (no KiCad installation needed at all)
python -m pcb_periph netlist board.kicad_pcb --canonical --out netlist.json

# differential-pair check: straight from a board file...
python -m pcb_periph diffpair --board board.kicad_pcb

# ...or from a netlist JSON produced above
python -m pcb_periph diffpair --netlist netlist.json --canonical --out dp.json
```

### Options

| Option | Meaning |
|---|---|
| `--out FILE` | write the JSON report to `FILE` instead of stdout |
| `--raw-dir DIR` | directory for raw kicad-cli JSON reports (default: directory of `--out`, else the working directory) |
| `--canonical` | emit the canonical form (strip volatile fields) — see *Determinism* |
| `--runs N` | run kicad-cli N times per input and record whether all runs produced identical counts (default 1) |
| `--timeout SECONDS` | per-run kicad-cli timeout (default 600) |
| `--kicad-cli PATH` | explicit kicad-cli executable path |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | no violations found (unconnected items are also zero) |
| 1 | violations found (including unconnected items) |
| 2 | tool or configuration error: kicad-cli not found / failed, wrong input suffix, bad options |
| 3 | input file unreadable: missing, not a regular file, no read permission |

When several inputs are given, the worst result wins:
`3 (unreadable) > 2 (tool/config) > 1 (violations) > 0`.

## Output JSON schema (`schema_version` 1.0.0)

`drc` produces:

```json
{
  "schema_version": "1.0.0",
  "tool": "pcb-periph-dsh",
  "tool_version": "0.1.0",
  "command": "drc",
  "kicad_version": "10.0.5",
  "boards": [
    {
      "status": "ok",
      "board": "examples/diffpair_showcase/diffpair_showcase.kicad_pcb",
      "raw_report": "out/demo/diffpair_showcase.drc-raw.json",
      "violations": {
        "total": 25,
        "by_severity": { "error": 25 },
        "by_type": { "clearance": 25 }
      },
      "unconnected": 0,
      "ignored_checks": 6
    }
  ],
  "summary": { "boards": 1, "boards_ok": 1, "violations": 25, "unconnected": 0 },
  "timing_ms": 6100
}
```

(the excerpt above is the showcase example with its minimum clearance
raised to 5 mm — the "dirty board" built by
`tests/make_dirty_fixture.py`; the untouched board reports 0 violations)

`erc` produces the same shape with `schematics[]` items; each item has a
`sheets` count instead of `unconnected`, and violations are aggregated
across all sheets of the schematic.

Field notes:

- **Buckets use the native kicad-cli taxonomy only.** `by_severity` and
  `by_type` count the `severity`/`type` strings exactly as kicad-cli
  reports them (e.g. `error`, `warning`; `clearance`,
  `copper_edge_clearance`, `lib_footprint_issues`). No derived
  classification, no re-interpretation — for locations and full detail,
  read the raw report referenced by `raw_report`.
- **Path anchors.** `board` and `raw_report` are forward-slash paths
  relative to the process working directory; if a path cannot be
  relativized (e.g. a different drive letter on Windows), the absolute
  path is recorded instead.
- **Failed inputs stay in the payload.** An unusable input appears as
  `{"status": "unreadable" | "config_error" | "tool_error", "error": "..."}`
  instead of an `ok` entry, and the exit code reflects the worst status.

## Netlist extraction (`netlist`)

`netlist` parses `.kicad_pcb` files with a clean-room, pure-stdlib
s-expression reader and emits a **general-purpose netlist JSON** — no
`kicad-cli`, no KiCad installation, no project context. Reading the
`diffpair_showcase` example board takes well under 0.1 s; a ~900 KB
third-party board takes ~0.4 s.

| Option | Meaning |
|---|---|
| `--out FILE` | write the JSON report to FILE instead of stdout |
| `--canonical` | emit the canonical form (strip volatile fields) — see *Determinism* |
| `--diffpair-rules NAME` | differential-pair suffix rule set for the candidate scan (default `kicad-doc-v1`, the set documented in the KiCad PCB Editor manual and shared with the `diffpair` command; `none` disables) |

Exit codes: `0` all boards parsed, `2` configuration error (wrong input
suffix, not parseable as a `.kicad_pcb` s-expression), `3` input file
unreadable. There is no "violations found" code — this is a reader, not
a checker. When several inputs are given, the worst result wins
(`3 > 2 > 0`), and unusable inputs stay in the payload with a `status`
and `error` instead of an `ok` entry.

### Output JSON schema (`schema_version` 1.0.0)

```json
{
  "schema_version": "1.0.0",
  "tool": "pcb-periph-dsh",
  "tool_version": "0.1.0",
  "command": "netlist",
  "diffpair_rule_set": "kicad-doc-v1",
  "boards": [
    {
      "status": "ok",
      "board": "examples/diffpair_showcase/diffpair_showcase.kicad_pcb",
      "source": { "version": 20241229, "generator": "pcbnew",
                  "generator_version": "9.0" },
      "layers": [
        { "index": 0, "name": "F.Cu", "type": "signal" }
      ],
      "footprints": [
        { "reference": "R2", "library_id": "Generated:R_pair_0603",
          "layer": "F.Cu", "position": { "x": 30, "y": 35 }, "pads": 2 }
      ],
      "pads": [
        { "footprint": "R2", "pad": "1", "type": "smd",
          "shape": "rect", "net": { "id": 3, "name": "DATA_P" } }
      ],
      "nets": { "GND": ["R6-2", "R7-2", "R8-2", "R9-2", "R10-2", "J1-2", "C1-2"] },
      "pads_no_net": 1,
      "diffpair_candidates": {
        "rule_set": "kicad-doc-v1",
        "suffix_groups": [ { "group": "plus_minus", "suffix_style": "symbol",
                             "positive_suffix": "+", "negative_suffix": "-" },
                           { "group": "p_n", "suffix_style": "separator",
                             "positive_suffix": "P", "negative_suffix": "N",
                             "separators": ["_", "-", "."] },
                           { "group": "p_n", "suffix_style": "bare",
                             "positive_suffix": "P", "negative_suffix": "N" } ],
        "pairs": [ { "base": "CLK", "positive": "CLK-P", "negative": "CLK-N",
                     "pads": { "positive": 1, "negative": 1 }, "...": "group/style/suffixes" } ],
        "unpaired": [ { "net": "PIEZO_IN", "base": "PIEZO_I",
                        "polarity": "negative", "suffix_style": "bare", "...": "group/separator/suffix/pads" },
                      { "net": "SENSE+", "...": "symbol-style positive half" } ]
      },
      "stats": { "layers": 20, "footprints": 14, "pads": 27,
                 "pads_no_net": 1, "pads_with_net": 26,
                 "nets_declared": 20, "nets_named": 19,
                 "diffpair_pairs": 5, "diffpair_unpaired": 5,
                 "diffpair_suspicious": 2 }
    }
  ],
  "summary": { "boards": 1, "boards_ok": 1, "...": "sums of all stats keys" },
  "timing_ms": 147
}
```

Field notes:

- **`layers`** entries carry the copper/technical layer `index`, `name`
  and `type` exactly as declared in the board's `(layers ...)` node, plus
  the optional user nickname.
- **`pads`** is a flat, file-order list; `type` is the pad technology
  (`thru_hole`, `smd`, ...), `shape` the pad shape (`rect`, `oval`, ...).
- **`net`** is `null` for pads without a net; pads referencing the
  unnamed net 0 or an empty net name also count as no-net.
- **`nets`** maps each *named* net to its `"REF-PAD"` reference list in
  file order; `pads_no_net` counts the remainder. Auto-generated
  `unconnected-(...)` nets are ordinary named nets on both this side and
  KiCad's own reader.
- **`diffpair_candidates`** is a name-suffix scan over named nets only —
  the same engine as the `diffpair` subcommand (rule set
  `kicad-doc-v1`, see the *Differential-pair check* section below for
  the full rule semantics and the pinned boundary decisions).
  **Change note:** before the `diffpair` command existed, the scan used
  a minimal `basic` rule set (`+`/`-` and `_P`/`_N` only); the default
  switched to the documented full convention set when the checker
  landed, so older outputs with `diffpair_rule_set: "basic"` predate it.
  `pairs`/`unpaired` carry base names, polarity and pad counts;
  `unpaired` lists suffix-bearing nets whose counterpart is missing —
  under the full convention set that includes bare-P/N names, e.g. the
  example board's `SENSE+` symbol-style half **and** its `PIEZO_IN` net
  (a bare-`N` half, base `PIEZO_I`). Auto-generated names such as
  `Net-(U201B-+)` end with `)` and are therefore not suffix-bearing.
  The Python API offers the same set (`pcb_periph.diffpair.RULE_SETS`,
  `check_diffpairs`) plus a name-only adapter
  (`pcb_periph.netlist.scan_diffpairs`).
- **`stats`** counts agree with the payload contents (sum of pad lists =
  `pads_with_net`, etc.) and the `summary` block sums them over all
  boards.
- **Determinism** works exactly as for `drc`/`erc`: no timestamps, only
  `timing_ms` volatile, canonical form byte-identical across runs of the
  same input+options+working directory — the example-board smoke digest is
  `sha256: 8933a0dd847179c6...` (first 16 hex chars, pinned against
  KiCad 10.0.5-parsed input).

**Cross-validation:** the parser output is reconciled against KiCad's own
`pcbnew` reader in the test suite (footprint/pad/net counts and the full
pad-to-net mapping). That comparison is a development-side harness only —
the GPL-licensed `pcbnew` module is imported exclusively by a test script
and never by the shipped package, whose parser is clean-room and
dependency-free.

## Differential-pair check (`diffpair`)

`diffpair` pair-checks the named nets of one board against the
differential-pair naming convention documented in the KiCad PCB Editor
manual (rule set **`kicad-doc-v1`**) and reports complete pairs, unpaired
halves and suspicious near-pair names — with per-net pad counts taken
from the netlist, so a "pair" whose two nets have wildly different pad
counts is easy to spot. Pure name checking: no `kicad-cli`, no KiCad
installation, no project context.

Two input paths, exactly one per invocation (they are mutually
exclusive):

- `--board BOARD.kicad_pcb` — parse the board through the `netlist`
  pipeline first, then check;
- `--netlist FILE` — read the nets from a `netlist`-subcommand JSON
  report (must contain exactly one successfully parsed board; the
  canonical form of that report is a fine input).

Both paths produce the same check result (covered by an explicit test).

| Option | Meaning |
|---|---|
| `--netlist FILE` | read nets from a netlist-subcommand JSON report |
| `--board BOARD` | read nets from a `.kicad_pcb` file (netlist pipeline first) |
| `--out FILE` | write the JSON report to FILE instead of stdout |
| `--canonical` | emit the canonical form (strip volatile fields) — see *Determinism* |

Exit codes: `0` check completed — **a board with zero pairs is still a
completed check**, and unpaired halves or suspicious findings do not
change the exit code; `2` input/configuration error (invalid JSON, not a
netlist document, wrong suffix, not parseable as a `.kicad_pcb`
s-expression); `3` input file unreadable. Gate on the JSON fields, not
the exit code, when you want to fail on findings.

### Output JSON schema (`schema_version` 1.0.0)

```json
{
  "schema_version": "1.0.0",
  "tool": "pcb-periph-dsh",
  "tool_version": "0.1.0",
  "command": "diffpair",
  "status": "ok",
  "rule_set": "kicad-doc-v1",
  "suffix_groups": [ { "group": "plus_minus", "suffix_style": "symbol",
                       "positive_suffix": "+", "negative_suffix": "-" },
                     { "group": "p_n", "suffix_style": "separator",
                       "positive_suffix": "P", "negative_suffix": "N",
                       "separators": ["_", "-", "."] },
                     { "group": "p_n", "suffix_style": "bare",
                       "positive_suffix": "P", "negative_suffix": "N" } ],
  "input": { "kind": "board", "path": "examples/diffpair_showcase/diffpair_showcase.kicad_pcb",
             "source": { "version": 20241229, "generator": "pcbnew",
                         "generator_version": "9.0" } },
  "pairs": [
    { "base": "CLK", "positive": "CLK-P", "negative": "CLK-N",
      "group": "p_n", "suffix_style": "separator", "separator": "-",
      "suffixes": { "positive": "-P", "negative": "-N" },
      "pads": { "positive": 1, "negative": 1 }, "pads_total": 2 }
  ],
  "unpaired": [
    { "net": "LONE_P", "base": "LONE", "polarity": "positive",
      "group": "p_n", "suffix_style": "separator", "separator": "_",
      "suffix": "_P", "pads": 1 }
  ],
  "suspicious": [
    { "kind": "suffixless_twin", "base": "DATA", "net": "DATA",
      "suffix_nets": ["DATA_N", "DATA_P"] }
  ],
  "stats": { "nets_named": 19, "pairs": 5, "nets_in_pairs": 10,
             "unpaired": 5, "suspicious": 2, "pads_in_pairs": 10,
             "pads_in_unpaired": 5 },
  "timing_ms": 402
}
```

Field notes:

- **`pairs`** are complete pairs: common base, both net names, the
  suffix group/style that matched, the actual suffix strings and
  per-side pad counts. Sorted by base.
- **`unpaired`** are suffix-bearing nets whose counterpart is missing —
  net, base, polarity (`positive`/`negative`), decomposition and pad
  count. Sorted by net.
- **`suspicious`** lists mechanically determinable near-pair clues:
  `suffixless_twin` (a plain net named exactly like the base of
  suffix-bearing nets, e.g. `DATA` next to `DATA_P`/`DATA_N`) and
  `mixed_suffix_style` (two or more unpaired halves share a base but
  carry different suffix strings, e.g. `DATA_P` next to `DATA-N`,
  `DATA_P` next to `DATAN`, or `DATA_P` next to `DATA+`).
- **`input`** records the provenance: `kind` (`board`/`netlist`), the
  path anchor relative to the working directory, the board source header
  (when known), and — for the `netlist` kind — the board anchor and the
  netlist report's `schema_version`.
- Unusable inputs produce `{"status": "unreadable" | "config_error",
  "error": "..."}` instead of the check fields, with exit code 3/2.
- **Determinism** as everywhere else: no timestamps, only `timing_ms`
  volatile; the canonical form of a fixed input+options+working
  directory is byte-identical across runs (example-board smoke digest
  via `--board`: `sha256: baf24005afa1757b...`, first 16 hex chars; the
  `--netlist` path yields the same pairs/unpaired/suspicious/stats, its
  digest additionally depends on where the netlist report itself lives).

### Rule set `kicad-doc-v1`

The rule set is a clean-room implementation of the net naming
convention in the KiCad 10.0 PCB Editor manual ([Differential pairs](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#differential_pairs),
*Board setup → Differential pairs*; wording as of KiCad 10.0):

> "Differential pairs in KiCad are defined as nets with a common base
> name and a positive and negative suffix. KiCad supports using + and −,
> or P and N as the suffixes."

Implemented as two suffix groups, always at the **end** of the net name:

| Group | Style | Positive suffix | Negative suffix | Example pair |
|---|---|---|---|---|
| `plus_minus` | `symbol` | `+` | `-` | `CLK+` / `CLK-` |
| `p_n` | `separator` | `P` (after `_`, `-` or `.`) | `N` (after `_`, `-` or `.`) | `DATA_P` / `DATA_N` |
| `p_n` | `bare` | `P` | `N` | `DATAP` / `DATAN` |

A pair is reported when both nets share the **same base**, the same
group **and** the same style (same separator character). The manual
leaves several boundaries open; the choices below are pinned by tests
(`tests/test_diffpair.py`) and are part of the rule set contract:

| Boundary | Pinned choice | Rationale / effect |
|---|---|---|
| Case sensitivity | Case-sensitive: only upper-case `P`/`N` count | The manual says "P and N"; `DATA_p`/`DATA_n` neither pairs nor appears as a half |
| Separator set for `P`/`N` | Exactly `_`, `-`, `.` | Three conventional separators, no others; `DATA=P` is not suffix-bearing |
| Mixed separators within one pair | Not paired → `mixed_suffix_style` suspicious | `DATA_P` next to `DATA-N` is a naming inconsistency a checker should surface, not absorb |
| Mixed styles within one base | Not paired → `mixed_suffix_style` suspicious | Same for `DATA_P` next to `DATAN`, or `DATA_P` next to `DATA+` |
| Multi-level suffixes | Decompose at the last level only | `USB_DP`/`USB_DN` pair on base `USB_D` (bare style) |
| `+`/`-` in the middle of a name | Never a suffix | `DATA+CLK` is not suffix-bearing; suffixes bind at the name end only |
| Empty base | Not suffix-bearing | `+`, `-`, `P`, `N` alone are ignored; `_P` falls back to the bare style (base `_`) |
| Base ending in a separator + symbol | Base keeps the separator | `CLK_+`/`CLK_-` pair on base `CLK_` (symbol group takes the last character only) |
| Symbols are ASCII | `+` and `-` only | The typographic `−` in the manual's prose is not a net-name character |
| Bare-P/N false positives | Accepted, but labeled | Any net ending in `P`/`N` is suffix-bearing, so word-final letters can make halves (the example board's `PIEZO_IN` net is a bare-`N` half on base `PIEZO_I`); every entry carries `suffix_style`, so `bare` findings are trivially filterable |

`--diffpair-rules` on the `netlist` subcommand uses the same rule set
(`kicad-doc-v1` default, `none` disables); the `netlist` report's
`diffpair_candidates` block is the same engine's result embedded
per-board.

## Determinism, canonical form and hashing

The payload contains **no timestamps**. The only volatile field is the
top-level `timing_ms`. The **canonical form** is the payload without
volatile fields, serialized with sorted keys, UTF-8 and LF line endings:

- `--canonical` writes that form directly;
- post-hoc: `pcb_periph.canonical.dumps_canonical(json.load(report))`
  reproduces it byte-for-byte.

For a fixed input, fixed kicad-cli version, fixed options and a fixed
working directory, two runs produce **byte-identical canonical JSON** —
the basis for a "fixed input → fixed sha256" smoke test:

```
python -m pcb_periph drc board.kicad_pcb --canonical --out a.json
python -m pcb_periph drc board.kicad_pcb --canonical --out b.json
sha256sum a.json b.json        # identical digests
```

**Upstream caveats (honest limitations):**

- `kicad-cli` 10.0.5 itself is not fully deterministic for boards with
  many near-threshold geometry pairs — violation *sets* can differ
  slightly from run to run (observed ±1…3 counts on a deliberately
  rule-tightened test board), independent of this tool. The canonical
  form guarantees byte-stability of everything this tool adds; when the
  upstream counts drift, they drift. Use `--runs N` (with the `stable`
  flag per board) to detect such drift explicitly instead of trusting a
  single run.
- `kicad-cli` writes a `<project>.kicad_prl` settings file next to the
  input on some runs; that is kicad-cli behavior, not something this tool
  can suppress. Treat input directories as writable by the pipeline.

## Why not kicad-mcp-pro `run_drc`?

[kicad-mcp-pro](https://github.com/lakbubuaa/kicad-mcp-pro) 4.3.0 exposes
`run_drc` as an MCP tool. This CLI differs on purpose:

1. **CLI-first, CI-native.** No MCP server, no Python-MCP runtime, no
   live project/application context to connect to — one process, one
   command, one JSON document on stdout or a file. Drop-in for any CI
   runner, cron job or shell script.
2. **Normalized, schema-versioned output.** Violation counts bucketed by
   native severity/type, path anchors, kicad version,
   `schema_version`-gated schema — instead of a raw report passthrough.
   The raw report is still preserved and referenced for full detail.
3. **CI-friendly exit codes** (0/1/2/3 above) with documented
   precedence, so a pipeline gate is one shell check.
4. **Portable kicad-cli discovery** — environment variable override and
   multi-location probe instead of a hard-coded install path.
5. **Multi-board batch runs** in a single invocation, with per-board
   status entries and a summary block.
6. **Configurable multi-run stability check** (`--runs N` + `stable`
   flag) to surface kicad-cli run-to-run drift explicitly.

For `netlist`, the comparison point upstream is `pcb_get_board_summary`
(a summary view, not a netlist): this CLI emits a full pad-level netlist
(`net → pad references`, pad → net mapping), differential-pair
candidates, and canonical byte-stable JSON — with zero runtime
dependencies and no KiCad installation at all.

For `diffpair` there is no upstream comparison point: kicad-mcp-pro 4.3.0
ships no differential-pair pairing checker (its `sch_get_connectivity_graph`
is a schematic connectivity graph, not a PCB netlist pair check). This
CLI adds the documented-suffix pairing audit with unpaired/suspicious
findings, pad counts and the same canonical JSON/exit-code contract.

## Example boards (test data)

All boards under `examples/` are **original, script-generated content**
written by this repository's generator `tests/make_boards.py`
(deterministic: regenerating reproduces the files byte-for-byte). They
carry no third-party copyright and ship under the repository MIT license
with no attribution requirements — which is exactly why they exist:
redistributing KiCad's own demo boards inside an MIT repository would be
a license mismatch (the KiCad demo collection is CC BY-SA 4.0), so the
test suite and the examples share one set of generated boards instead.

- `examples/diffpair_showcase/` — a two-layer board whose 19 named nets
  exercise every suffix style of the `kicad-doc-v1` convention: five
  complete pairs (`CLK+`/`CLK-`, `DATA_P`/`DATA_N`, `CLK-P`/`CLK-N`,
  `USB.P`/`USB.N`, multi-level bare `USB_DP`/`USB_DN`), five unpaired
  halves, one `suffixless_twin`, one `mixed_suffix_style` finding and a
  `+`-in-the-middle negative control (`DATA+CLK`). Includes a minimal
  `.kicad_sch` (ERC target) and a `.kicad_pro` with KiCad's default
  design rules plus one severity override (`lib_footprint_issues` is
  ignored in project context because the self-contained board ships
  without its source footprint libraries).
- `examples/small_mcu/` — a plainer second board (connector, passives,
  one `DM_P`/`DM_N` pair, one unpaired `SW_N` half).

The **dirty DRC fixture is not shipped**: the tests build it on the fly
in a temp directory with `tests/make_dirty_fixture.py`, which copies the
showcase project and raises `min_clearance` to 5 mm in the copied
`.kicad_pro`, producing a large number of real `clearance` violations
(25 on KiCad 10.0.5). The clean example is never modified.

## Development

```
venv/Scripts/python tests/make_boards.py           # regenerate example boards
venv/Scripts/python tests/run_tests.py             # stdlib test runner
python -m pytest tests/                            # equivalent under pytest
venv/Scripts/python tests/audit_engine_isolation.py --source-root /path/to/private/source
```

`tests/make_dirty_fixture.py --src examples/diffpair_showcase --dst DIR`
builds a dirty-board copy (see *Example boards*); the test suite does
that itself in a temp directory.

The tests use plain pytest-style functions (`test_*` + bare asserts) and
need kicad-cli on the machine; they skip automatically when it is not
found. `tests/run_tests.py` is a dependency-free fallback runner for
environments where pytest is not installable.

`tests/test_netlist_crosscheck.py` additionally reconciles the `netlist`
parser against the KiCad-bundled `pcbnew` module; it runs
`tests/netlist_pcbnew_probe.py` under the KiCad interpreter (default
`F:\kicad\bin\python.exe`, override with `$PCBNEW_PYTHON`) and skips
when that interpreter is absent. `pcbnew` is GPL-licensed, so it is
imported only by that test-side probe script — never by `pcb_periph`.
