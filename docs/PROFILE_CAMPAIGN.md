# PROFILE_CAMPAIGN.md — coverage-campaign steering table (Phase 0)

Created 2026-07-02 (Phase 0 of the plan in `~/.claude/plans/enchanted-booping-summit.md`).
All numbers SPIN-FREE (`tools/hle_span.py tick` — df_spin/dfg_rff exec-hook method; the old
`CYCLES=1 B1PC` tick numbers carry up to ~4 frames of spin pollution and are OBSOLETE).
Budget = 179K SA-1 cyc/frame (60fps). Update this file at every checkpoint.

## Commands (mechanical re-profile)

```
python3 tools/hle_span.py /tmp/supermn-scratch/<T> tick            # tick total, escapes-full
ESC0=1 python3 tools/hle_span.py /tmp/supermn-scratch/<T> tick     # pure-interp arm (rate calib)
B1PC=0818 CHOKE=1 SWIN=1 SEL=1 GPPROF=1 ALLSTREAM=1 \
  EXACT=01C000-01F1FF,00CB00-00CEFF,023000-024FFF,011000-012FFF,000400-0007FF,000800-000FFF,00C100-00C9FF \
  python3 tools/lockstep_trap.py /tmp/supermn-scratch/<T> 2F60 1   # cluster histogram + fire ctrs
python3 tools/freerun_rate.py 600                                  # topline ticks/frame (no injection)
python3 tools/tick_timeline.py <T>       # per-instr cycle attribution (lh_off-hook; end-detect flaky)
python3 tools/body_residency.py <T> <ENTRY24> [EXIT24=inext]       # per-tick residency of one body
```

## R1/R2 — tick totals (escapes-full vs pure-interp), 8 states

| state | class | full cyc | ×179K | interp instrs | ESC0 cyc | ESC0 instrs | rate cyc/instr | interp share (full) |
|---|---|---|---|---|---|---|---|---|
| span_quiet | idle tick | 1,327,882 | 7.4× | 116 | 2,618,150 | 1253 | ~2.09K | ~18% |
| span_mod | idle tick | 1,138,722 | 6.4× | 116 | 2,007,358 | 888 | ~2.26K | ~21% |
| trip1000 | light gameplay | 1,507,984 | 8.4× | 263 | 3,275,019 | 1612 | ~2.03K | ~35% |
| trip1040 | light gameplay | 2,441,535 | 13.6× | 690 | — | — | — | ~50% (est) |
| trip2500 | gameplay | 3,021,161 | 16.9× | 1069 | 8,549,537 | 4860 | ~1.76K | ~63% |
| trip5000 | gameplay | 3,009,618 | 16.8× | 1054 | 8,311,312 | 4700 | ~1.77K | ~62% |
| ce4trip64 | combat | 2,987,802 | 16.7× | 1043 | 8,247,273 | 4660 | ~1.77K | ~62% |
| span_heavy | render-heavy | 2,984,178 | 16.7× | 632 | 12,204,550 | 8004 | ~1.52K | ~32% |

**Topline (free-run, `freerun_rate.py`, attract=demo-gameplay): 16.7× slowdown** — matches the
trip-class injected numbers exactly ⇒ wall-clock ≈ SA-1 cycles, no hidden pacing wall (a forced-`$AC`
feed changes nothing), the cycle-based steering model is VALID. (One earlier 600-frame sample read
60× — attract-section variance; re-check over a longer window next session.)

## R3 — interpreted-cluster histogram (escapes-full, instrs/tick)

| cluster | quiet/mod | trip1000-class | trip2500/5000/ce4 | span_heavy | lever |
|---|---|---|---|---|---|
| $01Cxx–$01F1xx object-proc | 0 | (in the 263) | 279–315 | 0 | HLE (no transpile: dyn jsr(a4)) |
| $023xx–$024xx trap#5 coro | 0 | — | 223–285 | 0 | transpile segments + bail |
| $00CBxx–$00CExx | 0 | — | 157 | 0 | jump-table transpile + HLE residue |
| $011xx–$012xx chain | 0 | — | 136 | 0 | transpile + contiguous ($12B6C done) |
| scheduler $04–$07xx | 25 | — | 38 | 90 | mostly done (swin/sel) |
| $00C1xx–$00C9xx | 2 | — | 12 | 90 | done (c9a6) + tail |
| **cluster total** | ~30 | — | ~850 | ~190 | |

Escape fires/tick: trip-class swin=11 sel=10 ce4=2 13be=2; heavy ce4=5 swin=4 8fa=3 fd2=1 c9a6=3
sel=2; quiet swin=1 sel=1 ce4=1.

## R4/R5 — the non-interp residual (THE open cell)

full − interp×rate ≈ **~1.0–1.1M cyc/tick in EVERY class** (quiet 1.09M, trip1000 0.97M,
trip2500 1.13M) — per-TICK, NOT proportional to frames-spanned. Composition differs: quiet ticks =
mostly frame-flag WAITS inside escape bodies (`tick_timeline` shows a 224K gap at the `$3B54
jsr $26a0` frame-sync; waits self-price at ~0 at realtime); gameplay ticks = native escape bodies +
scheduler + render + some waits. Measured anchors: entry_ce4 first-fire 2.6K/call; hle_12b6c body
1.57K; entry_26a0 16 fires ≈ 69K (incl. a 24K wait span). **Next session, first task:
`body_residency.py` sweep (swin, sel, ce4, 13be, 26a0, 8c2, 2bc2/2bda-class) on trip2500 + quiet →
split the residual into {bodies, waits, IRQ/render} and re-run the projection below.**

## R4b — residency sweep (2026-07-02, body_residency.py, trip2500 unless noted)

| component | fires/tick | cyc/tick | % of 3.02M | class |
|---|---|---|---|---|
| entry_swin | 7.3 | 55K | 2.7% | scheduler |
| lhs_sel | 6.7 | 56K | 2.7% | scheduler |
| lh_sched collapsed scan | ~14/540K window (partial) | ~64K measured, ~360K/tick extrapolated (UNCERTAIN) | 2-12% | scheduler/collapsed |
| entry_c172 (+295a/29b6) | 0.7 | 31K | 1.5% | render/coroutine |
| entry_25110 (call-site span) | ~1 | 28K | 0.9% | collision |
| entry_ce4 | 1.3 | 22K | 1.1% | render |
| entry_d96 | 0.7 | 20K | 1.0% | render |
| hle_12b6c (incl. its ce4 call) | 0.7 | 18K | 0.9% | render shell |
| header callees (8c2/26a0/2bxx/3c36) | ~5 | ~53K | 1.8% | frame-sync/input |
| d0xx family + fb8 + rng412 | ~8 | ~21K | 0.7% | misc |
| 13be/cc10/1008/8fa/fd2/c9a6 | 0 | 0 | — | (don't fire in trip-class) |
| **measured native total** | | **~330-630K** | **11-21%** | |
| interp (rate-based, incl. dispatch) | 1069 instrs | ~1.89M | 63% | |
| **unattributed remainder** | | **~0.5-0.8M** | **16-26%** | dispatch-tax / IRQ / bus / collapsed |

Waits confirmed context-dependent: on span_quiet, entry_8c2 = 109-218K/fire (frame-sync wait),
entry_26a0 = 12-24K; on busy ticks the same bodies cost ~13K (waits absorb idle, vanish at realtime).

**Phase-2.5.0 GATE ANSWER: renderers do NOT dominate the native residual** (known render bodies
~90-120K/tick ≈ 3-4%). The native residual is scheduler machinery + collapsed loops + waits +
dispatch overhead. Consequence for the semantic program (re-surfaced to the user per the gate):
the render pipeline remains the right FIRST semantic pilot (narrowest contract, best oracle), but
the big semantic-cycle prizes are (a) the interpreted game-logic clusters (already Phase-1/2 faithful
targets first), and (b) the SCHEDULER/tick machinery as a semantic rewrite (native task scheduler
honoring the task-context contract — well understood from Campaigns 1-4; ~170-470K/tick with
lh_sched). Ordering inside Phase 2.5 updates accordingly after Phase 1.

### Instrument notes (hard-won this session)
- **Nexen run_until stops on ANY registered hook** (McpTools.cs checks the GLOBAL match counter,
  ignores the handle) → keep exactly ONE exec-hook registered at a time (body_residency.py does
  add/remove alternation). hle_span/hle_cost are safe only by temporal ordering of their hooks.
- body_residency.py normalizes by the game's tick counter ($40:1C56) — no fragile end-trap.
- lh_off misses loop_hook-collapsed instructions (31 stops vs 116 $4A-instrs on quiet) →
  tick_timeline totals are partial; big-gap ATTRIBUTION is still valid.
- exec-hook addresses must be instruction STARTS (mid-instruction addrs never match).

## CP1 checkpoint (2026-07-03) — end-of-Phase-1 re-profile + re-rank

Tick totals (hle_span tick, same instrument, reproduces the Phase-1.4 numbers):

| state | Phase-0 | CP1 | interp instrs | note |
|---|---|---|---|---|
| trip2500 (avg) | 3,021,161 = 16.9× | **2,439,033 = 13.6×** | 1069 → 680 | −582K, Phase 1.1+1.4 |
| ce4trip64 (combat) | 2,987,802 = 16.7× | **2,499,110 = 14.0×** | 1043 → 716 | −489K |
| trip1000 (light) | 1,507,984 = 8.4× | **1,506,299 = 8.4×** | 263 → 263 | **UNMOVED** |
| span_quiet (idle) | 1,327,882 = 7.4× | **1,324,536 = 7.4×** | 116 → 116 | unmoved |

**Load-bearing CP1 finding: Phase 1's wins were 100% gameplay-class.** The light tick's 263 interp
instrs contain ZERO object-proc/trap#5/task-loop PCs. Light-tick interp (~534K of 1.51M) =
$00CBxx–CExx (55) + $00C1xx–C9xx (47) + scheduler $04–07xx (31) + $008xx (6) + tail 124 — the tail
is dominated by the **$0046xx–$4Cxx family ≈ 43 instrs = the deferred-hard `$4A9E` callee** (called
from the $00C844 dbra loop) + $00D2–D6xx ≈ 24.

trip2500 remaining 680: **object-proc $01C0xx–$1F1xx = 279 (41%)** (spine $01C980 ×42, $01E780 ×39,
$01CD00 ×32, $01E7C0 ×22, $01F180 ×18) / trap#5 residue $023–24xx = 105 (coroutine SHELLS: yield
loops, jsr.l dispatch tax ×1 each, a4-advance scan loops — segment-transpilable between yields) /
$00CBxx–CExx = 62 (incl. dynamic `jsr (a0)` via $1c9a(a5)-table gateways) / sched 38 / $011–12xx 25
/ $00C1–C9xx 12 / tail ~153 (again $004Bxx–4Cxx ≈ 24+).

**Re-rank (score = avg+light saving per session; both classes bind the ≤358K insurance exit):**
1. **$00CBxx + $00C1–C9xx + $4A9E family** — ~130K avg + ~294K light, ~2 sessions ≈ **212K/s**;
   the ONLY interp cluster that moves the light tick; hardest class (dyn jsr(a0) + link-frame $4A9E).
2. **trap#5 shell segments** — ~185K avg, 0 light, ~1 session (known CORO_PCS machinery) ≈ **185K/s**.
3. **object-proc $01Cxxx** — ~491K avg, 0 light, ~3 sessions (spec→v1→widen) ≈ **164K/s**; biggest
   single prize + biggest unknown.

Decision: proceed per plan with **Phase 2.1 A1 (object-proc spec-only, timeboxed)** — largest single
cluster, unknowns gate the campaign tail; queue trap#5-residue (2.3) + CBxx/$4A9E (2.2) immediately
after — both are now well-characterized. CP1's $AC free-run soak: run alongside A1; the freerun
chunk-sensitivity item stays open (injected spin-free ticks remain the steering currency).

## Phase 2.1 A1 — object-processor spec: DONE (2026-07-03), A2 = GO

**Full spec: `docs/OBJPROC_SPEC.md`.** The "un-escapable dynamic coroutine" verdict is SOFT: one
scheduler task, TWO resume PCs ($01E7C0 render pass, $01D5F0 physics), each yielding at the trap#5
immediately before its resume PC; the internal jsr(a6) ping-pong is structural (targets $01E7B0 /
$01C99E via the $350a private stack — $3506(a5) is its top slot, resume-set = {$01C99E} by
construction); the hot `jsr (a4)` at $01F096 calls **[$3514(a5)] = $0D96 = entry_d96 (ALREADY
NATIVE)** with a 7-word caller-cleanup frame; all pc-rel jump tables enumerate small; the 16-slot
spawn table ($31c2) is all-zero on every triple (its cold per-slot jsr(a4) handlers = the bail
guard). A2 = transpile-first with 2 reusable features (F1 guarded direct-link jsr(An), F2 pc-rel
table) + CORO_PCS dispatch; **projected −470–530K cyc/tick on gameplay ticks (2.44M → ~1.95M ≈
10.9×), zero light-tick value.** New instruments: `lockstep_trap.py STREAMDUMP` (chronological
fetch stream) + `tools/disasm_region.py` (stream-annotated listing).

CP1 $AC soak: 1800 chunked frames free-run STABLE (no freeze, ticks advance) — rate read 69.2×
= the chunk-sensitivity anomaly again (per-frame-pause reads ~16.7×); stability box CHECKED,
rate-mode question still open.

## Phase 2.1 A2 — objproc coroutine bodies SHIPPED (2026-07-03): trip2500 13.6× → **11.9×**

Both visits native, dispatched via **bank-$01 xlat pages** (512-page layout, index=(bank<<8)|(PC>>8);
zero bank-$00 changes — ors_rte_x→ojmp_hook→xlat_dispatch was already the route):

| body | commit | win (cyc/tick) |
|---|---|---|
| entry_1d5f0 physics @ $97:EC00 (pilot) | 296cb90 | ce4 −93K, t25 −16.5K |
| entry_1e7c0 render @ $98:AE00 (+entry_d96t, esc_udiv copy) | 2a6b97f | t25 −286K, ce4 −287K |
| **total** | | **t25 2.439M→2.136M (11.9×, 680→518 instr); ce4 2.499M→2.119M (11.8×)** |

Transpiler features (071b69b, all inert where unused; ce4t/29b6t regen byte-identical): **F2**
`--jt=BASE:MIN:MAX` pc-rel jump tables (fused move.w+jmp → switch on the index + interp-bail
default — un-enumerated/garbage indices stay faithful); **F3** jsr abs.w; **F4** move.l→Bcc (tst32);
**F5** `--bail` = the Phase-1.2 generic bail-to-interp (CCR/X-reader ops excluded; 8 cold edges in
the render body: 2 divs, 4 muls, 2 dyn-bclr). **F1** guarded direct-link for jsr (An) — the hot
$01F096 jsr(a4)→[$3514]=$0D96 stays native via a **pushed-$00FB:cont-sentinel return + same-bank
--table variant (entry_d96t)**. F1 LESSON (cost one debug round): jsr(An) callees take the TABLE
convention (return on stack); the set-$40/$42 bridge shape fits only STANDARD-convention re-simulating
callees — the old $92 entry_d96 exits via popped-PC `jml inext`, which fetches a sentinel as a 68K PC.

Gates (each body): FULLDIFF GREEN ×3 triples + **A/B diff-set-identical** (POKEROM-zeroed xlat entry
arm) + ESC0 GREEN + smoke OK + light tick untouched (1.507M/263 — objproc is gameplay-class only).

**A3 widen queue (residual objproc interp ≈ ~125 instr/tick):** the latch pass + jsr(a6) ping-pong +
side-A 16-slot scan ($01E780..$01E7BE + $01C986..$01CD60, interpreted between the two native visits)
— needs either a 2nd entry at $01E780+mid-entries or extending the visit-1 body across the backward
`bra $1e780`; plus the bsr $1f1fe render-record builder (t50 anim path, bridges to interp).

## Phase 2.1 A3 — objproc middle native (objproc_mid, 2026-07-03): trip2500 11.9× → **11.1×**

**objproc_mid** (escbank4 $98:EAD7, HAND-WRITTEN — the hle_12b6c pattern, not more transpile
plumbing): entry_1e7c0's backward-`bra $1e780` exit stub retargeted `jmp objproc_mid` (nop-padded
to the original 14 bytes = ZERO shift, byte-diff-verified), running the whole interpreted middle
straight-line: latch pass (8-slot) → ping-pong pushes ([a7-4]=a6, $34c6:=a7-4, [a7-8]=$0001E7B0)
→ side-A a1/d3 restore + 16-slot $31c2 status scan + w($34c2) test → yield (PC=$01E7BE, mask:=4,
Z=1 CCR; the trap #5 itself stays interpreted). The structural jsr(a6) round-trip is SKIPPED —
[$3506]==$0001C99E is GUARDED up front and the movem/private-stack re-pushes are value-identical.
Guards (all pre-write, restart-at-$01E780 idempotent): a6/a7 hi==$00F0, a6lo≥$20, the $3506
continuation. Bails: first non-zero status byte → $01C9B0 (a0/d4/d5/a6=$01C99E/a7-8 + move.b CCR
materialized); w($34c2)≠0 → $01CD44. NOTE: no triple lights the $31c2 table — the slot-bail edge
is faithful-by-construction, unexercised by the gates (same for $34c2≠0).

**Win: t25 2.136M→1.983M (−151K, 11.1×, interp 518→403); ce4 2.119M→1.971M (−148K, 11.0×);
light 1.508M/263 untouched.** Per-instr rate ~1.31K (scan/latch are cheap beq/dbra ops — below
the 1.76K average; the plan's 220K estimate overshot for that reason).

Gates: FULLDIFF GREEN ×3 (diff sets byte-identical to pre-A3 baseline) + A/B set-identical
(POKEROM 2B2A40:000000 = the $01E7C0 xlat entry) + ESC0 GREEN + smoke OK + **yield-state identity**:
exit_dump at $01E7BE — all-64KB WRAM + full reg file/CCR byte-identical to the shipped A2 build
(the only int-arm delta is the PRE-EXISTING 3-byte below-SP F1-sentinel residue at $F00BD1, present
in A2 too). exit_dump now takes the full 24-bit trap PC (pass 1E7BE not E7BE — $0716 bank compare)
and grew lockstep_trap's POKEROM arm. Gate tools now resolve build/interp.sfc repo-relatively and
honor NAT=<path> (worktree-parallel runs without clobbering /tmp/b0_native.mss).

**A3 residual SHIPPED (same session): entry_1f1fe** — visit-1 regen'd `--escapes=D96,1F1FE`
(regen determinism first verified: byte-identical to deployed modulo the 5 FD→FB sentinel sites;
the C172/D718 drift lesson). `--escapes=1F1FE` rewrites TWO sites: the bsr → static bridge
($40:=native resume label, $42:=$00FB sentinel, `jmp entry_1f1fe`; the STANDARD-convention body
re-simulates that as the pushed return → its rts pop routes ors_pre→ors_98chk native resume), and
the jsr(a4) guard chain gains an ==$01F1FE arm → **entry_1f1fet** (--table variant; never fires at
that site — mechanical ESCAPED-set arm; both variants must exist same-bank). Label-collision
gotcha: both variants in ONE file need `s/1f1fe/1f1fet/g` on the t-variant (labels embed the pfx;
d96/d96t never collided only because they live in different banks). t50 instr 433→409 (−24 = the
builder fired); t25/ce4 unchanged; escbank4 → $F5B3. Same full gate battery GREEN incl. t50
yield-state identity (same 3-byte below-SP sentinel residue class, tick-end washed).

**Then:** 2.2 CBxx+$4A9E per the CP1 re-rank (2.3 trap#5 shells SHIPPED below; 2.2 slice 1 SHIPPED below).

## Phase 2.1 item 2.2 slice 1 — the light-tick lever MOVES (2026-07-03): light 8.4× → **7.7×**

**THE FIRST LIGHT-TICK WIN OF THE CAMPAIGN: trip1000 1.509M → 1.378M cyc (−131K, interp 263→183).**
STREAMDUMP on trip1000 resolved the light tick into four task visits (resumes after $0796):
$46DE (11i, small — residual), **$C604** (26i: the $C58A game-mode yield loop), **$C78E** (56i:
movem/push spine + `jsr $4a9e.l` + tail w/ the hot `jsr (a0)` via $1c8a(a5) → xlat → entry_ce4t)
and **$CD1A** (30i spine; stable across tick classes). All three shipped as --coroutine bodies in
escbank5 + CORO_PCS (bank-$00 xlat pages, existing machinery). entry_c604 registers resume $C604
but decodes from the loop head $C58A (the resume instr is `bra.b $c58a`; the --coroutine
backward-bra heuristic would otherwise decode 1 instr). entry_cd1a ends in a FAITHFUL rts (pops
the real $D522 return → ors_pre routes real banks to the interp); its post-rts pc-rel jmp(a0)
dispatcher/handler chain (~50i: $D522/$CEB6/$CF8A/$D6B0/$D226 stubs) = the 2.2 residual, along
with $46DE + the $3B48 prologue. Gameplay triples: byte-identical sets (the 2.2 tasks yield at
OTHER PCs there — $C170/$C846/$7828/$11752 etc. = future CORO additions); span_quiet untouched.

**F6 `--xflag` (transpiler, inert-off):** entry_4a9e has 22 X-setter sites (lsl/lsr/neg/subq) —
hand-patching is untenable, so the trap5-shells lesson became a transpiler mode: emit $A2 from the
live native carry at add/sub/addq/subq (X=C / borrow), inside dynamic-shift loops per step
(count=0 → untouched, faithful), after imm-shift chains, and NZ-derived for NEG. Guarded inert:
the deployed entry_1e7c0 regen is byte-identical without the flag.

**$4A9E resolved (the old "hard target: link frame + uninit-local read" deferral):** it transpiles
clean with --bail + --xflag; the REAL story behind the deferral is that its link-frame locals are
read UNINITIALIZED → its outputs are below-SP-garbage-dependent, and that garbage ALREADY differs
interp-vs-MAME on the deployed build (tick-end byte $F0104F: interp 00 vs MAME 10 = this task's
saved-SR X — divergent pre-2.2, GREEN-tolerated forever). The native arm changes the garbage
flavor (saves $19 there), NOT the class: yield dumps show c604 bit-exact, cd1a exact-at-handoff,
c78e CCR/frame diffs all garbage-derived and tick-end-washed except the pre-existing $F0104F.

Gates: FULLDIFF GREEN ×4 (t25/ce4/t50 byte-identical sets; t10 position-identical to the deployed
baseline incl. the pre-existing $F0104F/$F0004D/$F00E19 class) + A/B position-identical (POKEROM
2B180C/2B1CAA/2B1E4E) + ESC0 GREEN + smoke OK + the three yield/handoff dumps as above.

**2.2 slice 2 attempted + DROPPED (drop-rule; the loop_hook-collapse lesson RE-LEARNED):** the
post-rts jmp(a0) dispatcher/handler chain (~59 STREAMDUMP instr/tick: $D522/$CEB6/$D6B0/$D226
dispatchers + $CF8A/$D6D8/$D374 idle rts handlers) was built + registered (7 jmp-state xlat
entries, all gates GREEN) — and HOOKTEST exec-hooks showed **0 fires**: the whole idle chain is
loop_hook-COLLAPSED (dbg_fetch/STREAMDUMP logs the PCs, but they never reach lh_off/op_jmp_idx/
op_rts_norm, so no dispatch hook ever sees them and their real cost is ≈ free). Fully reverted.
RULE (write it on your hand): STREAMDUMP counts ≠ real cost — before scoping any residual, verify
REAL (genuinely-interpreted, ilog/$40:C000) vs ALL, or HOOKTEST a candidate body FIRST; the
hle_span "interp-instr" ($4A) counter ALSO includes collapsed instrs. The light tick's remaining
183 $4A-instrs are therefore an OVERCOUNT of real residual — the true light-tick lever is now
smaller than it reads; next-lever ranking should use cycle deltas, not instr counts.

**2.2 remaining (re-scoped):** the $46DE visit (11i, decode truncates at 5 — cold-middle rts
bounds; needs a decoder range override or stays interpreted), the $3B48 prologue (14i,
branch-reached = choke-allowlist class), sched plumbing (~37i), and the GAMEPLAY-tick task
resumes ($C170/$C846/$7828/$11752/$17586 = CORO additions for the avg tick — likely the real
next lever, cycle-verify first).

## Phase 2.1 item 2.2 slice 3 — entry_c846 (2026-07-03): trip2500 10.2× → **9.8×** (sub-10×)

The gameplay-tick resume census (STREAMDUMP t25, loop-shape screened per the slice-2 rule):
$011752 = 37i straight-line BUT its body carries 13 call-bridges to jah2-convention native
callees → bridging DEMOTES them to interpreted (the cb9e +89K lesson) — that's the PARKED
"contiguous tree + --table variants" item, skipped. $7828/9i, $17586/4i, $C170/1i = drop-rule.
**$C846 = the win**: the c78e TWIN — a per-slot yield loop (trap#5 at $00C844 EVERY iteration →
the resume fires every gameplay tick): movem/push spine + `jsr $4a9e.l` (static-linked to the
slice-1 entry_4a9e, same-bank) + slot-exit guards; dbra-taken → Ltj $C844 = the interpreted
trap. HOOKTEST-verified firing (1/tick) BEFORE gating. Zero X-setters in the spine (4a9e's 22
are --xflag-handled). **t25 1.833M→1.747M (−86K, 9.76×, interp 294→249); ce4 1.732M (9.67×);
t50 1.739M; light/quiet untouched.** Gates: FULLDIFF ×4 identical-set + A/B (POKEROM 2B1ED2,
disabled arm restores the 300-instr lockstep baseline) + ESC0 + smoke + $C844 yield dump
(regs/CCR identical; 3-byte below-SP sentinel residue = the accepted class).

**Campaign line after this session: trip2500 11.9× → 9.8×, ce4 11.8× → 9.7×, light 8.4× → 7.7×.**
Next: the $011752 contiguous-tree item (needs --table variants for its jah2 callees), $46DE
decoder range gap, $3B48 choke class, sched plumbing.

## The $011752 CONTIGUOUS TREE — SHIPPED (2026-07-04): trip2500 9.8× → **9.5×**

The parked Phase-1.1 blob, unblocked WITHOUT the --table-variant work it was queued behind: the
callee-convention census showed all 9 escbank3 callees (12e56/12c1a/129c6/12a92/12af6/117b4/
cc44/cc80/caf6) are ALREADY standard-convention with sentinel-safe `jml.l ors_pre` exits → they
take the pushed-$00FA static bridge directly (cross-bank jml.l, gen_escbank5_syms imports). The
old blocker ("leaf-convention bodies always bounce through the interp") applied to the cb9e-class
bank-$00 gap bodies, NOT these. Pieces:
- **entry_cc10 / entry_ccd8**: FRESH standard escbank5 bodies (--bail --xflag) — their old $92
  bodies never caught this bsr reach (both ran fully interpreted, 6 PCs each/tick).
- **entry_11752** (resume $011752, CORO bank-$01 page): spine first half, 12 static links.
- **The hle_12b6c SPLIT**: a bridge at `bsr $12b6c` would DEMOTE the hle → the emitted ojmp
  bridge is hand-replaced with a zero-push bail AT the bsr ($011778) — the interp runs the bsr,
  bhp_bank_ext dispatches the hle natively, and its rts pops the REAL $01177C return which
  op_rts_norm routes through the xlat into **entry_1177c** (spine second half, jmp-state class,
  bank-$01 page). The spine-split-at-unbridgeable-callee trick is REUSABLE.
- HOOKTEST pre-gate: both halves fire (2/tick). Zero X-setters in the spine.

**Win: t25 1.747M→1.699M (−47K, 9.49×, interp 249→217); ce4 1.684M (9.41×); t50 1.691M; light
untouched (183, no $011752 resume there).** Gates: FULLDIFF ×4 byte-identical sets + A/B
set-identical (POKEROM 2B33F6/2B3474; disabled arm = the 255-instr baseline) + ESC0 + smoke +
$011750 yield dump (regs/CCR identical; 3-byte below-SP sentinel residue = accepted class).

**Campaign line: trip2500 11.9× → 9.5×, ce4 11.8× → 9.4×, light 8.4× → 7.7×.** Next: $46DE
decoder range gap, $3B48 choke class, sched plumbing, CC10/CCD8-class other reaches.

## $46DE — SHIPPED (2026-07-04): F7 --fnfrag + the bridged-callee xlat catch; light 7.7× → **7.6×**

Two findings closed it:
- **F7 `--fnfrag`** (transpiler, gated/inert, deployed-regen byte-identical): Phase-2b decode —
  absorb FAR straight-line rts fragments (a branch target beyond the first linear rts, cold code
  between; same ≤$40/no-control-flow guards as the contiguous Phase 2). Fixes the $46DE 5-instr
  truncation (the hot exit $47EC..rts lives past the cold middle's early rts). Undecoded
  in-window code stays safe: a branch into it references a missing label → LOUD assembly failure.
- **The resume was never an rte**: $46DE is a CALL-BRIDGED callee of the OLD $92 entry_4542 body
  (the $455E cors_disp task) — the bridge pushed the $00FE sentinel and `jml.l inext`'d, so no
  dispatch hook ever saw the callee PC. Fix = the size-neutral bridge swap `jml.l inext` →
  `jml.l ojmp_hook` at that ONE site: xlat[$0046DE] → entry_46de native; its faithful rts pops
  the $00FE sentinel → ors_pre_92 resumes the $92 body. Gate-off/miss → inext (identical).
  RULE: a "resume PC" in the stream after $0796 can be a NATIVE body's interp HANDOFF, not an
  rte — HOOKTEST caught the 0-fire immediately (the slice-2 discipline paying off).

**Win: light 1.374M→1.356M (−18K, 7.58×, instr 183→172); t25 1.699M→1.676M (−23K, 9.37×, the
4542 bridge fires on gameplay too); ce4 1.666M (9.31×); t50 1.674M.** Gates: FULLDIFF ×4
(known position-sets) + A/B (POKEROM 2B179A; disabled arm = the 189-instr baseline) + ESC0 +
smoke + HOOKTEST fire-verify.

**Campaign line: trip2500 11.9× → 9.4×, ce4 11.8× → 9.3×, light 8.4× → 7.6×.** Next: $3B48
prologue (choke class), sched plumbing, CC10/CCD8-class stale-reach audit (old $92 bodies whose
jah2 arms miss bsr reaches — the cc10/ccd8 find suggests more).

## The $92-bridge stale-reach audit — COMPLETE (2026-07-04): 1 candidate, evaluated, DROPPED

Enumerated ALL `jml.l inext` call-bridges (the pre-ojmp_hook convention): 16 in escbank ($92) +
4 in escbank2. Fire-rate screen (stream grep): every bridged callee is COLD on all triples
($2D8A ×8, $2E26, $17DA ×2, $3E0E, $90C4, $24920 ×2 — boot/cold-path) EXCEPT **$00CD1A (1/tick,
BOTH triples)**: the ce58 body ($00CEB4 task) bridges `jsr $cd1a.l`.

**The one swap evaluated and DROPPED (evidence-based):** swapping that bridge to ojmp_hook made
t25 DIFF=9 (2 new bytes: the fd2 counter + a task byte) — and the POKEROM-DISABLED arm reproduced
the IDENTICAL diff: the divergence is NOT entry_cd1a's logic but the ojmp_hook detour's ~50 native
cycles SHIFTING AN IRQ-SLICE BOUNDARY (fd2t fired 3×; one slice-sensitive task byte flipped — the
known $0708-timing-artifact class). Win = −1 interp instr (the body first-guard-bails on t25
state). Timing perturbation for zero win → reverted. **RULE: bridge-swap candidates must clear
the fire-rate screen AND a disabled-arm (POKEROM) timing-sensitivity check — a pure dispatch
detour can flip IRQ-slice-sensitive bytes with zero functional change.**

**Bookkeeping correction: entry_cd1a is DEAD** — HOOKTEST 0 fires on BOTH triples, both reaches
of $CD1A are the ce58 bridge (no trap sits where an rte could ever resume $CD1A). Slice 1's
light win was entirely c604 + c78e/4a9e (the numbers stand; the attribution is corrected). The
body + its CORO entry stay deployed (harmless, provably unreached) — flagged for removal on the
next escbank5 re-org.

**Campaign line (final this session): trip2500 11.9× → 9.4×, ce4 11.8× → 9.3×, light 8.4× →
7.6×.** Next: $3B48 prologue (choke class), sched plumbing.

## The $3B48 GAME_TICK prologue — SHIPPED (2026-07-04): the QUIET tick moves for the first time

The prologue = a jsr-dispatch spine to the 6 native $92 header callees (8c2/26a0/158e|17b4/2d8e/
5c32, all jah2-dispatched) + a 15-reg movem/rts tail — running on EVERY tick class. Shipped as 3
fragments (escbank5): **entry_3b48** (choke-reached: the $3B48 fall-through fetch) +
**entry_3b58/entry_3b70** (rts-pop-reached: the callees exit `jml.l ors_pre` → op_rts_norm →
xlat). Each jsr site is a **JAH2-REACH BAIL** (PC=the jsr itself, zero pushes) — the interp
DECODES the jsr so the hook keeps dispatching the callee native (a bridge would demote it);
interp cost/tick = the 6 jsr instrs only (14 → ~7). Jsr-adjacent return PCs ($3B54/$3B62/$3B68/
$3B6C) are deliberately UNregistered (a body that immediately bails = pure detour).

**Choke allowlist extension (ct_ext):** choke_tramp's 42-byte block was full → its last arm is
now `jmp ct_ext` (size-neutral: jmp+2nop == cmp+bne) with the tail ($0FD2 moved + $3B48 + future
arms) carved at $D2E8 in the dead-25110 corpse, abutting ors_99chk.

**NEW GATE RULE (an A/B arm bit us):** choke-reached entries assume GUARANTEED table hits (the
choke pla's the jsr-return before xlat_dispatch) — POKEROM-zeroing their xlat entry corrupts the
interp stack and runs away (112K-instr hang). The correct A/B for the choke class = disable the
ARM (patch the ct_ext cmp immediate in BOTH bank-$00 ROM copies: D2EE:ffff,52EE:ffff);
pop-reached entries zero normally.

**Win: light 1.356M→1.346M (165 instr); t25 1.667M (9.31×, 199 instr); ce4/t50 GREEN;
span_quiet 1.328M→1.316M (109 instr) — the FIRST quiet-tick movement of the campaign.**
Gates: FULLDIFF ×4 known sets + quiet + A/B (arm-disable, = the 178-instr baseline) + ESC0 +
smoke + HOOKTEST 3/3.

**Campaign line: trip2500 11.9× → 9.31×, ce4 11.8× → 9.3×, light 8.4× → 7.52×, quiet 7.4× →
7.35×.** Next: sched plumbing (the last 2.2 residual).

## Sched plumbing — SHIPPED (2026-07-04): the last 2.2 residual; a GENERAL btst bug caught

Two bodies close the scheduler glue: **entry_75c** (the FIRST task-SELECT after GAME_TICK,
$075C..$0794 — straight-line-reached so lhs_sel never sees it) + **entry_77a** (the DEFER path
entered from the trap#5 handler, $0532→$077A). Both choke ct_ext arms. Two transpiler features:
**F8 `--stopat=HEX`** (hard decode bound + hand-appended seam stub — the defer path FALLS INTO
the $0796 switch-in seam, which entry_swin owns; decode otherwise plows into the switch-in
machinery and stalls in data) and an ungated **rte decode-break** (rte never falls through;
deployed regens unaffected).

**GENERAL TRANSPILER BUG (the sixth FULLDIFF catch): `btst #n,Dn` with n≥8** — capstone prints
`btst.b` even for REGISTER destinations, and trusting the suffix applied the memory-form mod-8
rule to the LOW BYTE: `btst #$1d,d2` (the defer countdown gate, bit 29) tested bit 5 → the
countdown write was skipped ($F00055 $4A-vs-$49). Fixed (register dst = mod 32, hi/lo word
select); deployed-body audit CLEAN (capstone sweep over every `transpiled from` range: the only
btst #≥8,Dn sites in deployed code were these two new bodies).

**Win: quiet 1.316M→1.301M (102 instr, 7.27×); light 1.346M→1.332M (158, 7.44×); t25 1.661M
(197, 9.28×).** Gates: FULLDIFF ×4 known sets + A/B (arm-disable ×2 = the 171-instr baseline)
+ ESC0 + smoke + the disabled-arm bisect that isolated entry_77a during the debug.

**Campaign line: trip2500 11.9× → 9.28×, light 8.4× → 7.44×, quiet 7.4× → 7.27×. The 2.2
residual list is EMPTY** — remaining sched interp = trap/rte/glue singletons (~12/tick, at the
dispatch-mechanism floor). Next altitude: the CP0 strategic fork (contiguous-compile toward
avg-frame realtime / 30fps retarget / semantic-HLE — user decision) + hygiene (entry_cd1a
removal, escbank $F000 overlap).

## Phase 2.1 item 2.3 — trap#5 SHELLS native (escbank5, 2026-07-03): trip2500 11.1× → **10.2×**

The $023-25xxx shell residue = exactly TWO coroutine yield-loop segments per gameplay tick
(STREAMDUMP: resume $024BC2 59 instr / $02429C 68 instr, each $000796-switch-in-entered, each
yielding at the trap#5 immediately before its own resume PC — the objproc pattern). Shipped as
**escbank5** ($99:8000, file $2C8000, NEW): entry_24bc2 + entry_2429c (--coroutine --bail) + their
still-interpreted callees entry_23e34/23e42/259ca/28ddc/24d98, ALL static-linked via --escapes —
incl. the already-native Phase-1.4 roots ($23342/$235E0/$23864 escbank4) and entry_25110 (escbank3)
as CROSS-BANK `jml.l` links (gen_escbank5_syms imports their 24-bit addresses), killing the jsr.l
dispatch tax. Machinery: xlat 512→**768 pages** (bank $02; xlat_dispatch `cmp #$0003`, size-neutral)
+ CORO_PCS += the 2 resume PCs + the **$00FA sentinel arm** (ors_98chk zero-shift tail swap →
ors_99chk, carved at $D2D8 out of the DEAD old-inline-25110 front half — bank $00 has NO free gaps
left; the dead-corpse reclaim is the remaining space source). Post-processing: sed #$00FD→#$00FA +
the 11 mechanically-emitted jsr(An) guarded t-variant arms STRIPPED (all cold; the INDIRECT-BRIDGE
fall-through stays faithful — entry_25110t etc. don't exist and 25110 is too big to duplicate).

**X-FLAG LESSON (a FULLDIFF catch, new failure surface):** the transpiler's known "X-untouched"
gap (gen_addsub never writes $A2; only branch-to-exit edges materialize it) becomes OBSERVABLE
when a coroutine body yields via trap#5 — the interpreted trap SAVES SR (sr_build reads $A2) into
the task frame, so a stale X lands in work RAM ($F00D01 = $14 vs $04 = bit 4). The shell cluster
has exactly ONE hot-path X-setter (`sub.w $2a32(a5),d1` in entry_24d98) — hand-patched (php/rol/
eor/sta $A2/plp at the sbc, carry still live). Cold-path X-setters keep the documented gap.
RULE for future --coroutine bodies: census X-SETTERS (add/sub/addq/subq/neg/shifts, NOT cmp/adda)
on the hot path — any one upstream of a yield needs the $A2 write (or the transpiler grows it).

**Win: t25 1.983M→1.830M (−153K, 10.2×, interp 403→294); ce4 1.816M (10.1×); t50 1.826M;
light 1.509M/263 untouched.** Gates: FULLDIFF GREEN ×3 identical-set + light + A/B set-identical
(POKEROM 2B2ED4/2B3246 = both bank-$02 xlat entries) + ESC0 GREEN + smoke OK + yield-state identity
at BOTH yields (regs/CCR identical; 6-byte below-SP sentinel-vs-return residue = the accepted A2
class, trap-frame-overwritten by tick end; flag vars are TRUTHY words — nat Z=2 vs int Z=1 is the
same semantic).

**NEW (audit find, follow-up): tools/audit_banks.py flags a PRE-EXISTING escbank overlap** — the
$8000 block's bodies have grown to $F29F, PAST the pinned .org $F000/$F400 dispatcher blocks, which
stomp $F000–$F57A of whatever body straddles there (the d386/d3b0 family — almost certainly the real
root cause of their "co-dispatch divergence" xlat exclusion). Latent (excluded bodies never dispatch);
fix = relocate those bodies (escbank has no free tail — move to escbank3/4) then re-test d386/d3b0
through the table. Run `python3 tools/audit_banks.py` after every build until it's wired into
build_interp.sh (blocked on this fix — the audit currently exits 1 on the pre-existing violation).

## Phase-1 progress ledger

| item | status | win | commit |
|---|---|---|---|
| escbank3 in gen_xlat_table BANK_OF_SYM | DONE | infra | e1f49ff |
| entry_12e56 | **RE-SHIPPED** (branch-chain + indexed-EA features; 0 skipped) | (in loop total) | 308ddb9 |
| entry_129c6 | **SHIPPED** (dyn-bset transpiler fix; bit-exact both triples) | 3.2× span, ~43K/tick | cbbd0e1 |
| entry_12c1a | **RE-SHIPPED** (branch-chain feature; 0 skipped) | (in loop total) | 308ddb9 |
| whole $011750 task-loop iteration | 3 of 12 callees now native | 453,950→380,933 = **~73K/tick** | 308ddb9 |
| $011752 contiguous tree | UNBLOCKED (stray-Bcc closed); next: remaining callees ($12a92/$12af6/$117b4) then the tree | — | — |

**Phase 1.4 SHIPPED (`c0628dc`): the $023xxx trap#5 cluster — the biggest single item (~27% of
remaining interp) — is native.** It resolved into 7 ordinary jsr.l/bsr-reached functions called
BETWEEN yields (no coroutine machinery needed). Cost three transpiler features (clr+Bcc
constant-flag fusion, dynamic lsl.l/lsr.l, indexed long load) and the **FOURTH escape bank**
(escbank4 $98:8000, $00FB sentinel — the 9.5KB family needs same-bank internal --escapes links) +
jb2_ext (the jah2_b2 bank-$02 jsr.l extension, dead-space hosted). **trip2500 tick total:
3,021,161 → 2,439,234 cyc = −582K vs the Phase-0 baseline (16.9× → 13.6×; interp 1069 → 680).**
OPEN ITEM (measurement): freerun_rate.py reads 16.7× when pausing per-frame but ~60-67× with
chunked run_frames — a Nexen harness sensitivity, NOT attract variance (deterministic start);
the injected spin-free tick totals remain the steering currency until resolved.

**caf6 UNPARKED — root cause was a GENERAL transpiler bug, not cb9e (`f877b4f`):** `lea (d16,An)`
with a NEGATIVE disp emitted `adc #$0000` for the hi word instead of the `$FFFF` sign extension →
the low-word carry pushed a1 into bank $F1 → rdw_ea routed to IO → a1=0 (found via the exit_dump
INPUT-state differential at cb9e entry: all regs equal except a1). The inertness audit caught the
same latent bug in the deployed entry_12c1a + entry_12e56 → all three regenerated. **The real
convention finding:** leaf-convention natives (entry_cb9e class: jmp-inext exit) are UNREACHABLE
from escape-body bridges — bridging demoted cb9e to interpreted and cost +89K/tick. The pattern
that works: a SAME-convention body in the escape bank direct-linked via `--escapes` (entry_cb9e in
$97 @ $E800, --video), while the old leaf keeps serving the interp chain. **Task loop final:
453,950 → 132,506 cyc = 3.43×, ~321K/tick, interp instrs 245 → 36.** This also DELIVERS most of
the contiguous-tree value (the caf6+cb9e chain is a 2-level contiguous native subtree); the
residual blob share is now ~36 instrs ≈ 65K — still below the drop-rule bar as a standalone item.

**Phase-1.1 COMPLETE through the callee set (`90dc82e`..`3a1aa3a`):** the $011750 task loop now runs
9 of its 12 callees native (12e56+12c1a+129c6+12a92+12af6+117b4 via bhp arms; cc44+cc80 via NEW
jah2_ext_bsr→escbank3 cross-bank arms; 12e56 direct-links 12af6). **Loop iteration 453,950 →
247,087 cyc = 1.84×, ~207K/tick** (interp instrs 245→115). Transpiler gains along the way: dynamic
bset/bclr/bchg, branch chains, indexed (An,Dn.w) EA, dead-cmp elimination, **IO-aware RMW under
--video** (the ea_rmw fast path corrupts $40:lo16 through ROM-valued pointers — game code
legitimately stores through ROM pointers; interp drops those writes; exit_dump differential caught
it). PARKED: entry_caf6 (the $00CBxx gateway; built + corruption fixed, residual walk divergence
tied to bridged-cb9e-interpreted vs native-leaf entry_cb9e — needs the leaf-vs-bridge convention
analysis). **CONTIGUOUS $011752 BLOB: assessed and PARKED by the drop rule** — remaining
blob-addressable share = ~6 same-bank bsr dispatches + ~10 glue instrs ≈ 30-40K/tick, while its 5
bank-$00 calls CANNOT improve without --table variants (leaf-convention bodies always bounce
through the interp; a blob bridge would REGRESS their current jah2 dispatch). The blob becomes
worthwhile bundled WITH --table variants for cc10/cc44/cc80/ccd8 (+cb9e convention work) — queue as
one item, ranked by the profile.

**Stray-Bcc gap CLOSED (`308ddb9`): branch chains** — `producer; Bcc1; Bcc2…` re-consumes the live
source flags (68K branches preserve CCR; the 'tst'/'signed' lowerings are branch-ops-only on
fall-through). Guards: labeled Bcc still raises; 32-bit sources excluded. Also NEW: brief indexed
`(An,Dn.w)` loads. Both inert where unused (9-escape regen byte-identical; val_branch32 5460/0).
Residual risk (standard class): the chain sites sit on deep paths our triples exercise only
partially — default gates + the free-run soak at CP1 are the ongoing net.
transpile.py now HARD-FAILS on UNIMPLEMENTED (exit 2; --allow-unimpl to inspect) — the 12e56 lesson:
a body with skipped instructions can validate GREEN on its shallow path and corrupt on deep paths.
More instrument notes: never $0710-trap an escape's RETURN address (that fetch bypasses dbg_fetch —
trap the NEXT instruction); lockstep_trap POKEOP=<hex16> disables one bhp arm for A/B bisection.

## CP0 projection (per the decision rule) — and the verdict

Model: coverage converts ~85% of interp instrs at ~30× (spike-measured); Phase-3 hand-rewrite =
1.62× on the native residual; wait-share vanishes at realtime (bounded 0.3–0.5M, UNRESOLVED).

| stage | trip1000 (light gameplay) | trip2500-class (avg gameplay) |
|---|---|---|
| today | 1.51M = 8.4× | 3.02M = 16.9× |
| + Phase 1–2 coverage | ~1.07M = 6.0× | ~1.46M = 8.2× |
| + Phase 3 (1.62× on native) | ~0.68M = 3.8× | ~1.04M = 5.8× |
| + wait/IRQ subtraction (optimistic) | ~0.40–0.55M = **2.2–3.1×** | ~0.6–0.75M = **3.4–4.2×** |
| ISA floor (13.3K real 68K instrs/frame, best native) | ~1.5–3× | ~1.5–3× |

**VERDICT: the CP0 rule (> 2× budget → STOP) FIRES.** Even the optimistic light-gameplay projection
lands 2.2–3.1× over budget — at/above the ISA floor. **60fps-every-light-frame is not reachable by
the faithful coverage grind**; the arithmetic that suggested it was based on the contaminated light
numbers. Honest reachable ceiling of Phases 1–3 ≈ 2–4× (i.e. solid ~30fps-class in light/avg play,
slower in combat), with the residual-decomposition open cell moving the estimate within that band.

**Renegotiation options (user's call):**
- **(A) Re-target to smooth 30fps** (logic at 30Hz, 60Hz display — the standard SNES-port compromise):
  needs ≤358K/tick = inside the optimistic band for light/avg gameplay; combat still drops. The
  Phases 1–3 worklist stays EXACTLY as planned; only the exit criterion changes.
- **(B) Semantic HLE** (same per-frame RESULT, less work — rewrite hot systems, not instructions):
  the only road that goes THROUGH the ISA floor toward true 60fps; big/risky; Phase 1–2 work remains
  its prerequisite/scaffolding.
- **(C) Proceed as-is** knowing the landing zone is ~2–4× ("fast playable demo", 15–30fps effective).

## Session-found gotchas (bank these)
- `hle_span.py tick` = the canonical tick metric. Same-run deltas only.
- `freerun_rate.py` reads the game's own tick counter ($40:1C56 BE); NAT loads FROZEN at jh_spin →
  needs the `$0702=0/$0704=1` release pulse first.
- Turning escape gates OFF mid-flight on a NAT free-run HARD-FREEZES the interp (68K PC stuck $0708,
  $AC frozen) — gates must match the state's epoch; harnesses set them before release. (Parked.)
- `tick_timeline.py` (lh_off hook): attribution works, but lh_off misses some instr class (31 stops
  vs 116 $4A-instrs on span_quiet) and idle-end detection is unreliable — fix before trusting totals.
- inext is NOT a universal per-instr point (branch paths bypass it); lh_off is closer but imperfect.

## THE FORK IS SETTLED (user, 2026-07-04): 30fps retarget + sound — kickoff measurements

**Sound track LAUNCHED (PR #11):** 21/21 VGM tracks → TAD MML drafts + projects, all
tad-compiler-check OK, SPC render proven; raw rips/ROM dumps/decoded audio gitignored (rights).
Remaining = the musical pass (FM instruments, BRR drums, tempo/balance) + engine integration
(TAD driver, SPC700 upload, sound-command mailbox → TAD triggers).

**30fps decomposition SEEDED (body_residency, current build):** the wait story has CHANGED
since R4b — waits already self-priced down as ticks got faster: quiet-tick waits now ≈ 120K
(entry_8c2 109.6K = 12.2%, entry_26a0 11.8K) vs the old 224K-gap read; combat waits are
NEGLIGIBLE (8c2 14.8K + 26a0 11.7K ≈ 2%). **Wait-adjusted gap to the 358K/tick 30fps budget:
quiet/light ≈ 3-3.3×, combat ≈ 4.6× (the binding class).** The residual is now native bodies +
dispatch + render/IRQ machinery, NOT waits — the pre-measurement 1.4-3× estimate was optimistic.
NEXT (first task, next session): the full per-body sweep on ce4trip64 (swin/sel/ce4/d96/25110/
objproc/shell bodies) to rank the contiguous-compile + semantic-HLE targets against the 4.6×.

## Combat-tick decomposition (body_residency sweep, ce4trip64, 2026-07-04)

| component | cyc/tick | % of tick | note |
|---|---|---|---|
| **xlat_dispatch span total** | **243K** | **12.1%** | 39 fires/tick; the ENTRY->inext span INCLUDES the dispatched body -> this = the xlat-dispatched-native TOTAL (shells/objproc/fragments/coro), ~6.2K avg per dispatch |
| lhs_sel | 125K | 6.3% | |
| entry_swin | 119K | 5.9% | |
| entry_1e7c0 (objproc render) | 42K | 2.1% | |
| entry_c172 | 33K | 1.6% | |
| waits (8c2+26a0) | 26K | 2.1% | negligible on combat |
| hle_12b6c | 21K | 1.4% | |
| entry_25110 | 15K | 0.8% | |
| entry_1d5f0 | 3K | 0.2% | |
| measured native total | ~580K | ~29% | |
| interp (197 x ~1.7K) | ~335K | ~17% | |
| **UNATTRIBUTED** | **~1.08M** | **~54%** | THE 30fps object — see below |

Measurement caveats: entry_24bc2/2429c/d96/d96t read 0 fires — their exits never pass the
inext anchor inside the span (ors_pre/native chains); they're inside the xlat_dispatch total
instead. Windows ~2.0M/tick (B0->B1 anchors) vs hle_span's 1.68M — use the % column.

**THE PIVOTAL HYPOTHESIS for 30fps: the 1.08M unattributed is dominated by PER-FRAME machinery**
(the interpreted 68K vblank ISR + render/PPU-shadow + IRQ dispatch), which runs ONCE PER DISPLAY
FRAME — ~10-12x/tick at today's sub-realtime speed but only 2x/tick at the 30fps target. If so,
it SELF-PRICES like the waits did (a convergent series: every tick-speedup cuts frames-per-tick
cuts ISR share), and the true 30fps gap is much smaller than the raw 4.6x. NEXT MEASUREMENT
(first task, next session): count vblank-ISR fires/tick + residency of the interpreted ISR body
on ce4trip64, and re-project the gap with the per-frame share scaled to 2 frames/tick. If the
hypothesis holds, the remaining REAL work = the jah2-native bodies (sel+swin = 244K -> the
scheduler semantic-rewrite finally pays) + interp 335K (contiguous-compile).

## ISR verification round (2026-07-04): three suspects ELIMINATED + a steering blind spot found

- **take_irq fires 0× in injected windows** — the $AC countdown (2F60) never expires inside a
  ~200-instr tick, and no hardware path delivers the 68K vblank ISR there either. Consequence A:
  the 1.08M unattributed is NOT the 68K ISR. **Consequence B (steering-validity): every injected
  tick total (hle_span — the campaign currency) EXCLUDES the per-frame 68K ISR cost entirely** —
  free-run reality is higher by the ISR share (this is the long-open freerun-vs-injected
  discrepancy, now mechanistically explained). The 358K/tick 30fps budget MUST count the ISR at
  2 fires/tick — needs a free-run instrument, not lockstep.
- **The SA-1 nmi/irq handlers are bare `rti`** (0 fires) — no native per-frame ISR either.
- Remaining suspects for the 1.08M: (a) **5A22↔SA-1 BW-RAM bus contention** while the 5A22 runs
  the per-frame VID render pipeline (SA-1 stall cycles ∝ frames/tick → still SELF-PRICING at
  30fps, via contention rather than code); (b) window slack (body_residency's B0→B1 anchors read
  ~2.0M/tick vs hle_span's 1.68M ≈ ~300K boundary spin in the denominator); (c) interp helper
  time not captured by body anchors.
- **Next session (30fps track, in order):** (1) a free-run per-frame cost instrument (freerun +
  ISR/frame counters) to price the 68K ISR + close the steering blind spot; (2) a 5A22-contention
  probe (SA-1 cycleCount vs wall-frames with VID stubbed vs live); (3) re-project the 30fps gap
  from FREE-RUN numbers; only then rank scheduler-rewrite vs contiguous-compile.

## Free-run ISR probe (tools/freerun_isr_probe.py, 2026-07-04): the blind spot is SMALL

Free-running the NAT (smoke-release flags: $072E=1,$0704=1) with escapes armed, exec-hook on
take_irq: **7 fires over 7 game ticks (9.41M cyc window, 1.34M cyc/tick — matching the injected
light-class number!)** — the 68K vblank ISR fires ONCE PER GAME TICK, not per display frame: the
$0818 idle-spin FORCE-FIRES the vblank ($AC=1 -> $AA) when the tick's work completes, so ISR
frequency is tick-paced by design. Consequences:
- The injected-window ISR blind spot is ~1 ISR body/tick, NOT 10-12x/frame — the steering
  numbers are only slightly optimistic, and free-run tick cost CONFIRMS them (1.34M ≈ hle_span's
  1.33M light). The scary version of the blind spot is dead.
- The per-frame self-pricing hypothesis for the 1.08M unattributed is WEAKENED: it isn't ISR.
  Remaining suspects unchanged: 5A22<->SA-1 BW-RAM contention during VID render + window slack +
  helper time. The contention probe (VID stubbed vs live) is now the decisive measurement.
- Probe caveats: ISR-body spans didn't capture (op_rte alternation quirk, n=0) — the fires/tick
  + free-run-vs-injected agreement are the load-bearing data; frame counting approximate.

**30fps standing after this round: the gap is REAL (~3-4.6x wait-adjusted, free-run-confirmed),
not an artifact — closing it = the contention probe, then scheduler-rewrite (244K) +
contiguous-compile (335K) + whatever contention reveals.**

## 5A22-contention probe + WRAM-supervisor fix (2026-07-04): the unattributed 1.08M is mostly BUS CONTENTION

**The probe** (tools/contention_probe.py light free-run, tools/contention_combat.py injected
ce4trip64): Nexen's SA-1 core prices bus conflicts into cycleCount (Sa1Cpu::ProcessCpuCycle —
ROM/IRAM conflict +1-2 cyc, BW-RAM 2→4 cyc, whenever the SA-1's access type matches the 5A22's
latched Bus-A type). The 5A22 video supervisor busy-polled FROM ROM at 100% duty. Measured by
parking the 5A22 in a WRAM `bra $` (NOT stp — `_memTypeBusA` is a LATCH; a stopped/wai'd 5A22
whose last fetch was ROM fake-conflicts forever; any idle loop must EXECUTE FROM WRAM):

| class | live | 5A22 parked | contention | share |
|---|---|---|---|---|
| light (NAT free-run) | 1.426M | 1.016M | 411K/tick | 28.8% |
| combat (ce4trip64) | 2.017M | 1.439M | 578K/tick | 28.7% |

Graded stubs (light): the BUSY-SPIN itself is the tax (spin fetch/IRAM = 544K at 100% duty);
the joy BW-RAM hammer is noise (-0.4%); nopping vid_frame made it WORSE (+9% — render periods
are $7E-write/DMA-heavy = LESS conflicting than the raw ROM spin). **Combat accounting: 578K
contention + ~300K window slack ≈ 880K of the 1.08M unattributed; residual ~200K helpers.**

**The fix (SHIPPED, video.pasm):** the supervisor poll loop now lives in WRAM $7E:F000
(wl_setup copies a 23-byte position-independent blob; throttled IRAM poll ~0.7% duty; jsl
$E98004 → vf_tick = joy+vid_frame once per game tick — joy moves from continuous to per-tick,
one-tick-stale harness input pokes). Zero-shift: cv_loop's 21 bytes became boundary-safe pads
(old save states resume the 5A22 at old cv_loop PCs or inside joy5a22 — joy5a22 UNMOVED at
$E9:884A). $8004 = the old VID_INIT no-op slot, repurposed (BOOT_ARM owns the boot jsl).
Validated: REQ-bump → ack + $410002→$410000 forward + render + return-to-WRAM; smoke GREEN.

**Results on the fixed ROM:** light 1.426M → **1.137M (−289K, −20%; 3.18× of the 358K budget)**,
parked residual 138K. Combat **UNCHANGED (~2.0M)**: in-window sampling shows per-tick VID_FRAME
(REQ++ every tick) keeps the 5A22 rendering ~100% of the wall time — combat contention is
RENDER-PERIOD conflicts (5A22 ROM code fetches + $41 BW-RAM shadow reads while the SA-1 works),
not spin. **Next contention lever (rank vs scheduler-rewrite/contiguous-compile): relocate the
render's hot inner loops (decode_tile/vid_bg/vid_obj walkers) to WRAM too** — same latch rule.
Also flagged for the 30fps pacing phase: today's render spans MULTIPLE display frames per tick;
at 30fps it must fit ~2 (delta rendering / cache hit-rate work may be needed).

**Free-run render gotcha (pre-existing, both ROMs):** in the NAT free-run harness mode the
$AC-reload VID_FRAME path effectively doesn't advance FRAME_REQ per tick (REQ frozen; a slow
REQ/ACK oscillation triggers occasional re-renders). Injected windows DO render per tick. The
old light "live" numbers therefore under-count production render contention slightly; combat
numbers are production-shaped.

## pt.21 (2026-07-04): render-to-WRAM SHIPPED but MEASURED SMALL — the lever was mis-premised

The pt.20 "next lever" (relocate the render inner loops to WRAM) is BUILT and VALIDATED
(video.pasm `rc_copy`: verbatim mirror $E9:8000-$8FFF -> $7F:8000 at supervisor boot; the $8004
VF_TICK wrapper jml's the $7F copy; DRAFT PR #13, commit `50dfc62`). It is byte-faithful,
zero-shift, smoke-GREEN, and the render **provably runs from $7F** (exec-hooks vid_frame$7F/
vid_bg$7F fire; the 5A22's program bank is $7F during render vs $E9 on the ROM path).

**BUT the win is only ~3.4%, not the projected ~27%.** Measured on a FRESH boot (Sa1 cyc/frame,
render firing continuously with the heavy BG path + forced tile-decode): **ROM 92464 vs WRAM
89341 = 3123 cyc/frame = 3.4% (~68K/combat-tick)**. WRAM is contention-FLAT regardless of render
load; ROM rises with it. The projected 2.0M->1.45M (~550K, ~27%) over-estimated the render's
contention share by ~8x: the render is DMA/$7E-write-heavy (this doc's own "nopping vid_frame
made it +9% WORSE" already said render < spin), so the CODE-FETCH share — the only part WRAM
relocation recovers — is minor. **Verdict: keep the change (small real win, safe) but the render
lever is spent; the bigger levers stand — scheduler semantic rewrite (~244K) and
contiguous-compile (~335K).**

**HARNESS LESSON (this cost the session): the NAT (dump_b0_native jh_spin transplant) strands
the 5A22 at $00:D161 — its `setcpu(cpu['snes'])` moves the 5A22 OUT of the $7E:F000 supervisor
poll loop, so the render NEVER fires under NAT/injected harnesses (FRAME_ACK frozen;
contention_combat + validate_wl_fix are both render-DEAD, and set_cpu_state('Snes') won't force
it back). This is why pt.20's own migration "doesn't engage" in a fresh session — the pt.20
combat contention numbers are NOT reproducible from the NAT.** Measure render/5A22 changes on a
FRESH boot instead (cpu5a22_boot puts the 5A22 in the supervisor): inject the combat shadow +
force game-alive ($400002=$0300/frame) + bump FRAME_REQ/frame. Tool: `tools/measure_render_wram.py`.

## pt.22 (2026-07-05): current interp-residual re-profile → lever = escape the coroutine's leaf handlers

User picked the **contiguous-compile lever** (make the 335K combat interp residual native). First
step = re-profile the CURRENT residual (all prior cluster breakdowns are stale — A2/A3 objproc,
trap#5 shells, and the whole CP1-2.2 light-tick campaign shipped after them). Method:
`lockstep_trap.py <triple> 2F60 1` env `B1PC=0708 CHOKE=1 SWIN=1 SEL=1 GPPROF=1 ALLSTREAM=1
ENTRYCLASS=1` (the 2-level-nesting + ABSOLUTE-ROM Nexen-under-Bash recipe; runners in the pt.22
session scratchpad).

**Fresh injected profiles (current `main` build) — ADDRESS-INDEPENDENT, correct:** combat (ce4trip64)
**204** interp fetches/tick; light (trip1000) **133**. Dominant BOTH-class residual = the
**sprite-build coroutine system**:

| cluster | combat | light | character |
|---|---|---|---|
| $00CBxx–CFxx ($00CE58 coro + $00CEB6 handler) | ~54 | ~61 | jump-table dispatch + indirect sprite-draw `jsr [$1cb2/$1c9a(a5)]`; dbra loops |
| $00D2xx–D6xx ($d522/$d6b0/$d226 handlers) | ~24 | ~28 | same `lea $T(pc),a0;adda -2(a4);movea (a0),a0;jmp(a0)` jmp-table idiom |
| scheduler $000 4xx–8xx | ~45 | ~35 | IRQ/coroutine machinery |
| GAME_TICK spine $003Axx–3Bxx | ~29 | **~4** | static `jsr(pc)` tree, callees already native — **COMBAT-ONLY** ($1cca(a5)=0 early-exits light at $3AB6) |
| $024xxx trap#5 residue | ~15 | — | escbank5 shell residue |

**⚠️ CORRECTED FINDING (a mid-session error, caught + fixed same day): `entry_ce58` FIRES — it is NOT
dead.** An intermediate step wrongly concluded the three `op_rte` coroutine escapes (c2f8/4542/ce58)
"fire 0× / the dispatch is systemically dead." **That was a HOOKTEST BANK-ADDRESSING ARTIFACT** — the
escbank bodies execute at **`$92:xxxx`**, but the HOOKTESTs used bare `$00`-bank addresses
(E889/E3C9/E810), so they hooked dead addresses; the `take_irq` control was genuinely bank-$00 and fired,
falsely validating the addressing. The evidence it actually fires:
- **Fetch stream (address-independent):** the coroutine **spine `$CE58–$CEB0` is ABSENT** from the
  interpreted stream (it runs native); only `$CEB2` ×1 — entry_ce58's documented native EXIT
  (`Lce58_ceb2` sets PC=$CEB2, `jml inext`, escbank.pasm:12739) — and the **bridge-interpreted handler
  prologues** ($ceb6 ×6, $d522/$d6b0/$d226 ×1-2) are present. Exact signature of entry_ce58 firing.
- **Corrected HOOKTEST:** `entry_swin @ $92FB00` → `matchedEventsEmitted=11` (== its counter =
  calibration proof the `$92` addressing is right); `entry_ce58 @ $92E889` → **fires 1×/tick**;
  c2f8/4542 @ their `$92` addresses also fire. (Independent code-trace corroboration: the resume routes
  `entry_swin → op_rte → ors_rte(=$CEB4) → cors_disp → entry_ce58` and works.)

**RULE (BANKED — this cost real time): HOOKTEST escbank bodies at their `$92:xxxx` EXECUTION address, and
calibrate every HOOKTEST against a known-firing escape AT `$92` (`entry_swin @ $92FB00 == 11`), never a
bank-$00 control.** (The `$07xx`-counter caution still holds — but the fix is the right hook *address*,
not distrusting the escape.)

**So the real residual is the leaf handlers `entry_ce58` CALL-BRIDGES TO INTERPRET** (escbank.pasm:12539+):
`bsr $d522`→brce58_3, `bsr $ceb6`→brce58_4, `bsr $d6b0`→brce58_5, `bsr $d226`→brce58_6, `jsr $cd1a`
→brce58_1 (all "interpret callee"); only `$26fa`/`$d18a` are native bridges. These handlers are the
same jump-table state-handler class as the shipped siblings `entry_d5c4/d6fc/d386/d3b0/d18a`.

**LEVER (pt.22) = escape the leaf handlers** (the coroutine dispatch already works, so no revival needed):
for each ($ceb6 highest @ ×6, then $d522/$d226/$d6b0/$cd1a), transpile the handler (all clean, 0
UNIMPLEMENTED; `jmp(a0)`→ojmp_hook, sub-handlers native-if-in-table else interpret) and **retarget its
entry_ce58 bridge interpret→native** exactly like `brce58_1`→`jmp entry_26fa` /
`brce58_7`→`jmp entry_d18a` (escbank.pasm:12560-12565, 12732-12737). Then batch the still-interpreted
sub-handlers (like the `$d01a/$d05e/$d0bc/$d07a` set). Gate + bit-exact (ON-vs-OFF `$40`/`$41` diff=0,
`val_frame_diff.py`) + **`$92` HOOKTEST-fire** + smoke each. Full plan: the pt.22 approved plan file.
Related: [[scheduler-switchin-shipped]], [[bulk-transpile-phase]], [[escape-deploy-shift-safe]].

### pt.22 BATCH RESULTS (branch `pt22-lever-b-handlers`) — the "mechanical repeat" premise is INVALIDATED

Executed the lever handler-by-handler with per-handler empirical validation (combat + light bit-exact
diff vs MAME, `$92` HOOKTEST fire, smoke). Outcome split cleanly and **not** the way the plan assumed:

| handler | bridge | result | Δ interp/tick | commit |
|---|---|---|---|---|
| `$ceb6` | brce58_4 | ✅ **SHIPPED** bit-exact both-class | −24 | `1bef4cb` (pilot) |
| `$d6b0` | brce58_5 | ✅ **SHIPPED** bit-exact both-class | −8 | `375198e` |
| `$d522` | brce58_3 | ❌ **DERAILS** (reverted) — 62B RED | — | — |
| `$d226` | brce58_6 | ❌ **DERAILS** (reverted) — 65B RED, **`trap=False`** | — | — |
| `$cd1a` | brce58_1 | ⏸️ untested (harder: 30 instrs, 4× indirect `jsr`/`ibridge`) | — | — |

**The derail (`d522`/`d226`):** the naive interpret→native bridge flip breaks the WHOLE tick — the
coroutine spine's rts chain corrupts so `entry_ce58` never returns (`trap=False`; the tick runs to the
`WN=65536` instr budget → the lockstep diff HANGS >2min). `swin` drops 11→6; both share the exact same
divergence signature (`$F00005/09/4D/29F/2E9/30A-F…`). **It is NOT any static predicate** we can screen on:
- `d6b0`'s OWN targets `$D6FC/$D718` have escapes (`entry_d6fc`/`entry_d718`) and it's GREEN → not "escaped target".
- ALL targets (incl. d6b0's) are `; coroutine task body: NO return-push` → not "coroutine-convention target".
- `entry_d5c4` (d522's index-0 target) **fires 2× AND is GREEN in the baseline** (interpreted `jmp(a0)` →
  `op_jmp_idx` → `ojmp_hook` → xlat → `entry_d5c4`) → the target is not dormant/broken.
- `ojmp_hook` is STATELESS (interp.pasm:11128 — gate `$071A` + `$40/$42` only); the native prologue sets
  `$40/$42`=target identically; the two prologues are BYTE-IDENTICAL modulo the table-base immediate.

Root cause = a non-obvious native-prologue ↔ dispatched-coroutine-escape runtime interaction (needs
FETCH-STREAM tracing, GPPROF good-vs-broken — not static analysis). **DISCIPLINE: validate every
coroutine-bridge retarget EMPIRICALLY; a derail shows as `trap=False` / a >2min diff hang, NOT a small
byte delta.** See [[coroutine-bridge-retarget-derails]].

**USER DECISION (2026-07-05): ship the 2 clean wins (PR #14), then RE-RANK the levers toward the
playable-game goal.** The re-rank (`pt22-lever-rerank-verdict`) surfaced an honest fork; **the user chose
(a) CONTIGUOUS-COMPILE** the sprite-build coroutine subtree. Approved plan:
`/home/chad/.claude/plans/mutable-coalescing-hippo.md`.

### pt.22 CONTIGUOUS-COMPILE — P1 DONE + PROVEN (commit `daf2e97`)
The d522/d226 derail root cause = the transpiler's `jmp(a0)→jml ojmp_hook` lowering: its runtime
`movea.l (a0),a0` computes a WRONG a0 → `ojmp_hook`/xlat HITs a wrong native escape → coroutine never
returns (`trap=False`). **FIX (P1): resolve the jump table STATICALLY** — replace `movea.l+jml ojmp_hook`
with a `bne`-to-next compare-chain on the runtime index (`memory[a4-2]`), one case per ROM-table entry →
direct `jml.l entry_X` (escaped) / `jml inext` (interpreted); default = the original `movea.l+ojmp_hook`.
`entry_d226` (hand-authored, `escbank.pasm`) = **combat 4B / light 8B GREEN, `trap=True`, −8 interp/tick
both classes, fires 2×, smoke OK.** **KEY codegen requirement: each case MUST set a0 (`$20/$22`)=target
AND 68K PC (`$40/$42`)=target** (the `movea.l+jmp(a0)` side-effects; omitting a0 leaked d6b0's stale
`$D718` into `$0DFE` → a 2-byte divergence IDENTICAL in combat+light, i.e. logic not `$AC` timing). This
PROVES the contiguous mechanism: the derailing dispatchers ARE escapable via static resolution.
**REMAINING (approved plan): P2** mechanize the `jmp(An)` static-switch in `tools/transpile.py` (regen
`$D522`/`$D226`); **P3** scale the whole `ce58` subtree (keep the 11 indirect `$1cXX(a5)` draws dynamic);
**P4** measure the `CYCLES=1` cyc/tick win. Honest ceiling stands (narrows heavy combat, sub-30fps).


---

## §sound-era addendum (2026-07-10/11): loop_hook root-cause + the $0818 clamp

Restoring production cold boot for the sound port's concurrent validation exposed and
closed a loop_hook failure family (full detail: memory `sound-p3-progress`; commits on
`sound-p3`):

- **`.org` overlap** — the lh flow chain (`.org $F442`) grew past `$F601` and the later
  `.org $F602` gm_verify section silently assembled over it (Poppy: last org wins per
  byte). lh_3fea lost its `sec/rts` (fall-through → carry-clear → stale-opcode re-execute
  → the boot RAM-test "failure"); lh_adbe + gm_memclr were buried whole (dispatch jmps →
  mid-gm_verify garbage). Bodies now in escbank5 (`$99:F400/F450/F4A0` + gm_memset via a
  `$92:FFC0` tramp); gm_memclr rehomed at the `$F602` section; `build_interp_rom.py`
  asserts the slack seams. The same overgrowth had covered the `$F600` TESTFLAG.
- **Generic matchers made gameplay-sound** — gm_verify now ACTUALLY verifies (mismatch →
  no-fire → the interp takes the genuine early/error path; the old assume-match collapse
  corrupted compare/search loops); all collapses set exit CCR (the dbra-fallthrough
  stale-flags class; cells `$60/$6E/$70/$72/$A2`, nonzero=set) and guard `count==0`.
- **`$0818` idle-collapse** — "fire the IRQ now" (`$AC=1`) deterministically corrupted a
  coroutine context ~24 game-seconds into gameplay (flight-recorder signature: healthy
  `$0532/$0796` cascade dispatching to `$080000` = 68K ROM end). A runtime-pokeable lab
  (arm redirected to an IRAM handler) swept the boundary: spacing ≤ `$0800` fails,
  `$2000` is stable. Shipped as a clamp (`$AC` lowered to `$2000` at the spin, NEVER
  raised — an unconditional store refills faster than iloop drains and starves the IRQ).
  ~18x game speed retained; soaked through the fatal event repeatedly.
- **Arming** — nothing arms at reset (the boot self-test must run pure); `snd_vframe`
  arms lh + all escapes when the 68K sound-ring pointer signature (`$00F01C2x`) appears.
- **Diagnosis toolkit** (no MAME lockstep needed; first-reach tools next time): the
  interp's always-on 68K PC ring (IRAM `$0400-$05FF`, ptr `$48`, last 128 PCs) + the
  `$0710/$0716` PC-freeze (`$0712` frozen-marker, `$0714` release, `$0730=$5A5A`
  re-firing mode) + deterministic per-arm poke-bisects on ROM copies.
