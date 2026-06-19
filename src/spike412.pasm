; =============================================================================
; spike412.pasm — hand-transpilation of Superman 68K leaf $000412 to 65816.
; The 68K source (verified RNG, state=(176*state) mod 32749 @ $F0170E):
;     move.w ($170E,A5),D7 ; bne ; moveq #1,D7
;     muls.w #$00B0,D7      ; divs.w #$7FED,D7 ; swap D7 ; move.w D7,($170E,A5)
; Per TRANSPILER_DESIGN.md: signed muls/divs lowered to software helpers; the
; divide's compare/subtract uses the D1 carry convention (65816: C set = no
; borrow → BCC skips the subtract when rem < divisor). 32-bit values live in
; direct page (D2).
;
; Differential-harness contract (driven from WRAM by the MCP harness):
;   $7E2000  count N (word)         <- harness writes
;   $7E2200  inputs[]  (stride 4, word at +0)   <- harness writes
;   $7E2400  outputs[] (stride 4: rem@+0, quotient@+2)  -> harness reads
;   $7E2010  heartbeat (word, increments each main pass)
; Direct-page scratch: $00 in, $02 rem, $04 quot, $10/$12 ma, $14 mb,
;   $16/$18 prod/dividend/quotient, $1A divisor, $20 sign, $22 div-rem.
; =============================================================================
.snes
INIDISP=$2100

.bank 0
.org $8000
reset:
    clc
    xce                    ; native mode
    rep #$30               ; 16-bit A/X/Y
    ldx #$1fff
    txs
    sep #$20
    lda #$80
    sta INIDISP            ; force blank (headless)
    rep #$30
    lda #0
    sta $7E2000            ; count = 0 until harness loads it

main:
    lda $7E2000            ; N
    tay
    beq main_done
    ldx #0                 ; byte offset, stride 4
ploop:
    lda $7E2200,x          ; input word
    sta $00
    phx
    phy
    jsr rng_core           ; $00 -> rem $02, quotient $04
    ply
    plx
    lda $02
    sta $7E2400,x          ; remainder (= 68K stored word)
    lda $04
    sta $7E2402,x          ; quotient (= high word of D7 after swap)
    inx
    inx
    inx
    inx
    dey
    bne ploop
main_done:
    lda $7E2010
    inc a
    sta $7E2010            ; heartbeat
    bra main

; --- rng_core: one element. in=$00, out rem=$02, quotient=$04 ----------------
rng_core:
    rep #$30
    lda $00
    bne rc_nz
    lda #1                 ; x==0 -> x=1  (moveq #1,D7)
rc_nz:
    bpl rc_xpos            ; N flag = sign of x
    ldy #1                 ; x negative: sign=1, ma=|x|
    eor #$FFFF
    clc
    adc #1
    bra rc_store
rc_xpos:
    ldy #0
rc_store:
    sty $20                ; sign of x
    sta $10                ; ma_lo = |x|
    stz $12                ; ma_hi = 0
    lda #176
    sta $14                ; mb = 176
    jsr umul16             ; $16/$18 = |x| * 176
    lda $20
    beq rc_pp
    jsr neg32              ; apply x sign -> signed product (muls result)
rc_pp:
    lda $18                ; dividend sign
    bpl rc_dp
    ldy #1
    jsr neg32              ; |dividend|
    bra rc_ds
rc_dp:
    ldy #0
rc_ds:
    sty $20                ; sign of dividend (= sign of x)
    lda #32749
    sta $1A                ; divisor = $7FED
    jsr udiv32_16          ; quotient $16/$18, remainder $22
    lda $20
    beq rc_sp
    lda $16                ; signed: negate 16-bit quotient
    eor #$FFFF
    clc
    adc #1
    sta $16
    lda $22                ; and 16-bit remainder (sign of dividend)
    eor #$FFFF
    clc
    adc #1
    sta $22
rc_sp:
    lda $22
    sta $02                ; remainder = stored word
    lda $16
    sta $04                ; quotient
    rts

; --- umul16: unsigned 16x16->32.  ma=$10/$12, mb=$14 -> prod $16/$18 ----------
umul16:
    stz $16
    stz $18
    ldx #16
um_l:
    lsr $14                ; next multiplier bit -> carry
    bcc um_s
    clc
    lda $16
    adc $10
    sta $16
    lda $18
    adc $12
    sta $18
um_s:
    asl $10                ; ma <<= 1 (32-bit)
    rol $12
    dex
    bne um_l
    rts

; --- udiv32_16: unsigned 32/16 -> quotient(32) + rem(16). -------------------
; dividend $16/$18 (overwritten by quotient), divisor $1A, remainder -> $22.
; Exact for divisor magnitude <= 32768 (always true for divs.w).
udiv32_16:
    stz $22
    ldx #32
ud_l:
    asl $16                ; shift dividend left, MSB -> carry
    rol $18
    rol $22                ; rem = rem<<1 | carry
    lda $22
    cmp $1A                ; D1: C set if rem >= divisor (no borrow)
    bcc ud_s               ;     rem < divisor -> quotient bit 0
    sbc $1A                ; rem -= divisor (carry already set)
    sta $22
    inc $16                ; quotient bit 0 = 1
ud_s:
    dex
    bne ud_l
    rts

; --- neg32: $16/$18 = -$16/$18 (two's complement) ---------------------------
neg32:
    sec
    lda #0
    sbc $16
    sta $16
    lda #0
    sbc $18
    sta $18
    rts

nmi:
    rti
irq:
    rti

.org $FFE0
.word $0000,$0000,irq,irq,$0000,nmi,reset,irq
.org $FFF0
.word $0000,$0000,irq,$0000,$0000,nmi,reset,irq
