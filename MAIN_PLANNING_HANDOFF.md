# MAIN_PLANNING_HANDOFF.md

> ## R6 PLAYABILITY OVERRIDE (2026-07-22)
>
> The historical R5 task below is complete and superseded for one exact production candidate.
> v105, ROM SHA-256
> `72d925ac1817965f62ebcfdf8cb53a6ebb135423b7b6a97b37990254e46f85b3`, starts from power-on
> with `TESTFLAG=0`, arms production organically, and sustains 1,802 game ticks across 3,603
> emulated SNES video frames: **30.008326 game ticks/s at 357,281.999 mean SA-1 cycles/tick**.
> The same uninterrupted run conserves 1,802 renderer requests / 1,802 unit ACKs / 1,802 true
> draws with zero queue drops, uses the real input path, retains a valid sound ring, and reaches
> tick 2,230 with halt zero and all 16 task stacks above their floors. Fresh MAME gates pass
> optest 160/160 and opsweep 782/782.
>
> Current engineering truth is in `CONFESSION.md`, `RECOVERY.md` R6, `AGENTS.md`, and the
> 2026-07-22 section of `docs/PROFILE_CAMPAIGN.md`. The candidate is playable under the project's
> representative 30 Hz evidence contract, not yet shippable or full-playthrough validated.
> Aligned MAME pixel fidelity, hardware qualification, audio listening, and real SFX remain open.
> Do not transfer the verdict to another ROM hash without rerunning the full cold-boot gate.
>
> ## RECOVERY OVERRIDE (2026-07-12)
>
> **Historical; superseded by R6 above.** Do not start the historical "CURRENT TASK" below.
> Read `CONFESSION.md`, `AGENTS.md`, and
> `RECOVERY.md`. The production cold-boot baseline is complete: 1.3237 game-fps post-arm, about
> 8.10M SA-1 cycles/tick, with a 32/32 real-boundary hook check. The level background also reproduces
> after a long same-boot palette fade. The immediate task is R5: attribute the continuous-run cycle
> cost and require a measured path to the 30 Hz budget before resuming per-function escapes, sound
> polish, or rendering polish. Historical campaign sections remain useful for mechanisms and failed
> approaches, not current priority.

> ## ⭐ CURRENT STATE (2026-07-11): SOUND PORT COMPLETE — see STATUS.md's top banners
> The TAD/YM2610 sound port (the second half of the 2026-07-04 strategic fork) is DONE:
> P1 plumbing → P2 capture+wiring → P3 real audio + per-note polish + the GROUND-TRUTH
> trigger map for all 21 tracks + concurrent live-gameplay validation. Along the way,
> production COLD BOOT was restored (TESTFLAG relocation + build guard) and the whole
> loop_hook failure family was root-caused and fixed (org-overlap relocations, sound
> generic-matcher corrections, the $0818 idle-collapse re-shipped as a $2000 clamp);
> accelerators now self-arm after the boot self-test. Branch `sound-p3` / PR #15.
> Docs: `tools/sound/README.md`, `docs/SOUND_COMMAND_MAP.md`; memory `sound-p3-progress`.
> Remaining sound items (non-blocking): by-ear listening pass, real SFX authoring,
> rights review (tracks 3/8/19 = John Williams theme).
> The pt.22 material below is the PRIOR campaign state, kept for context.

Last updated: 2026-07-06 (**pt.22 P3a DONE**: ceb6 + d6b0 STATIC-RESOLVED via `--jtstatic` — all 4 sprite-build
coroutine leaf dispatchers (ceb6/d6b0 + d226/d522) now dispatch DIRECT, 8 ojmp_hook round-trips/tick eliminated;
GREEN both-class bit-exact, same-bank $92 relocation (ceb6 @ .org $FEB0 tail, d6b0 @ .org $F600 jah2_ext_bsr tail),
smoke OK. **MEASURED (deterministic instr-counts): P3a cycle win is small (~500 cyc/tick, <0.15% budget — the
ojmp_hook round-trip is the CHEAP native→native bridge). P3b sub-handler ceiling directly measured SMALL (~4 interp
PCs/tick of 165); the interp mass is the SCHEDULER ROOT ~42% + the cd1a spine $CD40 x18 (~25 PCs, harder shape).**
USER (2026-07-06) chose: commit P3a + do the 9 sub-handlers (P3b) despite the low ceiling — finish the subtree.
HARNESS: regen /tmp/b0_native.mss via dump_b0_native.py after EVERY rebuild or lockstep gives false trap=False/instr=0.)
**THE STRATEGIC FORK IS
SETTLED (user, 2026-07-04): 30fps retarget (budget 358K/tick, tick = 2 display frames) + the
TAD/YM2610 sound port; realtime-60 abandoned (ISA-floor verdict). Don't re-litigate.**

**pt.21 DONE (render-to-WRAM SHIPPED + VALIDATED, DRAFT PR #13, commits `50dfc62`+`3c79000`):**
relocated the 5A22 render to WRAM `$7F` via a VERBATIM SAME-OFFSET COPY (video.pasm `rc_copy`
mirrors $E9:8000-$8FFF → $7F:8000 at supervisor boot; the $8004 VF_TICK wrapper jml's the $7F
copy) — SIMPLER than the pt.20-plan's `$7E:D000` re-assembly (the render code is bank-relocatable
by construction: jsr/bra K-relative, all data bank-explicit/DBR-relative). Byte-faithful (0-diff
mirror), zero-shift (4 bytes; BOOT_ARM/cv_loop/joy5a22 unmoved), smoke-GREEN, render provably runs
from $7F. **BUT the win is only ~3.4% (~68K/combat-tick), NOT the projected ~27% (~550K)** — the
render is DMA/$7E-write-heavy so its code-fetch (the only WRAM-recoverable share) is a MINOR
Bus-A conflict source. **The render lever is SPENT.** (Memory `render-to-wram-pt21`;
docs/PROFILE_CAMPAIGN.md §pt.21.) HARNESS LESSON (cost the session, don't relearn): the NAT
(dump_b0_native jh_spin transplant) STRANDS the 5A22 at $00:D161, OUT of its $7E:F000 supervisor
poll loop → the render NEVER fires under NAT/injected harnesses (contention_combat + validate_wl_fix
are render-DEAD; set_cpu_state('Snes') won't force it back). This is why pt.20's own migration
"doesn't engage" fresh — those combat contention numbers are NOT reproducible from the NAT.
MEASURE render/5A22 changes on a FRESH boot (`tools/measure_render_wram.py`).

**pt.22 DONE (leaf-handler escape lever EXECUTED, 2026-07-05, PR #14 on branch `pt22-lever-b-handlers`):**
re-profile confirmed the dominant BOTH-class residual = the sprite-build coroutine ($00CE58 + its
jump-table leaf handlers), combat 204 interp fetches/tick, light 133. Escaped the leaf handlers by
retargeting `entry_ce58`'s `brce58_N` call-bridges interpret→native. **Outcome split — the "mechanical
repeat" premise was INVALIDATED:** ✅ `ceb6` (−24 interp/tick) + `d6b0` (−8) SHIPPED bit-exact both-class;
❌ `d522`+`d226` **DERAIL the whole tick** (trap=False, tick never returns, diff hangs — not any static
predicate; see `coroutine-bridge-retarget-derails`), reverted; `cd1a` untested. **RULE BANKED (cost real
time): HOOKTEST escbank bodies at their `$92:xxxx` execution address, calibrate vs `entry_swin @ $92FB00
== 11`, never a bank-$00 control** (`hooktest-escbank-92-addressing`).

**⚠️ CURRENT STATE = LEVER RE-RANK, USER DECISION PENDING (`pt22-lever-rerank-verdict`).** The interp-escape
lever is de-prioritized: the MEASURED economics say interpretation is NOT the wall (~0.42× budget at full
coverage); the wall is dispatch+bridge overhead (~86%). **HONEST CEILING: no lever on the board reaches
true-30fps HEAVY combat** — contiguous compilation (measured 4.85× on LEAF subtrees) narrows the gap but
STALLS at the scheduler root, exactly where the sprite-build coroutine lives, and the d522/d226 derail is
at that same boundary. **USER CHOSE (a) contiguous-compile (2026-07-05); P1 DONE + PROVEN (commit
`daf2e97`, branch `pt22-lever-b-handlers`).** The d522/d226 derail is FIXED via STATIC jump-table
resolution — `cmp` the runtime index (`memory[a4-2]`) against each ROM-table entry → direct `jml.l
entry_X` (escaped) / `jml inext` (interpreted), default = the original `movea.l+ojmp_hook` — instead of
the transpiler's derailing `jmp(a0)→ojmp_hook` lowering. `entry_d226` (hand-authored) is now native +
bit-exact both-class (combat 4B / light 8B GREEN, `trap=True`, −8 interp/tick, fires 2×). **KEY codegen
requirement (learned the hard way): each switch case MUST set a0 (`$20/$22`)=target AND 68K PC
(`$40/$42`)=target** — the `movea.l+jmp(a0)` side-effects the sub-handler depends on; omitting a0 leaks
the prior handler's stale a0 → a 2-byte divergence (identical combat+light = logic, not `$AC` timing).
**✅ P2 DONE + PROVEN (2026-07-06, branch `pt22-lever-b-handlers`):** the static switch is now a transpiler
lowering — `tools/transpile.py --jtstatic=BASE:COUNT` + `gen_jtstatic` (fused 4-instr matcher on the
`lea/adda/movea/jmp(An)` idiom; per-case sets a0+PC=target then jumps direct; default = original
movea+ojmp_hook). Regenerated `$D226` is **INSTRUCTION-IDENTICAL to the P1 hand body (`daf2e97`)**. Two codegen fixes: (1)
**same-bank target MUST use `jmp entry_X`, not `jml.l`** — Poppy resolves a same-FILE `entry_X` to its
file-local `$00` origin so `jml.l` jumps to bank $00 (a DERAIL); cross-bank keeps `jml.l` (24-bit const);
added `escbank_bank_of` (BANK_OF_SYM lookup). (2) the a0+PC per-case set (the P1 lesson). **BOTH d226 AND
d522 ship GREEN (combat 4B / light 8B, both-class).**

**✅ d522 FIXED — the "derail" was ESCBANK $92 SPACE EXHAUSTION, NOT a logic bug (I first WRONGLY deferred it
as a "scheduler-boundary wall"; it is DETERMINISTIC).** `deploy` inserts bodies at `ESCBANK_BODIES_END`, but
the $92 body region already overflows past the `.org $F000` ceiling (entry_d386@$F020, d3b0@$F0FD, d226@$F395
survive only because their reached code fits the pre-`.org` gaps). Adding entry_d522 pushed it to **`$F471` —
INSIDE the `.org $F400 jah2_ext_bsr` dispatch region** → Poppy assembles the body then `.org $F400` **silently
OVERWRITES entry_d522's bytes** → `jmp entry_d522` runs garbage → derail (surfaces at `$CD1A`'s rts → `$92:$00FE`).
**FIX (shipped): place `entry_d522` at `.org $FE00`** (free $92 tail past `lsel_set@$FDCA`, ~512B) + `jmp
entry_d522`. **How found (after wrongly chasing $AC-timing / coroutine-stack / "wall"): DP ($00-$FF) AND full
work-RAM were BYTE-IDENTICAL native-vs-interp at `$CD1A` entry, yet native derailed → the divergence is NOT 68K
state → it's the ROM LAYOUT → the sym showed entry_d522@$F471 in the `.org $F400` region.** **LESSON FOR P3:
the binding constraint is ESCBANK $92 SPACE, NOT a coroutine wall — every new ce58 sub-handler must go in FREE
space (a $92 `.org` gap or cross-bank $94 via --bank2), never blindly at `ESCBANK_BODIES_END`; a body landing
in a `.org`-pinned region corrupts with NO build error.** This RETRACTS the earlier "wall confirmed" claim.
P3/P4 NOT started. Refs: `coroutine-bridge-retarget-derails` (full P2 grind + the escbank-space root cause),
`escape-deploy-shift-safe` / `escbank-overflow-second-bank` (the .org-overlap hazard),
`pt22-lever-rerank-verdict` (fork), plan `/home/chad/.claude/plans/mutable-coalescing-hippo.md`.

**Branch topology (CONSOLIDATED 2026-07-05): `main` is the single source of truth.** PRs #12
(pt.20) and #13 (pt.21) were validated + fast-forward-merged into `main` (tip `108ecce`); PRs
#1–#13 are ALL merged. The main checkout (`/home/chad/supermn-snes`) is on `main` with the real
`data/` build inputs — a next session branches off `main` for pt.22, no worktree env setup
needed. (If using a fresh worktree instead: the gitignored `data/` + `tools/mame-trace/*.bin`
build inputs must be symlinked from the main checkout; Nexen under Bash needs 2-level python
nesting + absolute ROM path — exit-144 gotcha.)

**pt.19→pt.20 record (all on branch `worktree-a3-objproc-mid`, PRs #1-#12):** A3 objproc widen
(`495ccf9`+`184a52b`, 11.9×→11.1×, PR #1); trap#5 shells (`2c0b33e`, →10.2×, PR #2); CP1 2.2
light-tick campaign complete (PRs #3-#10: trip2500 **9.28×**, light 7.44×, quiet 7.27×,
`52f8337`); CP0 STOP-rule fired → user fork decision (30fps + sound); sound kickoff
(`ee5cefd`, PR #11); 30fps decomposition (waits already self-priced; combat 4.6× binding,
`abc31b0`/`af893ce`); ISR rounds (`da3da95`/`cbab0ff`: injected windows exclude the 68K ISR
but it fires only 1×/tick — the blind spot is SMALL, free-run 1.34M/tick CONFIRMS the
steering currency); **pt.20: contention probe + WRAM supervisor loop (`8933076`, PR #12)**.
Steering doc: docs/PROFILE_CAMPAIGN.md (bottom sections, newest last). Triples/NAT backup:
`/home/chad/supermn-state/RESTORE.txt` if /tmp was wiped; /tmp/b0_native.mss is re-captured
per build by smoke_gameplay.

Everything below this banner is the pt.19-and-earlier record + REFERENCE/CONTEXT (dispatch
model, tooling, recipes, methodology, task ledger).

---

> ## pt.19 banner (2026-07-03, superseded): Phase-2.1 A3 (objproc widen) — start at
> `docs/OBJPROC_SPEC.md` §"A3 WIDEN" + the CP1/A2 sections of `docs/PROFILE_CAMPAIGN.md`.
> State then: CP1 done (`be8d3db`, light tick UNMOVED 8.4× — light interp is CBxx/$4A9E/sched);
> A1 objproc spec done (`4787ff1`); A2 SHIPPED (`296cb90`+`2a6b97f`): both objproc coroutine
> visits native via NEW bank-$01 xlat pages — trip2500 13.6×→11.9×, ce4 11.8×; transpiler F1–F5
> landed (`071b69b`). Memory `objproc-a2-shipped` has the F1 pushed-sentinel lesson + the
> audit_banks.py findings (incl. the PRE-EXISTING escbank $F000 overlap = the d386/d3b0
> divergence suspect).

---

# ⭐ CURRENT TASK (start here): HLE SPIKE — does hand-written native beat the faithful ceiling?

> ## ✅ pt.18 (2026-07-02): SPIKE EXECUTED — VERDICT: GO. SHIPPED `0aac3c6` (enabled in production).
> **Answer to the hypothesis: YES, decisively — and the premise needed correcting.**
> - **Built:** `hle_12b6c` (escbank2 `.org $E000` = `$94:E000`) — hand-written native tree
>   (dispatcher + $12B84/$12C04 marshalling, faithful stack residue, CCR/X materialization, direct
>   `jml.l entry_ce4` when a1==$0CE4, interp bails for the rare blink-counter sub-path). Dispatched
>   by `bhp_bank_ext` (zero-shift 4B swap in `bsr_hookpush`, hosted in the dead entry_25110 space).
> - **Bit-exact:** ESC=full FULLDIFF = the identical 4-byte baseline set; ESC=0 GREEN; smoke OK.
> - **Measured** (spin-free same-run spans `$011778→$01177C`, `tools/hle_span.py` — NEW, because the
>   step-5/6 method here was UNSOUND: the CYCLES=1 B1PC read is spin-polluted + cross-run absolutes
>   don't compare): **interp 82,019 cyc → HLE 34,746 = 2.36×** end-to-end; marshalling body 1,572 vs
>   ~49K interpreted ≈ **30×**. Variants: v1 jsr-handoff 37,845; sentinel-through-ce4t 41,457
>   (REJECTED → exposed **hand-native entry_ce4 24.5K vs transpiled entry_ce4t 39.7K = 1.62×**).
> - **CORRECTIONS (rewrite your priors):** the 11,300 baseline this section cites was a measurement
>   artifact — the TRUE interp baseline is 82K, so the pt.15 "contiguous-compile LOST / loop_hook
>   collapses loops to ~free" story is INVERTED (transpiled 26-37K actually BEAT interp; Option B is
>   back on the table). And `$012B84` has NO loop — it is straight-line marshalling; the loops are in
>   its `jsr(a1)` callee `$0CE4` (already native). End-to-end tree wins are CALLEE-BOUND.
> - **Campaign sizing (GO):** dominant lever = make the remaining ~1040 interp instrs/tick native
>   (~2K cyc each ≈ 2.1M of the 3.8M combat tick): transpile where possible, **HLE where transpile
>   fails** (the state-cluster floor is exactly HLE's niche); secondary = hand-rewrite the hottest
>   native bodies (1.6×). Effort: this 51-instr tree ≈ half a session; est. 2-4h per
>   marshalling-class routine, 1-2 sessions per loop-heavy body.
> - **Reusable-pattern check: CONFIRMED** — the hand body used the standard escape slot + gates +
>   validation, zero new machinery (Gigandes-safe; the toolchain does not fork).
> - Memory: `hle-spike-verdict` (+ the superseded-banner in `contiguous-compile-prototype`).


**Read these memory files first (they are the substance; this section is the checklist):**
`contiguous-compile-prototype.md` (the proven bank-$01 dispatch + the measurement gotchas + the
measured baselines), `contiguous-compile-profile.md` (why these targets; the hot-region map),
`aot-codegen-sketch.md` (the ~2.7× ISA-penalty floor), `production-escape-enable.md` (the escape-bank
pattern + the "banks full was WRONG, escbank2 has ~18KB free" correction), `gigandes-target.md`
(the reusable-toolchain goal this must not break).

## Why (the strategic frame)
Every 68K-FAITHFUL approach (interpreter + per-function escapes + contiguous-compile) is at its ceiling:
the SA-1's clock margin over the 68K (~1.34×) is smaller than the 68K-on-65816 ISA penalty (~3-4×), so
the theoretical floor is ~2.7× the 60fps budget → **flawless 60fps is UNREACHABLE faithfully.** We are
at "avg-frame realtime + combat frame-drops." **HLE — hand-writing a hot routine as native SNES logic
(same RESULT, not the same instructions) — is the ONLY lever that drops the ISA penalty and can break
that floor.** This spike SIZES it before any campaign: does a hand-written native routine beat the
interpreter (which, via `loop_hook`, is effectively already a hand-tuned native loop) on a hot
loop-heavy routine — and how much effort per routine? It ALSO validates the reusable pattern (below).

## Hypothesis + success criteria + deliverable
- HYPOTHESIS: a hand-written native routine (tight loops, direct BE work-RAM, SA-1 HW where useful, no
  68K faithfulness) beats the interp's `loop_hook`-assisted cost on a hot loop.
- SUCCESS: HLE body cost **< the interp baseline** for the same routine, BIT-EXACT. A large margin ⇒
  HLE worth a campaign; roughly equal ⇒ `loop_hook` is already near-optimal ⇒ HLE not worth it for
  loops (a real, negative answer — then ship playable-with-drops; the faithful ceiling stands).
- DELIVER: the HLE body + its measured cost vs the baselines + a GO/NO-GO verdict + a per-routine effort
  estimate (hours to understand+write+validate) to size a full HLE campaign.

## Target (reuse THIS session's proven infrastructure)
- **PRIMARY: the `$012B6C → {$012B84, $012C04}` call-tree** — the exact loop-heavy case where
  faithful-native LOST this session (transpiled 26-37K cyc vs interp 11.3K). HLE it as ONE hand-written
  native routine. ~51 real 68K instrs across 3 small fns → tractable. `$012B84` is the loop-heavy leaf
  (the reason faithful lost); `$012B6C` a small dispatcher; `$012C04` a tiny leaf. The bank-$01
  dispatch + escbank2 hosting + `hle_cost.py` measurement are ALL PROVEN this session for this exact
  target — you are swapping the transpiled body for a hand-written one.
- ALTERNATIVE if `$12b84`'s semantics don't reimplement cleanly in a session: the `$025110` collision
  O(n²) inner loop — DEEPLY understood this session (object table @ `a5+$3a74`; outer loop over objects
  `d7=$1E`; inner pair scan; type checks vs `$bf`/`$bd`; x-coord `cmp.w $4(a1),d0/bgt`; result in
  `d5/d6/d7` = `FFFF`=none). Hotter (~12.6%) but 545 instrs — HLE only its inner loop.

## Baselines (measured this session; ce4trip64 combat, production gates on)
- **interp `$012B6C` tree = 11,300 cyc / invocation** (loop_hook-assisted). ← **THE NUMBER TO BEAT.**
- transpiled faithful native = 37,049 cyc (--bank2) / 26,125 cyc (--workram) — both LOST.
- straight-line `$012A92` native = 893 cyc (calibration: what native does with NO loop → ~40× cheaper).
- whole active-compute tick ≈ 3.14M cyc (~21× the 179K-cyc/frame 60fps budget). B1PC=0818 span.

## Step-by-step
1. **UNDERSTAND the semantics (the crux, do this properly).** Disassemble `$012B6C/$012B84/$012C04`
   (capstone m68k; 68K PC → ROM file offset `0x10000+(pc&0x3FFFFF)`). Capture its real execution + I/O
   with this session's method: the interp PC-stream (`dbg_fetch` $40:8000, enabled by `$0718=0`; see how
   `contiguous-compile-prototype`/lockstep_trap `GPPROF ALLSTREAM` did it) and MAME as ground truth.
   Write a SEMANTIC SPEC: which regs/work-RAM it READS, what the loop COMPUTES, which regs/work-RAM it
   WRITES. If it's too tangled to reimplement confidently, switch to the `$025110` inner-loop alternative.
2. **RE-ESTABLISH the dispatch** (it was reverted after the negative contiguous-compile result). Recipe in
   `contiguous-compile-prototype.md`: zero-shift swap `lda $5E/bne bhp_push`→`jmp bhp_bank_ext`+`nop` in
   `bsr_hookpush` (interp.pasm); host `bhp_bank_ext` in the DEAD inline-`entry_25110` space ($D1F2+, past
   its `jml $978000` redirect); match `$5E:$5C == $0001:$2B6C`; set `$40=$54` (PC=return $01177C),
   `$42=$0001`; `pla`; `jml $94<hle_entry>`. Host the HLE body in escbank2 (`$94`, ~18KB free; splice
   before the `ESCBANK2_BODIES_END` marker; get its addr from `escbank2.sym`; hardcode it in the `jml`).
3. **HAND-WRITE the HLE body** (native 65816/SA-1). Produce the SAME outputs bit-exact, NOT the same
   instructions. Entry state (from the dispatch): `$40`=return($01177C), `$42`=$0001, 68K stack ptr at
   `$3C`, reg-file DP model (D0-D7@$00-$1C, A0-A7@$20-$3C, a5=state base@$34). Work RAM is `$40:xxxx`
   BIG-ENDIAN (`lda $400000,x; xba` = BE word). Return via the 68K-rts idiom → `jml.l ors_pre` (see any
   transpiled `--bank2` body's tail). Use tight native loops, SA-1 HW (mul/div `$2250+`, DMA) where it
   helps. It needs a re-sim-push prologue ONLY if the interp expects the return re-pushed — check against
   a transpiled body's prologue.
4. **VALIDATE bit-exact.** `python3 tools/lockstep_trap.py /tmp/supermn-scratch/ce4trip64 2F60 1` env
   `B1PC=0818 CHOKE=1 SWIN=1 SEL=1 FULLDIFF=1 HOOKTEST=<hle_entry_sa1_linear>` → require **GREEN** AND
   `matchedEventsEmitted≥1` (it fired natively). Zero-added-divergence: the FULLDIFF set must be identical
   to the ESC=1 baseline WITHOUT the HLE (i.e. the tree interpreted).
5. **MEASURE.** `python3 tools/hle_cost.py /tmp/supermn-scratch/ce4trip64 <hle_entry_24bit> <hle_exit_24bit>`
   → the spin-free native body cost. `<hle_exit_24bit>` = the body's terminal `jml.l ors_pre` addr.
6. **VERDICT.** HLE_cost vs 11,300: `<<` ⇒ GO (report the ratio + estimate the tick fraction a full HLE
   campaign could reclaim toward the 3.14M→179K goal + the per-routine effort). `≈`/`>` ⇒ NO-GO for
   loops (loop_hook already near-optimal) ⇒ ship playable-with-drops; HLE only helps straight-line, which
   is a small share. Bank the verdict + numbers in memory + STATUS.md.

## Measurement gotchas (LEARNED this session — do not relearn)
- Native cost: **`tools/hle_cost.py`** (exec-hooks + `run_until`, spin-FREE). The `$0710` fetch-trap
  BUSY-SPINS to end-of-frame (~179K cyc pollution) → useless for sub-tick spans. The whole-tick
  poke-diff is NONDETERMINISTIC (~60K/tick B0-staging jitter) → only valid for effects `>> 60K`.
- The interp baseline (11,300) is NOT re-measurable by exec-hook (shared `iloop`, no distinct SA-1 addr)
  — it's this session's measured number; trust it (or re-derive via the whole-tick poke-diff ONLY if the
  effect is large).
- `lockstep_trap.py` now has a **bank-aware B1 trap** (pass a 24-bit `B1PC` to trap a bank-≠0 PC;
  committed `aa0ad11`). `tools/exit_dump.py` isolates an escape's direct output (committed `6713ed3`).

## Reusable-pattern check (must confirm — this is why HLE is OK for the Gigandes plan)
HLE = a hand-written escape BODY in the EXISTING escape framework (same dispatch hooks, same bit-exact
vs-MAME validation). The framework (interpreter + dispatch + validation) is game-AGNOSTIC — Gigandes
reuses all of it; only the reimplemented BODY is per-game. During the spike, CONFIRM the pattern is clean
(a hand-written body drops into an escape slot with zero special machinery beyond what a transpiled body
needs). If confirmed, HLE is a per-game escape hatch that does NOT fork the toolchain. If it needs
special machinery, note what — that's a cost against the multi-game thesis.

## Guardrails
- It's a SIZING spike: ONE target, ONE number, ONE verdict. Don't sink >1 session or chase full-routine
  HLE — validate the pattern + the payoff, then stop and report.
- Bank-$00 must NOT shift (packed; 8-bit branch wrap). Zero-shift edits only (see methodology §7 below).
- Git: branch `boot-scheduler-progress`, HEAD `aa0ad11`, pushed. This session added `tools/hle_cost.py`
  (the measurement tool) — commit any spike work as its own commits; don't touch the shipped 5 commits.

---


> ## ⇒ STATE (2026-07-02): the Phase-2 escape/codegen sprint is BANKED. DO NOT auto-start a campaign.
> The escape-coverage thread is COMPLETE and validated — see `STATUS.md`'s "BANKED" block for the
> shipped table (Campaigns 1-4 + 2 transpiler CCR fixes + the ~2× INLINE_MEM codegen win; cumulative
> moderate 4666→3714 / heavy 8010→2917 interp-instr, all bit-exact). The coverage FLOOR is reached
> (pt.14 verdict below): the remaining moderate clusters are dynamic-dispatch game-logic that doesn't
> transpile. **More coverage will NOT close the ~24-40× realtime gap.** The open item is a
> STRATEGIC-DIRECTION decision (pt.11 fork: codegen-efficiency / big-transpile / accept-sub-realtime /
> re-architect), which is the USER's to make — no realtime work is queued pending it. The chronological
> campaign-completion blocks below (pt.5→pt.14) are the sprint record; the mental model / tooling /
> recipes (§1-8) remain current and correct.
>
> **pt.15 (2026-07-02): the "re-architect" fork is now SKETCHED + approved** →
> `/home/chad/.claude/plans/reflective-twirling-cook.md` (memory: `aot-codegen-sketch.md`). Verdict:
> native regalloc is the WRONG lever; **contiguous call-tree compilation** is the game (measured 4.85×);
> static-addressing = bounded polish. Realtime-EVERY-frame is UNLIKELY (SA-1's 1.34× clock margin <
> the ~3-4× 68K-on-65816 ISA penalty → ~2.7× budget at the codegen floor; avg-frame fits, heavy-combat
> ~5×). Achievable ceiling = **avg-frame realtime + heavy-combat drops** (arcade-like).
>
> **pt.16 (2026-07-02): Phase-0 budget measurement EXECUTED** (lockstep_trap CYCLES=1 B1PC=0818,
> current HEAD; budget 179K cyc/tick). BIG FINDING: **the escape gates are never enabled in production
> src** ($071A/$073A/$073C/$0736 harness-only) → the ROM SHIPS pure-interp (~12-68× over budget). Max
> escapes (ESC=1+CHOKE+SWIN+SEL) → **combat worst-case ~16-17×** (ce4trip64 8.39M→3.05M; span_heavy
> 12.23M→2.87M), **light frames ~7-8.5×**. Near-bit-exact (ce4trip64 DIFF=48 = the known $AC-pacing
> artifact). VERDICT (measured, confirms the sketch): realtime-every-frame OUT; avg-frame realtime is
> the ceiling + in codegen-lever range. **THE FORK (user's call): (A) flip escapes ON in production +
> validate free-run = a validated ~4× speedup currently switched off (cheap; its free-run validation is
> also the first $AC-pacing probe); (B) A + multi-session contiguous-compile toward avg-frame realtime;
> (C) bank.** Rec: A first, regardless. Full table + go/no-go in the plan file's "Phase 0 — EXECUTED"
> section; raw logs in /tmp/supermn-scratch.
>
> **pt.17 (2026-07-02): Option A STARTED — escapes now ENABLED in production boot.** `BOOT_ARM`
> (src/video.pasm @ `$E9:8900`) arms the 4 gates; the notest boot `jsl BOOT_ARM` **replaces** the
> SA-1-no-op `jsl VID_INIT` = ZERO bank-$00 shift (an INLINE insert BROKE gameplay — smoke stuck at
> 68K `$3ABE`; bank-$00 must not shift). Validated: smoke PASS (no regression), BOOT_ARM runtime-arms
> the gates, escapes-on FREE-RUN stable (swin 47→203 / sel 40→174 linear over 1800f, no crash).
> Change is UNCOMMITTED. **REMAINING GATE before a clean ship: `$AC`-pacing over sustained free-run is
> UNvalidated** (only scheduler escapes exercised in attract; render/HUD not free-run-tested; the
> `--accharge` work is the next step). See memory `production-escape-enable.md` + the plan file.

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

> ## ✅ Campaign 4 SHIPPED after all — native scheduler SELECT (`lhs_sel`), `0a36f95` (2026-07-01 pt.10)
> The pt.9 "bank-$00-blocked" read was too pessimistic: found a **zero-shift** deploy. `lhs_found`
> (`lda #$075C; bra lhs_exit`, 5B) → `jml $92FD00; nop` (5B) — `lhs_done`/`lhs_exit`/all anchors
> UNCHANGED. `lhs_sel` (escbank `$92:FD00`) does `$075C-$0778` natively and sets `$40` to the
> continuation (`$0796` ready→entry_swin / `$077A` defer / `$074C` disabled), producing EXACTLY
> entry_swin's input reg-file. Gate `$0736==$5EEC`; OFF → replicate the handoff + re-fetch `$075C`
> (swo_tramp has no `$075C` arm → decodes normally, **no loop** — the key that made this work without a
> swo_tramp arm or dropping entry_swo). `pla` drops the loop_hook return (entry_swin pattern).
> **Validated:** ESC=0 regression unshifted (4666/8010/1259 GREEN); vs-MAME GREEN both arms ×3; 20-tick
> self-diff **0 LIVE ×3**; composes with entry_swin (sel=10→swin=11) + full-on 20-tick self-diff 0 LIVE.
> **Measured:** moderate **−110 interp-instr/tick** (10 selects×11; exact) ≈ ~7% of the tick; heavy/quiet
> do few selects/tick (~neutral there). **Cumulative C1-4 full-on: moderate tick 4666→3714 interp-instr,
> heavy 8010→2917.** Off-default cost negligible (native round-trip, 0 added interp-instr).
> **NEXT (Campaign 5):** the moderate state clusters `$01C9xx/$01E7xx` (~165) + `$00CBxx` (~109) —
> jmp-state/coroutine via the `$CEB6` dispatcher → xlat table (escbank, no bank-$00 fight); needs
> per-entry-PC identification (the c172/d5c4 pattern). Or the bank-$00 compaction to unblock more
> loop_hook-class escapes. Re-run the ALLSTREAM gate first.

> ## ⏸ Campaign 5 — GATE DONE: clean levers EXHAUSTED; remaining = complex game-logic (2026-07-02 pt.11)
> Re-profiled full-on (incl. lhs_sel): moderate 4666→3714 done; remaining ~1046 interp-instr is
> dominated by **complex game-logic / state-machine clusters, none a clean mechanical escape:**
> - **`$01C9xx-$01F1xx` (~177, biggest):** the main **object-update loop** — 16-object physics +
>   animation, `ori #$700,sr; set a7; jsr(a6)` DYNAMIC dispatch, table-driven fixed-point math,
>   branches to `$1cd38/$1ca48`. Core game logic, dynamic-dispatch — a transpile rabbit hole (high
>   risk, bridge-dominated). NOT the mechanical-scheduler class C1/C4 escaped.
> - **`$00CBxx` (~109):** a big linked function (a6-frame locals, jump tables `$32578/$32d16`) with an
>   object-copy loop + `bsr $cb9e`/iter. Also game logic; no clean entry (link >$140 back).
> - **`$023xx-$024xx` (~94):** coroutine `trap #$5`. **`$012xx` (~58):** small `bsr`-reached fns —
>   only `$12A92` (22 instr) / `$12B6C` (8) transpile clean, and each fires ~1×/tick (~30 instr total,
>   token value); `$129C6` (bset-dyn) + `$12C1A` (stray blt) are UNIMPLEMENTED.
>
> **STRATEGIC INFLECTION (the honest read after C1-4 + the transpiler fix):** the escape-COVERAGE
> approach has now captured the mechanical/scheduler/background levers. What remains is game logic that
> is expensive+risky to escape cleanly and (per [[cycle-budget-realtime-gap]]) bridge-dominated /
> diminishing. Coverage alone plateaus at ~5-10× over the 179K budget; we're still ~24-40× off. The
> real levers from here are **not more coverage** but: (a) **codegen efficiency** (the thesis's actual
> lever — but [[workram-lever-bounded]] pins EA-specialization at ≤20%, ~1.2×, not the ~5.7× realtime
> needs); (b) a **big game-logic transpile** (the object-update loop — high effort, uncertain net given
> dynamic dispatch); (c) **accept sub-realtime** and bank the C1-4 progress; or (d) reconsider the
> hybrid interp+escape ARCHITECTURE vs full-AOT for the realtime goal. Campaign 5 did NOT ship — the
> disciplined call is to surface this fork rather than grind a marginal/risky escape. Tools ready
> (lockstep_trap/choke/multitick all have SEL/$0736; `val_branch32.py` guards the transpiler).

> ## ✅ Codegen efficiency (user pick) — 16-bit INLINE_MEM, ~2× cheaper inline access, `c4a5e60` (pt.12)
> The escape bodies' inline work-RAM access was byte-by-byte BE assembly in 8-bit mode (`sep #$20; lda
> $400000,x; xba; lda $400001,x; rep #$20` = 5 ops). A **16-bit `lda $400000,x`** reads both bytes LE;
> **`xba`** → the 68K BE word = **2 ops, no sep/rep** (rdw40 5→2, wrw40 6→3, rdb40 4→2; wrb40 stays
> 8-bit). Pure equivalence, the common path in EVERY escape body → ~2× cheaper on every inline word/byte
> access, all escapes uniformly, no per-escape validation. NEW general codegen win, DISTINCT from
> `--workram` (bounded ≤20%, already-mostly-done); it speeds the accesses the transpiler ALREADY inlines
> (a5/a6/a7 + `--workram`), which dominate the bodies. Rolled out (regenerated + re-spliced) to the clean
> `--table` gameplay escapes: **ce4t 780→660 ops, 29b6t −96, 13bet −66, 295at −27** (~309 native ops/tick
> removed; 29b6t/295at kept `--video`). Validated bit-exact (ESC=0 unshifted; full-on vs-MAME GREEN
> mod+heavy; ce4 native-vs-interp + full-on-vs-all-off 20-tick self-diffs 0 LIVE). Win = op-count (exact);
> full-tick cyc delta is below the ~0.7M runf noise. **NOT re-done:** 8fat/fd2t (hand counter + still-open
> **dbra-fallthrough CCR gap**), c172 ($AC-charge), attract/gap escapes → heal on next natural re-transpile.
> **NEXT codegen levers:** (a) close the dbra-CCR gap → re-transpile 8fat/fd2t clean+cheaper; (b) the
> `[dp],y` copy prize for future memcpy escapes; (c) broad `--workram`. All bounded — codegen is polish,
> not the 24×-closer; the pt.11 realtime fork still stands.

> ## ✅ dbra-CCR gap CLOSED + escbank2 fully transpiler-generated — `8600fc6` (pt.13)
> The Campaign-2 hand-fix is now in the transpiler. **Gap:** 68K `dbra`/`dbf` PRESERVE the CCR, so a
> caller reads N/Z of the loop body's last moved value — but the transpiler's `dbra` emits `cmp #$FFFF`
> (corrupts native flags), move.l's native flags are the pointer-bump's not the value's, and
> `emit_ccr_native` only fired at Bcc-to-exit edges (a dbra FALLS THROUGH to the epilogue). **Fix:**
> `emit_ccr_from_value(dp,size)` computes N/Z (V=0,C=0) from the move's result value; the main loop
> detects a `dbra`/`dbf` whose fall-through ∈ `exit_addrs` and materializes from the loop body's last
> move (`dbra_exit_ccr_val`: move.l (An)+,(An)+→`$9A`; move Dn,mem→Dn; move #imm→const). Byte-matches
> the old hand-fix; **inert** for escapes w/o a dbra-to-exit (13bet/29b6t/295at regen byte-identical).
> **Re-transpiled 8fat/fd2t clean** (dbra-CCR auto + 16-bit INLINE_MEM; counters re-added) + **ce4t**
> (also has a dbra-to-exit, was benign-GREEN, now materialized). **ESCBANK2 IS NOW 0 HAND-FIXES —
> fully transpiler-generated.** Validated: ESC=0 unshifted; full-on vs-MAME GREEN mod+heavy;
> ce4/8fa/fd2 native-vs-interp + full-on-vs-all-off 20-tick self-diffs 0 LIVE; `val_branch32` 5460/0.
> The two transpiler CCR gaps (32-bit `.l` flags + dbra-fallthrough) are both closed → the escbank
> bodies carry no hand-patches; future escapes transpile correct. **Remaining codegen levers:** the
> `[dp],y` copy prize + broad `--workram` (both bounded); the realtime fork (pt.11) still stands.

> ## ⛔ Campaign 5 state clusters — DEEP-DIVE VERDICT: NOT escapable (2026-07-02 pt.14)
> Investigated the moderate state clusters exhaustively (reach + STREAMWIN + test-transpile). They are
> the game's **core object/actor/coroutine system**, and they resist the escape approach:
> - **`$01C9xx-$01F1xx` object-processor (~177, biggest):** a COROUTINE body resumed via `jsr (a6)`
>   with a6 = a5-relative resume-PC (`$3506(a5)`=`$01C99E` in-state). `jsr(An)` IS hooked
>   (op_jsr_an→jsrabs_hook2→jah2), so it's *reachable* — BUT the body is **>300 instructions** (no rts
>   within 300 of `$01C99E`), does **dynamic `jsr (a4)`** dispatch, and **fails to transpile**
>   (`Unsupported: EA '(a4...'`). A wholesale escape would be huge + bridge-dominated + need new
>   transpiler EA support → high-risk, low-value (the cycle thesis's worst class).
> - **`$00CBxx` (~109):** big linked fn, `$32578`/`$32d16` jump tables, a6-frame locals, `bsr $cb9e`/iter.
> - **`$023xx-$024xx` (~94):** `trap #$5` coroutine yields. **`$012xx` (~58):** hot PCs are mid-flow in
>   big fns; only tiny leaf fns (`$12A92` 22 / `$12B6C` 8) transpile clean and they DON'T cover the hot
>   PCs (~1×/tick, token). `$129C6` (bset-dyn) / `$12C1A` (stray blt) UNIMPLEMENTED.
>
> **VERDICT:** no clean, measurable, low-risk escape exists in these clusters. They'd need a major
> transpiler push (big-body + dynamic-`jsr(An)`-dispatch bridging + new EA modes) for uncertain,
> bridge-dominated value — NOT worth it under the measured discipline. This is the concrete floor of
> the escape-coverage approach: the mechanical/scheduler/background/HUD levers (C1-4) are captured;
> what remains is dynamic-dispatch game-logic. The realtime goal (still ~24-40× off) needs the pt.11
> fork (codegen — bounded; or re-architecture), NOT more coverage. **Nothing shipped; tree clean.**

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
