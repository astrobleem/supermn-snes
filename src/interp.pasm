; =============================================================================
; interp.pasm — 68000 INTERPRETER SPIKE on 65816 (increment 3: real memory).
; Pushes the interpreter through the reset handler's work-RAM TEST — which writes
; a pattern and reads it back, so it needs a real memory model + Z-flags + several
; addressing modes. Reaching $4008 (first opcode after the RAM test) proves real
; data-dependent 68K code runs correctly on real SNES.
;
; Memory: 68K work RAM $F0xxxx -> SNES bank $7F ($400000,x). Other writes no-op.
; 68K regs in direct page (D2): Dn @ $00+4n (lo@+0, hi@+2), An @ $20+4n.
; PC@$40, opcode@$44, scratch@$50/$52, log idx@$48, step@$4A (32-bit), stop@$4C,
; Z-flag@$60. 68K ROM slice at CPU $A000 (ROM off $2000); PC log -> $0800.
; =============================================================================
.snes
INIDISP=$2100
OBSEL=$2101
OAMADDL=$2102
BGMODE=$2105
BG1SC=$2107
BG12NBA=$210B
BG1HOFS=$210D
BG1VOFS=$210E
VMAIN=$2115
VMADDL=$2116
VMADDH=$2117
CGADD=$2121
CGDATA=$2122
TM=$212C
NMITIMEN=$4200
HVBJOY=$4212
MDMAEN=$420B
DMAP0=$4300
BBAD0=$4301
A1T0L=$4302
A1T0H=$4303
A1B0=$4304
DAS0L=$4305
DAS0H=$4306
SLICE_BASE=$3E00
; video subsystem entry points (src/video.pasm @ ROM bank $E9, file $290000)
VID_FRAME=$E98000
VID_INIT=$E98004
VIDTEST=$E98008
CPU5A22_VIDEO=$E9800B

.bank 0
.org $8000
reset:
    sep #$20             ; reset = 8-bit emulation on both CPUs; explicit for Poppy.
    lda #$FF
    sta $222A            ; CIWP: the SA-1 enables its OWN IRAM writes FIRST (the $2200
                         ; release zeroed it; only Sa1RegisterWrite handles $222A, so the
                         ; 5A22 can't set it). The interp's DP regfile / 65816 stack / vc /
                         ; ring all live in the SA-1's bank-$00 IRAM -> must be writable
                         ; before any of them is touched. (On the 5A22 $222A is ignored.)
    clc
    xce
    rep #$30
    ldx #$07ff           ; 65816 stack in bank-$00 low RAM. On the SA-1 (which runs the
    txs                  ; interp) bank $00 is 2KB IRAM ($0000-07FF); stack grows down
                         ; from $07FF, clear of DP ($00-FF), vc ($0200), ring ($0400).
    sep #$20
    lda #$80
    sta INIDISP
    rep #$30
    ; zero 68K work RAM $7F:0000-$7F:FFFF. The fast-start jumps straight to $4008
    ; and SKIPS the boot RAM-clear; MAME has all of F00000-F0FFFF = 0 at $4008
    ; (verified via oracle). Without this, the game reads Mesen's random power-on
    ; WRAM -> non-deterministic divergence + rare crash.
    lda #$0000
    ldx #$0000
wramclr:
    sta $400000,x        ; abs-long,x ($9F): clears 2 bytes
    inx
    inx
    bne wramclr          ; X: 0,2,..,FFFE -> wrap to 0 -> done (full 64KB)
    ldx #$F000           ; clear C-Chip shared RAM $41:F000-$41:FFFF (game scratch backing;
ccramclr:                ; else random power-on values break the start handshake readback)
    sta $410000,x
    inx
    inx
    bne ccramclr
    sta $000200          ; clear the virtual-controller test-injection word (A=0 here).
                         ; $00:0200 = interp-private WRAM (not 68K $7F / not video $7E).
    ; ---- TEST-MODE entry (optest.py differential harness) ----
    ; If ROM TESTFLAG ($00:F400) != 0 (baked into a test .sfc), enter single-step
    ; poll-idle. The harness pokes DP regs ($00-$3F), PC ($40/$42), flags
    ; (Z$60 C$6E N$70 V$72 X$A2), SR mask $7C and the work-RAM operand directly
    ; via write_memory after boot, then sets the go-flag $A0; test_idle then runs
    ; exactly one op (op baked in the ROM image) and returns. Production = TESTFLAG 0.
    lda $F400
    beq notest
    stz $AA              ; no pending IRQ (countdown/pending moved off $88/$8A; see iloop)
    lda #$7FFF
    sta $AC              ; huge countdown: no IRQ during the single step
    lda #$0001
    sta $7E              ; single-step ON
    stz $A0              ; go-flag clear
    jmp test_or_vid      ; TESTFLAG 1 -> single-step; TESTFLAG 2 -> video render test
notest:
    ; fast-start at $4008; preset ALL 68K regs to MAME's exact state there
    ; (ground truth, regs_at_4008.log): D0=$3FFE D6=$FFFF D7=$4
    ; A0=$F00000 A1=$F03FFE A5=$F00000 A7=$0 (rest 0).
    ldx #$003E
rclr:
    stz $00,x            ; zero D0-D7 ($00-$1F) + A0-A7 ($20-$3F)
    dex
    dex
    bpl rclr
    lda #$3FFE           ; D0 = $00003FFE
    sta $00
    lda #$FFFF           ; D6 = $0000FFFF
    sta $18
    lda #$0004           ; D7 = $00000004
    sta $1C
    lda #$00F0           ; A0 = $00F00000
    sta $22
    lda #$3FFE           ; A1 = $00F03FFE
    sta $24
    lda #$00F0
    sta $26
    lda #$00F0           ; A5 = $00F00000
    sta $36
    ; A7 = $00000000 (already zeroed)
    lda #$4008           ; PC = $4008
    sta $40
    stz $42
    stz $48
    stz $4A
    stz $4C
    stz $4E
    stz $7E              ; single-step test flag OFF in production
    stz $A2              ; X flag = 0
    stz $A4              ; USP low16  (Batch 8 MOVE USP)
    stz $A6              ; USP high16
    stz $A8              ; C-Chip phase: 0=GWK signature handshake, 1=input mailbox
    stz $60
    stz $62              ; last C-Chip command (selects response buffer)
    stz $6E              ; C flag
    stz $70              ; N flag
    stz $72              ; V flag
    lda #$0007
    sta $7C              ; SR interrupt mask = 7 (IRQs masked during boot)
    stz $AA              ; IRQ pending = 0 (moved off $88/$8A; see iloop note)
    lda #$7000
    sta $AC              ; vblank IRQ countdown, in INTERP INSTRUCTIONS. Real 68K is 8 MHz
                         ; (16MHz_XTAL/2, TMP68000N-8) @ 57.43 Hz = 13299 MAME instr/frame, BUT
                         ; this interp is instruction-paced and its busy-wait poll loops burn
                         ; many more instructions/frame than MAME's cycles, so the IRQ must not
                         ; fire mid-frame-work: $7000=28672 is the empirically-tuned budget
                         ; (13299 fires too early -> scheduler corruption -> boot crash @ $30).
    jsl VID_INIT         ; clear $7E shadow/staging, screen off, TM=0 (production)
    ; NOTE: a prior reset-time bootstrap of ($F00006)=$00F0000A was REMOVED. With the
    ; corrected VBLANK cadence ($8A=$7000), trap#1 ($0466) now runs to completion and
    ; itself sets ($F00006) and fabricates slot0's context at $F015C4 (A5=$00F00000),
    ; exactly as MAME does. The bootstrap made pre-trap#1 ISRs save the boot stack into
    ; ($F0000A) and corrupted the scheduler; leaving ($F00006)=0 lets $06D8's
    ; move.l A7,(A6=0) no-op (write to $000000 = ROM, ignored) until trap#1 sets it.

iloop:
    ; ---- Stage 2+: real SNES VBLANK rising edge -> PPU flush (video output).
    ; Independent of the simulated 68K IRQ below; just mirrors current shadow
    ; state to the PPU once per real frame. Interp is ~100x slower than realtime
    ; so it polls HVBJOY many times per frame and reliably catches the edge.
    ; (BISECT: iloop-top hook removed; flush now happens at the $8A reload below.)
    ; ---- vblank IRQ: countdown -> pending; take if mask < 6 (level-6 autovector $6C4)
    ; NOTE: countdown/pending live at $AC/$AA, NOT $8A/$88 -- op_bitop and two other
    ; handlers use $88/$8A/$8C as scratch, which would otherwise corrupt the frame pacing
    ; (a BTST setting $8A=mask -> spurious frame IRQ every bit-op). $AA/$AC are private.
    lda $AC
    dec a
    sta $AC
    bne irq_chk
    lda #$7000
    sta $AC              ; reload frame countdown = 28672 interp-instr/frame (see reset note)
    lda #$0001
    sta $AA              ; raise vblank pending
    jsl VID_FRAME        ; game-frame boundary: rebuild CGRAM from shadow + DMA
irq_chk:
    lda $AA
    beq irq_none
    lda $7C
    and #$0007
    cmp #$0006
    bcs irq_none         ; mask >= 6 -> blocked
    jsr take_irq
irq_none:
    ; ptr ($56,3 bytes) = $C10000 + PC  (full 512KB 68K image in HiROM $C1:0000+)
    lda $40
    sta $56              ; ptr low16 = PC low16
    lda $42
    cmp #$00F0           ; 68K work-RAM PC ($F0xxxx)? execute from SNES $7F bank
    bne ifetch_rom
    lda #$0040
    sta $58              ; ptr bank = $7F (work RAM); RAM-resident routines
    bra ifetch_go
ifetch_rom:
    clc
    adc #$00C1
    sta $58              ; ptr high byte = PC.high8 + $C1 (ROM image at $C1:0000)
ifetch_go:
    ldy #$0000
    lda [$56],y
    xba                  ; A = big-endian opcode word
    sta $44
    ; ring buffer: last 64 PCs (4 bytes each: low16,high16) at $0400; idx $48 wraps $100.
    ; ($0400 not $0800: on the SA-1, bank-$00 IRAM is 2KB and $0800 mirrors $0000=DP.)
    jsr dbg_fetch        ; ring-log 68K PC + optional debug-freeze (was inline ring write)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
nolog:
    ; CLR <ea> ($42xx, ss!=11) via the correct general handler. The specific CLR handlers
    ; no-op'd / omitted memory modes (op_clr = no-op for (An)+; no CLR -(An) handler at all),
    ; so e.g. CLR.W -(A7) at $8AC8 (pushing a 0 player-index arg) left a STALE stack word ->
    ; [A6+8]=$4290 garbage -> the credit/start routine took the P2-input path -> START masked.
    ; op_clr_g ea_write goes through writebyte/writeword, preserving $900xxx side effects, so
    ; (unlike op_move_g) this does not bypass the C-Chip boot handshake.
    lda $44
    jmp move_dispatch_check  ; route ALL MOVE/MOVEA ($1/$2/$3xxx) to op_move_g (complete
                             ; N/Z+V/C, ROM-aware read, video/C-Chip/work-RAM write); the
                             ; trace-driven specific MOVE handlers (incomplete flags) are now
                             ; dead. Non-MOVE returns to dsp_clr_cont. (Zero-shift jmp-swap.)
dsp_clr_cont:
    cmp #$4200
    bne dsp_notclr
    lda $44
    and #$00C0
    cmp #$00C0
    beq dsp_notclr       ; ss==11 -> $42C0 (illegal), not CLR
    jmp op_clr_g
dsp_notclr:
    ; ---- decode (bne-skip + jmp; reach unlimited) ----
    ; General ADDQ/SUBQ #d,<ea> FIRST (all modes/sizes), via the EA engine so every
    ; addressing mode incl. memory RMW is correct. $5xxx with ss(bits7-6)!=11 (ss==11
    ; is Scc/DBcc). bit8: 0=ADDQ, 1=SUBQ. The old loose-mask fast paths (op_addq_w/
    ; op_subq_w/op_addq_l/...) mis-decoded memory modes as Dn/An and are now dead.
    lda $44
    and #$F000
    cmp #$5000
    bne dsp_imm         ; not $5xxx -> try immediate ALU
    lda $44
    and #$00C0
    cmp #$00C0
    bne dsp_x0
    jmp dsp0           ; $5xxx ss==11 -> Scc/DBcc (main dispatch; far -> jmp)
dsp_x0:
    lda $44
    and #$0100
    bne dsp_subq
    jmp op_addq_g
dsp_subq:
    jmp op_subq_g
    ; General immediate ALU through the EA engine. SUBI $04xx / CMPI $0Cxx: no CCR/SR
    ; form, route all EA modes. ANDI $02xx / ORI $00xx: exclude ea(bits5-0)==$3C (the
    ; #imm-dest = ANDI/ORI #,CCR/SR, routed to the specific handlers later).
dsp_imm:
    lda $44
    and #$FF00
    cmp #$0400
    bne dsp_i1
    jmp op_subi_g
dsp_i1:
    cmp #$0C00
    bne dsp_i1b
    jmp op_cmpi_g
dsp_i1b:
    cmp #$0600
    bne dsp_i2
    jmp op_addi_g       ; route ADDI Dn too (the specific op_addi_b/w skipped X=C)
dsp_i2:
    cmp #$0200
    bne dsp_i3
    lda $44
    and #$003F
    cmp #$003C
    bne dsp_x1
    jmp dsp0
dsp_x1:
    jmp op_andi_g
dsp_i3:
    cmp #$0000
    bne dsp_or
    lda $44
    and #$003F
    cmp #$003C
    bne dsp_x2
    jmp dsp0
dsp_x2:
    jmp op_ori_g
    ; General OR ($8xxx): ss!=11 (DIVU/DIVS), and not dir1+ea-mode<2 (SBCD).
dsp_or:
    lda $44
    and #$F000
    cmp #$8000
    bne dsp0            ; REVERTED dsp_move/dsp_clr: routing MOVE/CLR through op_move_g/
                        ; op_clr_g bypassed specific handlers' side effects (e.g. the $900C01
                        ; C-Chip command write -> $62), breaking the boot handshake. MOVE/CLR
                        ; keep their specific handlers; their flag-setting is fixed in-place.
    lda $44
    and #$00C0
    cmp #$00C0
    beq dsp0            ; ss==11 -> DIVU/DIVS
    lda $44
    and #$0100
    beq dsp_or_go       ; dir0 -> OR
    lda $44
    and #$0038
    cmp #$0010
    bcc dsp0            ; dir1 ea-mode<2 -> SBCD/PACK
dsp_or_go:
    jmp op_or_g
    ; MOVE/MOVEA = $1xxx/$2xxx/$3xxx (the only ops in that range) -> general handler
    ; (op_move_g sets N/Z, V=C=0 for MOVE, none for MOVEA; the specific fast paths
    ; skipped flags). CLR = $42xx (ss!=11) -> op_clr_g (specifics mishandled some modes).
dsp_move:
    lda $44
    and #$C000
    bne dsp_clr
    lda $44
    and #$3000
    beq dsp_clr        ; $0xxx (immediate group) -> not MOVE
    jmp op_move_g
dsp_clr:
    lda $44
    and #$FF00
    cmp #$4200
    bne dsp0
    lda $44
    and #$00C0
    cmp #$00C0
    beq dsp0           ; $42C0 ss==11 -> not CLR (illegal on 68000)
    jmp op_clr_g
dsp0:
    lda $44
    and #$F1FF
    cmp #$41F9
    bne dsp0w
    jmp op_lea_abs
dsp0w: cmp #$41F8           ; lea (xxx).W,An  (abs-short; was unimplemented -> hang)
    bne k1
    jmp op_lea_abs_w
k1: cmp #$303C
    bne k2
    jmp op_movw_imm_dn
k2: cmp #$203C
    bne k3
    jmp op_movl_imm_dn
k3: cmp #$103C
    bne k4
    jmp op_movb_imm_dn
k4: lda $44
    cmp #$33FC
    bne k5
    jmp op_movw_imm_abs
k5: lda $44
    and #$F1F8
    cmp #$41E8
    bne k6
    jmp op_lea_d16
k6: cmp #$41D0
    bne k7
    jmp op_lea_an
k7: cmp #$2000
    bne k8
    jmp op_movl_dn
k8: cmp #$10C0
    bne k9
    jmp op_movb_dn_anp
k9: cmp #$1080
    bne k9b
    jmp op_movb_dn_an
k9b: cmp #$1100           ; move.b Dn,-(An)  (A masked $F1F8)
    bne k9c
    jmp op_movb_dn_predec
k9c: lda $44
    and #$F1FF
    cmp #$113C            ; move.b #imm,-(An)
    bne k9d
    jmp op_movb_imm_predec
k9d: lda $44
    and #$F1F8
    cmp #$1140            ; move.b Dn,(d16,An)
    bne k10
    jmp op_movb_dn_d16
k10: cmp #$B018
    bne k11
    jmp op_cmpb_anp
k11: cmp #$B010
    bne k12
    jmp op_cmpb_an
k12: lda $44
    and #$FFF8
    cmp #$4298
    bne k13
    jmp op_clr
k13: cmp #$51C8
    bne k14
    jmp op_dbra
k14: lda $44
    and #$F1C8
    cmp #$5180
    bne k15
    jmp op_subq_l
k15: lda $44
    and #$F138
    cmp #$E008
    bne k16
    jmp op_shift  ; (retired -> generic)
k16: lda $44
    cmp #$4EB9
    bne k17
    jmp op_jsr_abs
k17: cmp #$4E75
    bne k18
    jmp op_rts
k18: cmp #$0C39          ; cmpi.b #imm,(xxx).L  (.L = $0C39; .W would be $0C38)
    bne k18g
    jmp op_cmpib_abs
k18g: lda $44
    and #$FFC0
    cmp #$0C00           ; cmpi.b #imm,<ea> (byte size, any mode; abs.L caught above) -> general
    bne k18b
    jmp op_cmpib_g
k18b: lda $44              ; reload (k18g clobbered A; k18b/k19 need the raw opcode)
    pha
    and #$FFF8
    cmp #$0C00           ; cmpi.b #imm,Dn  ($0C00|Dn)
    bne k18b2
    pla
    jmp op_cmpi_b_dn
k18b2: cmp #$0C80          ; cmpi.l #imm,Dn  ($0C80|Dn)
    bne k18c
    pla
    jmp op_cmpi_l_dn
k18c: pla
k19: and #$F1FF
    cmp #$317C
    bne k20
    jmp op_movw_imm_d16
k20: lda $44
    and #$FF00
    cmp #$6100
    bne k23
    jmp op_bsr
k23: cmp #$6000
    bne k23b
    jmp op_bra
k23b: and #$F000             ; any other $6xxx (incl bne/beq) -> generic Bcc
    cmp #$6000
    bne k24
    jmp op_bcc
k24: lda $44
    and #$F1FF
    cmp #$313C            ; move.w #imm,-(An)  (push word)
    bne k24b
    jmp op_movw_imm_pre
k24b: lda $44
    and #$F1F8
    cmp #$3100            ; move.w Dn,-(An)
    bne k24b2
    jmp op_movw_dn_predec
k24b2: cmp #$3128          ; move.w (d16,An),-(An)
    bne k24c
    jmp op_movw_d16_predec
k24c: lda $44
    and #$F1FF
k25: cmp #$D1FC           ; adda.l #imm,An
    bne k26
    jmp op_adda_l
k26: cmp #$D0FC           ; adda.w #imm,An
    bne k27
    jmp op_adda_w
k27: lda $44
    and #$F1F8
    cmp #$3028            ; move.w (d16,An),Dn
    bne k28
    jmp op_movw_d16_dn
k28: cmp #$3140           ; move.w Dn,(d16,An)
    bne k29
    jmp op_movw_dn_d16
k29: cmp #$10D0           ; move.b (An),(An)+   (I/O-aware src)
    bne k30
    jmp op_movb_an_anp
k30: lda $44
    and #$FFF8
    cmp #$4240            ; clr.w Dn
    bne k31
    jmp op_clrw_dn
k31: cmp #$13C0           ; move.b Dn,(xxx).L   (command-port aware)
    bne k32
    jmp op_movb_dn_abs
k32: lda $44
    cmp #$13FC            ; move.b #imm,(xxx).L (I/O no-op write)
    bne k33
    jmp op_movb_imm_abs
k33: cmp #$4E71           ; nop
    bne k34
    jmp op_nop
k34: cmp #$4EBA           ; jsr (d16,PC)
    bne k35
    jmp op_jsr_pcrel
k35: lda $44
    and #$F1FF
    cmp #$1039            ; move.b (xxx).L,Dn
    bne k36
    jmp op_movb_abs_dn
k36: lda $44
    and #$F1F8
    cmp #$8000            ; or.b Dn,Dn
    bne k37
    jmp op_or_b
k37: lda $44
    and #$F1C8
    cmp #$E108            ; lsl.b #cnt,Dn
    bne k38
    jmp op_shift  ; (retired -> generic)
k38: lda $44
    and #$FFF8
    cmp #$0200            ; andi.b #imm,Dn
    bne k39
    jmp op_andi_b
k39: lda $44
    and #$F1FF
    cmp #$41FA            ; lea (d16,PC),An
    bne k40
    jmp op_lea_pc
k40: cmp #$217C            ; move.l #imm,(d16,An)
    bne k41
    jmp op_movl_imm_d16
k41: lda $44
    and #$F1F8
    cmp #$D0C0            ; adda.w Dn,An
    bne k42
    jmp op_adda_w_dn
k42: cmp #$3150            ; move.w (An),(d16,An)
    bne k43
    jmp op_movw_an_d16
k43: cmp #$20D8            ; move.l (An)+,(An)+
    bne k44
    jmp op_movl_anp_anp
k44: lda $44
    and #$FFF8
    cmp #$0240            ; andi.w #imm,Dn
    bne k45
    jmp op_andi_w
k45: cmp #$0828            ; btst #imm,(d16,An)
    bne k46
    jmp op_btst_imm_d16
k46: cmp #$42A8            ; clr.w (d16,An)
    bne k47
    jmp op_clrw_d16
k47: lda $44
    cmp #$4879            ; pea (xxx).L
    bne k47b
    jmp op_pea
k47b: pha
    and #$FFF8
    cmp #$4868            ; pea (d16,An)
    bne k47c
    pla
    jmp op_pea_d16
k47c: pla
k48: lda $44
    and #$F1C8
    cmp #$E148            ; lsl.w #cnt,Dn
    bne k49
    jmp op_shift  ; (retired -> generic)
k49: cmp #$5140            ; subq.w #data,Dn
    bne k50
    jmp op_subq_w
k50: lda $44
    and #$FFF8
    cmp #$4E50            ; link An,#imm16
    bne k51
    jmp op_link
k51: cmp #$4E58            ; unlk An
    bne k52
    jmp op_unlk
k52: cmp #$48E0            ; movem.l <list>,-(An)
    bne k52d
    jmp op_movem_pre
k52d: cmp #$48E8           ; movem.l <list>,(d16,An)  (was unimplemented -> hang)
    bne k52w
    jmp op_movem_d16_store
k52w: cmp #$48A0           ; movem.w <list>,-(An)
    bne k53
    jmp op_movem_w_pre
k53: cmp #$4CD8            ; movem.l (An)+,<list>
    bne k53w
    jmp op_movem_post
k53w: cmp #$4C98           ; movem.w (An)+,<list>
    bne k53d
    jmp op_movem_w_post
k53d: cmp #$4CE8           ; movem.l (d16,An),<list>  (was unimplemented -> hang)
    bne k54
    jmp op_movem_d16
k54: lda $44
    and #$F1F8
    cmp #$2068            ; movea.l (d16,An),An  (frame/stack -> direct $7F)
    bne k55
    jmp op_movea_l_d16
k55: cmp #$3018            ; move.w (An)+,Dn  (ROM-aware src)
    bne k55b
    jmp op_movw_anp_dn
k55b: cmp #$3098           ; move.w (An)+,(An)  (ROM-aware src, gated dst)
    bne k56
    jmp op_movw_anp_an
k56: cmp #$2058            ; movea.l (An)+,An  (ROM-aware src)
    bne k57
    jmp op_movea_l_anp
k57: cmp #$2018            ; move.l (An)+,Dn  (ROM-aware src)
    bne k58
    jmp op_movl_anp_dn
k58: cmp #$81A8            ; or.l Dn,(d16,An)  (long opmode 110; work RAM dest)
    bne k59
    jmp op_or_l_d16
k59: lda $44
    and #$F1FF
    cmp #$10FC            ; move.b #imm,(An)+
    bne k60
    jmp op_movb_imm_anp
k60: lda $44
    and #$F1F8
    cmp #$10D8            ; move.b (An)+,(An)+  (ROM-aware src)
    bne k61
    jmp op_movb_anp_anp
k61: cmp #$1000            ; move.b Dn,Dn
    bne k62
    jmp op_movb_dn_dn
k62: lda $44
    and #$FF00
    cmp #$0600            ; ADDI #imm,<ea> family ($06xx)?
    bne k62m
    lda $44
    and #$0038            ; mode field (bits 5-3)
    cmp #$0010            ; mode >= 2 (memory EA) -> general handler; mode 0/1 -> specific
    bcc k62m
    jmp op_addi_g
k62m: lda $44
    and #$FFF8
    cmp #$0600            ; addi.b #imm,Dn
    bne k63
    jmp op_addi_b
k63: cmp #$0440            ; subi.w #imm,Dn
    bne k64
    jmp op_subi_w
k64: lda $44
    and #$FF00
    cmp #$4A00            ; $4Axx = TST/TAS group?
    bne k64x
    lda $44
    and #$00C0
    cmp #$00C0            ; size 11 = TAS (not TST) -> skip
    beq k64x
    jmp op_tst_g          ; general TST.B/W/L <ea> (all modes, incl Dn)
k64x: lda $44
    and #$FFF8           ; restore the masked opcode for the checks below
    cmp #$4A40            ; tst.w Dn
    bne k64b
    jmp op_tst_w
k64b: cmp #$4A80           ; tst.l Dn
    bne k65
    jmp op_tst_l
k65: cmp #$4218            ; clr.b (An)+
    bne k65w
    jmp op_clrb_anp
k65w: pha
    and #$FFF8
    cmp #$4258            ; clr.w (An)+
    bne k65w2
    pla
    jmp op_clrw_anp
k65w2: cmp #$4210          ; clr.b (An)
    bne k65x
    pla
    jmp op_clrb_an
k65x: pla
k66: lda $44
    and #$F1F8
    cmp #$2148            ; move.l An,(d16,An)
    bne k66b
    jmp op_movl_an_d16
k66b: cmp #$2140           ; move.l Dn,(d16,An)
    bne k67
    jmp op_movl_dn_d16
k67: lda $44
    and #$FFF8
    cmp #$0800            ; btst #imm,Dn
    bne k68
    jmp op_btst_imm_dn
k68: lda $44
    and #$F1F8
    cmp #$8040            ; or.w Dn,Dn  (opmode 001)
    bne k68b
    jmp op_or_w
k68b: cmp #$8068           ; or.w (d16,An),Dn
    bne k69
    jmp op_or_w_d16
k69: lda $44
    and #$F1FF
    cmp #$1179            ; move.b (xxx).L,(d16,An)
    bne k70
    jmp op_movb_abs_d16
k70: lda $44
    and #$F1F8
    cmp #$1010            ; move.b (An),Dn  (I/O/ROM-aware src)
    bne k71
    jmp op_movb_an_dn
k71: cmp #$D1C0            ; adda.l Dn,An
    bne k72
    jmp op_adda_l_dn
k72: cmp #$2150            ; move.l (An),(d16,An)  (ROM-aware src)
    bne k73
    jmp op_movl_an_d16dst
k73: lda $44
    cmp #$0C79            ; cmpi.w #imm,(xxx).L
    bne k74
    jmp op_cmpiw_abs
k74: lda $44
    and #$FFF8
    cmp #$4280            ; clr.l Dn
    bne k75
    jmp op_clrl_dn
k75: cmp #$4268            ; clr.w (d16,An)  (reuse clrw handler)
    bne k76
    jmp op_clrw_d16
k76: cmp #$0C68            ; cmpi.w #imm,(d16,An)
    bne k77
    jmp op_cmpiw_d16
k77: cmp #$0628            ; addi.b #imm,(d16,An)
    bne k78
    jmp op_addib_d16
k78: lda $44
    and #$F1F8
    cmp #$B068            ; cmp.w (d16,An),Dn
    bne k79
    jmp op_cmpw_d16_dn
k79: lda $44
    and #$F1F8
    cmp #$1028            ; move.b (d16,An),Dn
    bne k80
    jmp op_movb_d16_dn
k80: cmp #$0100            ; btst Dn,Dn  (dynamic)
    bne k81
    jmp op_btst_dn_dn
k81: cmp #$3080            ; move.w Dn,(An)
    bne k82
    jmp op_movw_dn_an
k82: lda $44
    and #$FFF8
    cmp #$0640            ; addi.w #imm,Dn
    bne k83
    jmp op_addi_w
k83: lda $44
    cmp #$4EF9            ; jmp (xxx).L
    bne k84
    jmp op_jmp_abs
k84: pha
    and #$FFF8
    cmp #$4EE8            ; jmp (d16,An)  ($4EE8|An)
    bne k84j
    pla
    jmp op_jmp_d16_an
k84j: pla
    cmp #$007C            ; ori #imm,SR
    bne k85
    jmp op_ori_sr
k85: cmp #$027C            ; andi #imm,SR
    bne k86
    jmp op_andi_sr
k86: cmp #$46FC            ; move #imm,SR
    bne k86a
    jmp op_move_imm_sr
k86a: cmp #$003C           ; ori #imm,CCR
    bne k86b
    jmp op_ori_ccr
k86b: cmp #$023C           ; andi #imm,CCR
    bne k86c
    jmp op_andi_ccr
k86c: cmp #$0A3C           ; eori #imm,CCR
    bne k86d
    jmp op_eori_ccr
k86d: cmp #$0A7C           ; eori #imm,SR
    bne k87
    jmp op_eori_sr
k87: cmp #$4E73            ; rte
    bne k87b
    jmp op_rte
k87b: cmp #$4CF9           ; movem.l (xxx).L,<list>
    bne k87c
    jmp op_movem_abs
k87c: lda $44
    and #$FFF0
    cmp #$4E40            ; TRAP #n
    bne k89
    jmp op_trap
k89: lda $44
    and #$F1FF
    cmp #$117C            ; move.b #imm,(d16,An)
    bne k90
    jmp op_movb_imm_d16
k90: cmp #$213C           ; move.l #imm,-(An)
    bne k90b
    jmp op_movl_imm_pre
k90b: lda $44
    and #$F1F8
    cmp #$3010            ; move.w (An),Dn
    bne k91
    jmp op_movw_an_dn
k91: lda $44
    and #$F1F8
    cmp #$3000            ; move.w Dn,Dn
    bne k92
    jmp op_movw_dn_dn
k92: cmp #$01C0           ; bset Dn,Dn  (0000 rrr 111 000 RRR -> base $01C0)
    bne k94
    jmp op_bset_dn_dn
    ; (retired k93 add.w Dn,Dn -> op_add_w; $D040 now flows to generic op_add)
k94: cmp #$2180           ; move.l Dn,(d8,An,Xn)
    bne k94b
    jmp op_movl_dn_idx
k94b: cmp #$41F0          ; lea (d8,An,Xn),An
    bne k95
    jmp op_lea_idx
k95: cmp #$2188           ; move.l An,(d8,An,Xn)
    bne k96
    jmp op_movl_an_idx
k96: cmp #$2070           ; movea.l (d8,An,Xn),An
    bne k97
    jmp op_movea_l_idx
k97: cmp #$2128           ; move.l (d16,An),-(An)  (src (d16,An)=101 -> $2128)
    bne k97m
    jmp op_movl_d16_pre
k97m: pha
    and #$F1F8
    cmp #$2028           ; move.l (d16,An),Dn
    bne k97n
    pla
    jmp op_movl_d16_dn
k97n: pla
k98: pha
    and #$F1F0
    cmp #$2100           ; move.l Dn/An,-(An)  (register push)
    bne k98b
    pla
    jmp op_movl_reg_pre
k98b: pla
    cmp #$2110           ; move.l (An),-(An)
    bne k99
    jmp op_movl_an_pre
k99: lda $44
    and #$FFF8
    cmp #$0040           ; ori.w #imm,Dn
    bne k100
    jmp op_ori_w_dn
k100: cmp #$4840          ; swap Dn
    bne k101
    jmp op_swap
k101: lda $44
    and #$F1F8
    cmp #$1168            ; move.b (d16,An),(d16,An)
    bne k101w
    jmp op_movb_d16_d16
k101w: cmp #$3168           ; move.w (d16,An),(d16,An)
    bne k102
    jmp op_movw_d16_d16
k102: cmp #$2088           ; move.l An,(An)
    bne k103
    jmp op_movl_an_an
k103: cmp #$2010           ; move.l (An),Dn
    bne k104
    jmp op_movl_an_dn
k104: cmp #$2008           ; move.l An,Dn
    bne k105
    jmp op_movl_an2dn
k105: cmp #$2050           ; movea.l (An),An
    bne k106
    jmp op_movea_l_an
k106: cmp #$1018           ; move.b (An)+,Dn
    bne k107
    jmp op_movb_anp_dn
k107: cmp #$30C0           ; move.w Dn,(An)+
    bne k108
    jmp op_movw_dn_anp
k108: cmp #$3120           ; move.w -(An),-(An)
    bne k109
    jmp op_movw_pre_pre
k109: cmp #$9058           ; sub.w (An)+,Dn
    bne k110
    jmp op_subw_anp_dn
k110: lda $44
    and #$F1FF
    cmp #$30FC            ; move.w #imm,(An)+
    bne k110d
    jmp op_movw_imm_anp
    ; muls.w/divs.w #imm (formerly k110b/k110c -> op_muls_w/op_divs_w) retired:
    ; #imm now falls through to the generic op_muls/op_divs (kmul/kdivs), which
    ; handle every EA mode and trap on DIVS #0. op_muls_w/op_divs_w are dead.
k110d: lda $44
    and #$F1F8
    cmp #$2080           ; move.l Dn,(An)
    bne k113
    jmp op_movl_dn_an
k113: lda $44
    and #$FFF8
    cmp #$33C0            ; move.w Dn,(xxx).L
    bne k114
    jmp op_movw_dn_abs
k114: cmp #$4200           ; clr.b Dn
    bne k115
    jmp op_clrb_dn
k115: cmp #$4228           ; clr.b (d16,An)
    bne k116
    jmp op_clrb_d16
k116: cmp #$4260           ; clr.w -(An)
    bne k117
    jmp op_clrw_pre
k117: cmp #$4A28           ; tst.b (d16,An)
    bne k118
    jmp op_tstb_d16
k118: cmp #$4A68           ; tst.w (d16,An)
    bne k119
    jmp op_tstw_d16
k119: cmp #$4880           ; ext.w Dn
    bne k120
    jmp op_ext_w
k120: cmp #$4E90           ; jsr (An)
    bne k121
    jmp op_jsr_an
k121: cmp #$0C40           ; cmpi.w #imm,Dn
    bne k122
    jmp op_cmpiw_dn
k122: cmp #$0000           ; ori.b #imm,Dn
    bne k123
    jmp op_orib_dn
k123: cmp #$0010           ; ori.b #imm,(An)
    bne k124
    jmp op_orib_an
k124: cmp #$0880           ; bclr #imm,Dn
    bne k125
    jmp op_bclr_imm_dn
k125: lda $44
    and #$F1C8
    cmp #$5040            ; addq.w #data,Dn
    bne k126
    jmp op_addq_w
k126: cmp #$5088           ; addq.l #data,An
    bne k127
    jmp op_addq_l
k127: lda $44             ; ($F1C8 from k125 can't distinguish the full mode field)
    and #$F1F8
    cmp #$5068           ; addq.w #data,(d16,An)
    bne k127b
    jmp op_addq_w_d16
k127b: cmp #$5168          ; subq.w #data,(d16,An)
    bne k127c
    jmp op_subq_w_d16
k127c: lda $44
    and #$F1C8
k129: cmp #$E140           ; asl.w #cnt,Dn (== lsl.w for left)
    bne k130
    jmp op_shift  ; (retired -> generic)
k130: lda $44
    cmp #$4A79            ; tst.w (xxx).L
    bne k131
    jmp op_tstw_abs
k131: cmp #$0839           ; btst #imm,(xxx).L
    bne k132
    jmp op_btst_imm_abs
k132: cmp #$23FC           ; move.l #imm,(xxx).L
    bne k133
    jmp op_movl_imm_abs
k133: lda $44
    and #$F1F8
    cmp #$B1F0            ; cmpa.l (d8,An,Xn),An  (dest-An bits 11-9 masked -> $B1F0)
    bne k134
    jmp op_cmpa_l_idx
k134: cmp #$2170           ; move.l (d8,An,Xn),(d16,An)
    bne k135
    jmp op_movl_idx_d16
k135: cmp #$0168           ; bchg Dn,(d16,An)
    bne k136
    jmp op_bchg_dn_d16
k136: cmp #$E0A8           ; lsr.l Dn,Dn (register count)
    bne k137
    jmp op_shift  ; (retired -> generic)
k137: lda $44
    and #$FFF8
    cmp #$0070           ; ori.w #imm,(d8,An,Xn)
    bne k138
    jmp op_ori_w_idx
k138: lda $44
    and #$F100
    cmp #$7000            ; moveq #data8,Dn
    bne k139
    jmp op_moveq
k139: lda $44
    and #$FFC0
    cmp #$4600            ; not.b <ea>
    bne k140
    jmp op_not
k140: cmp #$4640            ; not.w <ea>
    bne k141
    jmp op_not
k141: cmp #$4680            ; not.l <ea>
    bne k141a
    jmp op_not
k141a: lda $44
    and #$F1F8
    cmp #$C100            ; abcd Dy,Dx (reg)
    bne k141b
    jmp op_abcd
k141b: cmp #$C108            ; abcd -(Ay),-(Ax) (mem)
    bne k141c
    jmp op_abcd
k141c: cmp #$8100            ; sbcd Dy,Dx (reg)
    bne k141d
    jmp op_sbcd
k141d: cmp #$8108            ; sbcd -(Ay),-(Ax) (mem)
    bne k141e
    jmp op_sbcd
k141e: lda $44
    and #$FFC0
    cmp #$4800            ; nbcd <ea>
    bne k142
    jmp op_nbcd
k142: lda $44
    and #$F1C0
    cmp #$C000            ; and.b <ea>,Dn
    bne k143
    jmp op_and
k143: cmp #$C040            ; and.w <ea>,Dn
    bne k144
    jmp op_and
k144: cmp #$C080            ; and.l <ea>,Dn
    bne k145
    jmp op_and
k145: cmp #$C100            ; and.b Dn,<ea>
    bne k146
    jmp op_and
k146: cmp #$C140            ; and.w Dn,<ea>
    bne k147
    jmp op_and
k147: cmp #$C180            ; and.l Dn,<ea>
    bne k147a
    jmp op_and
k147a: lda $44
    and #$F1F8
    cmp #$B108            ; cmpm.b (Ay)+,(Ax)+
    bne k147b
    jmp op_cmpm
k147b: cmp #$B148            ; cmpm.w
    bne k147c
    jmp op_cmpm
k147c: cmp #$B188            ; cmpm.l
    bne k147d
    jmp op_cmpm
k147d: lda $44
    and #$F1C0
    cmp #$B0C0            ; cmpa.w <ea>,An
    bne k147e
    jmp op_cmpa
k147e: cmp #$B1C0            ; cmpa.l <ea>,An
    bne k148
    jmp op_cmpa
k148: cmp #$B100            ; eor.b Dn,<ea>
    bne k149
    jmp op_eor
k149: cmp #$B140            ; eor.w Dn,<ea>
    bne k150
    jmp op_eor
k150: cmp #$B180            ; eor.l Dn,<ea>
    bne k151
    jmp op_eor
k151: lda $44
    and #$FFC0
    cmp #$0A00            ; eori.b #imm,<ea>
    bne k152
    jmp op_eori
k152: cmp #$0A40            ; eori.w #imm,<ea>
    bne k153
    jmp op_eori
k153: cmp #$0A80            ; eori.l #imm,<ea>
    bne k153a
    jmp op_eori
k153a: lda $44
    and #$F138
    cmp #$D100            ; addx.b Dy,Dx (reg)
    bne k153b
    jmp op_addx
k153b: cmp #$D140            ; addx.w (reg)
    bne k153c
    jmp op_addx
k153c: cmp #$D180            ; addx.l (reg)
    bne k153d
    jmp op_addx
k153d: cmp #$D108            ; addx.b -(Ay),-(Ax) (mem)
    bne k153e
    jmp op_addx
k153e: cmp #$D148            ; addx.w (mem)
    bne k153f
    jmp op_addx
k153f: cmp #$D188            ; addx.l (mem)
    bne k153g
    jmp op_addx
k153g: cmp #$9100            ; subx.b Dy,Dx (reg)
    bne k153h
    jmp op_subx
k153h: cmp #$9140
    bne k153i
    jmp op_subx
k153i: cmp #$9180
    bne k153j
    jmp op_subx
k153j: cmp #$9108            ; subx.b -(Ay),-(Ax) (mem)
    bne k153k
    jmp op_subx
k153k: cmp #$9148
    bne k153l
    jmp op_subx
k153l: cmp #$9188
    bne k153m
    jmp op_subx
k153m: lda $44
    and #$FFC0
    cmp #$4000            ; negx.b <ea>
    bne k153n
    jmp op_negx
k153n: cmp #$4040            ; negx.w
    bne k153o
    jmp op_negx
k153o: cmp #$4080            ; negx.l
    bne k154
    jmp op_negx
k154: lda $44
    and #$F1C0
    cmp #$D000            ; add.b <ea>,Dn
    bne k155
    jmp op_add
k155: cmp #$D040            ; add.w <ea>,Dn
    bne k156
    jmp op_add
k156: cmp #$D080            ; add.l <ea>,Dn
    bne k157
    jmp op_add
k157: cmp #$D100            ; add.b Dn,<ea>
    bne k158
    jmp op_add
k158: cmp #$D140            ; add.w Dn,<ea>
    bne k159
    jmp op_add
k159: cmp #$D180            ; add.l Dn,<ea>
    bne k160
    jmp op_add
k160: cmp #$9000            ; sub.b <ea>,Dn
    bne k161
    jmp op_sub
k161: cmp #$9040            ; sub.w <ea>,Dn
    bne k162
    jmp op_sub
k162: cmp #$9080            ; sub.l <ea>,Dn
    bne k163
    jmp op_sub
k163: cmp #$9100            ; sub.b Dn,<ea>
    bne k164
    jmp op_sub
k164: cmp #$9140            ; sub.w Dn,<ea>
    bne k165
    jmp op_sub
k165: cmp #$9180            ; sub.l Dn,<ea>
    bne k166
    jmp op_sub
k166: cmp #$B000            ; cmp.b <ea>,Dn
    bne k167
    jmp op_cmp
k167: cmp #$B040            ; cmp.w <ea>,Dn
    bne k168
    jmp op_cmp
k168: cmp #$B080            ; cmp.l <ea>,Dn
    bne k169
    jmp op_cmp
k169: lda $44
    and #$FFF8
    cmp #$48C0            ; ext.l Dn
    bne k170
    jmp op_ext_l
k170: lda $44
    and #$FFC0
    cmp #$4400            ; neg.b <ea>
    bne k171
    jmp op_neg
k171: cmp #$4440            ; neg.w <ea>
    bne k172
    jmp op_neg
k172: cmp #$4480            ; neg.l <ea>
    bne k173
    jmp op_neg
k173: lda $44
    and #$F000
    cmp #$E000            ; all $Exxx = shift/rotate (68000)
    bne kbit_s
    lda $44
    and #$00C0
    cmp #$00C0            ; size field 11 -> memory (word, 1-bit) form
    bne k173r
    jmp op_shift_mem
k173r: jmp op_shift
kbit_s: lda $44
    and #$FF00
    cmp #$0800            ; static bit ops: BTST/BCHG/BCLR/BSET #n,<ea>
    bne kbit_d
    jmp op_bitop
kbit_d: lda $44
    and #$F100
    cmp #$0100            ; dynamic bit ops: bit8=1, hi nibble 0
    bne kdbcc
    lda $44
    and #$0038
    cmp #$0008            ; mode==An(001) -> MOVEP (not a bit op)
    bne kbit_dgo
    jmp op_movep
kbit_dgo:
    jmp op_bitop
kdbcc: lda $44
    and #$F0F8
    cmp #$50C8            ; DBcc : 0101 cccc 11 001 rrr  (any cc; DBF/cc=1 still hits op_dbra earlier)
    bne kscc
    jmp op_dbcc
kscc: lda $44
    and #$F0C0
    cmp #$50C0            ; Scc : 0101 cccc 11 mmmrrr  (DBcc mode=001 routed above)
    bne kmul
    jmp op_scc
kmul: lda $44
    and #$F1C0
    cmp #$C0C0            ; MULU.W <ea>,Dn  (1100 ddd 011 mmmrrr)
    bne kmuls
    jmp op_mulu
kmuls: cmp #$C1C0           ; MULS.W <ea>,Dn  (1100 ddd 111 mmmrrr)
    bne kdivu
    jmp op_muls
kdivu: cmp #$80C0           ; DIVU.W <ea>,Dn  (1000 ddd 011 mmmrrr)
    bne kdivs
    jmp op_divu
kdivs: cmp #$81C0           ; DIVS.W <ea>,Dn  (1000 ddd 111 mmmrrr)
    bne kchk
    jmp op_divs
kchk: cmp #$4180            ; CHK.W <ea>,Dn   (0100 ddd 110 mmmrrr)
    bne kb8
    jmp op_chk
kb8: lda $44                ; --- Batch 8 control/system ---
    cmp #$4AFC             ; ILLEGAL (must precede TAS, which it shares $4Axx with)
    bne kb8_tas
    jmp op_illegal
kb8_tas: lda $44
    and #$FFC0
    cmp #$4AC0             ; TAS <ea>
    bne kb8_mfsr
    jmp op_tas
kb8_mfsr: cmp #$40C0        ; MOVE SR,<ea>
    bne kb8_mtccr
    jmp op_move_from_sr
kb8_mtccr: cmp #$44C0       ; MOVE <ea>,CCR
    bne kb8_mtsr
    jmp op_move_to_ccr
kb8_mtsr: cmp #$46C0        ; MOVE <ea>,SR
    bne kb8_trapv
    jmp op_move_to_sr
kb8_trapv: lda $44
    cmp #$4E76             ; TRAPV
    bne kb8_reset
    jmp op_trapv
kb8_reset: cmp #$4E70       ; RESET
    bne kb8_stop
    jmp op_reset
kb8_stop: cmp #$4E72        ; STOP #imm
    bne kb8_rtr
    jmp op_stop
kb8_rtr: cmp #$4E77         ; RTR
    bne kb8_usp
    jmp op_rtr
kb8_usp: lda $44
    and #$FFF8
    cmp #$4E60             ; MOVE An,USP
    bne kb8_uspf
    jmp op_move_an_usp
kb8_uspf: cmp #$4E68        ; MOVE USP,An
    bne kbad
    jmp op_move_usp_an
kbad:
    lda $44              ; general MOVE fallback: any unmatched $1xxx/$2xxx/$3xxx is a
    and #$C000           ; move/movea EA variant -> op_move_g (EA engine). bits 15-14==00
    bne kbad_mv0         ; not $0-3xxx -> try CLR
    lda $44
    and #$3000           ; bits 13-12 != 00 identifies a MOVE (vs $0xxx ORI/ANDI/...)
    beq kbad_mv0
    jmp op_move_g
kbad_mv0:
    lda $44              ; CLR.size <ea> = $42xx -> op_clr_g (EA engine, any EA mode)
    and #$FF00
    cmp #$4200
    bne kbad_pea
    jmp op_clr_g
kbad_pea:
    lda $44              ; PEA <ea> = $4840-$487F (SWAP $4840-47 already matched) -> op_pea_g
    and #$FFC0
    cmp #$4840
    bne kbad_halt
    jmp op_pea_g
kbad_halt:
    jmp kbad_chkidx      ; SAME-SIZE swap (3 bytes): check indexed JMP/JSR -> else kbad_aq2
    sta $4E              ; (dead: kbad_aq2 sets $4E and jmp idone for the non-ADDQ.B case)
    jmp idone

; --- helpers: extract reg (bits 11-9) -> A, and (bits 2-0) -> A ---
; (inlined per handler)

op_lea_abs:              ; lea (xxx).L,An : An = abs32 ; PC += 6
    jsr rdw2
    sta $52              ; abs high16
    jsr rdw4
    sta $54              ; abs low16
    jsr regdstA          ; X = An slot
    lda $54
    sta $00,x
    lda $52
    sta $02,x
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_movw_imm_abs:         ; move.w #imm,(xxx).L : no-op, PC += 8
    lda $40
    clc
    adc #8
    sta $40
    jmp inext

op_movw_imm_dn:          ; move.w #imm,Dn : Dn.lo=imm, PC += 4
    jsr rdw2
    sta $50
    jsr regdst           ; X = Dn slot (bits 11-9)*4
    lda $50
    sta $00,x
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_imm_dn:          ; move.l #imm,Dn : Dn=imm32, PC += 6
    jsr rdw2             ; top word (bytes 0,1)
    sta $50
    jsr rdw4             ; bottom word (bytes 2,3)
    sta $52
    jsr regdst
    lda $52
    sta $00,x            ; Dn low
    lda $50
    sta $02,x            ; Dn high
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_movb_imm_dn:          ; move.b #imm,Dn : Dn.lobyte=imm, PC += 4
    jsr rdw2             ; imm word; low byte = the byte imm
    and #$00FF
    sta $50
    jsr regdst
    sep #$20
    lda $50
    sta $00,x            ; Dn low byte
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_lea_d16:              ; lea (d16,An),An : dstAn = srcAn + d16 ; PC += 4
    jsr rdw2
    sta $50              ; d16 (sign in bit15)
    ; src An (bits 2-0) low16 + d16 -> tmp
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; X = src An slot
    lda $00,x            ; src An low16
    clc
    adc $50
    sta $52              ; result low16
    lda $02,x            ; src An high
    sta $54              ; (carry of low add ignored; test stays in $F0)
    ; dst An (bits 11-9)
    jsr regdstA          ; X = dst An slot ($20 + reg*4)
    lda $52
    sta $00,x
    lda $54
    sta $02,x
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_lea_an:               ; lea (An),An : dstAn = srcAn ; PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    sta $52
    lda $02,x
    sta $54
    jsr regdstA
    lda $52
    sta $00,x
    lda $54
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movl_dn:              ; move.l Dn,Dn : dst = src (32-bit) ; PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $52
    lda $02,x
    sta $54
    jsr regdst
    lda $52
    sta $00,x
    lda $54
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movb_dn_anp:          ; move.b Dn,(An)+ : dstAn=(11-9), srcDn=(2-0); PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x            ; Dn low (byte in low8)
    sta $50
    jsr regdstA          ; X = dst An slot
    lda $00,x            ; An low16
    sta $52              ; mem offset
    inc a
    sta $00,x            ; An++
    ldx $52              ; X = mem offset (use long,X — no long,Y exists)
    sep #$20
    lda $50
    sta $400000,x        ; write byte to work RAM
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movb_dn_d16:          ; move.b Dn,(d16,An) : [An+d16]=Dn.b (work RAM); Z ; PC += 4
    jsr rdw2
    sta $52              ; d16
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    and #$00FF
    sta $50              ; Dn byte
    jsr regdstA          ; X = dst An slot (bits 11-9)
    lda $02,x
    cmp #$00F0
    bne mbdd_skip        ; non-work-RAM -> no-op
    lda $00,x
    clc
    adc $52
    tax                  ; dst addr = An.low16 + d16
    sep #$20
    lda $50
    sta $400000,x
    rep #$20
mbdd_skip:
    lda $50
    jsr setnz_b
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movb_dn_predec:       ; move.b Dn,-(An) : An-=1; [An]=Dn.b (work RAM); Z ; PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    and #$00FF
    sta $50              ; Dn byte
    jsr regdstA          ; X = dst An slot
    lda $00,x
    dec a
    sta $00,x            ; An -= 1
    lda $02,x
    cmp #$00F0
    bne mdp_skip
    lda $00,x
    tax
    sep #$20
    lda $50
    sta $400000,x
    rep #$20
mdp_skip:
    lda $50
    jsr setnz_b
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movb_imm_predec:      ; move.b #imm,-(An) : An-=1; [An]=imm.b ; Z ; PC += 4
    jsr rdw2
    and #$00FF
    sta $50              ; imm byte
    jsr regdstA          ; X = dst An slot
    lda $00,x
    dec a
    sta $00,x            ; An -= 1
    lda $02,x
    cmp #$00F0
    bne mip_skip
    lda $00,x
    tax
    sep #$20
    lda $50
    sta $400000,x
    rep #$20
mip_skip:
    lda $50
    jsr setnz_b
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movb_dn_an:           ; move.b Dn,(An) : work-RAM only (I/O = no-op) ; PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50
    jsr regdstA
    lda $02,x            ; An high16
    cmp #$00F0
    bne mdn_skip         ; not work RAM -> I/O write no-op
    lda $00,x            ; An low16 -> X
    tax
    sep #$20
    lda $50
    sta $400000,x
    rep #$20
mdn_skip:
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_cmpb_anp:             ; cmp.b (An)+,Dn : Z=(mem==Dn.b); An++; PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; X = An slot
    lda $00,x
    sta $52              ; mem offset
    inc a
    sta $00,x            ; An++
    ldx $52
    sep #$20
    lda $400000,x        ; mem byte
    sta $50
    rep #$20
    lda $50
    and #$00FF
    sta $74              ; src = mem.b
    stz $76
    jsr regdst           ; X = Dn slot
    lda $00,x
    and #$00FF
    sta $80              ; dest = Dn.b
    stz $82
    stz $5E              ; byte -> full N/Z/V/C (X untouched); CMP has no write-back
    jsr subflags
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_cmpb_an:              ; cmp.b (An),Dn : no increment ; PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x            ; An low16 -> X
    tax
    sep #$20
    lda $400000,x
    sta $50
    rep #$20
    lda $50
    and #$00FF
    sta $74              ; src = mem.b
    stz $76
    jsr regdst
    lda $00,x
    and #$00FF
    sta $80              ; dest = Dn.b
    stz $82
    stz $5E              ; full N/Z/V/C (X untouched); CMP has no write-back
    jsr subflags
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_clr:                  ; clr.l (An)+ : no-op write, PC += 2
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_dbra:                 ; dbra Dn,disp
    jsr rdw2
    sta $50
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    dec a
    sta $00,x
    cmp #$FFFF
    beq dbra_fall
    jmp branch_apply     ; bank-correct PC = (PC+2) + sign_ext(disp16)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
dbra_fall:
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_subq_l:               ; subq.l #data,Dn : Dn -= data(32) ; Z=(Dn==0) ; PC += 2
    ; data = (op>>9)&7 (0 means 8 in 68K, but reset uses #1)
    lda $44
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
    sta $50              ; data (bits 11-9)
    lda $44              ; reg is bits 2-0, NOT 11-9
    and #$0007
    asl a
    asl a
    tax
    sec
    lda $00,x
    sbc $50
    sta $00,x
    lda $02,x
    sbc #$0000
    sta $02,x
    ; Z = (low==0 && high==0)
    lda $00,x
    ora $02,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_lsr_b:                ; lsr.b #cnt,Dn : Dn.byte >>= cnt ; Z=(byte==0) ; PC += 2
    lda $44
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
    sta $50              ; cnt (bits 11-9; reset uses 1)
    lda $44              ; reg is bits 2-0, NOT 11-9
    and #$0007
    asl a
    asl a
    tax
    sep #$20
    lda $00,x            ; Dn byte
lsr_loop:
    ldy $50
    cpy #0
    beq lsr_done
    lsr a
    dec $50
    bra lsr_loop
lsr_done:
    sta $00,x
    rep #$20
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_bne:                  ; bne disp8 : if Z==0 branch PC+2+disp else PC+=2
    lda $60
    bne bne_fall         ; Z set -> not taken
    ; sign-extend disp8
    lda $44
    and #$00FF
    cmp #$0080
    bcc bne_pos
    ora #$FF00
bne_pos:
    sta $50
    jmp branch_apply     ; bank-correct PC = (PC+2) + sign_ext(disp16)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
bne_fall:
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_bra:                  ; bra disp8 (or disp16 if disp8==0) : PC = PC+2+disp
    lda $44
    and #$00FF
    bne bra_short
    jsr rdw2             ; word form: disp16 at PC+2
    sta $50
    bra bra_go
bra_short:
    cmp #$0080
    bcc bra_pos
    ora #$FF00
bra_pos:
    sta $50
bra_go:
    jmp branch_apply     ; bank-correct PC = (PC+2) + sign_ext(disp16)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop

op_jsr_abs:              ; jsr (xxx).L : push PC+6, PC = 24-bit target ; (work-RAM stack)
    jsr rdw2             ; target high16 (bank) @ PC+2 -- was DISCARDED (stz $42), forcing
    sta $50              ; bank 0 so cross-bank jsr (e.g. JSR $024AA8) crashed into bank 0
    jsr rdw4             ; target low16 @ PC+4
    sta $52
    lda $40
    clc
    adc #6
    sta $54              ; return addr low16
    jsr jsrabs_hook2     ; native-escape dispatch (jsr.l call path); miss -> jsrabs_hook
    lda $52
    sta $40              ; PC low16 = target low16
    lda $50
    sta $42              ; PC high16 = target bank
    jmp inext

op_bsr:                  ; bsr : disp8 (short) or, if disp8==0, disp16 (word form)
    lda $44
    and #$00FF
    bne bsr_short
    ; word form: disp16 @ PC+2, return = PC+4, PC = PC+2 + disp16
    jsr rdw2
    sta $50
    lda $40
    clc
    adc #4
    sta $54              ; return addr = PC+4
    jsr bsr_hookpush     ; native-escape check (else push32r); byte-neutral swap
    jmp branch_apply     ; bank-correct PC = (PC+2) + sign_ext(disp16)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
bsr_short:
    cmp #$0080
    bcc bsr_pos
    ora #$FF00
bsr_pos:
    sta $50
    lda $40
    clc
    adc #2
    sta $54              ; return addr = PC+2
    jsr bsr_hookpush     ; native-escape check (else push32r); byte-neutral swap
    jmp branch_apply     ; bank-correct PC = (PC+2) + sign_ext(disp16)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop

op_rts:                  ; rts : PC = pop 24-bit return (bank byte1 -> $42) ; A7 += 4
    ldx $3C              ; A7 low16
    sep #$20
    lda $400001,x        ; byte1 = PC bits 16-23 (bank) -- was discarded (stz $42),
    rep #$20             ; truncating cross-bank returns to bank 0
    and #$00FF
    sta $42              ; PC high16 = bank
    sep #$20
    lda $400002,x        ; byte2 = PC bits 8-15 -> A.hi
    xba
    lda $400003,x        ; byte3 = PC bits 0-7  -> A.lo
    rep #$20
    sta $40              ; PC low16 = byte2<<8 | byte3
    lda $3C
    clc
    adc #4
    sta $3C              ; A7 += 4
    jmp inext

op_beq:                  ; beq disp8 : if Z(set) branch
    lda $60
    beq beq_fall
    lda $44
    and #$00FF
    cmp #$0080
    bcc beq_pos
    ora #$FF00
beq_pos:
    sta $50
    jmp branch_apply     ; bank-correct PC = (PC+2) + sign_ext(disp16)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
beq_fall:
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_cmpib_abs:            ; cmpi.b #imm,(xxx).L : Z=(mem==imm) ; PC += 8
    jsr rdw2
    and #$00FF
    sta $50              ; imm byte
    jsr rdw4
    sta $52              ; addr top16
    jsr rdw6
    sta $54              ; addr low16
    jsr readbyte         ; A.low = byte at addr (I/O aware)
    sep #$20
    cmp $50
    rep #$20
    jsr setz_from_eq
    lda $40
    clc
    adc #8
    sta $40
    jmp inext

op_cmpi_l_dn:           ; cmpi.l #imm,Dn : full CCR (Dn - imm32) ; PC += 6
    jsr rdw2
    sta $76            ; imm high16
    jsr rdw4
    sta $74            ; imm low16
    lda $44
    and #$0007
    asl a
    asl a
    tax                ; Dn slot
    sec
    lda $00,x
    sbc $74
    sta $78            ; result low16
    lda $02,x
    sbc $76
    sta $7A            ; result high16
    bcs cil_noc        ; 65816 carry set = no borrow
    lda #$0001
    sta $6E            ; C (68k borrow) = 1
    bra cil_z
cil_noc:
    stz $6E
cil_z:
    lda $78
    ora $7A
    bne cil_nz
    lda #$0001
    sta $60            ; Z = 1
    bra cil_n
cil_nz:
    stz $60
cil_n:
    lda $7A
    and #$8000
    beq cil_npos
    lda #$0001
    sta $70            ; N = 1
    bra cil_v
cil_npos:
    stz $70
cil_v:
    lda $02,x
    eor $76
    sta $5C            ; (dest^src) high16
    lda $02,x
    eor $7A
    and $5C
    and #$8000
    beq cil_vno
    lda #$0001
    sta $72            ; V = 1
    bra cil_done
cil_vno:
    stz $72
cil_done:
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_cmpi_b_dn:           ; cmpi.b #imm,Dn : Z=(Dn.b==imm.b) ; PC += 4
    jsr rdw2
    and #$00FF
    sta $50              ; imm byte
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x            ; Dn (low byte = Dn.b)
    sep #$20
    cmp $50
    rep #$20
    jsr setz_from_eq
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movw_imm_d16:         ; move.w #imm,(d16,An) : work-RAM word write (big-endian)
    jsr rdw2
    sta $50              ; imm word
    jsr rdw4
    sta $52              ; d16
    jsr regdstA          ; X = An slot
    lda $00,x
    clc
    adc $52
    tax                  ; X = An.low16 + d16 (assume An high $F0)
    lda $50
    xba                  ; store big-endian: hi at offset, lo at offset+1
    sta $400000,x
    lda $40
    clc
    adc #6               ; move.w #imm,(d16,An) is 6 bytes
    sta $40
    jmp inext

op_movw_d16_predec:      ; move.w (d16,An),-(An) : ROM-aware src -> jmp v2 (free block)
    jmp op_mw_d16pre_v2
    sta $52              ; src d16 (dead tail; kept to avoid shifting following handlers)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $00,x
    clc
    adc $52
    tax                  ; src addr
    sep #$20
    lda $400000,x        ; src bits15-8
    sta $51
    inx
    lda $400000,x        ; src bits7-0
    sta $50
    rep #$20
    jsr regdstA          ; X = dst An slot (bits 11-9)
    lda $00,x
    sec
    sbc #2
    sta $00,x            ; An -= 2
    tax                  ; dst addr (stack work RAM)
    sep #$20
    lda $51
    sta $400000,x        ; high byte
    inx
    lda $50
    sta $400000,x        ; low byte
    rep #$20
    lda $50
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movw_dn_predec:       ; move.w Dn,-(An) : An-=2; [An]=Dn.w (big-endian); Z ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50              ; Dn word
    jsr regdstA          ; X = An slot
    lda $00,x
    sec
    sbc #2
    sta $00,x            ; An -= 2
    tax                  ; An.low16 (stack assumed work RAM $F0)
    lda $50
    xba
    sep #$20
    sta $400000,x        ; high byte
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x        ; low byte
    rep #$20
    lda $50
    jsr setnz_w
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movw_imm_pre:         ; move.w #imm,-(An) : An-=2 ; [An]=imm (big-endian) ; PC+=4
    jsr rdw2
    sta $50              ; imm word
    jsr regdstA          ; X = An slot
    lda $00,x
    sec
    sbc #2
    sta $00,x            ; An -= 2
    tax                  ; X = An.low16 (assume work RAM $F0)
    lda $50
    xba
    sep #$20
    sta $400000,x        ; high byte
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x        ; low byte
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_adda_l:               ; adda.l #imm,An : An += imm32 ; PC += 6
    jsr rdw2
    sta $50              ; imm high16
    jsr rdw4
    sta $52              ; imm low16
    jsr regdstA          ; X = An slot
    clc
    lda $00,x
    adc $52
    sta $00,x            ; An low16
    lda $02,x
    adc $50
    sta $02,x            ; An high16
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_adda_w:               ; adda.w #imm,An : An += sign-ext(imm16) ; PC += 4
    jsr rdw2
    sta $50              ; imm16
    jsr regdstA          ; X = An slot
    clc
    lda $00,x
    adc $50
    sta $00,x            ; An low16
    lda $50
    bmi adw_neg
    lda $02,x
    adc #$0000
    sta $02,x
    bra adw_done
adw_neg:
    lda $02,x
    adc #$FFFF
    sta $02,x
adw_done:
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movw_d16_dn:          ; move.w (d16,An),Dn : ROM-aware src -> jmp v2 (free block)
    jmp op_mw_d16dn_v2
    sta $52              ; d16 (dead tail; kept to avoid shifting following handlers)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; X = src An slot
    lda $00,x
    clc
    adc $52
    tax                  ; X = addr low16 (work RAM)
    sep #$20
    lda $400000,x        ; high byte
    sta $51
    inx
    lda $400000,x        ; low byte
    sta $50
    rep #$20
    jsr regdst           ; X = Dn slot
    lda $50              ; word = $51<<8 | $50
    sta $00,x            ; Dn low16
    jsr setz_from_a      ; MOVE.W sets Z (was missing -> stale Z broke `move.w (d16,An),Dn / bne`)
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movw_dn_d16:          ; move.w Dn,(d16,An) : [An+d16] = Dn.lo (big-endian) ; PC+=4
    jsr rdw2
    sta $52              ; d16
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x            ; Dn low16
    sta $50
    jsr regdstA          ; X = An slot
    lda $00,x
    clc
    adc $52
    tax                  ; addr low16 (work RAM)
    lda $50
    xba
    sep #$20
    sta $400000,x        ; high byte
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x        ; low byte
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movb_an_anp:          ; move.b (An),(An)+ : [dstAn++]=read(srcAn) (I/O-aware src); PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $02,x
    sta $52              ; src high16
    lda $00,x
    sta $54              ; src low16
    jsr readbyte         ; A.low = byte (I/O aware; clobbers $50)
    and #$00FF
    sta $50
    jsr regdstA          ; X = dst An slot
    lda $00,x
    sta $52              ; dst low16
    inc a
    sta $00,x            ; dst An ++
    ldx $52
    sep #$20
    lda $50
    sta $400000,x        ; write to work RAM
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_clrw_dn:              ; clr.w Dn : Dn.lo = 0 ; Z=1 ; PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    stz $00,x
    lda #$0001
    sta $60
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movb_dn_abs:          ; move.b Dn,(xxx).L : track $900C01 command ; PC += 6
    jsr rdw2
    sta $52              ; abs high16
    jsr rdw4
    sta $54              ; abs low16
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    and #$00FF
    sta $50              ; Dn byte
    lda $52
    cmp #$0090
    bne mda_done
    lda $54
    cmp #$0C01           ; C-Chip command port
    bne mda_done
    lda $50
    sta $62              ; last command
mda_done:
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_movb_imm_abs:         ; move.b #imm,(xxx).L : I/O no-op write ; PC += 8
    lda $40
    clc
    adc #8
    sta $40
    jmp inext

op_nop:                  ; nop ; PC += 2
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_jsr_pcrel:            ; jsr (d16,PC) : push PC+4 ; PC = PC+2+d16
    jsr rdw2
    sta $50              ; d16
    lda $40
    clc
    adc #4
    sta $54              ; return addr = PC+4
    jsr bsr_hookpush     ; native-escape check (else push32r); byte-neutral swap
    jmp branch_apply     ; bank-correct PC = (PC+2) + sign_ext(disp16)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop

op_movb_abs_dn:          ; move.b (xxx).L,Dn : Dn.lobyte = read(abs) ; PC += 6
    jsr rdw2
    sta $52              ; abs high16
    jsr rdw4
    sta $54              ; abs low16
    jsr readbyte
    and #$00FF
    sta $50
    jsr regdst           ; X = Dn slot
    sep #$20
    lda $50
    sta $00,x            ; Dn low byte (high bytes preserved)
    rep #$20
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_andi_b:               ; andi.b #imm,Dn : Dn.lobyte &= imm ; Z ; PC += 4
    jsr rdw2
    and #$00FF
    sta $50              ; imm byte
    lda $44
    and #$0007
    asl a
    asl a
    tax
    sep #$20
    lda $00,x
    and $50
    sta $00,x
    rep #$20
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_or_b:                 ; or.b Dn,Dn : dst.lobyte |= src.lobyte ; Z ; PC += 2
    lda $44
    and #$0007           ; src Dn (bits 2-0)
    asl a
    asl a
    tax
    lda $00,x
    and #$00FF
    sta $50              ; src byte
    jsr regdst           ; X = dst Dn slot (bits 11-9)
    sep #$20
    lda $00,x
    ora $50
    sta $00,x
    rep #$20
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_lsl_b:                ; lsl.b #cnt,Dn : Dn.lobyte <<= cnt ; Z ; PC += 2
    lda $44
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
    sta $50              ; cnt (bits 11-9)
    lda $44
    and #$0007
    asl a
    asl a
    tax
    sep #$20
    lda $00,x            ; Dn byte
lsl_loop:
    ldy $50
    cpy #0
    beq lsl_done
    asl a
    dec $50
    bra lsl_loop
lsl_done:
    sta $00,x
    rep #$20
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_lea_pc:               ; lea (d16,PC),An : An = (PC+2)+signext(d16) ; PC += 4
    jsr rdw2
    sta $50              ; d16
    lda $40
    clc
    adc #2
    sta $52              ; base low16
    lda $42
    and #$00FF
    adc #$0000
    sta $54              ; base high (carry from +2)
    lda $52
    clc
    adc $50
    sta $52              ; result low16
    lda $50
    bmi lp_neg
    lda $54
    adc #$0000
    bra lp_hi
lp_neg:
    lda $54
    adc #$FFFF
lp_hi:
    sta $54
    jsr regdstA
    lda $52
    sta $00,x
    lda $54
    sta $02,x
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_imm_d16:         ; move.l #imm,(d16,An) : [An+d16]=imm32 (big-endian) ; PC+=8
    jsr rdw2
    sta $50              ; imm high16
    jsr rdw4
    sta $52              ; imm low16
    jsr rdw6
    sta $54              ; d16
    jsr regdstA
    lda $00,x
    clc
    adc $54
    tax                  ; addr low16
    sep #$20
    lda $51
    sta $400000,x        ; bits 24-31
    rep #$20
    inx
    sep #$20
    lda $50
    sta $400000,x        ; bits 16-23
    rep #$20
    inx
    sep #$20
    lda $53
    sta $400000,x        ; bits 8-15
    rep #$20
    inx
    sep #$20
    lda $52
    sta $400000,x        ; bits 0-7
    rep #$20
    lda $40
    clc
    adc #8
    sta $40
    jmp inext

op_andi_w:               ; andi.w #imm,Dn : Dn.lo &= imm ; Z ; PC += 4
    jsr rdw2
    sta $50
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    and $50
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_btst_imm_d16:         ; btst #bit,(d16,An) : Z=!(byte bit set) ; PC += 6
    jsr rdw2
    and #$0007
    sta $50              ; bit (mod 8, memory)
    jsr rdw4
    sta $52              ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot (bits 2-0)
    lda $00,x
    clc
    adc $52
    tax                  ; addr
    sep #$20
    lda $400000,x
    rep #$20
    and #$00FF
    sta $54              ; byte
    ldy $50
    lda #$0001
bt_sh:
    cpy #0
    beq bt_done
    asl a
    dey
    bra bt_sh
bt_done:
    and $54
    jsr setz_from_a
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_clrw_d16:             ; clr.w (d16,An) : [An+d16]=0 ; Z=1 ; PC += 4
    jsr rdw2
    sta $52              ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot (bits 2-0)
    lda $00,x
    clc
    adc $52
    tax                  ; addr
    sep #$20
    lda #$00
    sta $400000,x
    inx
    sta $400000,x
    rep #$20
    lda #$0001
    sta $60
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_pea:                  ; pea (xxx).L : push 32-bit abs address ; PC += 6
    jsr rdw2
    sta $50              ; abs high16
    jsr rdw4
    sta $52              ; abs low16
    lda $3C
    sec
    sbc #4
    sta $3C
    tax
    sep #$20
    lda $51
    sta $400000,x        ; bits 24-31
    inx
    lda $50
    sta $400000,x        ; bits 16-23
    inx
    lda $53
    sta $400000,x        ; bits 8-15
    inx
    lda $52
    sta $400000,x        ; bits 0-7
    rep #$20
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_pea_d16:              ; pea (d16,An) : push 32-bit EA (An+signext(d16)) ; PC+=4
    jsr rdw2
    sta $52              ; d16
    bpl ped_pos
    lda #$FFFF
    bra ped_hi
ped_pos:
    lda #$0000
ped_hi:
    sta $58              ; d16 sign-extension high
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot
    lda $00,x
    clc
    adc $52
    sta $54              ; EA low16
    lda $02,x
    adc $58
    sta $56              ; EA high16
    lda $3C
    sec
    sbc #4
    sta $3C
    tax                  ; A7 low16
    sep #$20
    lda $57              ; EA bits31-24
    sta $400000,x
    inx
    lda $56              ; bits23-16
    sta $400000,x
    inx
    lda $55              ; bits15-8
    sta $400000,x
    inx
    lda $54              ; bits7-0
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_adda_w_dn:            ; adda.w Dn,An : An += signext(Dn.lo) ; PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50              ; Dn low16
    jsr regdstA
    clc
    lda $00,x
    adc $50
    sta $00,x
    lda $50
    bmi awd_neg
    lda $02,x
    adc #$0000
    sta $02,x
    bra awd_done
awd_neg:
    lda $02,x
    adc #$FFFF
    sta $02,x
awd_done:
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movw_an_d16:          ; move.w (An),(d16,An) : [dstAn+d16]=[srcAn] (big-end) ; PC+=4
    jsr rdw2
    sta $52              ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $00,x
    tax                  ; src addr
    sep #$20
    lda $400000,x
    sta $51              ; high byte
    inx
    lda $400000,x
    sta $50              ; low byte
    rep #$20
    jsr regdstA          ; dst An
    lda $00,x
    clc
    adc $52
    tax                  ; dst addr
    sep #$20
    lda $51
    sta $400000,x        ; high
    inx
    lda $50
    sta $400000,x        ; low
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_anp_anp:         ; move.l (An)+,(An)+ : copy 4 bytes (I/O-aware src) ; PC += 2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $02,x
    sta $52              ; src high16 (readbyte: $52=top16)
    lda $00,x
    sta $54              ; src low16 (running)
    clc
    lda $00,x
    adc #4
    sta $00,x            ; src An += 4
    jsr regdstA          ; dst An slot
    lda $02,x
    sta $5E              ; dst high16
    lda $00,x
    sta $6A              ; dst addr (running)
    clc
    adc #4
    sta $00,x            ; dst An += 4
    lda $5E
    jsr map_snes         ; -> $C2 mode (0=$7F/1=$7E/2=noop), $6A = SNES offset
    ldy #$0000
mll_loop:
    jsr readbyte         ; reads from $52(top16)/$54(low16); ROM or RAM
    sta $50              ; byte
    lda $C2
    beq mll_work         ; mode 0 -> work RAM $7F
    cmp #$0001
    bne mll_nowrite      ; mode 2 -> no-op
    ldx $6A              ; mode 1 -> shadow RAM $7E
    sep #$20
    lda $50
    sta $410000,x        ; mirror byte into video shadow
    rep #$20
    bra mll_nowrite
mll_work:
    ldx $6A
    sep #$20
    lda $50
    sta $400000,x        ; write byte to dst (work RAM)
    rep #$20
mll_nowrite:
    inc $54              ; src low16++
    inc $6A              ; dst low16++
    iny
    cpy #4
    bne mll_loop
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_lsl_w:                ; lsl.w #cnt,Dn : Dn.lo <<= cnt ; Z ; PC += 2
    lda $44
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
    sta $50              ; cnt (bits 11-9)
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x            ; Dn low16
lslw_loop:
    ldy $50
    cpy #0
    beq lslw_done
    asl a
    dec $50
    bra lslw_loop
lslw_done:
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_subq_w:               ; subq.w #data,Dn : Dn.lo -= data ; Z ; PC += 2
    lda $44
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
    sta $50              ; data (bits 11-9; 0 means 8)
    bne sqw_ok
    lda #$0008
    sta $50
sqw_ok:
    lda $44
    and #$0007
    asl a
    asl a
    tax
    sec
    lda $00,x
    sbc $50
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_link:                 ; link An,#disp16 : push An; An=A7; A7+=signext(disp16) ; PC+=4
    jsr rdw2
    sta $50              ; disp16
    ; read An (32-bit) into $52(high16)/$54(low16)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot
    lda $00,x
    sta $54              ; An low16
    lda $02,x
    sta $52              ; An high16
    ; A7 -= 4
    lda $3C
    sec
    sbc #4
    sta $3C
    ldx $3C              ; X = A7 low16 (work RAM $7F)
    sep #$20
    lda $53              ; An bits31-24
    sta $400000,x
    inx
    lda $52              ; An bits23-16
    sta $400000,x
    inx
    lda $55              ; An bits15-8
    sta $400000,x
    inx
    lda $54              ; An bits7-0
    sta $400000,x
    rep #$20
    ; An = A7 (low16 from $3C, high16 = A7 high = $3E)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $3C
    sta $00,x
    lda $3E
    sta $02,x
    ; A7 += signext(disp16)
    clc
    lda $3C
    adc $50
    sta $3C
    lda $50
    bmi lnk_neg
    lda $3E
    adc #$0000
    sta $3E
    bra lnk_done
lnk_neg:
    lda $3E
    adc #$FFFF
    sta $3E
lnk_done:
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_unlk:                 ; unlk An : A7=An; An=pop32; A7+=4 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot
    lda $00,x
    sta $3C              ; A7 low16 = An low16
    lda $02,x
    sta $3E              ; A7 high16 = An high16
    ldx $3C              ; X = A7 (work RAM)
    sep #$20
    lda $400000,x        ; bits31-24
    sta $53
    inx
    lda $400000,x        ; bits23-16
    sta $52
    inx
    lda $400000,x        ; bits15-8
    sta $55
    inx
    lda $400000,x        ; bits7-0
    sta $54
    rep #$20
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $54              ; An low16 = $55:$54
    sta $00,x
    lda $52              ; An high16 = $53:$52
    sta $02,x
    ; A7 += 4
    lda $3C
    clc
    adc #4
    sta $3C
    lda $3E
    adc #$0000
    sta $3E
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movem_pre:            ; movem.l <list>,-(An) : push regs (D0..A7 by mask) ; PC+=4
    jsr rdw2
    sta $50              ; mask (shifted right each iter; bit0=A7..bit15=D0)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    sta $6C              ; An slot
    ldy #$0000           ; i = 0..15
mp_loop:
    lda $50
    lsr a
    sta $50              ; shift mask down; bit i -> carry
    bcc mp_skip
    ; bit i set: reg index r = 15 - i ; slot = r*4
    tya
    eor #$000F
    asl a
    asl a
    tax                  ; X = reg slot
    lda $00,x
    sta $54              ; reg low16
    lda $02,x
    sta $56              ; reg high16 (fetch ptr free now)
    ; An -= 4
    ldx $6C
    lda $00,x
    sec
    sbc #4
    sta $00,x
    tax                  ; X = An addr (work RAM $7F)
    sep #$20
    lda $57              ; bits31-24
    sta $400000,x
    inx
    lda $56              ; bits23-16
    sta $400000,x
    inx
    lda $55              ; bits15-8
    sta $400000,x
    inx
    lda $54              ; bits7-0
    sta $400000,x
    rep #$20
mp_skip:
    iny
    cpy #$0010
    bne mp_loop
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movem_w_pre:          ; movem.w <list>,-(An) : push reg low16s (D0..A7 by mask) ; PC+=4
    jsr rdw2
    sta $50              ; mask (bit0=A7..bit15=D0)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    sta $6C              ; An slot
    ldy #$0000
mpw_loop:
    lda $50
    lsr a
    sta $50
    bcc mpw_skip
    tya
    eor #$000F
    asl a
    asl a
    tax                  ; reg slot
    lda $00,x
    sta $54              ; reg low16
    ldx $6C
    lda $00,x
    sec
    sbc #2
    sta $00,x            ; An -= 2
    tax                  ; An addr (work RAM $7F)
    sep #$20
    lda $55              ; bits15-8
    sta $400000,x
    inx
    lda $54              ; bits7-0
    sta $400000,x
    rep #$20
mpw_skip:
    iny
    cpy #$0010
    bne mpw_loop
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movem_w_post:         ; movem.w (An)+,<list> : pop reg low16s, sign-extend ; PC+=4
    jsr rdw2
    sta $50              ; mask (bit0=D0..bit15=A7)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    sta $6C              ; An slot
    ldy #$0000
mqw_loop:
    lda $50
    lsr a
    sta $50
    bcc mqw_skip
    tya
    asl a
    asl a
    sta $6E              ; reg slot = i*4
    ldx $6C
    lda $00,x
    tax                  ; An addr
    sep #$20
    lda $400000,x        ; bits15-8
    sta $55
    inx
    lda $400000,x        ; bits7-0
    sta $54
    rep #$20
    ldx $6C
    lda $00,x
    clc
    adc #2
    sta $00,x            ; An += 2
    ldx $6E
    lda $54              ; low16 = $55:$54
    sta $00,x
    lda $54
    bpl mqw_pos
    lda #$FFFF
    bra mqw_hi
mqw_pos:
    lda #$0000
mqw_hi:
    sta $02,x            ; high16 = sign extension
mqw_skip:
    iny
    cpy #$0010
    bne mqw_loop
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movem_post:          ; movem.l (An)+,<list> : pop regs (D0..A7 by mask) ; PC+=4
    jsr rdw2
    sta $50              ; mask (bit0=D0..bit15=A7)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    sta $6C              ; An slot
    ldy #$0000
mq_loop:
    lda $50
    lsr a
    sta $50
    bcc mq_skip
    ; bit i set: reg index r = i ; slot = i*4
    tya
    asl a
    asl a
    sta $6E              ; reg slot
    ldx $6C
    lda $00,x
    tax                  ; X = An addr
    sep #$20
    lda $400000,x        ; bits31-24
    sta $53
    inx
    lda $400000,x        ; bits23-16
    sta $52
    inx
    lda $400000,x        ; bits15-8
    sta $55
    inx
    lda $400000,x        ; bits7-0
    sta $54
    rep #$20
    ; An += 4
    ldx $6C
    lda $00,x
    clc
    adc #4
    sta $00,x
    ; store into reg slot
    ldx $6E
    lda $54              ; low16 = $55:$54
    sta $00,x
    lda $52              ; high16 = $53:$52
    sta $02,x
mq_skip:
    iny
    cpy #$0010
    bne mq_loop
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movea_l_d16:         ; movea.l (d16,An),An : dst = [srcAn+d16] (direct $7F) ; PC+=4
    jsr rdw2
    sta $52              ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $00,x
    clc
    adc $52
    tax                  ; src addr low16 ($7F)
    sep #$20
    lda $400000,x        ; bits31-24
    sta $53
    inx
    lda $400000,x        ; bits23-16
    sta $52
    inx
    lda $400000,x        ; bits15-8
    sta $55
    inx
    lda $400000,x        ; bits7-0
    sta $54
    rep #$20
    jsr regdstA          ; dst An slot
    lda $54              ; low16 = $55:$54
    sta $00,x
    lda $52              ; high16 = $53:$52
    sta $02,x
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movw_anp_an:         ; move.w (An)+,(An) : [dstAn]=[srcAn] (ROM-aware src, gated dst); srcAn+=2 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot (bits 2-0)
    lda $02,x
    sta $52              ; src high16
    lda $00,x
    sta $54              ; src low16
    clc
    adc #2
    sta $00,x            ; src An += 2
    jsr readbyte         ; src high byte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte         ; src low byte
    sep #$20
    sta $50
    rep #$20
    jsr regdstA          ; X = dst An slot (bits 11-9)
    lda $00,x
    sta $6A              ; dst lo16
    lda $02,x
    jsr map_snes         ; -> $C2 mode, $6A = SNES offset
    lda $C2
    cmp #$0002
    beq mwaa_skip        ; no-op
    cmp #$0001
    beq mwaa_shadow      ; shadow $7E
    ldx $6A              ; work RAM $7F
    sep #$20
    lda $51
    sta $400000,x        ; high byte
    inx
    lda $50
    sta $400000,x        ; low byte
    rep #$20
    bra mwaa_skip
mwaa_shadow:
    ldx $6A
    sep #$20
    lda $51
    sta $410000,x        ; high byte (video shadow)
    inx
    lda $50
    sta $410000,x        ; low byte
    rep #$20
mwaa_skip:
    lda $50
    jsr setnz_w
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movw_anp_dn:         ; move.w (An)+,Dn : Dn.lo=[An] (big-end, ROM-aware); An+=2 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $02,x
    sta $52              ; high16
    lda $00,x
    sta $54              ; low16
    lda $00,x
    clc
    adc #2
    sta $00,x            ; An += 2
    jsr readbyte         ; [An] high byte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte         ; [An+1] low byte
    sep #$20
    sta $50
    rep #$20
    jsr regdst           ; Dn slot
    lda $50              ; word = $51:$50
    sta $00,x            ; Dn low16
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movea_l_anp:         ; movea.l (An)+,An : dst = [An] (32, ROM-aware); An+=4 ; PC+=2
    jsr read_anp_long
    jsr regdstA          ; dst An slot
    lda $50              ; low16 = $51:$50
    sta $00,x
    lda $6A              ; high16 = $6B:$6A
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movl_anp_dn:         ; move.l (An)+,Dn : Dn = [An] (32, ROM-aware); An+=4 ; PC+=2
    jsr read_anp_long
    jsr regdst           ; Dn slot
    lda $50
    sta $00,x
    lda $6A
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

; read 32-bit big-endian from (An) with An = source reg bits 2-0, ROM-aware via
; readbyte; advances An by 4; returns low16 in $50($51:$50), high16 in $6A($6B:$6A)
read_anp_long:
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    lda $00,x
    clc
    adc #4
    sta $00,x            ; An += 4
    jsr readbyte         ; bits31-24
    sep #$20
    sta $6B
    rep #$20
    inc $54
    jsr readbyte         ; bits23-16
    sep #$20
    sta $6A
    rep #$20
    inc $54
    jsr readbyte         ; bits15-8
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte         ; bits7-0
    sep #$20
    sta $50
    rep #$20
    rts

op_or_l_d16:            ; or.l Dn,(d16,An) : [An+d16] |= Dn (32, work RAM) ; PC+=4
    jsr rdw2
    sta $6A              ; d16
    jsr regdst           ; Dn slot
    lda $00,x
    sta $50              ; Dn low16
    lda $02,x
    sta $52              ; Dn high16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot (bits 2-0)
    lda $00,x
    clc
    adc $6A
    tax                  ; addr low16 ($7F)
    sep #$20
    lda $400000,x
    ora $53              ; bits31-24
    sta $400000,x
    inx
    lda $400000,x
    ora $52              ; bits23-16
    sta $400000,x
    inx
    lda $400000,x
    ora $51              ; bits15-8
    sta $400000,x
    inx
    lda $400000,x
    ora $50              ; bits7-0
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movb_imm_anp:        ; move.b #imm,(An)+ : [An]=imm.b (work RAM); An+=1 ; PC+=4
    jsr rdw2
    and #$00FF
    sta $50              ; imm byte
    jsr regdstA          ; An slot (bits 11-9)
    lda $00,x
    sta $52              ; An low16 (addr)
    inc a
    sta $00,x            ; An += 1
    ldx $52
    sep #$20
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movb_anp_anp:        ; move.b (An)+,(An)+ : [dst]=read(src) (ROM-aware); both An+=1 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $02,x
    sta $52              ; src high16
    lda $00,x
    sta $54              ; src low16
    inc a
    sta $00,x            ; src An += 1
    jsr readbyte
    and #$00FF
    sta $50              ; byte
    jsr regdstA          ; dst An slot
    lda $00,x
    sta $52              ; dst addr
    inc a
    sta $00,x            ; dst An += 1
    ldx $52
    sep #$20
    lda $50
    sta $400000,x        ; write to work RAM
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movb_dn_dn:          ; move.b Dn,Dn : dst.b = src.b ; Z ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    and #$00FF
    sta $50              ; src byte
    jsr regdst           ; dst Dn slot
    sep #$20
    lda $50
    sta $00,x            ; dst low byte
    rep #$20
    lda $50
    jsr setnz_b
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_addi_b:              ; addi.b #imm,Dn : Dn.b += imm ; Z ; PC+=4
    jsr rdw2
    and #$00FF
    sta $50              ; imm byte
    lda $44
    and #$0007
    asl a
    asl a
    tax
    sep #$20
    lda $00,x
    clc
    adc $50
    sta $00,x
    rep #$20
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_subi_w:             ; subi.w #imm,Dn : Dn.lo -= imm ; Z ; PC+=4
    jsr rdw2
    sta $50            ; imm word
    lda $44
    and #$0007
    asl a
    asl a
    tax
    sec
    lda $00,x
    sbc $50
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_tst_l:              ; tst.l Dn : Z=(Dn==0), N=bit31 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    ora $02,x
    jsr setz_from_a
    lda $02,x
    and #$8000
    beq tl_npos
    lda #$0001
    sta $70            ; N = 1
    bra tl_done
tl_npos:
    stz $70
tl_done:
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_tst_w:              ; tst.w Dn : Z=(Dn.lo==0) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_clrb_an:            ; clr.b (An) : [An]=0 (work RAM only); Z=1 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                 ; An slot
    lda $02,x
    cmp #$00F0
    bne cba_noff
    lda $00,x
    tax
    sep #$20
    stz $400000,x
    rep #$20
cba_noff:
    lda #$0001
    sta $60             ; Z = 1
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_clrb_anp:           ; clr.b (An)+ : [An]=0 (work RAM); An+=1; Z=1 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                 ; An slot (bits 2-0)
    lda $00,x
    sta $52
    inc a
    sta $00,x           ; An += 1
    ldx $52
    sep #$20
    lda #$00
    sta $400000,x
    rep #$20
    lda #$0001
    sta $60             ; Z = 1
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movl_an_d16:        ; move.l An,(d16,An) : [dstAn+d16]=srcAn (32, work RAM big-end) ; PC+=4
    jsr rdw2
    sta $52             ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                 ; src An slot
    lda $00,x
    sta $50             ; src low16
    lda $02,x
    sta $54             ; src high16
    jsr regdstA         ; dst An slot
    lda $00,x
    clc
    adc $52
    tax                 ; dst addr (work RAM)
    sep #$20
    lda $55             ; src bits31-24
    sta $400000,x
    inx
    lda $54             ; bits23-16
    sta $400000,x
    inx
    lda $51             ; bits15-8
    sta $400000,x
    inx
    lda $50             ; bits7-0
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_btst_imm_dn:        ; btst #bit,Dn : Z = !(Dn bit (imm&31) set) ; PC+=4
    jsr rdw2
    and #$001F          ; register btst => bit mod 32
    sta $50
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $50
    cmp #$0010
    bcs btd_hi
    ldy $50
    lda #$0001
btd_lsh:
    cpy #0
    beq btd_ltest
    asl a
    dey
    bra btd_lsh
btd_ltest:
    and $00,x           ; AND with Dn low16
    jsr setz_from_a
    bra btd_done
btd_hi:
    sec
    lda $50
    sbc #$0010
    tay                 ; bit - 16
    lda #$0001
btd_hsh:
    cpy #0
    beq btd_htest
    asl a
    dey
    bra btd_hsh
btd_htest:
    and $02,x           ; AND with Dn high16
    jsr setz_from_a
btd_done:
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_or_w:               ; or.w Dn,Dn : dst.lo |= src.lo ; Z ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50             ; src low16
    jsr regdst          ; dst Dn slot
    lda $00,x
    ora $50
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movb_abs_d16:       ; move.b (xxx).L,(d16,An) : [An+d16]=read(abs) (I/O/ROM-aware) ; PC+=8
    jsr rdw2
    sta $52             ; abs high16
    jsr rdw4
    sta $54             ; abs low16
    jsr rdw6
    sta $6A             ; d16
    jsr readbyte
    and #$00FF
    sta $50             ; byte
    jsr regdstA         ; dst An slot (bits 11-9)
    lda $00,x
    clc
    adc $6A
    tax                 ; addr = An + d16
    sep #$20
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #8
    sta $40
    jmp inext

op_movb_an_dn:         ; move.b (An),Dn : Dn.b = read(An) (I/O/ROM-aware) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                 ; src An slot
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    jsr readbyte
    and #$00FF
    sta $50
    jsr regdst          ; Dn slot
    sep #$20
    lda $50
    sta $00,x           ; Dn low byte
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_adda_l_dn:          ; adda.l Dn,An : An += Dn (32) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax                 ; src Dn slot
    lda $00,x
    sta $50
    lda $02,x
    sta $52
    jsr regdstA         ; An slot
    clc
    lda $00,x
    adc $50
    sta $00,x
    lda $02,x
    adc $52
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movl_an_d16dst:     ; move.l (An),(d16,An) : [dstAn+d16]=read32(srcAn) (ROM-aware) ; PC+=4
    jsr rdw2
    sta $6A             ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                 ; src An slot
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    jsr readbyte        ; bits31-24
    sep #$20
    sta $6D
    rep #$20
    inc $54
    jsr readbyte        ; bits23-16
    sep #$20
    sta $6C
    rep #$20
    inc $54
    jsr readbyte        ; bits15-8
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte        ; bits7-0
    sep #$20
    sta $50
    rep #$20
    jsr regdstA         ; dst An slot
    lda $00,x
    clc
    adc $6A
    tax                 ; dst addr
    sep #$20
    lda $6D
    sta $400000,x
    inx
    lda $6C
    sta $400000,x
    inx
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_cmpiw_abs:          ; cmpi.w #imm,(xxx).L : Z=(mem.w==imm) (ROM-aware) ; PC+=8
    jsr rdw2
    sta $6A             ; imm word
    jsr rdw4
    sta $52             ; abs high16
    jsr rdw6
    sta $54             ; abs low16
    jsr readbyte        ; high byte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte        ; low byte
    sep #$20
    sta $50
    rep #$20
    lda $50             ; mem word = $51:$50
    sta $74             ; dest = mem
    lda $6A
    sta $76             ; src = imm
    jsr subflags_w
    lda $40
    clc
    adc #8
    sta $40
    jmp inext

op_moveq:              ; moveq #data8,Dn : Dn = signext(data8) ; Z ; PC+=2
    lda $44
    and #$00FF
    cmp #$0080
    bcc mvq_pos
    ora #$FF00
mvq_pos:
    sta $50             ; signext low16
    jsr regdst          ; Dn slot (bits 11-9)
    lda $50
    sta $00,x
    cmp #$8000
    bcc mvq_hipos
    lda #$FFFF
    sta $02,x
    bra mvq_z
mvq_hipos:
    stz $02,x
mvq_z:
    lda $50
    jsr setnz_w
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_clrl_dn:            ; clr.l Dn : Dn=0 ; Z=1 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    stz $00,x
    stz $02,x
    lda #$0001
    sta $60
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_cmpiw_d16:          ; cmpi.w #imm,(d16,An) : Z=(mem.w==imm) ; PC+=6
    jsr rdw2
    sta $50            ; imm word
    jsr rdw4
    sta $52            ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $52
    tax                ; addr
    sep #$20
    lda $400000,x
    sta $53            ; high byte
    inx
    lda $400000,x
    sta $52            ; low byte
    rep #$20
    lda $52            ; mem word = $53:$52
    sta $74            ; dest = mem
    lda $50
    sta $76            ; src = imm
    jsr subflags_w
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_addib_d16:          ; addi.b #imm,(d16,An) : [An+d16]+=imm.b ; Z ; PC+=6
    jsr rdw2
    and #$00FF
    sta $50            ; imm byte
    jsr rdw4
    sta $52            ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $52
    tax                ; addr
    sep #$20
    lda $400000,x
    clc
    adc $50
    sta $400000,x
    rep #$20
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_cmpw_d16_dn:        ; cmp.w (d16,An),Dn : Z=(Dn.lo == mem.w) ; PC+=4
    jsr rdw2
    sta $52            ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; An slot (bits 2-0)
    lda $00,x
    clc
    adc $52
    tax                ; addr
    sep #$20
    lda $400000,x
    sta $51            ; high byte
    inx
    lda $400000,x
    sta $50            ; low byte
    rep #$20
    jsr regdst         ; Dn slot
    lda $00,x
    sta $74            ; dest = Dn.lo
    lda $50
    sta $76            ; src = mem word
    jsr subflags_w
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_bcc:                 ; generic Bcc (cc=2..15) : disp8, or disp16 if disp8==0
    lda $44
    and #$0F00
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a               ; A = cc (2..15)
    sta $50
    stz $52             ; taken = 0
    cmp #$0002
    bne bcc_n3
    lda $6E             ; HI: !C & !Z
    ora $60
    bne bcc_e2
    inc $52
bcc_e2:
    jmp bcc_eval
bcc_n3:
    cmp #$0003
    bne bcc_n4
    lda $6E             ; LS: C | Z
    ora $60
    beq bcc_e3
    inc $52
bcc_e3:
    jmp bcc_eval
bcc_n4:
    cmp #$0004
    bne bcc_n5
    lda $6E             ; CC: !C
    bne bcc_e4
    inc $52
bcc_e4:
    jmp bcc_eval
bcc_n5:
    cmp #$0005
    bne bcc_n6
    lda $6E             ; CS: C
    beq bcc_e5
    inc $52
bcc_e5:
    jmp bcc_eval
bcc_n6:
    cmp #$0006
    bne bcc_n7
    lda $60             ; NE: !Z
    bne bcc_e6
    inc $52
bcc_e6:
    jmp bcc_eval
bcc_n7:
    cmp #$0007
    bne bcc_n8
    lda $60             ; EQ: Z
    beq bcc_e7
    inc $52
bcc_e7:
    jmp bcc_eval
bcc_n8:
    cmp #$0008
    bne bcc_n9
    lda $72             ; VC: !V
    bne bcc_e8
    inc $52
bcc_e8:
    jmp bcc_eval
bcc_n9:
    cmp #$0009
    bne bcc_nA
    lda $72             ; VS: V
    beq bcc_e9
    inc $52
bcc_e9:
    jmp bcc_eval
bcc_nA:
    cmp #$000A
    bne bcc_nB
    lda $70             ; PL: !N
    bne bcc_eA
    inc $52
bcc_eA:
    jmp bcc_eval
bcc_nB:
    cmp #$000B
    bne bcc_nv
    lda $70             ; MI: N
    beq bcc_eB
    inc $52
bcc_eB:
    jmp bcc_eval
bcc_nv:                 ; GE/LT/GT/LE : compute nv = N^V into $54
    lda $70
    eor $72
    sta $54
    lda $50
    cmp #$000C
    bne bcc_nD
    lda $54             ; GE: !(N^V)
    bne bcc_eC
    inc $52
bcc_eC:
    jmp bcc_eval
bcc_nD:
    cmp #$000D
    bne bcc_nE
    lda $54             ; LT: N^V
    beq bcc_eD
    inc $52
bcc_eD:
    jmp bcc_eval
bcc_nE:
    cmp #$000E
    bne bcc_nF
    lda $60             ; GT: !Z & !(N^V)
    ora $54
    bne bcc_eE
    inc $52
bcc_eE:
    jmp bcc_eval
bcc_nF:
    lda $60             ; LE: Z | (N^V)
    ora $54
    beq bcc_eF
    inc $52
bcc_eF:
bcc_eval:
    lda $52
    beq bcc_fall
    ; taken
    lda $44
    and #$00FF
    bne bcc_d8
    jsr rdw2            ; disp16 form
    sta $50
    jmp branch_apply     ; bank-correct PC = (PC+2) + sign_ext(disp16)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
bcc_d8:
    cmp #$0080
    bcc bcc_d8p
    ora #$FF00
bcc_d8p:
    sta $50
    jmp branch_apply     ; bank-correct PC = (PC+2) + sign_ext(disp16)
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
bcc_fall:
    lda $44
    and #$00FF
    bne bcc_f2
    lda $40             ; disp16 form not taken -> PC+=4
    clc
    adc #4
    sta $40
    jmp inext
bcc_f2:
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movb_d16_dn:        ; move.b (d16,An),Dn : Dn.b = [An+d16] (work RAM) ; PC+=4
    jsr rdw2
    sta $52            ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; src An slot
    lda $00,x
    clc
    adc $52
    tax                ; addr
    sep #$20
    lda $400000,x
    sta $50
    rep #$20
    jsr regdst         ; Dn slot
    sep #$20
    lda $50
    sta $00,x          ; Dn low byte
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_btst_dn_dn:        ; btst Dn,Dn : Z = !(srcDn bit (cntDn&31) set) ; PC+=2
    jsr regdst         ; cnt Dn slot (bits 11-9)
    lda $00,x
    and #$001F
    sta $50            ; bit number
    lda $44
    and #$0007
    asl a
    asl a
    tax                ; src Dn slot
    lda $50
    cmp #$0010
    bcs btdd_hi
    ldy $50
    lda #$0001
btdd_l:
    cpy #0
    beq btdd_lt
    asl a
    dey
    bra btdd_l
btdd_lt:
    and $00,x
    jsr setz_from_a
    bra btdd_done
btdd_hi:
    sec
    lda $50
    sbc #$0010
    tay
    lda #$0001
btdd_h:
    cpy #0
    beq btdd_ht
    asl a
    dey
    bra btdd_h
btdd_ht:
    and $02,x
    jsr setz_from_a
btdd_done:
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_addi_w:            ; addi.w #imm,Dn : Dn.lo += imm ; Z ; PC+=4
    jsr rdw2
    sta $50
    lda $44
    and #$0007
    asl a
    asl a
    tax
    clc
    lda $00,x
    adc $50
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movw_dn_an:        ; move.w Dn,(An) : [An]=Dn.lo (big-end) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50            ; Dn low16
    jsr regdstA        ; An slot
    lda $02,x          ; An.high16: route arcade video banks to the $41 shadow. THE BG-BUILD
    cmp #$00F0         ; ($2742) writes $E00800 via MOVE.W D1,(A0) -> this handler. Without
    bne mwdan_vid      ; routing it lands in $40 work RAM and the playfield never renders.
    lda $00,x
    tax                ; addr
    lda $50
    xba
    sep #$20
    sta $400000,x      ; high byte
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x      ; low byte
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext
mwdan_vid:
    lda $00,x
    sta $54            ; addr low16 (no postincrement for (An))
    lda $02,x
    sta $52            ; bank -> map_snes routes $B0/$D0/$E0 -> $41
    lda $50
    sta $80            ; value (big-end via store_vid_word)
    jsr store_vid_word
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_jmp_abs:            ; jmp (xxx).L : PC = 24-bit target (was forced to bank 0)
    jsr rdw2           ; target high16 (bank) @ PC+2
    sta $42
    jsr rdw4           ; target low16 @ PC+4
    sta $40
    jmp inext

op_jmp_d16_an:         ; jmp (d16,An) : PC = An + signext(d16) ; (RAM-resident routines)
    jsr rdw2
    sta $50            ; d16
    lda $50
    bpl jda_pos
    lda #$FFFF
    bra jda_hi
jda_pos:
    lda #$0000
jda_hi:
    sta $52            ; sign-extension high word
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; An slot
    lda $00,x
    clc
    adc $50
    sta $40            ; PC low16 = An.lo + d16
    lda $02,x
    adc $52
    and #$00FF
    sta $42            ; PC high8 (24-bit 68K addr)
    jmp inext

; idx_ea: brief-extension indexed EA (d8,An,Xn).  A = ext word, X = base An slot.
;   -> $52 = base An.high16, $54 = effective low16. (Xn added as low16; d8 sign-ext.)
idx_ea:
    sta $90              ; brief extension word
    lda $02,x
    sta $52              ; base high16
    lda $00,x
    sta $54              ; base low16
    ; add signext(d8) as a full 32-bit displacement (carry into $52)
    lda $90
    and #$00FF
    cmp #$0080
    bcs ix_d8neg
    clc
    adc $54
    sta $54
    lda $52
    adc #$0000
    sta $52
    bra ix_reg
ix_d8neg:
    ora #$FF00           ; d8 < 0 -> sign-extend low16
    clc
    adc $54
    sta $54
    lda $52
    adc #$FFFF           ; + high sign extension (-1) with carry
    sta $52
ix_reg:
    lda $90
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #$001C           ; (regnum)*4
    sta $92
    lda $90
    and #$8000
    beq ix_data
    lda $92
    clc
    adc #$0020           ; An region
    sta $92
ix_data:
    ldx $92
    lda $90
    and #$0800           ; bit 11: 0 = word index (sign-extend), 1 = long index
    bne ix_long
    lda $00,x            ; index reg low16
    bmi ix_wneg
    clc
    adc $54
    sta $54
    lda $52
    adc #$0000
    sta $52
    rts
ix_wneg:
    clc
    adc $54
    sta $54
    lda $52
    adc #$FFFF
    sta $52
    rts
ix_long:
    lda $00,x            ; full 32-bit index
    clc
    adc $54
    sta $54
    lda $02,x
    adc $52
    sta $52
    rts

; --- memory WRITE helpers (mirror readbyte's decode): addr hi16 $52, lo16 $54.
;     Only 68K work RAM $00F0xxxx writes (-> $7F:xxxx); ROM/I/O writes no-op.
;     Data: writebyte uses $80(low byte); writeword $80(word, big-endian);
;     writelong $80(lo16)/$82(hi16) (big-endian 4 bytes). Caller is 16-bit (rep).
writebyte:
    lda $52
    cmp #$00F0
    bne wb_io
    ldx $54
    sep #$20
    lda $80
    sta $400000,x
    rep #$20
wb_done:
    rts
wb_io:
    cmp #$0090           ; C-Chip space $900000-$9007FF is SHARED RAM (the game uses it as
    bne wb_vid           ; scratch: e.g. the start handshake BSET/BTST $900007). Back it with
    lda $54              ; BW-RAM $41:F000+lo16 so writes persist and read back. $900C01 also
    cmp #$0C01           ; sets $62 (command selector). (The C-Chip overlays inputs $900001/3/5
    bne wb_ram           ; + signature on READ; those reads ignore this RAM -- see rb_data.)
    sep #$20
    lda $80
    sta $62              ; command port
    rep #$20
    rts
wb_ram:
    ldx $54
    sep #$20
    lda $80
    sta $41F000,x        ; C-Chip shared RAM
    rep #$20
    rts
wb_vid:
    jmp store_vid_byte   ; $B0/$D0/$E0 -> $41 shadow (else dropped); rts to caller
writeword:
    lda $52
    cmp #$00F0
    bne ww_vid
    ldx $54
    sep #$20
    lda $81              ; high byte first (big-endian)
    sta $400000,x
    inx
    lda $80              ; low byte
    sta $400000,x
    rep #$20
ww_done:
    rts
ww_vid:
    jmp store_vid_word   ; $B0/$D0/$E0 -> $41 shadow (else dropped); rts to caller
writelong:
    lda $52
    cmp #$00F0
    bne wl_vid
    ldx $54
    sep #$20
    lda $83              ; bits 31-24
    sta $400000,x
    inx
    lda $82              ; bits 23-16
    sta $400000,x
    inx
    lda $81              ; bits 15-8
    sta $400000,x
    inx
    lda $80              ; bits 7-0
    sta $400000,x
    rep #$20
wl_done:
    rts
wl_vid:
    jmp store_vid_long   ; $B0/$D0/$E0 -> $41 shadow (else dropped); rts to caller

op_movw_dn_dn:         ; move.w Dn,Dn : dst.lo = src.lo ; Z ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50
    jsr regdst
    lda $50
    sta $00,x
    jsr setnz_w
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_or_w_d16:           ; or.w (d16,An),Dn : Dn.lo |= [An+d16].w ; Z ; PC+=4
    jsr rdw2
    sta $52            ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; An slot
    lda $00,x
    clc
    adc $52
    tax                ; src addr low16
    sep #$20
    lda $400000,x      ; bits15-8
    sta $51
    inx
    lda $400000,x      ; bits7-0
    sta $50
    rep #$20
    jsr regdst         ; dst Dn slot
    lda $50            ; word value $51:$50
    ora $00,x
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_add_w:              ; add.w Dn,Dn : dst.lo += src.lo ; Z ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50            ; src.lo
    jsr regdst
    clc
    lda $00,x
    adc $50
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_ori_w_dn:           ; ori.w #imm,Dn : Dn.lo |= imm ; Z ; PC+=4
    jsr rdw2
    sta $50
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    ora $50
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_swap:               ; swap Dn : swap high/low 16 ; Z ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    pha
    lda $02,x
    sta $00,x
    pla
    sta $02,x
    ora $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_bset_dn_dn:         ; bset Dn,Dn : Z=!(bit); set bit (cntDn&31) in dstDn ; PC+=2
    jsr regdst         ; cnt Dn slot (bits 11-9)
    lda $00,x
    and #$001F
    sta $50            ; bit number
    lda $44
    and #$0007
    asl a
    asl a
    tax                ; dst Dn slot
    ; build 32-bit mask 1<<bit into $94(lo)/$96(hi)
    stz $94
    stz $96
    lda $50
    cmp #$0010
    bcs bs_hi
    ldy $50
    lda #$0001
bs_ls:
    cpy #0
    beq bs_lset
    asl a
    dey
    bra bs_ls
bs_lset:
    sta $94
    bra bs_test
bs_hi:
    sec
    lda $50
    sbc #$0010
    tay
    lda #$0001
bs_hs:
    cpy #0
    beq bs_hset
    asl a
    dey
    bra bs_hs
bs_hset:
    sta $96
bs_test:
    ; Z = !(dst & mask)
    lda $00,x
    and $94
    sta $50
    lda $02,x
    and $96
    ora $50
    jsr setz_from_a
    ; set the bit
    lda $00,x
    ora $94
    sta $00,x
    lda $02,x
    ora $96
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movl_dn_an:         ; move.l Dn,(An) : [An]=Dn (32, work RAM big-end) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50
    lda $02,x
    sta $52
    jsr regdstA
    lda $00,x
    tax
    sep #$20
    lda $53
    sta $400000,x
    inx
    lda $52
    sta $400000,x
    inx
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

; usmul: $50 * $52 (unsigned 16x16) -> $94(lo16):$96(hi16)
usmul:
    stz $94
    stz $96
    lda $50
    sta $98
    stz $9A
um_loop:
    lda $52
    beq um_done
    lsr a
    sta $52
    bcc um_skip
    clc
    lda $94
    adc $98
    sta $94
    lda $96
    adc $9A
    sta $96
um_skip:
    asl $98
    rol $9A
    bra um_loop
um_done:
    rts

; udiv: dividend $50(lo16):$52(hi16) / divisor $54 -> quot $50:$52, rem $94
udiv:
    stz $94
    ldy #$0020
ud_l:
    asl $50
    rol $52
    rol $94
    bcs ud_sub
    lda $94
    cmp $54
    bcc ud_no
ud_sub:
    lda $94
    sec
    sbc $54
    sta $94
    inc $50
ud_no:
    dey
    bne ud_l
    rts

op_muls_w:             ; muls.w #imm,Dn : Dn = signext(Dn.lo)*signext(imm) ; Z ; PC+=4
    jsr rdw2
    sta $52            ; b
    jsr regdst
    lda $00,x
    sta $50            ; a
    stz $90
    lda $50
    bpl ms_apos
    sec
    lda #$0000
    sbc $50
    sta $50
    inc $90
ms_apos:
    lda $52
    bpl ms_bpos
    sec
    lda #$0000
    sbc $52
    sta $52
    inc $90
ms_bpos:
    jsr usmul          ; $94:$96
    lda $90
    and #$0001
    beq ms_pos
    sec
    lda #$0000
    sbc $94
    sta $94
    lda #$0000
    sbc $96
    sta $96
ms_pos:
    jsr regdst
    lda $94
    sta $00,x
    lda $96
    sta $02,x
    ora $94
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_divs_w:             ; divs.w #imm,Dn : Dn.lo=quot, Dn.hi=rem ; Z ; PC+=4
    jsr rdw2
    sta $54            ; divisor
    jsr regdst
    lda $00,x
    sta $50            ; dividend lo16
    lda $02,x
    sta $52            ; dividend hi16
    stz $90            ; quot sign
    stz $92            ; rem sign
    lda $52
    bpl dv_dpos
    sec
    lda #$0000
    sbc $50
    sta $50
    lda #$0000
    sbc $52
    sta $52
    inc $90
    inc $92
dv_dpos:
    lda $54
    bpl dv_spos
    sec
    lda #$0000
    sbc $54
    sta $54
    inc $90
dv_spos:
    jsr udiv           ; quot $50:$52, rem $94
    lda $90
    and #$0001
    beq dv_qpos
    sec
    lda #$0000
    sbc $50
    sta $50
dv_qpos:
    lda $92
    beq dv_rpos
    sec
    lda #$0000
    sbc $94
    sta $94
dv_rpos:
    jsr regdst
    lda $50
    sta $00,x
    lda $94
    sta $02,x
    lda $50
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_cmpa_l_idx:         ; cmpa.l (d8,An,Xn),An : An - mem(32) sets C/Z/N ; PC+=4
    jsr rdw2
    sta $90
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $90
    jsr idx_ea
    jsr rd32           ; $50=mem lo16, $6A=mem hi16
    jsr regdstA
    sec
    lda $00,x
    sbc $50
    sta $94
    lda $02,x
    sbc $6A
    sta $96
    bcs cai_noc
    lda #$0001
    sta $6E
    bra cai_z
cai_noc:
    stz $6E
cai_z:
    lda $94
    ora $96
    jsr setz_from_a
    lda $96
    and #$8000
    beq cai_np
    lda #$0001
    sta $70
    bra cai_d
cai_np:
    stz $70
cai_d:
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_idx_d16:       ; move.l (d8,An,Xn),(d16,An) : [dstAn+d16]=read32(ea) ; PC+=6
    jsr rdw2
    sta $90            ; index ext
    jsr rdw4
    sta $6E            ; dst d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $90
    jsr idx_ea
    jsr rd32           ; $50=lo16,$6A=hi16
    jsr regdstA
    lda $00,x
    clc
    adc $6E
    tax
    sep #$20
    lda $6B
    sta $400000,x
    inx
    lda $6A
    sta $400000,x
    inx
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_bchg_dn_d16:        ; bchg Dn,(d16,An) : toggle bit (Dn&7) in [An+d16].b ; Z=old ; PC+=4
    jsr rdw2
    sta $52            ; d16
    jsr regdst
    lda $00,x
    and #$0007
    sta $50            ; bit
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $52
    tax                ; addr
    stx $54            ; save addr
    sep #$20
    lda $400000,x
    sta $52            ; byte
    rep #$20
    ldy $50
    lda #$0001
bcd_sh:
    cpy #0
    beq bcd_t
    asl a
    dey
    bra bcd_sh
bcd_t:
    sta $56            ; mask
    and $52
    jsr setz_from_a
    lda $52
    eor $56            ; toggle
    ldx $54
    sep #$20
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_lsr_l_dn:           ; lsr.l Dn,Dn : Dn(32) >>= (cntDn & 63) logical ; Z ; PC+=2
    jsr regdst
    lda $00,x
    and #$003F
    sta $50            ; count
    lda $44
    and #$0007
    asl a
    asl a
    tax
lsl_l_loop:
    lda $50
    beq lsl_l_done
    lsr $02,x
    ror $00,x
    dec $50
    bra lsl_l_loop
lsl_l_done:
    lda $00,x
    ora $02,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_ori_w_idx:          ; ori.w #imm,(d8,An,Xn) : [ea].w |= imm (work RAM) ; Z ; PC+=6
    jsr rdw2
    sta $6E            ; imm
    jsr rdw4
    sta $90            ; index ext
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $90
    jsr idx_ea         ; $54=ea low16
    ldx $54
    sep #$20
    lda $400000,x
    sta $51
    inx
    lda $400000,x
    sta $50
    rep #$20
    lda $50
    ora $6E
    sta $50
    jsr setz_from_a
    ldx $54
    sep #$20
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_lea_idx:            ; lea (d8,An,Xn),An : dstAn = ea (with base An.high16) ; PC+=4
    jsr rdw2
    sta $90
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $90
    jsr idx_ea         ; -> $52=hi16, $54=lo16
    jsr regdstA
    lda $54
    sta $00,x
    lda $52
    sta $02,x
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_dn_idx:        ; move.l Dn,(d8,An,Xn) : [ea]=Dn (32, work RAM big-end) ; PC+=4
    jsr rdw2
    sta $90            ; ext (idx_ea re-reads from A; pass via A)
    lda $44
    and #$0007
    asl a
    asl a
    tax                ; src Dn slot
    lda $00,x
    sta $50            ; Dn low16
    lda $02,x
    sta $58            ; Dn high16 (temp)
    jsr regdstA        ; dst base An slot -> X
    lda $90
    jsr idx_ea         ; -> $54 = ea low16
    ldx $54
    sep #$20
    lda $59            ; Dn bits31-24 (high byte of $58)
    sta $400000,x
    inx
    lda $58            ; bits23-16
    sta $400000,x
    inx
    lda $51            ; bits15-8
    sta $400000,x
    inx
    lda $50            ; bits7-0
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_an_idx:        ; move.l An,(d8,An,Xn) : [ea]=An (32, work RAM) ; PC+=4
    jsr rdw2
    sta $90
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; src An slot
    lda $00,x
    sta $50
    lda $02,x
    sta $58
    jsr regdstA        ; dst base An slot
    lda $90
    jsr idx_ea
    ldx $54
    sep #$20
    lda $59
    sta $400000,x
    inx
    lda $58
    sta $400000,x
    inx
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movea_l_idx:        ; movea.l (d8,An,Xn),An : dst = [ea] (32, ROM-aware) ; PC+=4
    jsr rdw2
    sta $90
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; src base An slot
    lda $90
    jsr idx_ea         ; -> $52=high16, $54=low16
    jsr readbyte
    sep #$20
    sta $59
    rep #$20
    inc $54
    jsr readbyte
    sep #$20
    sta $58
    rep #$20
    inc $54
    jsr readbyte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte
    sep #$20
    sta $50
    rep #$20
    jsr regdstA        ; dst An slot
    lda $50
    sta $00,x          ; low16 = $51:$50
    lda $58
    sta $02,x          ; high16 = $59:$58
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_d16_pre:       ; move.l (d16,An),-(An) : dst An-=4; [dst]=[srcAn+d16] (32, $7F) ; PC+=4
    jsr rdw2
    sta $52            ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; src An slot
    lda $00,x
    clc
    adc $52
    tax                ; src addr ($7F)
    sep #$20
    lda $400000,x
    sta $59
    inx
    lda $400000,x
    sta $58
    inx
    lda $400000,x
    sta $51
    inx
    lda $400000,x
    sta $50
    rep #$20
    jsr regdstA        ; dst An slot
    lda $00,x
    sec
    sbc #4
    sta $00,x
    tax                ; dst addr
    sep #$20
    lda $59
    sta $400000,x
    inx
    lda $58
    sta $400000,x
    inx
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_d16_dn:        ; move.l (d16,An),Dn : Dn = [An+d16] (32, work RAM) ; PC+=4
    jsr rdw2
    sta $52            ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; src An slot
    lda $00,x
    clc
    adc $52
    tax                ; src addr low16 (An assumed $F0xxxx -> $7F)
    sep #$20
    lda $400000,x
    sta $53            ; bits 31-24
    inx
    lda $400000,x
    sta $52            ; bits 23-16
    inx
    lda $400000,x
    sta $55            ; bits 15-8
    inx
    lda $400000,x
    sta $54            ; bits 7-0
    rep #$20
    jsr regdst         ; X = dest Dn slot (bits 11-9)
    lda $54
    sta $00,x          ; low16 = $55:$54
    lda $52
    sta $02,x          ; high16 = $53:$52
    lda $54
    ora $52
    jsr setz_from_a    ; move.l sets Z from the 32-bit value
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_dn_d16:        ; move.l Dn,(d16,An) : [An+d16]=Dn (32, work RAM); Z ; PC+=4
    jsr rdw2
    sta $52            ; d16
    lda $44
    and #$0007
    asl a
    asl a
    tax                ; src Dn slot
    lda $00,x
    sta $54            ; Dn low16
    lda $02,x
    sta $56            ; Dn high16
    jsr regdstA        ; X = dst An slot (bits 11-9)
    lda $02,x
    cmp #$00F0
    bne mldd_skip      ; non-work-RAM -> no-op write
    lda $00,x
    clc
    adc $52
    tax                ; dst addr
    sep #$20
    lda $57
    sta $400000,x      ; bits31-24
    inx
    lda $56
    sta $400000,x      ; bits23-16
    inx
    lda $55
    sta $400000,x      ; bits15-8
    inx
    lda $54
    sta $400000,x      ; bits7-0
    rep #$20
mldd_skip:
    lda $54
    ora $56
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movl_reg_pre:       ; move.l Dn/An,-(An) : push 32-bit register ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    sta $52            ; src reg*4 (Dn slot)
    lda $44
    and #$0038
    cmp #$0008         ; source mode 001 = An?
    bne mrp_src
    lda $52
    clc
    adc #$0020
    sta $52            ; -> An slot
mrp_src:
    ldx $52
    lda $00,x
    sta $54            ; src low16
    lda $02,x
    sta $56            ; src high16
    jsr regdst         ; X = (bits 11-9)*4
    txa
    clc
    adc #$0020
    tax                ; dest An slot
    lda $00,x
    sec
    sbc #4
    sta $00,x          ; An -= 4
    tax                ; An low16 -> work-RAM offset
    sep #$20
    lda $57            ; bits 31-24
    sta $400000,x
    inx
    lda $56            ; bits 23-16
    sta $400000,x
    inx
    lda $55            ; bits 15-8
    sta $400000,x
    inx
    lda $54            ; bits 7-0
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movl_an_pre:        ; move.l (An),-(An) : dst An-=4; [dst]=[srcAn] (32, $7F) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; src An slot
    lda $00,x
    tax                ; src addr
    sep #$20
    lda $400000,x
    sta $59
    inx
    lda $400000,x
    sta $58
    inx
    lda $400000,x
    sta $51
    inx
    lda $400000,x
    sta $50
    rep #$20
    jsr regdstA
    lda $00,x
    sec
    sbc #4
    sta $00,x
    tax
    sep #$20
    lda $59
    sta $400000,x
    inx
    lda $58
    sta $400000,x
    inx
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

; rd32: read 32-bit big-endian via readbyte from $52(hi16)/$54(lo16) (advances $54)
;   -> $50 = low16 ($51:$50), $6A = high16 ($6B:$6A)
rd32:
    jsr readbyte
    sep #$20
    sta $6B
    rep #$20
    inc $54
    jsr readbyte
    sep #$20
    sta $6A
    rep #$20
    inc $54
    jsr readbyte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte
    sep #$20
    sta $50
    rep #$20
    rts

op_movb_d16_d16:       ; move.b (d16,An),(d16,An) : work RAM ; PC+=6
    jsr rdw2
    sta $50            ; src d16
    jsr rdw4
    sta $52            ; dst d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $50
    tax
    sep #$20
    lda $400000,x
    sta $54
    rep #$20
    jsr regdstA
    lda $00,x
    clc
    adc $52
    tax
    sep #$20
    lda $54
    sta $400000,x
    rep #$20
    lda $54
    and #$00FF
    jsr setnz_b      ; move.b sets Z from the moved byte (was missing -> $06CE bne mis-fell-through)
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_movw_d16_d16:       ; move.w (d16,An),(d16,An): ROM-aware src -> jmp to v2 (free block)
    jmp op_mw_d16d16_v2
    sta $50            ; src d16 (dead tail; kept to avoid shifting following handlers)
    jsr rdw4
    sta $52            ; dst d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; src An slot
    lda $00,x
    clc
    adc $50
    tax                ; src addr
    sep #$20
    lda $400000,x      ; src bits15-8
    sta $55
    inx
    lda $400000,x      ; src bits7-0
    sta $54
    rep #$20
    jsr regdstA        ; dst An slot
    lda $00,x
    clc
    adc $52
    tax                ; dst addr
    sep #$20
    lda $55
    sta $400000,x      ; high byte
    inx
    lda $54
    sta $400000,x      ; low byte
    rep #$20
    lda $54
    jsr setz_from_a
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_movl_an_an:         ; move.l An,(An) : [dstAn]=srcAn (32, work RAM) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    sta $50
    lda $02,x
    sta $52
    jsr regdstA
    lda $00,x
    tax
    sep #$20
    lda $53
    sta $400000,x
    inx
    lda $52
    sta $400000,x
    inx
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movl_an_dn:         ; move.l (An),Dn : Dn = [srcAn] (32, ROM-aware) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    jsr rd32
    jsr regdst
    lda $50
    sta $00,x
    lda $6A
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movl_an2dn:         ; move.l An,Dn : Dn = srcAn (32) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    sta $50
    lda $02,x
    sta $52
    jsr regdst
    lda $50
    sta $00,x
    lda $52
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movea_l_an:         ; movea.l (An),An : dstAn = [srcAn] (32, ROM-aware) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    jsr rd32
    jsr regdstA
    lda $50
    sta $00,x
    lda $6A
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movb_anp_dn:        ; move.b (An)+,Dn : Dn.b=[srcAn] (ROM-aware); An+=1 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    inc a
    sta $00,x
    jsr readbyte
    and #$00FF
    sta $50
    jsr regdst
    sep #$20
    lda $50
    sta $00,x
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movw_dn_anp:        ; move.w Dn,(An)+ : [An]=Dn.lo (big-end); An+=2 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50
    jsr regdstA
    lda $02,x          ; An.high16: route arcade video banks to the $41 shadow (sprite builders)
    cmp #$00F0
    bne mwdanp_vid
    lda $00,x
    sta $52
    clc
    adc #2
    sta $00,x
    ldx $52
    lda $50
    xba
    sep #$20
    sta $400000,x
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext
mwdanp_vid:
    lda $00,x
    sta $54            ; addr low16
    clc
    adc #2
    sta $00,x          ; An += 2
    lda $02,x
    sta $52            ; bank
    lda $50
    sta $80            ; value
    jsr store_vid_word
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movw_pre_pre:       ; move.w -(An),-(An) : src/dst predecrement (work RAM) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    sec
    sbc #2
    sta $00,x
    tax
    sep #$20
    lda $400000,x
    sta $51
    inx
    lda $400000,x
    sta $50
    rep #$20
    jsr regdstA
    lda $00,x
    sec
    sbc #2
    sta $00,x
    tax
    sep #$20
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_subw_anp_dn:        ; sub.w (An)+,Dn : Dn.lo -= [srcAn].w (ROM-aware); An+=2; Z ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    lda $54
    clc
    adc #2
    sta $00,x
    jsr readbyte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte
    sep #$20
    sta $50
    rep #$20
    lda $50
    sta $74              ; src = mem.w
    stz $76
    jsr regdst
    lda $00,x
    sta $80              ; dest = Dn.w
    stz $82
    lda #$0001
    sta $5E              ; word -> full N/Z/V/C
    jsr subflags         ; $80 = Dn - mem
    lda $6E
    sta $A2              ; X = C
    jsr regdst
    lda $80
    sta $00,x            ; Dn.w = result (high word preserved)
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movw_imm_anp:       ; move.w #imm,(An)+ : [An]=imm (big-end); An+=2 ; PC+=4
    jsr rdw2
    sta $50
    jsr regdstA
    lda $00,x
    sta $52
    clc
    adc #2
    sta $00,x
    ldx $52
    lda $50
    xba
    sep #$20
    sta $400000,x
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_movw_dn_abs:        ; move.w Dn,(xxx).L : work RAM ($F0) write; else I/O no-op ; PC+=6
    jsr rdw2
    sta $52
    jsr rdw4
    sta $54
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $50
    lda $54
    sta $6A              ; dst lo16
    lda $52
    jsr map_snes         ; -> $C2 mode, $6A = SNES offset
    lda $C2
    cmp #$0002
    beq mwa_io           ; no-op (e.g. $30/$40/$60 ctrl strobes)
    cmp #$0001
    beq mwa_shadow       ; shadow $7E
    ldx $6A              ; work RAM $7F
    lda $50
    xba
    sep #$20
    sta $400000,x
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x
    rep #$20
    bra mwa_io
mwa_shadow:
    ldx $6A
    lda $50
    xba
    sep #$20
    sta $410000,x        ; high byte (video shadow)
    rep #$20
    inx
    lda $50
    sep #$20
    sta $410000,x        ; low byte
    rep #$20
mwa_io:
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_clrb_dn:            ; clr.b Dn : Dn.lobyte=0; Z=1 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    sep #$20
    stz $00,x
    rep #$20
    lda #$0001
    sta $60
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_clrb_d16:           ; clr.b (d16,An) : [An+d16]=0; Z=1 ; PC+=4
    jsr rdw2
    sta $52
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $52
    tax
    sep #$20
    stz $400000,x
    rep #$20
    lda #$0001
    sta $60
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_clrw_anp:           ; clr.w (An)+ : [An]=0 (work RAM only); An+=2; Z=1 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; X = An slot
    lda $02,x          ; An high16
    cmp #$00F0
    bne caw_noff       ; non-work-RAM (video/I-O) target -> no-op the write
    lda $00,x          ; An low16
    phx                ; save An slot
    tax                ; X = work-RAM offset
    sep #$20
    stz $400000,x
    inx
    stz $400000,x
    rep #$20
    plx                ; restore An slot
caw_noff:
    lda $00,x
    clc
    adc #2
    sta $00,x          ; An += 2
    lda #$0001
    sta $60            ; Z = 1
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_clrw_pre:           ; clr.w -(An) : An-=2; [An]=0; Z=1 ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    sec
    sbc #2
    sta $00,x
    tax
    sep #$20
    stz $400000,x
    inx
    stz $400000,x
    rep #$20
    lda #$0001
    sta $60
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_tstb_d16:           ; tst.b (d16,An) : Z=([An+d16].b==0) ; PC+=4
    jsr rdw2
    sta $52
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $52
    tax
    sep #$20
    lda $400000,x
    rep #$20
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_tstw_d16:           ; tst.w (d16,An) : Z=([An+d16].w==0) ; PC+=4
    jsr rdw2
    sta $52
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $52
    tax
    sep #$20
    lda $400000,x
    sta $51
    inx
    lda $400000,x
    sta $50
    rep #$20
    lda $50
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_ext_w:              ; ext.w Dn : sign-extend Dn.b -> Dn.w ; Z ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    and #$00FF
    cmp #$0080
    bcc ext_pos
    ora #$FF00
ext_pos:
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_jsr_an:             ; jsr (An) : push PC+2; PC = An.low16 ; (bank 0)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    sta $52            ; target low16
    lda $02,x
    sta $50            ; target high16 (An bank) -- was discarded (stz $42)
    lda $40
    clc
    adc #2
    sta $54            ; return = PC+2
    jsr push32r
    lda $52
    sta $40
    lda $50
    sta $42            ; PC bank = An bank
    jmp inext

op_cmpiw_dn:           ; cmpi.w #imm,Dn : full CCR ; PC+=4
    jsr rdw2
    sta $76            ; src = imm
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $74            ; dest = Dn.lo
    jsr subflags_w
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_orib_dn:            ; ori.b #imm,Dn : Dn.b |= imm ; Z ; PC+=4
    jsr rdw2
    and #$00FF
    sta $50
    lda $44
    and #$0007
    asl a
    asl a
    tax
    sep #$20
    lda $00,x
    ora $50
    sta $00,x
    rep #$20
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_orib_an:            ; ori.b #imm,(An) : [An].b |= imm (work RAM) ; Z ; PC+=4
    jsr rdw2
    and #$00FF
    sta $50
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    tax
    sep #$20
    lda $400000,x
    ora $50
    sta $400000,x
    rep #$20
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_bclr_imm_dn:        ; bclr #bit,Dn : Z=!(bit); clear bit (mod 32) ; PC+=4
    jsr rdw2
    and #$001F
    sta $50
    lda $44
    and #$0007
    asl a
    asl a
    tax
    stz $94
    stz $96
    lda $50
    cmp #$0010
    bcs bc_hi
    ldy $50
    lda #$0001
bc_ls:
    cpy #0
    beq bc_lset
    asl a
    dey
    bra bc_ls
bc_lset:
    sta $94
    bra bc_test
bc_hi:
    sec
    lda $50
    sbc #$0010
    tay
    lda #$0001
bc_hs:
    cpy #0
    beq bc_hset
    asl a
    dey
    bra bc_hs
bc_hset:
    sta $96
bc_test:
    lda $00,x
    and $94
    sta $50
    lda $02,x
    and $96
    ora $50
    jsr setz_from_a
    lda $94
    eor #$FFFF
    and $00,x
    sta $00,x
    lda $96
    eor #$FFFF
    and $02,x
    sta $02,x
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_addq_w:             ; addq.w #data,Dn : Dn.lo += data(1-8) ; Z ; PC+=2
    jsr addq_data
    lda $44
    and #$0007
    asl a
    asl a
    tax
    clc
    lda $00,x
    adc $50
    sta $00,x
    jsr setz_from_a
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_addq_l:             ; addq.l #data,An : An += data(1-8) (32) ; PC+=2
    jsr addq_data
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    clc
    lda $00,x
    adc $50
    sta $00,x
    lda $02,x
    adc #$0000
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_addq_w_d16:         ; addq.w #data,(d16,An) : [An+d16].w += data ; Z ; PC+=4
    jsr addq_data
    jsr rdw2
    sta $52
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $52
    sta $52            ; addr
    tax
    sep #$20
    lda $400000,x
    sta $55
    inx
    lda $400000,x
    sta $54
    rep #$20
    lda $54
    clc
    adc $50
    sta $54
    jsr setz_from_a
    ldx $52
    sep #$20
    lda $55
    sta $400000,x
    inx
    lda $54
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_subq_w_d16:         ; subq.w #data,(d16,An) : [An+d16].w -= data ; Z ; PC+=4
    jsr addq_data
    jsr rdw2
    sta $52
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $52
    sta $52
    tax
    sep #$20
    lda $400000,x
    sta $55
    inx
    lda $400000,x
    sta $54
    rep #$20
    sec
    lda $54
    sbc $50
    sta $54
    jsr setz_from_a
    ldx $52
    sep #$20
    lda $55
    sta $400000,x
    inx
    lda $54
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

addq_data:             ; -> $50 = addq/subq #data (bits 11-9; 0 means 8)
    lda $44
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
    bne ad_ok
    lda #$0008
ad_ok:
    sta $50
    rts

op_tstw_abs:           ; tst.w (xxx).L : Z=(mem.w==0) (ROM-aware) ; PC+=6
    jsr rdw2
    sta $52
    jsr rdw4
    sta $54
    jsr readbyte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte
    sep #$20
    sta $50
    rep #$20
    lda $50
    jsr setz_from_a
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_btst_imm_abs:       ; btst #bit,(xxx).L : Z=!(byte bit) (I/O/ROM-aware) ; PC+=8
    jsr rdw2
    and #$0007
    sta $50            ; bit mod 8
    jsr rdw4
    sta $52
    jsr rdw6
    sta $54
    jsr readbyte
    and #$00FF
    sta $52            ; byte
    ldy $50
    lda #$0001
bia_sh:
    cpy #0
    beq bia_t
    asl a
    dey
    bra bia_sh
bia_t:
    and $52
    jsr setz_from_a
    lda $40
    clc
    adc #8
    sta $40
    jmp inext

op_movl_imm_abs:       ; move.l #imm,(xxx).L : work RAM ($F0) write; else I/O no-op ; PC+=10
    jsr rdw2
    sta $50            ; imm hi16
    jsr rdw4
    sta $52            ; imm lo16
    jsr rdw6
    sta $54            ; abs hi16
    ldy #$0008
    lda [$56],y
    xba
    sta $58            ; abs lo16
    lda $54
    cmp #$00F0
    bne mia_io
    ldx $58
    sep #$20
    lda $51
    sta $400000,x
    inx
    lda $50
    sta $400000,x
    inx
    lda $53
    sta $400000,x
    inx
    lda $52
    sta $400000,x
    rep #$20
mia_io:
    lda $40
    clc
    adc #$000A
    sta $40
    jmp inext

op_movw_an_dn:         ; move.w (An),Dn : Dn.lo = [An] (big-end, ROM-aware) ; PC+=2
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    jsr readbyte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte
    sep #$20
    sta $50
    rep #$20
    jsr regdst
    lda $50
    sta $00,x
    lda $40
    clc
    adc #2
    sta $40
    jmp inext

op_movb_imm_d16:       ; move.b #imm,(d16,An) : [An+d16]=imm.b (work RAM) ; PC+=6
    jsr rdw2
    and #$00FF
    sta $50            ; imm byte
    jsr rdw4
    sta $52            ; d16
    jsr regdstA
    lda $00,x
    clc
    adc $52
    tax
    sep #$20
    lda $50
    sta $400000,x
    rep #$20
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_movl_imm_pre:       ; move.l #imm,-(An) : An-=4; [An]=imm32 (big-end) ; PC+=6
    jsr rdw2
    sta $50            ; imm high16
    jsr rdw4
    sta $52            ; imm low16
    jsr regdstA
    lda $00,x
    sec
    sbc #4
    sta $00,x
    tax                ; An addr
    sep #$20
    lda $51
    sta $400000,x      ; bits31-24
    inx
    lda $50
    sta $400000,x      ; bits23-16
    inx
    lda $53
    sta $400000,x      ; bits15-8
    inx
    lda $52
    sta $400000,x      ; bits7-0
    rep #$20
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

op_trap:               ; TRAP #n : push PC+2 + SR ; PC = vector[32+n] ($80+n*4); mask unchanged
    lda $40
    clc
    adc #2
    sta $50            ; retPC low16
    lda $42
    adc #0
    and #$00FF
    sta $52            ; retPC high16
    lda $3C
    sec
    sbc #4
    sta $3C
    tax
    sep #$20
    stz $400000,x      ; 31-24 = 0
    inx
    lda $52
    sta $400000,x      ; 23-16
    inx
    lda $51
    sta $400000,x      ; 15-8
    inx
    lda $50
    sta $400000,x      ; 7-0
    rep #$20
    jsr sr_build
    sta $50
    lda $3C
    dec a
    dec a
    sta $3C
    tax
    lda $50
    xba
    sep #$20
    sta $400000,x      ; SR hi
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x      ; SR lo
    rep #$20
    ; read vector[32+n] from ROM (table at $0)
    lda $44
    and #$000F
    asl a
    asl a
    clc
    adc #$0080
    sta $54            ; vector addr low16
    stz $52            ; high16 = 0
    jsr readbyte       ; 31-24 (ignored)
    inc $54
    jsr readbyte       ; 23-16
    sep #$20
    sta $42
    stz $43
    rep #$20
    inc $54
    jsr readbyte       ; 15-8
    sep #$20
    sta $41
    rep #$20
    inc $54
    jsr readbyte       ; 7-0
    sep #$20
    sta $40
    rep #$20
    jmp inext

op_movem_abs:          ; movem.l (xxx).L,<list> : load regs from abs (ROM-aware) ; PC+=8
    jsr rdw2
    sta $50              ; mask (bit0=D0..bit15=A7)
    jsr rdw4
    sta $52              ; abs high16 (readbyte src high)
    jsr rdw6
    sta $54              ; abs low16 (running)
    ldy #$0000
mab_loop:
    lda $50
    lsr a
    sta $50
    bcc mab_skip
    jsr readbyte         ; bits31-24
    sep #$20
    sta $8F
    rep #$20
    inc $54
    jsr readbyte         ; bits23-16
    sep #$20
    sta $8E
    rep #$20
    inc $54
    jsr readbyte         ; bits15-8
    sep #$20
    sta $8D
    rep #$20
    inc $54
    jsr readbyte         ; bits7-0
    sep #$20
    sta $8C
    rep #$20
    inc $54
    tya
    asl a
    asl a
    tax                  ; reg slot = i*4
    lda $8C              ; low16 = $8D:$8C
    sta $00,x
    lda $8E              ; high16 = $8F:$8E
    sta $02,x
mab_skip:
    iny
    cpy #$0010
    bne mab_loop
    lda $40
    clc
    adc #8
    sta $40
    jmp inext

op_ori_sr:             ; ori #imm,SR : SR |= imm ; PC+=4
    jsr rdw2
    sta $50
    jsr sr_build
    ora $50
    jsr sr_apply
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_andi_sr:            ; andi #imm,SR : SR &= imm ; PC+=4
    jsr rdw2
    sta $50
    jsr sr_build
    and $50
    jsr sr_apply
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_ori_ccr:            ; ori #imm,CCR : CCR |= imm8 (imm high byte 0 -> mask kept) ; PC+=4
    jsr rdw2
    and #$00FF
    sta $50
    jsr sr_build
    ora $50
    jsr sr_apply
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_andi_ccr:           ; andi #imm,CCR : CCR &= imm8 (preserve mask/S) ; PC+=4
    jsr rdw2
    ora #$FF00          ; keep high byte (mask/S) when ANDing
    sta $50
    jsr sr_build
    and $50
    jsr sr_apply
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_eori_ccr:           ; eori #imm,CCR : CCR ^= imm8 ; PC+=4
    jsr rdw2
    and #$00FF          ; only CCR bits
    sta $50
    jsr sr_build
    eor $50
    jsr sr_apply
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_eori_sr:            ; eori #imm,SR : SR ^= imm ; PC+=4
    jsr rdw2
    sta $50
    jsr sr_build
    eor $50
    jsr sr_apply
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_move_imm_sr:        ; move #imm,SR : SR = imm ; PC+=4
    jsr rdw2
    jsr sr_apply
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

op_rte:                ; rte : SR = pop.w ; PC = pop.l
    ldx $3C
    sep #$20
    lda $400000,x        ; SR hi byte
    sta $51
    inx
    lda $400000,x        ; SR lo byte
    sta $50
    rep #$20
    lda $50              ; $51:$50 = SR word
    jsr sr_apply
    lda $3C
    clc
    adc #2
    sta $3C
    ldx $3C
    sep #$20
    lda $400000,x        ; PC bits31-24 (ignored)
    inx
    lda $400000,x        ; bits23-16
    sta $42
    stz $43              ; PC high16 top byte = 0
    inx
    lda $400000,x        ; bits15-8
    sta $41
    inx
    lda $400000,x        ; bits7-0
    sta $40
    rep #$20
    lda $3C
    clc
    adc #4
    sta $3C
    jmp inext

; take_irq: simulate a level-6 (vblank) interrupt -> push PC.l + SR.w, mask=6,
; PC = autovector $6C4. Called from iloop when pending and mask<6.
take_irq:
    stz $AA              ; clear pending (IRQ pending moved off $88; see iloop note)
    lda $3C
    sec
    sbc #4
    sta $3C              ; A7 -= 4 (push PC long)
    tax
    sep #$20
    stz $400000,x        ; PC bits31-24 = 0
    inx
    lda $42
    sta $400000,x        ; bits23-16
    inx
    lda $41
    sta $400000,x        ; bits15-8
    inx
    lda $40
    sta $400000,x        ; bits7-0
    rep #$20
    jsr sr_build         ; A = SR
    sta $50
    lda $3C
    dec a
    dec a
    sta $3C              ; A7 -= 2 (push SR word)
    tax
    lda $50
    xba
    sep #$20
    sta $400000,x        ; SR hi byte
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x        ; SR lo byte
    rep #$20
    lda #$0006
    sta $7C              ; mask = 6
    lda #$06C4
    sta $40
    stz $42              ; PC = $0006C4
    rts

; sr_build: assemble SR word from mask($7C)+CCR(N$70 Z$60 V$72 C$6E) -> A
sr_build:
    lda $7C
    and #$0007
    xba                  ; mask -> bits 8-10
    ora #$2000           ; S (supervisor)
    sta $86
    lda $6E              ; C -> bit0
    beq sb_nc
    lda $86
    ora #$0001
    sta $86
sb_nc:
    lda $A2              ; X -> bit4 (dedicated X flag word @ $A2, isolated)
    beq sb_nx
    lda $86
    ora #$0010
    sta $86
sb_nx:
    lda $72              ; V -> bit1
    beq sb_nv
    lda $86
    ora #$0002
    sta $86
sb_nv:
    lda $60              ; Z -> bit2
    beq sb_nz
    lda $86
    ora #$0004
    sta $86
sb_nz:
    lda $70              ; N -> bit3
    beq sb_nn
    lda $86
    ora #$0008
    sta $86
sb_nn:
    lda $86
    rts

; sr_apply: A = SR word -> set mask($7C) + CCR bytes
sr_apply:
    sta $86
    xba
    and #$0007
    sta $7C              ; mask
    lda $86
    and #$0001
    sta $6E              ; C
    lda $86
    and #$0010
    beq sa_x0
    lda #$0001
    sta $A2              ; X
    bra sa_xv
sa_x0:
    stz $A2
sa_xv:
    lda $86
    and #$0002
    beq sa_v0
    lda #$0001
    sta $72
    bra sa_z
sa_v0:
    stz $72
sa_z:
    lda $86
    and #$0004
    beq sa_z0
    lda #$0001
    sta $60
    bra sa_n
sa_z0:
    stz $60
sa_n:
    lda $86
    and #$0008
    beq sa_n0
    lda #$0001
    sta $70
    rts
sa_n0:
    stz $70
    rts

; --- subroutines ---
push32:                  ; push 32-bit ($56:$54) onto 68K stack at A7 (work RAM)
    lda $3C
    sec
    sbc #4
    sta $3C              ; A7 -= 4
    tax                  ; X = A7 low16
    sep #$20
    lda $57
    sta $400000,x        ; byte0 (bits 24-31)
    inx
    lda $56
    sta $400000,x        ; byte1 (bits 16-23)
    inx
    lda $55
    sta $400000,x        ; byte2 (bits 8-15)
    inx
    lda $54
    sta $400000,x        ; byte3 (bits 0-7)
    rep #$20
    rts

readbyte:                ; addr $52(top16)/$54(low16) -> A.low = byte (I/O aware)
    lda $52
    cmp #$00F0
    bne rb_io
    ldx $54
    sep #$20
    lda $400000,x
    rep #$20
    and #$00FF
    rts
rb_io:
    cmp #$0090           ; C-Chip space?
    bne rb_chk50
    lda $54
    cmp #$0803           ; self-test status -> $01 (OK)
    bne rb_cc_inp
    lda #$0001
    rts
; C-Chip $900001/3/5 serve two phases (the (addr>>1) index aliases them onto the
; even signature bytes, so they need explicit handling):
;   phase 0 = GWK signature handshake (68K writes a seed, polls until it reads
;             back $47/$57/$4B 'G'/'W'/'K' at $900001/3/5);
;   phase 1 = per-frame input mailbox (P1/P2/coins) read by the $3A92 frame work,
;             idle = $FF (active-low). $A8 = phase, set when the full sig is read.
rb_cc_inp:
    lda $A8
    and #$00FF
    bne rb_cc_inputs     ; phase 1 -> inputs
    lda $54              ; phase 0 -> signature
    cmp #$0001
    bne rb_cc_p0b
    lda #$0047           ; 'G'
    rts
rb_cc_p0b:
    cmp #$0003
    bne rb_cc_p0c
    lda #$0057           ; 'W'
    rts
rb_cc_p0c:
    cmp #$0005
    bne rb_cc_dp
    lda #$0001
    sta $A8              ; full signature read -> switch to input phase
    lda #$004B           ; 'K'
    rts
rb_cc_inputs:
    lda $62              ; GWK download active (cmd $01)? then $900001/3/5 carry the
    and #$00FF           ; routine bytes, NOT the input mailbox. Route to rb_data so the
    cmp #$0001           ; $2C42 copy loop reads RESP1[idx] (boot writes cmd $00 after,
    beq rb_cc_dp         ; so later input polls see $62!=1 and fall through to $FF).
    lda $54
    cmp #$0001
    beq rb_jp1           ; $900001 P1 -> live SNES controller
    cmp #$0003
    beq rb_cc_ff         ; $900003 P2 -> idle (single player)
    cmp #$0005
    beq rb_jp5           ; $900005 coins/service -> Select = insert coin
rb_cc_dp:
    jmp rb_cc_evn        ; C-Chip status bytes ($900000/4/6 post-boot) then data-port replay
rb_cc_ff:
    lda #$00FF
    rts
rb_jp1:
    jmp input_p1         ; abs jmp: input_p1/input_coins live in the $F800 free block
rb_jp5:
    jmp input_coins
rb_chk50:
    cmp #$0050           ; $500000 DIP/input space -> $0F (idle, MAME ground truth)
    bne rb_chk80
    lda #$000F
    rts
rb_chk80:
    cmp #$0080           ; $800000 sound-latch status
    bne rb_rom
    jmp rb_sound         ; $800003 = TC0140SYT sound comm: replicate MAME's [04,04,01,0E] read
    nop                  ; cycle so COMB alternates $44/$E1 (sound-ready) -> watchdog $1C49 resets
                         ; like MAME. Other $800000 reads still return $04. (byte-neutral swap.)
rb_rom:
    cmp #$0008           ; high16 < 8 => 68K ROM ($00000-$7FFFF) at $C10000+addr
    bcs rb_zero
    lda $54
    sta $66
    lda $52
    clc
    adc #$00C1
    sta $68
    phy                  ; preserve Y (callers like op_movl_anp_anp use Y as a loop counter)
    ldy #$0000
    sep #$20
    lda [$66],y
    rep #$20
    ply
    and #$00FF
    rts
rb_data:                 ; data port: response[cmd][(low16>>1)&FF]
    lda $54              ; ($50 must be preserved: op_cmpib_abs holds imm there)
    lsr a
    and #$00FF
    sta $64              ; index (NOT $50 — that's the caller's imm)
    lda $62
    and #$00FF
    cmp #$0001
    beq rb_cmd1
    cmp #$0002
    beq rb_cmd2
    bra rb_cram          ; not a boot command -> shared C-Chip RAM (game scratch, e.g. $900007)
rb_cram:
    ldx $54
    sep #$20
    lda $41F000,x
    rep #$20
    and #$00FF
    rts
rb_cmd1:                 ; command 1 -> 256-byte downloaded block
    ldx $64
    sep #$20
    lda RESP1,x
    rep #$20
    and #$00FF
    rts
rb_cmd2:                 ; command 2 -> "GWK" signature ($47/$57/$4B)
    lda $64
    bne rb_c2_1
    lda #$0047
    rts
rb_c2_1:
    cmp #$0001
    bne rb_c2_2
    lda #$0057
    rts
rb_c2_2:
    cmp #$0002
    bne rb_zero
    lda #$004B
    rts
rb_zero:
    lda $54
    sta $6A
    lda $52
    jsr map_snes         ; video banks $B0/$D0/$E0 -> read BACK the $41 shadow (builders read
    lda $C2              ; $E0 sprite RAM). mode 1 = video (offset $6A); else 0.
    cmp #$0001
    bne rbz_0
    ldx $6A
    sep #$20
    lda $410000,x
    rep #$20
    and #$00FF
    rts
rbz_0:
    lda #$0000
    rts

; read big-endian operand word at PC+2 / +4 / +6 (via the $56 fetch pointer)
rdw2:
    ldy #$0002
    bra rdw_go
rdw4:
    ldy #$0004
    bra rdw_go
rdw6:
    ldy #$0006
rdw_go:
    lda [$56],y
    xba
    rts

; --- subroutines (orig) ---
regdst:                  ; X = (op bits 11-9)*4   (Dn slot)
    lda $44
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
    rts
regdstA:                 ; X = $20 + (op bits 11-9)*4  (An slot)
    lda $44
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
    clc
    adc #$0020
    tax
    rts
setz_from_eq:            ; set $60 from the prior CMP (Z native flag)
    beq sz1
    stz $60
    rts
sz1:
    lda #$0001
    sta $60
    rts
setz_from_a:             ; set $60 = (A==0)
    cmp #$0000
    beq sz2
    stz $60
    rts
sz2:
    lda #$0001
    sta $60
    rts

; subflags_w: compute full CCR for word subtraction (dest - src).
;   inputs: dest.w @ $74, src.w @ $76. sets Z($60) C($6E) N($70) V($72).
subflags_w:
    sec
    lda $74
    sbc $76
    sta $78              ; result.w
    bcs sfw_noc          ; 65816 carry SET = no borrow (dest>=src)
    lda #$0001
    sta $6E              ; C(68k borrow) = 1
    bra sfw_z
sfw_noc:
    stz $6E
sfw_z:
    lda $78
    bne sfw_nz
    lda #$0001
    sta $60              ; Z = 1
    bra sfw_n
sfw_nz:
    stz $60
sfw_n:
    lda $78
    and #$8000
    beq sfw_npos
    lda #$0001
    sta $70              ; N = 1
    bra sfw_v
sfw_npos:
    stz $70
sfw_v:
    lda $74
    eor $76
    sta $7A              ; dest^src
    lda $74
    eor $78
    and $7A              ; (dest^src)&(dest^result)
    and #$8000
    beq sfw_vno
    lda #$0001
    sta $72              ; V = 1
    rts
sfw_vno:
    stz $72
    rts

; ===========================================================================
;  EA ENGINE (additive; the 142 existing handlers are untouched)
;  Contract (caller sets, all 16-bit DP words):
;    $9C = EA 6-bit code (mode<<3 | reg)   $5E = size (0=B,1=W,2=L)
;    $46 = PC delta in bytes (init 2; advanced as ext words are consumed)
;  ea_resolve outputs:
;    $9E = kind (0=memory,1=Dn-direct,2=An-direct,3=immediate)
;    $94 = DP reg slot (register-direct kinds)   $52/$54 = address (memory)
;  ea_read  -> value in $80(lo16)/$82(hi16), zero-extended
;  ea_write <- value from $80/$82 (size-respecting)
;  Scratch: $96 mode, $98 reg, $5A-$5D ext ptr, $84 temp.
; ===========================================================================
ea_resolve:
    lda $9C
    and #$0038
    lsr a
    lsr a
    lsr a
    sta $96              ; mode (bits 5-3)
    lda $9C
    and #$0007
    sta $98              ; reg (bits 2-0)
    lda $96
    bne ear_n0
    ; mode 0: Dn direct
    lda $98
    asl a
    asl a
    sta $94
    lda #$0001
    sta $9E
    rts
ear_n0:
    cmp #$0001
    bne ear_n1
    ; mode 1: An direct
    lda $98
    asl a
    asl a
    clc
    adc #$0020
    sta $94
    lda #$0002
    sta $9E
    rts
ear_n1:
    cmp #$0002
    bne ear_n2
    ; mode 2: (An)
    jsr ea_an_addr
    stz $9E
    rts
ear_n2:
    cmp #$0003
    bne ear_n3
    ; mode 3: (An)+
    jsr ea_an_addr
    jsr ea_an_postinc
    stz $9E
    rts
ear_n3:
    cmp #$0004
    bne ear_n4
    ; mode 4: -(An)
    jsr ea_an_predec
    jsr ea_an_addr
    stz $9E
    rts
ear_n4:
    cmp #$0005
    bne ear_n5
    ; mode 5: (d16,An)
    jsr ea_an_addr
    jsr ea_extw
    jsr add_signext_w
    stz $9E
    rts
ear_n5:
    cmp #$0006
    bne ear_n6
    ; mode 6: (d8,An,Xn)
    jsr ea_extw
    pha
    lda $98
    asl a
    asl a
    clc
    adc #$0020
    tax
    pla
    jsr idx_ea
    stz $9E
    rts
ear_n6:
    ; mode 7: sub-mode in reg
    lda $98
    bne ear_m7a
    ; (xxx).W
    jsr ea_extw
    sta $54
    and #$8000
    beq ear_w_pos
    lda #$FFFF
    sta $52
    stz $9E
    rts
ear_w_pos:
    stz $52
    stz $9E
    rts
ear_m7a:
    cmp #$0001
    bne ear_m7b
    ; (xxx).L
    jsr ea_extw
    sta $52
    jsr ea_extw
    sta $54
    stz $9E
    rts
ear_m7b:
    cmp #$0002
    bne ear_m7c
    ; (d16,PC): base = address of extension word = PC + delta
    jsr ea_pcbase
    jsr ea_extw
    jsr add_signext_w
    stz $9E
    rts
ear_m7c:
    cmp #$0003
    bne ear_m7d
    ; (d8,PC,Xn): base = address of extension word
    jsr ea_pcbase
    jsr ea_extw
    jsr idx_pc
    stz $9E
    rts
ear_m7d:
    ; #imm (kind 3; ea_read consumes the ext word(s))
    lda #$0003
    sta $9E
    rts

; ea_an_addr: $52/$54 = An[reg]
ea_an_addr:
    lda $98
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    rts

; ea_sizestep: A = address step for (An)+/-(An) (B=1 but A7=2; W=2; L=4)
ea_sizestep:
    lda $5E
    bne ess_nw
    lda $98
    cmp #$0007
    beq ess_2
    lda #$0001
    rts
ess_nw:
    cmp #$0001
    bne ess_long
ess_2:
    lda #$0002
    rts
ess_long:
    lda #$0004
    rts

ea_an_postinc:
    jsr ea_sizestep
    sta $84
    lda $98
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    clc
    adc $84
    sta $00,x
    lda $02,x
    adc #$0000
    sta $02,x
    rts

ea_an_predec:
    jsr ea_sizestep
    sta $84
    lda $98
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    sec
    sbc $84
    sta $00,x
    lda $02,x
    sbc #$0000
    sta $02,x
    rts

; ea_pcbase: $52/$54 = PC + current delta ($46) (the 68K PC-relative base rule)
ea_pcbase:
    lda $40
    clc
    adc $46
    sta $54
    lda $42
    adc #$0000
    sta $52
    rts

; add_signext_w: add signext(A as 16-bit) to $52(hi)/$54(lo)
add_signext_w:
    pha
    and #$8000
    bne asw_neg
    pla
    clc
    adc $54
    sta $54
    lda $52
    adc #$0000
    sta $52
    rts
asw_neg:
    pla
    clc
    adc $54
    sta $54
    lda $52
    adc #$FFFF
    sta $52
    rts

; ea_extw: read big-endian ext word at PC+delta ($46); advance delta by 2
ea_extw:
    lda $40
    clc
    adc $46
    sta $5A              ; ptr lo16 ($5A/$5B)
    lda $42
    adc #$00C1
    sta $5C              ; ptr bank ($5C)
    ldy #$0000
    lda [$5A],y
    xba                  ; big-endian word
    inc $46
    inc $46
    rts

; idx_pc: like idx_ea but base already in $52/$54 (PC-relative indexed). A=ext word.
idx_pc:
    sta $90
    and #$00FF
    cmp #$0080
    bcs idxp_neg
    clc
    adc $54
    sta $54
    lda $52
    adc #$0000
    sta $52
    jmp ix_reg
idxp_neg:
    ora #$FF00
    clc
    adc $54
    sta $54
    lda $52
    adc #$FFFF
    sta $52
    jmp ix_reg

; ea_read: kind $9E + size $5E -> $80(lo16)/$82(hi16), zero-extended
ea_read:
    lda $9E
    beq ear_rd_mem
    cmp #$0003
    beq ear_rd_imm
    ; register-direct (Dn or An)
    ldx $94
    lda $5E
    beq err_rb
    cmp #$0001
    beq err_rw
    lda $00,x
    sta $80
    lda $02,x
    sta $82
    rts
err_rw:
    lda $00,x
    sta $80
    stz $82
    rts
err_rb:
    lda $00,x
    and #$00FF
    sta $80
    stz $82
    rts
ear_rd_imm:
    lda $5E
    beq eim_b
    cmp #$0001
    beq eim_w
    jsr ea_extw
    sta $82
    jsr ea_extw
    sta $80
    rts
eim_w:
    jsr ea_extw
    sta $80
    stz $82
    rts
eim_b:
    jsr ea_extw
    and #$00FF
    sta $80
    stz $82
    rts
ear_rd_mem:
    lda $5E
    beq emr_b
    cmp #$0001
    beq emr_w
    ; long: save $54, rd32 (clobbers $54), restore
    lda $54
    sta $84
    jsr rd32
    lda $50
    sta $80
    lda $6A
    sta $82
    lda $84
    sta $54
    rts
emr_w:
    jsr readbyte
    xba
    and #$FF00
    sta $80
    inc $54
    jsr readbyte
    and #$00FF
    ora $80
    sta $80
    dec $54
    stz $82
    rts
emr_b:
    jsr readbyte
    and #$00FF
    sta $80
    stz $82
    rts

; ea_write: kind $9E + size $5E <- $80(lo16)/$82(hi16)
ea_write:
    lda $9E
    beq eaw_mem
    cmp #$0002
    beq eaw_an
    ; Dn direct: modify only the low byte/word/long
    ldx $94
    lda $5E
    beq ewb
    cmp #$0001
    beq eww
    lda $80
    sta $00,x
    lda $82
    sta $02,x
    rts
eww:
    lda $80
    sta $00,x
    rts
ewb:
    sep #$20
    lda $80
    sta $00,x
    rep #$20
    rts
eaw_an:
    ldx $94
    lda $80
    sta $00,x
    lda $82
    sta $02,x
    rts
eaw_mem:
    lda $5E
    bne eawm_nb
    jmp writebyte
eawm_nb:
    cmp #$0001
    bne eawm_l
    jmp writeword
eawm_l:
    jmp writelong

; logflags: result $80/$82, size $5E -> N,Z set; V,C cleared; X untouched
logflags:
    stz $72              ; V = 0
    stz $6E              ; C = 0
    lda $5E
    beq lf_b
    cmp #$0001
    beq lf_w
    lda $80
    ora $82
    bne lf_lnz
    lda #$0001
    sta $60
    bra lf_ln
lf_lnz:
    stz $60
lf_ln:
    lda $82
    and #$8000
    bne lf_setN
    stz $70
    rts
lf_w:
    lda $80
    bne lf_wnz
    lda #$0001
    sta $60
    bra lf_wn
lf_wnz:
    stz $60
lf_wn:
    lda $80
    and #$8000
    bne lf_setN
    stz $70
    rts
lf_b:
    lda $80
    and #$00FF
    bne lf_bnz
    lda #$0001
    sta $60
    bra lf_bn
lf_bnz:
    stz $60
lf_bn:
    lda $80
    and #$0080
    bne lf_setN
    stz $70
    rts
lf_setN:
    lda #$0001
    sta $70
    rts

; ===========================================================================
;  Size-generic flag helpers (Batch 3).  src @ $74(lo16)/$76(hi16),
;  dest+result @ $80(lo16)/$82(hi16), size $5E.  Set N,Z,V,C (NOT X — the
;  caller copies C->$A2 for ADD/SUB; CMP leaves X alone). $78 saves dest sign.
; ===========================================================================
addflags:
    lda $5E
    bne adf_nb
    jmp adf_b
adf_nb:
    cmp #$0001
    bne adf_lng
    jmp adf_w
adf_lng:
    lda $82
    sta $78
    clc
    lda $80
    adc $74
    sta $80
    lda $82
    adc $76
    sta $82
    bcc adf_lc0
    lda #$0001
    sta $6E
    bra adf_lv
adf_lc0:
    stz $6E
adf_lv:
    lda $76
    eor $78
    and #$8000
    bne adf_lv0
    lda $78
    eor $82
    and #$8000
    beq adf_lv0
    lda #$0001
    sta $72
    bra adf_ln
adf_lv0:
    stz $72
adf_ln:
    lda $82
    and #$8000
    beq adf_lnp
    lda #$0001
    sta $70
    bra adf_lz
adf_lnp:
    stz $70
adf_lz:
    lda $80
    ora $82
    bne adf_lzn
    lda #$0001
    sta $60
    rts
adf_lzn:
    stz $60
    rts
adf_w:
    lda $80
    sta $78
    clc
    lda $80
    adc $74
    sta $80
    bcc adf_wc0
    lda #$0001
    sta $6E
    bra adf_wv
adf_wc0:
    stz $6E
adf_wv:
    lda $74
    eor $78
    and #$8000
    bne adf_wv0
    lda $78
    eor $80
    and #$8000
    beq adf_wv0
    lda #$0001
    sta $72
    bra adf_wn
adf_wv0:
    stz $72
adf_wn:
    lda $80
    and #$8000
    beq adf_wnp
    lda #$0001
    sta $70
    bra adf_wz
adf_wnp:
    stz $70
adf_wz:
    lda $80
    bne adf_wzn
    lda #$0001
    sta $60
    rts
adf_wzn:
    stz $60
    rts
adf_b:
    lda $80
    and #$00FF
    sta $78
    lda $74
    and #$00FF
    clc
    adc $78
    sta $76
    and #$00FF
    sta $80
    lda $76
    and #$0100
    beq adf_bc0
    lda #$0001
    sta $6E
    bra adf_bv
adf_bc0:
    stz $6E
adf_bv:
    lda $74
    eor $78
    and #$0080
    bne adf_bv0
    lda $78
    eor $80
    and #$0080
    beq adf_bv0
    lda #$0001
    sta $72
    bra adf_bn
adf_bv0:
    stz $72
adf_bn:
    lda $80
    and #$0080
    beq adf_bnp
    lda #$0001
    sta $70
    bra adf_bz
adf_bnp:
    stz $70
adf_bz:
    lda $80
    and #$00FF
    bne adf_bzn
    lda #$0001
    sta $60
    rts
adf_bzn:
    stz $60
    rts

; subflags: result = dest - src. C = borrow (68K). Sets N,Z,V,C.
subflags:
    lda $5E
    bne sbf_nb
    jmp sbf_b
sbf_nb:
    cmp #$0001
    bne sbf_lng
    jmp sbf_w
sbf_lng:
    lda $82
    sta $78
    sec
    lda $80
    sbc $74
    sta $80
    lda $82
    sbc $76
    sta $82
    bcs sbf_lc0
    lda #$0001
    sta $6E
    bra sbf_lv
sbf_lc0:
    stz $6E
sbf_lv:
    lda $76
    eor $78
    and #$8000
    beq sbf_lv0
    lda $78
    eor $82
    and #$8000
    beq sbf_lv0
    lda #$0001
    sta $72
    bra sbf_ln
sbf_lv0:
    stz $72
sbf_ln:
    lda $82
    and #$8000
    beq sbf_lnp
    lda #$0001
    sta $70
    bra sbf_lz
sbf_lnp:
    stz $70
sbf_lz:
    lda $80
    ora $82
    bne sbf_lzn
    lda #$0001
    sta $60
    rts
sbf_lzn:
    stz $60
    rts
sbf_w:
    lda $80
    sta $78
    sec
    lda $80
    sbc $74
    sta $80
    bcs sbf_wc0
    lda #$0001
    sta $6E
    bra sbf_wv
sbf_wc0:
    stz $6E
sbf_wv:
    lda $74
    eor $78
    and #$8000
    beq sbf_wv0
    lda $78
    eor $80
    and #$8000
    beq sbf_wv0
    lda #$0001
    sta $72
    bra sbf_wn
sbf_wv0:
    stz $72
sbf_wn:
    lda $80
    and #$8000
    beq sbf_wnp
    lda #$0001
    sta $70
    bra sbf_wz
sbf_wnp:
    stz $70
sbf_wz:
    lda $80
    bne sbf_wzn
    lda #$0001
    sta $60
    rts
sbf_wzn:
    stz $60
    rts
sbf_b:
    lda $80
    and #$00FF
    sta $78
    lda $74
    and #$00FF
    sta $7A
    sec
    lda $78
    sbc $7A
    and #$00FF
    sta $80
    lda $78
    cmp $7A
    bcs sbf_bc0
    lda #$0001
    sta $6E
    bra sbf_bv
sbf_bc0:
    stz $6E
sbf_bv:
    lda $7A
    eor $78
    and #$0080
    beq sbf_bv0
    lda $78
    eor $80
    and #$0080
    beq sbf_bv0
    lda #$0001
    sta $72
    bra sbf_bn
sbf_bv0:
    stz $72
sbf_bn:
    lda $80
    and #$0080
    beq sbf_bnp
    lda #$0001
    sta $70
    bra sbf_bz
sbf_bnp:
    stz $70
sbf_bz:
    lda $80
    and #$00FF
    bne sbf_bzn
    lda #$0001
    sta $60
    rts
sbf_bzn:
    stz $60
    rts

; regwr_sized: write $80/$82 into Dn slot X, size $5E (low byte/word/long only)
regwr_sized:
    lda $5E
    bne rws_nb
    sep #$20
    lda $80
    sta $00,x
    rep #$20
    rts
rws_nb:
    cmp #$0001
    bne rws_l
    lda $80
    sta $00,x
    rts
rws_l:
    lda $80
    sta $00,x
    lda $82
    sta $02,x
    rts

; ===========================================================================
;  Extended-precision flag helpers (Batch 3): X carry-in + STICKY Z.
;  src $74/$76, dest+result $80/$82, X read from $A2. Set N,V,C and X=C.
;  Z is sticky: cleared if result != 0, left unchanged if result == 0.
; ===========================================================================
addxflags:
    lda $5E
    bne axf_nb
    jmp axf_b
axf_nb:
    cmp #$0001
    bne axf_lng
    jmp axf_w
axf_lng:
    lda $82
    sta $78
    lda $A2
    lsr a                ; carry = X
    lda $80
    adc $74
    sta $80
    lda $82
    adc $76
    sta $82
    bcc axf_lc0
    lda #$0001
    sta $6E
    sta $A2
    bra axf_lv
axf_lc0:
    stz $6E
    stz $A2
axf_lv:
    lda $76
    eor $78
    and #$8000
    bne axf_lv0
    lda $78
    eor $82
    and #$8000
    beq axf_lv0
    lda #$0001
    sta $72
    bra axf_ln
axf_lv0:
    stz $72
axf_ln:
    lda $82
    and #$8000
    beq axf_lnp
    lda #$0001
    sta $70
    bra axf_lz
axf_lnp:
    stz $70
axf_lz:
    lda $80
    ora $82
    beq axf_lzd
    stz $60
axf_lzd:
    rts
axf_w:
    lda $80
    sta $78
    lda $A2
    lsr a
    lda $80
    adc $74
    sta $80
    bcc axf_wc0
    lda #$0001
    sta $6E
    sta $A2
    bra axf_wv
axf_wc0:
    stz $6E
    stz $A2
axf_wv:
    lda $74
    eor $78
    and #$8000
    bne axf_wv0
    lda $78
    eor $80
    and #$8000
    beq axf_wv0
    lda #$0001
    sta $72
    bra axf_wn
axf_wv0:
    stz $72
axf_wn:
    lda $80
    and #$8000
    beq axf_wnp
    lda #$0001
    sta $70
    bra axf_wz
axf_wnp:
    stz $70
axf_wz:
    lda $80
    beq axf_wzd
    stz $60
axf_wzd:
    rts
axf_b:
    lda $80
    and #$00FF
    sta $78
    lda $74
    and #$00FF
    sta $7A
    clc
    lda $78
    adc $7A
    clc
    adc $A2
    sta $76
    and #$00FF
    sta $80
    lda $76
    and #$0100
    beq axf_bc0
    lda #$0001
    sta $6E
    sta $A2
    bra axf_bv
axf_bc0:
    stz $6E
    stz $A2
axf_bv:
    lda $7A
    eor $78
    and #$0080
    bne axf_bv0
    lda $78
    eor $80
    and #$0080
    beq axf_bv0
    lda #$0001
    sta $72
    bra axf_bn
axf_bv0:
    stz $72
axf_bn:
    lda $80
    and #$0080
    beq axf_bnp
    lda #$0001
    sta $70
    bra axf_bz
axf_bnp:
    stz $70
axf_bz:
    lda $80
    and #$00FF
    beq axf_bzd
    stz $60
axf_bzd:
    rts

; subxflags: result = dest - src - X ; C/X = borrow ; sticky Z.
subxflags:
    lda $5E
    bne sxf_nb
    jmp sxf_b
sxf_nb:
    cmp #$0001
    bne sxf_lng
    jmp sxf_w
sxf_lng:
    lda $82
    sta $78
    lda $A2
    eor #$0001
    lsr a                ; carry = ~X
    lda $80
    sbc $74
    sta $80
    lda $82
    sbc $76
    sta $82
    bcs sxf_lc0
    lda #$0001
    sta $6E
    sta $A2
    bra sxf_lv
sxf_lc0:
    stz $6E
    stz $A2
sxf_lv:
    lda $76
    eor $78
    and #$8000
    beq sxf_lv0
    lda $78
    eor $82
    and #$8000
    beq sxf_lv0
    lda #$0001
    sta $72
    bra sxf_ln
sxf_lv0:
    stz $72
sxf_ln:
    lda $82
    and #$8000
    beq sxf_lnp
    lda #$0001
    sta $70
    bra sxf_lz
sxf_lnp:
    stz $70
sxf_lz:
    lda $80
    ora $82
    beq sxf_lzd
    stz $60
sxf_lzd:
    rts
sxf_w:
    lda $80
    sta $78
    lda $A2
    eor #$0001
    lsr a
    lda $80
    sbc $74
    sta $80
    bcs sxf_wc0
    lda #$0001
    sta $6E
    sta $A2
    bra sxf_wv
sxf_wc0:
    stz $6E
    stz $A2
sxf_wv:
    lda $74
    eor $78
    and #$8000
    beq sxf_wv0
    lda $78
    eor $80
    and #$8000
    beq sxf_wv0
    lda #$0001
    sta $72
    bra sxf_wn
sxf_wv0:
    stz $72
sxf_wn:
    lda $80
    and #$8000
    beq sxf_wnp
    lda #$0001
    sta $70
    bra sxf_wz
sxf_wnp:
    stz $70
sxf_wz:
    lda $80
    beq sxf_wzd
    stz $60
sxf_wzd:
    rts
sxf_b:
    lda $80
    and #$00FF
    sta $78
    lda $74
    and #$00FF
    sta $7A
    lda $A2
    eor #$0001
    lsr a
    lda $78
    sbc $7A
    sta $76
    bcs sxf_bc0
    lda #$0001
    sta $6E
    sta $A2
    bra sxf_bv
sxf_bc0:
    stz $6E
    stz $A2
sxf_bv:
    lda $76
    and #$00FF
    sta $80
    lda $7A
    eor $78
    and #$0080
    beq sxf_bv0
    lda $78
    eor $80
    and #$0080
    beq sxf_bv0
    lda #$0001
    sta $72
    bra sxf_bn
sxf_bv0:
    stz $72
sxf_bn:
    lda $80
    and #$0080
    beq sxf_bnp
    lda #$0001
    sta $70
    bra sxf_bz
sxf_bnp:
    stz $70
sxf_bz:
    lda $80
    and #$00FF
    beq sxf_bzd
    stz $60
sxf_bzd:
    rts

; ===========================================================================
;  BCD cores (Batch 4) — replicate Musashi exactly (incl. its "undefined" N/V).
;  Inputs: dest byte $78, src byte $7A, X $A2. Output: result byte $76.
;  Sets X=C (decimal carry/borrow), N (res bit7), V (~initial_lo & res bit7),
;  sticky Z. Scratch: $5A/$5C nibbles, $74 vtmp.
; ===========================================================================
bcd_add:
    lda $7A
    and #$000F
    sta $5C
    lda $78
    and #$000F
    clc
    adc $5C
    clc
    adc $A2
    sta $76              ; res = lo(s)+lo(d)+X
    eor #$FFFF
    sta $74              ; vtmp = ~res
    lda $76
    cmp #$000A
    bcc bcd_a_n6
    clc
    adc #$0006
    sta $76
bcd_a_n6:
    lda $7A
    and #$00F0
    sta $5C
    lda $78
    and #$00F0
    clc
    adc $5C
    clc
    adc $76
    sta $76              ; res += hi(s)+hi(d)
    cmp #$009A
    bcc bcd_a_nc
    lda #$0001
    sta $6E
    sta $A2
    lda $76
    sec
    sbc #$00A0
    sta $76
    bra bcd_a_v
bcd_a_nc:
    stz $6E
    stz $A2
bcd_a_v:
    lda $74
    and $76
    and #$0080
    beq bcd_a_v0
    lda #$0001
    sta $72
    bra bcd_a_n
bcd_a_v0:
    stz $72
bcd_a_n:
    lda $76
    and #$0080
    beq bcd_a_np
    lda #$0001
    sta $70
    bra bcd_a_z
bcd_a_np:
    stz $70
bcd_a_z:
    lda $76
    and #$00FF
    sta $76
    beq bcd_a_zd
    stz $60
bcd_a_zd:
    rts

bcd_sub:
    lda $78
    and #$000F
    sta $5A
    lda $7A
    and #$000F
    sta $5C
    lda $5A
    sec
    sbc $5C
    sec
    sbc $A2
    sta $76              ; res = lo(d)-lo(s)-X
    eor #$FFFF
    sta $74              ; vtmp = ~res
    lda $76
    cmp #$000A
    bcc bcd_s_n6
    sec
    sbc #$0006
    sta $76
bcd_s_n6:
    lda $78
    and #$00F0
    sta $5A
    lda $7A
    and #$00F0
    sta $5C
    lda $76
    clc
    adc $5A
    sec
    sbc $5C
    sta $76              ; res += hi(d)-hi(s)
    cmp #$009A
    bcc bcd_s_nc
    lda #$0001
    sta $6E
    sta $A2
    lda $76
    clc
    adc #$00A0
    sta $76
    bra bcd_s_v
bcd_s_nc:
    stz $6E
    stz $A2
bcd_s_v:
    lda $74
    and $76
    and #$0080
    beq bcd_s_v0
    lda #$0001
    sta $72
    bra bcd_s_n
bcd_s_v0:
    stz $72
bcd_s_n:
    lda $76
    and #$0080
    beq bcd_s_np
    lda #$0001
    sta $70
    bra bcd_s_z
bcd_s_np:
    stz $70
bcd_s_z:
    lda $76
    and #$00FF
    sta $76
    beq bcd_s_zd
    stz $60
bcd_s_zd:
    rts

; --- Batch 2: NOT <ea> (size in bits 7-6) : result=~ea ; N,Z ; V,C=0 ; X kept
op_not:
    lda $44
    and #$003F
    sta $9C
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E              ; size 0/1/2
    lda #$0002
    sta $46
    jsr ea_resolve
    jsr ea_read
    lda $80
    eor #$FFFF
    sta $80
    lda $82
    eor #$FFFF
    sta $82
    jsr logflags
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 2: AND <ea>,Dn (dir0) / AND Dn,<ea> (dir1) ; N,Z ; V,C=0 ; X kept
;     dir1 with ea-mode 0/1 is ABCD/EXG (not AND) -> kbad until implemented.
op_and:
    lda $44
    and #$0100
    beq op_and_go
    lda $44
    and #$0038
    cmp #$0010
    bcc op_and_bad
op_and_go:
    lda $44
    and #$003F
    sta $9C
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    jsr ea_resolve
    jsr ea_read
    jsr regdst
    lda $80
    and $00,x
    sta $80
    lda $82
    and $02,x
    sta $82
    jsr logflags
    lda $44
    and #$0100
    bne op_and_toea
    ; dir0: result -> Dn (size-aware; X still = Dn slot)
    lda $5E
    beq op_and_db
    cmp #$0001
    beq op_and_dw
    lda $80
    sta $00,x
    lda $82
    sta $02,x
    bra op_and_pc
op_and_dw:
    lda $80
    sta $00,x
    bra op_and_pc
op_and_db:
    sep #$20
    lda $80
    sta $00,x
    rep #$20
    bra op_and_pc
op_and_toea:
    jsr ea_write
op_and_pc:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext
op_and_bad:              ; $Cxxx dir1 ea-mode 0/1 (ABCD caught earlier) == EXG
    lda $44
    and #$F1F8
    cmp #$C140            ; EXG Dx,Dy
    beq oab_exg
    cmp #$C148            ; EXG Ax,Ay
    beq oab_exg
    cmp #$C188            ; EXG Dx,Ay
    beq oab_exg
    jmp kbad
oab_exg:
    jmp op_exg

; --- Batch 2: EOR Dn,<ea> ; N,Z ; V,C=0 ; X kept  (ea-mode 1 = CMPM -> kbad)
op_eor:
    lda $44
    and #$0038
    cmp #$0008
    beq op_eor_bad
    lda $44
    and #$003F
    sta $9C
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    jsr ea_resolve
    jsr ea_read
    jsr regdst
    lda $80
    eor $00,x
    sta $80
    lda $82
    eor $02,x
    sta $82
    jsr logflags
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext
op_eor_bad:
    jmp kbad

; --- Batch 2: EORI #imm,<ea> ; N,Z ; V,C=0 ; X kept  (imm staged in $74/$76)
op_eori:
    lda $44
    and #$003F
    sta $9C
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    lda $5E
    beq op_eori_ib
    cmp #$0001
    beq op_eori_iw
    jsr ea_extw
    sta $76
    jsr ea_extw
    sta $74
    bra op_eori_have
op_eori_iw:
    jsr ea_extw
    sta $74
    stz $76
    bra op_eori_have
op_eori_ib:
    jsr ea_extw
    and #$00FF
    sta $74
    stz $76
op_eori_have:
    jsr ea_resolve
    jsr ea_read
    lda $80
    eor $74
    sta $80
    lda $82
    eor $76
    sta $82
    jsr logflags
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 3: ADD <ea>,Dn (dir0) / ADD Dn,<ea> (dir1) ; full XNZVC ; X=C.
;     dir1 ea-mode 0/1 = ADDX (deferred -> kbad).
op_add:
    lda $44
    and #$0100
    beq op_add_go
    lda $44
    and #$0038
    cmp #$0010
    bcc op_add_bad
op_add_go:
    lda $44
    and #$003F
    sta $9C
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    jsr ea_resolve
    jsr ea_read
    jsr regdst
    lda $44
    and #$0100
    bne op_add_d1
    lda $80
    sta $74
    lda $82
    sta $76
    lda $00,x
    sta $80
    lda $02,x
    sta $82
    jsr addflags
    lda $6E
    sta $A2
    jsr regwr_sized
    bra op_add_pc
op_add_d1:
    lda $00,x
    sta $74
    lda $02,x
    sta $76
    jsr addflags
    lda $6E
    sta $A2
    jsr ea_write
op_add_pc:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext
op_add_bad:
    jmp kbad

; --- Batch 3: SUB <ea>,Dn (dir0) / SUB Dn,<ea> (dir1) ; full XNZVC ; X=C.
;     dir1 ea-mode 0/1 = SUBX (deferred -> kbad).
op_sub:
    lda $44
    and #$0100
    beq op_sub_go
    lda $44
    and #$0038
    cmp #$0010
    bcc op_sub_bad
op_sub_go:
    lda $44
    and #$003F
    sta $9C
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    jsr ea_resolve
    jsr ea_read
    jsr regdst
    lda $44
    and #$0100
    bne op_sub_d1
    lda $80
    sta $74
    lda $82
    sta $76
    lda $00,x
    sta $80
    lda $02,x
    sta $82
    jsr subflags
    lda $6E
    sta $A2
    jsr regwr_sized
    bra op_sub_pc
op_sub_d1:
    lda $00,x
    sta $74
    lda $02,x
    sta $76
    jsr subflags
    lda $6E
    sta $A2
    jsr ea_write
op_sub_pc:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext
op_sub_bad:
    jmp kbad

; --- Batch 3: CMP <ea>,Dn ; sets N,Z,V,C (X untouched); no writeback.
op_cmp:
    lda $44
    and #$003F
    sta $9C
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    jsr ea_resolve
    jsr ea_read
    jsr regdst
    lda $80
    sta $74
    lda $82
    sta $76
    lda $00,x
    sta $80
    lda $02,x
    sta $82
    jsr subflags
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 3: NEG <ea> : result = 0 - ea ; full XNZVC ; X=C.
op_neg:
    lda $44
    and #$003F
    sta $9C
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    jsr ea_resolve
    jsr ea_read
    lda $80
    sta $74
    lda $82
    sta $76
    stz $80
    stz $82
    jsr subflags
    lda $6E
    sta $A2
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 3: EXT.l Dn : sign-extend low word to 32 ; N,Z ; V,C=0 ; X kept.
op_ext_l:
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $80
    bmi op_extl_neg
    stz $82
    bra op_extl_st
op_extl_neg:
    lda #$FFFF
    sta $82
op_extl_st:
    lda $82
    sta $02,x
    lda #$0002
    sta $5E
    jsr logflags
    lda $40
    clc
    adc #$0002
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 3: CMPA <ea>,An : An - ea(sign-ext to 32) ; N,Z,V,C ; X kept ; no write.
op_cmpa:
    lda $44
    and #$003F
    sta $9C
    lda #$0002
    sta $46
    lda $44
    and #$0100
    bne op_cmpa_l
    lda #$0001
    sta $5E
    jsr ea_resolve
    jsr ea_read
    lda $80
    bpl op_cmpa_wpos
    lda #$FFFF
    sta $82
    bra op_cmpa_have
op_cmpa_wpos:
    stz $82
    bra op_cmpa_have
op_cmpa_l:
    lda #$0002
    sta $5E
    jsr ea_resolve
    jsr ea_read
op_cmpa_have:
    lda $80
    sta $74
    lda $82
    sta $76
    jsr regdstA
    lda $00,x
    sta $80
    lda $02,x
    sta $82
    lda #$0002
    sta $5E
    jsr subflags
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 3: CMPM (Ay)+,(Ax)+ : (Ax) - (Ay) ; N,Z,V,C ; X kept ; both An post-inc.
op_cmpm:
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    ; src = (Ay)+, Ay = bits 2-0, mode 3
    lda $44
    and #$0007
    ora #$0018
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    sta $74
    lda $82
    sta $76
    ; dest = (Ax)+, Ax = bits 11-9, mode 3
    lda $44
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
    ora #$0018
    sta $9C
    jsr ea_resolve
    jsr ea_read
    jsr subflags
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 3: ADDX Dy,Dx (reg) / ADDX -(Ay),-(Ax) (mem) : dest+src+X ; sticky Z.
op_addx:
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    lda $44
    and #$0008
    bne op_addx_mem
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $74
    lda $02,x
    sta $76
    jsr regdst
    lda $00,x
    sta $80
    lda $02,x
    sta $82
    jsr addxflags
    jsr regdst
    jsr regwr_sized
    bra op_addx_pc
op_addx_mem:
    lda $44
    and #$0007
    ora #$0020
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    sta $74
    lda $82
    sta $76
    lda $44
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
    ora #$0020
    sta $9C
    jsr ea_resolve
    jsr ea_read
    jsr addxflags
    jsr ea_write
op_addx_pc:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 3: SUBX Dy,Dx (reg) / SUBX -(Ay),-(Ax) (mem) : dest-src-X ; sticky Z.
op_subx:
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    lda $44
    and #$0008
    bne op_subx_mem
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $74
    lda $02,x
    sta $76
    jsr regdst
    lda $00,x
    sta $80
    lda $02,x
    sta $82
    jsr subxflags
    jsr regdst
    jsr regwr_sized
    bra op_subx_pc
op_subx_mem:
    lda $44
    and #$0007
    ora #$0020
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    sta $74
    lda $82
    sta $76
    lda $44
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
    ora #$0020
    sta $9C
    jsr ea_resolve
    jsr ea_read
    jsr subxflags
    jsr ea_write
op_subx_pc:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 3: NEGX <ea> : result = 0 - ea - X ; sticky Z ; X=borrow.
op_negx:
    lda $44
    and #$003F
    sta $9C
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    jsr ea_resolve
    jsr ea_read
    lda $80
    sta $74
    lda $82
    sta $76
    stz $80
    stz $82
    jsr subxflags
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 4: ABCD Dy,Dx (reg) / -(Ay),-(Ax) (mem) : BCD dest+src+X ; sticky Z.
op_abcd:
    stz $5E
    lda #$0002
    sta $46
    lda $44
    and #$0008
    bne op_abcd_mem
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    and #$00FF
    sta $7A
    jsr regdst
    lda $00,x
    and #$00FF
    sta $78
    jsr bcd_add
    jsr regdst
    sep #$20
    lda $76
    sta $00,x
    rep #$20
    bra op_abcd_pc
op_abcd_mem:
    lda $44
    and #$0007
    ora #$0020
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    and #$00FF
    sta $7A
    lda $44
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
    ora #$0020
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    and #$00FF
    sta $78
    jsr bcd_add
    lda $76
    and #$00FF
    sta $80
    jsr writebyte
op_abcd_pc:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 4: SBCD Dy,Dx (reg) / -(Ay),-(Ax) (mem) : BCD dest-src-X ; sticky Z.
op_sbcd:
    stz $5E
    lda #$0002
    sta $46
    lda $44
    and #$0008
    bne op_sbcd_mem
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    and #$00FF
    sta $7A
    jsr regdst
    lda $00,x
    and #$00FF
    sta $78
    jsr bcd_sub
    jsr regdst
    sep #$20
    lda $76
    sta $00,x
    rep #$20
    bra op_sbcd_pc
op_sbcd_mem:
    lda $44
    and #$0007
    ora #$0020
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    and #$00FF
    sta $7A
    lda $44
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
    ora #$0020
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    and #$00FF
    sta $78
    jsr bcd_sub
    lda $76
    and #$00FF
    sta $80
    jsr writebyte
op_sbcd_pc:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 4: NBCD <ea> : BCD 0 - ea - X ; sticky Z.
op_nbcd:
    stz $5E
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    and #$00FF
    sta $7A
    stz $78
    jsr bcd_sub
    lda $76
    and #$00FF
    sta $80
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; ===========================================================================
;  SHIFT/ROTATE engine (Batch 5). Bit-by-bit loop -> exact hardware flags.
;  Value $80/$82, size $5E. Loop scratch: count $74, dir $76 (1=left),
;  type $78 (0=AS,1=LS,2=ROX,3=RO), C-out $7A, newbit $84. V -> $72, X -> $A2.
; ===========================================================================
get_msb:                 ; A = size-MSB bit of $80/$82 (0 or nonzero)
    lda $5E
    beq gm_b
    cmp #$0001
    beq gm_w
    lda $82
    and #$8000
    rts
gm_w:
    lda $80
    and #$8000
    rts
gm_b:
    lda $80
    and #$0080
    rts
mask_size:               ; mask $80/$82 to size $5E
    lda $5E
    beq mks_b
    cmp #$0001
    beq mks_w
    rts
mks_w:
    stz $82
    rts
mks_b:
    lda $80
    and #$00FF
    sta $80
    stz $82
    rts
set_size_msb:            ; set the size-MSB bit of $80/$82 to 1
    lda $5E
    beq ssm_b
    cmp #$0001
    beq ssm_w
    lda $82
    ora #$8000
    sta $82
    rts
ssm_w:
    lda $80
    ora #$8000
    sta $80
    rts
ssm_b:
    lda $80
    ora #$0080
    sta $80
    rts
set_nz:                  ; set N($70)/Z($60) from $80/$82 (size-aware); V/C/X untouched
    jsr get_msb
    beq snz_n0
    lda #$0001
    sta $70
    bra snz_z
snz_n0:
    stz $70
snz_z:
    lda $5E
    beq snz_zb
    cmp #$0001
    beq snz_zw
    lda $80
    ora $82
    bra snz_zt
snz_zw:
    lda $80
    bra snz_zt
snz_zb:
    lda $80
    and #$00FF
snz_zt:
    beq snz_z1
    stz $60
    rts
snz_z1:
    lda #$0001
    sta $60
    rts
shift_step:              ; one bit; updates C-out $7A, X $A2, V $72, value $80/$82
    lda $76
    bne sstep_left
    jmp sstep_right
sstep_left:
    jsr get_msb
    beq sl_out0
    lda #$0001
    sta $7A
    bra sl_in
sl_out0:
    stz $7A
sl_in:
    lda $78
    cmp #$0003
    beq sl_ro
    cmp #$0002
    beq sl_rox
    stz $84
    bra sl_dosh
sl_ro:
    lda $7A
    sta $84
    bra sl_dosh
sl_rox:
    lda $A2
    sta $84
sl_dosh:
    asl $80
    rol $82
    lda $84
    beq sl_nob0
    lda $80
    ora #$0001
    sta $80
sl_nob0:
    jsr mask_size
    lda $78
    bne sl_noV
    jsr get_msb
    beq sl_nm0
    lda #$0001
    bra sl_cmpv
sl_nm0:
    lda #$0000
sl_cmpv:
    cmp $7A
    beq sl_noV
    lda #$0001
    sta $72
sl_noV:
    lda $78
    cmp #$0003
    beq sl_xs
    lda $7A
    sta $A2
sl_xs:
    rts
sstep_right:
    lda $80
    and #$0001
    sta $7A
    lda $78
    cmp #$0003
    beq sr_ro
    cmp #$0002
    beq sr_rox
    cmp #$0000
    beq sr_as
    stz $84
    bra sr_dosh
sr_as:
    jsr get_msb
    beq sr_as0
    lda #$0001
    sta $84
    bra sr_dosh
sr_as0:
    stz $84
    bra sr_dosh
sr_ro:
    lda $7A
    sta $84
    bra sr_dosh
sr_rox:
    lda $A2
    sta $84
sr_dosh:
    lsr $82
    ror $80
    lda $84
    beq sr_nm
    jsr set_size_msb
sr_nm:
    jsr mask_size
    lda $78
    cmp #$0003
    beq sr_xs
    lda $7A
    sta $A2
sr_xs:
    rts

; --- Batch 5: register shift/rotate (ASx/LSx/ROXx/ROx, B/W/L, imm or reg count)
op_shift:
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda $44
    and #$0100
    beq op_sh_r
    lda #$0001
    sta $76
    bra op_sh_dir
op_sh_r:
    stz $76
op_sh_dir:
    lda $44
    and #$0018
    lsr a
    lsr a
    lsr a
    sta $78
    lda $44
    and #$0020
    bne op_sh_regc
    lda $44
    and #$0E00
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    bne op_sh_inz
    lda #$0008
op_sh_inz:
    sta $74
    bra op_sh_load
op_sh_regc:
    lda $44
    and #$0E00
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    asl a
    asl a
    tax
    lda $00,x
    and #$003F
    sta $74
op_sh_load:
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    sta $80
    lda $02,x
    sta $82
    jsr mask_size
    stz $72
    lda $74
    bne op_sh_loop
    lda $78
    cmp #$0002
    bne op_sh_c0c0
    lda $A2
    sta $6E
    bra op_sh_nz
op_sh_c0c0:
    stz $6E
    bra op_sh_nz
op_sh_loop:
    jsr shift_step
    dec $74
    bne op_sh_loop
    lda $7A
    sta $6E
op_sh_nz:
    jsr set_nz
    lda $44
    and #$0007
    asl a
    asl a
    tax
    jsr regwr_sized
    lda $40
    clc
    adc #$0002
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; --- Batch 5: memory shift/rotate (word, 1 bit) : 1110 0TT D 11 <ea>
op_shift_mem:
    lda #$0001
    sta $5E
    lda #$0001
    sta $74
    lda $44
    and #$0100
    beq op_shm_r
    lda #$0001
    sta $76
    bra op_shm_dir
op_shm_r:
    stz $76
op_shm_dir:
    lda $44
    and #$0600
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $78
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read
    jsr mask_size
    stz $72
    jsr shift_step
    lda $7A
    sta $6E
    jsr set_nz
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; cond_test: in $50 = cc (0..15) ; out $52 = 1 if condition true else 0.
; Mirrors op_bcc's proven flag logic; scratch $54 (nv = N^V). Flags read:
; Z@$60 C@$6E N@$70 V@$72 (nonzero = set). cc 0=T,1=F, 2..15 per 68000.
cond_test:
    stz $52
    lda $50
    bne ct_n1
    inc $52              ; T (always true)
    rts
ct_n1:
    cmp #$0001
    bne ct_n2
    rts                  ; F (always false; $52=0)
ct_n2:
    cmp #$0002
    bne ct_n3
    lda $6E              ; HI: !C & !Z
    ora $60
    bne ct_r2
    inc $52
ct_r2:
    rts
ct_n3:
    cmp #$0003
    bne ct_n4
    lda $6E              ; LS: C | Z
    ora $60
    beq ct_r3
    inc $52
ct_r3:
    rts
ct_n4:
    cmp #$0004
    bne ct_n5
    lda $6E              ; CC(HS): !C
    bne ct_r4
    inc $52
ct_r4:
    rts
ct_n5:
    cmp #$0005
    bne ct_n6
    lda $6E              ; CS(LO): C
    beq ct_r5
    inc $52
ct_r5:
    rts
ct_n6:
    cmp #$0006
    bne ct_n7
    lda $60              ; NE: !Z
    bne ct_r6
    inc $52
ct_r6:
    rts
ct_n7:
    cmp #$0007
    bne ct_n8
    lda $60              ; EQ: Z
    beq ct_r7
    inc $52
ct_r7:
    rts
ct_n8:
    cmp #$0008
    bne ct_n9
    lda $72              ; VC: !V
    bne ct_r8
    inc $52
ct_r8:
    rts
ct_n9:
    cmp #$0009
    bne ct_nA
    lda $72              ; VS: V
    beq ct_r9
    inc $52
ct_r9:
    rts
ct_nA:
    cmp #$000A
    bne ct_nB
    lda $70              ; PL: !N
    bne ct_rA
    inc $52
ct_rA:
    rts
ct_nB:
    cmp #$000B
    bne ct_nv
    lda $70              ; MI: N
    beq ct_rB
    inc $52
ct_rB:
    rts
ct_nv:
    lda $70              ; nv = N ^ V
    eor $72
    sta $54
    lda $50
    cmp #$000C
    bne ct_nD
    lda $54              ; GE: !(N^V)
    bne ct_rC
    inc $52
ct_rC:
    rts
ct_nD:
    cmp #$000D
    bne ct_nE
    lda $54              ; LT: N^V
    beq ct_rD
    inc $52
ct_rD:
    rts
ct_nE:
    cmp #$000E
    bne ct_nF
    lda $60              ; GT: !Z & !(N^V)
    ora $54
    bne ct_rE
    inc $52
ct_rE:
    rts
ct_nF:                   ; LE: Z | (N^V)
    lda $60
    ora $54
    beq ct_rF
    inc $52
ct_rF:
    rts

; op_bitop: BTST/BCHG/BCLR/BSET, static (#n) or dynamic (Dn) bit number.
;   type = bits 7-6 (00 BTST,01 BCHG,10 BCLR,11 BSET). Dn target -> long, bit mod 32;
;   memory target -> byte, bit mod 8. Z = !(old bit); N/V/C/X unaffected.
;   Scratch: $88 bitnum, $8A/$8C mask lo/hi, $8E modulo, $86 temp (all outside EA's set).
op_bitop:
    lda $44
    and #$0038            ; EA mode
    bne bop_mem
    lda #$0002
    sta $5E              ; Dn target -> long
    lda #$001F
    sta $8E              ; bit mod 32
    bra bop_szdone
bop_mem:
    stz $5E              ; memory target -> byte
    lda #$0007
    sta $8E              ; bit mod 8
bop_szdone:
    lda #$0002
    sta $46
    lda $44
    and #$0100            ; bit8: 1=dynamic (Dn), 0=static (#n)
    beq bop_static
    lda $44              ; dynamic: bit number from Dn = (op>>9)&7
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
    bra bop_bitset
bop_static:
    jsr ea_extw          ; static bit number in ext word (read BEFORE EA ext words)
bop_bitset:
    and $8E
    sta $88              ; bitnum &= modulo
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; operand -> $80/$82
    stz $8C              ; mask = 1 << bitnum
    lda #$0001
    sta $8A
    ldy $88
    beq bop_maskdone
bop_maskloop:
    asl $8A
    rol $8C
    dey
    bne bop_maskloop
bop_maskdone:
    lda $80              ; old bit = value & mask
    and $8A
    sta $86
    lda $82
    and $8C
    ora $86
    bne bop_wasset
    lda #$0001
    sta $60              ; Z = 1 (bit was clear)
    bra bop_modify
bop_wasset:
    stz $60              ; Z = 0 (bit was set)
bop_modify:
    lda $44
    and #$00C0            ; type
    beq bop_finish       ; BTST -> no write
    cmp #$0040
    beq bop_bchg
    cmp #$0080
    beq bop_bclr
    lda $80              ; BSET: value |= mask
    ora $8A
    sta $80
    lda $82
    ora $8C
    sta $82
    bra bop_write
bop_bchg:
    lda $80              ; BCHG: value ^= mask
    eor $8A
    sta $80
    lda $82
    eor $8C
    sta $82
    bra bop_write
bop_bclr:
    lda $8A              ; BCLR: value &= ~mask
    eor #$FFFF
    and $80
    sta $80
    lda $8C
    eor #$FFFF
    and $82
    sta $82
bop_write:
    jsr ea_write
bop_finish:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; op_dbcc: DBcc Dn,disp16  (0101 cccc 11 001 rrr).
;   if cc TRUE  -> terminate: PC += 4 (no decrement).
;   if cc FALSE -> Dn.w -= 1; if Dn.w == $FFFF then PC += 4 (expired) else
;                  PC = PC + 2 + signext(disp16)  (branch, full 32-bit).
op_dbcc:
    lda $44
    and #$0F00
    xba
    sta $50              ; cc
    jsr cond_test        ; $52 = 1 if condition TRUE
    lda $52
    bne dbcc_done        ; true -> terminate, PC += 4
    lda $44
    and #$0007
    asl a
    asl a
    tax
    lda $00,x
    dec a
    sta $00,x            ; Dn.w -= 1 (low word only)
    cmp #$FFFF
    beq dbcc_done        ; expired -> fall through, PC += 4
    jsr rdw2             ; A = disp16 (extension word at PC+2)
    sta $50
    lda $40
    clc
    adc #2
    sta $40
    lda $42
    adc #$0000
    sta $42              ; PC += 2
    lda $50
    bmi dbcc_bneg
    clc
    adc $40
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext
dbcc_bneg:
    clc
    adc $40
    sta $40
    lda $42
    adc #$FFFF           ; sign-extend negative disp16 into high word
    sta $42
    jmp inext
dbcc_done:
    lda $40
    clc
    adc #4
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; op_scc: Scc <ea>  (0101 cccc 11 mmmrrr) : byte = $FF if cc true else $00.
; No flags affected. EA is data-alterable byte. cond_test clobbers $52/$54
; (the EA address slots), so test cc FIRST and stash the byte in $74.
op_scc:
    stz $5E              ; byte size
    lda $44
    and #$0F00
    xba
    sta $50              ; cc
    jsr cond_test        ; $52 = 1 if true
    lda $52
    beq scc_false
    lda #$00FF
    bra scc_set
scc_false:
    lda #$0000
scc_set:
    sta $74              ; stash byte (EA path leaves $74 untouched)
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    lda $74
    sta $80
    stz $82
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; ============================================================================
; Batch 7 — MULU/MULS/DIVU/DIVS/CHK (generic EA forms; word source).
;   Reuse usmul/udiv primitives; sign-correct via abs+parity (mirrors the
;   #imm fast-path handlers op_muls_w/op_divs_w). DIVU/DIVS by zero -> trap
;   vector 5; CHK out-of-range -> trap vector 6.
; ============================================================================

; trap_to: take an exception. IN: $50/$52 = return PC (lo16/hi16, hi<=8 bits),
;   $58 = vector number. Pushes PC(4) + SR(2) on SSP ($3C=A7), reads
;   vector[$58] from ROM table at $0, sets PC ($40-$43). Mirrors op_trap's
;   stack/vector sequence. (op_trap left untouched.)
trap_to:
    lda $3C
    sec
    sbc #4
    sta $3C
    tax
    sep #$20
    stz $400000,x        ; PC 31-24 = 0
    inx
    lda $52
    sta $400000,x        ; PC 23-16
    inx
    lda $51
    sta $400000,x        ; PC 15-8
    inx
    lda $50
    sta $400000,x        ; PC 7-0
    rep #$20
    jsr sr_build
    sta $50
    lda $3C
    dec a
    dec a
    sta $3C
    tax
    lda $50
    xba
    sep #$20
    sta $400000,x        ; SR hi
    rep #$20
    inx
    lda $50
    sep #$20
    sta $400000,x        ; SR lo
    rep #$20
    lda $58
    asl a
    asl a
    sta $54              ; vector addr low16 = N*4
    stz $52              ; high16 = 0
    jsr readbyte         ; 31-24 ignored
    inc $54
    jsr readbyte         ; 23-16
    sep #$20
    sta $42
    stz $43
    rep #$20
    inc $54
    jsr readbyte         ; 15-8
    sep #$20
    sta $41
    rep #$20
    inc $54
    jsr readbyte         ; 7-0
    sep #$20
    sta $40
    rep #$20
    rts

op_mulu:                 ; MULU.W <ea>,Dn : Dn = Dn.w * ea.w (unsigned 32) ; NZ,V=C=0
    lda #$0001
    sta $5E              ; word source
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; src word -> $80
    jsr regdst
    lda $00,x
    sta $50              ; a = Dn.w
    lda $80
    sta $52              ; b = src.w
    jsr usmul            ; product -> $94:$96
    jsr regdst
    lda $94
    sta $00,x
    lda $96
    sta $02,x
    jmp mul_done

op_muls:                 ; MULS.W <ea>,Dn : signed 16x16 -> 32 in Dn ; NZ,V=C=0
    lda #$0001
    sta $5E
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; src word -> $80
    jsr regdst
    lda $00,x
    sta $50              ; a = Dn.w
    lda $80
    sta $52              ; b = src.w
    stz $90              ; sign parity
    lda $50
    bpl mls_apos
    sec
    lda #$0000
    sbc $50
    sta $50
    inc $90
mls_apos:
    lda $52
    bpl mls_bpos
    sec
    lda #$0000
    sbc $52
    sta $52
    inc $90
mls_bpos:
    jsr usmul            ; |a|*|b| -> $94:$96
    lda $90
    and #$0001
    beq mls_pos
    sec
    lda #$0000
    sbc $94
    sta $94
    lda #$0000
    sbc $96
    sta $96
mls_pos:
    jsr regdst
    lda $94
    sta $00,x
    lda $96
    sta $02,x
    ; fall through to mul_done
mul_done:                ; product in $94:$96 ; set N,Z ; V=C=0 ; PC += $46
    lda $94
    ora $96
    bne muld_nz
    lda #$0001
    sta $60
    bra muld_n
muld_nz:
    stz $60
muld_n:
    lda $96
    and #$8000
    beq muld_np
    lda #$0001
    sta $70
    bra muld_v
muld_np:
    stz $70
muld_v:
    stz $72              ; V=0
    stz $6E              ; C=0
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_divu:                 ; DIVU.W <ea>,Dn : Dn(32)/ea.w -> quot(lo16),rem(hi16)
    lda #$0001
    sta $5E              ; word divisor
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; divisor -> $80
    lda $80
    bne divu_ok
    stz $70              ; DIVU #0 (per MAME): N=Z=V=C=0, X kept
    stz $60
    stz $72
    stz $6E
    jmp do_trap5         ; divide by zero -> vector 5
divu_ok:
    sta $54              ; divisor
    jsr regdst
    lda $00,x
    sta $50              ; dividend lo16
    lda $02,x
    sta $52              ; dividend hi16
    jsr udiv             ; quot $50:$52, rem $94
    lda $52
    beq divu_noov
    lda #$0001
    sta $72              ; quotient overflow: V=1, no write
    stz $6E              ; C=0
    bra div_pcadv
divu_noov:
    jsr regdst
    lda $50
    sta $00,x            ; quotient -> low16
    lda $94
    sta $02,x            ; remainder -> high16
    stz $72              ; V=0
    stz $6E              ; C=0
    lda $50
    bne divu_nz
    lda #$0001
    sta $60
    bra divu_n
divu_nz:
    stz $60
divu_n:
    lda $50
    and #$8000
    beq divu_np
    lda #$0001
    sta $70
    bra div_pcadv
divu_np:
    stz $70
div_pcadv:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_divs:                 ; DIVS.W <ea>,Dn : signed 32/16 -> quot(lo16),rem(hi16)
    lda #$0001
    sta $5E
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; divisor -> $80
    lda $80
    bne divs_ok
    stz $70              ; DIVS #0 (per MAME): N=V=C=0, Z=1, X kept
    lda #$0001
    sta $60
    stz $72
    stz $6E
    jmp do_trap5
divs_ok:
    jsr regdst
    lda $00,x
    sta $50              ; dividend lo16
    lda $02,x
    sta $52              ; dividend hi16
    stz $90              ; quotient sign parity
    stz $92              ; remainder sign (= dividend sign)
    lda $52
    bpl dvs_dpos
    sec                  ; abs(dividend)
    lda #$0000
    sbc $50
    sta $50
    lda #$0000
    sbc $52
    sta $52
    inc $90
    inc $92
dvs_dpos:
    lda $80
    sta $54
    bpl dvs_spos
    sec                  ; abs(divisor)
    lda #$0000
    sbc $54
    sta $54
    inc $90
dvs_spos:
    jsr udiv             ; |quot| $50:$52, |rem| $94
    lda $52
    bne dvs_ovf          ; |quot| >= $10000 -> overflow
    lda $90
    and #$0001
    beq dvs_qpos
    lda $50
    cmp #$8001
    bcs dvs_ovf          ; negative result: overflow if |quot| > $8000
    bra dvs_signfix
dvs_qpos:
    lda $50
    cmp #$8000
    bcs dvs_ovf          ; positive result: overflow if |quot| > $7FFF
dvs_signfix:
    lda $90
    and #$0001
    beq dvs_qfix_done
    sec
    lda #$0000
    sbc $50
    sta $50
dvs_qfix_done:
    lda $92
    beq dvs_rfix_done
    sec
    lda #$0000
    sbc $94
    sta $94
dvs_rfix_done:
    jsr regdst
    lda $50
    sta $00,x
    lda $94
    sta $02,x
    stz $72
    stz $6E
    lda $50
    bne dvs_nz
    lda #$0001
    sta $60
    bra dvs_n
dvs_nz:
    stz $60
dvs_n:
    lda $50
    and #$8000
    beq dvs_np
    lda #$0001
    sta $70
    jmp div_pcadv
dvs_np:
    stz $70
    jmp div_pcadv
dvs_ovf:
    lda #$0001
    sta $72              ; V=1, no write
    stz $6E
    jmp div_pcadv

do_trap5:                ; divide-by-zero: save next-PC, vector 5
    lda $40
    clc
    adc $46
    sta $50
    lda $42
    adc #$0000
    and #$00FF
    sta $52
    lda #$0005
    sta $58
    jsr trap_to
    jmp inext

op_chk:                  ; CHK.W <ea>,Dn : if Dn.w<0 or Dn.w>ea.w (signed) -> trap6
    lda #$0001
    sta $5E
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; bound -> $80
    jsr regdst
    lda $00,x
    sta $84              ; value = Dn.w
    and #$8000
    beq chk_nonneg
    lda #$0001
    sta $70              ; Dn < 0 : N=1
    jmp do_trap6
chk_nonneg:
    lda $80
    and #$8000
    bne chk_trap0        ; bound < 0, value >= 0 -> out of range
    lda $84
    cmp $80
    beq chk_ok           ; value == bound -> in range
    bcc chk_ok           ; value < bound -> in range
chk_trap0:
    stz $70              ; value > bound : N=0
    jmp do_trap6
chk_ok:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

do_trap6:                ; CHK out-of-range: N set by caller; Z=V=C=0 (per MAME)
    stz $60
    stz $72
    stz $6E
    lda $40
    clc
    adc $46
    sta $50
    lda $42
    adc #$0000
    and #$00FF
    sta $52
    lda #$0006
    sta $58
    jsr trap_to
    jmp inext

; ============================================================================
; Batch 8 — control/system: ILLEGAL, TRAPV, RESET, STOP, RTR, EXG, TAS,
;   MOVE from SR / to CCR / to SR, MOVE USP, MOVEP. Reuses trap_to (B7),
;   sr_build/sr_apply, and the EA engine.
; ============================================================================

; ccr_apply: A.low = CCR byte -> set C/X/V/Z/N; mask ($7C) untouched.
; (low-byte subset of sr_apply; shared by RTR and MOVE to CCR)
ccr_apply:
    and #$00FF
    sta $86
    and #$0001
    sta $6E              ; C
    lda $86
    and #$0010
    beq cca_x0
    lda #$0001
    sta $A2              ; X
    bra cca_v
cca_x0:
    stz $A2
cca_v:
    lda $86
    and #$0002
    beq cca_v0
    lda #$0001
    sta $72              ; V
    bra cca_z
cca_v0:
    stz $72
cca_z:
    lda $86
    and #$0004
    beq cca_z0
    lda #$0001
    sta $60              ; Z
    bra cca_n
cca_z0:
    stz $60
cca_n:
    lda $86
    and #$0008
    beq cca_n0
    lda #$0001
    sta $70              ; N
    rts
cca_n0:
    stz $70
    rts

op_illegal:              ; ILLEGAL ($4AFC): trap vec4; stacked PC = instr addr; flags kept
    lda $40
    sta $50
    lda $42
    and #$00FF
    sta $52
    lda #$0004
    sta $58
    jsr trap_to
    jmp inext

op_trapv:                ; TRAPV ($4E76): if V -> trap vec7 (retPC=next); else PC+=2
    lda $72
    bne trapv_take
    lda $40
    clc
    adc #2
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext
trapv_take:
    lda $40
    clc
    adc #2
    sta $50
    lda $42
    adc #$0000
    and #$00FF
    sta $52
    lda #$0007
    sta $58
    jsr trap_to
    jmp inext

op_reset:                ; RESET ($4E70): no external bus; treat as no-op
    lda $40
    clc
    adc #2
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_stop:                 ; STOP #imm ($4E72): SR = imm; (halt modeled as continue)
    jsr rdw2
    jsr sr_apply
    lda $40
    clc
    adc #4
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_rtr:                  ; RTR ($4E77): CCR = pop.w (low byte only); PC = pop.l
    ldx $3C
    sep #$20
    lda $400000,x        ; CCR word hi (ignored)
    inx
    lda $400000,x        ; CCR word lo
    sta $50
    rep #$20
    lda $50
    jsr ccr_apply
    lda $3C
    clc
    adc #2
    sta $3C
    ldx $3C
    sep #$20
    lda $400000,x        ; PC 31-24 (ignored)
    inx
    lda $400000,x        ; 23-16
    sta $42
    stz $43
    inx
    lda $400000,x        ; 15-8
    sta $41
    inx
    lda $400000,x        ; 7-0
    sta $40
    rep #$20
    lda $3C
    clc
    adc #4
    sta $3C
    jmp inext

op_move_an_usp:          ; MOVE An,USP ($4E60|An): USP = An
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $00,x
    sta $A4
    lda $02,x
    sta $A6
    lda $40
    clc
    adc #2
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_move_usp_an:          ; MOVE USP,An ($4E68|An): An = USP
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax
    lda $A4
    sta $00,x
    lda $A6
    sta $02,x
    lda $40
    clc
    adc #2
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_exg:                  ; EXG ($C140 Dn,Dn / $C148 An,An / $C188 Dx,Ay): swap 32-bit
    lda $44
    and #$00F8           ; opmode<<3
    sta $8A
    lda $44              ; Rx*4 (bits 11-9)
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
    sta $86
    lda $44              ; Ry*4 (bits 2-0)
    and #$0007
    asl a
    asl a
    sta $88
    lda $8A
    cmp #$0048
    bne exg_n48
    lda $86              ; An,An : both +$20
    clc
    adc #$0020
    sta $86
    lda $88
    clc
    adc #$0020
    sta $88
    bra exg_swap
exg_n48:
    cmp #$0088
    bne exg_swap         ; Dn,Dn : both as-is
    lda $88              ; Dx,Ay : Ry +$20
    clc
    adc #$0020
    sta $88
exg_swap:
    ldx $86
    lda $00,x
    sta $90
    lda $02,x
    sta $92              ; $90/$92 = Rx
    ldx $88
    lda $00,x
    sta $94
    lda $02,x
    sta $96              ; $94/$96 = Ry
    ldx $86
    lda $94
    sta $00,x
    lda $96
    sta $02,x            ; Rx = Ry
    ldx $88
    lda $90
    sta $00,x
    lda $92
    sta $02,x            ; Ry = Rx
    lda $40
    clc
    adc #2
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_tas:                  ; TAS <ea> ($4AC0|ea): byte; N/Z from value; V=C=0; set bit7
    stz $5E              ; byte
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; byte -> $80
    lda $80
    and #$00FF
    bne tas_nz
    lda #$0001
    sta $60
    bra tas_n
tas_nz:
    stz $60
tas_n:
    lda $80
    and #$0080
    beq tas_np
    lda #$0001
    sta $70
    bra tas_v
tas_np:
    stz $70
tas_v:
    stz $72
    stz $6E
    lda $80
    ora #$0080           ; set bit 7
    sta $80
    stz $82
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_move_from_sr:         ; MOVE SR,<ea> ($40C0|ea): EA.w = SR ; no flag change
    lda #$0001
    sta $5E
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr sr_build
    sta $80
    stz $82
    jsr ea_write
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_move_to_ccr:          ; MOVE <ea>,CCR ($44C0|ea): CCR = EA.w low byte
    lda #$0001
    sta $5E
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    jsr ccr_apply
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_move_to_sr:           ; MOVE <ea>,SR ($46C0|ea): SR = EA.w (full SR)
    lda #$0001
    sta $5E
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read
    lda $80
    jsr sr_apply
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; MOVEP ($0xx8, mode==An): move Dn <-> alternate bytes at (d16,Ay). No flags.
;   opmode (bits 8-6): 100=W mem->Dx, 101=L mem->Dx, 110=W Dx->mem, 111=L Dx->mem
op_movep:
    jsr rdw2             ; d16 displacement
    sta $50
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; Ay slot
    lda $02,x
    sta $52
    lda $00,x
    sta $54
    lda $50
    jsr add_signext_w    ; $52/$54 = Ay + signext(d16)
    jsr regdst
    stx $84              ; Dx slot
    lda $44
    and #$01C0
    cmp #$0180
    beq mvp_w_r2m
    cmp #$01C0
    beq mvp_l_r2m
    cmp #$0100
    beq mvp_w_m2r
    ; $0140 : MOVEP.L mem->Dx
    jsr movep_rdbyte
    xba
    sta $88
    jsr movep_rdbyte
    ora $88
    sta $88              ; Dx.hi16 = b0:b1
    jsr movep_rdbyte
    xba
    sta $8A
    jsr movep_rdbyte
    ora $8A              ; Dx.lo16 = b2:b3
    ldx $84
    sta $00,x
    lda $88
    sta $02,x
    jmp movep_done
mvp_w_m2r:               ; MOVEP.W mem->Dx (Dx.hi16 unchanged)
    jsr movep_rdbyte
    xba
    sta $88
    jsr movep_rdbyte
    ora $88
    ldx $84
    sta $00,x
    jmp movep_done
mvp_w_r2m:               ; MOVEP.W Dx->mem : [addr]=b15-8, [addr+2]=b7-0
    ldx $84
    lda $00,x
    sta $88
    xba
    jsr movep_wrbyte     ; b15-8
    lda $88
    jsr movep_wrbyte     ; b7-0
    jmp movep_done
mvp_l_r2m:               ; MOVEP.L Dx->mem
    ldx $84
    lda $02,x
    sta $88              ; hi16
    lda $00,x
    sta $8A              ; lo16
    lda $88
    xba
    jsr movep_wrbyte     ; b31-24
    lda $88
    jsr movep_wrbyte     ; b23-16
    lda $8A
    xba
    jsr movep_wrbyte     ; b15-8
    lda $8A
    jsr movep_wrbyte     ; b7-0
movep_done:
    lda $40
    clc
    adc #4
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

movep_rdbyte:            ; read byte at $52:$54 -> A.low ; $54 += 2
    jsr readbyte
    and #$00FF
    pha
    lda $54
    clc
    adc #2
    sta $54
    pla
    rts

movep_wrbyte:            ; write A.low byte to $52:$54 ; $54 += 2
    and #$00FF
    sta $80
    jsr writebyte
    lda $54
    clc
    adc #2
    sta $54
    rts

inext:
    lda $7E              ; single-step test mode? (harness sets $7E=1)
    and #$00FF           ; low byte only ($7F is unrelated)
    beq instep_norm
    lda #$0001
    sta $4E              ; done marker: one opcode executed
    jmp test_idle        ; back to the poll-idle loop (await next vector)
instep_norm:
    lda $4A
    inc a
    sta $4A
    bne nocarry
    inc $4C              ; high word of 32-bit step counter
nocarry:
    lda $4C
    cmp #$0800           ; safety cap raised (~134M) — main loop runs many frames
    bcs docap
    jmp iloop
docap:
    lda #$CAFE
    sta $4E
idone:
    lda $48
    sta $5E              ; expose logged byte count (separate from stop @ $4E)
    lda $7E              ; TEST-HARNESS recovery: in single-step mode a halt ($DEAD/$CAFE)
    and #$00FF           ; must NOT wedge the session -- return to the poll loop so the next
    bne idone_test       ; vector still runs. The halt value stays in $4E for the harness to
ispin:                   ; read as an "unimplemented op" finding. (No effect in production:
    bra ispin            ; $7E=0 there, so production halts spin as before.)
idone_test:
    jmp test_idle

; test_idle: single-step poll loop (test mode only). Wait for the harness to set
; the go-flag $A0, then run exactly one op (the $7E hook returns here after it).
test_idle:
    lda $A0
    and #$00FF
    beq test_idle
    stz $A0              ; consume go-flag
    stz $4E              ; clear done marker
    jmp iloop

nmi:
    rti
irq:
    rti

; C-Chip command-1 boot response (256 bytes of downloaded 68K code), captured
; from MAME (data/cchip_boot_response.bin). Read at $00:F700 via DBR=$00.
.org $E000
; op_mw_d16d16_v2 — MOVE.W (d16,An),(d16,An) with a ROM-AWARE source read. The original
; read src from $40 work RAM unconditionally; but e.g. $8D86 `move.w $4(a1),$2930(a5)` has
; a1=$6AB4 (ROM table) -> it read $40 garbage (0) -> the level palette index $2930 stayed 0
; -> the fade ramped to the wrong (gray) palette. readbyte routes $F0->$40 else ROM/IO.
op_mw_d16d16_v2:
    jsr rdw2
    sta $50            ; src d16
    jsr rdw4
    sta $56            ; dst d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                ; src An slot
    lda $02,x
    sta $52            ; src high16 (readbyte ROM-awareness)
    lda $00,x
    clc
    adc $50
    sta $54            ; src low16 + d16 ($54/$55 = src addr; keep intact for inc)
    jsr readbyte       ; high byte (big-endian)
    sep #$20
    sta $51            ; data high (NOT $55 -> that is the addr high byte)
    rep #$20
    inc $54
    jsr readbyte       ; low byte
    sep #$20
    sta $50            ; data low
    rep #$20
    jsr regdstA        ; dst An slot
    lda $00,x
    clc
    adc $56
    tax                ; dst addr (work RAM)
    sep #$20
    lda $51
    sta $400000,x      ; high byte
    inx
    lda $50
    sta $400000,x      ; low byte
    rep #$20
    lda $50
    jsr setnz_w
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

; op_mw_d16dn_v2 — MOVE.W (d16,An),Dn with ROM-aware source (was $40-only; ROM-table
; sources via (d16,An) misread as work RAM). readbyte routes $F0->$40 else ROM/IO.
op_mw_d16dn_v2:
    jsr rdw2
    sta $50              ; src d16 (reused as data-low later)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $02,x
    sta $52              ; src high16
    lda $00,x
    clc
    adc $50
    sta $54              ; src low16 + d16
    jsr readbyte         ; high byte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte         ; low byte
    sep #$20
    sta $50
    rep #$20
    jsr regdst           ; Dn slot
    lda $50              ; word = $51<<8 | $50
    sta $00,x            ; Dn low16
    jsr setnz_w
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

; op_mw_d16pre_v2 — MOVE.W (d16,An),-(An) with ROM-aware source (dst stack is work RAM).
op_mw_d16pre_v2:
    jsr rdw2
    sta $50              ; src d16 (reused as data-low later)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; src An slot
    lda $02,x
    sta $52              ; src high16
    lda $00,x
    clc
    adc $50
    sta $54              ; src low16 + d16
    jsr readbyte         ; high byte
    sep #$20
    sta $51
    rep #$20
    inc $54
    jsr readbyte         ; low byte
    sep #$20
    sta $50
    rep #$20
    jsr regdstA          ; dst An slot (bits 11-9)
    lda $00,x
    sec
    sbc #2
    sta $00,x            ; An -= 2
    tax                  ; dst addr (stack work RAM)
    sep #$20
    lda $51
    sta $400000,x        ; high byte
    inx
    lda $50
    sta $400000,x        ; low byte
    rep #$20
    lda $50
    jsr setnz_w
    lda $40
    clc
    adc #4
    sta $40
    jmp inext
; setnz_b / setnz_w / setnz_l — MOVE flag helpers: set N($70)/Z($60) size-aware, V($72)=
; C($6E)=0, X kept (full 68K MOVE CCR). The specific MOVE handlers set Z-only via
; setz_from_a; swapping that call to these completes them. setnz_b/w take the value in A;
; setnz_l takes $80=lo16 / $82=hi16 preset by the caller.
setnz_b:
    and #$00FF
    sta $80
    stz $82
    stz $5E              ; size byte
    bra setnz_fin
setnz_w:
    sta $80
    stz $82
    lda #$0001
    sta $5E              ; size word
    bra setnz_fin
setnz_l:
    lda #$0002
    sta $5E              ; size long ($80/$82 preset by caller)
setnz_fin:
    jsr set_nz           ; N($70)/Z($60) from $80/$82 by size; V/C/X untouched
    stz $72              ; V = 0
    stz $6E              ; C = 0
    rts

; move_dispatch_check — A=$44 (opcode). MOVE/MOVEA = $1/$2/$3xxx (bits15-14==00 AND
; bits13-12 != 00); route those to op_move_g. Everything else returns to dsp_clr_cont
; (the CLR-check `cmp #$4200`, A reloaded + `and #$FF00` as the original instruction did).
move_dispatch_check:
    and #$C000
    bne mdc_no           ; bits15-14 != 00 -> not $0-3xxx
    lda $44
    and #$3000
    beq mdc_no           ; bits13-12 == 00 -> $0xxx immediate, not MOVE
    jmp op_move_g
mdc_no:
    lda $44
    and #$FF00
    jmp dsp_clr_cont

; =============================================================================
; jsrabs_hook — op_jsr_abs return-push, plus a LOCK-STEP VALIDATION HALT.
; Normally just tail-does push32r (push the 24-bit return) and rts. When the
; harness arm flag (SA-1 IRAM $0500, 0 in production) is set, it freezes the
; interpreter the instant the IRQ handler calls GAME_TICK ($00003A92) -- i.e. at
; a per-frame boundary identical to MAME's `bpset 3a92`. The harness injects
; MAME's frame-N state, arms, runs one game-frame, and reads work RAM here to
; diff vs MAME's frame N+1. $0502 = done marker (harness polls it).
; Production-safety: relies on IRAM $0500 powering up 0 (true in Mesen). For a
; shipping build, clear $0500 at reset before enabling the hook.
; =============================================================================
.org $E200
jsrabs_hook:
    jsr push32r          ; do the normal return-push FIRST (stack must match MAME wramB)
    rep #$30
    lda $0700            ; armed?  (flags moved $05xx->$07xx; ring now fills $0400-$05FF, 128 entries)
    beq jh_ret
    lda $50              ; target bank
    bne jh_ret
    lda $52              ; target low16
    cmp #$3A92
    bne jh_ret
    lda $40              ; gate on the call SITE (IRQ handler $0708) so interp B0->B1 and MAME's
    cmp #$0708           ; hit-to-hit pair the SAME logical interval (the two $3A92 call sites
    bne jh_ret           ; $06F0/$0708 make "consecutive $3A92" an ambiguous unit otherwise)
    lda #$0001
    sta $0702            ; done marker (harness sees the freeze)
    stz $0704            ; clear release pulse
jh_spin:
    lda $0704            ; wait here (clean inter-op point) for the harness release pulse
    beq jh_spin
    jmp iloop            ; released -> resume fetch at $40 (harness injected the new PC/state)
jh_ret:
    rts

; rb_sound — $800003 TC0140SYT sound-comm read. MAME's $2E06 reads it twice per poll and
; forms COMB=(read2<<4)|(read1&$F); the observed sequence alternates (04,04)->$44 and
; (01,0E)->$E1 (sound busy/ready). Replicate that [04,04,01,0E] cycle via a per-read counter
; ($0506 IRAM, 0 at boot) so the game's sound watchdog ($1C49 reload @ $2DB0) resets like MAME
; instead of timing out. Other $800000 reads keep the $04 ACK status.
rb_sound:
    lda $54
    cmp #$0003
    bne rbs_04
    lda $0706
    inc a
    sta $0706            ; counter++ (per $800003 read)
    dec a                ; A = pre-increment counter
    and #$0003
    cmp #$0002
    bcc rbs_04           ; 0,1 -> $04
    beq rbs_01           ; 2   -> $01
    lda #$000E           ; 3   -> $0E
    rts
rbs_01:
    lda #$0001
    rts
rbs_04:
    lda #$0004
    rts

; branch_apply — bank-correct relative-branch target. Callers set $50 = signed
; disp16 (sign-extended) and `jmp branch_apply`; this computes the FULL 24-bit
; PC = (PC+2) + sign_extend(disp16), propagating carry/borrow into the bank byte
; ($42). The old per-site tails added only the low16 ($40), so a relative branch
; whose target lay in a different 24-bit bank kept the wrong bank: e.g. the
; backward `bsr.w $00CC10` at $0114EE (disp $B720 = -$48E0) wrongly landed at
; $01CC10 and ran off into bank-$01 data ($F02A4C). 16-bit A on entry/exit.
branch_apply:
    lda $40
    clc
    adc #2
    sta $40
    lda $42
    adc #$0000          ; PC += 2, carry -> bank
    sta $42
    lda $40
    clc
    adc $50             ; low16 += disp16 ; C = carry-out
    sta $40
    lda $50
    bmi ba_neg          ; (LDA/BMI preserve C)
    lda $42
    adc #$0000          ; disp >= 0: bank += carry
    sta $42
    jmp inext
ba_neg:
    lda $42
    adc #$FFFF          ; disp <  0: bank += carry - 1 (sign-extend high = $FFFF)
    sta $42
    jmp inext

; dbg_fetch — per-instruction debug hook (replaces the inline 68K-PC ring write).
; Always logs the 68K PC to the 128-entry ring at $0400 (idx $48). Additionally, if
; the debug-freeze target $0710 is non-zero and equals the current 68K PC low16 ($40),
; it freezes (sets $0712=1, spins on $0714) so the harness can read the interp register
; file mid-routine -- the $3A92 jsr-hook can't reach non-jsr PCs like the task loops.
; One-shot: clears $0710 on release. 16-bit A; preserves X (decode needs it).
dbg_fetch:
    phx
    ldy $48
    lda $40
    sta $0400,y
    lda $42
    sta $0402,y
    tya
    clc
    adc #4
    and #$01FF
    tay
    sty $48
    ; stream ALL frame PCs to BW-RAM $40:8000+ (non-wrapping; byte ptr $0718; cap ~16k).
    ; Enabled when the harness sets $0718=0 at B0; production leaves $0718=$FFF8 -> capped.
    ldx $0718
    cpx #$FFF8
    bcs ds_skip
    lda $40
    sta $408000,x
    lda $42
    sta $408002,x
    txa
    clc
    adc #4
    tax
    stx $0718
ds_skip:
    lda $0710           ; debug-freeze target low16 (0 = disabled)
    beq df_ret
    cmp $40
    bne df_ret
    lda $0716           ; target bank (must also match $42)
    cmp $42
    bne df_ret
    lda #$0001
    sta $0712           ; frozen marker (harness polls)
    stz $0714
df_spin:
    lda $0714
    beq df_spin
    stz $0710           ; one-shot: don't re-freeze the same PC next iteration
df_ret:
    plx
    rts

; op_movem_d16 — movem.l (d16,An),<list> : load regs from [An + sign_ext(d16)],
; ROM/work-RAM-aware via readbyte, ascending, An NOT updated ; PC += 6.
; This addressing mode (opcode $4CE8|An) was UNIMPLEMENTED -> the coroutine/context
; restore `movem.l ($34ca,A5),A1` at $1C99E fell through every dispatch and HUNG the
; interpreter mid-busy-frame. Modeled on op_movem_abs. (bit0=D0..bit15=A7; slot=i*4.)
op_movem_d16:
    jsr rdw2
    sta $50              ; mask
    jsr rdw4
    sta $56              ; d16 (signed)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot
    lda $00,x            ; An low16
    clc
    adc $56              ; EA.low16 = An.low16 + d16 ; C = carry
    sta $54
    lda $02,x            ; An high16
    ldy $56
    bmi md_neg           ; (LDA/LDY preserve C)
    adc #$0000           ; d16 >= 0: high += carry
    bra md_sethi
md_neg:
    adc #$FFFF           ; d16 <  0: high += carry - 1 (sign extend)
md_sethi:
    sta $52              ; EA high16 (readbyte src)
    ldy #$0000
md_loop:
    lda $50
    lsr a
    sta $50
    bcc md_skip
    jsr readbyte         ; bits31-24
    sep #$20
    sta $8F
    rep #$20
    inc $54
    jsr readbyte         ; bits23-16
    sep #$20
    sta $8E
    rep #$20
    inc $54
    jsr readbyte         ; bits15-8
    sep #$20
    sta $8D
    rep #$20
    inc $54
    jsr readbyte         ; bits7-0
    sep #$20
    sta $8C
    rep #$20
    inc $54
    tya
    asl a
    asl a
    tax                  ; reg slot = i*4
    lda $8C              ; low16 = $8D:$8C
    sta $00,x
    lda $8E              ; high16 = $8F:$8E
    sta $02,x
md_skip:
    iny
    cpy #$0010
    bne md_loop
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

; op_lea_abs_w — lea (xxx).W,An : An = sign_extend16(word) ; PC += 4. Absolute-SHORT
; addressing ($41F8|An<<9) was unimplemented -> `lea $36b2.w,a4` at $1C1A4 (a sprite-table
; base lookup, hit when Superman moves) hung the interp mid-gameplay-frame.
op_lea_abs_w:
    jsr rdw2
    sta $54              ; abs16
    jsr regdstA          ; X = An slot (bits 11-9)
    lda $54
    sta $00,x            ; An low16
    bmi law_neg          ; (STA preserves N from LDA)
    lda #$0000
    bra law_hi
law_neg:
    lda #$FFFF
law_hi:
    sta $02,x            ; An high16 = sign extension
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

; op_movem_d16_store — movem.l <list>,(d16,An) : store D0..A7 (forward, by mask) to
; [An + sign_ext(d16)], An NOT updated ; PC += 6. Work-RAM dest ($40), like op_movem_pre.
; Was UNIMPLEMENTED ($48E8|An) -> the coroutine context SAVE `movem.l a1,$34ca(a5)` at
; $1C986 hung the interp. Pairs with op_movem_d16 (the load side).
op_movem_d16_store:
    jsr rdw2
    sta $50              ; mask (bit0=D0..bit15=A7)
    jsr rdw4
    sta $58              ; d16 (signed)
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot
    lda $00,x            ; An low16
    clc
    adc $58
    sta $58              ; running dst = An.low16 + d16 (work-RAM low16)
    ldy #$0000
ms_loop:
    lda $50
    lsr a
    sta $50
    bcc ms_skip
    tya
    asl a
    asl a
    tax                  ; reg slot = i*4
    lda $00,x
    sta $54              ; reg low16  ($55:$54)
    lda $02,x
    sta $56              ; reg high16 ($57:$56)
    ldx $58
    sep #$20
    lda $57              ; bits31-24 (big-endian store)
    sta $400000,x
    inx
    lda $56              ; bits23-16
    sta $400000,x
    inx
    lda $55              ; bits15-8
    sta $400000,x
    inx
    lda $54              ; bits7-0
    sta $400000,x
    rep #$20
    lda $58
    clc
    adc #4
    sta $58              ; dst += 4
ms_skip:
    iny
    cpy #$0010
    bne ms_loop
    lda $40
    clc
    adc #6
    sta $40
    jmp inext

; =============================================================================
; Phase B: native-escape hook + entry412 (route live $000412 RNG to native 65816)
; bsr_hookpush REPLACES op_bsr/op_jsr_pcrel's `jsr push32r` (byte-neutral): it resolves
; the target and, if the hook is enabled ($071A!=0) and the target is in the dispatch
; chain, sets the 68K PC to the return address and JMPs the native routine (which ends
; `jmp inext`, never touching the 68K stack). Otherwise it does the normal push.
;
; --- FOUNDATION CONTRACT for bulk transpilation (add native escapes safely) ---
; 1. SAFETY: only hook targets that tools/leaf_check.py reports SAFE-LEAF (no call /
;    indirect jmp / device I/O on ANY path). The trace leaf flag is unsound -- $24D98
;    and $25110 "looked" like leaves in one trace but are not.
; 2. STACK: each native entry must end `jmp inext` and NEVER rts/touch the 68K stack.
;    On a HIT the chain `pla`s op_bsr's 65816 return so S stays balanced (the earlier
;    `jsr hook_check;jmp native` form leaked 4 bytes/hit -> crash after ~64).
; 3. SCRATCH: native entries use ONLY transient DP $80-$9E. They must NOT clobber the
;    68K register file $00-$3F (except the result regs the real routine writes), the
;    flags $60-$7F, or $A0-$AC. Read/write work RAM via $40:xxxx (long), ROM via readbyte.
; 4. ENABLE: $071A=0 (off) by default so the lockstep hook-off/on differential works
;    (lockstep.py argv3). Production sets $071A=1 once (e.g. at boot) to use the escapes.
; 5. VALIDATE every new escape with the hook-off/on differential (bit-identical work RAM
;    + reg file) and multi_hit.py (stack stays balanced across many hits).
; 6. EXTEND: add an immediate-compare block in bsr_hookpush (not an abs table -- that was
;    DBR/PBR-fragile) sending its `bne` to the next block; add the native entry routine.
; =============================================================================
bsr_hookpush:            ; in: $50=signed disp, $54=return lo16 ; out: (miss) push32r+rts
    lda $40
    clc
    adc #2
    sta $5C
    lda $42
    adc #$0000
    sta $5E              ; (PC+2) 24-bit
    lda $5C
    clc
    adc $50              ; + disp16 low
    sta $5C
    lda $50
    bmi bhp_neg
    lda $5E
    adc #$0000
    bra bhp_tb
bhp_neg:
    lda $5E
    adc #$FFFF
bhp_tb:
    sta $5E              ; target = $5E:$5C
    ; --- escape dispatch: INLINE immediate-compare chain (no jsr -> a HIT only has op_bsr's
    ; RET1 on the 65816 stack to drop). HIT: set 68K PC=return, `pla` to drop RET1 (the
    ; native ends `jmp inext`, never rts -> else 4 bytes/hit leak -> crash after ~64), then
    ; jmp the native entry. Immediate compares (not an abs table) keep this DBR/PBR-safe.
    ; EXTEND for bulk: per leaf_check.py-verified SAFE-LEAF target, add a block like the
    ; $0412 one, sending its `bne` to the next block's label and ending the chain at bhp_push.
    lda $071A            ; hook enable (0 = off)
    beq bhp_push
    lda $5E              ; both escape targets are bank 0
    bne bhp_push
    ; -- $000412 -> entry412 --
    lda $5C
    cmp #$0412
    bne bhp_e1
    lda $54
    sta $40              ; 68K PC = return addr (bank $42 unchanged)
    pla                  ; drop RET1 -> 65816 S back at the iloop dispatch level
    jmp entry412
bhp_e1:                  ; -- $00CB9E -> entry_cb9e --  (A still = target lo16)
    cmp #$CB9E
    bne bhp_e2
    lda $54
    sta $40
    pla
    jmp entry_cb9e
bhp_e2:                  ; -- $0015B4 -> entry_15b4 --  (A still = target lo16)
    cmp #$15B4
    bne bhp_push
    lda $54
    sta $40
    pla
    jmp entry_15b4
bhp_push:                ; MISS: push the 24-bit return. push32r derives the return bank
    ; from the caller's carry (PC+len add) which we clobbered -> derive it ourselves.
    lda $54
    cmp $40              ; C set if return-lo16 >= PC-lo16 (i.e. no bank wrap)
    lda $42
    bcs bhp_nob
    inc a                ; return crossed into the next bank
bhp_nob:
    sta $56              ; return bank
    jmp push32           ; push $57:$56:$55:$54, then rts -> op_bsr -> branch_apply

; entry412 — native $000412 (Lehmer RNG, 16-bit state @ [A5+$170E]).
; state(->1 if 0); D7=(state*176)/32749 signed; new state = remainder.
; mirrors: [A5+$170E].w=rem ; D7=(quotient<<16)|rem ; CCR from move.w(rem). jmp inext.
; rng scratch relocated to $80-$94 (transient) so the live reg file $00-$3F is safe.
entry412:
    rep #$30
    inc $071C            ; hit counter (proof the native escape fired)
    lda $34              ; A5 low16
    clc
    adc #$170E
    sta $9A              ; work-RAM offset of state
    tax
    sep #$20
    lda $400000,x        ; state hi byte (big-endian)
    xba
    lda $400001,x        ; state lo byte
    rep #$20
    and #$FFFF
    sta $80              ; rng input
    jsr rng_core_n       ; -> rem $82, quotient $84
    ldx $9A
    lda $82
    sep #$20
    xba
    sta $400000,x        ; new state hi
    xba
    sta $400001,x        ; new state lo
    rep #$20
    lda $82
    sta $1C              ; D7 low16 = remainder (= new state)
    lda $84
    sta $1E              ; D7 high16 = quotient
    lda $82              ; CCR from `move.w D7,(...)` = remainder
    bne e412_nz
    lda #$0001
    sta $60              ; Z set (nonzero=set)
    bra e412_n
e412_nz:
    stz $60              ; Z clear
e412_n:
    lda $82
    and #$8000
    sta $70              ; N = rem bit15
    stz $6E              ; C = 0
    stz $72              ; V = 0
    jmp inext

rng_core_n:              ; in $80 ; out rem $82, quotient $84 (scratch $86-$94)
    rep #$30
    lda $80
    bne rcn_nz
    lda #1
rcn_nz:
    bpl rcn_xpos
    ldy #1
    eor #$FFFF
    clc
    adc #1
    bra rcn_store
rcn_xpos:
    ldy #0
rcn_store:
    sty $92              ; sign of x
    sta $86              ; ma_lo = |x|
    stz $88              ; ma_hi = 0
    lda #176
    sta $8A              ; mb
    jsr umul16_n         ; $8C/$8E = |x|*176
    lda $92
    beq rcn_pp
    jsr neg32_n
rcn_pp:
    lda $8E
    bpl rcn_dp
    ldy #1
    jsr neg32_n
    bra rcn_ds
rcn_dp:
    ldy #0
rcn_ds:
    sty $92
    lda #32749
    sta $90              ; divisor
    jsr udiv32_16_n      ; quotient $8C/$8E, rem $94
    lda $92
    beq rcn_sp
    lda $8C
    eor #$FFFF
    clc
    adc #1
    sta $8C
    lda $94
    eor #$FFFF
    clc
    adc #1
    sta $94
rcn_sp:
    lda $94
    sta $82              ; remainder
    lda $8C
    sta $84              ; quotient
    rts

umul16_n:                ; ma $86/$88 * mb $8A -> $8C/$8E
    stz $8C
    stz $8E
    ldx #16
umn_l:
    lsr $8A
    bcc umn_s
    clc
    lda $8C
    adc $86
    sta $8C
    lda $8E
    adc $88
    sta $8E
umn_s:
    asl $86
    rol $88
    dex
    bne umn_l
    rts

udiv32_16_n:             ; dividend $8C/$8E, divisor $90 -> quotient $8C/$8E, rem $94
    stz $94
    ldx #32
udn_l:
    asl $8C
    rol $8E
    rol $94
    lda $94
    cmp $90
    bcc udn_s
    sbc $90
    sta $94
    inc $8C
udn_s:
    dex
    bne udn_l
    rts

neg32_n:                 ; $8C/$8E = -$8C/$8E
    sec
    lda #0
    sbc $8C
    sta $8C
    lda #0
    sbc $8E
    sta $8E
    rts

; rdw40 / wrw40 — big-endian 16-bit word read/write of 68K work RAM ($F0xxxx) in
; BW-RAM $40. in: X = work-RAM offset (aN.lo + disp). rdw40 -> A=word. wrw40: A=word
; in. 16-bit A on entry/exit; preserve X. (work RAM stores big-endian: [X]=hi,[X+1]=lo.)
rdw40:
    sep #$20
    lda $400000,x        ; hi byte
    xba
    lda $400001,x        ; lo byte
    rep #$20
    rts
wrw40:
    sep #$20
    xba                  ; A.lo = hi byte
    sta $400000,x
    xba                  ; A.lo = lo byte
    sta $400001,x
    rep #$20
    rts
; rdw_a0 — ROM/IO/work-RAM-aware big-endian word read of [a0+Y]. in: Y=byte disp.
;   out: A=word (hi:lo). a0 may point at ROM ($00-$07xxxx) or work RAM, so route through
;   readbyte (NOT $40 direct). readbyte preserves Y,$52,$54 and clobbers $66,$68; $90 scratch.
rdw_a0:
    lda $22
    sta $52              ; a0.hi16
    tya
    clc
    adc $20
    sta $54              ; a0.lo + disp
    jsr readbyte         ; A.lo = [a0+disp] hi byte
    xba
    sta $90              ; hi:00
    inc $54              ; a0.lo + disp + 1 (readbyte preserved $52/$54)
    jsr readbyte         ; A.lo = [a0+disp+1] lo byte
    ora $90              ; A = hi:lo
    rts
; rdb_a0 — ROM-aware byte read of [a0+Y]. in: Y=disp. out: A=byte (hi=0).
rdb_a0:
    lda $22
    sta $52
    tya
    clc
    adc $20
    sta $54
    jmp readbyte         ; tail-call (returns A.lo=byte, A.hi=0)

; entry_cb9e — native $00CB9E (sprite-position update, SAFE-LEAF, ~10 calls/frame).
; 68K (a0/a1/a6 ptrs; a2=[a6-$54]):
;   tst.w (a1); ble rts                         ; signed early-out, regs untouched
;   (a1+6)=(a6-$22)+(a0+6) ; (a1+8)=(a6-$22)+(a0+8)
;   d0=(a0+2); d1=(a0+4); d2.b=(a0+c)
;   btst#7,(a6-$24): set -> d1=(a0+2);d0=(a0+4); neg d0;neg d1;neg.w d2; d2.b+=$80
;   (a1+2)=(a6-$1e)+d0 ; (a1+4)=(a6-$1e)+d1 ; (a1+c).b=d2.b
;   a2=(a6-$54); (a2)=1; (a2+4)=(a1+4); (a2+2)=(a1+2)
; .w ops preserve reg-file high words; d2 mixes .b/.w. Scratch $80-$8C. CCR from the
; exit op (tst.w on early-out; move.w (a1+2) on the normal path). Ends jmp inext.
entry_cb9e:
    rep #$30
    inc $071E            ; cb9e hit counter (validation)
    ldx $24              ; a1.lo  -> X = (a1+0) offset
    jsr rdw40
    sta $80              ; [a1+0] ; sets N/Z
    beq cb_e0            ; signed <= 0 -> early-out (near trampoline to far cb_early)
    bmi cb_e0
    bra cb_norm
cb_e0:
    jmp cb_early
cb_norm:
    ; ---- normal path ----
    ; (a) d0 = [a6-$22] + [a0+6] ; [a1+6] = d0
    lda $38
    clc
    adc #$FFDE           ; -$22
    tax
    jsr rdw40
    sta $82              ; m22 = [a6-$22]
    ldy #$0006
    jsr rdw_a0           ; [a0+6] (a0=ROM)
    clc
    adc $82
    sta $00              ; d0.lo
    lda $24
    clc
    adc #$0006
    tax
    lda $00
    jsr wrw40            ; [a1+6] = d0
    ; (b) d0 = [a6-$22] + [a0+8] ; [a1+8] = d0
    ldy #$0008
    jsr rdw_a0           ; [a0+8] (a0=ROM)
    clc
    adc $82
    sta $00
    lda $24
    clc
    adc #$0008
    tax
    lda $00
    jsr wrw40            ; [a1+8] = d0
    ; (c) base: d0=[a0+2],d1=[a0+4],d2.b=[a0+c]  -> $84/$86, d2 byte (a0=ROM)
    ldy #$0002
    jsr rdw_a0
    sta $84              ; [a0+2]
    ldy #$0004
    jsr rdw_a0
    sta $86              ; [a0+4]
    ldy #$000C
    jsr rdb_a0           ; [a0+c] byte
    sep #$20
    sta $08              ; d2 byte0 (preserve d2 bits 8-31)
    rep #$20
    ; (d) btst #7,[a6-$24].b
    lda $38
    clc
    adc #$FFDC           ; -$24
    tax
    sep #$20
    lda $400000,x
    and #$80
    rep #$20
    bne cb_neg
    ; bit clear: d0=[a0+2], d1=[a0+4] (d2 already = [a0+c])
    lda $84
    sta $00
    lda $86
    sta $04
    bra cb_after
cb_neg:
    ; bit set: d0=-[a0+4], d1=-[a0+2], d2=-(d2.lo16) then byte0+=$80
    lda $86
    eor #$FFFF
    inc a
    sta $00              ; d0 = -[a0+4]
    lda $84
    eor #$FFFF
    inc a
    sta $04              ; d1 = -[a0+2]
    lda $08
    eor #$FFFF
    inc a
    sta $08              ; neg.w d2
    sep #$20
    lda $08
    clc
    adc #$80
    sta $08              ; d2.b += $80
    rep #$20
cb_after:
    ; (e) d3 = [a6-$1e] + d0 ; [a1+2] = d3
    lda $38
    clc
    adc #$FFE2           ; -$1e
    tax
    jsr rdw40
    sta $8A              ; m1e = [a6-$1e]
    clc
    adc $00
    sta $0C              ; d3
    lda $24
    clc
    adc #$0002
    tax
    lda $0C
    jsr wrw40            ; [a1+2] = d3
    ; (f) d3 = [a6-$1e] + d1 ; [a1+4] = d3
    lda $8A
    clc
    adc $04
    sta $0C
    lda $24
    clc
    adc #$0004
    tax
    lda $0C
    jsr wrw40            ; [a1+4] = d3
    ; (g) [a1+c].b = d2.b
    lda $24
    clc
    adc #$000C
    tax
    sep #$20
    lda $08
    sta $400000,x        ; [a1+c] byte
    rep #$20
    ; (h) a2 = [a6-$54] (long, big-endian) ; [a2]=1 ; [a2+4]=[a1+4] ; [a2+2]=[a1+2]
    lda $38
    clc
    adc #$FFAC           ; -$54
    tax
    sep #$20
    lda $400000,x        ; b0
    xba
    lda $400001,x        ; b1
    rep #$20
    sta $2A              ; a2.hi16
    inx
    inx
    sep #$20
    lda $400000,x        ; b2
    xba
    lda $400001,x        ; b3
    rep #$20
    sta $28              ; a2.lo16
    ldx $28
    lda #$0001
    jsr wrw40            ; [a2+0] = 1
    lda $24
    clc
    adc #$0004
    tax
    jsr rdw40            ; [a1+4]
    pha
    lda $28
    clc
    adc #$0004
    tax
    pla
    jsr wrw40            ; [a2+4] = [a1+4]
    lda $24
    clc
    adc #$0002
    tax
    jsr rdw40            ; [a1+2]
    sta $8C              ; for CCR
    pha
    lda $28
    clc
    adc #$0002
    tax
    pla
    jsr wrw40            ; [a2+2] = [a1+2]
    ; CCR = move.w (a1+2): N/Z from [a1+2], V=C=0
    lda $8C
    bne cbn_nz
    lda #$0001
    sta $60
    bra cbn_n
cbn_nz:
    stz $60
cbn_n:
    lda $8C
    and #$8000
    sta $70
    stz $6E
    stz $72
    jmp inext
cb_early:
    ; CCR = tst.w (a1): N/Z from [a1+0] ($80), V=C=0 ; regs untouched
    lda $80
    bne cbe_nz
    lda #$0001
    sta $60
    bra cbe_n
cbe_nz:
    stz $60
cbe_n:
    lda $80
    and #$8000
    sta $70
    stz $6E
    stz $72
    jmp inext

; entry_15b4 — native $0015B4: 255x `move.l (a0)+,(a1)+` block copy (1020 bytes), SAFE-LEAF.
; The interp's op_movl_anp_anp copies BYTE-WISE (src via readbyte, dst via map_snes routing,
; NO flag update). Captured live: a0=work RAM ($F0), a1=$D0 video shadow ($41). Fast path =
; direct word copy $40:(a0.lo) -> $41:((a1.lo&$0FFF)|$3000) (raw byte positions preserved by
; 16-bit moves). Fallback = faithful op_movl_anp_anp x255 for any other bank combo. a0/a1
; post-increment by 1020. No flag update (matches the interp). Scratch $96-$9E. Ends jmp inext.
entry_15b4:
    rep #$30
    inc $0720                ; hit counter
    lda $22
    cmp #$00F0               ; src must be work RAM for the fast path
    bne e15_slow
    lda $26
    cmp #$00D0               ; dst must be the $D0 shadow region
    bne e15_slow
    ; ---- FAST: word copy 1020 bytes, $40:(a0.lo) -> $41:SHADOW_D0+(a1.lo&$0FFF) ----
    lda $20
    sta $96                  ; src ptr lo16 = a0.lo ($96/$97)
    sep #$20
    lda #$40
    sta $98                  ; src bank $40 (work RAM)
    rep #$20
    lda $24
    and #$0FFF
    ora #$3000               ; SHADOW_D0
    sta $9C                  ; dst ptr lo16 ($9C/$9D)
    sep #$20
    lda #$41
    sta $9E                  ; dst bank $41 (video shadow)
    rep #$20
    ldy #$0000
e15_fast:
    lda [$96],y
    sta [$9C],y
    iny
    iny
    cpy #$03FC               ; 1020 bytes
    bne e15_fast
    lda $20
    clc
    adc #$03FC
    sta $20                  ; a0 += 1020
    lda $24
    clc
    adc #$03FC
    sta $24                  ; a1 += 1020
    jmp inext
e15_slow:
    ; ---- FALLBACK: faithful op_movl_anp_anp x255 (any bank combo, byte-wise) ----
    lda #$00FF               ; 255 longs
    sta $9C                  ; long counter
e15_long:
    lda $22
    sta $52
    lda $20
    sta $54                  ; src = a0 (running)
    lda $20
    clc
    adc #$0004
    sta $20                  ; a0 += 4
    lda $26
    sta $5E
    lda $24
    sta $6A                  ; dst = a1 (running)
    lda $24
    clc
    adc #$0004
    sta $24                  ; a1 += 4
    lda $5E
    jsr map_snes
    ldy #$0000
e15_byte:
    jsr readbyte
    sta $50
    lda $C2
    beq e15_w
    cmp #$0001
    bne e15_nw               ; mode 2 -> no-op
    ldx $6A
    sep #$20
    lda $50
    sta $410000,x            ; mode 1 -> $41 shadow
    rep #$20
    bra e15_nw
e15_w:
    ldx $6A
    sep #$20
    lda $50
    sta $400000,x            ; mode 0 -> work RAM $40
    rep #$20
e15_nw:
    inc $54
    inc $6A
    iny
    cpy #$0004
    bne e15_byte
    dec $9C
    bne e15_long
    jmp inext

; jsrabs_hook2 — native-escape dispatch for op_jsr_abs (jsr.l). Target $50(hi):$52(lo),
; return $54. Same call-path as bsr_hookpush but for absolute-long jsr. HIT: pla (drop our
; jsr return -> stack back to inext level), PC=return, jmp the native entry. MISS: tail-jmp
; jsrabs_hook (the original push32r + lockstep-halt). $42 (return bank) stays the PC bank.
jsrabs_hook2:
    php                  ; preserve carry (op_jsr_abs's adc #6) -- jsrabs_hook's push32r needs it
    lda $071A
    beq jah2_miss
    lda $50
    bne jah2_miss        ; all escape targets are bank 0
    lda $52
    cmp #$0412
    beq jah2_e412
    cmp #$CB9E
    beq jah2_ecb9e
    cmp #$15B4
    beq jah2_e15b4
jah2_miss:
    plp                  ; restore carry for push32r
    jmp jsrabs_hook
jah2_e412:
    plp
    pla
    lda $54
    sta $40
    jmp entry412
jah2_ecb9e:
    plp
    pla
    lda $54
    sta $40
    jmp entry_cb9e
jah2_e15b4:
    plp
    pla
    lda $54
    sta $40
    jmp entry_15b4
.org $F700
RESP1:
.incbin "../data/cchip_boot_response.bin"

; =============================================================================
; VIDEO PLUMBING routines, placed in free bank space ($F800+) so adding them does
; NOT shift the main code (a mid-file insertion can push a relative branch out of
; range). All are jsr-called, so position within the bank is irrelevant.
;
;  map_snes — destination-bank dispatch for stores. The live game writes hardware
;  video banks via only op_movl_anp_anp / op_movw_anp_an / op_movw_dn_abs (Stage-0
;  capture, video_writes.log). We mirror them into SNES bank $7E shadow RAM:
;    $B0 = palette (xRGB555 4KB) -> $7E:2000+(lo&$0FFF)
;    $D0 = sprite Y/scroll/ctrl  -> $7E:3000+(lo&$0FFF)
;    $E0 = sprite code+X (16KB)  -> $7E:4000+(lo&$3FFF)  (bases ORA-aligned)
;  in: A=dst hi16, $6A=dst lo16 ; out: $C2=mode(0=$7F work/1=$7E shadow/2=noop),
;  $6A=SNES offset ; preserves $50/$51 and X ; 16-bit A.
; =============================================================================
.org $F800
SHADOW_PAL=$2000
SHADOW_D0=$3000
SHADOW_COD=$4000
STAGING_CGRAM=$8000
map_snes:
    cmp #$00F0
    bne ms_b0
    stz $C2              ; mode 0: work RAM $7F, offset already = lo16
    rts
ms_b0:
    cmp #$00B0
    bne ms_e0
    lda $6A
    and #$0FFF
    ora #SHADOW_PAL
    sta $6A
    bra ms_shadow
ms_e0:
    cmp #$00E0
    bne ms_d0
    lda $6A
    and #$3FFF
    ora #SHADOW_COD
    sta $6A
    bra ms_shadow
ms_d0:
    cmp #$00D0
    bne ms_noop
    lda $6A
    and #$0FFF
    ora #SHADOW_D0
    sta $6A
    bra ms_shadow
ms_noop:
    lda #$0002           ; mode 2: unknown I/O -> no-op
    sta $C2
    rts
ms_shadow:
    lda #$0001           ; mode 1: shadow RAM $7E
    sta $C2
    rts

; ppu_build — convert shadow palette ($7E:2000) -> CGRAM staging ($7E:8000).
; Runs once per simulated game-frame (at the $8A reload), not per real vblank.
; --- video subsystem relocated to bank $E9 (src/video.pasm). map_snes stays here
;     (hot store path). These 3 entries are reached via jsl/jml VID_*. ---
test_or_vid:
    lda $F400
    cmp #$0002
    bne tov_idle
    jml VIDTEST          ; $E98008 -> vidtest_init (no return)
tov_idle:
    jmp test_idle

; =============================================================================
; INPUTS — map the live SNES controller into the arcade C-Chip input mailbox.
; Reads JOY1 with a MANUAL serial read of $4016 (auto-joypad / $4218 didn't update
; in this harness). readbyte routes $900001 -> input_p1, $900005 -> input_coins.
; Arcade mailbox is active-LOW (idle $FF, pressed bit=0).
;   JOY1 (16-bit, MSB first): B(15) Y(14) Select(13) Start(12) Up(11) Down(10)
;                             Left(9) Right(8) A(7) X(6) L(5) R(4)
;   arcade P1 $900001: Up(0) Down(1) Left(2) Right(3) Btn1(4) Btn2(5) Start(7)
;   arcade coins $900005: Coin1(0)
; Scratch: $64 (arcade byte), $66 (JOY1). Returns 16-bit A = byte (low 8).
; =============================================================================
joy_read:                ; -> $66 = 16-bit JOY1 (active-high). On the SA-1 build the interp
    php                  ; can't touch $4016 or $00:0200 WRAM, so the 5A22 (joy5a22) reads
    rep #$30             ; the pad into the BW-RAM mailbox $41:0000 each frame; just load it.
    lda $410000
    sta $66
    plp
    rts

input_p1:
    jsr joy_read
    rep #$30
    stz $64              ; arcade_active (pressed = 1)
    lda $66
    and #$0800           ; Up -> bit0
    beq ip_1
    lda $64
    ora #$0001
    sta $64
ip_1:
    lda $66
    and #$0400           ; Down -> bit1
    beq ip_2
    lda $64
    ora #$0002
    sta $64
ip_2:
    lda $66
    and #$0200           ; Left -> bit2
    beq ip_3
    lda $64
    ora #$0004
    sta $64
ip_3:
    lda $66
    and #$0100           ; Right -> bit3
    beq ip_4
    lda $64
    ora #$0008
    sta $64
ip_4:
    lda $66
    and #$1000           ; Start -> bit7
    beq ip_5
    lda $64
    ora #$0080
    sta $64
ip_5:
    lda $66
    and #$C000           ; B or Y -> Btn1 (bit4)
    beq ip_6
    lda $64
    ora #$0010
    sta $64
ip_6:
    lda $66
    and #$00C0           ; A or X -> Btn2 (bit5)
    beq ip_7
    lda $64
    ora #$0020
    sta $64
ip_7:
    lda $64
    eor #$00FF           ; active-low
    and #$00FF
    rts

input_coins:
    jsr joy_read
    rep #$30
    lda $66
    and #$2000           ; SNES Select -> Coin 1 (active-low bit0)
    beq ic_idle
    lda #$00FE
    rts
ic_idle:
    lda #$00FF
    rts

; push32r: push a RETURN address (24-bit). The high16 ($56) = current PC bank ($42)
; plus the carry from the caller's `$54 = PC + offset` add (callers leave carry set
; after `adc`; do NOT clc before jsr). 68K addrs are 24-bit so $57 ends up $00.
; Used by op_jsr_abs/op_bsr/op_jsr_pcrel/op_jsr_an in place of push32 so returns into
; banks >=1 (the 512KB program spans $00-$07xxxx) keep their bank — else RTS truncates
; to bank 0 and lands in unrelated/zero code (the cross-bank crash past attract).
push32r:
    lda $42
    adc #$0000           ; + carry from caller's low16 add
    sta $56
    jmp push32           ; push $57:$56:$55:$54, then rts to the caller

; store_vid_{byte,word,long}: generic-write fallback for the video banks ($B0/$D0/$E0).
; writebyte/word/long only handle work RAM ($F0); the live game also writes the arcade
; video banks via generic MOVE handlers (op_move_g etc.) -- those were DROPPED, so the BG
; playfield / OBJ never reached the $41 shadow. Route them through map_snes -> $41 shadow
; (same big-endian convention as op_movw_anp_an's mwa_shadow). Value in $80..$83, addr
; $52:$54. map_snes preserves $50/$51 and X; it does not touch $80-$83.
store_vid_word:
    lda $54
    sta $6A
    lda $52
    jsr map_snes
    lda $C2
    cmp #$0001
    bne svw_done
    ldx $6A
    sep #$20
    lda $81
    sta $410000,x
    inx
    lda $80
    sta $410000,x
    rep #$20
svw_done:
    rts
store_vid_long:
    lda $54
    sta $6A
    lda $52
    jsr map_snes
    lda $C2
    cmp #$0001
    bne svl_done
    ldx $6A
    sep #$20
    lda $83
    sta $410000,x
    inx
    lda $82
    sta $410000,x
    inx
    lda $81
    sta $410000,x
    inx
    lda $80
    sta $410000,x
    rep #$20
svl_done:
    rts
store_vid_byte:
    lda $54
    sta $6A
    lda $52
    jsr map_snes
    lda $C2
    cmp #$0001
    bne svb_done
    ldx $6A
    sep #$20
    lda $80
    sta $410000,x
    rep #$20
svb_done:
    rts

; op_move_g — general MOVE/MOVEA <ea>,<ea> via the EA engine. Fallback from kbad for any
; $1xxx/$2xxx/$3xxx not matched by a specific handler (the game past attract hits move EA
; combos the attract-only validation never exercised, e.g. $2B6E move.l (d16,Ay),(d16,Ax)).
; Skips flags, matching the existing move handlers. dest mode/reg are SWAPPED in the move
; encoding (reg=bits11-9, mode=bits8-6); source=bits5-0.
.org $FA00
op_move_g:
    rep #$30
    lda $44              ; size: bits 13-12  01=B,10=L,11=W -> $5E (0=B,1=W,2=L)
    and #$3000
    cmp #$1000
    bne mvg_nb
    stz $5E
    bra mvg_sz
mvg_nb:
    cmp #$2000
    bne mvg_w
    lda #$0002
    sta $5E
    bra mvg_sz
mvg_w:
    lda #$0001
    sta $5E
mvg_sz:
    lda #$0002
    sta $46              ; PC delta (ea_resolve advances it as ext words are consumed)
    lda $44              ; --- source EA = op bits 5-0 ---
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; $80/$82 = source value
    lda $44              ; flags: MOVE sets N/Z, V=C=0; MOVEA (dest mode 1) sets none.
    and #$01C0           ; (the existing specific move handlers skip flags -- a latent bug
    cmp #$0040           ; the attract path never exposed; needed once the game branches on
    beq mvg_noflag       ; a move result.)
    jsr set_nz
    stz $72              ; V = 0
    stz $6E              ; C = 0
mvg_noflag:
    lda $44              ; --- dest EA = (mode bits 8-6) | (reg bits 11-9) ---
    and #$01C0
    lsr a
    lsr a
    lsr a                ; mode -> $9C bits 5-3
    sta $84
    lda $44
    and #$0E00
    xba
    lsr a                ; reg bits 11-9 -> bits 2-0
    and #$0007
    ora $84
    sta $9C
    jsr ea_resolve
    jsr ea_write         ; dst <- $80/$82
    lda $40              ; PC += $46
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; op_clr_g — general CLR.size <ea> = 0 (Z=1,N=V=C=0) via the EA engine. Fallback from kbad
; for $42xx CLR variants with EA modes the specific handlers miss (e.g. $42B4 mode 6).
op_clr_g:
    rep #$30
    lda $44              ; size bits 7-6: 00=B,01=W,10=L -> $5E
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    stz $80              ; value = 0
    stz $82
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_write
    lda #$0001
    sta $60              ; Z = 1
    stz $70              ; N = 0
    stz $72              ; V = 0
    stz $6E              ; C = 0
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; op_pea_g — general PEA <ea>: push the 32-bit effective address ($52top16:$54low16 from
; ea_resolve) onto the 68K stack (A7). Fallback for PEA EA modes the specific op_pea/
; op_pea_d16 miss (e.g. $4850 = PEA (A0), mode 2).
op_pea_g:
    rep #$30
    lda #$0002
    sta $46
    lda #$0002
    sta $5E
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve       ; $52:$54 = EA address (control modes -> kind 0 memory)
    lda $3C
    sec
    sbc #4
    sta $3C              ; A7 -= 4
    tax
    sep #$20
    lda $53              ; bits 31-24
    sta $400000,x
    inx
    lda $52              ; bits 23-16
    sta $400000,x
    inx
    lda $55              ; bits 15-8
    sta $400000,x
    inx
    lda $54              ; bits 7-0
    sta $400000,x
    rep #$30
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; op_cmpib_g — general CMPI.B #imm,<ea>: mem.b - imm.b, set N/Z/C (V=0) via the EA engine.
; Covers CMPI.B modes the specific handlers miss (e.g. $0C29 = (d16,An)); also handles Dn.
; abs.L ($0C39) stays on op_cmpib_abs (caught earlier). imm word @PC+2 (low byte used),
; EA ext words @PC+4.
op_cmpib_g:
    rep #$30
    stz $5E              ; byte size
    jsr rdw2
    and #$00FF
    sta $50              ; imm byte
    lda #$0004
    sta $46              ; PC delta: opcode(2)+imm(2); EA ext starts at +4
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; $80 low byte = mem byte
    sep #$20
    lda $80
    sec
    sbc $50              ; mem - imm (byte); 65816 C = !borrow
    sta $51              ; result byte
    rep #$20
    bcs cbg_noc
    lda #$0001
    sta $6E              ; C (68k borrow) = 1
    bra cbg_z
cbg_noc:
    stz $6E
cbg_z:
    lda $51
    and #$00FF
    bne cbg_nz
    lda #$0001
    sta $60              ; Z = 1
    bra cbg_n
cbg_nz:
    stz $60
cbg_n:
    lda $51
    and #$0080
    beq cbg_npos
    lda #$0001
    sta $70              ; N = 1
    bra cbg_v
cbg_npos:
    stz $70
cbg_v:
    stz $72              ; V = 0
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; op_addi_g — general ADDI.B/W/L #imm,<ea>: mem += imm, full N/Z/V/C (+X=C) via addflags
; and the EA engine. Routed for ADDI memory modes (>=2) the specific Dn/byte handlers miss
; (e.g. $066D = ADDI.W #imm,(d16,A5)). imm word(s) @PC+2; EA ext after (offset 4 B/W, 6 L).
op_addi_g:
    rep #$30
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E              ; size 0=B,1=W,2=L
    cmp #$0002
    beq addg_long
    jsr rdw2
    sta $74              ; imm low16 (B/W)
    stz $76
    lda #$0004
    sta $46
    bra addg_ea
addg_long:
    jsr rdw2
    sta $76              ; imm high16
    jsr rdw4
    sta $74              ; imm low16
    lda #$0006
    sta $46
addg_ea:
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; $80/$82 = mem (dest)
    jsr addflags         ; $80/$82 = mem + imm($74/$76); N/Z/V/C
    lda $6E
    sta $A2              ; X = C
    jsr ea_write         ; store result
    rep #$30
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; op_tst_g — general TST.B/W/L <ea>: Z=(ea==0), N=msb, V=C=0 via the EA engine. Covers all
; TST modes incl Dn, so it supersedes the specific tst handlers (e.g. $4A9F TST.L (A7)+).
op_tst_g:
    rep #$30
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E              ; size 0=B,1=W,2=L
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; $80/$82 = operand
    jsr set_nz           ; N/Z size-aware
    stz $72              ; V = 0
    stz $6E              ; C = 0
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; op_addsubq_g — ADDQ.B/SUBQ.B #data,(d16,An): [An+d16].b +/- data ; Z ; PC+=4. Direct
; work-RAM access (mirrors the proven op_addq_w_d16). Routed for $522D = ADDQ.B (d16,A5)
; (the coin/credit counter increment), the byte (d16,An) gap the word handler misses.
; PLACED AT $FD00 (after cpu5a22_boot at $FC00): the $FA00 handler block fills to ~$FBE0,
; so adding here would overflow $FC00 and be overwritten by cpu5a22_boot -> executing it
; would run into `jml CPU5A22_VIDEO` and wedge the SA-1 into the 5A22 supervisor.
.org $FD00
op_addsubq_g:
    rep #$30
    jsr addq_data        ; $50 = data (1-8)
    jsr rdw2
    sta $52              ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot
    lda $00,x
    clc
    adc $52
    sta $52              ; addr = An.lo + d16
    tax
    lda $44
    and #$0100            ; bit 8: 0 = ADDQ, 1 = SUBQ
    bne aqg_sub
    sep #$20
    lda $400000,x
    clc
    adc $50
    sta $400000,x
    rep #$30
    bra aqg_z
aqg_sub:
    sep #$20
    lda $400000,x
    sec
    sbc $50
    sta $400000,x
    rep #$30
aqg_z:
    sep #$20
    lda $400000,x
    rep #$30
    and #$00FF
    jsr setz_from_a
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

; kbad_aq2 — reached by kbad_halt's `jmp kbad_aq2` (a same-size swap of `lda #$DEAD`, so the
; dispatch never shifts -> no Poppy branch-wrap). Routes ADDQ.B/SUBQ.B #data,(d16,An)
; ($5028/$5128) to op_addsubq_g; anything else is a genuine unknown opcode -> stop ($DEAD).
kbad_aq2:
    lda $44
    and #$F0F8
    cmp #$5028
    bne kaq2_or
    jmp op_addsubq_g
kaq2_or:
    lda $44              ; OR.B Dn,(d16,An) = $8128 (dir1, byte, mode 5) -> op_orb_d16
    and #$F1F8
    cmp #$8128
    bne kaq2_halt
    jmp op_orb_d16
kaq2_halt:
    lda #$DEAD
    sta $4E
    jmp idone

; op_orb_d16 — OR.B Dn,(d16,An): [An+d16].b |= Dn.b ; N/Z, V=C=0 ; PC+=4. Direct work-RAM.
op_orb_d16:
    rep #$30
    stz $5E              ; byte size (for set_nz)
    jsr rdw2
    sta $52              ; d16
    lda $44
    and #$0007
    asl a
    asl a
    clc
    adc #$0020
    tax                  ; An slot
    lda $00,x
    clc
    adc $52
    sta $52              ; addr = An.lo + d16
    jsr regdst           ; X = Dn slot
    sep #$20
    lda $00,x            ; Dn.b
    sta $50
    rep #$30
    ldx $52              ; addr
    sep #$20
    lda $400000,x
    ora $50              ; |= Dn.b
    sta $400000,x        ; write back; A = result byte
    rep #$30
    and #$00FF
    sta $80
    stz $82
    jsr set_nz           ; N/Z (size $5E=0)
    stz $72              ; V=0
    stz $6E              ; C=0
    lda $40
    clc
    adc #4
    sta $40
    jmp inext

; rb_cc_evn — post-boot C-Chip status bytes the attract/game state machine polls each frame
; (MAME ground truth: $900000->$47, $900004->$FF, $900006->$03). Only in the input phase
; ($A8 set); during boot fall through to rb_data (RESP1/signature replay). $54 = C-Chip lo16.
; Reached by rb_cc_dp's `jmp rb_cc_evn` (same-size swap of `jmp rb_data`, so no dispatch shift).
rb_cc_evn:
    lda $A8
    and #$00FF
    beq rce_data
    lda $54
    cmp #$0000
    beq rce_47
    cmp #$0004
    beq rce_ff
    cmp #$0006
    beq rce_03
rce_data:
    jmp rb_data
rce_47:
    lda #$0047
    rts
rce_ff:
    lda #$00FF
    rts
rce_03:
    lda #$0003
    rts

; ---- 5A22 bootstrap (Phase A2) ----
; cpu5a22_boot runs on the 5A22 (its reset vector points here, via the LoROM mirror at
; $00:FC00 = file $7C00). It does NOT run the interpreter -- it brings up the SA-1 to run
; the interpreter (CRV=$8000 = the interp reset, reached by the SA-1 at $00:8000 = file $0
; mirror), enabling the shared BW-RAM/IRAM, then halts (A2: no video; A3 gives the 5A22 a
; video shim instead of stp). Runs 8-bit emulation (5A22 reset default); sep #$20 keeps
; Poppy emitting 8-bit immediates.
.org $FC00
cpu5a22_boot:
    sep #$20
    lda #$FF
    sta $2229            ; SIWP: 5A22 IRAM writes enabled
    lda #$80
    sta $2226            ; SBWE: BW-RAM writes enabled (both CPUs)
    lda #$00
    sta $2228            ; BWPA: no BW-RAM write protect
    lda #$00
    sta $2203            ; CRV low  ($8000)
    lda #$80
    sta $2204            ; CRV high ($8000 = the interp reset entry)
    lda #$20
    sta $2200            ; assert SA-1 reset (explicit edge)
    stz $2200            ; release -> SA-1 runs the interpreter from $00:8000
    clc
    xce                  ; 5A22 -> native mode for the 16-bit video code
    rep #$30
    jml CPU5A22_VIDEO    ; A3: 5A22 becomes the video supervisor (reads $41 shadow, drives
                         ; the PPU on each SA-1 frame signal). Never returns.

; op_jmp_idx / op_jsr_idx — indexed/PC-relative control transfers the specific handlers
; miss: JMP/JSR (d8,An,Xn) $4EF0-7/$4EB0-7, (d16,PC) $4EFA, (d8,PC,Xn) $4EFB/$4EBB.
; In the $FC00 free block, reached via the kbad catch-all (no mid-file dispatch insertion
; -> no branch wrap). ea_resolve with $46=2 reads the extension word after the 2-byte opcode.
op_jmp_idx:
    rep #$30
    lda $44
    and #$003F
    sta $9C
    lda #$0002
    sta $46
    stz $5E
    jsr ea_resolve
    lda $54
    sta $40
    lda $52
    and #$00FF
    sta $42
    jmp inext
op_jsr_idx:
    rep #$30
    lda $44
    and #$003F
    sta $9C
    lda #$0002
    sta $46
    stz $5E
    jsr ea_resolve
    lda $52
    sta $58              ; save target hi16
    lda $54
    sta $50              ; save target lo16
    lda $40
    clc
    adc #4
    sta $54              ; return = PC+4 (carry -> $56 in push32r)
    jsr push32r
    lda $50
    sta $40
    lda $58
    and #$00FF
    sta $42
    jmp inext
; kbad_chkidx — free-space tail of the kbad catch-all: route indexed/PC-rel JMP/JSR, else
; fall through to kbad_aq2. Reached only via the same-size jmp swap at kbad_halt.
kbad_chkidx:
    lda $44
    and #$FFC0
    cmp #$4EC0           ; JMP <ea> (any EA mode reaching kbad = no specific handler)
    beq kci_jmp
    cmp #$4E80           ; JSR <ea>
    beq kci_jsr
    lda $44              ; ADDA.W/L <ea>,An ($D0C0) / SUBA.W/L <ea>,An ($90C0): memory-source
    and #$F0C0           ; EA modes the #imm/Dn specific handlers miss
    cmp #$D0C0
    beq kci_adda
    cmp #$90C0
    beq kci_suba
    jmp kbad_aq2         ; not handled here -> original halt chain
kci_jmp:
    jmp op_jmp_idx
kci_jsr:
    jmp op_jsr_idx
kci_adda:
    jmp op_adda_g
kci_suba:
    jmp op_suba_g

; op_adda_g / op_suba_g — ADDA/SUBA.W/L <ea>,An for memory-source EA modes (the specific
; handlers only cover #imm and Dn sources). No flags; word source sign-extended to 32-bit.
adsa_src:                ; common: $80/$82 = sign/zero-extended source; $46 = PC delta
    rep #$30
    lda $44
    and #$003F
    sta $9C
    lda #$0002
    sta $46
    lda $44
    and #$0100            ; bit8: 0=word, 1=long
    bne adsa_l
    lda #$0001
    sta $5E
    bra adsa_rd
adsa_l:
    lda #$0002
    sta $5E
adsa_rd:
    jsr ea_resolve
    jsr ea_read          ; $80/$82 = zero-extended source
    lda $5E
    cmp #$0002
    beq adsa_done        ; long: use as-is
    lda $80              ; word: sign-extend into $82
    bpl adsa_pos
    lda #$FFFF
    sta $82
    rts
adsa_pos:
    stz $82
adsa_done:
    rts
op_adda_g:
    jsr adsa_src
    jsr regdstA          ; X = dst An slot (bits 11-9)
    lda $00,x
    clc
    adc $80
    sta $00,x
    lda $02,x
    adc $82
    sta $02,x
    bra adsa_pc
op_suba_g:
    jsr adsa_src
    jsr regdstA
    lda $00,x
    sec
    sbc $80
    sta $00,x
    lda $02,x
    sbc $82
    sta $02,x
adsa_pc:
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; General ADDQ/SUBQ #data,<ea> via the EA engine (replaces the loose-mask Dn/An fast
; paths that mis-decoded memory modes). data = bits 11-9 (0->8). An dest = full 32-bit,
; no flags; all other dests = sized add/sub with N/Z/V/C and X=C. Modeled on op_addi_g.
.org $FE00
op_addq_g:
    rep #$30
    jsr addq_data        ; $50 = data (1-8)
    lda $50
    sta $74              ; addend = data
    stz $76
    lda #$0002
    sta $46              ; op word; ea_extw adds EA ext words
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E              ; size 0/1/2
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    lda $9E
    cmp #$0002
    beq aqg_an
    jsr ea_read
    jsr addflags         ; $80/$82 += data ; N/Z/V/C
    lda $6E
    sta $A2              ; X = C
    jsr ea_write
    bra aqg_pc
aqg_an:
    lda #$0002
    sta $5E              ; An: full 32-bit, no flags
    jsr ea_read
    rep #$30
    lda $80
    clc
    adc $74
    sta $80
    lda $82
    adc #$0000
    sta $82
    jsr ea_write
aqg_pc:
    rep #$30
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_subq_g:
    rep #$30
    jsr addq_data
    lda $50
    sta $74
    stz $76
    lda #$0002
    sta $46
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    lda $9E
    cmp #$0002
    beq sqg_an
    jsr ea_read
    jsr subflags         ; $80/$82 -= data ; N/Z/V/C
    lda $6E
    sta $A2
    jsr ea_write
    bra sqg_pc
sqg_an:
    lda #$0002
    sta $5E
    jsr ea_read
    rep #$30
    lda $80
    sec
    sbc $74
    sta $80
    lda $82
    sbc #$0000
    sta $82
    jsr ea_write
sqg_pc:
    rep #$30
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

; General immediate ALU via EA engine (SUBI/ANDI/ORI/CMPI), modeled on op_addi_g.
; Prologue (size + imm into $74/$76 + $46) is shared via imm_prologue. SUBI/CMPI use
; subflags; ANDI/ORI use logflags (N/Z, V=C=0, X kept). CMPI does NOT write back or
; touch X. Replaces the trace-driven Dn-only specifics that skipped flags / memory modes.
imm_prologue:            ; -> $5E size, $74/$76 imm, $46 pcdelta, $9C EA ; A/X 16-bit
    rep #$30
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    cmp #$0002
    beq imp_long
    jsr rdw2
    sta $74
    stz $76
    lda #$0004
    sta $46
    bra imp_ea
imp_long:
    jsr rdw2
    sta $76
    jsr rdw4
    sta $74
    lda #$0006
    sta $46
imp_ea:
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    rts
imm_pc:                  ; PC += $46 ; jmp inext
    rep #$30
    lda $40
    clc
    adc $46
    sta $40
    lda $42
    adc #$0000
    sta $42
    jmp inext

op_subi_g:
    jsr imm_prologue
    jsr ea_read
    jsr subflags
    lda $6E
    sta $A2              ; X = C
    jsr ea_write
    jmp imm_pc

op_cmpi_g:
    jsr imm_prologue
    jsr ea_read
    jsr subflags         ; N/Z/V/C only; no write-back, X untouched
    jmp imm_pc

op_andi_g:
    jsr imm_prologue
    jsr ea_read
    lda $80
    and $74
    sta $80
    lda $82
    and $76
    sta $82
    jsr logflags         ; N/Z; V=C=0; X kept
    jsr ea_write
    jmp imm_pc

op_ori_g:
    jsr imm_prologue
    jsr ea_read
    lda $80
    ora $74
    sta $80
    lda $82
    ora $76
    sta $82
    jsr logflags
    jsr ea_write
    jmp imm_pc

; General OR <ea>,Dn (dir0) / Dn,<ea> (dir1) via the EA engine. result = EA | Dn (sized);
; logical flags (N/Z, V=C=0, X kept). dir0 -> Dn, dir1 -> EA (RMW). Dispatch excludes
; DIVU/DIVS (ss=11) and SBCD (dir1 ea-mode<2). Replaces the partial OR.W-only specifics.
op_or_g:
    rep #$30
    lda $44
    and #$00C0
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta $5E
    lda #$0002
    sta $46
    lda $44
    and #$003F
    sta $9C
    jsr ea_resolve
    jsr ea_read          ; $80/$82 = EA operand
    jsr regdst           ; X = Dn slot (bits 11-9 *4)
    lda $00,x
    ora $80
    sta $80
    lda $02,x
    ora $82
    sta $82
    jsr logflags         ; N/Z from result; V=C=0; X kept
    lda $44
    and #$0100
    beq oror_dir0
    jsr ea_write         ; dir1: result -> EA (uses $9E/$94 from ea_resolve)
    jmp imm_pc
oror_dir0:
    jsr regdst
    stx $94
    lda #$0001
    sta $9E              ; kind = Dn direct -> ea_write does the sized Dn writeback
    jsr ea_write
    jmp imm_pc

.org $FFE0
.word $0000,$0000,irq,irq,$0000,nmi,reset,irq
.org $FFF0
.word $0000,$0000,irq,$0000,$0000,nmi,reset,irq
