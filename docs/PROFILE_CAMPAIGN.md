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
