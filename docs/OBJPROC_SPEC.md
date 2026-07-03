# OBJPROC_SPEC.md — the $01Cxxx object-processor: A1 spec (Phase 2.1)

A1 deliverable (2026-07-03, plan `enchanted-booping-summit.md` Phase 2.1). Method: chronological
fetch streams (`lockstep_trap.py STREAMDUMP=<f>`, new) on trip2500/ce4trip64/trip5000 + annotated
listing (`tools/disasm_region.py 01C980 01F2FF <streams...>`, new) + REGDUMP traps at the resume
PCs + pointer/table reads from wramA/ROM. **Headline: the "un-escapable dynamic coroutine" verdict
is SOFT — every dynamic edge on the hot path is enumerable or guardable. A2 is GO.**

## 1. Runtime architecture (what actually executes)

One scheduler task ("object manager") runs the whole cluster. Per gameplay tick it is switched in
TWICE (entries from `$000796` = the native entry_swin path), and each visit ends at a `trap #5`
yield sitting immediately before its own resume PC:

| visit | resume PC | yield (exit) | len (t25/ce4/t50) | role |
|---|---|---|---|---|
| 1 | **$01E7C0** | $01E7BE `trap #5` | 270/270/291 instr | render/update pass over the 8-object list |
| 2 | **$01D5F0** | $01D5EE `trap #5` | 9/45/12 instr | per-object physics step (jump-table state machine) |

**Zero object-proc instructions run on light/idle ticks** (trip1000/trip1040/span_quiet/heavy —
CP1). This is a gameplay/combat-class lever only (~491K cyc/tick on trip2500 at the 1.76K rate).

Inside visit 1 lives a HAND-ROLLED SYMMETRIC COROUTINE pair (independent of the scheduler):

- side B (render pass, $01E7xx): `$01E7A4 move.l a6,-(a7); move.l a7,$34c6(a5);
  movea.l $3506(a5),a6; jsr (a6)` → side A.
- side A (scan loop, $01C986): `ori #$700,sr` (ints off), **`lea $350a(a5),a7`** = a 4-byte private
  stack, `movea.l $34c6(a5),a6; movea.l -4(a6),a6; jsr (a6)` → back into side B at $01E7B0.
- **The `$3506(a5)` "resume slot" is NOT a variable — it is the top of that private stack**:
  side A's `jsr (a6)` at $01C99C pushes its return address $01C99E into $350A−4 = $3506(a5),
  which side B then loads. The resume-PC set is **{$01C99E} by construction** (it could only differ
  if side A suspended elsewhere; no other suspension point exists in the code).
- Side B on return: `movea.l $34c6(a5),a7` (drops side A's frame), `andi/ori sr`, `movea.l (a7)+,a6`
  — stack fully unwinds every round. No hidden coroutine state survives outside a5-relative slots.

## 2. Memory contract (concrete, verified on 3 triples)

a5 = $F00000 (work-RAM base) always. Task-context slots (a5-relative):

| slot | meaning | observed |
|---|---|---|
| $34c2 | side-A work counter (0 → skip $01CD46 path) | 0 |
| $34c6 | saved side-B a7 during ping-pong | $F00BDE (=list base−4) |
| $34ca | side-A a1 save (movem) | — |
| $3506 | private-stack top = side-A continuation | $01C99E |
| $350a | private stack base (lea → a7) | — |
| $3510 | renderer #2 ptr, re-latched each pass from $1c92(a5) | $00111A (interpreted sibling) |
| $3514 | **renderer #1 ptr, re-latched from $1c8e(a5)** | **$000D96 = entry_d96 NATIVE** |
| $3518 | OAM cursor base | $0204/$0224 |
| $351c | flag, cleared in epilogue | 0 |
| $351e | OAM cursor, += 2×count per object | $0228/$0248 |
| $3522 | 8-bit per-slot skip mask (btst d5) | — |
| $2a32/$2a4a/$2a4c/$2a4e/$2a50 | camera X / game mode / camera block / camY / camX-fine | — |
| $2932, $2930 | global state words (guards) | — |
| $31c2 | side-A 16-slot table, $30 bytes/slot, status byte first | **all 16 zero on every triple** |

**Top-object list**: 8 longword pointers at `a6−$20` where a6 = frame ctx = $F00C02 (REGDUMP) →
list at **$F00BE2** (base of the task's own stack region). Observed: exactly ONE live object,
always **$F002DA** (Superman). Physics visit (2) runs with a7 == a1 == the object — the task
context IS the object record.

**Object record layout** (offsets used by the hot path; record ≈ $68 bytes):

| off | field | off | field |
|---|---|---|---|
| $0 | type (physics table index ×2) | $36/$3c | latch pair (Y-prev, bpl/bmi guards) |
| $4,$6,$7,$a | status/flags bytes | $38/$3a | prev-X/prev-Y latches |
| $8 | visibility flags (bclr #0/#1) | $3e/$40 | screen X/Y (camera-relative store-back) |
| $e | anim frame countdown | $42/$44 | render origin X/Y |
| $10 | anim script ptr (ROM $01D9xx) | $46/$4a/$4e | sub-block ptrs a2/a3/a4 ($F03A74/$F03A84/$F037F4) |
| $14 | current frame gfx ptr (ROM $033xxx) | $5e | timer word (visit-2 tst) |
| $18 | attr word ($3000) | $66 | flag byte (guard) |
| $1a | hw-sprite count (=$12 → 18 sprites) | $2e/$32 | world X/Y |

Sub-blocks (a2/a3/a4): fields $2/$4 (X pair) and $6/$8 (Y pair) get the per-tick screen delta
added; these are the hardware-sprite strip headers the renderer consumes.

## 3. Dynamic-dispatch inventory — the whole point

| site | instr | hot? | target(s) | A2 treatment |
|---|---|---|---|---|
| $01C99C | jsr (a6) | ✓ | $01E7B0 (=[[$34c6]−4], structural) | inline the pair (§4) |
| $01E7AE | jsr (a6) | ✓ | $01C99E (=[$3506], structural) | inline the pair |
| $01F096 | jsr (a4) | ✓ | **[$3514] = $0D96 native entry_d96** | guard a4==$0D96 → direct `jml entry_d96`; else handoff-at-the-jsr (hle_12b6c v1 idiom) |
| $01D602 | jmp $1d606(pc,d7.w) | ✓ | table: {$01D71E ×?, $01D632} (types 0-7 read; ce4 type=8 → table ≥9 entries) | enumerate table to max type, bail out-of-range |
| $01D722 | jmp $1d726(pc,d7.w) | ✓ | {$01D864,$01D5EE,$01D758,$01D740,$01D7E6,$01D7CA,$01D7FA} | enumerate + bail |
| $01EE58 | jmp $1ee6c(pc,d7.w) | ✓ | anim-op table, **indexes DOWNWARD (negative op words)**; observed ops → $01EE72-class local + cold $02xxxx spawn ops ($0216C0/$024F40/$021FC8/$02553A/$022C94) | enumerate local ops; **bail on any $02xxxx target** |
| $01F0B2 | jmp $1f0b6(pc,d7.w) | ✓ | mode table {$01F166,$01F0BE,$01F0D4,$01F0EA} (4 modes, all local+tame) | transpile all 4 |
| $01CBEE/$01CC16/$01CD58 | jsr (a4) | cold | per-slot handlers of the $31c2 16-slot table | **never reached while table all-zero; bail guard = any status byte ≠ 0** |
| $01D202/$01D88C/$01DE00/$01E432 | jmp (a4) | cold | — | outside hot bodies; unreached |

trap#3 sites: error stubs after cold jmp(a4); unreached.

## 4. Hot-path per-segment spec (visit 1)

Resume $01E7C0 (from swin rte):
1. **$01E7C0**: `$3518 → $351e` (OAM cursor reset).
2. **Render loop** ($01E7CC..$01F192, ×8 slots, null-skip): guards (btst $3522 mask; tst.b
   $4/$66/$a(a0)); d1 = $2e(a0) − camX $2a32; d2 = $32(a0); conditional `sub camX from $5e(a0)`
   when $2932≠0; bclr #0,$8(a0); screen clamps (d1 vs $C..$174; d2 vs 0/$20 + d1 vs $38/$148 →
   re-set bclr); a2/a3 := $46/$4a(a0); type guards on $e(a2)/$e(a3) vs #$81/#$82; clr.b $6(a0);
   $e(a2)/$e(a3) ≤0 checks; d7 = d2−$a0 clamp; **store d1/d2 → $2e/$32(a0)**; ΔY = d2−$3a(a0) →
   a4 := $4e(a0), add ΔY to $6/$8 of a2,a3,a4; latch guards ($36/$3c bpl/bmi); ΔX = d1−$38(a0) →
   add to $2/$4 of a2,a3,a4; clr d0.
3. **Anim step** ($01EE3A): `subq.w #1,$e(a0)`; if expired: a4 := $10(a0) script; next word →
   $e(a0); >0 → **new-frame path** $01EFAA (d4 = (a4)+ longword → $14(a0); a4 → $10(a0); marshal);
   ≤0 → **op path** $01EE4E (op×2 → downward table; observed: set-$0(a0) op $01EE72, and t50's
   build-render-record op $01EF3E: a3 := $4e(a0), d7 = $36(a0), `bsr $1f1fe` → §6).
4. **Marshal + render call** ($01EFEC steady / $01EFAA new-frame): push {count−1 ($1a(a0)−1),
   frame ptr ($14(a0) or d4), X (d1−$42(a0)), Y (d2−$44(a0)), attr $18(a0), OAM cursor $351e(a5)}
   = 7 words; a4 := $3514(a5) (steady) or $1c8e(a5) (new-frame); **jsr (a4) → entry_d96**;
   `adda.w #$e,a7` (caller cleanup); $351e += 2×$1a(a0); bclr #1,$8(a0).
5. **Mode dispatch** ($01F0A8): $2a4a(a5) ×2 → table; mode 1 ($01F0BE): clr.b $7(a0); d1 −=
   $2a50; d2 −= $2a4e; a4 = $2a4c; → $01F170: btst/cmp guards on (a4) → **store d1/d2 → $3e/$40(a0)**.
6. dbra → next slot; **epilogue** $01F196: tst $351c → (≤0) $01F1AC: `$1c92 → $3510`,
   `$1c8e → $3514`, clr $351c; `bra $01E780`.
7. **Latch pass** ($01E780, ×8): $36→$3c, $2e→$38, $32→$3a per live object.
8. **Ping-pong** ($01E7A4, §1) → side A: restore a1 (movem $34ca), d3 = $34c4; **16-slot scan**
   $01C9AE (×16): status byte 0 → skip (+$30); then $34c2 test (0) → `bra $01C986` (top): save a1,
   ints off, private stack, jsr → side B $01E7B0: restore a7/sr/a6 → **YIELD $01E7BE**.

Visit 2 (resume $01D5F0): d0/d1 = $3e/$40(a1); d5 = $0(a1)×2 → physics-type table → (type 1)
$01D71E → table2 → $01D5EE yield [9 instr, no writes]; (type 8, ce4) $01D6A4: screen-code from
d0/d1 via ROM tables $36B2.w/$308E.w → $9(a1), Δ tables → `sub.l` $2e(a1)/$32(a1) (world-pos
update — the only visit-2 writes) → table2 → $01D740 `tst $5e(a1); bgt yield` / t50 $01D7CA
`movea $4e(a1),a4; tst $e(a4); beq yield`.

Reads outside the record: camera block, $2932, $3518/$351c/$3522, ROM tables/scripts.
Writes: object record fields above, a2/a3/a4 sub-blocks ($2/$4/$6/$8), $351e/$351c/$3510/$3514,
$34c6/$3506/$34ca (coroutine plumbing), SR. Plus entry_d96's own writes (already native, unchanged).

## 5. Renderer-call contract ($01F096)

7-word arg frame, pushed right-to-left, **caller cleanup** (`adda.w #$e,a7`), a4 = fn ptr:
`[a7+0]=OAM cursor, +2=attr, +4=Y, +6=X, +8..+B=frame ptr (long), +C=count−1`. Target $0D96 =
entry_d96 (native, bit-exact, batch-validated). The $3510/$1c92 sibling $00111A is NOT yet native
— it is NOT called on the observed hot path (only $3514/$1c8e is), but the new-frame path reads
$1c8e directly, so keep the guard on the VALUE, not the slot.

## 6. $01F1FE render-record builder (t50 anim-op path)

`bsr $1f1fe` with a3 = $4e(a0), a4 = script ptr, d7 = $36(a0), d1/d2 = screen X/Y:
writes (a3)+ sequence: $0001, Y−(a4)+ pair (swapped), X+(a4)+ pair, (a4)+ raw, $80−(a4)+ byte,
(a4)+ byte + $3520(a5) palette-bank add, clr.w terminator; rts. Straight-line, ~23 instrs,
transpiles as-is (rts returns within the body via the enclosing bsr — same-body link).

## 7. A2 v1 design + estimate

**Dispatch**: register $01E7C0 + $01D5F0 in xlat CORO_PCS (c172 precedent) → native bodies in
escbank3/4. Yields NEVER crossed: native exits set 68K PC = $01E7BE / $01D5EE and re-enter the
interp AT the trap (the standard bail edge).

**Body plan**: transpile-first (not hand-HLE) — the hot path is ~250 ordinary instructions once
the dynamic edges are handled; hand-rewrite stays the Phase-3 1.62× residual lever. Two transpiler
features unlock it (both reusable — the $00CBxx gateways are the same shapes):
- **F1 guarded direct-link for jsr (An)**: `cmp.l An,#$0D96`-equivalent guard → `jsl entry_d96`
  native-to-native; else marshal-state handoff at the jsr (hle_12b6c v1 idiom, correct for ANY An).
- **F2 pc-rel jump table**: transpile-time table read over the index domain (incl. negative,
  anim-op) → native bounds-check + dispatch to in-body labels; out-of-enumeration or $02xxxx
  target → bail. The inner jsr(a6) pair: transpile the ping-pong as a straight inline sequence
  (side B → side A scan → side B) with guards [$3506]==$01C99E and [[$34c6]−4]==$01E7B0; the
  private-stack pushes still performed (writes to $3506/$34c6 are part of the contract).

**Bail set (all → re-enter interp at the segment's current 68K PC):** any $31c2 slot byte ≠ 0;
$34c2 ≠ 0; physics type > enumerated max; anim-op outside enumerated local set (all $02xxxx spawn
ops bail); a4 guard miss at $01F096 (→ handoff, not bail); a2/a3 type-guard mismatches follow the
faithful branches (transpiled, no bail needed); mode table: all 4 targets transpiled.

**Win estimate**: 279–315 interp instr/tick × ~1.76K = **~490–555K cyc/tick on gameplay/combat
ticks**; native residual ≈ 250 × ~65cyc + entry_d96 (already spent) ≈ ~18K → **net ≈ −470–530K
= trip2500 2.44M → ~1.95M ≈ 10.9×** (single biggest campaign item). Light ticks: zero (CP1).
Effort: F1+F2 ~half session; bodies+validation ~1 session (gates: ESC=0 GREEN ×3 triples,
FULLDIFF identical-set, exit_dump at both yields, hle_span tick delta, smoke).

**Park rule**: projected saving ≫ 30K threshold → **GO for A2.** Risks: (a) table sizes — physics
type observed up to 8, enumerate to 16 and bail above; (b) the anim-op downward table needs exact
word-domain enumeration before codegen (30-min ROM read); (c) multi-object ticks (2+ live slots in
the 8-list) exercise no new code (loop is generic) but DO change per-tick cost/$AC charge —
--accharge co-requisite stands; (d) the 16-slot spawn table lights up in enemy waves → the bail
must be FIRST in side A's scan (cheap: 16 byte-tests are part of the body anyway; bail on first
non-zero).

## Regen commands (mechanical)

```
STREAMDUMP=<f> B1PC=0818 CHOKE=1 SWIN=1 SEL=1 GPPROF=1 ALLSTREAM=1 \
  python3 tools/lockstep_trap.py /tmp/supermn-scratch/<T> 2F60 1
python3 tools/disasm_region.py 01C980 01F2FF stream_t25.txt stream_ce4.txt stream_t50.txt
B1PC=01E7C6 REGDUMP=1 CHOKE=1 SWIN=1 SEL=1 python3 tools/lockstep_trap.py ... # live a6/a1
```
