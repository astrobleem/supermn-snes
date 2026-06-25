# MAIN PLANNING HANDOFF — resume the Superman port here

Last updated: June 25, 2026. **Start here** to pick the main thread back up in a fresh session.
This is the "where were we / what's next / how to resume" doc. Authoritative detail lives in
[STATUS.md](STATUS.md) (state), [ROADMAP.md](ROADMAP.md) (plan), [METHODOLOGY.md](METHODOLOGY.md)
(recipe), [BUILD.md](BUILD.md) (toolchain + migration).

> **Context:** we split off to do **Mesen/Nexen MCP** work (see [Parked threads](#parked-threads));
> that is NOT the main thread. The main thread is the **Superman 68K→SNES/SA-1 transpiler**. Branch:
> **`boot-scheduler-progress`** (everything below is committed + pushed there).

---

## Where we are (one paragraph)

The interpret-cold / transpile-hot hybrid is a **working production pipeline**. The 68000
interpreter is bit-exact vs MAME, runs on the SA-1, renders video, reads input. The **automated
transpiler** (`tools/transpile.py`) is built and validated; it replaces hot 68K functions with
native 65816 "escapes" — leaf, **non-leaf (call-bridge)**, and **video (shadow stores)**. **8
escapes are deployed in free bank-$00 gaps and validated bit-exact**, including the two big ones
this phase: `entry_25110` (collision, ~12.6%, bridged) and `entry_20e8` (video, ~5.9%, `$41`
shadow). The multi-bank idea proved **unnecessary** (bank $00 has gaps). **Next = the throughput
grind: transpile the rest of the hot set until the per-frame path hits the realtime cycle budget.**

### Escapes live (all bit-exact)
`entry412` (RNG) · `entry_cb9e`/`entry_15b4`/`entry_3e6a` (leaves) · `entry_ce4` ($000CE4 ~12.5%) ·
`entry_111a` ($00111A ~5.9%) · **`entry_25110`** ($025110 collision ~12.6%, 2 bridged jsr.l) ·
**`entry_20e8`** ($0020e8 video ~5.9%, shadow stores).

---

## What's next (priority order)

1. **Transpile the next hot functions** (mechanical now). From the live profile
   (`tools/stream_profile.py`), the remaining `$002xxx`/`$025xxx` hot set:
   - `$0028d4` (video, ~2.4%), `$00267a` (~1.3%) — video-family, use `--video`.
   - `$025xxx` collision-cluster siblings; `$001140`; others the profiler ranks.
   - Recipe per function: `tools/transpile.py <addr> [--video]` → deploy in a bank-$00 gap →
     validate **ON-vs-OFF = 0** (a7-classify stack diffs; diff `$41` shadow for video).
2. **Measure G3 (realtime cycle budget, <150k SA-1 cycles/frame).** Benchmark steps/frame and the
   SA-1 cycle count with the hot mass native; decide if the cold interpreter tail needs more
   transpilation or a faster dispatch. Then cycle-aware `$AC` IRQ pacing for unattended realtime.
3. **Watch bank-$00 space.** Gaps used: `$D1ED` (entry_25110), `$EC2C` (entry_20e8). `$F149` (1463B)
   free + smaller. When gaps run dry → a transpiler code-size pass (An-addr caching; non-frame reads
   are ~6 instrs each) OR revisit a 2nd executable bank (see `multibank-interp` memory — SUPERSEDED
   for now, but the machinery exists).
4. **Audio** (YM2610→TAD) in parallel; **integration** → one playable full-level-validated ROM.

---

## How to resume (mechanics)

```sh
# build (-> build/interp.sfc, 4194304 bytes)
bash tools/build_interp.sh

# find the next hot target (fresh Mesen port; $SUPERMN_SCRATCH = the flytick/state dir)
export SUPERMN_SCRATCH=<scratch-with-flytick/>
python3 tools/stream_profile.py            # ranked in-game hot 68K functions

# transpile + validate one function
python3 tools/transpile.py <hexaddr> [--video]
python3 tools/flyval.py 7000               # ON-vs-OFF; for video also diff $41 (see val_* scripts)
```

**Deploy recipe (bank-$00 gap):** insert `.org <gap-addr>` + the escape just **before the next
`.org`** (NOT before `.org $F700` — that shifts code → overflow). Add a tiny dispatch handler
right after `jah2_e111a` (near `jsrabs_hook2` so the `beq` is short) that `jmp entry_<addr>`. For a
SECOND escape sharing a region, let it **flow into the gap with no `.org`** (an explicit `.org` over
dispatch-shifted code corrupts it → hang). Build must stay 32768 with RESP1 intact.

**Validation gotchas:** the lockstep compares work RAM ($40); for a **bridged** escape, raw diffs
include **dead-stack sentinel bytes below `a7`** — classify vs `a7`, only `≥a7` (live) matters. For
a **video** escape, work-RAM ($40) won't show the video writes — diff the **`$41` shadow** too.
Mesen: foreground only, ~90 s/run, **fresh ports each run** (they wedge), no pipes (SIGPIPE).

---

## Parked threads (not the main path)

- **Mesen → Nexen MCP port** (the current split-off). Scoped: `Mesen2/MCP_NEXEN_PORT_SCOPE.md` +
  `mcp-nexen-port` memory. Strategic infra (gain Andy's RE stack, give him an MCP); NOT a Superman
  blocker. Do it in parallel/after.
- **G1 disassembly coverage** — in progress; NOT a hybrid blocker (interpreter is the cold fallback).
- **Audio** — not started; parallelizable.

## ⚠️ Drive / migration
The build drive has bad sectors. **[BUILD.md](BUILD.md)** is the migration guide. Toolchain is safe
on GitHub (Game Garden = `TheAnsarya/{poppy,peony,pansy,game-garden}`; `astrobleem/{mame-mcp,Mesen2}`).
**Still only on the drive** (copy off / re-derive): the arcade ROM + derived assets
(`data/superman_m68k.bin`, `tools/mame-trace/gfx1.bin`, `data/cchip_boot_response.bin`) and the
`$SUPERMN_SCRATCH` flytick/MAME captures. (The MAME-0.287 `.inp` recordings ARE in git now.)

## Key memories (recall these first)
`transpiler-tool` (the tool + deploy recipe) · `bulk-transpile-phase` · `multibank-interp` (why NOT
needed) · `gameplay-input-validated` · `lockstep-harness-progress` · `timing-8mhz` · `mame-mcp` ·
`mesen-mcp-validation` · `build-toolchain-migration` · `mcp-nexen-port`.
