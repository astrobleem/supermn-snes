; =============================================================================
; spike24d98.pasm — hand-transpilation of Superman 68K leaf $24D98 (per-slot body)
; to 65816. The 68K source: timer-countdown/clamp over a 12-byte slot:
;   tst.l ($4,A1); beq skip            ; inactive -> skip
;   D0=id; D1=timer; sub.w delta,D1; tst.w D1; ble clear
;   move.w D1,($2,A1)                  ; store new timer
;   btst D0(id),flags; beq bitclear
;   bit set:   ($8)=$B4
;   bitclear:  if ($8)!=0: ($8)-=1  else: [trap] ($8)=$B4  (struct-effect only)
;   clear:     ($4)=0;($0)=0;($2)=0;($8)=0
;
; D1 notes (per TRANSPILER_DESIGN.md): the 68K `tst.w D1; ble` clears V, so the
; signed `<=0` test is just Z OR N -> 65816 `beq`/`bmi` after the subtract (no V).
; 16-bit values held in direct page / WRAM long-indexed (D2).
;
; Harness contract (WRAM, A1->slot mapped to a 16-byte record, base $7E2200):
;   +0 id(w) +2 timer(w) +4 active_lo(w) +6 active_hi(w) +8 f8(w) +12 delta(w) +14 flags(w)
;   count of vectors at $7E2000 (word). Routine processes each record in place.
; =============================================================================
.snes
INIDISP=$2100

.bank 0
.org $8000
reset:
    clc
    xce
    rep #$30
    ldx #$1fff
    txs
    sep #$20
    lda #$80
    sta INIDISP
    rep #$30
    lda #0
    sta $7E2000

main:
    lda $7E2000
    sta $00                ; vector count in DP $00 (Y/X are busy)
    beq main_done
    ldx #0                 ; byte offset = vector * 16
ploop:
    ; active = [+4].lo | [+6].hi
    lda $7E2204,x
    ora $7E2206,x
    beq slot_done          ; inactive -> unchanged
    ; D1 = timer - delta  (16-bit signed)
    lda $7E2202,x
    sec
    sbc $7E220C,x          ; A = timer - delta; N,Z reflect result (V unused, per tst.w)
    beq do_clear           ; ble: Z  (==0)
    bmi do_clear           ; ble: N  (<0)
    ; store path
    sta $7E2202,x          ; timer' = D1
    ; btst id of flags -> (flags >> id) & 1
    lda $7E2200,x          ; id
    tay                    ; Y = shift count
    lda $7E220E,x          ; flags
    cpy #0
    beq bt_done
bt_loop:
    lsr a
    dey
    bne bt_loop
bt_done:
    and #$0001
    beq bit_clear
    ; bit set -> f8 = $B4
    lda #$00B4
    sta $7E2208,x
    bra slot_done
bit_clear:
    lda $7E2208,x
    beq bc_zero
    dec a                  ; f8 -= 1
    sta $7E2208,x
    bra slot_done
bc_zero:
    lda #$00B4             ; trap path: struct-effect is f8 = $B4
    sta $7E2208,x
    bra slot_done
do_clear:
    lda #0
    sta $7E2200,x          ; id = 0
    sta $7E2202,x          ; timer = 0
    sta $7E2204,x          ; active lo = 0
    sta $7E2206,x          ; active hi = 0
    sta $7E2208,x          ; f8 = 0
slot_done:
    txa
    clc
    adc #16
    tax
    dec $00
    beq main_done
    jmp ploop
main_done:
    lda #0
    sta $7E2000            ; process the batch once (in-place); no re-decrement
    lda $7E2010
    inc a
    sta $7E2010            ; heartbeat
    jmp main

nmi:
    rti
irq:
    rti

.org $FFE0
.word $0000,$0000,irq,irq,$0000,nmi,reset,irq
.org $FFF0
.word $0000,$0000,irq,$0000,$0000,nmi,reset,irq
