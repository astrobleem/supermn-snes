# MC68000-to-65816 transpiler workflow

`tools/transpile.py` converts a bounded MC68000 function into a native 65816 escape
that uses the interpreter's register file and memory conventions. It is an optimizer,
not the bring-up path and not a whole-program compiler.

## Select a real hot path

Capture organic gameplay first. Use the PC stream, call graph, and adjacent-tick
fixtures to establish:

- that the entry actually executes;
- how it is reached: call, jump, coroutine resume, or table dispatch;
- all real callers and return PCs;
- effective-address regions for every address register;
- whether stores target work RAM or video state; and
- whether the caller observes CCR, X, stack residue, or return-address residue.

Do not promote an entry from one sparse trace. The `$012B6C` combat failure came from
an HLE that assumed one return PC although the real function had 34 BSR callers.

## Generate, then inspect

Basic examples:

```sh
python3 tools/transpile.py 025110 > /tmp/entry_25110.pasm
python3 tools/transpile.py 0020e8 --video > /tmp/entry_20e8.pasm
python3 tools/transpile.py 0129c6 --bank2 > /tmp/entry_129c6.pasm
```

The decoder normally reads `data/superman_m68k.bin`. A new game must provide an
equivalent private image and parameterize or replace that source before using the
tool.

Important entry modes:

| Mode | Contract |
|---|---|
| default | Hook skipped an MC68000 JSR/BSR push; generated prologue recreates it |
| `--coroutine` | Entered at task resume; no simulated return push |
| `--table` | A real return already exists on the MC68000 stack |
| `--video` | Non-work-RAM stores route through the video shadow adapter |
| `--bank1`, `--bank2`, `--bank5`, `--bank6`, `--bank7` | Transform calls/addresses for a selected escape bank |
| `--bail` | Unsupported non-CCR-reading instruction may return to interpretation |

The tool exits nonzero when it skips unsupported semantics unless explicitly forced
with `--allow-unimpl`. Forced output is for inspection and is not deployable.

## Review the generated contract

Before insertion, audit:

- every source instruction appears or reaches a correct interpreter bail;
- M/X width is explicit at all entries, labels after returns, and bridges;
- raw arcade addresses do not bypass the address adapter;
- big-endian reads/writes preserve exact bytes;
- signed conditions and subtraction carry use the correct lowering;
- CCR/X are materialized on every observable exit;
- the entry convention matches the actual caller;
- stack and return residue match interpretation; and
- cross-bank calls are explicit long-bank operations.

## Validate before deployment

1. Build a focused MAME fixture for the entry and every meaningful path.
2. Run native-off and native-on from the same adjacent state.
3. Compare D/A registers, CCR/X, PC, live MC68000 stack, mapped work RAM, and video
   shadow where applicable.
4. Prove the native body fires using an SA-1 execution hook at its actual `$92+`
   execution address.
5. Exercise every known caller class, including error, empty, full, and wrap cases.
6. Run a multi-tick gameplay soak with task-stack floors and recent progress checked.
7. Cold-boot the exact final ROM if layout, scheduling, combat, input, rendering, or
   sound can be affected.

`tools/flyval.py`, `tools/lockstep_choke.py`, `tools/multitick_choke.py`, and focused
`val_*` tools implement variants of this pattern. Fixture names and addresses remain
Superman-specific.

## Deploy without corrupting layout

Old upstream Poppy silently allowed `.org` overlap, and a later section won. The
latest corrected fork rejects that class, but keep generated bodies in audited
escape-bank space, run the ROM pack assertions and `tools/audit_banks.py`, then
byte-audit every changed seam. The charged-shot freeze was caused by a valid body
crossing a later `.org $F000` island; local semantic tests did not detect the
overwritten tail.

The historical [transpiler design](../history/designs/TRANSPILER_DESIGN.md),
[call-bridge design](../history/designs/CALL_BRIDGE_DESIGN.md), and
[transpiler tool scope](../history/plans/TRANSPILER_TOOL_SCOPE.md) preserve the detailed
lowering and campaign rationale.
