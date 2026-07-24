# MC68000 interpreter architecture

`src/interp.pasm` is the correctness-first half of the port. It executes the private
MC68000 program image on the SA-1 and remains the fallback for every path that has not
been safely moved to native 65816.

## State model

- MC68000 D0-D7 and A0-A7 live in the SA-1 direct-page register file.
- The emulated PC, CCR components, scheduler cells, and interpreter scratch also live
  in SA-1 IRAM/direct page.
- Program bytes are fetched big-endian from the packed private ROM image.
- Emulated work RAM is stored byte-for-byte in BW-RAM. Word and long helpers swap at
  the 65816 boundary so the MC68000-visible layout remains big-endian.
- Device reads and writes go through region-aware helpers. A direct BW-RAM access is
  legal only when the effective address has been proved to be work RAM.

The current semantic regression suite covers the legal MC68000 instruction set with
160/160 curated optest groups and 782/782 opsweep cells. These are strong fixture
results, not proof that every whole-program fetch and device path is correct.

## Execution loop

The interpreter:

1. converts the emulated PC to the packed ROM or RAM-resident-code source;
2. fetches and dispatches the opcode;
3. evaluates effective addresses through the shared or specialized handler;
4. reads or writes via the game adapter;
5. updates the split CCR representation; and
6. returns to the fetch loop, scheduler boundary, exception path, or native dispatch.

Native escapes use the same register file and mapped memory. They are replacements for
bounded MC68000 work, not a second independent game state.

## What transfers unchanged

- opcode semantics and effective-address behavior;
- exception frame construction and vectoring;
- big-endian register/memory conventions;
- native-entry register/CCR contract;
- optest/opsweep fixture machinery; and
- the diagnostic PC ring and PC-freeze concepts.

## What must be adapted

- program image placement and reset-vector boot glue;
- the ROM, work-RAM, palette, video, input, sound, protection, and watchdog regions;
- IRQ level and delivery cadence;
- any RAM-resident program fetch paths;
- game-specific HLE and native dispatch tables; and
- test-state drivers and mapped ranges in differential scripts.

Start a new game with every native escape and HLE disabled. An interpreter boot is
slower but gives one place to debug CPU and address-map correctness. Re-enable or
replace hot work only after the organic interpreter path is coherent.

## Three recurring correctness traps

1. **All instruction-fetch paths must know the source bank.** Normal PC fetch,
   extension-word fetch, and RAM-resident execution have failed independently.
2. **Data reads need the same proof.** An address register that usually points to work
   RAM may point into ROM for one caller; a `$40` fast path then returns plausible but
   wrong data.
3. **CCR state is observable across function boundaries.** Carry meaning differs
   between MC68000 subtraction and 65816 comparison, and 65816 `CMP` does not compute
   overflow.

The forensic recipes are in [DEBUGGING.md](DEBUGGING.md). The original bring-up record
is preserved in
[INTERPRETER_BRINGUP.md](../history/experiments/INTERPRETER_BRINGUP.md), and the
lowering rationale is preserved in
[TRANSPILER_DESIGN.md](../history/designs/TRANSPILER_DESIGN.md).

## Validation

Run the semantic gates with MAME 0.287 and Nexen configured:

```sh
python3 tools/optest.py
python3 tools/opsweep.py
```

For an integration change, also boot through the real reset vector, exercise mapped
devices, compare a representative adjacent game tick with MAME, and run with native
dispatch disabled. See [differential validation](DIFFERENTIAL_VALIDATION.md).
