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

**Then:** 2.2 CBxx+$4A9E per the CP1 re-rank (2.3 trap#5 shells SHIPPED below).

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
