; ============================================================================
; Superman Sprite Test ROM
; Displays a single frame of Superman sprites captured from MAME
; ============================================================================

.snes
.rom_id "SPRT"

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
TS       = $212D
CGADD    = $2121
CGDATAWR = $2122
OBSEL    = $2103
OAMADDL  = $2104
OAMADDH  = $2105
OAMDATA  = $2106
VMADDL   = $2116
VMADDH   = $2117
VMDATAL  = $2118
VMDATAH  = $2119
NMITIMEN = $4200
RDNMI    = $4210
MEMSEL   = $420D
DMAP0    = $4300
BBAD0    = $4301
A1T0L    = $4302
A1T0H    = $4303
A1B0     = $4304
DAS0L    = $4305
DAS0H    = $4306

; === WRAM Variables ===
OAM_BUFFER  = $0100    ; 544 bytes OAM buffer (512 + 32 high bits)
VRAM_TILES  = $0000    ; VRAM address for sprite tiles (word address)

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
    jsr init_ppu
    jsr load_palette
    jsr load_tiles
    jsr load_oam
    jsr main_loop
    bra hw_reset

; === NMI Handler ===
nmi_handler:
    php
    rep #$30
    sep #$20
    lda RDNMI
    ; Reload OAM each frame
    jsr load_oam
    plp
    rti

; === Other Handlers ===
irq_handler:
    rti
cop_handler:
    rti
brk_handler:
    rti

; === Main Loop ===
main_loop:
    wai
    bra main_loop

; === PPU Init ===
init_ppu:
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

    ; Set mode 1, 8x8 sprites
    lda #$01
    sta BGMODE          ; Mode 1, BG1+BG2+BG3

    ; Sprite tile data at VRAM $0000 (word address)
    lda #$00
    sta OBSEL           ; Sprite tiles at $0000, size 8x8/16x16

    ; Enable sprites on main screen
    lda #$10
    sta TM              ; Enable OBJ on main screen

    ; Enable NMI
    lda #$81
    sta NMITIMEN

    ; Turn on screen (brightness 15)
    lda #$0F
    sta INIDISP

    rep #$30
    rts

; === Load Palette via DMA ===
; CGRAM palette is at data/palettes/sprites/sprites_16x16.cgram
; 256 bytes: 8 palettes × 16 colors × 2 bytes (BGR555)
load_palette:
    sep #$20
    
    ; Set CGRAM address to 0
    lda #$00
    sta CGADD
    
    ; Use DMA to load palette
    ; Channel 0: CPU -> CGRAM
    lda #$00            ; DMA mode: CPU -> PPU, 1 register write once
    sta DMAP0
    lda #$22            ; Destination: CGDATAWR ($2122)
    sta BBAD0
    
    ; Source: cgram_data (defined at end of file)
    lda #<cgram_data
    sta A1T0L
    lda #>cgram_data
    sta A1T0H
    lda #^cgram_data
    sta A1B0
    
    ; Size: 256 bytes
    lda #<256
    sta DAS0L
    lda #>256
    sta DAS0H
    
    ; Trigger DMA
    lda #$01
    sta $420B
    
    rep #$30
    rts

; === Load Tiles via DMA ===
; Sprite tiles at data/palettes/sprites/sprites_16x16.tiles
; 524288 bytes = 16384 tiles × 32 bytes
; Load first 4096 tiles (128KB) to VRAM $0000
load_tiles:
    sep #$20
    
    ; Set VRAM address to 0
    lda #$00
    sta VMADDL
    sta VMADDH
    
    ; Use DMA to load tiles
    ; Channel 0: CPU -> VRAM
    lda #$01            ; DMA mode: CPU -> PPU, 2 registers write
    sta DMAP0
    lda #$18            ; Destination: VMDATAL ($2118)
    sta BBAD0
    
    ; Source: tile_data (defined at end of file)
    lda #<tile_data
    sta A1T0L
    lda #>tile_data
    sta A1T0H
    lda #^tile_data
    sta A1B0
    
    ; Size: 32768 bytes (1024 tiles)
    ; We'll load in chunks of 8192 bytes
    lda #<32768
    sta DAS0L
    lda #>32768
    sta DAS0H
    
    ; Trigger DMA
    lda #$01
    sta $420B
    
    rep #$30
    rts

; === Load OAM ===
; OAM data at tools/mame-trace/snes_oam.bin
; 544 bytes: 512 bytes OAM + 32 bytes high bits
load_oam:
    sep #$20
    
    ; Set OAM address to 0
    lda #$00
    sta OAMADDL
    sta OAMADDH
    
    ; Copy OAM data to WRAM buffer first, then DMA
    ; Actually, we can DMA directly from CPU memory to OAM
    ; Channel 0: CPU -> OAM
    lda #$00            ; DMA mode: CPU -> PPU, 1 register write
    sta DMAP0
    lda #$06            ; Destination: OAMDATA ($2106)
    sta BBAD0
    
    ; Source: oam_data (defined at end of file)
    lda #<oam_data
    sta A1T0L
    lda #>oam_data
    sta A1T0H
    lda #^oam_data
    sta A1B0
    
    ; Size: 544 bytes
    lda #<544
    sta DAS0L
    lda #>544
    sta DAS0H
    
    ; Trigger DMA
    lda #$01
    sta $420B
    
    rep #$30
    rts

; === Data ===
; These are binary data files included via .incbin
; We'll use the build system to concatenate them

; CGRAM palette (256 bytes)
.rodata
cgram_data:
    .incbin "../data/palettes/sprites/sprites_16x16.cgram"

; Sprite tiles (first 1024 tiles = 32768 bytes)
tile_data:
    .incbin "../data/palettes/sprites/sprites_16x16.tiles" 0 32768

; OAM data (544 bytes)
oam_data:
    .incbin "../tools/mame-trace/snes_oam.bin"

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
