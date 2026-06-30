# MAIN_PLANNING_HANDOFF.md

Last updated: 2026-06-30. **Read this first** in a fresh session, then act. It captures the
current state, the reliable mental model (several older notes were WRONG — corrected here), the
tooling, the validated escape-deployment recipe, and prioritized next steps.

Goal: ~99% native per-frame coverage so the SA-1 runs Superman at realtime (playable).
Repo: clean at `507d692`, branch `boot-scheduler-progress`. AOT table: **13 escapes**
(c172 = first COROUTINE escape, shipped this session; STEP A resolved).
Build: `bash tools/build_interp.sh` (→ `build/interp.sfc`).

> NOTE: there is older planning text (STATUS.md, ROADMAP.md, and the prior version of this file)
> from the "bulk-transpile / 8-escape" phase. The strategic picture has since changed — trust THIS
> doc and §1 over those.

---

## 1. The reliable mental model (corrected this session — trust this)

The interpreter (`src/interp.pasm`, 65816 on SA-1) runs Superman 68K code. Per GAME_TICK (`$3A92`)
it executes **~1900 genuinely-interpreted 68K instructions/tick**. Realtime needs that ~40
(escape ~99% of per-tick work to native). Each native escape = a transpiled 65816 reimplementation
of a hot 68K function, dispatched so the interp jumps to it instead of interpreting.

**Dispatch families that ACTUALLY FIRE in gameplay (verified with SA-1 exec-hooks):**
- **jah2 (jsr-class):** `jsr.l`/`jsr (An)`/`bsr` → `jsrabs_hook2` cmp-chain (interp.pasm:16970).
  Already covers the clean leaves ($412, $CE4, $111A, $295A, $29B6, $25110, …).
- **jmp-state (the AOT xlat table):** `jmp (a0)` → `op_jmp_idx` → `ojmp_hook` ($00:D1B3) →
  `xlat_dispatch` ($94:F900), data in `src/xlat_table.bin` from `tools/gen_xlat_table.py`. The
  PC→native table. Verified firing: d0d0, d5c4, d718, d3f6, etc.

**What is PROVEN NOT to work (reliable exec-hook evidence, this session):**
- **rts-class table dispatch fires 0× in gameplay.** `ce4t` and `entry_13bet` NEVER fire. The hot
  handlers ($CE4, $13BE, …) are reached as **rts returns inside the coroutine scheduler's
  `rte→task→rts→next` chain**, which bypasses `op_rts_norm→ojmp_hook→xlat`. You CANNOT grind
  rts-reached "leaf" escapes into the table — they will not fire. `ce4t` is dead weight in the
  table; its old "fires 63451×" claim was a **corrupted `$07xx` memory-counter artifact**.

**The dominant interpreted cost = the coroutine SCHEDULER + the coroutine/handler chains:**
- `$0500-$07C0` scheduler machinery ≈ **470/tick**. The 16-task cooperative dispatcher is
  `$074C-$07E8`: per task → check enable bit (`btst d0,$2(a5)`), check flags, set a7=task SP,
  `rte` to resume. `$0740` region alone = 246/tick (the disabled-task-skip iteration).
- `$00C1xx` multi-resume coroutine ≈ **227/tick** (c172 = `$C172`).
- Object handlers ($CB40, $CE80, $CD40…) and bank-`$01` context-switch code ($01C980: `ori #$700,sr`
  + `lea a7` + `jsr (a6)` = an SP-swapping context switch).

**METHODOLOGY RULE (hard-won):** NEVER trust in-memory diag counters at `$07xx` — the game
overwrites them; they give garbage (read "xlat 63524×" when truth was 73×; "clean13be 56493" was
noise). ALWAYS measure SA-1 execution with **exec-hooks** (`HOOKTEST`, §2).

---

## 2. Tooling (all in `tools/lockstep_trap.py`, env-var driven)

Run: `[ENV=…] python3 tools/lockstep_trap.py <triple-dir> 2F60 <ESC>`
Triples (MAME-ground-truth GAME_TICK captures) in `/tmp/supermn-scratch/`:
`ce4trip64`, `trip2500`, `trip4000`, `trip5000`. ESC=1 = escapes on; ESC=0 = pure interp.
Baseline: ESC=1 on `ce4trip64` = **DIFF=48** (a pre-existing `$0708`-trap/$AC timing artifact);
ESC=0 = GREEN. A new escape is "clean" if DIFF stays 48 AND the diff *set* is byte-identical to
baseline (zero added/removed bytes).

- **`HOOKTEST=<hex,hex,…>`** — arm SA-1 exec-hooks; prints `hook_diag matchedEventsEmitted` = the
  TRUE fire count. The reliable fire test. (Escape SA-1 addr: `src/escbank2.sym` `00:XXXX entry_foo`
  → `$94XXXX`.)
- **`GPPROF=1`** — dump the genuinely-interpreted (ilog) stream; top 64B regions = real gameplay
  interpreted cost. (GPPROF clobbers work-RAM $8000+/$C000+ → its wramB DIFF is meaningless in this
  mode; use only for the stream.)
- **`PRED=<hex>`** — stream predecessors of a PC (how it's reached).
- **`STREAMWIN=<hex>` [`STREAMWIN_N=20`]** — ordered stream window before the first hit (traces the
  true call chain; this revealed the scheduler→rts→handler chain).
- **`ENTRYCLASS=1`** — tally function entries by dispatch kind (jsr/bsr/rts/jmp/rte). Use to tell
  jmp-reached (catchable) from rts-reached (NOT catchable).
- **`B1PC=<hex>` + `REGDUMP=1`** — trap at a PC; dump reg file + `$AC`/`$4A`/vbl (for `$AC` pacing;
  trap at a yield e.g. `B1PC=C170`).
- **`FULLDIFF=1`** — list all diff bytes (for symmetric-diff zero-added checks).

---

## 3. VALIDATED escape recipe (jmp-state class) — this WORKS; shipped d718 + d3f6 this way

1. `python3 tools/transpile.py <pc> --bank2 --coroutine` (jmp-state = `--coroutine` convention).
   `Unsupported` → not tractable yet (see §4 STEP D transpiler hardening).
2. Splice the body into `src/escbank2.pasm` before `; >>> ESCBANK2_BODIES_END`.
3. Add the PC to `JMP_STATE_PCS` in `tools/gen_xlat_table.py`.
4. `bash tools/build_interp.sh`.
5. Validate (the gate, all on a triple where the handler is jmp-reached — check `ENTRYCLASS=1`):
   - `HOOKTEST=<entry_addr> … 2F60 1` → matchedEvents > 0 (it FIRES); instr drops.
   - `FULLDIFF=1 … 2F60 1` → DIFF=48, symmetric diff vs baseline empty.
   - `… 2F60 0` → GREEN.
6. Commit only if it FIRES AND zero-added AND GREEN. rts-reached handlers won't fire — don't deploy.

---

## 4. Next steps, prioritized

### STEP A — `$AC` exact-charge / COROUTINE class. **RESOLVED 2026-06-30 (task #73 closed). c172 SHIPPED.**
Resolution (commit 507d692): the "charge=0 and charge=35 both give DIFF=49" anomaly is settled.
- `esc_ac_charge` WORKS (measured: `--accharge` drains `$AC` by exactly 231 at `$AC@C170`).
- The exact c172 charge = **35** (isolated: c172-interpreted reaches `$C170` in 562 interp-steps
  vs 527 escaped). Shipped as ONE static `lda #$0023 / jsr esc_ac_charge` at entry; per-block
  `--accharge` OVER-charges to 231 (bridged loop charges per-iteration).
- The residual `$F01401` byte is NOT `$AC`-correctable: the `$0708` lockstep trap is
  HARDWARE-VBLANK-driven, proven `$AC`-INVARIANT (DIFF=48 across injected `$AC`=2F60/2600/3400).
  c172's body never writes `$1401` (targets a5+`$2A3x` / a4 `$0004`+8 / a7 `$170A`+0xE); the
  01-vs-04 is other code shifted by the escape running faster (1878 vs 1913 steps to vblank) — a
  sub-realtime artifact, same class as the 48-byte baseline. Bounded across 3 triples (49/51/51).
- RECIPE for the next coroutine's exact charge: toggle `CORO_PCS` in `gen_xlat_table.py`, measure
  `$AC@<yield>` via `REGDUMP=1 B1PC=<yield>` both ESC=1; the delta is the charge. Splice the body,
  add a single static charge at entry, validate (FIRES via HOOKTEST + ESC=0 GREEN + bounded diff).

Next coroutine bodies to grind (rte-reached, same path): `$46DE`, `$7828`, `$11752`, the rest of
the `$00C1xx` cluster. NOTE (from [[coroutine-shells-low-value]]): coroutine shells save only
~35/tick each — the bigger lever is escaping their bridge CALLEES ($29B6/$295A already escaped).

c172 facts: body is PROVEN bit-exact (regs + work-RAM identical at the `$C170` yield, ESC=1 vs 0).
Native c172 saves ~35 interp-steps vs interp (others held constant). `--accharge` OVER-charges
(~231 vs needed ~35) because bridge callees run interpreted in BOTH paths.

**Experiment / decision tree (resolve the anomaly first):**
1. Deploy c172: `transpile c172 --bank2 --coroutine`, splice escbank2, add `CORO_PCS={0xC172}` into
   gen_xlat_table's `ALLOWED_PCS`, build. It dispatches via op_rte→ors_rte_x→table and FIRES
   (HOOKTEST on its entry addr).
2. **THE ANOMALY to resolve:** this session, charge=0 AND charge=35 both gave DIFF=49. Either (a)
   `esc_ac_charge` (src/escbank2.pasm) isn't actually consuming `$AC`, or (b) `$1401` isn't
   `$AC`-determined. Verify (a): `REGDUMP=1 B1PC=C170 … 2F60 1` with charge=0 vs charge=N — does
   `$AC@C170` change by N? If not, FIX `esc_ac_charge` first.
3. If the charge works: find the exact value = (`$AC@C170` for c172-OFF) − (c172-ON-no-charge),
   both ESC=1, others constant. Static-charge that delta; DIFF should return to 48.
4. If `$1401` still won't clear with the exact charge → it's not `$AC`. Use `add_write_hook` on Sa1
   `$401401` (BYTE-granular matchValue, not word) or `STREAMWIN` around the write to find the writer.
5. Alternative framing: confirm via multi-tick lockstep (`tools/lockstep.py`) whether the divergence
   stays BOUNDED across several GAME_TICKs (→ pure `$0708`-trap/$AC measurement artifact, not a
   gameplay bug; the 48-byte baseline is already this class) — if so, it's defensible to relax the
   single-frame zero-added gate for body-bit-exact coroutine escapes.

Once `$AC` is solved, c172 ships (first coroutine escape) and the path is validated end-to-end →
grind the other rte-reached coroutine bodies (`$46DE`, `$7828`, `$11752`, the `$00C1xx` cluster).

### STEP B — More jmp-state escapes (task #79). INVESTIGATED 2026-06-30: surface is SPARSE, LOW ROI.
Finding: beyond the shipped 11, the jmp-state surface is largely exhausted. ENTRYCLASS across
ce4trip64/trip2500/trip4000/trip5000/trip1000/trip1040 shows the only jmp-reached targets are rts
TRAMPOLINES ($CF8A/$D6D8/$D374 = bare `rts`, escaping them is a no-op) plus the already-shipped
handlers. $CEB6 and $D522 ARE catchable in principle — both are jmp-reached from `$00D52C: jmp (a0)`
(the object-dispatch loop, op_jmp_idx-routed) — and transpile+deploy cleanly. BUT their reaches are
RARE and scene-specific (x1 in one frame's GPPROF stream), so they could NOT be validated FIRING:
HOOKTEST=0 on trip1000 (732-instr window) AND trip1040 (1181-instr window, ce4t fired 3x). Per the
§3 gate ("commit only if it FIRES"), they were built+reverted, not shipped. Each is ~10 interp/tick
anyway. To actually land these you need a true FIRE-FINDER: trace `$00D52C` jmp(a0) targets across
the MAME playback (`/snap/bin/mame` + vplay.inp), find a frame where target==$CEB6/$D522 with a full
GAME_TICK->vblank window, capture that triple, then run §3. Deferred as low-value vs STEP C.

### STEP C — Escape the SCHEDULER (task #75). DONE 2026-06-30 (commit 1aaafb2). lh_sched shipped.
Hand-wrote `lh_sched` (interp.pasm) for the disabled-task-skip loop `$074C-$0772`. Dispatch: NOT a
new hook — `loop_hook` is ALREADY per-fetch in gameplay ($072E set in notest, it's what collapses
$0818), and fires on `$40==$074C`. Routed via `lh_gen: jmp lh_sched_pre` (size-neutral swap of
`jmp gm_memclr` — no loop_hook region growth, which is critical: the region is packed against
.org $F602). lh_sched scans current+1..15, skips enable-disabled tasks natively, hands the first
ENABLED task to interp at `$075C` (deeper $0774+ checks; a fail re-fetches $074C -> re-fires) or
`$07EA` at 16. Sets a4=a5+4 (for $075C's `move.w d0,(a4)`) and d0=found idx. BE reads via lhs_rdbe.
Placement: lh_sched_pre+main (79B) in the il_skip->$FA00 gap; lhs_rdbe (15B) in the $D1BF gap.
Behaviorally exact -> runs UNGATED (like $0818 collapse) so ESC=0 catches bugs directly.
RESULT: ESC=0 GREEN on all 4 triples; ESC=1 DIFF unchanged (zero added); interpreted 1842->1717
(-125/tick), $0740 region 246->121 (-51%). The residual 121 = ENABLED-task setups ($075C+ real
work) + the $0540/$0500 trap-handler re-entries (66+44/tick) -- the next scheduler targets.
NOTE: bank-$00 space is the binding constraint (biggest gaps: 86B@$F9AA, 46B@$D1BF). New bank-$00
loop_hook escapes must fit those or split; loop_hook itself can't grow (packed vs .org $F602).

### STEP D — Transpiler hardening (as it blocks real handlers).
Added (commit 7d09bc9): `move.l <long> -> -(An)` (push long) in store_long_from — unblocked $46DE
(coroutine sibling). $11752 also transpiles clean (31 instrs). Both are READY coroutine escapes
pending firing-validation (need an rte-reached triple + the STEP A charge cycle). Next limits you'll
hit: `move.l feeding branch`, `(An)+ dst feeding branch`, and linear-decode stall on
no-`rts`/external-jmp functions (give the decoder an explicit end bound for loop/coroutine bodies).

---

## 5. Tasks & memory
Tasks: #67 (~99% coverage, overarching), #70 (AOT table unify), #72 (ce4t never fires), #73 (`$AC`
exact-charge — STEP A, **CLOSED 2026-06-30: c172 shipped, commit 507d692**), #74 (closed, rts-class
misread), **#75 (scheduler — STEP C)**, #78 (closed, coroutine-dispatch resolution), **#79
(jmp-state/fire-finder — STEP B)**.
Memory: `rts-class-dispatch-nonfunctional.md` (corrected model + methodology lesson),
`coroutine-shells-low-value.md`, `escape-bank.md`, `aot-dispatch-table.md`, `transpiler-tool.md`.

## 6. Don't repeat these dead ends
- Don't grind rts-reached "leaf" escapes into the table — they can't fire (scheduler-dispatched).
- Don't trust `$07xx` memory counters — use HOOKTEST exec-hooks.
- Don't expect big/coroutine escapes to be zero-added until `$AC` is solved (STEP A).
- ce4t is dead weight (never fires); don't "re-validate" it with single-frame zero-added (passes
  only because it never runs).

**Recommended first action:** STEP A is DONE. Next: STEP B (fire-finder for more jmp-state escapes,
low-risk additive) and/or grind the next coroutine bodies via the STEP A recipe. Highest VALUE is
still STEP C (the ~246/tick scheduler), but it's the hardest.

---

## Session deltas (2026-06-30 pt.2, → `7d09bc9`) — STEPS A-D
- **STEP A (#73 CLOSED):** shipped `entry_c172` (commit 507d692, table 12->13), the FIRST coroutine
  escape. Resolved the $AC-charge anomaly: esc_ac_charge works; exact charge=35 (static); the
  residual $1401 is hardware-vblank timing, $AC-invariant (not chargeable). Recipe + memory updated.
- **STEP B (#79):** investigated — jmp-state surface beyond the shipped 11 is sparse; $CEB6/$D522
  catchable (from $D52C jmp(a0)) but reaches too rare to firing-validate; not shipped. Low ROI.
- **STEP C (#75 CLOSED):** shipped `lh_sched` (commit 1aaafb2) — native disabled-task-skip for the
  $074C scheduler scan via loop_hook. ESC=0 GREEN all triples; interpreted 1842->1717 (-125/tick),
  $0740 region 246->121. New memory: [[scheduler-escape-loophook]].
- **STEP D:** transpile.py `move.l -> -(An)` push-long (commit 7d09bc9), unblocks $46DE.

## Prior session deltas (→ `59f4b15`)
- Table 10 → 12: shipped `entry_d718`, `entry_d3f6` (jmp-state, validated firing, zero-added, GREEN).
- transpile.py: `movea.l (An),An` aliasing fix; `--table` rts `$42` bank-mask; `move-to-mem feeding
  branch` feature.
- lockstep_trap.py: HOOKTEST / GPPROF / PRED / STREAMWIN / ENTRYCLASS (reliable tooling).
- Corrected model: rts-class dispatch is non-functional in gameplay; ce4t never fires (false prior
  milestone); the bottleneck is the coroutine scheduler. Closed dead-end tasks #74; reopened #72.
