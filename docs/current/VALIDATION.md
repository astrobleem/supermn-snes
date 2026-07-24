# Validation commands and evidence scope

Run the smallest gate that can falsify the change, then add wider gates in proportion
to the risk. Assembly success alone is never a correctness result.

## Documentation and private-input tooling

```sh
python3 tools/check_doc_links.py
python3 -m py_compile tools/prepare_roms.py tools/transpile.py tests/test_prepare_roms.py
python3 -m unittest discover -v
python3 tools/prepare_roms.py /path/to/superman.zip --dry-run
python3 tools/prepare_roms.py /path/to/superman.zip --validate-only
```

These prove links, Python syntax/unit behavior, set authentication, deterministic
derivation, and existing-output identity. They do not prove the game runs.

## Build and layout

```sh
bash tools/build_interp.sh
python3 tools/audit_banks.py
stat -c '%s' build/interp.sfc
sha256sum build/interp.sfc
```

The normal build must produce a 4,194,304-byte ROM. `build_interp_rom.py` contains
exact-byte, seam, bank, boot-asset, and packing assertions; `audit_banks.py` is an
additional lower-bound overlap check for its covered escape-bank set. Follow a layout
change with a fresh cold boot and the relevant differential.

Use the diagnostic recorder only when required:

```sh
PC_RING=1 bash tools/build_interp.sh
# run the diagnostic
bash tools/build_interp.sh
```

The `PC_RING=1` ROM has measurable overhead and cannot support production performance
claims.

## Interpreter semantics

With MAME 0.287 and Nexen MCP configured:

```sh
python3 tools/optest.py
python3 tools/opsweep.py
```

Latest retained gates are 160/160 optest groups and 782/782 opsweep cells
(1,564/1,564 vectors). These prove covered instruction fixtures. They do not prove
every whole-game address path, RAM-resident instruction fetch, device mapping, or
fast-path region assumption.

## Native escape or HLE change

Minimum evidence:

1. prove the entry executes with an SA-1 execution hook in the actual `$92+` bank;
2. run the focused MAME fixture/differential;
3. run gate-off and gate-on on fresh adjacent states;
4. compare registers, CCR, terminal PC, mapped work RAM, and `$41` video shadow when
   relevant;
5. run a multi-tick gameplay/checkpoint soak; and
6. cold-boot the final exact ROM if the path affects scheduling, layout, input, combat,
   rendering, or sound.

The established adjacent-tick workflow is:

```sh
export SUPERMN_SCRATCH=/path/to/private/flytick-data
python3 tools/flyval.py 7000
```

The address/fixture argument is target-specific. Consult
[the transpiler workflow](../toolchain/TRANSPILER_WORKFLOW.md) before interpreting
stack residue or a sparse capture.

## Rendering

Choose the focused validator for the changed path:

- `tools/validate_fast_obj_renderer.py`
- `tools/validate_obj_cache_vram.py`
- `tools/validate_paced_obj_sources.py`
- `tools/validate_vertical_scroll_bridge.py`
- `tools/capture_mesen211_transitions.py`
- `tools/trace_playtest_actions.py`

A synthetic or checkpointed test proves only its named invariant. Rendering acceptance
also needs an unmodified fresh boot, screenshots/PPU state, continued ticks/renders,
and eventually an aligned MAME frame comparison.

## Scheduler, renderer ownership, and performance

The formal cold-boot harness is:

```sh
python3 tools/recovery_baseline.py \
  --rom build/interp.sfc \
  --gameplay-right-b \
  --uninterrupted-gameplay-frames 3600 \
  --output build/validation/production-coldboot
```

Use a fresh port and retain the complete output directory. A qualifying result must:

- start from power-on with `TESTFLAG=0`;
- arm production gates organically;
- drive the real port-0 controller/mailbox;
- validate `$0760` against `$00:F5A3`;
- include waits, IRQs, rendering, input, audio supervision, and transitions;
- cross the known scheduling event;
- check task-stack floors and recent tick/render progress; and
- identify the exact source and ROM hash.

Checkpoint tools such as `soak_gameplay_ordering.py` and `profile_continuous.py`
provide focused ordering/attribution evidence, never end-to-end fps.

## Sound

Required mechanical gates include:

```sh
python3 tools/sound/vgm_profile.py "/path/to/track.vgm"
python3 tools/sound/vgm_ym2610.py "/path/to/track.vgm"
tad-compiler check soundwork/tad/superman_all.terrificaudio
soundwork/tad/build_blob.sh
```

Also verify the exact TAD data in SPC ARAM and the packed ROM. Mechanical equality,
ARAM fit, a non-silent WAV, or the absence of 200 ms digital silence does not prove
musical fidelity. Acceptance requires listening against the arcade/VGM reference and
recording the per-track result.

## Human playtest

Use the exact ROM hash and route in [CONTROLS.md](CONTROLS.md). Human findings are
project evidence even before automation reproduces them. Record bounded positive
observations as bounded observations; do not promote them to complete-stage,
crash-free, playable, or shippable claims.
