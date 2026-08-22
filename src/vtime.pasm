.snes
; vtime.pasm -- isolated virtual-MC68000-cycle clock diagnostic bank.
;
; Packed at SA-1 $F2:8000 by tools/build_interp_rom.py.  The byte at $F2:8000
; is zero in normal builds, retaining the established $AC instruction timer.
; VTIME=1 only enables this staged interpreter-clock diagnostic.  It is not a
; production acceptance path: native/HLE span charging still has to migrate to
; this representation before the gate can be promoted.
;
; State is deliberately outside both the 2 KiB SA-1 IRAM/native stack and the
; arcade's mapped $40:0000-$3FFF work RAM.  $40:4000-$4027 is a diagnostic
; candidate selected by static-reference audit; a runtime canary and sustained
; cold-boot proof are still required before any production allocation claim.
; No save state predating this state has timing authority.

; Low byte only: bit 0 enables this diagnostic; bit 1 additionally disables
; every general gameplay-native dispatch gate and scheduler shortcut after the
; virtual clock has initialized. The latter is an interpreter-only correctness
; probe, not a performance mode: it lets the remaining unledgered native/HLE
; and scheduler spans take the path-sensitive per-fetch clock while their exact
; ledgers and due-boundary handoffs are being built.
VTIME_ENABLE=$F28000
VTIME_FLAG_ENABLED=$0001
VTIME_FLAG_INTERPRETER_ONLY=$0002
VTIME_FLAG_0818_INTERPRETER_FALLBACK=$0004
VT_MAGIC=$404000
VT_VALID=$404002
VT_COST=$404004             ; next completed instruction, in two-cycle units
VT_REMAIN_LO=$404006
VT_REMAIN_HI=$404008
VT_PHASE=$40400A            ; 0..5742, adds 50 per reload
VT_OVERSHOOT=$40400C
VT_OPCODE=$40400E
VT_CONDITION=$404010
VT_TMP=$404012
VT_NATIVE_PENDING=$404014  ; 1-based $025110 block ordinal; 0 means none
VT_NATIVE_CURRENT=$404016  ; native helper's current block ordinal
VT_DUE=$404018             ; a direct native charge crossed the deadline
VT_NATIVE_OWNER=$40401A    ; 3=$025110, 5=$02429C, 9=Stage-3 player ledger
VT_CLOCK_PHASE=$40401C     ; interval-start bucket 0..4; bit15=current +1 unit
VT_CLOCK_VALID=$40401E     ; phase-bucket migration/initialization sentinel
VT_INPUT_PENDING=$404020   ; next virtual-tick pad value after ordered delay
VT_INPUT_VALID=$404022     ; delayed-input self-initialization sentinel
VT_INPUT_LAST_RELEASE=$404024 ; low byte of `$41012B` seen by input_p1
VT_INPUT_SCRATCH=$404026   ; stable NMI pad sample during seqlock read
VT_OWNER_25110=$0003
VT_OWNER_2429C=$0005
VT_OWNER_STAGE3_PLAYER=$0009

VT_MAGIC_VALUE=$C71E
VT_BASE_LO=$1012            ; 69,650 two-cycle units = $0001:$1012
VT_BASE_HI=$0001
VT_FRACTION_INCREMENT=$0032
VT_FRACTION_DENOMINATOR=$166F
VT_CLOCK_INITIAL_PHASE=$0001
VT_CLOCK_VALID_VALUE=$5A17
VT_INPUT_VALID_VALUE=$49D1

    .org $8000
vtime_enable_byte:
    .db $00                  ; packer changes only this byte for VTIME=1 diagnostics

; Called through the VTIME-only choke gateway after the existing post-self-test
; `$072E` gate is armed. The bank-$00 caller owns the ordinary JSR frame; this
; helper has a real 24-bit JSL/RTL frame and must not discard it. Before `$072E`
; is armed the diagnostic preserves the ordinary choke return, avoiding new
; timing traffic during the RAM self-test. Virtual timing remains diagnostic-
; only until every native/HLE path is migrated.
    .org $8001
vtime_prepare_gateway:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_prepare_disabled
    ; Cold boot has an established instruction-count proof.  `$0734` alone
    ; arms when the sound ring becomes valid, which precedes construction of
    ; the arcade task contexts.  Arm the experimental cycle clock only after
    ; both the post-self-test pacing path and the emulated task mask exist;
    ; before that point retain the proven legacy boot cadence.
    lda $0734
    beq vtime_prepare_disabled
    lda $400002
    bne vtime_prepare_active
vtime_prepare_disabled:
    lda $072E              ; preserve the packed call site's replaced LDA
    rtl
vtime_prepare_active:
    phx
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    beq vtime_prepare_enforce_mode
    lda #VT_MAGIC_VALUE
    sta VT_MAGIC
    lda #$0001
    sta VT_VALID
    ; 65816 STZ has no long-address form.  These diagnostic words live in
    ; BW-RAM ($40:4000+), so use explicit long stores rather than silently
    ; truncating them to SA-1 IRAM absolute addresses.
    lda #$0000
    sta VT_PHASE
    sta VT_OVERSHOOT
    sta VT_NATIVE_PENDING
    sta VT_NATIVE_CURRENT
    sta VT_DUE
    sta VT_NATIVE_OWNER
.ifdef VTIME_IRQ_ENTRY_ACCOUNTING_FIX
    lda #VT_CLOCK_INITIAL_PHASE
    sta VT_CLOCK_PHASE
    lda #VT_CLOCK_VALID_VALUE
    sta VT_CLOCK_VALID
.endif
    jsr vtime_load_initial_deadline
vtime_prepare_enforce_mode:
    ; In the explicit interpreter-only diagnostic, disable the four existing
    ; gameplay/scheduler-native gates only *after* the proven boot/task-context
    ; boundary. Enforce the mode for both a newly initialized clock and a
    ; restored already-valid state; otherwise a declared ROM-migration probe
    ; can inherit stale armed gates from its old save state. This leaves boot
    ; unchanged and keeps every subsequently unledgered accelerated span on
    ; the interpreter's dynamic cycle path. Normal VTIME retains all gates and
    ; its selected ledgers.
    lda VTIME_ENABLE
    and #$00FF
    bit #VTIME_FLAG_INTERPRETER_ONLY
    beq vtime_prepare_have_state
    stz $071A
    stz $073A
    stz $0736              ; native scheduler select -> interpret original $075C
    stz $073C              ; native scheduler switch-in -> interpret original $0796
vtime_prepare_have_state:
    lda $44
    sta VT_OPCODE
    tax
    sep #$20
    lda $F10000,x            ; packed MAME CPU-000 static-cycle byte table
    rep #$20
    and #$00FF
    lsr a                    ; all CPU-000 table entries are even cycle counts
    sta VT_COST
    jsr vtime_dynamic_charge
    plx
    lda $072E              ; preserve the packed call site's replaced LDA
    rtl
vtime_prepare_gateway_end:

; MAME 0.287's MC68000 autovector acknowledge is synchronized to a ten-cycle
; VPA cadence.  All represented instruction costs are even, so retain the
; start of the current virtual-vblank interval as one of five odd phases:
; bucket 0..4 means cycle phase 1/3/5/7/9, and bit 15 says this interval is
; the 69,651-unit rather than 69,650-unit form.  The completed CPU phase is
; derived only when an IRQ is accepted from interval length minus the existing
; 32-bit countdown.  This deliberately keeps phase accounting out of the hot
; per-instruction consume path.
;
; Fresh VTIME arming uses the retained Stage-3 boundary calibration.  A
; checkpoint from the predecessor diagnostic has no bucket, so reconstruct
; its interval-start bucket once from the fractional reload phase.  The
; 69,650-unit base is divisible by five; only completed fractional carries
; affect that start phase.
;
; This migration loop is diagnostic-only and runs once.  It deliberately
; favors a small auditable implementation over adding a second packed table.
.ifdef VTIME_IRQ_ENTRY_ACCOUNTING_FIX
    .org $8200
vtime_clock_ensure:
    lda VT_CLOCK_VALID
    cmp #VT_CLOCK_VALID_VALUE
    bne vtime_clock_reconstruct
    rts
vtime_clock_reconstruct:
    phx
    phy
    lda #VT_CLOCK_INITIAL_PHASE
    sta VT_CLOCK_PHASE
    ldx #$0000              ; fractional phase at the current interval
    ldy #$0000              ; whether that interval has the extra unit
vtime_clock_reconstruct_loop:
    txa
    cmp VT_PHASE
    beq vtime_clock_reconstruct_found
    tya                     ; completed interval contributes only its carry
    clc
    adc VT_CLOCK_PHASE
    jsr vtime_mod5
    sta VT_CLOCK_PHASE
    txa
    clc
    adc #VT_FRACTION_INCREMENT
    cmp #VT_FRACTION_DENOMINATOR
    bcc vtime_clock_reconstruct_no_carry
    sbc #VT_FRACTION_DENOMINATOR
    tax
    ldy #$0001
    bra vtime_clock_reconstruct_loop
vtime_clock_reconstruct_no_carry:
    tax
    ldy #$0000
    bra vtime_clock_reconstruct_loop
vtime_clock_reconstruct_found:
    ; Y describes the current interval, not one already accumulated above.
    ; Encode its single extra unit in bit 15; elapsed work stays represented
    ; by VT_REMAIN and is reduced only at IRQ acceptance.
    tya
    beq vtime_clock_reconstruct_ready
    lda VT_CLOCK_PHASE
    ora #$8000
    sta VT_CLOCK_PHASE
vtime_clock_reconstruct_ready:
    lda #VT_CLOCK_VALID_VALUE
    sta VT_CLOCK_VALID
    ply
    plx
vtime_clock_ensure_done:
    rts

; Reduce an unsigned 16-bit value modulo five with a fixed 14-comparison
; ladder.  Every subtraction is a power-of-two multiple of five, so one pass
; leaves 0..4 without a data-dependent long division loop.
vtime_mod5:
    cmp #$A000
    bcc vtime_mod5_5000
    sbc #$A000
vtime_mod5_5000:
    cmp #$5000
    bcc vtime_mod5_2800
    sbc #$5000
vtime_mod5_2800:
    cmp #$2800
    bcc vtime_mod5_1400
    sbc #$2800
vtime_mod5_1400:
    cmp #$1400
    bcc vtime_mod5_0a00
    sbc #$1400
vtime_mod5_0a00:
    cmp #$0A00
    bcc vtime_mod5_0500
    sbc #$0A00
vtime_mod5_0500:
    cmp #$0500
    bcc vtime_mod5_0280
    sbc #$0500
vtime_mod5_0280:
    cmp #$0280
    bcc vtime_mod5_0140
    sbc #$0280
vtime_mod5_0140:
    cmp #$0140
    bcc vtime_mod5_00a0
    sbc #$0140
vtime_mod5_00a0:
    cmp #$00A0
    bcc vtime_mod5_0050
    sbc #$00A0
vtime_mod5_0050:
    cmp #$0050
    bcc vtime_mod5_0028
    sbc #$0050
vtime_mod5_0028:
    cmp #$0028
    bcc vtime_mod5_0014
    sbc #$0028
vtime_mod5_0014:
    cmp #$0014
    bcc vtime_mod5_000a
    sbc #$0014
vtime_mod5_000a:
    cmp #$000A
    bcc vtime_mod5_0005
    sbc #$000A
vtime_mod5_0005:
    cmp #$0005
    bcc vtime_mod5_done
    sbc #$0005
vtime_mod5_done:
    rts

; Advance the retained interval-start phase exactly once when a deadline is
; reloaded.  Base length is zero modulo five, so only the encoded +1 matters.
; Clear the flag here; vtime_load_next_deadline sets it again if the newly
; loaded interval owns a fractional carry.
vtime_clock_finish_interval:
    lda VT_CLOCK_PHASE
    bit #$8000
    beq vtime_clock_finish_no_extra
    and #$0007
    inc a
    cmp #$0005
    bcc vtime_clock_finish_ready
    sbc #$0005
    bra vtime_clock_finish_ready
vtime_clock_finish_no_extra:
    and #$0007
vtime_clock_finish_ready:
    sta VT_CLOCK_PHASE
    rts

; Return the completed CPU phase bucket in A without mutating the retained
; interval-start state.  Since 65536 == 1 (mod 5), the 32-bit remaining value
; reduces as low+high.  Current elapsed units are interval_extra-remaining
; modulo five because the 69,650-unit base itself is divisible by five.
vtime_clock_current_phase:
    lda VT_REMAIN_LO
    jsr vtime_mod5
    sta VT_TMP
    lda VT_REMAIN_HI
    clc
    adc VT_TMP
    jsr vtime_mod5
    sta VT_TMP
    lda VT_CLOCK_PHASE
    bit #$8000
    beq vtime_clock_current_no_extra
    and #$0007
    inc a
    bra vtime_clock_current_subtract
vtime_clock_current_no_extra:
    and #$0007
vtime_clock_current_subtract:
    clc
    adc #$0005
    sec
    sbc VT_TMP
    jsr vtime_mod5
    rts

; Predict whether the next fractional deadline owns the extra unit, record it
; in the interval-start word, then tail-enter the original compact loader.
; Keep this diagnostic-only extension in the free phase island: adding it to
; the tightly packed loader below $85A0 would overlap the pinned IRQ helper,
; which Poppy otherwise permits silently.
vtime_clock_load_next_deadline:
    lda VT_PHASE
    clc
    adc #VT_FRACTION_INCREMENT
    cmp #VT_FRACTION_DENOMINATOR
    bcc vtime_clock_load_next_tail
    lda VT_CLOCK_PHASE
    ora #$8000
    sta VT_CLOCK_PHASE
vtime_clock_load_next_tail:
    jmp vtime_load_next_deadline
.endif

; Convert a newly fetched opcode's static cost to the retained dynamic CPU-000
; outcomes that have direct trace coverage here: Bcc/DBcc, TRAP #n, MOVEM, and
; data-register shifts/rotates.  Native spans and general multiply/divide
; timing are intentionally not claimed by this diagnostic stage.
;
; Keep the fixed fetch gateway compact and put this variable-size decoder in
; the audited diagnostic slack below the player ledger.
    .org $B500
vtime_dynamic_charge:
    lda VT_OPCODE
    and #$FFF0
    cmp #$4E40
    bne vtime_dynamic_branch
    lda #$0011              ; TRAP #n total 34 cycles / 2
    sta VT_COST
    rts
vtime_dynamic_branch:
    lda VT_OPCODE
    and #$F000
    cmp #$6000
    bne vtime_dynamic_dbcc
    lda VT_OPCODE
    xba
    and #$000F
    cmp #$0002              ; BRA/BSR are fixed/static, Bcc begins at cc=2
    bcc vtime_dynamic_dbcc
    sta VT_CONDITION
    jsr vtime_condition_true
    sta VT_TMP               ; 1=taken, 0=not taken
    lda VT_OPCODE
    and #$00FF
    beq vtime_bcc_word
    lda VT_TMP
    bne vtime_dynamic_dbcc
    lda VT_COST              ; short Bcc not taken: 8 instead of table's 10
    dec a
    sta VT_COST
    rts
vtime_bcc_word:
    lda VT_TMP
    bne vtime_dynamic_dbcc
    lda VT_COST              ; word Bcc not taken: 12 instead of table's 10
    inc a
    sta VT_COST
    rts
vtime_dynamic_dbcc:
    lda VT_OPCODE
    and #$F0F8
    cmp #$50C8
    bne vtime_dynamic_movem
    lda VT_OPCODE
    xba
    and #$000F
    sta VT_CONDITION
    jsr vtime_condition_true
    beq vtime_dbcc_condition_false
    jmp vtime_dynamic_done   ; condition true exits at static 12 cycles
vtime_dbcc_condition_false:
    lda VT_OPCODE
    and #$0007
    asl a
.ifdef VTIME_DBCC_REGISTER_STRIDE_FIX
    asl a
.endif
    tax
    lda $00,x                ; pre-instruction low word of selected Dn
    dec a
    cmp #$FFFF
    beq vtime_dbcc_expired
    lda VT_COST              ; false/decrement-and-branch: 10, not static 12
    dec a
    sta VT_COST
    rts
vtime_dbcc_expired:
    lda VT_COST              ; false/expired exit: 14, not static 12
    inc a
    sta VT_COST
vtime_dynamic_movem:
    ; MOVEM uses a word-sized register-mask extension.  CPU-000 adds four
    ; cycles per word register or eight per long register beyond the static
    ; opcode-table base.  The fetch pointer at $56:$58 is still the current
    ; instruction address, so [$56],Y with Y=2 obtains that big-endian mask
    ; without touching the emulated PC or the current instruction's scratch.
    lda VT_OPCODE
    and #$FB80
    cmp #$4880
    bne vtime_dynamic_shift
    lda VT_OPCODE
    lsr a
    lsr a
    lsr a
    and #$0007
    cmp #$0002              ; modes 0/1 include EXT, not a legal MOVEM EA
    bcc vtime_dynamic_shift
    ldy #$0002
    lda [$56],y
    xba
    sta VT_TMP
    lda VT_OPCODE
    and #$0040
    beq vtime_movem_word
    ldx #$0004              ; long: eight cycles = four timer units/register
    bra vtime_movem_count
vtime_movem_word:
    ldx #$0002              ; word: four cycles = two timer units/register
vtime_movem_count:
    ldy #$0010
vtime_movem_loop:
    lda VT_TMP
    lsr a
    sta VT_TMP
    bcc vtime_movem_skip
    txa
    clc
    adc VT_COST
    sta VT_COST
vtime_movem_skip:
    dey
    bne vtime_movem_loop
    rts
vtime_dynamic_shift:
    ; Data-register AS/LS/ROX/RO forms add two cycles per shift count.  Memory
    ; shifts (ss=11) are static.  Register counts are Dn & $3f; immediate zero
    ; encodes eight.  One added CPU cycle pair is one timer unit.
    lda VT_OPCODE
    and #$F000
    cmp #$E000
    bne vtime_dynamic_done
    lda VT_OPCODE
    and #$00C0
    cmp #$00C0
    beq vtime_dynamic_done
    lda VT_OPCODE
    and #$0020
    beq vtime_shift_immediate
    lda VT_OPCODE
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    and #$003F
    bra vtime_shift_add
vtime_shift_immediate:
    lda VT_OPCODE
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #$0007
    bne vtime_shift_add
    lda #$0008
vtime_shift_add:
    clc
    adc VT_COST
    sta VT_COST
vtime_dynamic_done:
    rts

; Return A=1 iff the pre-instruction 68000 condition code in VT_CONDITION is
; true.  N/Z/V/C are their interpreter-owned nonzero/zero flags at $70/$60/
; $72/$6E.  X is intentionally not used so the caller's pushed decode X stays
; untouched.
vtime_condition_true:
    lda VT_CONDITION
    bne vtime_condition_not_t
    jmp vtime_condition_yes  ; T (far tail)
vtime_condition_not_t:
    cmp #$0001
    bne vtime_condition_not_f
    jmp vtime_condition_no   ; F (far tail)
vtime_condition_not_f:
    cmp #$0002
    beq vtime_condition_hi
    cmp #$0003
    beq vtime_condition_ls
    cmp #$0004
    beq vtime_condition_cc
    cmp #$0005
    beq vtime_condition_cs
    cmp #$0006
    beq vtime_condition_ne
    cmp #$0007
    beq vtime_condition_eq
    cmp #$0008
    beq vtime_condition_vc
    cmp #$0009
    beq vtime_condition_vs
    cmp #$000A
    beq vtime_condition_pl
    cmp #$000B
    beq vtime_condition_mi
    cmp #$000C
    beq vtime_condition_ge
    cmp #$000D
    beq vtime_condition_lt
    cmp #$000E
    beq vtime_condition_gt
    ; cc=15 LE
    lda $60
    bne vtime_condition_yes
    jmp vtime_condition_lt
vtime_condition_hi:
    lda $6E
    bne vtime_condition_no
    lda $60
    beq vtime_condition_yes
    bra vtime_condition_no
vtime_condition_ls:
    lda $6E
    bne vtime_condition_yes
    lda $60
    bne vtime_condition_yes
    bra vtime_condition_no
vtime_condition_cc:
    lda $6E
    beq vtime_condition_yes
    bra vtime_condition_no
vtime_condition_cs:
    lda $6E
    bne vtime_condition_yes
    bra vtime_condition_no
vtime_condition_ne:
    lda $60
    beq vtime_condition_yes
    bra vtime_condition_no
vtime_condition_eq:
    lda $60
    bne vtime_condition_yes
    bra vtime_condition_no
vtime_condition_vc:
    lda $72
    beq vtime_condition_yes
    bra vtime_condition_no
vtime_condition_vs:
    lda $72
    bne vtime_condition_yes
    bra vtime_condition_no
vtime_condition_pl:
    lda $70
    beq vtime_condition_yes
    bra vtime_condition_no
vtime_condition_mi:
    lda $70
    bne vtime_condition_yes
    bra vtime_condition_no
vtime_condition_ge:
    lda $70
    beq vtime_condition_ge_n_clear
    lda $72
    bne vtime_condition_yes
    bra vtime_condition_no
vtime_condition_ge_n_clear:
    lda $72
    beq vtime_condition_yes
    bra vtime_condition_no
vtime_condition_lt:
    lda $70
    beq vtime_condition_lt_n_clear
    lda $72
    beq vtime_condition_yes
    bra vtime_condition_no
vtime_condition_lt_n_clear:
    lda $72
    bne vtime_condition_yes
    bra vtime_condition_no
vtime_condition_gt:
    lda $60
    bne vtime_condition_no
    jmp vtime_condition_ge
vtime_condition_yes:
    lda #$0001
    rts
vtime_condition_no:
    lda #$0000
    rts
vtime_dynamic_helpers_end:

; Reached through the VTIME-only local top-of-iloop gateway after the existing
; `$072E` gate is armed. It consumes the cost prepared before the previous
; instruction. A=0 leaves Z set so the retained BNE falls through to the
; existing IRQ/pacing path; A=1 retains the ordinary BNE path.
    .org $8400
vtime_consume:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_consume_legacy
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_consume_legacy
    lda VT_VALID
    bne vtime_consume_virtual
vtime_consume_legacy:
    lda $AC                 ; exact legacy behavior while diagnostic is disabled
    dec a
    sta $AC
    rtl
vtime_consume_virtual:
    lda VT_DUE
    bne vtime_consume_due
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_consume_no_deadline
    lda VT_VALID
    beq vtime_consume_no_deadline
    lda VT_REMAIN_HI
    bne vtime_consume_high
    lda VT_REMAIN_LO
    cmp VT_COST
    bcc vtime_consume_expired
    beq vtime_consume_expired
vtime_consume_high:
    lda VT_REMAIN_LO
    sec
    sbc VT_COST
    sta VT_REMAIN_LO
    bcs vtime_consume_no_deadline
    lda VT_REMAIN_HI
    dec a
    sta VT_REMAIN_HI
vtime_consume_no_deadline:
    lda #$0001
    rtl
vtime_consume_expired:
    lda VT_COST
    sec
    sbc VT_REMAIN_LO
    sta VT_OVERSHOOT
    lda #$0001
    sta VT_DUE
vtime_consume_due:
    lda #$0000              ; Z=1 for the retained BNE irq check
    rtl
vtime_consume_end:

; Called through the retained $97:E5C0 campaign_irq_reload JSL.  Disabled
; mode exactly restores $AC=$7000.  Enabled mode advances the fractional
; two-cycle deadline from the previous hardware phase and applies the
; instruction's recorded overshoot once before returning to the old pending/VID
; frame path.  Overshoot belongs to the deadline that just expired: subtract
; it exactly once from the new deadline, then clear the staged instruction
; slot so the first post-reload fetch cannot consume it a second time.
    .org $8500
vtime_reload:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_reload_legacy
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_reload_legacy
    lda VT_VALID
    bne vtime_reload_virtual
vtime_reload_legacy:
    lda #$7000
    sta $AC
    rtl
vtime_reload_virtual:
.ifdef VTIME_IRQ_ENTRY_ACCOUNTING_FIX
    ; Preserve only an interval boundary phase.  This runs once per virtual
    ; vblank rather than once per interpreted instruction.
    jsr vtime_clock_ensure
    jsr vtime_clock_finish_interval
    jsr vtime_clock_load_next_deadline
.else
    jsr vtime_load_next_deadline
.endif
    lda VT_OVERSHOOT
    beq vtime_reload_clear
.ifdef VTIME_IRQ_ENTRY_ACCOUNTING_FIX
    sta VT_TMP
.else
    sta VT_COST
.endif
    lda VT_REMAIN_LO
    sec
.ifdef VTIME_IRQ_ENTRY_ACCOUNTING_FIX
    sbc VT_TMP
.else
    sbc VT_COST
.endif
    sta VT_REMAIN_LO
    bcs vtime_reload_clear
    lda VT_REMAIN_HI
    dec a
    sta VT_REMAIN_HI
vtime_reload_clear:
    lda #$0000
.ifdef VTIME_IRQ_ENTRY_ACCOUNTING_FIX
    sta VT_COST
.endif
    sta VT_OVERSHOOT
    sta VT_DUE
    sta VT_NATIVE_PENDING
    sta VT_NATIVE_OWNER
    lda #$7000              ; legacy/native charge quarantine until their migration
    sta $AC
    rtl
vtime_reload_end:

vtime_load_initial_deadline:
    lda #VT_BASE_LO
    sta VT_REMAIN_LO
    lda #VT_BASE_HI
    sta VT_REMAIN_HI
    rts

vtime_load_next_deadline:
    lda VT_PHASE
    clc
    adc #VT_FRACTION_INCREMENT
    cmp #VT_FRACTION_DENOMINATOR
    bcc vtime_reload_no_fraction_carry
    sec
    sbc #VT_FRACTION_DENOMINATOR
    sta VT_PHASE
    lda #VT_BASE_LO+$0001
    sta VT_REMAIN_LO
    lda #VT_BASE_HI
    sta VT_REMAIN_HI
    rts
vtime_reload_no_fraction_carry:
    sta VT_PHASE
    jmp vtime_load_initial_deadline
vtime_load_next_deadline_end:

; Called only by the VTIME pack-time hook in `take_irq`, after level 6 has
; actually been accepted.  VT_COST names the instruction already debited by
; the iloop consume immediately before irq_chk; when a pending interrupt was
; mask-blocked it must be discarded here rather than charged a second time.
; Derive that completed instruction's phase from the current interval start
; and remaining countdown, then clear its stale pipeline slot.  MAME's fixed
; 44-cycle entry core plus VPA synchronization maps completed cycle phases
; 1/3/5/7/9 to
; 27/26/25/29/28 two-cycle units; every result lands the first ISR fetch at
; cycle phase 5 (bucket 2).
;
; The normally impossible corner where either charge reaches the next virtual
; vblank is nevertheless kept coherent: reload that deadline, retain a new
; pending level-6 request, and run the same video-frame boundary used by the
; ordinary due path.  Production ROMs leave the bank-$00 hook as NOPs.
    .org $85A0
vtime_irq_enter:
.ifdef VTIME_IRQ_ENTRY_ACCOUNTING_FIX
    rep #$30
    lda VTIME_ENABLE
    beq vtime_irq_enter_disabled
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_irq_enter_disabled
    lda VT_VALID
    beq vtime_irq_enter_disabled
    jsr vtime_clock_ensure
    jsr vtime_clock_current_phase
    sta VT_TMP
    lda #$0000
    sta VT_COST
    lda #$001B              ; 27 - phase, wrapped into the range 25..29
    sec
    sbc VT_TMP
    cmp #$0019
    bcs vtime_irq_enter_charge
    clc
    adc #$0005
vtime_irq_enter_charge:
    jsr vtime_charge_units
    bcc vtime_irq_enter_disabled
    jsr vtime_irq_enter_reload_due
vtime_irq_enter_disabled:
    rtl
vtime_irq_enter_reload_due:
    jsl.l $F28500           ; vtime_reload (JSL because its public tail is RTL)
    lda #$0001
    sta $AA                 ; retain the newly crossed level-6 edge
    jsl.l $E98000           ; VID_FRAME, matching vtime_choke_due
    rts
.endif
vtime_irq_enter_end:

; $025110 is a bank-$97 native collision handler.  Its generated charge call
; precedes every original basic block, which means a block's dynamic terminal
; branch/DBcc outcome is available at the *next* charge.  Commit the previous
; block there, then leave the current block unexecuted if the virtual vblank
; deadline was crossed.  The generated tables are source-authenticated by
; tools/gen_vtime_esc3_charge_table.py and contain no arcade ROM bytes.
;
; Entry is a JSL from the VTIME-only bank-$97 gateway after the helper has
; PHP/PHA'd and that gateway has its own JSR frame.  The generated helper's
; JSR return residue is consequently at $0B,S after this routine's PHX: the
; gateway JSR contributes two bytes, JSL contributes three, and PHX contributes
; two.  65816 JSR pushes the final opcode byte, while the sparse table is keyed
; by the byte *after* the three-byte JSR, so increment the residue exactly once
; before lookup.
    .org $8600
vtime_esc3_charge:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_esc3_charge_disabled
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_esc3_charge_disabled
    lda VT_VALID
    beq vtime_esc3_charge_disabled
    lda VT_NATIVE_OWNER
    cmp #VT_OWNER_25110
    bne vtime_esc3_charge_owner_mismatch
    phx
    lda $0B,s
    inc a
    sec
    sbc #$8000
    bcc vtime_esc3_charge_missing_popx
    tax
    sep #$20
    lda $F29000,x            ; sparse return-PC -> one-based block ordinal
    beq vtime_esc3_charge_missing_popx_a8
    rep #$20
    and #$00FF
    sta VT_NATIVE_CURRENT
    plx
    lda VT_NATIVE_PENDING
    beq vtime_esc3_charge_first
    jsr vtime_esc3_charge_pending
    bcs vtime_esc3_charge_due
    bra vtime_esc3_charge_store_current
vtime_esc3_charge_first:
    lda VT_COST              ; complete the interpreted JSR that entered $25110
    beq vtime_esc3_charge_store_current
    jsr vtime_charge_units
    php
    lda #$0000              ; do not debit that JSR again at iloop
    sta VT_COST
    plp
    bcs vtime_esc3_charge_due
vtime_esc3_charge_store_current:
    lda VT_NATIVE_CURRENT
    sta VT_NATIVE_PENDING
    lda #$0002               ; enabled, deadline not crossed
    rtl
vtime_esc3_charge_due:
    lda #$0000
    sta VT_NATIVE_PENDING
    jsr vtime_esc3_set_current_pc
    lda #$0001               ; caller unwinds its JSR and JMLs inext
    rtl
vtime_esc3_charge_missing_popx_a8:
    rep #$20
vtime_esc3_charge_missing_popx:
    plx
vtime_esc3_charge_owner_mismatch:
    lda #$0000              ; fail closed to the legacy native charge path
    sta VT_VALID
vtime_esc3_charge_disabled:
    lda #$0000
    rtl

; Charge the previous native block with its generated static cost and the
; terminal post-state correction.  Every variable-cost instruction in this
; body is a terminal Bcc/DBcc (enforced by the table generator), so the
; current emulated CCR/Dn state is exactly the state after that instruction.
vtime_esc3_charge_pending:
    lda VT_NATIVE_PENDING
    beq vtime_esc3_charge_pending_none
    dec a
    tax
    sep #$20
    lda $F2AC00,x            ; static two-cycle-unit cost
    rep #$20
    and #$00FF
    sta VT_COST
    txa
    asl a
    tax
    lda $F2AF00,x            ; opcode bytes are big-endian in the generated table
    xba
    sta VT_OPCODE
    jsr vtime_dynamic_charge_post
    lda VT_COST
    jsr vtime_charge_units
    php
    lda #$0000
    sta VT_COST
    plp
vtime_esc3_charge_pending_none:
    rts

; The existing interpreter dynamic helper uses a DBcc pre-decrement register
; value.  Native deferred charging sees the value *after* the generated DBcc,
; so distinguish branch from expired exit from that post-state instead.
vtime_dynamic_charge_post:
    lda VT_OPCODE
    and #$F000
    cmp #$6000
    bne vtime_dynamic_charge_post_dbcc
    jmp vtime_dynamic_charge ; Bcc CCR is unchanged by the branch itself
vtime_dynamic_charge_post_dbcc:
    lda VT_OPCODE
    and #$F0F8
    cmp #$50C8
    bne vtime_dynamic_charge_post_done
    lda VT_OPCODE
    xba
    and #$000F
    sta VT_CONDITION
    jsr vtime_condition_true
    bne vtime_dynamic_charge_post_done
    lda VT_OPCODE
    and #$0007
    asl a
.ifdef VTIME_DBCC_REGISTER_STRIDE_FIX
    asl a
.endif
    tax
    lda $00,x                ; post-DBcc Dn.w
    cmp #$FFFF
    beq vtime_dynamic_charge_post_expired
    lda VT_COST             ; false/decrement-and-branch: 10, not static 12
    dec a
    sta VT_COST
    rts
vtime_dynamic_charge_post_expired:
    lda VT_COST              ; false/expired exit: 14, not static 12
    inc a
    sta VT_COST
vtime_dynamic_charge_post_done:
    rts

; A contains a positive two-cycle-unit cost.  C=1 means it crossed the
; hardware deadline; VT_DUE/VT_OVERSHOOT then let iloop take the retained IRQ
; path and reload against the real fractional vblank phase.
vtime_charge_units:
    sta VT_TMP
    lda VT_REMAIN_HI
    bne vtime_charge_units_high
    lda VT_REMAIN_LO
    cmp VT_TMP
    bcc vtime_charge_units_due
    beq vtime_charge_units_due
vtime_charge_units_high:
    lda VT_REMAIN_LO
    sec
    sbc VT_TMP
    sta VT_REMAIN_LO
    bcs vtime_charge_units_ok
    lda VT_REMAIN_HI
    dec a
    sta VT_REMAIN_HI
vtime_charge_units_ok:
    clc
    rts
vtime_charge_units_due:
    lda VT_TMP
    sec
    sbc VT_REMAIN_LO
    sta VT_OVERSHOOT
    lda #$0000
    sta VT_REMAIN_LO
    sta VT_REMAIN_HI
    lda #$0001
    sta VT_DUE
    ; Native/HLE gateways tail-enter `inext`.  The post-self-test `$0818`
    ; scheduler wait can immediately refetch itself through loop_hook and
    ; therefore bypass the fetch choke that normally observes VT_DUE.  Reuse
    ; the retained one-countdown IRQ entrance as a local bridge: the next
    ; iloop consumes this one, enters the established reload/pending path,
    ; and vtime_reload clears VT_DUE.  This is a delivery signal only, not a
    ; return to instruction-count timing.
    sta $AC
    sec
    rts

vtime_esc3_set_current_pc:
    lda VT_NATIVE_CURRENT
    dec a
    asl a
    tax
    lda $F2AD00,x            ; little-endian original low-16 PC
    sta $40
    lda #$0002
    sta $42
    rts

; Called only after entry_25110 has reproduced the original JSR stack push
; and accepted its native guard.  Do not touch VT_COST: it is the just-fetched
; JSR instruction and vtime_esc3_charge commits it at the first block seam.
    .org $8800
vtime_esc3_reset:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_esc3_reset_done
    lda #$0000
    sta VT_NATIVE_PENDING
    sta VT_NATIVE_CURRENT
    sta VT_DUE
    lda #VT_OWNER_25110
    sta VT_NATIVE_OWNER
vtime_esc3_reset_done:
    rtl

; The final generated block is an RTS and has no following charge site.  Its
; caller has already materialized the post-RTS PC/A7 before calling here, so
; a deadline crossing resumes at the correct return instruction boundary.
    .org $8820
vtime_esc3_finish:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_esc3_finish_disabled
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_esc3_finish_disabled
    lda VT_VALID
    beq vtime_esc3_finish_disabled
    lda VT_NATIVE_OWNER
    cmp #VT_OWNER_25110
    bne vtime_esc3_finish_disabled
    jsr vtime_esc3_charge_pending
    bcs vtime_esc3_finish_due
    lda #$0000
    sta VT_NATIVE_PENDING
    sta VT_NATIVE_OWNER
    lda #$0002
    rtl
vtime_esc3_finish_due:
    lda #$0000
    sta VT_NATIVE_PENDING
    lda #$0001
    rtl
vtime_esc3_finish_disabled:
    lda #$0000
    rtl

; VTIME-only bank-$F3 copy of the Stage-3 `$02429C` root.  Its generated
; prologue supplies a one-based exact original-block ordinal in A.  Unlike the
; sparse-return-address ledgers, this diagnostic copy owns every one of its 35
; charge sites directly.  Each child transfer flushes the completed parent
; block, publishes a genuine 68000 stack/PC state, clears this owner, and
; enters the interpreter.
    .org $8900
vtime_esc5_charge:
    rep #$30
    sta VT_NATIVE_CURRENT
    lda VTIME_ENABLE
    beq vtime_esc5_charge_disabled
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_esc5_charge_disabled
    lda VT_VALID
    beq vtime_esc5_charge_disabled
    lda VT_NATIVE_CURRENT
    beq vtime_esc5_charge_owner_mismatch
    cmp #$0024              ; exactly ordinals 1..35
    bcs vtime_esc5_charge_owner_mismatch
    lda VT_NATIVE_OWNER
    beq vtime_esc5_charge_claim_owner
    cmp #VT_OWNER_2429C
    bne vtime_esc5_charge_owner_mismatch
    bra vtime_esc5_charge_owner_ready
vtime_esc5_charge_claim_owner:
    lda VT_NATIVE_PENDING
    bne vtime_esc5_charge_owner_mismatch
    lda #VT_OWNER_2429C
    sta VT_NATIVE_OWNER
vtime_esc5_charge_owner_ready:
    lda VT_NATIVE_PENDING
    beq vtime_esc5_charge_first
    jsr vtime_esc5_charge_pending
    bcs vtime_esc5_charge_due
    bra vtime_esc5_charge_store_current
vtime_esc5_charge_first:
    lda VT_COST              ; complete the interpreted entry/return opcode
    beq vtime_esc5_charge_store_current
    jsr vtime_charge_units
    php
    lda #$0000
    sta VT_COST
    plp
    bcs vtime_esc5_charge_due
vtime_esc5_charge_store_current:
    lda VT_NATIVE_CURRENT
    sta VT_NATIVE_PENDING
    lda #$0002
    rtl
vtime_esc5_charge_due:
    jsr vtime_esc5_set_current_pc
    lda #$0000
    sta VT_NATIVE_PENDING
    sta VT_NATIVE_CURRENT
    sta VT_NATIVE_OWNER
    lda #$0001
    rtl
vtime_esc5_charge_owner_mismatch:
    lda #$0000              ; never silently mix native clock owners
    sta VT_VALID
vtime_esc5_charge_disabled:
    lda #$0000
    rtl

vtime_esc5_charge_pending:
    lda VT_NATIVE_PENDING
    beq vtime_esc5_charge_pending_none
    dec a
    tax
    sep #$20
    lda $F28C00,x
    rep #$20
    and #$00FF
    sta VT_COST
    txa
    asl a
    tax
    lda $F28C90,x
    xba
    sta VT_OPCODE
    jsr vtime_dynamic_charge_post
    lda VT_COST
    jsr vtime_charge_units
    php
    lda #$0000
    sta VT_COST
    plp
vtime_esc5_charge_pending_none:
    rts

vtime_esc5_set_current_pc:
    lda VT_NATIVE_CURRENT
    dec a
    asl a
    tax
    lda $F28C40,x
    sta $40
    lda #$0002
    sta $42
    rts

; The caller has already materialized the child/final PC and genuine 68000
; stack before reaching this boundary.  Clear the root owner on both outcomes
; so the interpreter can immediately reacquire the common per-fetch clock.
    .org $8B00
vtime_esc5_finish:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_esc5_finish_disabled
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_esc5_finish_disabled
    lda VT_VALID
    beq vtime_esc5_finish_disabled
    lda VT_NATIVE_OWNER
    cmp #VT_OWNER_2429C
    bne vtime_esc5_finish_disabled
    jsr vtime_esc5_charge_pending
    php
    lda #$0000
    sta VT_NATIVE_PENDING
    sta VT_NATIVE_CURRENT
    sta VT_NATIVE_OWNER
    plp
    bcs vtime_esc5_finish_due
    lda #$0002
    rtl
vtime_esc5_finish_due:
    lda #$0001
    rtl
vtime_esc5_finish_disabled:
    lda #$0000
    rtl

; Exact source-authenticated `$02429C` block metadata.  The diagnostic root
; passes ordinals directly, so no sparse return-address index is needed.
    .org $8C00
vtime_esc5_charge_cost:
    .incbin "vtime_esc5_charge_cost.bin"
    .org $8C40
vtime_esc5_charge_pc:
    .incbin "vtime_esc5_charge_pc.bin"
    .org $8C90
vtime_esc5_charge_terminal:
    .incbin "vtime_esc5_charge_terminal.bin"
    .org $8CD6
vtime_esc5_metadata_end:

; The six Stage-3 player handlers in bank $9F have an independently audited
; 83-block ledger.  Their charge calls are direct ``JSR`` instructions with a
; mandatory caller PHP.  The F2 routine therefore finds the generated return
; at $06,S after its PHX: two X bytes, three JSL bytes, then the original
; two-byte JSR residue (the caller PHP follows it).  As with $025110, the residue is the final
; opcode byte and must be incremented before sparse-table lookup.
;
; This remains diagnostic-only.  The packer routes exactly the source-checked
; player sites and their JSR/RTS handoffs here only when VTIME=1; all ordinary
; ROMs retain the established esc9_ac_charge instruction-count helper.
    .org $B100
vtime_esc9_charge:
    rep #$30
    lda VTIME_ENABLE
    bne vtime_esc9_charge_enabled
    jmp vtime_esc9_charge_disabled
vtime_esc9_charge_enabled:
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    beq vtime_esc9_charge_magic_ok
    jmp vtime_esc9_charge_disabled
vtime_esc9_charge_magic_ok:
    lda VT_VALID
    bne vtime_esc9_charge_valid
    jmp vtime_esc9_charge_disabled
vtime_esc9_charge_valid:
    phx
    lda $06,s
    inc a
    sec
    sbc #$BA00
    bcc vtime_esc9_charge_missing_popx
    tax
    sep #$20
    lda $F2BA00,x            ; sparse return-PC -> one-based block ordinal
    beq vtime_esc9_charge_missing_popx_a8
    rep #$20
    and #$00FF
    sta VT_NATIVE_CURRENT
    plx
    lda VT_NATIVE_OWNER
    beq vtime_esc9_charge_claim_owner
    cmp #VT_OWNER_STAGE3_PLAYER
    bne vtime_esc9_charge_owner_mismatch
    bra vtime_esc9_charge_owner_ready
vtime_esc9_charge_claim_owner:
    lda VT_NATIVE_PENDING
    bne vtime_esc9_charge_owner_mismatch
    lda #VT_OWNER_STAGE3_PLAYER
    sta VT_NATIVE_OWNER
vtime_esc9_charge_owner_ready:
    lda VT_NATIVE_PENDING
    beq vtime_esc9_charge_first
    jsr vtime_esc9_charge_pending
    bcs vtime_esc9_charge_due
    bra vtime_esc9_charge_store_current
vtime_esc9_charge_first:
    lda VT_COST              ; complete the interpreted BSR/JSR that entered
    beq vtime_esc9_charge_store_current
    jsr vtime_charge_units
    php
    lda #$0000              ; do not debit the entry call again at iloop
    sta VT_COST
    plp
    bcs vtime_esc9_charge_due
vtime_esc9_charge_store_current:
    lda VT_NATIVE_CURRENT
    sta VT_NATIVE_PENDING
    lda #$0002
    rtl
vtime_esc9_charge_due:
    lda #$0000
    sta VT_NATIVE_PENDING
    jsr vtime_esc9_set_current_pc
    lda #$0001
    rtl
vtime_esc9_charge_missing_popx_a8:
    rep #$20
vtime_esc9_charge_missing_popx:
    plx
vtime_esc9_charge_owner_mismatch:
    lda #$0000              ; never silently mix two native ledgers
    sta VT_VALID
vtime_esc9_charge_disabled:
    lda #$0000
    rtl

; Commit the preceding player block using the same dynamic Bcc/DBcc post-state
; rule as the collision ledger.  The generator rejects any other dynamic
; instruction before emitting these tables.
vtime_esc9_charge_pending:
    lda VT_NATIVE_PENDING
    beq vtime_esc9_charge_pending_none
    dec a
    tax
    sep #$20
    lda $F2FC80,x
    rep #$20
    and #$00FF
    sta VT_COST
    txa
    asl a
    tax
    lda $F2FD80,x
    xba
    sta VT_OPCODE
    jsr vtime_dynamic_charge_post
    lda VT_COST
    jsr vtime_charge_units
    php
    lda #$0000
    sta VT_COST
    plp
vtime_esc9_charge_pending_none:
    rts

vtime_esc9_set_current_pc:
    lda VT_NATIVE_CURRENT
    dec a
    asl a
    tax
    lda $F2FCD3,x
    sta $40
    lda #$0001
    sta $42
    rts

; Call this after a player-native terminal JSR handoff or its final RTS.  The
; source has already put the architectural post-call/post-RTS PC in $40:$42,
; so unlike the pre-block charge path a due result must preserve that PC.
    .org $B300
vtime_esc9_finish:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_esc9_finish_disabled
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_esc9_finish_disabled
    lda VT_VALID
    beq vtime_esc9_finish_disabled
    lda VT_NATIVE_OWNER
    cmp #VT_OWNER_STAGE3_PLAYER
    bne vtime_esc9_finish_disabled
    jsr vtime_esc9_charge_pending
    bcs vtime_esc9_finish_due
    lda #$0000
    sta VT_NATIVE_PENDING
    sta VT_NATIVE_OWNER
    lda #$0002
    rtl
vtime_esc9_finish_due:
    lda #$0000
    sta VT_NATIVE_PENDING
    lda #$0001
    rtl
vtime_esc9_finish_disabled:
    lda #$0000
    rtl

; `$0818` returns only after a real S-CPU/NMI video deadline.  In the VTIME
; diagnostic, deliver that external hardware deadline through the same pending
; IRQ path as a cycle-crossing instruction.  The ordinary pack leaves the
; caller's original five-byte `LDA #1 / STA $AC` sequence intact.
    .org $B400
vtime_paced_release:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_paced_release_legacy
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_paced_release_legacy
    lda VT_VALID
    beq vtime_paced_release_legacy
    lda #$0001
    sta VT_DUE
    ; Same bridge for the external `$0818` hardware-paced release: it can
    ; return directly into the self-refetching wait loop before choke runs.
    sta $AC
    rtl
vtime_paced_release_legacy:
    lda #$0001
    sta $AC
    rtl
vtime_paced_release_end:

; VTIME-only post-self-test fetch choke.  Its bank-$00 caller reuses the
; ordinary choke trampoline, so no new per-fetch traffic is introduced while
; `$072E` remains clear during the RAM self-test. Once the existing game gate
; is open, commit the previously prepared instruction, prepare the already
; fetched next instruction, and suppress the legacy instruction countdown.
; A crossed deadline rebuilds the old pending/video edge and returns A=0; the
; caller drops its JSR return and restarts `iloop` before that fetched opcode
; executes. Native/HLE coverage is deliberately still incomplete, so this is
; an opt-in clock-architecture diagnostic, not a production timing repair.
    .org $B480
vtime_choke_gateway:
    rep #$30
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    beq vtime_choke_have_magic
vtime_choke_prepare_only:
    ; The task-mask gate inside prepare retains legacy scheduling until the
    ; arcade contexts exist. Do not suppress `$AC` before that point.
    jsl.l $F28001
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_choke_continue
    ; The prepare call has just captured the instruction currently sitting at
    ; the fetch boundary.  Do not consume it until the *next* choke: it has to
    ; execute once first.  Start suppressing the legacy countdown only after
    ; a complete virtual-clock state now exists.
    lda VT_VALID
    beq vtime_choke_continue
    lda #$7000
    sta $AC
    lda #$0001
    rtl
vtime_choke_have_magic:
    lda VT_VALID
    beq vtime_choke_prepare_only
    jsl.l $F28400
    beq vtime_choke_due
    jsl.l $F28001
    lda #$7000
    sta $AC
vtime_choke_continue:
    lda #$0001
    rtl
vtime_choke_due:
    jsl.l $F28500
    lda #$0001
    sta $AA
    jsl.l $E98000          ; VID_FRAME: same old IRQ/pending video boundary
    lda #$0000
    rtl
vtime_choke_gateway_end:

; The bank-$00 MOVE.L run collapse (`mvc_check`) executes after the per-fetch
; prepare call and can consume hundreds of consecutive logical instructions
; without returning to the common clock. In the explicit interpreter-only
; diagnostic, decline that optimization before it changes registers, memory,
; PC, or CCR. Other modes re-materialize the two bank-$00 instructions replaced
; by the pack-time JML and resume at mvc_check's mask. The packer derives and
; patches the exact resume PC from interp.sym, then guards this source shape.
    .org $B4D1
vtime_mvc_gateway:
    rep #$30
    lda VTIME_ENABLE
    and #$00FF
    bit #VTIME_FLAG_INTERPRETER_ONLY
    bne vtime_mvc_interpret
    lda $44
    jml.l $0095F1         ; patched by packer from mvc_check + REP/LDA prefix
vtime_mvc_interpret:
    jml.l $00FA00         ; op_move_g: execute the already-prepared MOVE normally
vtime_mvc_gateway_end:

; VTIME-only P1 input bridge.  The 5A22's NMI serial reader publishes its
; completed real-pad sample at `$41:015E` under the word generation at
; `$41:015C`.  The ordinary renderer-safe `$0818` rendezvous publishes that
; sample to `$410000` for the following gameplay tick.  A virtual IRQ can start
; another tick before `$0818`, but exposing the newest NMI sample immediately
; advances input by one game tick.  Preserve the production ordering instead:
; if `$41012B` proves a real release occurred, use its mailbox publication;
; otherwise commit the sample held from the preceding P1 read.  Updating the
; shared mailbox here keeps the later coin read in the same `$003A92` input
; block coherent.  Ordinary ROMs retain the original input_p1/joy_read bytes
; and this island remains zero.
    .org $B740
vtime_input_p1_delayed:
.ifdef VTIME_INPUT_DELAYED_COMMIT_FIX
    rep #$30
    jsr vtime_input_ensure
    sep #$20
    lda.l $41012B
    cmp.l VT_INPUT_LAST_RELEASE
    beq vtime_input_no_release
    sta.l VT_INPUT_LAST_RELEASE
    rep #$20
    lda.l $410000
    bra vtime_input_committed
vtime_input_no_release:
    rep #$20
    lda.l VT_INPUT_PENDING
    sta.l $410000
vtime_input_committed:
    sta $66
    jsr vtime_input_read_staged
    sta.l VT_INPUT_PENDING
    lda $66
    rep #$30             ; replaces input_p1's following REP #$30
    rtl

; A predecessor checkpoint has no delayed-input fields.  Initialize them on
; first use without modifying architectural 68K work RAM or requiring a new
; fresh-boot lineage.
vtime_input_ensure:
    rep #$30
    lda.l VT_INPUT_VALID
    cmp #VT_INPUT_VALID_VALUE
    beq vtime_input_ensure_done
    lda.l $410000
    sta.l VT_INPUT_PENDING
    sep #$20
    lda.l $41012B
    sta.l VT_INPUT_LAST_RELEASE
    rep #$20
    lda #VT_INPUT_VALID_VALUE
    sta.l VT_INPUT_VALID
vtime_input_ensure_done:
    rts

; Read a stable completed NMI sample, then merge the current headless/harness
; injection word.  NMI is the sole seqlock writer.
vtime_input_read_staged:
    rep #$30
vtime_input_read_retry:
    lda.l $41015C
    bit #$0001
    bne vtime_input_read_retry
    pha
    lda.l $41015E
    sta.l VT_INPUT_SCRATCH
    pla
    cmp.l $41015C
    bne vtime_input_read_retry
    lda.l $410002
    ora.l VT_INPUT_SCRATCH
    rts
.endif
vtime_input_p1_delayed_end:

; Sparse native-block metadata.  Poppy's .incbin does not advance the logical
; program counter, hence each following .org is explicit and packer-audited.
    .org $9000
vtime_esc3_charge_index:
    .incbin "vtime_esc3_charge_index.bin"
    .org $AC00
vtime_esc3_charge_cost:
    .incbin "vtime_esc3_charge_cost.bin"
    .org $AD00
vtime_esc3_charge_pc:
    .incbin "vtime_esc3_charge_pc.bin"
    .org $AF00
vtime_esc3_charge_terminal:
    .incbin "vtime_esc3_charge_terminal.bin"
    .org $BA00
vtime_esc9_charge_index:
    .incbin "vtime_esc9_charge_index.bin"
    .org $FC80
vtime_esc9_charge_cost:
    .incbin "vtime_esc9_charge_cost.bin"
    .org $FCD3
vtime_esc9_charge_pc:
    .incbin "vtime_esc9_charge_pc.bin"
    .org $FD80
vtime_esc9_charge_terminal:
    .incbin "vtime_esc9_charge_terminal.bin"

; Future cross-bank native parent -> interpreter child handoff.  A deferred
; native block has already executed by the time a JSR/BSR/indirect transfer is
; about to leave its native owner.  Flush exactly that block before the caller
; exposes the architectural post-transfer PC and tail-enters the interpreter.
;
; C=0: no virtual deadline crossed; the caller may clear its native owner and
;      perform the ordinary handoff.
; C=1: the flush crossed a virtual deadline; VT_DUE is set and the caller must
;      preserve its already-materialized post-transfer PC, clear only its
;      pending block, and take the established IRQ path before executing the
;      child.  This helper deliberately has no PC/stack policy of its own.
;
; The two existing ledgers use distinct table layouts.  Dispatch through the
; current owner rather than treating a cross-bank transfer as an uncharged
; transition.  Unknown owners fail closed by invalidating the diagnostic; they
; may never silently run mixed-clock work.
    .org $FE40
vtime_native_handoff_to_interpreter:
    rep #$30
    lda VTIME_ENABLE
    beq vtime_native_handoff_none
    lda VT_MAGIC
    cmp #VT_MAGIC_VALUE
    bne vtime_native_handoff_none
    lda VT_VALID
    beq vtime_native_handoff_none
    lda VT_NATIVE_OWNER
    beq vtime_native_handoff_none
    cmp #VT_OWNER_25110
    beq vtime_native_handoff_esc3
    cmp #VT_OWNER_STAGE3_PLAYER
    beq vtime_native_handoff_esc9
    lda #$0000             ; STZ has no long form for BW-RAM workspace
    sta VT_VALID
    sec
    rtl
vtime_native_handoff_esc3:
    jsr vtime_esc3_charge_pending
    bra vtime_native_handoff_finish
vtime_native_handoff_esc9:
    jsr vtime_esc9_charge_pending
vtime_native_handoff_finish:
    bcs vtime_native_handoff_due
    lda #$0000
    sta VT_NATIVE_PENDING
    sta VT_NATIVE_CURRENT
    sta VT_NATIVE_OWNER
vtime_native_handoff_none:
    clc
    rtl
vtime_native_handoff_due:
    lda #$0000
    sta VT_NATIVE_PENDING
    sec
    rtl
vtime_native_handoff_to_interpreter_end:
vtime_image_end:
