; =============================================================================
; video.pasm — the video-render subsystem, relocated to ROM bank $E9 (file $290000)
; to free interp-bank ($8000-$FFFF) space. Assembled flat at .org $0000; run at
; CPU $E9:0000 (jsr/branches are PB-relative; long/PPU accesses are bank-explicit/
; DBR-inherited). Called from the interp bank via the 3 jsl/jml entry wrappers below.
; map_snes (hot store-dispatch) stays in interp.pasm.
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
SHADOW_PAL=$2000
SHADOW_D0=$3000
SHADOW_COD=$4000
STAGING_CGRAM=$8000
VFT_VEC=$E98004          ; fixed wrapper slot: per-tick joy+render vector (jsl'd from WRAM)
.bank 0
.org $8000
; entry wrappers (interp: jsl $E90000 vid_frame, jsl $E90004 vid_init, jml $E90008 vidtest)
    inc $3300            ; $8000 VID_FRAME: the SA-1's interp calls this each game-frame
    rtl                  ;   boundary -> signals FRAME_REQ++ in shared IRAM ($00:3000).
    jml $7F8918          ; $8004 VF_TICK: jml to the $7F WRAM copy of vf_tick (render-to-WRAM,
                         ;   pt.21). The whole per-tick joy+render path now fetches from bank
                         ;   $7F (rc_copy mirrors $E9:8000-$8FFF -> $7F:8000 at supervisor boot),
                         ;   so its code fetch no longer conflicts with the SA-1's Bus-A type
                         ;   (WRAM never matches — the LATCH RULE). jml long = 4B = old jmp+nop
                         ;   (zero-shift; VIDTEST stays $8008). wl_blob still jsl's VFT_VEC
                         ;   ($E98004); this jml lands in $7F and the $7F vf_tick rtl's back.
                         ;   LITERAL $7F8918 (== $7F0000|vf_tick), NOT the symbol expr: a
                         ;   forward-ref inside `vf_tick|$7F0000` mis-sizes in Poppy's first
                         ;   pass and de-syncs every downstream label by -1 (verified: the
                         ;   wrapper then jmp'd $8821, one byte into cpu5a22_video's rts). vf_tick
                         ;   is .org-pinned at $8918 (like VFT_VEC/BOOT_ARM), so the literal is safe.
    jmp vidtest_init     ; $8008 VIDTEST
    jmp cpu5a22_video    ; $800B CPU5A22_VIDEO: 5A22 supervisor (cpu5a22_boot jml's here)

ppu_build:
    php
    rep #$30
    ldx #$0000
pf_cg:
    lda $412000,x        ; shadow palette word (byte-swapped: hi | lo<<8)
    xba                  ; -> W (arcade xRGB555)
    jsr snes_color       ; -> A = SNES xBGR555
    sta $7E8000,x        ; CGRAM staging (LE byte order = CGDATA write order)
    inx
    inx
    cpx #$0200           ; 256 colors * 2 bytes
    bne pf_cg
    plp
    rts

; ppu_dma_flush — DMA prebuilt CGRAM staging -> CGRAM + screen on (cheap, vblank).
ppu_dma_flush:
    php
    sep #$20
    stz CGADD
    stz DMAP0            ; DMA mode 0: A-bus -> single B reg
    lda #$22
    sta BBAD0            ; B dest = $2122 CGDATA
    stz A1T0L
    lda #$80
    sta A1T0H            ; A src lo16 = $8000
    lda #$7E
    sta A1B0             ; A src bank = $7E
    stz DAS0L
    lda #$02
    sta DAS0H            ; length = 512
    lda #$01
    sta MDMAEN
    lda #$0F
    sta INIDISP          ; screen on
    plp
    rts

; snes_color: A = arcade xRGB555 -> A = SNES xBGR555. Clobbers $C6/$C8. 16-bit A.
; The leading rep #$30 is REQUIRED: it tells the assembler M is 16-bit here so the
; `and #$....` immediates assemble as 3-byte (16-bit) operands. Without it Poppy
; inherits the preceding routine's `sep #$20` state and emits 8-bit immediates,
; which the CPU (running 16-bit) misreads -> the whole routine desyncs.
snes_color:
    rep #$30
    sta $C6
    and #$001F           ; arcade B
    xba
    asl a
    asl a                ; B<<10
    sta $C8
    lda $C6
    and #$03E0           ; G in place
    ora $C8
    sta $C8
    lda $C6
    xba                  ; W>>8 -> low byte
    and #$00FF
    lsr a
    lsr a                ; W>>10 = arcade R
    and #$001F
    ora $C8
    rts

; vid_init — production reset: clear $7E shadow+staging, screen setup. (jsr-called
; from reset so it doesn't shift main code.)
vid_init:
    php
    rep #$30
    stz $C0
    lda #$0000           ; (no STZ long,X on 65816 -> use sta with A=0)
    ldx #$2000           ; clear derived buffers/staging $7E:2000-$7E:9FFE (5A22 WRAM)
viclr:
    sta $7E0000,x
    inx
    inx
    cpx #$A000
    bne viclr
    ldx #$2000           ; clear the raw shadow $41:2000-$41:7FFE (BW-RAM; the SA-1 fills it)
viclr41:
    sta $410000,x
    inx
    inx
    cpx #$8000
    bne viclr41
    sep #$20
    stz TM               ; no layers yet (Stage 2 shows backdrop only)
    stz NMITIMEN         ; auto-joypad off; inputs use a manual $4016 serial read
    rep #$30
    jsr bg_hclr          ; clear the persistent cross-frame BG tile cache (one-time)
    plp
    rts

; vid_frame — once per simulated game-frame (called at the $8A reload): rebuild the
; CGRAM image from shadow and DMA it. DMA happens at the game-frame boundary (not
; strictly in vblank): the image is static for ~hundreds of real frames between
; game-frames, so any single mid-frame CGRAM glitch is imperceptible.
vid_frame:
    jsr ppu_build
    ; Only build sprites once the game is alive (core scheduler tasks 0+1 active:
    ; 68K tmask $F00002 bits 0,1 = byte-swapped $0300). Early boot = garbage shadow.
    ; Was an EXACT `cmp #$0300`; past attract the game activates more tasks (e.g.
    ; tmask $03C0) so mask to bits 0,1 -> later states still render.
    lda $400002
    and #$0300
    cmp #$0300
    bne vf_noobj
    sep #$20
    lda #$80
    sta INIDISP          ; forced blank: VRAM/OAM/CGRAM DMA is only legal in blank
    rep #$30             ; (real hardware drops writes during active display)
    jsr vid_bg           ; build + upload BG1 playfield from shadow ($E00800/$E00C00)
    jsr vid_obj          ; build + upload OBJ sprites from shadow ($E0/$D0)
vf_noobj:
    jsr ppu_dma_flush    ; DMAs CGRAM, then INIDISP=$0F (screen back on)
    rts

; decode_tile: $C4 = arcade tile code (14-bit) -> four SNES 4bpp 8x8 tiles at
; $7E:8400 (128 bytes, quad order tl,tr,bl,br = offsets 0,32,64,96).
; The Taito 16x16 planar layout stores each row's plane byte IDENTICALLY to SNES
; 4bpp (bit 7-col = pixel col, plane p in consecutive bytes), so decode is a pure
; byte rearrangement. For pixel-row y (0..15), half h (0=left x0-7,1=right x8-15):
;   src 4 plane bytes = gfx[base + Yb(y) + h*32 .. +3],  base = $C90000 + code*128
;   Yb(y) = y*4 (y<8) else 64+(y-8)*4
;   dst SNES tile = quad (h + (y>=8)*2), row (y&7): plane0/1 at row*2, plane2/3 at 16+row*2.
decode_tile:
    php
    rep #$30
    lda $C4              ; gfx byte base = $C90000 + code*128 (code<<7)
    sta $D0
    stz $D2
    ldy #$0007
dt_shl:
    asl $D0
    rol $D2
    dey
    bne dt_shl
    lda $D2
    clc
    adc #$00C9
    sta $D2              ; $D0/$D1/$D2 = 24-bit gfx pointer
    stz $C6              ; y = 0
dt_y:
    lda $C6              ; Yb -> $CA
    cmp #$0008
    bcc dt_ylt8
    sec
    sbc #$0008
    asl a
    asl a
    clc
    adc #$0040
    bra dt_yb
dt_ylt8:
    asl a
    asl a
dt_yb:
    sta $CA
    lda $C6
    and #$0007
    asl a
    sta $CC              ; outrow*2
    lda $C6              ; quadbaseY (0 for rows 0-7, 64 for rows 8-15)
    cmp #$0008
    bcc dt_q0
    lda #$0040
    bra dt_qs
dt_q0:
    lda #$0000
dt_qs:
    sta $CE
    ; --- h=0 (left quad) ---
    ldy $CA              ; src byte0 = Yb
    lda $CE
    clc
    adc $CC
    sta $D4              ; dst plane0/1 offset
    clc
    adc #$0010
    sta $D6              ; dst plane2/3 offset
    jsr dt_copy4
    ; --- h=1 (right quad) ---
    lda $CA
    clc
    adc #$0020
    tay                  ; src byte0 = Yb+32
    lda $CE
    clc
    adc #$0020
    adc $CC
    sta $D4
    clc
    adc #$0010
    sta $D6
    jsr dt_copy4
    lda $C6
    inc a
    sta $C6
    cmp #$0010
    bne dt_y
    plp
    rts

; dt_copy4: copy 4 source plane bytes gfx[$D0+Y .. +3] into the SNES tile with the
; plane order REVERSED (SNES plane p = Taito source plane 3-p; this is the net of
; decode_16x16's `<<(3-p)` and pack8's `>>p`). Dst: SNES plane0/1 at $D4/$D4+1,
; plane2/3 at $D6/$D6+1. Y = src byte0 (16-bit). Returns in 16-bit mode.
dt_copy4:
    sep #$20
    ldx $D6
    inx                  ; X = $D6+1 (SNES plane3)
    lda [$D0],y          ; src plane0 -> SNES plane3
    sta $7E8400,x
    dex                  ; X = $D6 (SNES plane2)
    iny
    lda [$D0],y          ; src plane1 -> SNES plane2
    sta $7E8400,x
    ldx $D4
    inx                  ; X = $D4+1 (SNES plane1)
    iny
    lda [$D0],y          ; src plane2 -> SNES plane1
    sta $7E8400,x
    dex                  ; X = $D4 (SNES plane0)
    iny
    lda [$D0],y          ; src plane3 -> SNES plane0
    sta $7E8400,x
    rep #$30
    rts

; =============================================================================
; vid_obj — build the SNES OBJ frame from the shadowed arcade sprite state and
; upload it. Ports tools/build_snes_full_scene.py's OBJ path. Shadow sources:
;   code[i]   = word  $7E:4000 + 2i   ($E00000)  : tile(0-13) | flipX(15) | flipY(14)
;   xcolor[i] = word  $7E:4400 + 2i   ($E00400)  : X(0-8 signed) | bank(11-15)
;   y[i]      = byte  $7E:3000 + 2i   ($D00000)  : Y low
; Staging: OAM $7E:8600 (544), OBJ tile VRAM $7E:B000 (16-wide grid), bank->slot
; table $7E:8580 (32). OBJ palettes -> CGRAM staging $7E:8100+ (slot*32). Caps at
; 64 sprites / 8 palette banks (plenty for one frame; the rest are dropped).
; DP loop vars $E0-$F8 (clear of decode_tile/snes_color scratch $C4-$D6).
; =============================================================================
OAMSTG=$8600            ; $7E OAM staging (lo 512 + hi 32)
OBJVRAM=$B000           ; $7E OBJ tile VRAM staging (16-wide grid)
BANKTBL=$8580           ; $7E bank(0-31)->palslot table (32 bytes)
vid_obj:
    php
    rep #$30
    ; --- init OAM staging: all 128 sprites Y=$F0 (off), attrs 0; hi-table 0 ---
    lda #$0000           ; (no STZ long,X -> sta with A=0)
    ldx #$0000
voi_oami:
    sta $7E8600,x        ; X=0, Y=0 (fixed below)
    inx
    inx
    cpx #$0220
    bne voi_oami
    sep #$20
    ldx #$0001
voi_yoff:
    lda #$F0
    sta $7E8600,x        ; sprite (X-1)/4 Y byte = $F0
    rep #$30
    txa
    clc
    adc #$0004
    tax
    sep #$20
    cpx #$0201           ; X = 1,5,..,509 (128 sprites) -> stop at 513
    bne voi_yoff
    ; --- init bank->slot table = $FF ---
    rep #$30
    ldx #$0000
voi_bti:
    sep #$20
    lda #$FF
    sta $7E8580,x
    rep #$30
    inx
    cpx #$0020
    bne voi_bti
    jsr obj_hclr         ; clear OBJ code->slot hash ($A000) + tile-slot count ($DC)
    ; counters
    stz $E0              ; i = 0 (shadow index, steps 0,2,..)
    stz $E2              ; n = 0 (output sprite count)
    stz $E6              ; palslot counter
voi_loop:
    ; code = shadow word $7E:4000+i (byte-swapped back to arcade order via xba)
    ldx $E0
    lda $414000,x
    xba
    sta $F6
    and #$3FFF
    bne vchk1
    jmp voi_next         ; code&$3FFF==0 -> skip
vchk1:
    lda $F6
    cmp #$FFFF
    bne vchk2
    jmp voi_next
vchk2:
    ldx $E0
    lda $414400,x
    xba
    sta $E8              ; xcolor word
    ldx $E0
    inx
    sep #$20
    lda $413000,x        ; arcade low byte = Y
    rep #$30
    and #$00FF
    sta $EC              ; sy
    bne vchk3
    jmp voi_next         ; sy==0 -> skip
vchk3:
    cmp #$00F0
    bcc vchk4
    jmp voi_next         ; sy>=240 -> skip
vchk4:
    lda $E8              ; sx = (xcolor&$FF) - (xcolor&$100)
    and #$00FF
    sta $EA
    lda $E8
    and #$0100
    beq vchk5
    lda $EA
    sec
    sbc #$0100
    sta $EA
vchk5:
    lda $EA
    clc
    adc #$0010
    bpl vchk6
    jmp voi_next         ; sx < -16 -> skip
vchk6:
    lda $E8              ; bank = (xcolor>>11)&$1F
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
    lsr a
    and #$001F
    sta $EE
    jsr obj_palslot      ; -> $F0 palslot (assign+fill if new)
    lda $F6
    and #$3FFF
    sta $C4
    jsr obj_slot         ; dedup: decode+place tile only on first sight; $E4 = tile T
    jsr obj_oam          ; OAM entry n
    lda $E2
    inc a
    sta $E2
    cmp #$0080           ; cap 128 sprites (OAM limit; dedup shares tiles)
    beq voi_done
voi_next:
    lda $E0
    clc
    adc #$0002
    sta $E0
    cmp #$0400           ; 512 sprites * 2
    beq voi_done
    jmp voi_loop
voi_done:
    jsr obj_upload
    plp
    rts

; obj_palslot: in $EE=bank(0-31). out $F0=palslot(0-7). Assigns a new OBJ palette
; slot on first use of a bank (cap 8) and copies that bank's 16 arcade colors,
; converted, into the CGRAM staging OBJ region ($7E:8100 + slot*32 = CGRAM 128+).
obj_palslot:
    sep #$20
    ldx $EE
    lda $7E8580,x        ; existing slot?
    cmp #$FF
    bne ops_have
    ; new bank
    rep #$30
    lda $E6              ; next slot
    cmp #$0008
    bcc ops_assign
    sep #$20
    stz $F0              ; out of slots -> use palette 0
    rep #$30
    rts
ops_assign:
    sep #$20
    lda $E6
    sta $7E8580,x        ; bank -> slot
    sta $F0
    rep #$30
    inc $E6
    jsr obj_pal_fill
    rts
ops_have:
    sta $F0
    rep #$30
    rts

; obj_pal_fill: copy 16 colors of arcade bank $EE -> CGRAM OBJ slot $F0.
;   src word = $7E:2000 + bank*32 + e*2 ; dst staging = $7E:8100 + slot*32 + e*2
obj_pal_fill:
    rep #$30
    lda $EE              ; src offset = $2000 + bank*32
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$2000
    sta $D0              ; src ptr lo16 (bank $7E in $D2)
    lda $F0              ; dst offset = $8100 + slot*32
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$8100
    sta $D4              ; dst ptr lo16 (bank $7E in $D6)
    lda #$0041
    sta $D2              ; src bank = $41 (SA-1 BW-RAM palette shadow; was stale $7E WRAM)
    lda #$007E
    sta $D6              ; dst bank = $7E (CGRAM staging in WRAM)
    ldy #$0000
opf_l:
    lda [$D0],y          ; arcade color word (shadow, byte-swapped)
    xba
    jsr snes_color
    sta [$D4],y
    iny
    iny
    cpy #$0020           ; 16 colors
    bne opf_l
    rts

; obj_place: copy the 4 decoded quads ($7E:8400) into the OBJ VRAM grid for sprite
; n ($E2). 16-wide tile grid: T = 2*(n&7) + 32*(n>>3); quads -> T, T+1, T+16, T+17.
; Sets $E4 = T. Uses copy ptrs $D0-$D2 (src) / $D4-$D6 (dst), free after decode_tile.
obj_place:
    rep #$30
    lda $E2
    and #$0007
    asl a                ; 2*(n&7)
    sta $E4
    lda $E2
    lsr a
    lsr a
    lsr a                ; n>>3
    asl a
    asl a
    asl a
    asl a
    asl a                ; (n>>3)*32
    clc
    adc $E4
    sta $E4              ; T
    asl a
    asl a
    asl a
    asl a
    asl a                ; T*32
    clc
    adc #OBJVRAM         ; dst base = $B000 + T*32
    sta $F2              ; (saved dst base)
    lda #$007E
    sta $D2              ; src bank $7E
    sta $D6              ; dst bank $7E
    ; quad0 -> +0
    lda #$8400
    sta $D0
    lda $F2
    sta $D4
    jsr copy32
    ; quad1 -> +32
    lda #$8420
    sta $D0
    lda $F2
    clc
    adc #$0020
    sta $D4
    jsr copy32
    ; quad2 -> +512
    lda #$8440
    sta $D0
    lda $F2
    clc
    adc #$0200
    sta $D4
    jsr copy32
    ; quad3 -> +544
    lda #$8460
    sta $D0
    lda $F2
    clc
    adc #$0220
    sta $D4
    jsr copy32
    rts

copy32:                  ; copy 32 bytes $7E:($D0) -> $7E:($D4) (16-bit words)
    ldy #$0000
c32l:
    lda [$D0],y
    sta [$D4],y
    iny
    iny
    cpy #$0020
    bne c32l
    rts

; obj_oam: write OAM entry n ($E2) from sx($EA) sy($EC) code($F6) palslot($F0) T($E4).
obj_oam:
    rep #$30
    ; X = $8600 + n*4 (OAM lo entry)
    lda $E2
    asl a
    asl a
    clc
    adc #OAMSTG
    tax
    ; xlow = sx & $FF
    lda $EA
    sep #$20
    sta $7E0000,x        ; byte0 = X low
    rep #$30
    ; py = 256 - ((sy+14) & $FF)   [256 = MAME screen.height(); x1_001 draw_foreground uses
    ; screen_y = max_y - (sy+yoffs).  The old 224 shifted every sprite up 32px (a hack to drag
    ; the bottom HUD into the 224-line frame) -> gameplay sprites floated 32px above the BG
    ; (which sits at bitmap_y via vofs=-8). 256 lands them on the floor; only the bottom HUD's
    ; lowest ~24px clips off -- the unavoidable arcade-240 -> SNES-224 loss.
    lda $EC
    clc
    adc #$000E
    and #$00FF
    sta $F2
    jsr obj_pyfix        ; py = 256-(sy+14), with bottom-HUD wrap (byte-neutral: jsr+3 nop
    nop                  ; replaces the old lda #$0100/sec/sbc $F2 -> no downstream shift)
    nop
    nop
    inx
    sep #$20
    sta $7E0000,x        ; byte1 = Y
    rep #$30
    ; tile low = T & $FF
    lda $E4
    inx
    sep #$20
    sta $7E0000,x        ; byte2 = tile low
    rep #$30
    ; attr = $30 | (palslot<<1) | ((T>>8)&1) | flip
    lda $F0
    asl a
    ora #$0030
    sta $F2
    lda $E4              ; (T>>8)&1
    xba
    and #$0001
    ora $F2
    sta $F2
    lda $F6              ; flip bits from code: bit15 X, bit14 Y
    and #$8000
    beq oo_nfx
    lda $F2
    ora #$0040
    sta $F2
oo_nfx:
    lda $F6
    and #$4000
    beq oo_nfy
    lda $F2
    ora #$0080
    sta $F2
oo_nfy:
    lda $F2
    inx
    sep #$20
    sta $7E0000,x        ; byte3 = attr
    rep #$30
    ; hi-table: byte $8800 + (n>>2), shift (n&3)*2, val (xsign|2)<<shift
    lda $E2
    lsr a
    lsr a                ; n>>2
    clc
    adc #$8800
    tax                  ; hi byte addr offset
    lda $EA              ; sx<0 ? xsign=1
    and #$8000
    beq oo_xpos
    lda #$0001
    bra oo_xs
oo_xpos:
    lda #$0000
oo_xs:
    ora #$0002           ; size = large (16x16)
    sta $F2              ; (xsign|2)
    ; shift = (n&3)*2
    lda $E2
    and #$0003
    asl a
    tay                  ; shift count
    lda $F2
oo_shl:
    cpy #$0000
    beq oo_shd
    asl a
    dey
    bra oo_shl
oo_shd:
    sta $F2              ; shifted bits
    sep #$20
    lda $7E0000,x
    ora $F2
    sta $7E0000,x        ; OR into hi-table byte
    rep #$30
    rts

; obj_upload: DMA OBJ tiles ($7E:B000, 8KB) -> VRAM word $4000, OAM ($7E:8600, 544)
; -> OAM, set OBSEL + enable OBJ in TM.
obj_upload:
    sep #$20
    lda #$80
    sta VMAIN
    stz VMADDL
    lda #$40
    sta VMADDH           ; VRAM word $4000
    lda #$01
    sta DMAP0            ; mode 1 (VMDATAL/H)
    lda #$18
    sta BBAD0
    stz A1T0L
    lda #$B0
    sta A1T0H            ; src $B000
    lda #$7E
    sta A1B0
    stz DAS0L
    lda #$20
    sta DAS0H            ; 8192 bytes
    lda #$01
    sta MDMAEN
    ; OAM
    stz OAMADDL
    stz $2103
    stz DMAP0            ; mode 0
    lda #$04
    sta BBAD0
    stz A1T0L
    lda #$86
    sta A1T0H            ; src $8600
    lda #$7E
    sta A1B0
    lda #$20
    sta DAS0L
    lda #$02
    sta DAS0H            ; 544 bytes
    lda #$01
    sta MDMAEN
    lda #$02
    sta OBSEL            ; OBJ base word $4000, 8/16
    lda #$11
    sta TM               ; BG1 + OBJ
    rep #$30
    rts

; =============================================================================
; vid_bg — build BG1 (the X1-001 type0 playfield) from shadow tilemap codes
; ($E00800 -> $7E:4800) + colors ($E00C00 -> $7E:4C00). 16 cols x 32 offs of 16x16
; cells -> a 64x32 SNES BG1 tilemap. Tile dedup via a direct-mapped 64-slot cache
; (slot = code & $3F; decoded-flag at $7E:8900). BG tiles are contiguous (slot s ->
; SNES tiles s*4..s*4+3), so decode_tile's output copies straight in. BG palettes
; -> CGRAM 0-127. Staging: tiles $7E:D000 (8KB), tilemap $7E:F000 (4KB).
; =============================================================================
BGMAP=$9000             ; $7E BG tilemap staging (4KB)
HTCODE=$A000            ; $7E BG code->slot hash: code words (512), 0 = empty
HTSLOT=$A400            ; $7E BG code->slot hash: slot words (512)
vid_bg:
    php
    rep #$30
    lda #$0000           ; (no STZ long,X -> sta with A=0)
    ldx #$0000           ; clear tilemap staging (4KB) at $9000
vb_mclr:
    sta $7E9000,x
    inx
    inx
    cpx #$1000
    bne vb_mclr
    ldx #$0000           ; BG bank table (32) -> $FF
vb_dclr:
    sep #$20
    lda #$FF
    sta $7E8940,x
    rep #$30
    inx
    cpx #$0020
    bne vb_dclr
    ; Cross-frame BG tile cache (polish item 2): the hash ($7E:A000) and its decoded
    ; VRAM tiles PERSIST across frames, so a code already cached just reuses its slot
    ; (bg_slot's hit path skips decode+DMA -> the per-game-frame render is much cheaper
    ; for a static playfield). Evict by full-clear only when the cache is nearly full
    ; (>=160 of 192 slots), so accumulating codes from scene changes are eventually
    ; flushed. (The tilemap + palettes are still rebuilt every frame; only the
    ; expensive tile decode/DMA is cached.)
    lda $DC
    cmp #$00A0           ; 160
    bcc vb_keep
    jsr bg_hclr          ; cache full -> evict all (clear hash + count)
vb_keep:
    stz $E6              ; BG palslot counter
    stz $F0              ; clear bgpal slot (16-bit): $F1 high byte is uninit DP -> the fill's
                         ; `lda $F0` (16-bit) would read a stale high byte -> garbage dst -> the
                         ; bank->slot palette fill landed off-target (bricks kept ppu_build's bank0)
    stz $E0              ; i*2 = 0
vb_loop:
    ldx $E0
    lda $414800,x        ; tilemap code (byte-swapped)
    xba
    sta $F6
    and #$3FFF
    bne vb_c1
    jmp vb_next          ; empty cell
vb_c1:
    sta $E4              ; c = code & $3FFF
    ldx $E0
    lda $414C00,x        ; color word
    xba
    sta $E8
    jsr bg_slot          ; sequential dedup: $DA = tile slot (decodes if new)
    rep #$30
    ; bank = (color>>11)&$1F ; bgpal = bank->slot
    lda $E8
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
    lsr a
    and #$001F
    sta $EE
    jsr bg_palslot       ; -> $F0 = bgpal
    ; gx = col*2 + (offs&1) ; gy = offs>>1   (i = $E0>>1 ; col=i>>5 ; offs=i&31)
    lda $E0
    lsr a                ; i
    sta $F2
    and #$001F           ; offs
    sta $F4
    lsr a
    sta $EC              ; gy = offs>>1
    lda $F2
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a                ; col = i>>5
    asl a                ; col*2
    sta $F2
    lda $F4
    and #$0001
    clc
    adc $F2
    sta $EA              ; gx = col*2 + (offs&1)   (reuse $EA now=gx)
    ; 4 entries: (dx,dy,tk): (0,0,0)(1,0,1)(0,1,2)(1,1,3)
    ; base tilenum = slot*4 (slot from bg_slot in $DA)
    lda $DA
    asl a
    asl a
    sta $F8              ; base tile = slot*4
    ; tl
    lda $EA
    asl a
    sta $D0              ; tx = gx*2
    lda $EC
    asl a
    sta $D2              ; ty = gy*2
    lda $F8
    jsr bg_ent
    ; tr
    inc $D0
    lda $F8
    inc a
    jsr bg_ent
    ; br
    inc $D2
    lda $F8
    clc
    adc #$0003
    jsr bg_ent
    ; bl
    dec $D0
    lda $F8
    clc
    adc #$0002
    jsr bg_ent
vb_next:
    lda $E0
    clc
    adc #$0002
    sta $E0
    cmp #$0400
    beq vb_done
    jmp vb_loop
vb_done:
    jsr bg_upload
    plp
    rts

; bg_ent: write one BG tilemap entry. tx=$D0, ty=$D2, tilenum=A. ent = (tile&$3FF) |
; (bgpal $F0 <<10) | flipX($4000 if code $F6 bit15) | flipY($8000 if bit14).
; map_index = (tx>=32?$400:0) + (ty&31)*32 + (tx&31); store word at BGMAP+mi*2.
; bg_slot — code->slot dedup for BG via an open-addressing hash table (O(1) avg, vs
; the old O(n^2) linear scan). in $E4=code. out $DA=slot. On a new code (cap 192,
; the BG VRAM budget at char base word $1000) it allocates the next slot, decodes the
; tile, and DMAs it straight to VRAM word $1000+slot*64 (no big staging buffer).
bg_slot:
    rep #$30
    lda $E4
    and #$01FF           ; hash = code & $1FF
    asl a                ; word index *2
    sta $D8
bs_probe:
    ldx $D8
    lda $7EA000,x        ; htab_code[h]
    beq bs_ins           ; 0 = empty
    cmp $E4
    beq bs_hit
    inx
    inx
    txa
    and #$03FF           ; wrap (512 words)
    sta $D8
    bra bs_probe
bs_hit:
    ldx $D8
    lda $7EA400,x        ; htab_slot[h]
    sta $DA
    rts
bs_ins:
    lda $DC
    cmp #$00C0           ; 192-slot cap (VRAM word $1000-$3FFF)
    bcc bs_alloc
    stz $DA              ; overflow -> slot 0
    rts
bs_alloc:
    ldx $D8
    lda $E4
    sta $7EA000,x        ; htab_code[h] = code
    lda $DC
    sta $7EA400,x        ; htab_slot[h] = slot
    sta $DA
    inc $DC              ; count++
    lda $E4
    sta $C4
    jsr decode_tile      ; -> $7E:8400
    jsr bg_tile_dma      ; DMA decoded tile -> VRAM word $1000 + slot*64
    rts

; bg_tile_dma — DMA the 128-byte decoded tile ($7E:8400) to VRAM word $1000+($DA*64).
bg_tile_dma:
    php
    rep #$30
    lda $DA
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                ; slot*64
    clc
    adc #$1000
    sta $D0              ; VRAM word addr
    sep #$20
    lda #$80
    sta VMAIN
    lda $D0
    sta VMADDL
    lda $D1
    sta VMADDH
    lda #$01
    sta DMAP0            ; mode 1 (VMDATAL/H)
    lda #$18
    sta BBAD0
    lda #$00
    sta A1T0L
    lda #$84
    sta A1T0H            ; src $8400
    lda #$7E
    sta A1B0
    lda #$80
    sta DAS0L
    lda #$00
    sta DAS0H            ; 128 bytes
    lda #$01
    sta MDMAEN
    plp
    rts

bg_ent:
    rep #$30             ; ensure 16-bit immediates (Poppy width tracking)
    pha
    and #$03FF
    sta $FA              ; tile bits
    lda $F0              ; bgpal<<10
    asl a
    asl a                ; s<<2
    xba                  ; s<<2<<8 = s<<10 (ALREADY correct; the two asl below were the bug:
    nop                  ; they pushed it to s<<12 so slot1 -> pal4=gray. byte-neutral nop swap.)
    nop
    and #$1C00
    ora $FA
    sta $FA
    lda $F6
    and #$8000
    beq bge_nfx
    lda $FA
    ora #$4000
    sta $FA
bge_nfx:
    lda $F6
    and #$4000
    beq bge_nfy
    lda $FA
    ora #$8000
    sta $FA
bge_nfy:
    ; mi = (tx>=32?$400:0) + (ty&31)*32 + (tx&31)
    lda $D2
    and #$001F
    asl a
    asl a
    asl a
    asl a
    asl a                ; (ty&31)*32
    sta $FC
    lda $D0
    and #$001F
    clc
    adc $FC
    sta $FC              ; + (tx&31)
    lda $D0
    and #$0020
    beq bge_lo
    lda $FC
    clc
    adc #$0400
    sta $FC
bge_lo:
    asl $FC              ; mi*2 (byte offset)
    ldx $FC
    lda $FA
    sta $7E9000,x        ; tilemap entry word (BGMAP staging)
    pla
    rts

copy128:                 ; $7E:8400 -> $7E:($D4) (128 bytes, 16-bit).
    rep #$30             ; NB: the 65816 has no `lda long,Y`, so the source must be
    lda #$8400           ; an indirect-long pointer [$D0],y (not `lda $7E8400,y`).
    sta $D0
    lda #$007E
    sta $D2
    ldy #$0000
c128l:
    lda [$D0],y
    sta [$D4],y
    iny
    iny
    cpy #$0080
    bne c128l
    rts

; bg_palslot: in $EE=bank. out $F0=BG palette slot (0-7). Fills CGRAM 0-127 region
; (BG palettes) of the CGRAM staging on first use of a bank. Table $7E:8940.
bg_palslot:
    sep #$20
    ldx $EE
    lda $7E8940,x
    cmp #$FF
    bne bps_have
    rep #$30
    lda $E6
    cmp #$0008
    bcc bps_assign
    sep #$20
    stz $F0
    rep #$30
    rts
bps_assign:
    sep #$20
    lda $E6
    sta $7E8940,x
    sta $F0
    rep #$30
    inc $E6
    ; fill CGRAM staging BG slot: dst = $8000 + slot*32 ; src = $2000 + bank*32
    rep #$30
    lda $EE
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$2000
    sta $D0
    lda $F0
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$8000
    sta $D4
    lda #$0041
    sta $D2              ; src bank = $41 (SA-1 BW-RAM palette shadow; was stale $7E WRAM)
    lda #$007E
    sta $D6              ; dst bank = $7E (CGRAM staging in WRAM)
    ldy #$0000
bps_fl:
    lda [$D0],y
    xba
    jsr snes_color
    sta [$D4],y
    iny
    iny
    cpy #$0020
    bne bps_fl
    rts
bps_have:
    sta $F0
    rep #$30
    rts

; bg_upload: DMA BG tilemap ($7E:9000, 4KB) -> VRAM word $0000, set BG mode/regs/
; scroll. (BG tiles were already DMA'd per-tile to word $1000+ in bg_slot.)
bg_upload:
    sep #$20
    lda #$01
    sta BGMODE           ; mode 1
    lda #$01
    sta BG1SC            ; BG1 map @ word $0000, 64x32
    lda #$01
    sta BG12NBA          ; BG1 char @ word $1000
    lda #$80
    sta VMAIN
    ; tilemap -> word $0000
    stz VMADDL
    stz VMADDH
    lda #$01
    sta DMAP0
    lda #$18
    sta BBAD0
    stz A1T0L
    lda #$90
    sta A1T0H            ; src $9000 (BGMAP)
    lda #$7E
    sta A1B0
    stz DAS0L
    lda #$10
    sta DAS0H            ; 4096 bytes
    lda #$01
    sta MDMAEN
    ; scroll: H derived from the live scroll shadow (bg_hscroll); V = -8 (validated).
    ; (byte-neutral swap: jsr(3)+7*nop = the 10 bytes the old hofs block used, so no
    ;  downstream code shifts -> avoids the Poppy relative-branch-wrap hazard.)
    jsr bg_hscroll       ; BG1HOFS = ((spritectrl[2].bit0<<8) - scrollx[0]) & $3FF
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    lda #$F8
    sta BG1VOFS
    lda #$03
    sta BG1VOFS          ; vofs = $3F8 = (-8 & $3FF) (validated)
    rep #$30
    rts

; test_or_vid — TESTFLAG ($00:F400): 2 = video render test (render shadow forever,
; no 68K interpreter), else single-step (optest). Lets tools/check_render.py inject
; a MAME-captured frame into $7E shadow and validate vid_bg/vid_obj on real data.
vidtest_init:
    rep #$30
    jsr vid_init
vidtest_wait:
    lda $400000          ; wait for harness go-flag (so shadow is injected first)
    beq vidtest_wait
    jsr ppu_build
    jsr vid_bg
    jsr vid_obj
    jsr ppu_dma_flush
vidtest_halt:
    bra vidtest_halt     ; render ONCE then halt -> stable VRAM/OAM/screen to read


; =============================================================================
; OBJ tile dedup (polish item 1) — appended in the roomy $E9 bank so it shifts
; nothing. Mirrors bg_slot: a code->tile-slot hash ($7E:A000, shared with vid_bg
; which runs first and has already DMA'd its BG tiles) lets multiple sprites share
; one OBJ tile, so up to 128 sprites (OAM limit) need only <=64 distinct tiles.
; =============================================================================
obj_hclr:                ; clear OBJ code->slot hash (512 words) + tile-slot count
    rep #$30
    lda #$0000
    ldx #$0000
ohc_l:
    sta $7EA800,x
    inx
    inx
    cpx #$0400
    bne ohc_l
    stz $DE
    rts

obj_slot:                ; in $C4=code. out $E4=T (grid tile index). decode+place if new.
    rep #$30
    lda $C4
    and #$01FF
    asl a
    sta $D8
oss_p:
    ldx $D8
    lda $7EA800,x
    beq oss_ins
    cmp $C4
    beq oss_hit
    inx
    inx
    txa
    and #$03FF
    sta $D8
    bra oss_p
oss_hit:
    ldx $D8
    lda $7EAC00,x
    sta $D8
    jsr obj_T
    rts
oss_ins:
    lda $DE
    cmp #$0040           ; 64 tile-slot cap (one 256-tile OBJ name table)
    bcc oss_alloc
    stz $D8              ; overflow -> slot 0
    jsr obj_T
    rts
oss_alloc:
    ldx $D8
    lda $C4
    sta $7EA800,x        ; htab_code[h] = code
    lda $DE
    sta $7EAC00,x        ; htab_slot[h] = slot
    sta $D8
    inc $DE
    jsr decode_tile      ; $C4 = code -> $7E:8400
    jsr obj_place_at     ; place 4 quads at grid(slot $D8)
    rts

obj_T:                   ; 16-wide-grid top-left tile index for slot $D8 -> $E4
    rep #$30
    lda $D8
    and #$0007
    asl a
    sta $E4
    lda $D8
    lsr a
    lsr a
    lsr a
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc $E4
    sta $E4
    rts

obj_place_at:            ; copy 4 quads ($7E:8400) to OBJVRAM grid for slot $D8; $E4=T
    rep #$30
    jsr obj_T
    lda $E4
    asl a
    asl a
    asl a
    asl a
    asl a                ; T*32
    clc
    adc #OBJVRAM
    sta $F2
    lda #$007E
    sta $D2
    sta $D6
    lda #$8400
    sta $D0
    lda $F2
    sta $D4
    jsr copy32
    lda #$8420
    sta $D0
    lda $F2
    clc
    adc #$0020
    sta $D4
    jsr copy32
    lda #$8440
    sta $D0
    lda $F2
    clc
    adc #$0200
    sta $D4
    jsr copy32
    lda #$8460
    sta $D0
    lda $F2
    clc
    adc #$0220
    sta $D4
    jsr copy32
    rts

; bg_hclr — clear the persistent BG code->slot hash ($7E:A000, 512 words) + count.
; Called once at reset (vid_init) and as the cross-frame cache's overflow eviction.
bg_hclr:
    rep #$30
    lda #$0000
    ldx #$0000
bhc_l:
    sta $7EA000,x
    inx
    inx
    cpx #$0400
    bne bhc_l
    stz $DC
    rts

; cpu5a22_video — the 5A22's video supervisor (Phase A3). cpu5a22_boot jml's here
; ($E9:800B) after bootstrapping the SA-1, instead of stp. The SA-1 runs the interpreter
; and writes the raw arcade shadow into BW-RAM $41; at each game-frame boundary it bumps
; FRAME_REQ (IRAM $00:3000) via the VID_FRAME wrapper. The poll loop watches that counter
; and, on a new frame, rebuilds CGRAM/OAM/BG from the $41 shadow and DMAs to the PPU.
; CONTENTION FIX (2026-07-04): the poll loop now lives in WRAM ($7E:F000, see wl_setup) —
; the old in-ROM busy-poll conflicted with the SA-1 on every ROM/IRAM/BW-RAM cycle and
; taxed it 411K (light) / 578K (combat) cyc/tick = ~29% of the tick (tools/
; contention_probe.py, tools/contention_combat.py). cv_loop below is now just a
; state-resume-compatible thunk: pre-fix save states resume the 5A22 at old cv_loop
; instruction boundaries (or inside joy5a22, which must therefore stay at its old
; address) — every old boundary lands on a pad that routes to wl_setup.
cpu5a22_video:
    jsr rc_copy          ; pt.21: mirror the render code $E9:8000-$8FFF -> $7F:8000, THEN
                         ;   fall into vid_init (rc_copy tail-calls it). Same-size retarget of
                         ;   the old `jsr vid_init` (zero-shift: cv_loop/joy5a22 unmoved).
    rep #$30
    stz $3302            ; FRAME_ACK = 0 (IRAM; 5A22 IRAM writes enabled via SIWP)
    ; NOTE: stz has no long (24-bit) addressing mode, so "stz $410000" would assemble
    ; as a 16-bit abs store to the DBR bank ($00 here), NOT BW-RAM $41. Use a long sta
    ; so the mailbox AND the harness word are actually zeroed at init -- otherwise $41:0002
    ; keeps uninitialized BW-RAM garbage that joy5a22 ORs into every input read.
    lda #$0000
    sta $410000          ; input mailbox = idle (SA-1 joy_read reads this; 5A22 fills it)
    sta $410002          ; virtual-controller injection word (harness pokes; OR'd in)
cv_loop:
    bra cv_go            ; 2B (old `rep #$30` slot: keeps $8837 an instruction boundary)
    nop                  ; $8837-$8839: old `jsr joy5a22` slot -> slide to cv_go
    nop
    nop
cv_go:
    jmp wl_setup         ; $883A: ALSO the old joy5a22 rts-return PC (resume-safe)
    jmp wl_setup         ; $883D: old `cmp $3302` boundary
    bra cv_go            ; $8840: old `beq` boundary
    jmp wl_setup         ; $8842: old `sta $3302` boundary
    jmp wl_setup         ; $8845: old `jsr vid_frame` boundary
    bra cv_go            ; $8848: old `bra cv_loop` boundary (21B total: joy5a22 UNMOVED)

; joy5a22 — 5A22-side manual JOY1 read into the BW-RAM input mailbox $41:0000. The interp
; runs on the SA-1, which cannot touch $4016 (CPU-bus I/O) or $00:0200 (WRAM); so the 5A22
; reads the pad here and the SA-1's joy_read just loads $41:0000. active-high (1=pressed),
; first serial bit -> bit15 (matches the old in-interp joy_read so input_p1/_coins are
; unchanged). Auto-joypad is off (NMITIMEN=0), so strobe + clock 16 bits manually.
; Reads a REAL pad: strobe $4016 + clock 16 bits manually (auto-joypad off), first serial
; bit -> bit15, active-high (1=pressed). The result is OR'd with the harness virtual-
; controller word ($41:0002) so BOTH a real controller AND headless injection work: on
; hardware/an MCP that drives $4016 (e.g. Nexen's SetInputOverrides) the pad is the source
; and an unpressed pad reads $0000 (clean idle); the harness can still poke $41:0002.
; (SNES Select -> arcade Coin1, Start -> arcade Start; see joy_read mapping.)
joy5a22:
    php
    phb                  ; save DBR (the supervisor runs in bank $E9; $4016 needs DBR=$00)
    sep #$20
    lda #$00
    pha
    plb                  ; DBR = $00 -> $4016 resolves to the CPU-bus controller port
    rep #$30
    stz $66              ; 16-bit accumulator (DP, always bank $00, transient)
    sep #$20
    lda #$01
    sta $4016            ; latch controllers
    stz $4016            ; begin serial shift
    ldx #$0010
j5_l:
    lda $4016            ; D0 = current button bit (1 = pressed)
    lsr a                ; -> carry
    rep #$30
    rol $66              ; shift into 16-bit result (first serial bit -> bit15)
    sep #$20
    dex
    bne j5_l
    rep #$30
    lda $410002          ; OR in the pokeable harness virtual-controller word (long, DBR-free)
    ora $66
    sta $410000          ; write the JOY1 mailbox the SA-1's joy_read consumes (long)
    plb                  ; restore DBR
    plp
    rts

; bg_hscroll — set BG1HOFS from the live arcade scroll shadow instead of a fixed value.
; The X1-001 "type0" playfield is a continuous H-scroll: tilemap column c sits at true
; pixel T[c] = (T[0] + c*32) mod 512, and vid_bg already lays columns out sequentially
; (col c at BG pixel c*32), so a single BG1HOFS = -T[0] reproduces the arcade exactly.
;   T[0]  = (scrollx[0] - (upper.bit0 ? 256 : 0)) & $1FF   (per x1_001.cpp draw_background)
;   hofs  = (-T[0]) & $3FF  ==  ((upper.bit0<<8) - scrollx[0]) & $3FF
; scrollx[0] = low byte of word @ $D00408 (shadow $41:3408 -> low byte $41:3409);
; upper.bit0 = bit0 of spritectrl[2] @ $D00604 (shadow $41:3604 -> low byte $41:3605).
; (xoffs=0, and the scrolly/yoffs path nets the existing vofs=-8, so V is left hardcoded.)
; obj_pyfix — compute the SNES OAM Y from $F2 (=(sy+14)&$FF), then keep the bottom HUD on
; screen. Faithful gameplay Y = 256 - (sy+14) (matches x1_001 draw_foreground, screen.height
; =256), so gameplay sprites sit on the BG (which is at bitmap_y via vofs=-8). The arcade
; bottom-strip HUD (energy bar / credit, arcade y>216) lands at py>=224 = off the 224-line
; SNES bottom; wrap it up 24px so it shows at the very bottom edge (~y208) while gameplay
; stays grounded. Gameplay never sits below the floor (py<=~216), so py>=224 is HUD-only.
obj_pyfix:
    rep #$30
    lda #$0100           ; 256 (screen.height)
    sec
    sbc $F2              ; py = 256 - ((sy+14)&$FF)
    cmp #$00E0           ; >= 224 ? -> bottom-strip HUD, off the SNES screen bottom
    bcc oy_done
    sec
    sbc #$0018           ; -24 -> lands ~y208 (visible bottom edge)
oy_done:
    rts

bg_hscroll:
    php
    rep #$30
    sep #$20             ; 8-bit A
    lda $413409          ; scrollx[0] (low byte of the big-endian shadow word)
    rep #$20             ; 16-bit A
    and #$00FF
    sta $D0              ; scratch (free after vb_loop)
    sep #$20
    lda $413605          ; spritectrl[2] low byte
    and #$01             ; upper bit for column 0
    rep #$20
    and #$00FF
    xba                  ; A = bit0<<8  ($0100 or $0000)
    sec
    sbc $D0              ; (upper.bit0<<8) - scrollx[0]
    and #$03FF
    sep #$20
    sta BG1HOFS          ; low byte
    xba
    sta BG1HOFS          ; high byte
    plp
    rts

; ---- BOOT_ARM ($E9:8900): production escape-gate enable (Option A) -----------------
; The interp's notest/production boot calls `jsl BOOT_ARM` here IN PLACE OF the SA-1
; no-op `jsl VID_INIT` (a ZERO bank-$00 code-shift retarget, not an insert — inserting
; bytes in bank $00 shifts the packed gameplay path and breaks it, caught by
; smoke_gameplay). Arms the validated escape dispatch gates so the shipped ROM runs the
; native escapes. DBR=0 in the boot context -> the $07xx stores land in bank-$00 IRAM;
; 16-bit A (boot rep #$30). Test/optest never reach the notest jsl, so they stay ESC=0.
; VID_INIT ($8004) is itself a SA-1 no-op (rtl), so arm-then-rtl is exactly equivalent.
.org $8900
BOOT_ARM:
    rep #$30             ; force 16-bit A/X — the assembler's mode is 8-bit here (prior sep #$20),
                         ; which would mis-size the immediates (lda #$A55A -> lda #$A5 + stray $5A).
                         ; Harmless no-op at runtime (boot is already rep #$30).
    lda #$0001
    sta $071A            ; ESC   on  (jah2 jsr/bsr/jsr(An) + xlat jmp-state + coroutine rte)
    sta $073A            ; CHOKE on  (fetch-chokepoint: ce4/13be render-path rts-reach)
    lda #$A55A
    sta $073C            ; SWIN  on  (scheduler switch-IN escape, magic-match gate)
    lda #$5EEC
    sta $0736            ; SEL   on  (scheduler SELECT escape, magic-match gate)
    rtl                  ; VID_INIT was a SA-1 no-op rtl; return to the boot caller

; ---- WRAM-resident supervisor loop (the 5A22<->SA-1 contention fix, 2026-07-04) -----
; Nexen's SA-1 bus model (Sa1Cpu::ProcessCpuCycle, hardware-shaped): the SA-1 pays wait
; cycles whenever its access's memory TYPE matches the 5A22's current Bus-A type — ROM/
; IRAM conflict +1-2 cyc, BW-RAM 2->4 cyc. The old cv_loop busy-polled FROM ROM at 100%
; duty (ROM code fetch + IRAM $3300/$3302 poll + BW-RAM joy mailbox every iteration), a
; constant tax on every SA-1 cycle: measured 411K cyc/tick light (28.8%) / 578K combat
; (28.7%) — the bulk of the combat "unattributed 1.08M" (docs/PROFILE_CAMPAIGN.md).
; Fix: the 5A22 idles in WRAM — WRAM fetches can never conflict (the SA-1 has no WRAM
; path) — polling IRAM only ~2 accesses per ~700 cyc (throttle loop), and drops into ROM
; once per game tick for joy+render. joy sampling moves from continuous to per-tick,
; which is when the SA-1 consumes it anyway (one-tick-stale input for harness pokes made
; between ticks — acceptable; noted for lockstep tooling).
; NOTE the WAI trap for future NMI-wake work: Nexen latches the 5A22's Bus-A type
; (_memTypeBusA) — a `wai` FETCHED FROM ROM leaves the latch on PrgRom and fake-conflicts
; for the whole sleep. Any idle loop must EXECUTE from WRAM, wai included.
vf_tick:                 ; reached via the fixed $8004 wrapper (jsl VFT_VEC from the blob)
    php
    rep #$30
    jsr joy5a22          ; refresh the JOY1 mailbox ($41:0000) once per game tick
    jsr vid_frame        ; build CGRAM/OAM/BG from the $41 shadow + DMA to PPU
    plp
    rtl

wl_setup:                ; jmp'd from cv_loop (rep #$30, DBR=$00): copy the blob, move in
    phb
    sep #$20
    lda #$E9
    pha
    plb                  ; DBR=$E9 so `lda wl_blob,x` (bank-local abs) reads THIS bank
    ldx #$0000
wl_copy:
    lda wl_blob,x
    sta $7EF000,x        ; long store, DBR-free ($7E:F000-F016; OBJ staging tops at $CFFF)
    inx
    cpx #$0017           ; WL_LEN = 23 bytes — keep in sync with the blob below
    bne wl_copy
    plb                  ; DBR=$00 again (the blob polls IRAM $3300 via abs)
    rep #$30
    jml $7EF000          ; the 5A22 lives in WRAM from here on

wl_blob:                 ; assembled here, RUN at $7E:F000. Position-independent: relative
                         ; branches only (backward, to in-blob labels); abs data is DBR-
                         ; based; the ROM call is a fixed 24-bit vector. rep #$30 + DBR=$00
                         ; on entry and forever.
wl_poll:
    ldx #$0080           ; throttle: ~128 dex/bne of pure-WRAM fetches (~700 cyc) per poll
wl_dly:
    dex
    bne wl_dly
    lda $3300            ; FRAME_REQ (IRAM: the SA-1 bumps it once per game tick)
    cmp $3302            ; FRAME_ACK
    beq wl_poll          ; no new tick -> keep idling in WRAM
    sta $3302            ; ack this tick
    jsl VFT_VEC          ; $E98004 -> vf_tick (now $7F WRAM copy): joy + render, once per tick
    bra wl_poll          ; back to the throttle

; ---- rc_copy — pt.21: mirror the render code into WRAM bank $7F ------------------------
; The 5A22's per-tick render (vf_tick -> joy5a22 + vid_frame -> vid_bg/vid_obj/decode_tile +
; helpers, $E9:8000-$8FFF) fetches from ROM at ~100% duty during combat, taxing the SA-1
; ~578K cyc/tick (Nexen prices +1-2 cyc on every ROM/IRAM Bus-A type-match; render is
; code-fetch-bound). Fix: copy the whole render bank window to WRAM $7F:8000 (SAME 16-bit
; offset) and run it there. The render code is bank-relocatable -- jsr/bra are K-relative,
; and every data access is bank-explicit long ($7E staging / $41,$40 shadow) or DBR-relative
; ($21xx PPU); it contains no jml/jsl/phk/bank-$E9 ref -- so a verbatim same-offset copy runs
; bit-identical with K=$7F, and WRAM fetches never match an SA-1 Bus-A type (the _memTypeBusA
; LATCH rule -> zero contention on the code-fetch share). The $8004 wrapper jml's the $7F copy
; of vf_tick; wl_blob's jsl VFT_VEC still lands at $E9:8004 and the $7F vf_tick rtl's back.
; Runs ONCE at supervisor boot, 5A22-side (the SA-1 has no WRAM write path -> not BOOT_ARM).
; Long-indexed loop (no MVN -> no operand-order/DBR hazard; DBR untouched). Tail-calls vid_init.
rc_copy:
    php
    rep #$30
    ldx #$0000
rc_l:
    lda $E98000,x        ; long,X src: render bank ROM ($E9:8000-$8FFE; +X never crosses bank)
    sta $7F8000,x        ; long,X dst: WRAM mirror ($7F:8000-$8FFE)
    inx
    inx
    cpx #$1000           ; 4KB window (code tops out ~$8944; the tail is harmless padding)
    bne rc_l
    plp
    jsr vid_init         ; exactly the action cpu5a22_video's `jsr` originally performed
    rts
