# Run-collapse: native `move.l (An)+,(An)+` block-copy idiom (NOT YET LANDED)

## What & why
The hottest remaining interpreted code in a gameplay GAME_TICK (≈56% of the ~442
interpreted PCs/tick after $08C2+$26A0 landed) is the **`$0015B4` unrolled block copy**:
255 consecutive `move.l (a0)+,(a1)+` ($22D8) ending in `rts` at `$0017B2` — a fixed
1020-byte copy. Cycle-wise it is the dominant cost: 255 × ~16.5k interp cyc ≈ **4.2M
cycles**, ~23× the whole SA-1 frame budget. Collapsing it is the single biggest win toward
realtime.

> **(corrected 2026-06-30:** the "single biggest win" line is a dated profiling snapshot. The
> current bottleneck assessment is the **coroutine scheduler + handler chains** (~1900
> interpreted 68K instr per GAME_TICK), not this block copy — see `MAIN_PLANNING_HANDOFF.md`.
> The collapse design below remains valid and is still **NOT YET LANDED**.)

`entry_15b4` (native escape) already handles the **`bsr $15B4`** call sites. But the run is
ALSO entered by **fall-through**: `$158E` does `lea …,a0 / lea $E00002,a1` then falls
straight into `$15B4` (no call) for its third copy. The call-hook can't intercept a
fall-through (or any mid-stream `jmp` entry). So that copy runs fully interpreted.

## Fix: collapse the run inside the live MOVE handler
All MOVE opcodes are dispatched to **`op_move_g`** (the specific handlers like
`op_movl_anp_anp` are DEAD — `move_dispatch_check` at interp.pasm:~256 catches `$1/$2/$3xxx`
first; the `cmp #$20D8 / jmp op_movl_anp_anp` at :575 is unreachable).

Detect a run of identical `move.l (An)+,(An)+` from PC (peek `$C1:PC` via `$56/$58`, valid
from the fetch), **bulk-copy all but the LAST long** (byte-wise via `readbyte`+`map_snes`,
byte-identical to per-instruction), advance PC/An, then `jmp inext` so the fetch re-dispatches
the final long to `op_move_g` NORMALLY — that way **flags are op_move_g's, never replicated**.
Validated correct in isolation (the only failure when tried inline was the code-shift, below).

## BLOCKER: bank-$00 is fully packed
`op_move_g` lives at `.org $FA00`, a region packed to overlap `.org $FC00` (`op_tst_g`@$FC83,
`op_suba_g`@$FCFD). Adding ~190 bytes there pushed handlers into the overlap and corrupted
`op_tst_g` → hang. The main `$8000–$D1ED` region is also full (code ends `$D1E9`, `.org $D1ED`
= entry_25110). So the collapse code can't be added inline.

## Plan to land (size-neutral redirect + reclaim dead space)
1. Change `move_dispatch_check`'s `jmp op_move_g` (:256) → `jmp mvc_check` (3→3 bytes,
   ZERO shift).
2. Reclaim space by DELETING the confirmed-dead specific MOVE handlers (`op_movl_anp_anp`
   @2817, `op_movl_anp_dn` @3425, the dead `cmp #$20D8/$3150` k4x checks at :572–577, etc.)
   — verify no *reachable* `jmp` survives (the k4x move checks are dead; keep non-move ones
   like `adda.w`). This frees ~80+ lines in the main region.
3. Put `mvc_check` in the reclaimed space. It is the block below, but: start with
   `mvc_check:` + `rep #$30`, and change every `jmp mvg_normal` / `beq mvg_bail` bail to
   target a local `mvc_bail: jmp op_move_g` (op_move_g redoes `rep #$30` + handles the lone
   move.l with flags).
4. Build → `tools/smoke_gameplay.py` (must stay OK) → tick-diff (`/tmp/wrap2.py`, must stay
   GREEN) → `tools/profile_nat.py 1` (the $15C0–$1780 band should drop to ~0; valid PCs
   442 → ~190). Alternative if reclaiming is too risky: a 4-byte `mvc_tramp: jml mvc_check`
   in bank $92 (escbank) — but that bank-crosses every MOVE; reclaiming is preferred.

## Validated collapse block (adapt bails to `jmp op_move_g` per step 3)
```
mvc_check:
    rep #$30
    lda $44
    and #$F1F8
    cmp #$20D8               ; move.l (An)+,(An)+ ?
    beq mvc_start
mvc_bail:
    jmp op_move_g            ; not a copy / R==1 / bank-wrap -> general handler (sets flags)
mvc_start:
    ldy #$0000
    lda [$56],y
    sta $96                  ; opcode word to match
    ldx #$0000               ; count of FOLLOWING identical longs (= R-1)
mvc_cnt:
    iny
    iny
    cpy #$0200               ; cap 256 longs (bounds the scan)
    bcs mvc_done
    lda [$56],y
    cmp $96
    bne mvc_done
    inx
    bra mvc_cnt
mvc_done:
    cpx #$0000
    beq mvc_bail             ; lone move.l -> normal path (sets flags)
    txa
    asl a
    asl a
    sta $9A                  ; bytes = (R-1)*4
    lda $44                  ; src An slot -> $90
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    sta $90
    jsr regdstA              ; X = dst An slot
    stx $92
    ldx $90                  ; wrap guard: src.lo16 + bytes crosses bank -> single long
    lda $00,x
    clc
    adc $9A
    bcs mvc_bail
    ldx $92
    lda $00,x
    clc
    adc $9A
    bcs mvc_bail
    ldx $90                  ; src setup + advance by bytes
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    clc
    adc $9A
    sta $00,x
    ldx $92                  ; dst setup + advance by bytes
    lda $02,x
    sta $5E
    lda $00,x
    sta $6A
    clc
    adc $9A
    sta $00,x
    lda $5E
    jsr map_snes             ; -> $C2 mode (0=$40 work / 1=$41 shadow / 2=noop), $6A = SNES off
    ldy #$0000
mvc_loop:
    jsr readbyte
    sta $50
    lda $C2
    beq mvc_work
    cmp #$0001
    bne mvc_skip
    ldx $6A
    sep #$20
    lda $50
    sta $410000,x
    rep #$20
    bra mvc_skip
mvc_work:
    ldx $6A
    sep #$20
    lda $50
    sta $400000,x
    rep #$20
mvc_skip:
    inc $54
    inc $6A
    iny
    cpy $9A
    bne mvc_loop
    lda $9A
    lsr a                    ; PC += (R-1)*2 -> lands on the LAST move.l
    clc
    adc $40
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext
```
