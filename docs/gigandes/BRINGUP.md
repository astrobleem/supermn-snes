# Gigandes concrete bring-up sequence

This sequence is intentionally interpreter-first. It should expose every Superman
literal that still lives in supposedly reusable code before any Gigandes optimization
or polish begins.

## G0 — Pin and audit the arcade oracle

```sh
/snap/bin/mame -version
/snap/bin/mame -listxml gigandes > /tmp/gigandes-mame0287.xml
/snap/bin/mame -verifyroms gigandes
/snap/bin/mame -listxml gigandesa > /tmp/gigandesa-mame0287.xml
```

Record MAME 0.287, parent/clone identities, ROM metadata, DIP defaults, CPU clocks,
visible area, IRQ level, and the exact driver revision. Record both the configured
60 Hz refresh and the driver's 58 Hz PCB note as an open timing discrepancy. Keep
DSWA bit 4 off.

Gate: the legally obtained parent set passes MAME audit, and a short MAME boot has a
repeatable reset PC, stack pointer, RAM-clear boundary, first IRQ, and first rendered
frame.

## G1 — Add a private-input manifest and preparer

Parameterize the proven `tools/prepare_roms.py` design rather than weakening its
Superman checks. The Gigandes path must:

- accept a ZIP or directory;
- authenticate the 11 parent files and reject the earlier clone;
- assemble the 512 KiB `maincpu` and 2 MiB `gfx1` regions exactly as MAME does;
- preserve ADPCM-A and ADPCM-B as private derived/source inputs;
- verify every output by size and SHA-256;
- support dry-run and validation-only modes; and
- use a game-specific output namespace so Superman inputs cannot be overwritten.

Gate: synthetic lane/layout tests pass, and generated regions are byte-identical to a
MAME-region dump. No ROM or derived binary is tracked by Git.

## G2 — Split portable core from game adapter

Inventory Superman literals in:

```sh
rg -n 'superman|C10000|900000|F00000|B00000|D00000|E00000' \
  src tools --glob '*.pasm' --glob '*.py' --glob '*.sh'
```

Move only established variation points into a manifest or adapter: program-image
source, ROM packing range, reset/IRQ configuration, mapped regions, controller/DIP
handling, video shadow routing, sound command map, and build output names. Keep
MC68000 semantics shared.

Gate: the refactor produces the exact Superman ROM hash before Gigandes is selected,
and all retained Superman semantic/differential gates remain green.

## G3 — Interpreter-only CPU boot

Select Gigandes with all native escapes, HLE, production acceleration, Superman
C-Chip behavior, and TAD song hardcodes disabled.

Implement in this order:

1. reset-vector and program fetch;
2. `$F00000-$F03FFF` work RAM;
3. ignored/watchdog writes at `$400000/$600000`;
4. DIP/input reads at `$500000-$500007` and `$900000-$90000F`;
5. TC0140SYT status/command behavior at `$800001/$800003`;
6. X1-001 palette/object/control shadow; and
7. IRQ level 2 delivery at the observed cadence.

Make unknown device accesses fail loud in diagnostics. Do not return convenient zeroes
until MAME establishes that behavior.

Gate: SA-1 reaches a sequence of early MC68000 PCs and RAM checkpoints that match
MAME, first without IRQs, then through the first IRQ and stable attract loop.

## G4 — Inputs and organic gameplay

Create Gigandes-specific field names and scripted scenarios for coin, Start, movement,
both buttons, damage, death, and stage transitions. Capture a same-version `.inp`
playthrough for repeatable deep states.

Gate: fresh power-on reaches gameplay through the real input device, and an adjacent
MAME/Nexen tick matches registers, CCR, work RAM, and mapped side effects with native
dispatch still off.

## G5 — Graphics

Reuse the X1-001 decoder/manifest concepts, not Superman's crop or scene assumptions.
Trace palette banks, both object banks, control registers, column scroll, priority,
wrap, and visible coordinates in title, gameplay, cave demo, boss, and high-score
states.

Decide and document the 384→256 horizontal presentation policy only after captures:
center crop, tracked viewport, or another bounded mapping. The policy must not hide
objects the player can interact with.

Gate: one aligned static frame matches MAME's indexed/color/position data; organic
rendering then advances with request/ACK/true-render conservation and no cache,
manifest, or task-stack failure.

For the cave-demo discrepancy, retain both raw video state and rendered captures.
Label any choice between MAME output and inferred hardware behavior as an explicit
oracle decision.

## G6 — Sound

Inventory Gigandes TC0140SYT commands during boot, attract, coin, Start, gameplay,
boss, death, and continue. Obtain the corresponding VGMs, preserve both ADPCM regions,
and build a new TAD project/ID map rather than reusing Superman song numbers.

Gate: organic commands select the intended tracks/SFX, the blob fits ARAM, loops and
transitions are stable, and human A/B listening passes against the pinned VGM/MAME
reference.

## G7 — Timing and native-hot work

Measure the interpreter-only organic tick boundary before selecting hot functions.
Define the Gigandes gameplay cadence and end-to-end acceptance budget from MAME
behavior and the SNES presentation model.

Then:

1. trace a real playthrough and build a Gigandes CDL/call graph;
2. profile organic SA-1 execution;
3. transpile one measured hot function;
4. prove its real-bank hook fires;
5. run focused and adjacent-tick native-off/on differentials; and
6. rerun the end-to-end cold-boot measurement.

Gate: every claimed speedup has a same-run local result and the exact production ROM
has a power-on rate result satisfying the evidence protocol. Do not import Superman's
fps number, scheduler event, escape list, or stack floors.

## Expected highest risks

- hidden Superman assumptions in program fetch, map helpers, and packer paths;
- incorrect ROM byte-lane or `gfx1` region assembly;
- IRQ2 integration with a scheduler tuned around Superman IRQ6 behavior;
- a 384-pixel playfield that cannot be represented by a fixed 256-pixel crop;
- treating MAME's documented cave-render defect as hardware truth;
- new MC68000 address paths that evade existing semantic fixtures;
- ADPCM-B use, command timing, or FM effects not exercised by Superman; and
- premature native/HLE work masking an interpreter/map defect.

Use [the reusable toolchain index](../toolchain/README.md) for implementation details
and [differential validation](../toolchain/DIFFERENTIAL_VALIDATION.md) for evidence
labels.
