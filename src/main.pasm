; ============================================================================
; Superman Arcade → SNES Port
; Based on hello-snes (working Poppy template)
; ============================================================================

.snes

; === Hardware Registers ===
INIDISP  = $2100
BGMODE   = $2105
BG1SC    = $2107
BG2SC    = $2108
BG12NBA  = $210B
BG34NBA  = $210C
BG1HOFS  = $210D
BG1VOFS  = $210E
TM       = $212C
CGADD    = $2121
CGDATA   = $2122
NMITIMEN = $4200
RDNMI    = $4210
MEMSEL   = $420D
JOY1L    = $4218

; === WRAM Variables ===
FRAME_COUNT  = $0000
GAME_STATE   = $0002
LEVEL        = $0003
LIVES        = $0004
SCORE        = $0005
PLAYER_X     = $0009
PLAYER_Y     = $000B
INPUT_CUR    = $0020
INPUT_PREV   = $0022
SCROLL_X     = $0040
SCROLL_Y     = $0042

; === Code ===
.bank 0
.org $8000

hw_reset:
    clc
    xce
    sei
    rep #$30
    lda #$1fff
    tcs
    jsr init_snes
    jsr init_game_state
    sep #$20
    lda #$81
    sta NMITIMEN
    rep #$30
    cli

main_loop:
    wai
    bra main_loop

; === NMI Handler ===
nmi_handler:
    php
    rep #$30
    sep #$20
    lda RDNMI
    rep #$30
    inc FRAME_COUNT
    jsr read_input
    jsr game_tick
    jsr update_ppu
    plp
    rti

; === Other Handlers ===
irq_handler:
    rti
cop_handler:
    rti
brk_handler:
    rti

; === Game Tick ===
game_tick:
    php
    rep #$30
    lda GAME_STATE
    cmp #$0000
    beq .title
    cmp #$0001
    beq .play
    bra .done
.title:
    jsr process_title
    bra .done
.play:
    jsr process_player
    jsr process_enemies
    jsr process_physics
    jsr process_collision
    jsr process_scroll
    jsr process_sprites
    jsr process_sound
.done:
    plp
    rts

; === SNES Init ===
init_snes:
    sep #$20
    lda #$00
    sta NMITIMEN
    lda #$80
    sta INIDISP         ; Force blank

    ; Clear PPU registers
    ldx #$2100
clear_ppu_loop:
    stz $00,x
    inx
    cpx #$2134
    bne clear_ppu_loop

    ; Set mode
    lda #$01
    sta BGMODE          ; Mode 1
    lda #$04
    sta BG1SC           ; BG1 tilemap at $0400
    lda #$08
    sta BG2SC           ; BG2 tilemap at $0800
    lda #$00
    sta BG12NBA         ; BG1+BG2 tiles at $0000
    lda #$04
    sta BG34NBA         ; BG3+BG4 tiles at $4000
    lda #$03
    sta TM              ; Enable BG1+BG2
    lda #$01
    sta MEMSEL          ; FastROM

    ; Set palette color 0 = white
    lda #$00
    sta CGADD
    lda #$FF
    sta CGDATA
    lda #$7F
    sta CGDATA

    ; Turn on screen
    lda #$0F
    sta INIDISP

    rep #$30
    rts

; === Input ===
init_game_state:
    stz FRAME_COUNT
    lda #$0001
    sta GAME_STATE
    stz LEVEL
    lda #$0003
    sta LIVES
    stz SCORE
    stz SCORE+2
    stz PLAYER_X
    stz PLAYER_Y
    stz SCROLL_X
    stz SCROLL_Y
    rts

read_input:
    php
    rep #$30
    lda INPUT_CUR
    sta INPUT_PREV
    sep #$20
    lda JOY1L
    rep #$30
    and #$00FF
    sta INPUT_CUR
    plp
    rts

; === PPU Update ===
update_ppu:
    php
    sep #$20
    lda SCROLL_X
    sta BG1HOFS
    lda SCROLL_Y
    sta BG1VOFS
    rep #$30
    plp
    rts

; === Game Processors ===
process_title:
    php
    rep #$30
    lda INPUT_CUR
    and #$80
    beq .no_start
    lda #$0001
    sta GAME_STATE
.no_start:
    plp
    rts

process_player: rts
process_enemies: rts
process_physics: rts
process_collision: rts
process_scroll: rts
process_sprites: rts
process_sound: rts

; === Interrupt Vectors ===
; Native mode vectors at $FFE0
.org $FFE0
.word $0000                    ; $FFE0: Reserved
.word $0000                    ; $FFE2: Reserved
.word cop_handler              ; $FFE4: COP
.word brk_handler              ; $FFE6: BRK
.word $0000                    ; $FFE8: ABORT
.word nmi_handler              ; $FFEA: NMI
.word hw_reset                 ; $FFEC: RESET (unused in native)
.word irq_handler              ; $FFEE: IRQ

; Emulation mode vectors at $FFF0
.org $FFF0
.word $0000                    ; $FFF0: Reserved
.word $0000                    ; $FFF2: Reserved
.word cop_handler              ; $FFF4: COP (cop_handler)
.word $0000                    ; $FFF6: BRK (unused in emu)
.word $0000                    ; $FFF8: ABORT
.word nmi_handler              ; $FFFA: NMI
.word hw_reset                 ; $FFFC: RESET
.word irq_handler              ; $FFFE: IRQ (irq_handler)
