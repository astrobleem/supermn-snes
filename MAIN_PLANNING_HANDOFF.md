# MAIN_PLANNING_HANDOFF.md

Last updated: 2026-07-01 (pt.4). **Read this first** in a fresh session, then act. It captures the
current state, the reliable mental model, the strategic reality (read §0 before deciding what to do),
the tooling, the validated escape recipes, and the prioritized next steps.

> ## ✅ Phase-2 Campaign 1 (scheduler SWITCH-IN) — COMPLETE, SHIPPED `2e39b98` (2026-07-01 pt.5)
> **`entry_swin` is deployed & fully validated** (escbank `.org $FB00` + `swo_tramp` $0796 arm;
> gate `$073C==$A55A`, counter `$40:7FE2`). All gates GREEN: gate-off arm bit-identical (instr=4666
> exact); single-tick vs MAME GREEN ×3 triples; 20-tick SP-aware self-diff **0 LIVE diffs** ×3; the
> bit27 wake-up path closed synthetically (`tools/synth_swin_b27.py`, 0 wram+regfile diffs);
> composition CHOKE+SWIN GREEN (heavy tick 12.78M → **9.87M cyc**). See the plan file's
> "CAMPAIGN COMPLETE" section for the full record.
> **MODEL CORRECTION (inherit this):** the "~19–28 restores/tick" was a **2× sched_trace window
> artifact** (its $3A92 re-fetch trap never fires → the stream caps at 0x7000 ≈ 2 ticks; the
> `$070E/$0712/$0714 ×2` markers are the tell). TRUE switch-ins/tick: **11 moderate / 4 heavy /
> 1 quiet** (commit-counter ground truth; coverage 100%). Measured saving: **~0.5M cyc/tick
> (~6%) moderate**, less on heavy/quiet — half the plan's estimate, real and shipped. Any future
> sched_trace-derived per-tick number must be ÷2 (or re-measured with commit counters).
> **NEXT:** pick Campaign 2 by the same measured-cost gate — candidates per the plan's "Framing":
> (a) render-burst chokepoint allowlist extension (heavy ticks: ce4+13be already reclaim 24%),
> (b) task-body long tail, (c) codegen efficiency ([[workram-lever-bounded]] bounds it). Use commit
> counters, not sched_trace windows, for the gate.

> ## ✅ Phase-2 Campaign 2 (heavy-tick background loops) — COMPLETE, SHIPPED `5aea367` (2026-07-01 pt.6)
> **Gate:** one-tick ALLSTREAM profile (lockstep_trap `GPPROF=1 ALLSTREAM=1 EXACT=…`, everything
> armed — the dead-$0762/ilog GPPROF replaced by the live $0718 dbg_fetch stream) found **62% of the
> heavy tick's remaining interp = two loops**: the `$0008FA` block-copy (jsr-reached, never escaped)
> and the `$0FB8` word-fill loop at **`$0FD2` — a NEW REACH CLASS: the frame IRQ slices long
> background fills; the ISR-exit rte resumes at a MID-LOOP PC** no jsr/jmp/rte table can know. Only
> the fetch-chokepoint catches it. Shipped `entry_8fat` + `entry_fd2t` (--table + hand CCR at the
> dbra-fallthrough exit edges — **transpiler gap found:** `emit_ccr_native` covers Bcc-to-exit only;
> proper fix TODO) via 2 choke_tramp arms (ate 10 padding nops, 42B intact, zero-shift).
> **Validated:** all-off arm bit-identical; 20-tick self-diff 0 LIVE ×3 triples; MAME single-tick
> GREEN ×3 full-on; ESC=1 smoke unchanged. **Measured (full-on vs all-off): heavy 12.3M → 6.35M
> cyc (−48%, ~70× → ~35× budget; instr 8010→2939), moderate 8.7M → 7.47M (−14%), quiet ≈ noise.**
> fd2 also collapses FRESH interpreted fills at ESC=0 (chokepoint hits loop-iteration 1).
> **NEXT (Campaign 3 candidates, from the same profiles):** moderate-tick remainder — the
> $01C9xx/$01E7xx/$023-24xxx background clusters + the scheduler select block ($0740 region,
> 121 instr/tick moderate = extend lh_sched through $075C-$0778 into entry_swin); heavy remainder —
> the $C8C0-$CAFF helper cluster (~300 instr). Re-run the ALLSTREAM gate first; watch for more
> IRQ-slice resume-class PCs (check mid-loop PCs of any hot dbra loop).

> ## ✅ Phase-2 Campaign 3 (HUD decimal formatter) — COMPLETE, SHIPPED `11078ba` (2026-07-01 pt.7)
> **Gate** (re-profiled current build, ESC=1 all-armed): the `$C8C0-$CAFF` HUD/score cluster is the
> heavy tick's largest remaining interp region (~300 instr); `$00C9A6` (number→ASCII decimal) is its
> hottest leaf (~130 instr). Shipped **`entry_c9a6`** — reached `jsr.l` + `bsr`($C90C/$C960) → wired
> into BOTH jah2 chains (`jah2_ext` + `jah2_ext_bsr`) with a cross-bank `jml` to a `$94` body
> (default convention, proven by `entry_8c2`; counter `$40:7FE8`; normally-on validation toggle
> `$073E`). **Cost (ESC=1 single-tick heavy): 3.14M → 2.80M cyc (−337K/3 fires; instr 660→514).**
> Fires only when the HUD redraws (heavy 3×, all bsr; moderate/quiet 0×).
> **⚠ Found TWO GENERAL transpiler bugs** (memory [[transpiler-32bit-flag-bug]]): `emit_signed_cmp`
> and `tst` use the `.w`-only `ea_load_A`, so **all `.l` cmp/cmpi/cmpa/tst compare only the LOW
> word.** Bit c9a6 as `cmpi.l #$1869F` (clamp misfire → "99999") and `tst.l d0` (digit-loop exit one
> early). Hand-fixed both in the body (like the Campaign-2 dbra-CCR gap); **proper transpiler fix is
> TODO and matters for the Gigandes port.** Validated: all-off regression unshifted; ESC=1 c9a6-ON
> vs-MAME GREEN on heavy (BOTH interpreted and native arms match the MAME oracle).
> **NEXT (Campaign 4):** re-run the ALLSTREAM gate; remaining heavy clusters are the `$C8E0/$C958`
> HUD-draw parents (bridge c9a6 — now escaped — + the `jsr(a0)` blitters via `$1c9e/$1cae(a5)`) and
> the `$044x`/`$0572x`/`$072-73xx` regions; moderate is scheduler-select + `$01C9/$01E7/$023-24xxx`.
> **Strategic:** fixing the transpiler 32-bit-flag bug is a high-value cross-cutting task (unblocks
> clean `--table`/`--bank2` escapes of any arithmetic-heavy fn + Gigandes) — consider it before/【as】
> Campaign 4.

> ## ✅ Transpiler 32-bit-flag bug FIXED PROPERLY — `97d5049` (2026-07-01 pt.8)
> The general fix for the Campaign-3 finding. `emit_signed_cmp`/`tst`/`sub.l Dn` did a single 16-bit
> `sbc`/load for ALL sizes (`ea_load_A` is `.w`-only), so every `.l` `cmp/cmpi/cmpa/tst` compared only
> the low word. Now: two chained `sbc` (N/V/C 32-bit-valid) + saved low diff; new `_branch32` in
> `emit_branch` reconstructs the full 32-bit Z and handles every consuming branch
> (beq/bne/blt/bge/ble/bgt/bcc/bcs/bhi/bls/bmi/bpl for `signed32`; the tst subset for `tst32`).
> Memory-operand `.l` compares read both words via `load_long_to`; a `.l` cmp branching to a fn-exit
> epilogue is explicitly Unsupported (32-bit CCR-at-exit not modeled; doesn't occur).
> **Validated:** `tools/val_branch32.py` (new; executes the ACTUAL emitted asm vs true 68K 32-bit
> semantics over edge operands) → **5460 cases, 0 failures**; CE4/13BE/C9F8/1008 byte-identical
> old-vs-new (no 16-bit regression); all 19 known escapes transpile clean; **entry_c9a6 REGENERATED**
> from the fixed transpiler (hand-fixes removed) → ESC=1 GREEN, ESC=0 baselines unshifted.
> **Deployed-drift note:** C172 + D718 carry the OLD 16-bit `.l` zero-tests (correct-by-luck on their
> triples; also older mem-codegen) → they heal on next natural re-transpile (regen isn't a clean swap;
> needs each escape's gate re-validated). See memory [[transpiler-32bit-flag-bug]].

> ## ⏸ Campaign 4 — GATE DONE, hit the bank-$00 wall (2026-07-01 pt.9); STRATEGIC FORK, nothing shipped
> Re-profiled the current build (ALLSTREAM, ESC=1 all-armed). **Remaining interp, ranked:**
> - **Scheduler SELECT `$075C-$0778` = the biggest lever: 121/tick moderate (~10% of the tick), 45/tick
>   heavy.** 11 instr × ~11 task-selects; it's the descriptor-setup+readiness `lh_sched` hands off at
>   `$075C` and `entry_swin` picks up at `$0796`. Pure mechanical (low risk), composes with entry_swin,
>   and is **cleanly measurable** (loop_hook-reached → ESC=0 lockstep_choke, dedicated gate). BUT it's
>   **BANK-$00-BLOCKED for a *gated* trampoline:** catching `$075C`→escbank needs a bank-$00 gate check
>   (else lh_sched always cross-bank-round-trips → regresses the off-by-default state). `swo_tramp`
>   ($FFCA, 21/22B) + `lhs_found` (5B, →$FA00) + `lh_sched_pre` are all packed; no zero-shift room for
>   the gate. The ungated 5→5B `lhs_found`→`jml lhs_sel` is zero-shift but regresses off-default
>   (round-trip w/ no benefit). **This is the recurring bank-$00 wall (task #10 / loop_hook-can't-grow).**
> - **HUD parents `$C8E0/$C958/$C9F8/$CA9A` (heavy ~152): bridge-dominated → LOW-VALUE.** Built + tested
>   `entry_c8e0` + a `--table` `entry_c9a6t` bridge-callee (so `bsr c9a6` stays native, no C3 regress).
>   **entry_c8e0 is BIT-EXACT** and the bridge-callee works — BUT it's mostly arg-marshalling + 2
>   `jsr(a0)` blitter bridges + the c9a6 bridge (exactly [[cycle-budget-realtime-gap]]'s low-value
>   class), and its cyc win is **below the ESC=1 measurement noise** (jah2/`$071A` escapes shift the
>   `$AC`-paced `$0708`-trap window — can't isolate a clean delta like the ESC=0-gated chokepoint/swin).
>   **Reverted** (working tree clean at `4ce26af`) — not shipping an unmeasurable, bridge-dominated escape.
> - **Moderate state clusters `$01C9xx/$01E7xx` (~165) + `$00CBxx` (~109):** jmp-state/coroutine handlers
>   (dispatched via `$CEB6`: `lea $cf8c(pc),a0; jmp(a0)`). Escbank-deployable via the xlat table (no
>   bank-$00 fight) BUT need per-entry-PC identification + convention work (the c172/d5c4 pattern, mid-flow
>   entries, bsr-subroutine bridges). Research-heavy, uncertain per-entry value.
>
> **STRATEGIC READ:** the clean single-function escapes are exhausted; every remaining big lever is either
> bank-$00-blocked (the select, #1) or bridge-dominated (HUD) or multi-entry-research (state clusters).
> **The unblocking work is bank-$00 space recovery** (task #10): a compaction/relocation pass (e.g. move
> the `$F700` RESP1 buffer or replace a packed cmp-chain with a jump table) to free room for a *gated*
> `$075C` trampoline — that ships the select (121/tick) AND unblocks future loop_hook-class escapes. This
> is the highest-ROI next step, but it's infrastructure, not a drop-in escape. Tools/counters for the
> select A/B are ready (lockstep_choke gates + `$40:7FEx` counter convention).

Goal: ~99% native per-frame coverage so the SA-1 runs Superman at realtime (playable).
Repo: branch `boot-scheduler-progress`, **committed + pushed at `a013dee`** (Phase-1 chokepoint
generalization: `entry_13bet` bit-exact, `$1400` dropped, transpiler CCR fix, self-diff tools). Working
tree clean at that commit. `entry_swo` (scheduler switch-**OUT**) is **deployed & GREEN** (bit-exact;
measurement showed it escaped the *rare* half — 1×/tick — which is why it read as "not a cycle win"; the
frequent half, switch-**IN** at ~19–28×/tick, is the open target). AOT table: **16 escapes** (15 prior +
`entry_13bet`). Build: `bash tools/build_interp.sh` → `build/interp.sfc`.

> Older planning text in STATUS.md / ROADMAP.md predates the strategic picture below. Trust THIS doc.

> **UPDATE 2026-07-01 — the rts-class dispatch blocker is RESOLVED (corrects §1 below).** A bank-$00
> `jsr choke_tramp` FETCH-CHOKEPOINT at the interpreter's `lh_off` (runs per genuinely-interpreted
> fetch) routes the about-to-decode 68K PC through the AOT table, so rts/branch-reached hot handlers
> dispatch natively **regardless of how they're reached**. `$0CE4` (entry_ce4t) — the hottest cluster,
> previously uncatchable by any hook — now dispatches natively **bit-exact** (all 6 ce4 triples +
> 20-tick self-diff; ~277 interp-68K-instr/call eliminated, ~285K SA-1 cyc/call). GOTCHA: an every-
> fetch cross-bank `jml $94…jml $00` round-trip is FATAL (silently breaks GAME_TICK — `jsr $3A92`
> lands on an rts, the tick is skipped); the bank-$00 `jsr`/`rts` trampoline (cross to $94 only on the
> rare HIT) is the fix. This work ALSO exposed + fixed a **transpiler D1 gap**: transpiled escapes
> lowered branches to native flags but never wrote the 68K CCR memory ($60/$6E/$70/$72/$A2) that an
> interp-CALLER reads after the escape's `rts` → stale flags (the trip1000 `$104F` divergence).
> `transpile.py` now materializes the CCR at branch-to-exit edges with provenance (`emit_ccr_native` +
> `exit_addrs`); entry_ce4t was regenerated FROM the fixed transpiler (not hand-patched), win intact.
> rts-class/xlat rollout **complete** (ce4t was the only exit-edge case; 295a/29b6 are straight-line).
> Existing escapes carry transpiler drift → they heal on their NEXT natural re-transpile (transpiler
> now correct); no risky mass-force-regen. STRATEGIC (§0) UNCHANGED: still 24× over budget, codegen is
> the wall — the chokepoint is a *dispatch enabler + correctness fix*, not the 24×-closer. Tools:
> `lockstep_choke.py` / `multitick_choke.py` (self-differential), `reg_probe.py` / `find_writer.py`
> (root-cause). Memories [[fetch-chokepoint-rts-escape]] (breakthrough + fix + rollout),
> [[rts-class-dispatch-nonfunctional]] (partially superseded). Build GREEN (working tree, uncommitted).

> **UPDATE 2026-07-01 (pt.2) — chokepoint GENERALIZED to $13BE + the measurement reckoning.** The
> chokepoint now dispatches a 2nd handler ($0013BE) bit-exact (2-way allowlist; entry_13bet fresh
> `--table`). Correctness GREEN: 6-triple SP-aware self-diff, 0 LIVE diffs (sole diff $15F9 is DEAD
> STACK below SP — link/trap pushes, never read live). **$001400 DROPPED: it is an INTERNAL label of
> $13BE** (the profiler's "$13BE 38 + $1400 30/fr" is one fn in two histogram buckets), so entry_13bet
> already covers it. **The strategic payoff is a MEASURED number, not the coverage:** trajectory-
> controlled single-tick (the ONLY valid escape-delta metric — free-run cyc/tick is corrupted by
> spin-wait trajectory divergence) gives **1832 cyc/interp-instr** (real interp rate) and **~1151 cyc
> net saved per interp-instr escaped ⇒ escaping keeps ~63% of interp cost**. That is §0's "codegen is
> the wall" thesis, now confirmed with a real number instead of a 9× proxy spread. **Phase-2 BLOCKER
> (do not skip):** the triples fire ce4/13be only ~2/tick, not the "66/frame" the thesis cites, and
> measured 8.55M cyc/GAME_TICK is ~2× the canonical 4.34M "24×" figure → **the 24× number's provenance
> is now suspect, and a representative reconciled budget is BLOCKED on an ACTIVE-GAMEPLAY triple**
> ([[new-freeze-camera-gating]]). Getting that triple is the explicit precondition for committing a
> multi-session codegen rewrite; do not manufacture a budget from these low-activity triples. Tool
> fixes: `multitick_choke.py` SP-aware, `cycle_rate_gp.py` CHOKE+PORT env. Details:
> [[fetch-chokepoint-rts-escape]] + `/tmp/supermn-scratch/chokegen/RESULTS.md`.

---

## 0. STRATEGIC REALITY — read before choosing what to do (the most important section)

We have a precise SA-1 cycle meter now (`get_cpu_state('Sa1')['cycleCount']`). It reframed everything:

- 60fps budget = **~179,000 SA-1 cyc/frame**. One GAME_TICK must fit one frame.
- Current state (ce4trip64, all escapes on) = **~4.34M cyc/tick = 24× over budget.**
- **Escaping MORE handlers alone plateaus at ~5–10× over budget — coverage is NOT the lever.**
  ~86% of every native escape's cycles is OVERHEAD (dispatch + bridge round-trips + generic-helper
  codegen), only ~14% is real work. Native escapes amortize to ~429 cyc/68K-instr, only ~4.1× faster
  than interpretation.
- **The wall is native-escape codegen, not the interpreter and not the number of handlers escaped.**
  Realtime needs native escapes **~5.7× cheaper**, via: (a) inline work-RAM EA access instead of the
  generic `rdw_ea_l`/`writeword_l`/`readbyte` helpers (EA-specialization — STARTED, see §6.A), (b)
  killing bridge round-trips by escaping the CALLEES so they run inline (PROVEN: c172 = 4.85× by
  escaping its $295A/$29B6 renderers), (c) bigger amortizing escapes.

**Consequence for planning:** the per-escape codegen win (~2× each, measured) must COMPOUND. A single
new handler escape — even the whole scheduler (~30% of the tick) — moves 24× → ~17×. The decisive
work is the transpiler codegen rewrite. See memory [[cycle-budget-realtime-gap]] (the authoritative
analysis) before committing a session to "escape more functions."

---

## 1. The reliable mental model (dispatch families — verified with SA-1 exec-hooks)

The interpreter (`src/interp.pasm`, 65816 on SA-1) runs Superman 68K code. Per GAME_TICK (`$3A92`)
it executes **~1700–1900 genuinely-interpreted 68K instructions/tick**.

**Dispatch families that ACTUALLY FIRE in gameplay (verified):**
- **jah2 (jsr-class):** `jsr.l`/`jsr (An)`/`bsr` → `jsrabs_hook` cmp-chain. Covers clean leaves.
- **jmp-state (AOT xlat table):** `jmp (a0)` → `op_jmp_idx` → `ojmp_hook` ($00:D1B3) →
  `xlat_dispatch` ($94:F900). PC→native table from `tools/gen_xlat_table.py`. Firing: d0d0, d5c4, etc.
- **coroutine (rte-resume):** `rte` → `ors_rte` ($00:D184) → table. c172 ships this way.
- **loop_hook (per-fetch):** gated by `$072E` (set in gameplay), fires on every fetched `$40`.
  Collapses the `$0818` idle spin AND `lh_sched` (the `$074C` scheduler scan). This is how you escape
  bra/beq-reached hot PCs that the jsr/jmp/rte families can't catch.

- **fetch-chokepoint (per-fetch, NEW 2026-07-01):** bank-$00 `jsr choke_tramp` at `lh_off` routes the
  about-to-decode PC through the AOT table (HIT → dispatch, MISS → `rts` back to decode). Catches
  rts/branch-reached handlers the jsr/jmp/rte families CAN'T. `$0CE4` (entry_ce4t) ships this way,
  bit-exact. Gated by `$073A` (PoC). This is the fix for the class the next bullet used to call dead.

**~~PROVEN NOT to work~~ RESOLVED 2026-07-01 (was: rts-class table dispatch fires 0×).** `$CE4`/`$13BE`
handlers ARE reached as rts returns inside the scheduler's `rte→task→rts→next` chain, which bypasses
`op_rts_norm→ojmp_hook→xlat` — so the *table lookup on rts* never fires. The FIX is upstream of the
reach question entirely: the **fetch-chokepoint** above intercepts at instruction FETCH, so `$0CE4`
dispatches regardless of how it was reached (proven bit-exact). Don't route rts-reached leaves through
`op_rts`→xlat (that's the dead path); route them through the chokepoint. (memories
[[fetch-chokepoint-rts-escape]], [[rts-class-dispatch-nonfunctional]] — the latter partially superseded.)

---

## 2. THE BIGGEST LEVER FOUND THIS SESSION — the coroutine scheduler is ~30% of the tick

`tools/sched_trace.py` (ground-truth: inject ce4trip64, stream every interpreted PC in `$0500-$07FF`,
disassemble the exact executed PCs) settled what the scheduler actually is:

It is a **cooperative coroutine CONTEXT-SWITCHER**, and its cost is pure mechanical plumbing — NOT
task bodies, NOT bridges. Per tick: ~22 switch-INs + ~21 switch-OUTs ≈ **~740 genuinely-interpreted
instrs ≈ ~1.29M SA-1 cyc ≈ ~30% of the tick.** The exact code (capstone of the executed PCs):

```
SWITCH-IN  (×22/tick, ALL take this path; the $077A "dispatch" fall-through fires 0×):
  $074C-$0772  select task: a3=a5+$4E+idx*4 (descriptor), $4a(a5)=a3, d2=(a3), enable recheck
  $0774 btst #$1e,d2 / $0778 bne $796     bit30 = task READY
  $079E movea.l (a4),a7                    load the task's saved SP   (context switch IN)
  $07A4 cmpa.l $4(a0,d1),a7                stack-bounds check
  $07E4 movem.l (a7)+,d0-d7/a0-a6          restore 15 task registers from its stack
  $07E8 rte                                pop PC+SR -> RESUME the task body
SWITCH-OUT ($0532 yield trap, ×21/tick) is the exact mirror:
  $0532 ori #$700,sr / $0536 movem.l d0-a6,-(a7) (save) / $053E save SP / mark descriptor / bra $74c
```

`lh_sched` (already shipped, last session) collapses only the `$074C` disabled-task scan. The
**switch-in ($075C-$07E8) + switch-out ($0532-$0550) machinery is the residual ~30% and is the
single biggest collapsible lever** — and it's mechanical (SP/reg save-restore + rte), so a faithful
native reimplementation has low bit-exactness risk. Both ends are loop_hook-catchable.
(memory [[scheduler-context-switch-lever]].)

---

## 3. STATUS of the scheduler switch-OUT escape — PARKED (body proven, integration unpinned)

This session built a native switch-OUT (`entry_swo`, escbank slot 19, bank-$00 trampoline on `$0532`
in the $FFCA gap, returns `jml lh_sched`). Outcome:

- **The body is PROVEN bit-exact** vs the real `$0532-$0550` — `tools/yield_multi.py`: 8/8 real MAME
  yields, my-asm == 68K-semantics byte-for-byte (a7 $F00200-$F015F8, varied resume-PCs).
- **But ESC=0 lockstep = DIFF~44** (baseline GREEN) — a real but unpinned **integration** divergence
  (enable mask $F00001/2 + sprite coords ±1 = ONE task dispatched differently). RULED OUT: body
  (bit-exact), CCR flags (added N=1/Z=0/V=0/C=0 → 46→47, no help), `$AC` pacing (flat 44-46 across a
  sweep). The escape was **reverted to GREEN**; the working code + notes are in
  `docs/handoff/scheduler_switchout_wip.md`.

**Why it isn't cracked yet — and the dead end we closed:** debugging needs the interp state right
after ONE switch-out, escape-vs-committed. Every INJECTION-based path failed:
- `capture_at_pc` (MAME) has prefetch-skewed SP for stack-frame handlers like `$0532` (memory
  [[mame-capture-precision]]).
- `tools/yield_faithful.py` PHASE A captures a clean S0 from the **interp's own** run (no skew) — but
  PHASE B proves that **re-injecting a mid-tick interp state does NOT reproduce execution** (committed
  build → corrupt $5E:0036; escape → stuck $0532). Mid-tick state isn't captured by IRAM+workRAM
  alone: the SA-1 native stack, the `$41` video shadow, `$0700+` control, and SA-1 HW/cycle state all
  matter. **Single-yield diff via injection is a DEAD END for this handler.**

**The one clean route left to crack it:** INTERP-SIDE INSTRUMENTATION — a debug build whose `$0710`
freeze RE-FIRES (single-step-on-release, a small ZERO-SHIFT `df_gap` change so it doesn't `stz $0710`
when a debug flag is set, plus a one-instruction-advance on release). Then diff escape-vs-committed
**in place** across consecutive `$0532` of ONE faithful tick — no injection, no skew, no df_gap-clear
trap. Invasive (interp surgery) but the only thing that escapes all three blockers at once.

**Recommendation:** before sinking a session into cracking this, weigh §0 — even fully working, the
switch-out is ~5% of the tick, and the switch-IN (~the other ~half of the ~30%) needs the same fight.
The body is banked as proven-correct. Either (a) build the re-firing-freeze debug build and finish
it, or (b) park it and spend the session on the codegen lever (§0). My read: (b) is higher ROI.

Tools built this session (all committed, reusable): `sched_trace.py` (scheduler ground truth),
`yield_diff.py`/`yield_sim.py`/`yield_multi.py` (MAME ground-truth + body bit-exactness proof),
`yield_diff2.py` (full-interp-state diff), `yield_faithful.py` (faithful interp-side capture).

---

## 4. Tooling

**Cycle meter & per-escape harnesses (the §0 work uses these):**
- `tools/lockstep_trap.py … 2F60 <ESC>` with `CYCLES=1 B1PC=0818` → active-compute SA-1 cyc/tick.
  ~16% (~700K) overshoot noise from runf chunking; magnitude robust. load_state TRANSPLANTS
  cycleCount → measure deltas WITHIN one continuous run only.
- `tools/cycle_isolate.py` — PRECISE per-escape cyc (driver in work RAM + `$0738=$A5A5` interp
  redirect; 7/8 within 5%). `DRIVER_JMP` mode for jmp-state/coroutine escapes.
- `tools/cycle_live.py` — LIVE-CONTEXT per-escape cyc (inject full triple, run until the escape
  naturally dispatches via SA-1 entry hook). For state-dependent escapes.
- `tools/cycle_rate.py` / `cycle_rate_gp.py` / `probe_*` — interp & native cyc/instr decomposition.

**Lockstep / profiling (`tools/lockstep_trap.py`, env-driven):** `HOOKTEST=<hex,…>` (TRUE fire count
via SA-1 exec-hooks — the reliable test; bank-$00 addrs only, NOT bank-$92/$94), `GPPROF=1`
(genuinely-interpreted stream), `PRED`/`STREAMWIN`/`ENTRYCLASS` (reach classification),
`B1PC`+`REGDUMP`, `FULLDIFF`. Baseline: ce4trip64 ESC=1 = DIFF=48 (pre-existing $0708-trap/$AC
artifact), ESC=0 = GREEN. Triples in `/tmp/supermn-scratch/`: ce4trip64, trip2500/4000/5000.

**Single-yield differential (§3):** `sched_trace.py`, `yield_diff.py` (+`yield_sim`/`yield_multi`),
`yield_diff2.py`, `yield_faithful.py`. Environment gotchas now in memory: **never `pkill -f mame`**
(matches the shell's own "mame-trace" cmdline → silent self-kill — use `pkill -x mame`); MAME
`HERE=Path(..).resolve()` or rompath doubles → code 2; MAME needs `SDL_VIDEODRIVER=dummy`; MAME runs
need `dangerouslyDisableSandbox` + long Bash timeouts.

---

## 5. VALIDATED escape recipes (these WORK — shipped this way)

**jmp-state / coroutine class:** `transpile.py <pc> --bank2 --coroutine` → splice into
`src/escbank2.pasm` → add PC to `JMP_STATE_PCS`/`CORO_PCS` in `gen_xlat_table.py` → build → gate:
HOOKTEST (FIRES) + FULLDIFF (DIFF=48, zero added) + ESC=0 GREEN. Commit only if FIRES & zero-added &
GREEN.

**Bridge-callee escape (the §0 lever — PROVEN 4.85×):** deploy a hot bridge callee as a `--table`
variant + add to `TABLE_PCS`; every bank-2 escape that bridges to it then dispatches it natively
(routes the jsr(a0) indirect bridge through `ojmp_hook`). This is how c172 went 463K→95K cyc.

**loop_hook / bra-reached class (hand-written, like lh_sched):** add a cmp/beq arm in `loop_hook`'s
lh_gen chain (or a zero-shift trampoline in a bank-$00 gap), body in a bank-$00 gap (binding
constraint: biggest gaps ~86B@$F9AA, 46B@$D1BF, 22B@$FFCA; loop_hook itself can't grow — packed vs
.org $F602) OR an escbank body reached by `jml $928000+slot*3`. Validate ESC=0 GREEN (runs ungated).

**Escbank deploy:** escbank ($92, file $290000) + escbank2 ($94, file $2A0000). Add a jmptab slot
(`jmp entry_X`), the body, and a bank-$00 dispatcher. `gen_escbank_syms.py` NEEDED[] lists bank-$00
symbols an escape may reference. Bank-$00 code changes must be ZERO-SHIFT (else regen b0_native via
`tools/dump_b0_native.py`).

---

## 6. Prioritized next steps (pick ONE strategic track)

**TRACK A — the codegen lever (HIGHEST ROI per §0).** Continue the transpiler EA-specialization
(commit 38d5388 started it: `is_workram(an)` + `--workram` → inline `lda $400000,x` instead of generic
helpers). Pick a read+work-RAM-write escape, redeploy through `--workram`, measure with
`cycle_isolate.py` (expect ~2×). Then escape more bridge CALLEES (c172-style). Compound the 2× wins.
This is the only track that closes the 24× realtime gap. (memory [[cycle-budget-realtime-gap]].)

**TRACK B — finish the scheduler switch-OUT** (§3). Build the re-firing-freeze debug build, diff
escape-vs-committed in place, pin the integration bug, ship switch-OUT, then do switch-IN the same way.
Biggest single coverage win (~30%) but doesn't close the gap alone, and the body is already banked.

**TRACK C — more individual escapes** (jmp-state/coroutine/bridge). Lowest strategic value per §0 but
lowest risk; good if you want incremental DIFF/coverage progress. Next coroutine bodies: `$46DE`,
`$7828`, `$11752`, the `$00C1xx` cluster (rte-reached; STEP-A $AC-charge recipe in git history).

**Cross-cutting tasks (open):** #8 realtime soak harness (free-run + fps + divergence detection),
#9 cycle-weighted reach-classified escape ranker (pick targets by CYCLES not instr-count),
#10 bank-$00 trampoline so loop_hook bodies can live in escbank2, #16 scheduler switch-IN. (See §8.)

---

## 7. Methodology rules & dead ends (hard-won — don't relearn these)
- Measure SA-1 execution with **HOOKTEST exec-hooks**, never `$07xx` memory counters (game overwrites
  them — read "63524×" when truth was 73×). SA-1 hooks fire on bank-$00 addrs only AND only while the
  interp is RUNNING (idle b0_native/jh_spin doesn't fetch → no fire).
- **Pick targets by CYCLES, not instruction count** (§0): native overhead dominates; a high-instr
  handler can be cheaper to leave interpreted than a bridged escape.
- Don't grind rts-reached leaves into the table (fire 0×).
- Don't inject a MID-TICK interp state and expect faithful execution (§3 dead end) — SA-1 stack/$41
  shadow/$0700+/HW state aren't reproduced.
- `capture_at_pc` SP is prefetch-skewed for stack-frame handlers; the inputs (a5, descriptor, slot)
  are reliable but SP/[SP] aren't.
- Bank-$00 is the binding space constraint; new bank-$00 code must be zero-shift or regen b0_native.
- The 48-byte ce4trip64 ESC=1 baseline DIFF is a $0708-trap/$AC sub-realtime artifact, not a bug.

---

## 8. Open task ledger (status at session end)

| # | task | status / note |
|---|------|---------------|
| #5 | Cycle meter SA-1 cyc/tick | **DONE** — `lockstep_trap CYCLES=1 B1PC=0818`; the §0 instrument. |
| #7 | loop_hook per-fetch tax | **DONE** — below single-tick noise; folded into the ~1880 interp cyc. |
| #8 | Realtime soak harness | **OPEN** — free-run + fps + divergence/crash detect. Not started. Useful once an escape set is realtime-plausible; low priority now (we're 24× off). |
| #9 | Cycle-weighted reach-classified ranker | **OPEN** — pick targets by CYCLES not instr-count. Valuable for TRACK A/C target selection; not started. |
| #10 | Bank-$00 trampoline → escbank2 loop_hook bodies | **OPEN** — partially exercised this session (the $0532 trampoline → escbank slot 19 pattern WORKS and is documented in §5/handoff). Generalizing it into the toolchain is unfinished. |
| #11 | Bridge round-trip cost | **DONE** — sized the callee-inlining win; led to the c172 4.85×. |
| #12 | Raw native rate (bridgeless) | **DONE** — ~665 cyc/move.l = helper-bound, no cheap floor (memory). |
| #13 | Transpiler EA-specialization | **DONE (v1)** — `--workram` inline path built (commit 38d5388). TRACK A continues it (more escapes, measure 2×). |
| #14 | Interp redirect hook | **DONE** — `$0738=$A5A5` df_gap redirect; unblocked cycle_isolate. |
| #15 | Native switch-OUT escape ($0532) | **PARKED** (§3) — body PROVEN bit-exact; integration divergence unpinned; reverted to GREEN. Needs the re-firing-freeze debug build (TRACK B). |
| #16 | Native switch-IN escape ($075C-$07E8) | **OPEN** — the bigger half of the ~30% scheduler lever; do it after switch-OUT is cracked, same method. |
| #17 | Single-yield differential harness | **DONE** — yield_diff/sim/multi/diff2/faithful built. Proved injection is a dead end; PHASE-A faithful capture works. |

(Deleted earlier: #6 "$CE4 on loop_hook" — superseded by the rts-class-fires-0× finding.)

---

## 9. Session deltas (2026-06-30 pt.3 → `58b20cb`)
- **FOUND the biggest lever:** scheduler = ~30% of the tick, pure coroutine context-switch plumbing
  (§2). Built `sched_trace.py`. Memory [[scheduler-context-switch-lever]].
- **Built + PARKED the switch-OUT escape** (§3): body PROVEN bit-exact (yield_multi 8/8); ESC=0
  DIFF~44 unpinned integration divergence (not body/flags/pacing). Reverted to GREEN.
- **Built the single-yield differential toolchain:** yield_diff/sim/multi (commit 464f99c),
  yield_diff2 (5047d29), yield_faithful (58b20cb). PROVED injection-based single-yield diff is a dead
  end for mid-tick handlers; the route is interp-side re-firing-freeze instrumentation.
- Repo GREEN, escape not in the build; switch-OUT code preserved in `docs/handoff/`.

## Prior session deltas (→ `59f4b15` / `507d692`)
- c172 shipped (first coroutine escape, $AC-charge resolved); c172 bridge callees $295A/$29B6 escaped
  → 4.85× (the bridge-callee lever). lh_sched shipped (the $074C scan, -125 interp/tick). entry_d718,
  entry_d3f6 (jmp-state). transpile.py move.l→-(An). Corrected model: rts-class fires 0×, scheduler is
  the bottleneck.
