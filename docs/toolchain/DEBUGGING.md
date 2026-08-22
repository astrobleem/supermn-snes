# Interp debug plumbing + toolchain gotchas (the "tribal knowledge" reference)

Everything here was learned the hard way on Superman and applies as-is to the next port
(Gigandes) because the interpreter core, the Poppy toolchain, and the two emulator oracles
all carry over. If you are a fresh agent bringing up or debugging the 68K interpreter,
READ THIS FIRST — each item below cost hours-to-days to discover.

For hardware questions, the host's local Nintendo/SA-1/fullsnes reference library is
routed in [SNES_REFERENCE_LIBRARY.md](SNES_REFERENCE_LIBRARY.md). Read only the focused
section implicated by the failure; emulator differentials remain the behavioral oracle.

## 1. The interpreter's built-in debug interface (SA-1 IRAM)

The source contains a flight recorder and a poke-driven freeze/trace facility. The production ROM
pack replaces their per-fetch calls with size-neutral NOPs because the recorder has a measurable
whole-tick cost. Build an instrumented ROM with `PC_RING=1 bash tools/build_interp.sh` when these
facilities are needed, then restore the production default with `bash tools/build_interp.sh`.
All addresses are SA-1 IRAM (Mesen memtype `Sa1Memory`), little-endian unless noted.

### 68K register file (direct page)
| Cell | Meaning |
|---|---|
| `$00-$1F` | D0-D7, 4 bytes each, little-endian 32-bit |
| `$20-$3F` | A0-A7 (A7 = `$3C/$3E` lo/hi) |
| `$40/$42` | current 68K PC lo16 / bank |
| `$44` | current (last-decoded) 68K opcode |
| `$48` | PC-ring write pointer (see flight recorder) |
| `$4E` | halt code: `$DEAD` = unimplemented op, `$CAFE` = step cap |
| `$56` | peek-ahead / operand fetch pointer |
| `$60/$6E/$70/$72/$A2` | CCR cells Z/C/N/V/X — nonzero = set (NOT bit-packed) |
| `$7C` | SR interrupt mask (mask ≥ 6 blocks level-6 delivery) |
| `$AA` | IRQ pending |
| `$AC` | virtual-IRQ countdown. The current `f369…` candidate reloads `$7000` through the bank-$97 seam; `$2328` and `$2354` are rejected reversible Stage-3 probes, not production values. Neither is a hardware-cycle model. |

### Flight recorder (diagnostic build only)
Last 128 interpreted 68K PCs in a ring at IRAM `$0400-$05FF`, 4 bytes/entry
(lo16, bank16), write pointer at `$48`. Read it after ANY derail/halt — it shows the
final instruction cascade. Decode: entries at `(ptr - 4(i+1)) & $1FF` walking backwards.

`tools/profile_tick_ring.py` verifies that both recorder calls are present and rejects a production
ROM rather than silently attributing an inert ring. Its instrumented cycle totals include recorder
overhead and therefore cannot support a production performance or fps claim.

**Reading the wedge signature:** if the ring stops updating AND `$AC` freezes AND
`$4E`=0, the SA-1 left the interp core and never came back (a native escape hung or
jumped into a garbage stream). If `$4E`=`$DEAD`, the interp itself fetched an
unimplementable opcode — ring shows how it got there.

### PC-freeze (poke-driven breakpoint, works from Mesen MCP)
- Arm: `$0710` = target 68K PC lo16, `$0716` = target bank. On hit the interp parks
  in a poll loop with `$0712` = 1 (frozen marker). All IRAM/BW-RAM readable at leisure.
- Release: write `$0714` = 1.
- Re-firing mode: `$0730` = `$5A5A` re-arms after release. **CAVEAT: re-fire checks at
  the same PC before the instruction advances — a re-firing freeze on a PC inside a
  tight revisit loop re-catches the SAME frozen instant forever (tick never advances).**
  For per-visit sampling, disarm + release + run ≥1 frame + re-arm instead.
- PC streaming: `$0718` = 0 streams the per-frame PC stream (see `stream_profile.py`).

### Counters: the ONE rule
**NEVER trust `$07xx` in-IRAM counters for anything the game can reach** — work-RAM/IRAM
overlap means the game overwrites them (the "ce4t fires 63451×" artifact). Measure firing
with SA-1 exec-hooks (HOOKTEST) or Mesen-side sampling. Purpose-placed counters in the
`$0760+` range are fine ONLY if you verified nothing else writes there.

### RAM-resident 68K code: THREE fetch paths must all be bank-aware
The game copies helpers into work RAM and executes them (PC bank `$F0`, e.g. the
sound enqueuer at `$f01b20` reached via `$2d8a: jmp $1b20(a5)`). The interp has
THREE instruction-stream read paths, and each needs the `$F0 → SNES bank $40`
special case, not the ROM `+$C1` mapping:
1. the iloop opcode fetch (has it),
2. `rdw2/rdw4/rdw6` via the `[$56]` fetch pointer (inherits it),
3. **`ea_extw` — the EA engine's own ext-word fetch (MISSED it until 2026-07-18)**:
   its unconditional `adc #$00C1` sent RAM-PC ext-word reads to open bus ($B1) —
   garbage d16/immediates for every EA-engine instruction executed from RAM. This
   silently killed ALL organic sound triggers for months (masked by the rc_copy
   boot-hardcoded attract song). Fixed: byte-neutral stub at `ea_extw` ($00:B83F)
   → bank-aware body `eaw5_fix` in escbank5 `$99:F700` (jml-back literal $00B843 —
   regenerate if ea_extw ever moves). Lesson: when adding ANY new instruction-stream
   read path, handle RAM PCs; when debugging "RAM code runs but does the wrong
   thing", suspect ext-word/immediate fetches before the opcode decode.

### FAST-PATH DATA reads must be bank-aware too (the F4 lesson, 2026-07-19)
The sibling class of the ea_extw bug, on the DATA side: inline fast-path
handlers (added for speed) that compute an EA and read `lda $400000,x`
UNCONDITIONALLY assume the operand lives in 68K work RAM ($F0xxxx→$40:lo16).
`op_cmpw_d16_dn` did exactly this — correct for the usual a5/a6-relative
game state, WRONG when An holds a ROM pointer (the music engine compares
against its ROM table at $6ab4 via a2): it read BW-RAM garbage, the compare
false-matched, and the round-start music send silently skipped. Fixed with
the same byte-neutral stub → escbank5 bank-aware body pattern (`cmpw5_fix`
$99:F760; jml-back literal $009F5C — regenerate if the handler moves).
Diagnostics that cracked it: PC-freeze at the BRANCH after the compare with
a FULL DP dump — the EA scratch residue ($52=d16, stale $5A/$5C) fingerprints
which read path ran. Lessons: (1) any new fast path must region-dispatch on
EA.hi16, not assume $F0; (2) opsweep can't catch this class — its An vectors
are work-RAM addresses; add ROM-pointer vectors when testing (d16,An) ops;
(3) accelerator-gate bisects can mislead: gates change timing/state
trajectories, so a state-dependent always-on bug can masquerade as an
escape interaction (F4 burned ~8 sessions on that red herring).
UNAUDITED siblings flagged: `op_movb_d16_dn`, the cmpi-(d16,An) family, and
any other `$400000,x` fast-path READ whose An can be ROM.

### PC-freeze arming gotchas (cost a session)
- The interp's boot ZEROES `$0710+` — a freeze poked before ~frame 3000 is silently
  wiped. Arm after interp init, before the target runs.
- Without re-fire mode (`$0730=$5A5A`) a released freeze is DEAD — a retargeted
  `$0710` after release never fires.

## 2. Poppy assembler gotchas (65816, `.pasm`)

The host's `/home/chad/poppy` remains old upstream `fa44a809…`. Chad's corrected
fork at [astrobleem/poppy](https://github.com/astrobleem/poppy), latest local
checkout `/home/chad/poppy-astrobleem-latest`, is at commit
`ec005c196eedabf7d0c25ff6336398c427dd43ac` with CLI DLL SHA-256
`715b14431478b62433498cc516c1cbbb8f418c1d7b39a8e71098ed98d9c9167e`. This includes
the earlier fixes for #376, #377, #379, and #380 plus the newer #389 bank-byte fix
and #386 width-hazard diagnostic. Superman deliberately adopted the older pinned
fork for the `d01db972…` lineage using checkout
`/home/chad/poppy-astrobleem-0d84bf5d` and CLI DLL SHA-256 `771916f2…993a`; keep it
for exact reproduction. The corrected compiler exposed real latent overlap and
illegal-addressing defects; the source and pack guards were repaired before the
bounded exact-hash run. Treat the list below as current project policy, not as a
claim that latest Poppy still silently miscompiles these cases: several are now
hard errors or warnings in the fork, but the byte and seam guards remain mandatory
because Superman relies on densely packed banks.

1. **`.org` overlap was silent in old upstream Poppy.** A section that grew past the
   next `.org` got truncated/overwritten without warning. This produced our worst
   bug: a handler chain grew past `$F601`, the `.org $F602` section assembled over
   its tail, and a lost `sec/rts` corrupted the boot RAM-test. The corrected fork
   rejects this class (#377), but after every layout change still assert slack seams
   in the ROM-pack script and confirm the bytes just before each `.org` boundary
   are the expected terminator/padding. Original upstream report:
   [Poppy #377](https://github.com/TheAnsarya/poppy/issues/377#issuecomment-5283787467).
2. **Mode inference after returns is fixed, but explicit width directives stay
   load-bearing.** Old upstream leaked M/X state across labels after
   `rtl`/`rts`/`rti`/`brk`, so code after an external entry label could be sized
   from the previous routine's tail. The latest fork resets inference to the last
   explicit `.a8`/`.a16`/`.i8`/`.i16` declaration at those labels. Keep those
   declarations at entry labels anyway, and byte-audit A8 code with 16-bit-looking
   immediates after assembling.
3. **Never insert code mid-file in `interp.pasm`** — long-range branches can still
   exceed architectural reach or disturb packed branch islands.
   Append new bodies at the end / in escape banks and reach them with stubs.
4. **Use explicit `rep`/`sep` and `.a*`/`.i*` around width-dependent immediates.**
   The latest fork diagnoses the narrow branch-over-width-change hazard (#386);
   it does not infer runtime caller state across every independently callable or
   multiply-entered label. Historical August 21 source lacked explicit entry-state
   contracts in three helpers, so those builds contained bad bytes: renderer
   `copy32` had `LDY #$B700` followed by a backward branch into `obj_place`, generic
   `udiv` had `LDY #$0620`, and shared `ix_wneg` had `69 FF 85` at its A16
   immediate. Current source repairs all three and the ROM packer asserts their
   exact bytes. These are closed source/packing regressions, not a blanket claim
   that the pinned compiler still emits them from current source.

   One distinct compiler case remains open as
   [Poppy #391](https://github.com/TheAnsarya/poppy/issues/391): a conditional
   branch target textually after `RTS` is reset to the declared width and can
   silently truncate an immediate even though the taken edge has a wider live
   mode. The eight-byte minimized repro is confirmed against pinned commit
   `ec005c1`; current `ix_wneg` avoids the vulnerable immediate and is byte-guarded.
   Reopen any other compiler attribution only with a minimized reproduction against
   the pinned DLL or a failing emitted-byte assertion.
5. **Forward-reference sizing bugs are fixed in the corrected fork.** Old upstream
   mis-sized forward `jsl target` and `jml [$1234]` during semantic layout, froze
   labels before pass-2 macro expansion, and later also mis-sized forward-referenced
   `=` constants. The fork fixes the reported cases (#376 plus the forward-EQU
   follow-up), but keep pack-time byte/seam assertions around dispatch tables and
   packed islands. Original minimized evidence:
   [Poppy #376](https://github.com/TheAnsarya/poppy/issues/376#issuecomment-5283787271).
6. Escape banks: start files with `.snes`(+`.sa1_enabled`); use explicit `jsl.l`/`jml.l`
   for cross-bank; branchless sign-extension beats branchy (see `escape-bank` notes in
   PROFILE_CAMPAIGN).
7. Symbol constants shared between `.pasm` files (e.g. `lh_nofire=$00F5C0` in escbank)
   do NOT track relocations in the other file. **After moving anything in `interp.pasm`,
   grep every other `.pasm` for hardcoded addresses into it** — a stale one is a
   mid-instruction `jml` landmine that presents as a silent SA-1 runaway.
8. **Invalid 24-bit operand forms now fail loud.** Old upstream turned examples
   like `sta $7E74C0,y` into `99 C0 74` and `stx $7E1234` into `8E 34 12`,
   silently discarding bank `$7E`. The corrected fork rejects the unsupported
   forms (#379) and also rejects narrower suffixes that would truncate a resolved
   long encoding (#385). Still reject known bad encodings in the ROM packer and
   express the operation through a legal long-X sequence or explicit helper.
9. **Macro sizing and ca65 macro invocation bugs were fixed in the corrected fork.**
   Old upstream could emit macro bytes without moving following labels, and
   macro-local branches could fail operand evaluation. Keep macros out of packed
   production islands unless the exact generated bytes are compile-tested and
   covered by pack assertions.
10. **The ca65 converter is improved, not a trusted translation path for this repo.**
   The corrected fork fixes the reported dot-directive, local-label, and macro
   invocation failures (#380). Any converted output still needs normal source
   review, build, and byte/audit gates before it can enter Superman.

The public minimized fixture bundle for the original old-upstream failures is
[poppy-65816-repros](https://gist.github.com/astrobleem/df4465b29b4ea740e5cbc21b44249ad9).
The latest local fork also carries regression coverage for the follow-up fixes:
return-label width reset, forward-EQU sizing, parser error propagation, `.incbin`
sizing, `.w` truncation rejection, `-name` lexing, `.sym` bank export, caret
bank-byte evaluation, and branch-over-width-change warnings.

## 3. Emulator-harness operational gotchas

### Codex sandbox and localhost harnesses

Mesen/Nexen/optest validation uses localhost sockets. The host AppArmor workaround in
`.codex/fix-bwrap-loopback-apparmor.sh` verifies that raw `bwrap --unshare-net` can
configure loopback, but it does not change Codex's per-command network-restricted
sandbox profile. Ordinary shell commands may still block `127.0.0.1` with
`Errno 1` / `Operation not permitted`.

For repeatable filtered optest work, use:

```sh
bash tools/run_optest_filter.sh 'FILTER TEXT' 120
```

Approve that wrapper prefix once for emulator work. For any other localhost-dependent
MCP harness, use the Luna playback-watcher role. Its project role file keeps
`workspace-write` filesystem isolation and enables network only for that agent via
`sandbox_workspace_write.network_access=true`. This setting is read when the agent
session starts; changing it cannot repair a watcher that was already spawned under
a network-disabled permission profile. Do not retry a failed loopback command inside
the same default Sol sandbox; inspect exact host processes first if a port may have
been left occupied.

### Mesen MCP (`mesen_mcp` Python)
- Needs `DOTNET_ROOT=/home/chad/.dotnet8` (and `.dotnet8` first in PATH).
- Long-running McpSession scripts die with exit 144 when run FOREGROUND under an agent
  Bash tool — run them in BACKGROUND and poll the output file.
- Use `socket_timeout=120` for sessions that run thousands of frames per call.
- `write_hex(addr, hex, 'Sa1Memory')` works while the SA-1 runs — poke-driven labs
  (runtime-pokeable IRAM handlers) beat rebuild-per-variant sweeps.
- A save made while an exact SA-1 execution stop is being delivered is a nested
  debugger artifact, even if the save call completes and repeated bytes match. The
  campaign labels it `sa1_exact_entry_nested_forensic`,
  `nested_sa1_entry_nonresumable=true`. Do not reload it to infer ROM scheduling,
  collision, or IRQ behavior. Use the campaign's S-CPU rendezvous and an authenticated
  `post_entry_safe_snes_boundary` checkpoint instead.

### MAME 0.287 (the arcade oracle)
- Lua: taps/subscriptions must be held in GLOBALS (else GC'd); `register_frame_done`;
  headless tracing = `-debug -debugger none`; PC reads back +2 (prefetch).
- **`set_input_line` is NOT exposed to Lua** — you cannot inject IRQs from a script;
  a "did it fire" tick-trace control is mandatory before trusting any injection result.
- Snap-confined MAME **cannot read `~/.claude` paths** — put scripts/artifacts under the
  project tree.
- `capture_at_pc` is prefetch-skewed → unreliable `[SP]` for stack-frame functions; use
  full-tick lockstep (`tools/lockstep.py`) for rts/table-class captures.

## 4. The coroutine-scheduler IRQ contract (why idle-collapse is clamped)

The game's per-frame tail is a cooperative coroutine scheduler (switch-out `$0532`,
switch-in `$0796`, select `$075C`, idle spin `$0818`). Decoding it revealed a hard
design contract, and any speed lever that increases IRQ density must respect it:

- Per-task stacks are TINY (256-512 bytes; `$087E` is the preceding `lea` base and the actual
  one-entry-per-slot floor table begins at ROM `$0882`). Every IRQ context save costs 66 bytes
  (6-byte exception frame + 60-byte
  `movem.l d0-d7/a0-a6`). The game even ships its own switch-in floor check with a
  "---Task Stack Error---" string — whose error handler jumps OFF-ROM (`$1000AE`,
  a dev-board address) and derails.
- **Contract: IRQ6 may only arrive when tasks are shallow** — on hardware, tasks finish
  each activation well within a video frame and the CPU idles at `$0818` (main context,
  roomy stack), so vblank never catches a task deep.
- Breaking the contract (IRQ spacing below a task activation's work window) fails two
  ways, both observed: (a) a deep-caught task's save blows through its floor into the
  neighbor's saved context → corrupt resume PC / off-ROM error path → `$DEAD` derail;
  (b) interleaving reorder makes a consumer poll a flag before its producer ran — if the
  poll loop is a NATIVELY-ESCAPED body, the native loop never returns to the interp
  core, `$AC` never decrements, no further IRQ can ever fire → system-wide livelock.
- Hence the shipped idle-collapse clamps `$AC` DOWN to `$2000` (never raises it — an
  unconditional store refills faster than the loop drains and starves the IRQ), which is
  longer than the longest task activation. Empirical boundary: ≤`$0800` fails at the
  first mass-coroutine-creation event; `$2000` is stable. Full narrative:
  [the historical profile campaign](../history/performance/PROFILE_CAMPAIGN.md).
- R5 also ruled out replacing that drain with real-vblank `WAI`. A masked NMI wake from main idle
  and a more conservative post-render supervisor wake both reproduced `$080100`/`$DEAD` at gameplay
  ticks 767/765 while sampled stack margins remained positive. The delay protects inter-tick
  producer/consumer ordering, not only against interrupting a deep task. See
  [the R5 scheduler experiments](../history/performance/R5_SCHEDULER_EXPERIMENTS.md).
