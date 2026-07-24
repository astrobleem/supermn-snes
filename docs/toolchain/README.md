# Reusable arcade-to-SNES toolchain

This path describes the machinery that should survive beyond Superman. It separates
portable CPU/oracle work from Taito X conventions and from one game's addresses,
assets, controls, and timing assumptions.

## Porting model

The project uses an **interpret-cold / native-hot** design:

1. authenticate and arrange the original game's private ROM images;
2. run the original MC68000 program through the SA-1 interpreter;
3. adapt arcade memory and device accesses at explicit boundaries;
4. translate video state into SNES PPU work and sound commands into TAD work;
5. measure real hot paths, transpile selected functions to native 65816, and retain
   interpretation as the correctness fallback; and
6. compare each side with an independent oracle: MAME for arcade behavior and Nexen
   for SNES/SA-1/PPU behavior.

## Portability boundary

| Layer | Reuse expectation | What must change for a new game |
|---|---|---|
| MC68000 semantics, EA engine, exceptions | Reuse unchanged | Revalidate after any integration edit |
| Direct-page register/CCR convention | Reuse unchanged | None unless the cartridge architecture changes |
| Transpiler lowering core | Reuse unchanged | Add unsupported forms only with focused differentials |
| Trace/CDL and differential method | Reuse unchanged | ROM name, state-driving scripts, mapped ranges |
| SA-1 boot and 5A22 supervision | Reuse as a starting platform | ROM layout, reset/IRQ wiring, game timing |
| Address/device adapter | Game-specific | ROM/RAM regions, I/O, protection, IRQ, sound boundary |
| Graphics renderer | Hardware-family-informed | Asset layout, object rules, crop, scroll, palette use |
| Sound authoring | Pipeline reusable | VGMs, command map, samples, MML, SFX vocabulary |
| Performance threshold | Product-specific | Establish from the arcade cadence and target presentation |

Do not copy Superman literals into a second game and call that reuse. Promote a value
to a manifest or adapter only after identifying whether it is an MC68000 invariant, an
SA-1 convention, a Taito X convention, or a Superman fact.

## Working sequence

1. [Adapt the address map](ADDRESS_MAP_ADAPTATION.md).
2. [Bring up the interpreter](MC68000_INTERPRETER.md) with all native escapes disabled.
3. [Convert and validate graphics](GRAPHICS_CONVERSION.md).
4. Establish controller, IRQ, scheduler, and render ownership using
   [the timing model](SCHEDULER_TIMING.md).
5. Establish the command vocabulary and [VGM/TAD sound path](SOUND_PIPELINE.md).
6. Capture representative states and apply
   [MAME/Nexen differential gates](DIFFERENTIAL_VALIDATION.md).
7. Profile the organic build and use the [transpiler workflow](TRANSPILER_WORKFLOW.md)
   only for measured hot paths.

The [tools index](../../tools/README.md) labels individual programs as
game-agnostic, parameterized, or Superman-specific. The historical
[porting playbook](../history/plans/PORTING_PLAYBOOK_20260625.md) preserves the
original campaign reasoning and rejected assumptions.

## Non-negotiable evidence rules

- A byte match proves bytes, not that a game is playable or music sounds right.
- A focused differential proves the covered fixture, not every caller or address path.
- A checkpoint proves behavior from that checkpoint, not an organic cold boot.
- A local cycle reduction is not end-to-end frame rate.
- Visual plausibility is not aligned pixel fidelity.
- Failed experiments and negative results belong in a dated evidence report, not in
  an untracked notebook.

Read [debugging and toolchain gotchas](DEBUGGING.md) before changing assembly or
emulator harnesses.
