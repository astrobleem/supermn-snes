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
OAMADDH=$2103
OAMDATA=$2104
BGMODE=$2105
BG1SC=$2107
BG2SC=$2108
BG12NBA=$210B
BG1HOFS=$210D
BG1VOFS=$210E
BG2HOFS=$210F
BG2VOFS=$2110
VMAIN=$2115
VMADDL=$2116
VMADDH=$2117
VMDATAL=$2118
VMDATAH=$2119
M7SEL=$211A
M7A=$211B
M7B=$211C
M7C=$211D
M7D=$211E
M7X=$211F
M7Y=$2120
CGADD=$2121
CGDATA=$2122
SLHV=$2137
OPVCT=$213D
TM=$212C
TS=$212D
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
SNAPSHOT_GEN=$0124       ; even = stable, odd = SA-1 is publishing boundary metadata/BG
SNAPSHOT_OBJ_SEL=$0126   ; completed OBJ buffer: 0=$5000, 1=$5C00
SNAPSHOT_OBJ_READY=$0128 ; hle_158e completion token: 1=buffer A, 2=buffer B
PACED_OBJ_SOURCE=$012E   ; source A5 low word for synchronous full-plane capture
PACED_OBJ_Y=$B000        ; private WRAM capture, exact $158E Y interior (1020 bytes)
PACED_OBJ_CODE=$B400     ; private WRAM capture, exact $158E code interior
PACED_OBJ_X=$B800        ; private WRAM capture, exact $158E X/palette interior
MANIFEST_SEQ=$0132       ; SA-1 candidate sequence; zero means no manifest yet
MANIFEST_ACK=$0134       ; 5A22 accepted candidate sequence
MANIFEST_BASE=$0136      ; SA-1 last-promoted accepted sequence
MANIFEST_OBJ_LEN=$0138   ; bit15=packed Y/code/X records; low15=byte length
MANIFEST_BG_LEN=$013A    ; byte length of $41:1A00 BG-offset list; $FFFF = full
MANIFEST_PAL_DIRTY=$013C ; exact palette comparison result for this candidate
MANIFEST_PREP_LEN=$0146  ; byte length of producer-prepared unique BG code list
MANIFEST_C0BC_PREP=$014A ; $C0BC only while live BG matches its prepared ROM image
MANIFEST_BG_LIST=$1A00   ; up to 512 unique 16-bit BG cell byte offsets
MANIFEST_OBJ_LIST=$1600  ; legacy offsets or up to 128 packed 6-byte visible records
MANIFEST_OBJ_CACHE=$BC00 ; private WRAM copy; kept clear of the $8C00 BG list
OBJ_PAL_SLOT_BANK=$2C00  ; previous frame's OBJ slot(0-7)->arcade palette bank
OBJ_PAL_CACHE_MARK=$89C0 ; validates OBJ_PAL_SLOT_BANK after reset/checkpoint loads
OBJ_FREE_LIST=$7B00      ; persistent reclaimed OBJ physical slots (128 bytes)
BG_FREE_LIST=$7C00       ; persistent reclaimed BG slots; never alias OBJ's $2D00 queue
BG_USED_BITMAP=$2E00     ; transient live-tilemap slot bitmap (192 bytes)
BG_OFFSET_TABLE=$7500    ; 512 words: arcade cell byte offset -> SNES TL map byte offset
BG_FREE_COUNT=$89C2      ; number of entries currently available in BG_FREE_LIST
BG_REVERSE_CODE=$D000    ; 192 words: physical BG slot -> active cached code (0 = free)
BG_REVERSE_MARK=$89D0    ; $B7C4 after bg_hclr initialized BG_REVERSE_CODE
RENDER_QUEUE_STATE=$89D2 ; 0 empty, 1 complete, 2 NMI/foreground owns queue storage
RENDER_QUEUE_DROPS=$89D4 ; deadline reached both still-full queue entries
RENDER_QUEUE_META=$D180  ; private queue begins immediately after BG_REVERSE_CODE
RQ_SEQ=$D180
RQ_OBJ_LEN=$D182
RQ_BG_LEN=$D184
RQ_PAL_DIRTY=$D186
RQ_PREP_LEN=$D188
RQ_FRAME_REQ=$D18A
RQ_CTRL_3408=$D18C      ; packed: low byte=BG1 VOFS, high byte=raw scrollx[0] low
RQ_CTRL_3604=$D18E
RQ_PALETTE=$D1A0        ; $0400 bytes
RQ_OBJ=$D5A0            ; packed manifest, at most $0300 bytes
RQ_BG_PAYLOAD=$D8A0     ; full raw $0800 bytes or prepared map $1000 bytes
RQ_BG_LIST=$E0A0        ; incremental offset list, at most $0400 bytes
RQ_BG_VALUES=$E4A0      ; packed code/color pairs, at most $0800 bytes; ends $ECA0
RQ_PREP_CODES=$E8A0     ; prepared unique-code list, at most $0180 bytes
RQ_PREP_PALMAP=$EA20    ; prepared 32-byte palette map; mutually exclusive, ends $EA40
RENDER_QUEUE2_STATE=$89D6
RENDER_QUEUE_CODE_MARK=$89D8 ; $C0DE only after the lazy private-$7E code install completes
RENDER_QUEUE_CODE_BYTES=$022A ; build guard proves this matches the final promoter span
OBJ_HASH_CODE=$5000    ; 1024 authoritative code words in retired snapshot WRAM
OBJ_HASH_SLOT=$5800    ; parallel physical-slot words; complete table ends at $6000
RQ2_SEQ=$B000           ; secondary compact-only slot occupies production-unused
RQ2_OBJ_LEN=$B002       ; $7E:B000-$BBFF (legacy $CA02 capture is rejected)
RQ2_BG_LEN=$B004
RQ2_PAL_DIRTY=$B006
RQ2_PREP_LEN=$B008
RQ2_FRAME_REQ=$B00A
RQ2_CTRL_3408=$B00C     ; same packed vertical/horizontal scroll word as primary
RQ2_CTRL_3604=$B00E
RQ2_PALETTE=$B020       ; $0400 bytes
RQ2_OBJ=$B420           ; $0300 bytes
RQ2_BG_LIST=$B720       ; incremental list below $0100 bytes
RQ2_BG_VALUES=$B820     ; corresponding pairs below $0200 bytes; ends before $BC00
; $7E:5000-$74FF formerly held an abandoned double-buffer snapshot design.
; No runtime instruction references those retired constants.  The widened OBJ
; hash above owns only $5000-$5FFF; $6000-$74FF remains deliberately unclaimed.
STAGING_CGRAM=$8000
TITLE_TEXT_META=$89BE ; palette dirty bit 15 = overloaded title composition uses BG2
TITLE_FONT_MARK=$89DC ; $A55B after coherent BG2 font/map VRAM has been initialized
TITLE_BG_MAP=$6000    ; private 2 KiB WRAM staging for the 32x32 BG2 map
TITLE_FONT=$6800      ; private 1344-byte staging: blank tile + 41 title glyphs
VFT_VEC=$E98004          ; fixed wrapper slot: per-tick joy+render vector (jsl'd from WRAM)
.bank 0
.org $8000
; entry wrappers (interp: jsl $E90000 vid_frame, jsl $E90004 vid_init, jml $E90008 vidtest)
    jmp snd_vframe       ; $8000 VID_FRAME (SA-1, each game-frame): snd_vframe does the original
    nop                  ;   FRAME_REQ++ AND copies the 68K sound-cmd ring $40:1c20 -> IRAM $3304
                         ;   (P2: the SA-1 reads its OWN $40 coherently; the 5A22 can't). jmp(3)+
                         ;   nop(1) keeps the 4-byte slot so VF_TICK stays pinned at $8004.
    jml $7F8918          ; $8004 VF_TICK: jml to the $7F WRAM copy of vf_tick (render-to-WRAM,
                         ;   pt.21). The whole per-tick joy+render path now fetches from bank
                         ;   $7F (rc_copy mirrors $E9:8000-$AFFF -> $7F:8000 at supervisor boot),
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
    lda $7E2800,x        ; coherent cached palette word (byte-swapped: hi | lo<<8)
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
    jsr dma0_blank_pulse ; blank only for the CGRAM DMA itself; CPU-side build stays visible
    nop
    nop
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
    jsr bg_offset_table_init ; immutable 16x32-cell -> two-nametable address map
    sta $410124          ; snapshot generation = 0 until snd_vframe publishes the first image
    sta $410126          ; completed OBJ buffer selector
    sta $410128          ; no hle_158e OBJ snapshot has completed yet
    sta $410132          ; no production renderer manifest candidate
    sta $410134          ; no candidate accepted by the 5A22
    sta $410136          ; no accepted palette/BG baseline
    sta $410138          ; empty candidate OBJ list
    sta $41013A          ; empty candidate BG list
    sta $41013C          ; candidate palette unchanged until first manifest
    sta $410146          ; no producer-prepared BG unique-code list
    sta $41014A          ; no guarded $C0BC prepared-image provenance
    sta $41014E          ; no cumulative exact producer offsets yet
    sta $410150          ; no title-text BG2 overlay
    sta $410142          ; candidate has no promotable BG image
    lda #$FFFF
    sta $410144          ; no proven final $20E8 tile-strip payload in shadow
    sta $41014C          ; boot's forced first image requires a full BG scan
    lda #$0001
    sta $41013E          ; force the first accepted palette conversion
    sta $410140          ; force the first accepted full BG initialization
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
    jsr ppu_build_cached ; skip the 256-color conversion when raw palette bytes are unchanged
    ; Only build sprites once the game is alive (core scheduler tasks 0+1 active:
    ; 68K tmask $F00002 bits 0,1 = byte-swapped $0300). Early boot = garbage shadow.
    ; Was an EXACT `cmp #$0300`; past attract the game activates more tasks (e.g.
    ; tmask $03C0) so mask to bits 0,1 -> later states still render.
    lda $400002
    and #$0300
    cmp #$0300
    bne vf_noobj
    ; Keep the previous completed frame visible while the 5A22 constructs the next
    ; one.  This path currently takes many real video frames; holding INIDISP=$80
    ; across it made fast SA-1 pacing produce an almost permanently black screen.
    ; Each upload routine now brackets only its actual DMA with forced blank via
    ; dma0_blank_pulse.  Nine NOP bytes preserve every downstream pinned address.
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    jsr vid_bg           ; build + upload BG1 playfield from shadow ($E00800/$E00C00)
    jsr vid_obj_cached   ; retain OAM/OBJ tiles when all three raw sprite planes are unchanged
vf_noobj:
    jsr ppu_dma_flush_acked ; release a lab-held producer, then DMA CGRAM/screen on
    rts

; decode_tile: $C4 = arcade tile code (14-bit) -> four SNES 4bpp 8x8 tiles at
; $7E:8400 (128 bytes, quad order tl,tr,bl,br = offsets 0,32,64,96).
; build_interp_rom.py now performs the immutable Taito-plane -> SNES-plane byte
; permutation once when packing the private graphics input.  Runtime therefore
; copies one native 128-byte record instead of re-decoding 512 pixels on the
; 3.58 MHz 5A22 every time a new BG/OBJ code appears.
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
    sta $D2              ; $D0/$D1/$D2 = 24-bit native-tile pointer
    ldx #$0000
    ldy #$0000
dt_copy_native:
    lda [$D0],y
    sta $7E8400,x
    iny
    iny
    inx
    inx
    cpx #$0080
    bne dt_copy_native
    plp
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
.org $8189               ; retain every established renderer/supervisor address;
                         ; the build-time tile conversion leaves a zero seam here
OAMSTG=$8600            ; $7E OAM staging (lo 512 + hi 32)
OBJVRAM=$B000           ; $7E OBJ tile VRAM staging (16-wide grid)
BANKTBL=$8580           ; $7E bank(0-31)->palslot table (32 bytes)
vid_obj:
    php
    rep #$30
voi_restart:            ; obj_slot's full-cache recovery restarts inside this one php/plp frame
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
    bcc voi_yoff         ; NMI/IRQ preemption can disturb X's low bits; never walk past OAM
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
    jsr obj_cache_prepare ; initialize once, then retain decoded OBJ tiles across game frames
    ; counters
    stz $E0              ; i = 0 (shadow index, steps 0,2,..)
    stz $E2              ; n = 0 (output sprite count)
    stz $E6              ; palslot counter
voi_loop:
    ; code = shadow word $7E:4000+i (byte-swapped back to arcade order via xba)
    ldx $E0
    lda $7E4000,x        ; coherent WRAM snapshot captured by vid_obj_cached
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
    lda $7E4400,x        ; coherent WRAM snapshot captured by vid_obj_cached
    xba
    sta $E8              ; xcolor word
    ldx $E0
    inx
    sep #$20
    lda $7E3000,x        ; coherent WRAM snapshot; arcade low byte = Y
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
    jsr obj_pal_fill_cached
    rts
ops_have:
    sta $F0
    rep #$30
    rts

; obj_pal_fill: copy 16 colors of arcade bank $EE -> CGRAM OBJ slot $F0.
;   src word = coherent cache $7E:2800 + bank*32 + e*2
;   dst staging = $7E:8100 + slot*32 + e*2
obj_pal_fill:
    rep #$30
    lda $EE              ; src offset = $2800 + bank*32
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$2800
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
    lda #$007E
    sta $D2              ; source is the coherent per-tick palette cache
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
    jsr obj_pyfix        ; py = 240-(sy+14)-8: exact centered 384x240 -> 256x224 crop
    nop                  ; replaces the old lda #$0100/sec/sbc $F2 -> no downstream shift
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
    jmp obj_upload_dispatch ; persistent cache uploads OBJ tiles only when its slot count grows
    nop                      ; four-byte replacement for sep/lda keeps the OAM path pinned
.a8
.i16
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
    lda #$40
    sta DAS0H            ; 16384 bytes: both 256-tile OBJ name tables ($4000/$5000 words)
    jsr dma0_blank_pulse ; blank only across this VRAM DMA
    nop
    nop
obj_upload_oam:
    ; OAM (always refreshed: positions/attributes are live even when tile pixels are cached)
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
    jsr dma0_blank_pulse ; blank only across this OAM DMA
    nop
    nop
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
    jmp bg_dispatch      ; cache check lives in the copied $9Bxx extension
    nop                  ; six-byte replacement for php/rep/lda keeps every old label pinned
    nop
    nop
vid_bg_heavy:
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
    ; for a static playfield). Evict by full-clear only when the cache is actually full
    ; (192 of 192 slots), so accumulating codes from scene changes do not trigger a
    ; premature 15-video-frame rebuild while 32 decoded slots are still available.
    ; flushed. (The tilemap + palettes are still rebuilt every frame; only the
    ; expensive tile decode/DMA is cached.)
    lda $DC
    cmp #$00C0           ; 192: match bg_slot/bg_dispatch's real VRAM limit
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
    lda $7E2000,x        ; coherent cached tilemap code (byte-swapped)
    xba
    sta $F6
    and #$3FFF
    bne vb_c1
    jmp vb_next          ; empty cell
vb_c1:
    sta $E4              ; c = code & $3FFF
    ldx $E0
    lda $7E2400,x        ; coherent cached color word
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
    jmp bg_slot_extended ; fixed-size entry; reclamation lives in the mirrored $A800 island

; Keep every established renderer/supervisor address stable.  In particular,
; old checkpoints may resume inside the $882e supervisor/cv/joy compatibility
; pad, and its source comments document those literal instruction boundaries.
.org $859E

; bg_tile_dma — fixed entry retained for old callers.  The private graphics image
; is already SNES-native, so the extension DMAs its 128-byte record straight from
; ROM to VRAM word $1000+($DA*64), skipping the old WRAM scratch copy.
bg_tile_dma:
    jmp bg_tile_dma_direct
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
    jsr dma0_blank_pulse ; blank only across this decoded-tile DMA
    nop
    nop
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
    ; fill CGRAM staging BG slot: dst = $8000 + slot*32 ; src = $2800 + bank*32
    rep #$30
    lda $EE
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$2800
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
    lda #$007E
    sta $D2              ; source is the coherent per-tick palette cache
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
    lda #$61
    sta BG12NBA          ; BG1 chars $1000; preserve title BG2 chars $6000
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
    jsr dma0_blank_pulse ; blank only across this tilemap DMA
    nop
    nop
    ; scroll: H is the live arcade scroll plus the centered-crop X origin.
    ; V follows the arcade center playfield column's scrolly plus its -1
    ; noflip offset and the centered-crop Y origin.
    ; (byte-neutral swap: jsr(3)+7*nop = the 10 bytes the old hofs block used, so no
    ;  downstream code shifts -> avoids the Poppy relative-branch-wrap hazard.)
    jsr bg_scroll        ; BG1 HOFS + guarded VOFS from one coherent snapshot
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
    nop                  ; preserve the two former absolute STZ instructions
    nop
    nop
    nop
    nop
    rep #$30
    rts

; test_or_vid — TESTFLAG ($00:F7E0): 2 = video render test (render shadow forever,
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
; nothing. A private code->tile-slot hash at $7E:5000-$5FFF lets multiple
; sprites share one OBJ tile while keeping BG's $7E:A000 table independent.
; Up to 128 sprites (OAM limit) can address 128 persistent physical slots.
; =============================================================================
obj_hclr:                ; clear OBJ code->slot hash (1024 words) + tile-slot count
    jmp obj_hclr_extended

.org $8756

obj_slot:                ; in $C4=code. out $E4=T (grid tile index). decode+place if new.
    rep #$30
    lda $C4
    asl a
    clc
    adc $C4              ; hash = (code * 3) & $03FF
    and #$03FF
    asl a
    sta $D8
oss_p:
    ldx $D8
    lda $7E5000,x
    beq oss_ins
    cmp $C4
    beq oss_hit
    inx
    inx
    txa
    and #$07FF
    sta $D8
    bra oss_p
oss_hit:
    ldx $D8
    lda $7E5800,x
    sta $D8
    jsr obj_T
    rts
oss_ins:
    lda $DE
    cmp #$0080           ; 128 slots across the two 256-tile OBJ name tables
    bcc oss_alloc
    jsr obj_cache_full   ; record the exact cause, discard returns, and restart coherently
    nop
    nop
oss_alloc:
    ldx $D8
    lda $C4
    sta $7E5000,x        ; htab_code[h] = code
    lda $DE
    sta $7E5800,x        ; htab_slot[h] = slot
    sta $D8
    inc $DE
    jsr obj_tile_queue   ; defer this native 128-byte record until just before OAM publish
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

; bg_hclr — clear the persistent BG code->slot hash ($7E:A000, 512 words) +
; allocator state.  The tail jumps to the extended helper to keep cpu5a22_video
; and every resume-compatible cv/joy instruction at its established address.
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
    jmp bg_cache_reset_counts

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
    jsr rc_copy          ; pt.21: mirror the render code $E9:8000-$AFFF -> $7F:8000, THEN
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

; bg_hscroll — set BG1HOFS from the live arcade scroll shadow and center crop.
; The X1-001 "type0" playfield is a continuous H-scroll: tilemap column c sits at true
; pixel T[c] = (T[0] + c*32) mod 512, and vid_bg already lays columns out sequentially
; (col c at BG pixel c*32), so BG1HOFS = -T[0] reproduces arcade X=0.  SNES
; screen X=0 must instead show arcade X=64, the centered 384->256 crop origin.
;   T[0]  = (scrollx[0] - (upper.bit0 ? 256 : 0)) & $1FF   (per x1_001.cpp draw_background)
;   hofs  = (-T[0] + 64) & $3FF
;         == ((upper.bit0<<8) - scrollx[0] + 64) & $3FF
; scrollx[0] = low byte of word @ $D00408 (shadow $41:3408 -> low byte $41:3409);
; upper.bit0 = bit0 of spritectrl[2] @ $D00604 (shadow $41:3604 -> low byte $41:3605).
; The arcade screen is 240 lines, not 256.  Centering its 240->224 crop begins at
; arcade Y=8.  obj_pyfix therefore computes 240-(sy+14)-8, modulo 256 for the
; X1-001/SNES top-edge wrap shared by partially visible 16px sprites.
obj_pyfix:
    rep #$30
    lda #$00E8           ; 240 arcade lines - 8-line centered crop origin
    sec
    sbc $F2              ; py = 232 - ((sy+14)&$FF)
    and #$00FF
    nop                  ; shrink this helper by four bytes so bg_hscroll can add
    nop                  ; the centered X origin without moving fixed $88CC
oy_done:
    rts

bg_hscroll:
    php
    rep #$30
    sep #$20             ; 8-bit A
    lda $7E8995          ; cached low byte of raw word $41:3408
    rep #$20             ; 16-bit A
    and #$00FF
    sta $D0              ; scratch (free after vb_loop)
    sep #$20
    lda $7E8997          ; cached low byte of raw word $41:3604
    and #$01             ; upper bit for column 0
    rep #$20
    and #$00FF
    xba                  ; A = bit0<<8  ($0100 or $0000)
    sec
    sbc $D0              ; (upper.bit0<<8) - scrollx[0]
    clc
    adc #$0040           ; centered 384->256 crop begins at arcade X=64
    and #$03FF
    sep #$20
    sta BG1HOFS          ; low byte
    xba
    sta BG1HOFS          ; high byte
    plp
    rts

; dma0_blank_pulse — publish a channel-0 DMA for the next NMI/VBlank.
; Callers have already programmed $4300-$4306 and enter A8/X16.  The former
; implementation set INIDISP=$80 immediately around every DMA.  Once production
; reached a render every two video frames, Mesen 2.1.1 showed those mid-screen
; blank pulses as black horizontal bars on every rendered frame.  Merely polling
; HVBJOY is insufficient: NMI can consume most of an already-active VBlank before
; returning to this helper, which made the 4 KiB tilemap upload partial.  Publish
; byte flag $1F11 instead; nmi_pacing_wram executes DMA0 near the leading edge,
; then clears the flag.  Small follow-up transfers may share the safe tail of
; that same VBlank according to their actual byte count; larger transfers wait
; for a fresh NMI edge.  The pinned entry jumps to the size-aware implementation
; in the $8Axx helper island so the tightly packed $88CC-$8900 seam does not grow.
.a8
.i16
dma0_blank_pulse:
    jmp dma0_blank_pulse_extended

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
    rtl                  ; DEFERRED (2026-07-10): arming at reset broke the boot's RAM
                         ; self-test (loop_hook corrupts a pass -> error display; open
                         ; interp bug). The escape gates + loop fast-path now arm in
                         ; snd_vframe when the 68K sound ring first reads initialized
                         ; (self-test passed, gameplay code begins). The interp's boot
                         ; `jsl BOOT_ARM` stays (zero bank-$00 shift); this is a no-op
                         ; again, like the VID_INIT it originally replaced.

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
.org $8918               ; vf_tick's PINNED address (the wl blob jsl's $7F8918 LITERALLY,
                         ; and Nexen states resume here). It was previously pinned only by
                         ; BOOT_ARM's byte count ending at $8917; when BOOT_ARM shrank to a
                         ; bare rtl (deferred arming, 2026-07-10) vf_tick silently slid to
                         ; $8901 — org-pin it so layout changes can't move it again.
vf_tick:                 ; reached via the fixed $8004 wrapper (jsl VFT_VEC from the blob)
    php
    rep #$30
    jsr joy5a22_ordered  ; foreground producer before pacing; NMI-only producer after cadence arm
    jsr snapshot_acquire ; paced path claims one NMI-owned immutable cache image
    jsr vid_frame        ; build CGRAM/OAM/BG from that coherent cached image + DMA to PPU
    jml.l $7FA090        ; queue-aware finish in the ordinary WRAM mirror; pinned below
    nop
    nop
    nop
    nop
    nop

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
    cpx #$0037           ; WL_LEN = 55 bytes — keep in sync with the blob below
    bne wl_copy
    plb                  ; DBR=$00 again (the blob polls IRAM $3300 via abs)
    sep #$20
    lda #$80
    sta NMITIMEN         ; NMI on; auto-joypad remains off (manual $4016 sampling below)
    sta $2202            ; acknowledge any stale SA-1 -> S-CPU coprocessor request
    sta $2201            ; enable that IRQ source on the 5A22
    lda #$5A
    sta $41012D          ; publish LAST: pacing may arm only after WRAM handlers are runnable
    cli
    rep #$30
    jml $7EF000          ; the 5A22 lives in WRAM from here on

wl_blob:                 ; assembled here, RUN at $7E:F000. Position-independent: relative
                         ; branches only (to in-blob labels); abs data is DBR($00)-based; ROM
                         ; calls are fixed 24-bit vectors. rep #$30 + DBR=$00 on entry.
                         ; WL_LEN below = 0x37 (55 bytes) -- keep wl_setup's cpx in sync.
wl_poll:
    ldx #$0080           ; throttle: ~128 dex/bne of pure-WRAM fetches (~700 cyc) per poll
wl_dly:
    dex
    bne wl_dly
    ; --- steady ~60Hz Tad_Process, VBlank-edge-paced. TAD is HOST-TICK-DRIVEN (the song advances
    ;     one tick per Tad_Process call), so it MUST run at a steady 60Hz -- NOT coupled to the
    ;     sub-realtime, irregular game-frame render (vf_tick) below. $1F10 = "handled this vblank". ---
    sep #$20             ; A8 (X stays 16-bit); TAD ABI = A8/X16
    lda $4212            ; HVBJOY: bit7 = in-VBlank
    bpl wl_notvb         ; not in vblank -> arm for the next rising edge
    lda $1F10            ; already ran Tad_Process this vblank?
    bne wl_novb
    lda #$01
    sta $1F10            ; mark this vblank handled (edge -> one call per frame = 60Hz)
    jsl.l Tad_Process|$7F0000   ; A8/X16 already set; the $7F WRAM copy (NOT $E9 ROM - 5A22
                                ;   ROM-hosted execution loses stores once the SA-1 runs its
                                ;   per-frame $E9 hook; see the rc_copy P3 CONCURRENT FIX note)
    bra wl_novb
wl_notvb:
    stz $1F10            ; out of vblank -> re-arm
wl_novb:
    rep #$30
    lda $1F1E            ; latest FRAME_REQ whose direct snapshot NMI completed
    cmp $3302            ; FRAME_ACK
    beq wl_poll          ; no ready image -> keep idling in low-contention WRAM
    sta $3302            ; ack this tick
    jsl.l $7F9800        ; P2: drain the 68K sound-command ring -> TAD (sound_tick, $7F WRAM
                         ;   copy of $E9:9800 - see the rc_copy P3 CONCURRENT FIX note).
                         ;   LITERAL vector (not a symbol) per the $7F8918 rule; sound_tick php/plp's
                         ;   its own width so no state juggling here. Runs once per game tick.
    jsl.l $7F8918        ; vf_tick ($7F WRAM copy, pinned $8918): joy + render, once per game
                         ;   tick. Direct (was jsl VFT_VEC=$E98004, whose 4-byte jml wrapper
                         ;   executed from ROM $E9 - eliminated for the same ROM-exec hazard)
    bra wl_poll          ; back to the throttle

; ---- rc_copy — pt.21: mirror the render code into WRAM bank $7F ------------------------
; The 5A22's per-tick render (vf_tick -> joy5a22 + vid_frame -> vid_bg/vid_obj/decode_tile +
; helpers, $E9:8000-$AFFF) fetches from ROM at ~100% duty during combat, taxing the SA-1
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
    lda $E98000,x        ; long,X src: render bank ROM ($E9:8000-$AFFF; +X never crosses bank)
    sta $7F8000,x        ; long,X dst: WRAM mirror ($7F:8000-$AFFF)
    inx
    inx
    cpx #$3000           ; 12KB window: renderer plus the bounded BG reclaimer at $A800
                         ; (TAD glue+port $9000-$93xx, sound_tick $9800, snd_map+snd_tbl
                         ; $9A00-$9AC6; snd_vframe $9900 rides along harmlessly - the SA-1
                         ; keeps running the $E9 original). P3 CONCURRENT FIX: once the SA-1
                         ; starts executing its per-game-frame $E9 hook (snd_vframe), 5A22
                         ; code EXECUTED from ROM $E9 loses its effect (stores never land;
                         ; measured: sound_tick jsl round-trips but its counters/W-reads stay
                         ; zero, while the SAME instructions hosted in WRAM work) - the same
                         ; class of hazard as the pt.20/21 "idle 5A22 must execute from WRAM"
                         ; latch rule. So ALL per-tick 5A22 sound code runs from the $7F copy
                         ; (TAD internal jsl's forced |$7F0000 via regen.sh TAD_CODE_BANK).
    bne rc_l
    plp
    jsr video_boot_init_extended ; vid_init only; deferred boot helpers run after Tad_Init
    ; --- TAD BSS zero-init (defensive, replicates ca65 crt0). vid_init clears only $7E:2000+,
    ;     so the supervisor never zeroes $7E:0000-1FFF where TAD's BSS ($00:1F00-1F0F) and
    ;     sfxQueue DP ($68/$69) live; the stock ca65 sound-test gets this from crt0. Correct
    ;     hygiene on random power-on WRAM, but NOT the P1 boot-flakiness root cause -- that
    ;     was the DataTable segment-offset skew in tad_glue.pasm (see DATA_SEGMENT_SKEW). ---
    rep #$30             ; 16-bit A/X (guaranteed, independent of plp/vid_init) for the long stores
    lda #$0000
    sta $410122          ; pacing snapshot arm = inactive until the organic production gate
    sta $41012A          ; vblank epoch + last-release epoch = 0
    sta $41012C          ; cadence marker + 5A22-ready byte = 0
    sta $410130          ; bounded catch-up debt = 0
    ldx #$001e
tad_bssclr:
    sta $7e1f00,x        ; TAD BSS + private supervisor state $1F00..$1F1F -> 0
    dex
    dex
    bpl tad_bssclr
    sta $7e0068          ; Tad_sfxQueue_sfx($68)/_pan($69) -> 0 (Tad_Init re-sets sfx=$ff next)
    ; --- P2 sound-mailbox init (5A22-private WRAM; see sound_tick @ $9800) ---
    lda #$0080
    sta $7e1f1b          ; bit7=Mode 7 boot indicator active; low7=two-vblank phase
                         ; (also clears the low byte of the adjacent debug call counter)
    lda #$0020
    sta $7e1f14          ; read cursor = ring base $0020 (empty until the game enqueues)
    sta $410120          ; $41 position slot = $20 too, so before snd_vframe first runs (game not
                         ;   yet executing at boot) sound_tick sees W==cursor==$20 -> empty, no drain
    sep #$20             ; A8
    rep #$10             ; X16  (TAD ABI)
    jsl.l Tad_Init|$7F0000       ; upload loader.bin -> audio-driver.bin (blocking IPL handshake;
                                 ;   the $7F copy exists - rc_copy ran above). BOOT-PHASE NOTE:
                                 ;   ROM-hosted 5A22 exec is still safe HERE (the hazard begins
                                 ;   when the SA-1 reaches its per-frame $E9 hook, seconds later),
                                 ;   but the $7F copy is used for consistency; the near `jsr
                                 ;   Tad_LoadSong` below still executes this rc_copy tail's own
                                 ;   bank and is boot-phase-only.
    lda #$01             ; Song id 1 = 01 Attract Mode (arcade boots into attract)
    jsr video_boot_finish_extended ; finish the boot-only song request
    rts

; Large producer-prepared native BG runs cannot be issued as one DMA: the
; visible-period tail is rejected by the PPU.  This WRAM-mirrored helper owns a
; formerly empty renderer seam and receives an already-programmed DMA0 with its
; total byte length in $D6.  It balances bg_tile_run_dma's PHP itself.
.org $8A00
.a8
.i16
bg_tile_run_dma_chunks:
    rep #$20
.a16
btr_chunk_loop:
    lda $D6
    cmp #$1701
    bcc btr_final_chunk
    sec
    sbc #$1700
    pha
    sep #$20
.a8
    stz DAS0L
    lda #$17             ; 5.75 KiB: about 35 of the 37 VBlank scanlines
    sta DAS0H
    jsr dma0_blank_pulse
    rep #$20
.a16
    pla
    sta $D6
    bra btr_chunk_loop
btr_final_chunk:
    sep #$20
.a8
    lda $D6
    sta DAS0L
    lda $D7
    sta DAS0H
    jsr dma0_blank_pulse
    plp
    rts
bg_tile_run_dma_chunks_end:

; Service a foreground-published PPU DMA only after the scheduler wake has run
; at its established leading-edge position.  Controller sampling follows the
; DMA but still completes before NMI return and the next wake decision.  A
; 5.75 KiB transfer consumes roughly 35 scanlines; running it before
; pacing_try_wake shifted the SA-1 release deep into VBlank and eventually
; destroyed the task-ordering contract.  Small CGRAM/OAM transfers are different:
; queue-capture work can move the following NMI entry to line 236, but a sub-1 KiB
; transfer still fits safely before line 252.  Use the programmed descriptor size
; to retain that safe tail instead of making a 544-byte upload wait three frames.
; Larger transfers keep the conservative leading-edge cutoff.  If there is not
; enough VBlank left, retain the flag and let the foreground wait for the next NMI.
.a8
.i16
service_pending_dma0:
    lda $1F11
    beq spd_done
    lda HVBJOY
    bpl spd_done
    lda SLHV             ; latch H/V counters
    lda OPVCT            ; vertical low byte
    tax
    lda DAS0H
    cmp #$04
    bcs spd_large
    txa
    cmp #$FC             ; sub-1 KiB: start no later than line 251
    bcs spd_done
    bra spd_line_ok
spd_large:
    txa
    cmp #$E3             ; large descriptor: start no later than line 226
    bcs spd_done
spd_line_ok:
    lda OPVCT            ; vertical bit 8 (reject lines 256-261)
    and #$01
    bne spd_done
    lda #$01
    sta MDMAEN
    stz $1F11            ; release foreground only after DMA completes
spd_done:
    rts
service_pending_dma0_end:

; Continue a renderer's consecutive sub-1 KiB transfers in the VBlank that
; serviced its first descriptor.  The common OBJ native record is 128 bytes;
; rejecting every transfer at line 252 made a cache refill issue only one or two
; records per VBlank and stretched a 7.8 KiB burst across ten video frames.
; Size tiers retain a full scanline of safety before visible line 0:
;   <=255 bytes through line 259, <=511 through 257, <=767 through 256,
;   <=1023 through 253.  Larger descriptors always publish for a fresh NMI.
.a8
.i16
dma0_blank_pulse_extended:
    phx
    lda HVBJOY
    bpl dma0_publish
    lda DAS0H
    cmp #$04
    bcs dma0_publish
    lda SLHV
    lda OPVCT
    tax
    lda OPVCT
    and #$01
    bne dma0_high_page

    ; Lines 225-255.  High-byte tiers 0-2 all fit from line 255; the
    ; 768-1023-byte tier needs two more scanlines of margin.
    lda DAS0H
    cmp #$03
    bcc dma0_direct
    txa
    cmp #$FE
    bcs dma0_publish
    bra dma0_direct

dma0_high_page:
    lda DAS0H
    beq dma0_high_tiny
    cmp #$01
    beq dma0_high_511
    cmp #$02
    bne dma0_publish
    txa
    cmp #$01             ; 512-767 bytes: line 256 only
    bcs dma0_publish
    bra dma0_direct
dma0_high_511:
    txa
    cmp #$02             ; 256-511 bytes: lines 256-257
    bcs dma0_publish
    bra dma0_direct
dma0_high_tiny:
    txa
    cmp #$04             ; <=255 bytes: lines 256-259
    bcs dma0_publish
dma0_direct:
    lda #$01
    sta MDMAEN
    plx
    rts
dma0_publish:
    plx
    lda #$01
    sta $1F11            ; private WRAM: pending DMA0 descriptor, published last
dma0_wait_complete:
    lda $1F11
    bne dma0_wait_complete
    rts
dma0_blank_pulse_extended_end:

; Mode 7 boot activity. The user-supplied SA-1 logo performs one non-rotating
; 64-frame zoom from an intentionally huge close-up to the established fitted
; size. Bit 6 of $1F1B latches that the zoom is complete; the low six bits
; then remain a palette-pulse heartbeat. The animation never repeats.
; joy5a22_ordered clears bit7 before the first game renderer owns the PPU.
.org $8B00
.a8
.i16
boot_mode7_tick:
    lda $1F1B
    bpl bmt_done         ; zero/positive = game renderer owns the display
    jsr boot_mode7_scale_tick
    lda $1F1B
    and #$20             ; one slow brightness cycle every 64 VBlanks
    beq bmt_dim
    lda #$83             ; OBJ palette 0, color 3
    sta CGADD
    lda #$FF             ; bright amber = SNES BGR555 $16FF
    sta CGDATA
    lda #$16
    sta CGDATA
    rts
bmt_dim:
    lda #$83
    sta CGADD
    lda #$CA             ; dim amber = SNES BGR555 $04CA
    sta CGDATA
    lda #$04
    sta CGDATA
bmt_done:
    rts
boot_mode7_tick_end:

; Mark every persistent OBJ cache slot referenced by the OAM image that is
; currently on screen.  The rare high-water reclaimer runs before replacement
; OAM is published; without this quarantine it could recycle one of those
; slots and rewrite its VRAM pixels while the old OAM still named it, producing
; the transient wrong Superman/enemy tiles seen during attack animations.
;
; OAM byte 2 is tile bits 0-7 and attribute bit 0 is tile bit 8.  obj_T maps
; physical slot s to T=2*(s&7)+32*(s>>3), so the inverse below is:
;   s = ((T & $01E0) >> 2) | ((T & $000E) >> 1)
; The protected old-only slots deliberately remain outside both the rebuilt
; hash and free list for this reclamation.  A later high-water pass releases
; them after replacement OAM has become the displayed image.
.org $8B40
.a16
.i16
obj_cache_protect_displayed:
    rep #$30
    lda $7E89B2          ; active entries in the currently displayed OAM image
    cmp #$0080
    bcc ocpd_count_ready
    lda #$0080           ; defensive clamp for checkpoint/corruption recovery
ocpd_count_ready:
    asl a
    asl a
    sta $D4              ; OAM low-table byte limit
    ldx #$0000
ocpd_loop:
    cpx $D4
    beq ocpd_done
    stx $D6              ; no absolute-long,Y encoding: retain the OAM cursor
    lda $7E8602,x        ; tile low byte + attribute byte
    and #$01FF
    sta $D0
    and #$000E
    lsr a
    sta $D2
    lda $D0
    and #$01E0
    lsr a
    lsr a
    ora $D2
    tax
    sep #$20
.a8
    lda #$01
    sta $7E2E00,x        ; quarantine the displayed physical slot
    rep #$20
.a16
    ldx $D6
    inx
    inx
    inx
    inx
    bra ocpd_loop
ocpd_done:
    rts
obj_cache_protect_displayed_end:

; Advance the one-shot identity-matrix zoom. Matrix entries are eight bytes
; (A/B/C/D); B and C are always zero, so only A/D need live PPU writes.
; Once table entry 63 has been applied, bit6 latches and only the low-six-bit
; activity phase advances. There is deliberately no rotation and no restart.
.org $8BC0
.a8
.i16
boot_mode7_scale_tick:
    lda $1F1B
    bit #$40
    bne bmst_settled
    and #$3F
    rep #$20
.a16
    and #$003F
    asl a
    asl a
    asl a
    tax
    sep #$20
.a8
    lda $7EF100,x
    sta M7A
    lda $7EF101,x
    sta M7A
    lda $7EF106,x
    sta M7D
    lda $7EF107,x
    sta M7D
    lda $1F1B
    and #$3F
    cmp #$3F
    beq bmst_finish
    inc a
    ora #$80
    sta $1F1B
    rts
bmst_finish:
    lda #$C0
    sta $1F1B
    rts
bmst_settled:
    inc a
    and #$3F
    ora #$C0
    sta $1F1B
    rts
boot_mode7_scale_tick_end:

; =============================================================================
; Production 30 Hz pacing supervisor — copied by rc_copy and executed from WRAM.
;
; Shared state:
;   $41:0122 = snapshot arm: 0 inactive, 1 SA-1 quiescent, 2 released, 3 claimed
;   $41:012A = monotonically wrapping 5A22 vblank epoch
;   $41:012B = epoch of the last SA-1 release
;   $41:012C = cadence initialized marker ($A5)
;   $41:012D = 5A22 supervisor ready publication ($5A)
;   $41:0130 = bounded catch-up debt in video frames (0..10)
;   $7E:1F1E = FRAME_REQ sequence represented by the latest complete direct snapshot
;
; At the $0818 idle boundary the SA-1 publishes arm=1 and requests one S-CPU
; deadline check, then sleeps with IRQ vectoring masked. NMI advances the epoch.
; At two real vblanks, either the NMI or the one-shot coprocessor IRQ claims the
; stable shadow, publishes the cached real-pad sample, snapshots the seven renderer
; input KiB to WRAM, releases ownership, and wakes the SA-1. The controller read for
; the following tick happens only after that decision, outside active SA-1 work.
;
; vf_tick keeps its three-byte call site pinned. Before cadence initialization it
; tail-calls the original foreground producer for boot compatibility; afterwards
; NMI is the sole mailbox producer, so input cannot be published after the SA-1 wake.
; =============================================================================
.org $8DD0
.a16
.i16
joy5a22_ordered:
    php
    sep #$20
    stz $1F1B            ; first renderer claim retires the Mode 7 boot animation
    lda $41012C
    cmp #$A5
    beq j5o_nmi_owner
    plp
    jmp joy5a22
j5o_nmi_owner:
    plp
    rts

.org $8E00
.a8
.i16
pacing_try_wake:
    lda $410122          ; proven shared BW-RAM window; low byte is the arm state
    cmp #$01
    beq ptw_arm_seen
    rts                   ; SA-1 active, already released, or another path claimed it
ptw_arm_seen:
    lda $410130
    beq ptw_two_frame_deadline
    ; Repay accumulated transition debt one video frame at a time.  The SA-1
    ; still waits for at least one real vblank, so catch-up can never create a
    ; zero-frame/burst game tick.
    lda $41012A
    sec
    sbc $41012B
    cmp #$01
    bcs ptw_deadline_due
    rts
ptw_two_frame_deadline:
    lda $41012A
    sec
    sbc $41012B
    cmp #$02
    bcs ptw_deadline_due
    rts                   ; exactly two real vblanks per game tick
ptw_deadline_due:
    rep #$20
    lda #$0003
    sta $410122          ; claim before touching the stable live shadow
    lda $7E1F12          ; real pad sampled after the previous wake decision
    ora $410002          ; combine the current headless/harness injection word
    sta $410000          ; sole ordered mailbox publish while the SA-1 is quiescent
ptw_renderer_ownership_guard:
    lda $7E899C          ; renderer owns the direct WRAM caches until vid_frame returns
    bne ptw_snapshot_queued
    ; An even direct generation can be complete but not yet claimed by wl_blob.
    ; Treat that publication-to-ACK interval as busy too: replacing $1F1E here
    ; would make the worker ACK the newer sequence and silently coalesce the old
    ; image even though neither compressed queue was full.
ptw_pending_direct_guard:
    lda $7E1F1E
    cmp $3302
    beq ptw_snapshot_direct
ptw_snapshot_queued:
    lda $7E89D2          ; primary compressed snapshot may wait behind the renderer
    bne ptw_try_queue2
    jsl.l $E9B000        ; ROM execution is safe here: arm=3 keeps the SA-1 asleep
    bra ptw_snapshot_busy
ptw_try_queue2:
    lda $7E89D6
    bne ptw_queue_full
    jsl.l $E9B140
    bra ptw_snapshot_busy
ptw_queue_full:
    lda $7E89D4
    inc a
    sta $7E89D4          ; explicit overflow evidence; candidate stays unacked
    bra ptw_snapshot_busy
ptw_snapshot_direct:
    jsr pacing_snapshot_direct
    lda $3300
    sta $1F1E            ; DBR=$00: publish the request represented by this snapshot
ptw_snapshot_busy:
    lda #$0002
    sta $410122          ; release ownership before raising the wake request
    sep #$20
    lda #$80
    sta $2200            ; wake only after all three DMA operations complete
    rts

; Capture the real controller for the next release. Two byte rotates preserve the
; old manual-reader ordering: first serial bit -> bit 15, active high. Both callers
; run with DBR=$00 and touch only CPU I/O plus 5A22-private WRAM.
.a8
.i16
pacing_sample_joy:
    stz $1F12
    stz $1F13
    lda #$01
    sta $4016
    stz $4016
    ldx #$0010
psj_loop:
    lda $4016
    lsr a
    rol $1F12
    rol $1F13
    dex
    bne psj_loop
    rts
pacing_helpers_end:

.org $8F00
nmi_pacing_wram:
    php
    rep #$30
    pha
    phx
    phy
    phb
    sep #$20
    lda #$00
    pha
    plb
    lda #$80
    sta $2201            ; keep the coprocessor-IRQ source enabled
    lda $41012A
    inc a
    sta $41012A          ; one shared-window epoch increment per real SNES vblank
    jsr pacing_try_wake
    jsr service_pending_dma0
    jsr pacing_sample_joy
    jsr boot_mode7_tick
    lda $3302            ; leave Bus-A latched on IRAM, not a ROM fetch
    plb
    ; Patch the hardware-saved return P while A/X/Y are still protected on our
    ; stack.  The old order restored A first and then used LDA/AND/STA here,
    ; corrupting the interrupted A low byte on every vblank.  In particular an
    ; NMI between a renderer LDA and its following STA could poison loop/hash
    ; state and strand the 5A22 inside one frame.  At this point the saved A,
    ; X, and Y occupy six bytes above S, our PHP byte is +7, and the hardware
    ; return P is +8.
    sep #$20
    lda $0008,s
    and #$FB             ; keep coprocessor IRQs enabled after NMI
    sta $0008,s
    rep #$30
    ply
    plx
    pla                  ; restore interrupted A after the flag-patch scratch
    plp
    rti

.org $8F40
irq_pacing_wram:
    php
    rep #$30
    pha
    phx
    phy
    phb
    sep #$20
    lda #$00
    pha
    plb
    lda #$80
    sta $2202            ; acknowledge SA-1 -> S-CPU coprocessor IRQ
    jsr pacing_try_wake
    jsr pacing_sample_joy
    lda $3302            ; leave Bus-A latched on IRAM
    plb
    rep #$30
    ply
    plx
    pla
    plp
    rti

; ============================================================================
; sound_tick — P2 STEP 2: drain the 68K sound-command ring and drive TAD.
; ----------------------------------------------------------------------------
; RE (docs/SOUND_COMMAND_MAP.md): the arcade sound interface is a SINGLE-BYTE
; TRIGGER stream (proven: the Z80 owns the music engine; it wrote the YM2610 5116x
; while the 68K sent 0 cmds over 120 frames). The 68K enqueues one command byte per
; game event into a 32-byte ring at work RAM $f01c20-$f01c3f, write ptr $f01c40
; (a big-endian 32-bit ADDRESS; its low/position byte is at $f01c43), wrap at $1c40.
; The interp mirrors 68K work RAM $f0xxxx -> BW-RAM $40:xxxx, so the ring lives at
; $40:1c20 (write position at $40:1c43). BUT the 5A22 CPU CANNOT reliably read live
; $40 OR live IRAM (the SA-1 hammers work RAM + the $0400-05FF IRAM scheduler every cycle
; -> the 5A22's reads there are stale: measured $1F/$14/$3B vs the true $24). The ONE
; proven 5A22-readable shared channel is BW-RAM $41 -- the SA-1 writes it only in per-frame
; bursts (the video shadow the render reads reliably). So the SA-1 (which reads its own $40
; coherently) copies the ring into $41:0100 + the write position into $41:0120 each
; game-frame, inside the VID_FRAME hook (snd_vframe). sound_tick reads that $41 copy. We
; keep a 5A22-private read cursor and map each NEW command -> Tad_LoadSong / QueueSoundEffect.
;
; Why $41-via-SA-1 and not an interp-side $0080 mailbox: bank $00 is packed (no >=20B code
; gap; wb_vid's early `jmp` can't be resized without a cascading shift). The SA-1-side ring
; copy needs ZERO bank-$00 changes -- it rides the existing per-frame VID_FRAME hook (bank
; $E9, roomy). Cost: couples to the 68K ring layout (verified: the write ptr reads
; $00 F0 1C 2x, big-endian, position byte at $1c43).
;
; State (5A22-private $7E WRAM, inited in rc_copy; SA-1 can't touch $7E):
;   $7E:1F14 = read cursor (16-bit, valid range $0020-$003F)
;   $7E:1F16 = drained-command count (debug, 8-bit, wraps)
;   $7E:1F17 = last command byte (debug)
;   $7E:1F18 = scratch (W)
;   $7E:1F19 = W-as-read debug (16-bit store; $1F1A = its always-zero high byte)
;   $7E:1F1C = call counter (16-bit; moved off $1F1A — see the note at the inc)
; Called via `jsl.l $E99800` from wl_blob once per game tick. php/plp-bracketed so the
; caller needs no width juggling. Tad_LoadSong/QueueSoundEffect are near (same bank $E9).
; ============================================================================
.org $9800
sound_tick:
    php
    rep #$30             ; 16-bit A/X
    lda $7e1f1c
    inc a
    sta $7e1f1c          ; DEBUG: sound_tick call counter (proves it runs). At $1F1C, NOT
                         ;   $1F1A: the W-debug `sta $7e1f19` below runs in 16-BIT A, so it
                         ;   also writes $1F1A (W's high byte, always 0) — the counter lived
                         ;   there originally and was SELF-ZEROED every call, which cost a
                         ;   long false "sound_tick never runs" diagnosis (P3 concurrent
                         ;   validation). $1F1A is now documented as the Wdbg high byte.
    lda.l $410120        ; W = write position from the $41 shadow copy (snd_vframe mirrors $40:1c43
    and #$00ff           ;   here). $41 is the proven 5A22-readable channel (the render reads it);
                         ;   force long (.l) so DBR is irrelevant.
    sta $7e1f19          ; DEBUG: raw W as the 5A22 reads the IRAM copy
    cmp #$0020
    bcc st_done          ; W < $20  -> ring uninitialized / no valid position -> nothing to do
    cmp #$0040
    bcs st_done          ; W > $3f  -> invalid
    sta $7e1f18          ; stash W
    lda $7e1f14          ; cursor
    cmp #$0020
    bcc st_adopt         ; cursor invalid -> sync to W (process nothing this pass)
    cmp #$0040
    bcc st_drain
st_adopt:
    lda $7e1f18
    sta $7e1f14          ; adopt W
    bra st_done
st_drain:
    lda $7e1f14
    cmp $7e1f18          ; cursor == W ? (no new commands)
    beq st_done
    tax                  ; X = cursor ($20-$3f)
    sep #$20             ; A8 (X stays 16-bit for the TAD ABI)
.a8
    lda.l $4100e0,x      ; command byte from the $41 ring copy (base $410100-$20 = $4100E0; +cursor)
    sta $7e1f17          ; debug: last command
    lda $7e1f16
    inc a
    sta $7e1f16          ; debug: drained count++ (long lda/sta; $7E not DBR)
    lda.l $4100e0,x      ; reload command (A8) for the map (from the $41 ring copy)
    jsr snd_map          ; A=cmd (A8), X16 -> Tad_LoadSong / Tad_QueueSoundEffect
    rep #$20             ; 16-bit for the cursor advance
.a16
    lda $7e1f14
    inc a
    cmp #$0040
    bcc st_nowrap
    lda #$0020           ; wrap $40 -> $20 (matches the 68K's $1c40 -> $1c20 ring wrap)
st_nowrap:
    sta $7e1f14
    bra st_drain
st_done:
    plp
    rtl


; ============================================================================
; snd_vframe — VID_FRAME hook (SA-1 side, bank $E9). Runs once per game-frame via the
; $8000 wrapper's `jmp snd_vframe`. Does VID_FRAME's original FRAME_REQ++ AND copies the
; 68K sound-command ring into BW-RAM $41 so the 5A22's sound_tick can read it (the 5A22
; CANNOT reliably read the SA-1's live $40 work RAM OR live IRAM -- stale reads; the SA-1
; reads its own $40 coherently, and $41 is written only in per-frame bursts so the 5A22
; reads it cleanly, like the video shadow). DBR=$00 on entry (the original `inc $3300`
; relies on it). Returns via rtl into the interp IRQ path (interp.pasm irq_chk) so P/A/X
; MUST be preserved.
;   $41:0100-$41:011f = 32-byte ring copy (mirrors $40:1c20-1c3f)
;   $41:0120          = write-position byte (mirrors $40:1c43)
; $41:0100+ is free (joy mailbox is $41:0000-3, video shadow starts $41:2000). Verify 8/8 boot.
; ============================================================================
.org $9900
snd_vframe:
    php
    rep #$30             ; 16-bit A/X
    pha
    phx
    ldx #$001e           ; copy $40:1c20..1c3f -> BW-RAM $41:0100..011f (16 words; x=$1e down to 0)
sv_cp:
    lda $401c20,x        ; long,X: the SA-1 reads its OWN work RAM $40 (coherent, no contention)
    sta $410100,x        ; long,X: $41 shadow copy. NOT IRAM -- the SA-1 hammers IRAM ($0400-05FF
                         ;   scheduler) so the 5A22's IRAM reads are stale; but $41 is written only
                         ;   in per-frame bursts (like the video shadow the render reads reliably).
    dex
    dex
    bpl sv_cp
    sep #$20             ; A8 for the single position byte
    lda $401c43          ; W = write-position byte ($40:1c43)
    sta $410120          ; $41 position slot
    ; --- DEFERRED ACCELERATOR ARMING (boot-self-test fix, 2026-07-10) -----------------
    ; The boot's walking-bit RAM test ($3F60-$4008 suite) FAILS when loop_hook is armed
    ; (parks in the $1B90-$1D46 error display; open interp-side bug — an lh/gm collapse
    ; corrupts a later pass). So NOTHING is armed at reset anymore (interp boot leaves
    ; $072E=0; BOOT_ARM defers here). Arm ONCE when the 68K's sound-ring WRITE POINTER
    ; longword at $40:1c40 reads as its initialized value $00F01C2x — a 4-byte signature
    ; the game writes right after the self-test + hw init (exactly when gameplay code,
    ; the accelerators' validated domain, begins) and which no RAM-test pattern can fake
    ; (the tests sweep uniform/walking patterns through $1c40-43; W alone ($2x) CAN
    ; transiently appear mid-test, which is why the full signature is checked).
    ; SA-1-side, so the $07xx IRAM writes need no SIWP and cannot race the sled
    ; mid-instruction (we ARE the SA-1, between instructions in the IRQ path).
    rep #$20
    ldx $0768            ; armed-once latch (free IRAM word, 0 at reset iramclr; NOT $0764,
                         ;   which is the jah2 escape-dispatch counter. If a future counter
                         ;   ever claims $0768 and wraps through 0 the arm block re-runs —
                         ;   idempotent, so harmless, but keep it unclaimed.)
    bne sv_armed
    lda $401c40          ; wptr bytes [1c40]=$00 [1c41]=$F0 (LE word = $F000)
    cmp #$F000
    bne sv_armed
    lda $401c42          ; wptr bytes [1c42]=$1C [1c43]=$20-$3F
    and #$00FF
    cmp #$001C
    bne sv_armed
    lda $401c43          ; position byte in [$20,$40)
    and #$00FF
    cmp #$0020
    bcc sv_armed
    cmp #$0040
    bcs sv_armed
    lda $41012C          ; high byte is the 5A22-ready publication at $41:012D
    and #$FF00
    cmp #$5A00
    bne sv_armed         ; retry next boundary; never enter WAI before its wake path exists
    lda #$0001
    sta $0768            ; latch first (never re-enter)
    sta $072E            ; LOOP FAST-PATH on — RE-ENABLED after the 2026-07-10 root-cause:
                         ;   the boot RAM-test failure was an .org-overlap truncating
                         ;   lh_3fea + burying lh_adbe/gm_memclr (relocated to escbank5,
                         ;   build-guarded), and the gameplay $080100 derail bisected to
                         ;   the $0818 idle-collapse arm alone (now disabled in loop_hook;
                         ;   see its comment). lh-minus-$0818 + all escapes soaked 36000f
                         ;   clean with fast boot.
    sta $071A            ; ESC   on
    sta $073A            ; CHOKE on
    lda #$A55A
    sta $073C            ; SWIN  on (magic-match gate)
    lda #$5EEC
    sta $0736            ; SEL   on (magic-match gate)
    lda #$0001
    sta $0734            ; publish LAST: production 30 Hz pacing + NMI snapshot ownership
sv_armed:
    rep #$20
    jsr snapshot_publish ; copy the completed six renderer planes under an even/odd generation
    plx
    pla
    inc $3300            ; A is still forced 16-bit: never turn the word doorbell into an 8-bit wrap
    plp                  ; restore caller flags after INC so its M width and NZ side effects cannot leak
    rtl


; snd_map — arcade command byte (A8, X16) -> TAD action, via a 128-entry table.
; docs/SOUND_COMMAND_MAP.md has the full GROUND-TRUTH byte->track map (P3 backfill,
; 2026-07-09): every byte $01-$7F was stimulated directly on the arcade machine in
; MAME (TC0140SYT latch writes, 68K halted) and the Z80's YM2610 register stream
; fingerprint-matched against the 21 VGM rips. Music ids are the contiguous block
; $05-$19 (all 21 tracks); $00 = stop. NOTE this CORRECTED two P2 event-correlation
; guesses: $32 is a rising-scale SFX (round-1 music is really $06), $07 is Main
; BGM 3 (not punch; the demo's action SFX are $4E/$2E).
; Table encoding: $00-$7F = TAD song id (0 = built-in silence); $80|n = SFX n;
; $FF = ignore (unmapped SFX/control). Music goes through Tad_LoadSongIfChanged so
; the game's repeated sends (e.g. $06 x3 at round start) don't restart the song —
; an intervening $00 (silence) still forces a real restart when the arcade wants one.
; ENTERED A8/X16 (sound_tick's TAD ABI); X is free to clobber (the caller reloads its
; cursor from $7E:1F14 after we return). The explicit .a8 is LOAD-BEARING: Poppy's
; sep/rep mode inference resets at a label after rtl and defaulted immediates here
; to 16-bit -> stray $00 operand bytes decoded as BRK at runtime in A8 (shipped
; silently in the P2 snd_map; caught by a byte-level encoding audit in P3).
.org $9a00
.a8
.i16
snd_map:
    ; The arcade mixes its $19 credit cue over the current music.  TAD track 2
    ; is a standalone transcription, so loading it while a song is active
    ; replaces that song and leaves gameplay silent when the short cue ends.
    ; Keep the active track instead; when no song is selected, retain the
    ; existing table mapping so the standalone cue remains available.
    cmp #$19
    bne sm_range
    pha
    lda $7e1f0c          ; TadPrivate_nextSong (explicit WRAM bank; caller DBR is unknown)
    beq sm_coin_silent
    pla
    rts
sm_coin_silent:
    pla
sm_range:
    cmp #$80
    bcs sm_done          ; ids >= $80 never observed -> ignore
    phb                  ; save caller DBR (TAD API needs a low-RAM DB)
    rep #$30
.a16
    and #$007f
    tax
    sep #$20
.a8
    phk
    plb                  ; DBR = PB ($E9) for the table read
    lda snd_tbl,x
    plb                  ; restore caller DBR
    cmp #$ff
    beq sm_done
    cmp #$80
    bcs sm_sfx
    jsr Tad_LoadSongIfChanged
    rts
sm_sfx:
    and #$7f
    jsr Tad_QueueSoundEffect
    rts
sm_done:
    rts

; arcade cmd byte -> action (see the encoding note above; TAD song id N = track N)
snd_tbl:
    .db $00,$ff,$ff,$ff,$ff,$01,$03,$08,$04,$05,$06,$09,$0a,$0b,$0d,$0e   ; $00-$0F
    .db $0f,$10,$11,$12,$07,$0c,$13,$14,$15,$02,$ff,$ff,$ff,$ff,$ff,$ff   ; $10-$1F
    .db $ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$81,$ff   ; $20-$2F
    .db $ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff   ; $30-$3F
    .db $ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$80,$ff   ; $40-$4F
    .db $ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff   ; $50-$5F
    .db $ff,$ff,$81,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff   ; $60-$6F
    .db $ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff   ; $70-$7F

; =============================================================================
; Persistent render-cache helpers ($9B00-$9CFF, copied into $7F WRAM by rc_copy).
;
; The original renderer rebuilt all 392 live BG cells and decoded every visible
; OBJ tile on every game tick.  At fast pacing that costs roughly nine SNES frames
; for BG plus nine for OBJ.  These helpers preserve the completed representation:
;   $7E:2000-$23FF  previous raw BG code words
;   $7E:2400-$27FF  previous raw BG color words
;   $7E:2800-$2BFF  previous raw palette words
;   $7E:3000-$33FF  coherent raw OBJ Y snapshot
;   $7E:4000-$43FF  coherent raw OBJ code/flip snapshot
;   $7E:4400-$47FF  coherent raw OBJ X/palette snapshot
;   $7E:8980+       cache validity/count markers
; The regions are reset by vid_init's existing $7E:2000-$9FFE clear.
; =============================================================================
.org $9B00

.a16
.i16
bg_dispatch:
    php
    rep #$30
    lda $7E8990          ; snapshot_acquire found a new coherent BG code/color image
    beq bg_dispatch_fast
    lda $7E89BC          ; producer's unique changed-cell list
    cmp #$FFFF
    beq bg_dispatch_full
    ; $FFFE is a producer-prepared full image: the SA-1 already built its exact
    ; SNES tilemap, unique-code order, and palette map.  Consume the historical
    ; nine-byte seam without moving any downstream renderer/layout boundary.
    cmp #$FFFE
    bne bg_dispatch_incremental
    jmp bg_dispatch_prepared
    nop
bg_dispatch_incremental:
    jsr vid_bg_incremental
    bcs bg_dispatch_full ; palette-map exhaustion: discard partial staging below
    jsr bg_incremental_finish
    plp
    rts
bg_dispatch_full:
    lda #$0000           ; original vid_bg entry contract for vb_mclr
    jmp vid_bg_heavy
bg_dispatch_fast:
    lda $7E8986          ; ppu_build_cached sets this only when raw palette bytes changed
    beq bg_dispatch_pal_ready
    jsr bg_refresh_pal   ; restore BG's bank->slot mapping after a real palette rebuild
bg_dispatch_pal_ready:
    jsr bg_scroll        ; tilemap/tiles persist, but both scroll axes remain live
    plp
    rts

bg_cache_test:          ; acquire stable $41 snapshot: C=0 unchanged, C=1 cache updated
    rep #$30
    lda $7E8982
    cmp #$B6C3
    bne bg_cache_changed
    ldx #$0000
bg_cache_check_loop:
    lda $416C00,x
    cmp $7E2000,x
    bne bg_cache_changed
    lda $417000,x
    cmp $7E2400,x
    bne bg_cache_changed
    inx
    inx
    cpx #$0400
    bne bg_cache_check_loop
    clc
    rts
bg_cache_changed:
    ldx #$0000
bg_cache_copy_loop:
    lda $416C00,x
    sta $7E2000,x
    lda $417000,x
    sta $7E2400,x
    inx
    inx
    cpx #$0400
    bne bg_cache_copy_loop
    lda #$B6C3
    sta $7E8982
    sec
    rts

bg_refresh_pal:
    rep #$30
    stz $EE              ; arcade palette bank 0..31
bg_refresh_pal_loop:
    ldx $EE
    sep #$20
.a8
    lda $7E8940,x        ; persistent bank->BG-slot map built by the heavy path
    cmp #$FF
    bne bg_refresh_pal_used
    rep #$20
.a16
    bra bg_refresh_pal_next
bg_refresh_pal_used:
.a8
    rep #$20
.a16
    and #$00FF
    sta $F0
    jsr bg_refresh_pal_fill
bg_refresh_pal_next:
    inc $EE
    lda $EE
    cmp #$0020
    bne bg_refresh_pal_loop
    rts

bg_refresh_pal_fill:    ; duplicate of bps_assign's fill, for an already-mapped bank/slot
    rep #$30
    lda $EE
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$2800
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
    lda #$007E
    sta $D2
    lda #$007E
    sta $D6
    ldy #$0000
bg_refresh_pal_fill_loop:
    lda [$D0],y
    xba
    jsr snes_color
    sta [$D4],y
    iny
    iny
    cpy #$0020
    bne bg_refresh_pal_fill_loop
    rts

obj_cache_prepare:
    rep #$30
    jsr obj_queue_prepare
    nop                  ; JSR+NOP is the replaced four-byte long load
    cmp #$A55A
    beq obj_cache_ready
    jsr obj_hclr
    lda #$FFFF           ; force the first OBJ tile upload even if random WRAM mimics count zero
    sta $7E8988
    lda #$A55A
    sta $7E8980
obj_cache_ready:
    rts

obj_cache_restart:
    rep #$30
    jsr obj_hclr         ; a full stale cache cannot map this frame coherently
    lda #$FFFF           ; slot meanings changed; the rebuilt staging must be uploaded
    sta $7E8988
    lda #$A55A
    sta $7E8980
    jmp voi_restart      ; rebuild OAM from entry zero inside vid_obj's saved-P frame

ppu_build_cached:
    ; Keep obj_upload_dispatch pinned at $9C27. Once the game is alive the BG
    ; and OBJ builders refresh every palette slot their tilemaps can reference,
    ; so converting all 256 arcade colors first is duplicate work (about 24K
    ; 5A22 cycles in the measured gameplay path). Boot retains the full table.
    jmp ppu_build_mapped
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop

obj_upload_dispatch:
    jmp obj_upload_queued

.org $9C40
.a16
.i16
obj_slot_fast_hash:
    rep #$30
    lda $C4
    asl a
    clc
    adc $C4              ; hash = (code * 3) & $03FF
    and #$03FF
    asl a
    sta $D8
osfh_probe:
    ldx $D8
    lda $7E5000,x
    beq osfh_insert
    cmp $C4
    beq osfh_hit
    inx
    inx
    txa
    and #$07FF
    sta $D8
    bra osfh_probe
osfh_hit:
    ldx $D8
    lda $7E5800,x
    sta $D8
    jsr obj_T
    rts

osfh_insert:
    lda $7E89CE
    bne osfh_free_allocate
    lda $DE
    cmp #$0080
    bcc osfh_allocate
    jmp obj_slot_fast_full_reset_ext
osfh_allocate:
    ldx $D8
    lda $C4
    sta $7E5000,x
    lda $DE
    sta $7E5800,x
    sta $D8
    inc $DE
    jsr obj_tile_queue
    rts

osfh_free_allocate:
    dec a
    sta $7E89CE
    tax
    sep #$20
.a8
    lda $7E7B00,x
    rep #$20
.a16
    and #$00FF
    sta $D0
    ldx $D8
    lda $C4
    sta $7E5000,x
    lda $D0
    sta $7E5800,x
    sta $D8
    jsr obj_tile_queue
    rts
obj_slot_fast_hash_end:

.org $9D00
.a16
.i16
vid_obj_cached:
    rep #$30
    lda $7E8986          ; palette rebuild overwrote mapped OBJ colors: rebuild even if geometry held
    bne voc_changed
    lda $7E8992          ; coherent OBJ cache changed during snapshot acquisition
    beq voc_done
voc_changed:
    jsr vid_obj_telemetry
voc_done:
    rts

ppu_dma_flush_acked:
    ; FRAME_ACK is claimed before rendering and may skip over several requests,
    ; so it is not a completed-frame counter.  Count only after the PPU flush
    ; returns, and retain the generation that actually reached the screen.
    jsr ppu_dma_flush
    rep #$30
    lda $7E89A2
    inc a
    sta $7E89A2          ; private 5A22 completed-render counter
    lda $7E89A0
    sta $7E89A4          ; last direct-cache generation fully rendered
    rts

vid_obj_telemetry:
    jsr vid_obj_fast
    rep #$30
    lda $E2
    sta $7E89B2          ; active OAM entries in the last heavy OBJ build
    lda $E6
    sta $7E89B4          ; arcade palette banks used by that OBJ build
    lda $DE
    sta $7E89B6          ; persistent decoded OBJ tile-slot count
    rts

; =============================================================================
; Coherent non-blocking video snapshot.
;
; The SA-1 owns the live arcade video shadow at $41:2000-$4FFF.  Letting the
; 5A22 scan those planes while the next game tick rewrites them created the
; wide black OBJ bands seen under fast pacing.  Stopping the SA-1 until the
; renderer acknowledged a snapshot fixed ordering but collapsed production to
; 16.5 Hz, so that architecture is rejected.
;
; snapshot_publish runs on the SA-1 immediately before FRAME_REQ++.  Palette
; and BG planes are copied to $41:6800-$73FF and the two control words to
; $7400.  OBJ is cheaper: hle_158e has already duplicated its existing staged
; DMA into alternating immutable buffers at $5000/$5C00, and publishes a
; completion token at $0128.  $41:0124 is an even/odd seqlock around the
; boundary metadata/palette/BG image.  The producer never waits for the 5A22.
;
; snapshot_acquire runs from the $7F WRAM mirror before any heavy rendering. It
; compares/copies the compact image into persistent WRAM caches, then verifies
; the generation.  If a new boundary overlapped acquisition, it retries all
; domains; dirty flags stay sticky so every derived PPU representation that may
; have become stale is rebuilt.  Heavy tile/OAM work therefore reads WRAM only
; and cannot race the following game tick.
; =============================================================================
.org $9E00
.a16
.i16
snapshot_acquire:
    rep #$30
    lda $41012C          ; shared cadence marker; DBR=$00 makes bare $0734 unrelated WRAM
    and #$00FF
    cmp #$00A5
    bne sa_production
    jmp snapshot_acquire_paced
sa_production:
    lda #$0000
    sta $7E8986          ; palette dirty this acquired image
    sta $7E8990          ; BG code/color dirty
    sta $7E8992          ; OBJ Y/code/X dirty
sa_read_generation:
    lda $410124
    beq sa_generation_wait ; zero means no completed boundary image yet
    bit #$0001
    beq sa_generation_ready
sa_generation_wait:
    ldx #$0080           ; WRAM-only delay: do not hammer BW-RAM while SA-1 publishes
sa_generation_delay:
    dex
    bne sa_generation_delay
    bra sa_read_generation
sa_generation_ready:
    sta $7E898E
    jsr snapshot_palette_cache
    jsr bg_cache_test
    bcc sa_bg_unchanged
    lda #$0001
    sta $7E8990
sa_bg_unchanged:
    jsr snapshot_obj_cache
    lda $417400          ; packed VOFS/scrollx word from capture_bg_vscroll
    sta $7E8994
    lda $417402          ; raw $41:3604 word (spritectrl[2] low byte is the second byte)
    sta $7E8996
    lda $410124
    cmp $7E898E
    bne sa_read_generation
    bit #$0001
    bne sa_read_generation
    rts

snapshot_palette_cache:
    lda $7E8984
    cmp #$C35A
    bne spc_changed
    ldx #$0000
spc_check_loop:
    lda $416800,x
    cmp $7E2800,x
    bne spc_changed
    inx
    inx
    cpx #$0400
    bne spc_check_loop
    rts
spc_changed:
    ldx #$0000
spc_copy_loop:
    lda $416800,x
    sta $7E2800,x
    inx
    inx
    cpx #$0400
    bne spc_copy_loop
    lda #$C35A
    sta $7E8984
    lda #$0001
    sta $7E8986
    rts

snapshot_obj_cache:
    lda $410126
    and #$0001
    beq soc_buffer_a
    lda #$5C00
    bra soc_pointer_base
soc_buffer_a:
    lda #$5000
soc_pointer_base:
    sta $D0              ; three long source pointers for the selected immutable OBJ buffer
    clc
    adc #$0400
    sta $D4
    clc
    adc #$0400
    sta $D8
    sep #$20
.a8
    lda #$41
    sta $D2
    sta $D6
    sta $DA
    rep #$20
.a16
    lda $7E898A
    cmp #$D06F
    bne soc_changed
    ldx #$0000
    ldy #$0000
soc_check_loop:
    lda [$D0],y
    cmp $7E3000,x
    bne soc_changed
    lda [$D4],y
    cmp $7E4000,x
    bne soc_changed
    lda [$D8],y
    cmp $7E4400,x
    bne soc_changed
    inx
    inx
    iny
    iny
    cpx #$0400
    bne soc_check_loop
    rts
soc_changed:
    ldx #$0000
    ldy #$0000
soc_copy_loop:
    lda [$D0],y
    sta $7E3000,x
    lda [$D4],y
    sta $7E4000,x
    lda [$D8],y
    sta $7E4400,x
    inx
    inx
    iny
    iny
    cpx #$0400
    bne soc_copy_loop
    lda #$D06F
    sta $7E898A
    lda #$0001
    sta $7E8992
    rts

snapshot_publish:       ; SA-1 side; caller already saved A/X/P
    rep #$30
    lda $0734
    bne spp_paced_done   ; production pacing snapshots directly to WRAM before waking the SA-1
    lda $410124
    and #$FFFE
    inc a
    sta $410124          ; odd: the compact image is being replaced
    lda $410128          ; hle_158e writes 1/2 only after its A/B OBJ buffer is complete
    beq spp_no_new_obj
    dec a
    and #$0001
    sta $410126
spp_no_new_obj:
    lda #$2000           ; three exact 1 KiB BW-RAM -> IRAM -> BW-RAM transfers
    ldx #$6800
    jsr snapshot_dma_plane
    lda #$4800
    ldx #$6C00
    jsr snapshot_dma_plane
    lda #$4C00
    ldx #$7000
    jsr snapshot_dma_plane
    jsr capture_bg_vscroll
    sta $417400
    nop
    lda $413604
    sta $417402
    lda $410124
    inc a
    bne spp_generation_done
    lda #$0002           ; reserve zero for "no completed snapshot yet"
spp_generation_done:
    sta $410124          ; even: publish atomically before FRAME_REQ increments
spp_paced_done:
    rts

; Copy one 1024-byte plane within physical BW-RAM bank 1.  SA-1 DMA cannot
; transfer BW-RAM directly to BW-RAM, so four synchronous 256-byte chunks pass
; through IRAM $0100-$01FF.  $0200 is immediately after this helper's staging
; window and is never touched.  Entry A=src,
; X=dst; clobbers interpreter scratch $90-$94, which is dead at iloop's frame
; boundary.  DMA is disabled and its completion flag acknowledged on return.
snapshot_dma_plane:
    rep #$30
.a16
.i16
    sta $90
    stx $92
    lda #$0004
    sta $94
sdp_chunk:
    sep #$20
.a8
    lda #$20
    sta $220B

    lda #$81             ; BW-RAM physical bank 1 -> IRAM $000100, 256 bytes
    sta $2230
    lda $90
    sta $2232
    lda $91
    sta $2233
    lda #$01
    sta $2234
    stz $2238
    lda #$01
    sta $2239
    stz $2235
    lda #$01
    sta $2236            ; writing DDA high starts the synchronous IRAM DMA

    lda #$86             ; IRAM $000100 -> BW-RAM physical bank 1, 256 bytes
    sta $2230
    stz $2232
    lda #$01
    sta $2233
    stz $2234
    stz $2238
    lda #$01
    sta $2239
    lda $92
    sta $2235
    lda $93
    sta $2236
    lda #$01
    sta $2237            ; writing destination bank starts the synchronous BW DMA

    rep #$20
.a16
    lda $90
    clc
    adc #$0100
    sta $90
    lda $92
    clc
    adc #$0100
    sta $92
    dec $94
    bne sdp_chunk
    sep #$20
.a8
    lda #$20
    sta $220B
    stz $2230
    rep #$20
.a16
    rts

; Clear the widened authoritative OBJ hash.  Its 1,024 code buckets and parallel
; slot words occupy $7E:5000-$5FFF, reclaimed from the abandoned snapshot
; double-buffer.  Eight stores per branch keep a reset comparable to the old
; 512-bucket scalar clear while halving steady-state occupancy.  Bank $7F is the
; emulated 68000 work RAM and must never be used as renderer scratch.
.org $A000
.a16
.i16
obj_hclr_extended:
    rep #$30
    lda #$0000
    ldx #$0000
ohce_hash_loop:
    sta $7E5000,x
    sta $7E5002,x
    sta $7E5004,x
    sta $7E5006,x
    sta $7E5008,x
    sta $7E500A,x
    sta $7E500C,x
    sta $7E500E,x
    txa
    clc
    adc #$0010
    tax
    lda #$0000           ; TXA/ADC changed A; every unrolled block must still store zero
    cpx #$0800
    bne ohce_hash_loop
    stz $DE
    rts

obj_queue_prepare_extended:
    rep #$30
    lda #$0000
    sta $7E89C6          ; number of new code/slot pairs in this visual frame
    lda $7E8980          ; preserve obj_cache_prepare's original marker result
    rts

obj_slot_fast_full_reset_ext:
    rep #$30
    lda #$0001
    sta $7E89C8
    lda $DE
    sta $7E89CA
    lda $7E89C6
    sta $7E89CC
    jsr obj_hclr
    lda #$FFFF
    sta $7E8988
    lda #$A55A
    sta $7E8980
    lda #$0000
    sta $7E89CE
    pla                  ; discard obj_slot_fast's JSR return, retain saved P
    jmp vof_pal_cache_ready

video_boot_init_extended:
    jsr vid_init
    jmp boot_screen_init ; tail return reaches rc_copy through its existing JSR frame

; Keep rc_copy's near Tad_LoadSong call behind this fixed helper so boot-only
; sequencing can change without moving the production pacing islands.
video_boot_finish_extended:
    jsr Tad_LoadSong
    rts
obj_hash_helpers_end:

; The queue promoter cannot live anywhere in bank $7F: that whole bank is live
; emulated 68000 work RAM.  This pinned helper is already part of the ordinary
; $7F:8000-$AFFF mirror.  Empty queues take the original finish path; a completed
; queue reaches the private-$7E promoter, whose first producer installed it only
; after production pacing was active.
.org $A090
.a16
.i16
render_queue_finish:
    rep #$30
    lda $7E89D2
    bne rqf_promote
    lda $7E89D6
    bne rqf_promote
    lda #$0000
    sta $7E899C
    plp                  ; balance vf_tick's entry PHP
    rtl
rqf_promote:
    jml.l $7EED00

; Called from the ROM-hosted primary capture while arm=$0003 keeps the SA-1
; asleep.  $7E:ED00-$EFFF is private 5A22 WRAM between the compressed queue's
; true $ECA0 ceiling and the $F000 worker.  The copy is free of Bus-A contention,
; and the marker publishes only after every code word landed.
render_queue_install:
    rep #$30
    lda $7E89D8
    cmp #$C0DE
    beq rqi_done
    ldx #$0000
rqi_copy:
    lda $E9ED00,x
    sta $7EED00,x
    inx
    inx
    ; Do not use a forward label subtraction here.  Poppy encoded that as the
    ; absolute end address ($ED2A), causing an unbounded/destructive copy through
    ; bank $7F.  The ROM pack proves this pinned size against the final symbols.
    cpx #RENDER_QUEUE_CODE_BYTES
    bne rqi_copy
    lda #$C0DE
    sta $7E89D8
rqi_done:
    rts
render_queue_helpers_end:

; Keep the common renderer in its contention-free WRAM mirror.  Only the
; overloaded arcade title crosses into the ROM-hosted BG2 helper after the
; ordinary OBJ upload has completed and its converted palette is available.
.org $A0E0
.a16
.i16
obj_upload_title_dispatch:
    jsr obj_upload
    lda $7E89BE
    bpl outd_done
    jsl.l $E9B300
outd_done:
    rts
obj_upload_title_dispatch_end:

; Production NMI/WAI acquisition.  An idle renderer is given a direct cache
; image by pacing_snapshot_direct while the SA-1 is quiescent.  While rendering
; or while a direct image awaits its worker ACK, later NMIs retain complete
; candidates in the two compressed queue entries.  Input publication and SA-1
; wake still happen on schedule.  This makes the
; cache immutable without the former 6 KiB compare/copy seqlock, whose retries
; starved for dozens of game ticks once real level rendering exceeded two
; vblanks. $7E:899A is the completed-image generation and $7E:89A0 the last
; generation claimed by the renderer.
.org $A100
.a16
.i16
snapshot_acquire_paced:
    rep #$30
sal_read_generation:
    lda $7E899A
    bne sal_generation_nonzero
    jmp sal_generation_wait
sal_generation_nonzero:
    bit #$0001
    beq sal_generation_even
    jmp sal_generation_wait
sal_generation_even:
    cmp $7E89A0
    bne sal_generation_new
    jmp sal_generation_wait
sal_generation_new:
    sta $7E898E          ; candidate generation before claiming the single cache image
    lda #$0001
    sta $7E899C          ; NMI now skips cache replacement
    lda $7E899A
    cmp $7E898E
    bne sal_generation_retry
    bit #$0001
    bne sal_generation_retry
    sta $7E89A0          ; consume exactly this completed direct-cache generation
    jsr pacing_palette_cache_test
    lda $7E8986
    beq sal_palette_clean
    lda $7E89A8
    inc a
    sta $7E89A8          ; consumed palette-change count (measurement only)
sal_palette_clean:
    jsr pacing_bg_cache_test
    lda $7E8990
    beq sal_bg_clean
    lda $7E89AA
    inc a
    sta $7E89AA          ; consumed BG-change count (measurement only)
sal_bg_clean:
    lda #$0001
    sta $7E8992          ; OBJ remains conservatively dirty every accepted image
    lda $7E89AC
    inc a
    sta $7E89AC          ; consumed OBJ-change count (measurement only)
    lda $7E3408          ; direct cache: packed VOFS/scrollx word
    sta $7E8994
    lda $7E3604          ; direct D0 cache: raw $41:3604 control word
    sta $7E8996
    rts
sal_generation_retry:
    lda #$0000
    sta $7E899C
sal_generation_wait:
    ldx #$0080
sal_generation_delay:
    dex
    bne sal_generation_delay
    jmp sal_read_generation

; The SA-1 manifest builder compared this candidate with the last image whose
; complete DMA the 5A22 acknowledged.  Consume those exact results here instead
; of rescanning 3 KiB on the 3.58 MHz CPU.  NMI copied the manifest and raw image
; under the same arm=1 ownership interval, so these flags describe these caches.
.org $A1A0
.a16
.i16
pacing_palette_cache_test:
    rep #$30
    lda $7E89BE
    and #$0001
    sta $7E8986
    rts

.org $A1B0
.a16
.i16
; Apply the packed scroll word accepted with the current coherent image.
; TITLE_TEXT_META bit 15 identifies the exact post-TAITO title composition,
; whose column effects must retain the established zero vertical offset.
bg_scroll:
    jsr bg_hscroll
    php
    sep #$20
.a8
    lda $7E89BF
    bmi bgs_vertical_zero
    lda $7E8994
    sta BG1VOFS
    lda #$00
    sta BG1VOFS
    plp
    rts
bgs_vertical_zero:
    lda #$00
    sta BG1VOFS
    sta BG1VOFS
    plp
    rts
bg_scroll_end:
pacing_palette_cache_test_end:

.org $A1E8
pacing_bg_cache_test:
    rep #$30
    lda $7E89BC
    beq pbct_clean
    lda #$0001
    sta $7E8990
    rts
pbct_clean:
    sta $7E8990
    rts
pacing_bg_cache_test_end:

; Refine the incremental renderer's conservative one-slot-per-cell capacity
; bound without mutating the persistent cache.  This runs only when that cheap
; bound would otherwise reclaim.  Missing codes are deduplicated in private
; $7E:7D00 scratch, so carry is set iff the frame genuinely needs more slots
; than the sequential tail plus free list can supply.  Entry A=available slots;
; DBR remains $00 and all scratch registers/cells are dead before rendering.
.org $A220
.a16
.i16
bg_capacity_exact:
    rep #$30
    sta $D2                    ; available physical slots
    stz $D4                    ; unique-missing-list byte length
    ldy #$0000                 ; changed-cell-list byte cursor
bce_cell_loop:
    tya
    cmp $7E89BC
    beq bce_fit
    tax
    lda $7E8C00,x
    tax
    lda $7E2000,x
    xba
    and #$3FFF
    beq bce_next_cell
    sta $E4
    asl a
    clc
    adc $E4                    ; odd *3 permutes adjacent 9-bit home buckets
    and #$01FF
    asl a
    sta $D8
bce_hash_probe:
    ldx $D8
    lda $7EA000,x
    beq bce_missing_search
    cmp $E4
    beq bce_next_cell
    inx
    inx
    txa
    and #$03FF
    sta $D8
    bra bce_hash_probe
bce_missing_search:
    ldx #$0000
bce_missing_loop:
    cpx $D4
    beq bce_missing_new
    lda $7E7D00,x
    cmp $E4
    beq bce_next_cell
    inx
    inx
    bra bce_missing_loop
bce_missing_new:
    txa
    lsr a
    cmp $D2
    bcs bce_overflow           ; adding this unique code exceeds capacity
    lda $E4
    sta $7E7D00,x
    inx
    inx
    stx $D4
bce_next_cell:
    iny
    iny
    bra bce_cell_loop
bce_fit:
    clc
    rts
bce_overflow:
    sec
    rts
bg_capacity_exact_end:

; Keep the persistent BG ownership reset outside the tightly packed $A800
; reclaimer.  Poppy permits backwards .org sections and silently overwrites on
; overlap, so this helper owns an explicitly guarded island before $A300.
.org $A290
.a16
.i16
bg_cache_reset_counts:
    rep #$30
    lda #$0000
    ldx #$0000
bcrc_reverse_clear:
    sta $7ED000,x
    inx
    inx
    cpx #$0180
    bne bcrc_reverse_clear
    stz $DC
    sta $7E89C2
    lda #$B7C4
    sta $7E89D0
    rts
bg_cache_reset_counts_end:

; A complete 5A22 capture atomically accepts the current producer touch set.
; Call with A=0 in the same WRAM execution bank; the JSR+NOP replaces the old
; four-byte `sta $410140` at each packed acceptance seam without moving code.
.org $A2D0
.a16
.i16
producer_touch_reset:
    sta $410140
    sta $41014C
    sta $41014E
    rts
producer_touch_reset_end:

; Channel-7 DMA one stable SA-1 shadow image directly into the renderer's
; established cache addresses.  Runs only from pacing_try_wake with the SA-1
; asleep and renderer idle.  Splitting E0 at +$0800 preserves the old BG cache
; addresses, so the pre-pacing snapshot path and all render code stay valid.
.org $A300
.a16
.i16
pacing_snapshot_direct:
    rep #$30
    lda $7E899A
    and #$FFFE
    inc a
    sta $7E899A          ; odd until every conditional snapshot transfer completes

    ; Latch the compact manifest metadata before any DMA.  The SA-1 published
    ; it before arm=1 and remains asleep until this routine returns.
    lda $410132
    sta $7E89B8          ; candidate sequence represented by this cache image
    lda $410138
    sta $7E89BA          ; OBJ manifest format flag + byte length
    lda $41013A
    sta $7E89BC          ; BG-list byte length, or $FFFF for a full rebuild
    lda $41013C
    sta $7E89BE          ; exact palette dirty result
    lda $410146
    sta $7E89C4          ; prepared unique-code byte length (only for $FFFE)

    sep #$20
    stz $4370            ; channel 7: mode 0, increment A-bus source
    lda #$80
    sta $4371            ; B-bus destination $2180 (WRAM data port)
    lda #$41
    sta $4374            ; stable SA-1 BW-RAM shadow source bank
    stz $2183            ; destination bank $7E

    rep #$30
    jsr psd_palette_dma
    lda $7E89BA
    bpl psd_obj_raw_planes
    lda $410128
    cmp #$CA02
    bne psd_obj_planes_done ; ordinary packed records replace both raw OBJ DMAs
psd_obj_raw_planes:
    ldx #$3000
    ldy #$3000
    lda #$0800
    jsr pacing_snapshot_dma
    ldx #$4000
    ldy #$4000
    lda #$0800
    jsr pacing_snapshot_dma

    ; A full $00158E transfer was captured at its exact call instant while the
    ; SA-1 slept. Overlay only the three architected 1020-byte interiors; the
    ; surrounding control/boundary bytes remain from the coherent live-shadow
    ; copies above. Short $0017B4 and interpreted fallback paths leave no
    ; $CA02 token and retain their ordinary live-shadow representation.
    lda $410128
    cmp #$CA02
    bne psd_obj_overlay_done
    sep #$20
    lda #$7F
    sta $4374
    rep #$30
    ldx #PACED_OBJ_Y
    ldy #$3002
    lda #$03FC
    jsr pacing_snapshot_dma
    ldx #PACED_OBJ_CODE
    ldy #$4002
    lda #$03FC
    jsr pacing_snapshot_dma
    ldx #PACED_OBJ_X
    ldy #$4402
    lda #$03FC
    jsr pacing_snapshot_dma
psd_obj_overlay_done:
psd_obj_planes_done:
    ; The old $3000-$37FF raw transfer also carried these non-OBJ control
    ; words.  Preserve them explicitly when packed records skip that plane.
    jsr capture_bg_vscroll
    sta $7E3408
    nop
    lda $413604
    sta $7E3604
    sep #$20
    lda #$41
    sta $4374
    rep #$30
    jsr psd_bg_dma

    ; Copy only the producer-published manifest bytes.  The old fixed maximum
    ; transfers moved 1.25 KiB even when BG was unchanged and the OBJ list was
    ; short; the helper also avoids SNES DMA's zero-length == 64 KiB trap.
    jsr psd_manifest_dma

    ; Acknowledge only after every raw plane and both compact lists are private.
    ; The next SA-1 boundary may now promote this candidate as its comparison
    ; baseline; a dropped/busy snapshot never reaches this store.
    lda $7E89B8
    sta $410134
    lda #$0000
    sta $41013E          ; consume cumulative producer dirty flags atomically
    jsr producer_touch_reset
    nop                  ; size-neutral replacement for the old long STA

    lda $7E899A
    inc a
    bne psd_generation_done
    lda #$0002           ; zero remains reserved for no completed image
psd_generation_done:
    sta $7E899A
    rts

pacing_snapshot_dma:    ; X=BW-RAM source, Y=WRAM destination, A=byte length
    stx $4372
    sty $2181
    sta $4375
    sep #$20
    lda #$80
    sta $420B
    rep #$30
    rts
pacing_snapshot_direct_end:

; Production OBJ transform.  The reference path at $8189 remains available to
; TESTFLAG=2 and as the cache-overflow recovery target.  This version preserves
; its visible selection/order, palette/tile helpers, and exact OAM bytes while
; removing the most expensive per-frame initialization and coordinate work.
; It lives in the extended $7F WRAM mirror so its instruction fetches remain
; disjoint from the SA-1 bus.
.org $A400
.a16
.i16
vid_obj_fast:
    php
    rep #$30
    lda $7E89C0
    cmp #$B17E
    beq vof_pal_cache_ready
    lda #$FFFF
    ldx #$0000
vof_pal_cache_init:
    sta $7E2C00,x
    inx
    inx
    cpx #$0008
    bne vof_pal_cache_init
    lda #$B17E
    sta $7E89C0
vof_pal_cache_ready:
    lda #$FFFF
    ldx #$0000
vof_bank_clear:
    sta $7E8580,x        ; two bank->palette entries per store
    inx
    inx
    cpx #$0020
    bne vof_bank_clear
    lda #$0000
    ldx #$0000
vof_hi_clear:
    sta $7E8800,x        ; exact zero high table; active pairs are ORed below
    inx
    inx
    cpx #$0020
    bne vof_hi_clear
    jsr obj_fast_prepare
    stz $E0              ; compact-list byte cursor
    stz $E2              ; compact OAM entry count
    stz $E6              ; palette-slot count
    lda $7E89BA          ; legacy offset bytes, or bit-15-tagged packed records
    beq vof_done
    bpl vof_loop
    jmp vid_obj_packed

vof_loop:
    ldx $E0
    lda $7EBC00,x
    sta $F4              ; source byte offset in each raw OBJ plane
    tax
    lda $7E4000,x
    xba
    sta $F6              ; logical arcade code/flip word
    and #$3FFF
    beq vof_next
    lda $F6
    cmp #$FFFF
    beq vof_next

    ldx $F4
    lda $7E4400,x
    xba
    sta $E8              ; logical arcade X/palette word
    lda $7E3000,x
    xba
    and #$00FF           ; arcade low Y byte
    sta $EC

    lda $E8
    and #$01FF
    ; X1-001 draws the signed coordinate in both 512px buckets.  The producer
    ; retained raw $031-$13F, so raw $100-$13F is the visible wrapped-right
    ; interval at arcade X=256..319, not an offscreen negative coordinate.
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
vof_sx_ready:
    sec
    sbc #$0040           ; centered crop: SNES X = arcade X - 64
    sta $EA
    nop                  ; preserve the established downstream helper address
vof_x_visible:
    lda $E8
    xba
    lsr a
    lsr a
    lsr a
    and #$001F
    sta $EE
    jsr obj_palslot
    lda $F6
    and #$3FFF
    sta $C4
    jsr obj_slot_fast
    jsr obj_oam_fast
    inc $E2
    lda $E2
    cmp #$0080
    beq vof_done
vof_next:
    lda $E0
    inc a
    inc a
    sta $E0
    cmp $7E89BA
    bne vof_loop

vof_done:
    jsr obj_hide_tail_fast
    jsr obj_upload_title_dispatch
    plp
    rts

; Write one exact four-byte low-OAM entry plus its two high-table bits.
obj_oam_fast:
    rep #$30
    lda $E2
    asl a
    asl a
    tax
    lda $EA
    and #$00FF
    sta $F2
    lda $EC
    clc
    adc #$000E
    and #$00FF
    eor #$00FF
    inc a                ; 256 - (sy + 14)
    sec
    sbc #$0018           ; 240-line correction + centered Y=8 crop = -24
    and #$00FF           ; retain SNES/X1-001 top-edge coordinate wrap
oof_y_ready:
    xba
    ora $F2
    sta $7E8600,x        ; X low, Y

    lda $F0
    asl a
    ora #$0030
    sta $F2
    lda $E4
    xba
    and #$0001
    ora $F2
    sta $F2
    lda $F6
    and #$8000
    beq oof_no_xflip
    lda $F2
    ora #$0040
    sta $F2
oof_no_xflip:
    lda $F6
    and #$4000
    beq oof_no_yflip
    lda $F2
    ora #$0080
    sta $F2
oof_no_yflip:
    lda $F2
    xba
    sta $F2
    lda $E4
    and #$00FF
    ora $F2
    sta $7E8602,x        ; tile low, attributes

    lda $E2
    and #$0003
    asl a
    tay                  ; pair shift = (n & 3) * 2
    lda $EA
    bpl oof_pair_positive
    lda #$0003           ; size=large plus negative-X high bit
    bra oof_pair_shift
oof_pair_positive:
    lda #$0002           ; size=large, positive X
oof_pair_shift:
    cpy #$0000
    beq oof_pair_ready
    asl a
    dey
    bra oof_pair_shift
oof_pair_ready:
    sta $F2
    lda $E2
    lsr a
    lsr a
    tax
    sep #$20
.a8
    lda $7E8800,x
    ora $F2
    sta $7E8800,x
    rep #$30
.a16
    rts
obj_oam_fast_end:

; The reference path zeroes all 128 low entries and then writes Y=$F0.  Active
; entries are already fully replaced, so reproduce those exact bytes only for
; the unused tail instead of clearing 544 bytes plus a second 128-entry loop.
.org $A570
obj_hide_tail_fast:
    rep #$30
    lda $7E89B2          ; previous completed frame's active-entry count
    bne ohf_previous_ready
    lda #$0080           ; first frame (or empty predecessor): hide the complete tail
ohf_previous_ready:
    sec
    sbc $E2
    beq ohf_done
    bcc ohf_done         ; a growing prefix overwrites every newly exposed entry
    sta $F2              ; only the shrinking suffix can still contain visible OAM
    lda $E2
    asl a
    asl a
    tax
    jmp ohf_dynamic_loop
ohf_done:
    rts

; Preserve the reference renderer's per-frame first-use slot assignment, but
; reconvert a 16-color OBJ palette only when that slot's bank changed or the
; raw arcade palette plane changed.  Stable combat frames otherwise retained
; and reconverted the same four or five banks on every visual update.
.org $A593              ; retain the palette-cache and every later established entry
obj_pal_fill_cached:
    rep #$30
    lda $F0
    and #$00FF
    tax
    sep #$20
.a8
    lda $7E2C00,x
    cmp $EE
    bne opfc_refresh
    lda $7E8986
    bne opfc_refresh
    rep #$20
.a16
    rts
opfc_refresh:
    lda $EE
    sta $7E2C00,x
    rep #$20
.a16
    jsr obj_pal_fill
    rts

; The live renderer owns CGRAM through its persistent BG/OBJ bank-to-slot
; maps. A full ppu_build immediately before those mapped fills only writes
; colors that are either overwritten or unreachable by the active tilemaps.
; Retain it during boot, before the scheduler/render mappings exist.
ppu_build_mapped:
    rep #$30
    lda $400002
    and #$0300
    cmp #$0300
    beq pbm_done
    lda $7E8986
    beq pbm_done
    jmp ppu_build
pbm_done:
    rts

; Incremental BG updates may touch only a subset of the palette banks already
; referenced by the retained tilemap. Refresh the small complete mapped set
; when raw colors changed, then preserve the original scroll tail call.
bg_incremental_finish:
    rep #$30
    lda $7E8986
    beq bif_scroll
    jsr bg_refresh_pal
bif_scroll:
    jmp bg_scroll

; Finish obj_hide_tail_fast in the former zero seam.  Low OAM is persistent:
; entries above the previous active prefix are already exactly
; $00,$F0,$00,$00, so rewriting only prev_count-current_count preserves every
; byte while avoiding the stable frame's full 128-entry tail walk.
.org $A5E0
ohf_dynamic_loop:
    lda #$F000
    sta $7E8600,x
    lda #$0000
    sta $7E8602,x
    inx
    inx
    inx
    inx
    dec $F2
    bne ohf_dynamic_loop
    rts
vid_obj_fast_end:

; Conditional direct-snapshot transfers.  These run only while pacing_try_wake
; owns arm=$0003 and the SA-1 is asleep, with channel 7 already configured for
; $41 -> $7E WRAM-port DMA.  Persistent caches make unchanged palette/BG planes
; safe to retain; compact lists are transferred at their exact published sizes.
.org $A600
.a16
.i16
psd_palette_dma:
    rep #$30
    lda $7E89BE
    beq psd_palette_done
    ldx #$2000
    ldy #$2800
    lda #$0400
    jsr pacing_snapshot_dma
psd_palette_done:
    rts

psd_bg_dma:
    rep #$30
    lda $7E89BC
    beq psd_bg_done
    cmp #$FFFE
    beq psd_bg_done      ; prepared full image needs no raw plane until a later diff
    ldx #$4800
    ldy #$2000
    lda #$0800
    jsr pacing_snapshot_dma
psd_bg_done:
    rts

psd_manifest_dma:
    rep #$30
    lda $7E89BA
    beq psd_bg_list
    bpl psd_obj_manifest_dma
    and #$7FFF
    beq psd_bg_list
psd_obj_manifest_dma:
    ldx #MANIFEST_OBJ_LIST
    ldy #MANIFEST_OBJ_CACHE
    jsr pacing_snapshot_dma
psd_bg_list:
    lda $7E89BC
    beq psd_manifest_done
    cmp #$FFFE
    beq psd_prepared_manifest
    cmp #$FFFF
    beq psd_manifest_done
    ldx #MANIFEST_BG_LIST
    ldy #$8C00
    jsr pacing_snapshot_dma
    bra psd_manifest_done
psd_prepared_manifest:
    jsr psd_prepared_dma
psd_manifest_done:
    rts
psd_manifest_dma_end:

; =============================================================================
; Incremental BG renderer for a producer-unique list of changed arcade cells.
;
; The first image or a palette-map overflow retains vid_bg_heavy.  Ordinary
; animation/scroll updates touch only the four
; SNES tilemap entries derived from each changed 16x16 arcade cell, then issue
; one 4 KiB tilemap DMA.  Persistent tile and palette maps remain authoritative.
; This island must end below the fixed $A800 cache-reclamation island.
; =============================================================================
.org $A680
.a16
.i16
vid_bg_incremental:
    rep #$30

    ; Worst-case one new tile per changed cell.  If the sequential tail plus
    ; already-reclaimed slots cannot cover that bound, prepare the complete
    ; changed-cell union before processing its first entry.  Preparation must
    ; happen here, not lazily inside bg_slot: clearing an entry after its cell
    ; was already processed would strand that finished cell as blank.
    lda $7E89BC
    lsr a
    sta $D0              ; conservative slots required by this unique list
    lda #$00C0
    sec
    sbc $DC              ; never-used sequential slots
    clc
    adc $7E89C2          ; plus slots reclaimed by an earlier preparation
    cmp $D0
    bcs vbi_capacity_ready
    ; Animation often changes dozens of cells to only a handful of genuinely
    ; new codes.  Count those unique cache misses without changing allocation
    ; state; reclaim only for an actual physical-slot shortfall.
    jsr bg_capacity_exact
    bcc vbi_capacity_ready
    jsr bg_cache_reclaim
vbi_capacity_ready:

    ; OBJ rendering reuses $E6, so reconstruct the next BG palette slot from
    ; the persistent bank->slot table before processing changed cells.
    stz $E6
    stz $F0              ; bg_palslot writes only its low byte on a cache hit
    ldx #$0000
vbi_palette_scan:
    sep #$20
.a8
    lda $7E8940,x
    cmp #$FF
    beq vbi_palette_next8
    rep #$20
.a16
    and #$00FF
    inc a
    cmp $E6
    bcc vbi_palette_next16
    sta $E6
    bra vbi_palette_next16
vbi_palette_next8:
    rep #$20
.a16
vbi_palette_next16:
    inx
    cpx #$0020
    bne vbi_palette_scan

    ldy #$0000
vbi_list_loop:
    ; CPY likewise has no long form.  Compare through A, then reuse that same
    ; cursor value as the true long,X list index below.
    tya
    cmp $7E89BC
    beq vbi_upload
    ; 65816 has no long,Y load.  Transfer the compact-list cursor to X so
    ; Poppy emits the real long,X form; an absolute,Y encoding would silently
    ; read $00:8C00 (ROM) because the video supervisor runs with DBR=$00.
    tax
    lda $7E8C00,x
    sta $E0              ; source byte offset shared by BG code/color planes
    phy                   ; tile/palette/decode helpers freely use Y
    jsr bg_incremental_cell
    ply
    bcs vbi_full_fallback
    iny
    iny
    bra vbi_list_loop
vbi_upload:
    jsr bg_upload
    clc
    rts
vbi_full_fallback:
    sec
    rts

bg_incremental_cell:
    rep #$30
    ldx $E0
    lda $7E2000,x
    xba
    sta $F6
    and #$3FFF
    beq bic_empty
    sta $E4
    lda $7E2400,x
    xba
    sta $E8
    jsr bg_slot
    bcc bic_slot_ready
    jmp bic_overflow     ; only possible if all 192 slots are simultaneously live
bic_slot_ready:

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
    tax
    sep #$20
.a8
    lda $7E8940,x
    cmp #$FF
    bne bic_palette_known8
    rep #$20
.a16
    lda $E6
    cmp #$0008
    bcc bic_palette_ready
    jmp bic_overflow
bic_palette_known8:
    rep #$20
.a16
bic_palette_ready:
    jsr bg_palslot
    lda $DA
    asl a
    asl a
    sta $F8
    bra bic_coordinates

bic_empty:
    stz $F0
    stz $F6
    stz $F8

bic_coordinates:
    ; Build the common tile attributes once.  bg_ent formerly repeated this
    ; palette/flip work and the full map-index calculation for all four quads.
    lda $F0
    and #$00FF
    asl a
    asl a
    xba
    and #$1C00
    sta $FA
    lda $F6
    and #$8000           ; arcade X flip becomes SNES tilemap bit 14
    beq bic_no_xflip
    lda $FA
    ora #$4000
    sta $FA
bic_no_xflip:
    lda $F6
    and #$4000           ; arcade Y flip becomes SNES tilemap bit 15
    beq bic_no_yflip
    lda $FA
    ora #$8000
    sta $FA
bic_no_yflip:
    lda $F8
    and #$03FF
    ora $FA
    sta $FA              ; complete top-left entry; other quads are +1/+2/+3

    ; The mapping is immutable, so vid_init computes it once.  Indexing by the
    ; source byte offset preserves exact parity with vid_bg_heavy while removing
    ; dozens of shifts/branches from every changed cell.
    ldx $E0
    lda $7E7500,x
    sta $D0
    clc
    adc #$0002           ; top-right is adjacent; TL is always an even tile x
    sta $D2

    ldx $D0
    lda $FA
    sta $7E9000,x        ; top-left
    inc a
    ldx $D2
    sta $7E9000,x        ; top-right
    lda $D0
    clc
    adc #$0040
    tax
    lda $FA
    clc
    adc #$0002
    sta $7E9000,x        ; bottom-left
    lda $D2
    clc
    adc #$0040
    tax
    lda $FA
    clc
    adc #$0003
    sta $7E9000,x        ; bottom-right
    clc
    rts
bic_overflow:
    sec
    rts

; X1-001 exposes independent vertical scroll for each 32-pixel column, while
; the SNES BG1 register is global. Stage 2 uses several simultaneous values, so
; follow column 4 from the center playfield group; returning zero when columns
; disagree would recreate the reported frozen camera. The exact title
; composition is held at zero by bg_scroll's signature guard. The returned
; word is deliberately packed so the established two-byte scroll mailbox
; needs no growth:
;   low byte  = BG1VOFS = (scrolly + noflip yoffs(-1) + crop 8) & $FF,
;   high byte = raw low byte of scrollx[0], consumed by bg_hscroll
; This helper runs either from ROM while the SA-1 is asleep or from the
; matching $7F mirror and preserves P.
.org $A7BC
.a16
.i16
capture_bg_vscroll:
    php
    sep #$20
.a8
    lda $413409
    xba                         ; retain scrollx in B
    lda $413481                 ; representative center-playfield column 4
    clc
    adc #$07                   ; X1 noflip yoffs=-1 plus centered crop y=8
    rep #$20                   ; B:scrollx + A:vofs -> packed 16-bit word
.a16
    plp
    rts
capture_bg_vscroll_end:
vid_bg_incremental_end:

; =============================================================================
; Bounded persistent-BG cache reclamation.
;
; The old allocator accumulated codes across scene animation and, at 192 slots,
; cleared the complete hash and decoded the whole visible level again.  The
; measured result was a 678K-cycle / 16-video-frame renderer stall.  The live
; tilemap already identifies exactly which decoded slots remain observable.
; Before allocation begins, clear the union of tilemap words covered by the
; producer's unique change list, scan the retained map, tombstone only the
; now-unreferenced hash entries, and recycle their slot bytes.  Clearing the
; complete union is load-bearing at scene transitions: the old and new screen
; can jointly exceed 192 codes even though either visible image fits easily.
; (The earlier half-scale incremental coordinate bug made adjacent cells overlap;
; the mapping below now matches vid_bg_heavy exactly.)  Open-addressing
; lookup remembers the first tombstone but continues to
; an empty entry before insertion, so a colliding live code can never be hidden
; or duplicated.  Incremental preflight calls reclamation only when the changed
; list's conservative one-new-slot-per-cell bound exceeds the currently available
; pool; its scan cost is bounded and amortized across every slot it recovers.
; =============================================================================
.org $A800
.a16
.i16
bg_slot_extended:
    rep #$30
    lda #$FFFF
    sta $C6              ; first tombstone in this code's probe chain
    lda $E4
bg_hash_mul3_marker:
    asl a
    clc
    adc $E4              ; hash = (code * 3) & $1FF
    and #$01FF           ; odd multiply preserves the 512-bucket permutation
    asl a                ; word index *2
    sta $D8
bse_probe:
    ldx $D8
    lda $7EA000,x
    beq bse_insert
    cmp #$FFFF
    beq bse_tombstone
    cmp $E4
    beq bse_hit
bse_next:
    inx
    inx
    txa
    and #$03FF           ; wrap 512-word hash table
    sta $D8
    bra bse_probe
bse_tombstone:
    lda $C6
    cmp #$FFFF
    bne bse_next
    stx $C6
    bra bse_next
bse_hit:
    lda $7EA400,x
    sta $DA
    clc
    rts

bse_insert:
    lda $DC
    cmp #$00C0
    bcc bse_sequential
    lda $7E89C2
    bne bse_reuse
    bra bse_no_slot      ; frame preparation proved no recyclable slot remains
bse_reuse:
    dec a
    sta $7E89C2
    tax
    sep #$20
.a8
    lda $7E7C00,x
    rep #$20
.a16
    and #$00FF
    sta $DA
    bra bse_store
bse_sequential:
    sta $DA              ; A == old $DC == next never-used slot
    inc $DC
bse_store:
    lda $C6
    cmp #$FFFF
    beq bse_store_empty
    tax                  ; recycle the first tombstone in this probe chain
    bra bse_store_indexed
bse_store_empty:
    ldx $D8
bse_store_indexed:
    lda $E4
    sta $7EA000,x
    lda $DA
    sta $7EA400,x
    asl a
    tax
    lda $E4
    sta $7ED000,x        ; reverse ownership makes reclamation a 192-slot scan
    lda $E4
    sta $C4
    ; bg_tile_dma's production entry jumps to bg_tile_dma_direct, which reads
    ; this same native 128-byte record from ROM.  The old decode_tile call only
    ; copied it to $7E:8400; no BG caller consumes that scratch image anymore.
    nop
    nop
    nop
    jsr bg_tile_dma
    clc
    rts
bse_no_slot:
    stz $DA
    sec
    rts

bg_cache_reclaim:
    php
    rep #$30
    pha
    phx
    phy
    phb
    sep #$20
.a8
    lda #$7E
    pha
    plb                  ; compact absolute indexed loops below address 5A22 WRAM
    rep #$30
.a16

    ; Clear the exact union of tilemap words that this frame will rebuild.
    ; Overlaps are deliberately harmless: repeated STZ is idempotent, unlike
    ; subtracting per-cell reference counts from shared quadrant words.
    ldy #$0000
bcr_clear_changed:
    tya
    cmp $7E89BC
    beq bcr_changed_done
    tax
    lda $7E8C00,x        ; arcade BG cell byte offset
    tax
    lda $7500,x          ; DBR=$7E: exact precomputed top-left map byte offset
    sta $D0              ; top-left byte offset
    clc
    adc #$0002
    sta $D2              ; top-right
    ldx $D0
    stz $9000,x
    lda $D0
    clc
    adc #$0040
    tax
    stz $9000,x
    ldx $D2
    stz $9000,x
    lda $D2
    clc
    adc #$0040
    tax
    stz $9000,x
    iny
    iny
    jmp bcr_clear_changed
bcr_changed_done:

    ; Eight word stores per branch cut this bounded 192-byte clear from 96
    ; loop branches to 12.  STZ keeps A free for the 16-byte X advance.
    ldx #$0000
bcr_clear_used:
    stz $2E00,x          ; two one-byte slot marks per store
    stz $2E02,x
    stz $2E04,x
    stz $2E06,x
    stz $2E08,x
    stz $2E0A,x
    stz $2E0C,x
    stz $2E0E,x
    txa
    clc
    adc #$0010
    tax
    cpx #$00C0
    bne bcr_clear_used

    ; Each arcade cell owns four SNES quadrant words and every quadrant's tile
    ; number resolves to the same physical slot.  The immutable 512-entry
    ; offset table therefore lets one top-left read per cell recover the exact
    ; live-slot set; scanning all 2,048 tilemap words was fourfold redundant.
    ldx #$0000
bcr_scan_tilemap:
    lda $7500,x
    tay
    lda $9000,y
    and #$03FF           ; SNES tile number = slot*4 + quadrant
    lsr a
    lsr a
    tay
    sep #$20
.a8
    lda #$01
    sta $2E00,y
    rep #$20
.a16
    inx
    inx
    cpx #$0400           ; one representative for each of 512 arcade cells
    bne bcr_scan_tilemap

    ; Retain the exact live code/physical-slot pairs.  The previous version
    ; tombstoned stale entries in place.  Repeated scene animation eventually
    ; left more than a hundred tombstones in the 512-entry table, turning an
    ; ordinary hit into a measured 42-probe average (113 worst case).  $7900 is
    ; the prepared-full code list, mutually exclusive scratch on this
    ; incremental path; $7D00 is otherwise-unused scratch for the parallel
    ; physical slots.  The persistent slot->code reverse map reduces this from
    ; 512 hash buckets to the 192 physical slots without changing pair order or
    ; the clean-table rebuild.  Keeping $7C00 exclusively as the BG free list
    ; prevents OBJ's later $2D00 upload queue from corrupting allocator state.
    ldx #$0000
    ldy $89C2            ; existing free-list count
    stz $D6              ; retained-pair count
bcr_collect_slots:
    stx $D2              ; physical slot index
    txa
    asl a
    tax
    lda $D000,x
    beq bcr_collect_next
    sta $D0              ; retained code
    ldx $D2
    sep #$20
.a8
    lda $2E00,x
    beq bcr_collect_unused8
    rep #$20
.a16
    lda $D6
    asl a
    tax
    lda $D0
    sta $7900,x          ; retained code word
    ldx $D6
    sep #$20
.a8
    lda $D2
    sta $7D00,x          ; parallel retained physical-slot byte
    rep #$20
.a16
    inc $D6
    bra bcr_collect_next
bcr_collect_unused8:
    lda $D2
    sta $7C00,y          ; append in the old hash-scan order (DBR=$7E)
    rep #$20
.a16
    iny
    lda $D2
    asl a
    tax
    stz $D000,x          ; the physical slot is now owned by the free list
bcr_collect_next:
    ldx $D2
    inx
    cpx #$00C0
    bne bcr_collect_slots
    tya
    sta $89C2            ; exact prior entries followed by newly freed slots

    ; Rebuild a clean zero-terminated table.  Physical slots never move, so
    ; the currently visible tilemap and VRAM contents remain authoritative.
    ; The code table is exactly $400 bytes.  Eight indexed STZ stores per
    ; branch avoid spending most of a rare reclaim on 512 loop branches.
    ldx #$0000
bcr_hash_clear:
    stz $A000,x
    stz $A002,x
    stz $A004,x
    stz $A006,x
    stz $A008,x
    stz $A00A,x
    stz $A00C,x
    stz $A00E,x
    txa
    clc
    adc #$0010
    tax
    cpx #$0400
    bne bcr_hash_clear
    ldy #$0000
bcr_rehash_loop:
    cpy $D6
    beq bcr_rehash_done
    tya
    asl a
    tax
    lda $7900,x
    sta $E4
    asl a
    clc
    adc $E4
    and #$01FF
    asl a
    sta $D8
bcr_rehash_probe:
    ldx $D8
    lda $A000,x
    beq bcr_rehash_store
    inx
    inx
    txa
    and #$03FF
    sta $D8
    bra bcr_rehash_probe
bcr_rehash_store:
    lda $E4
    sta $A000,x
    stx $D4
    sep #$20
.a8
    lda $7D00,y
    rep #$20
.a16
    and #$00FF
    ldx $D4
    sta $A400,x
    iny
    bra bcr_rehash_loop
bcr_rehash_done:

    plb
    ply
    plx
    pla
    plp
    rts
bg_cache_reclaim_end:

; Build the immutable lookup once during vid_init.  Table index is the source
; cell byte offset (2*(column*32+offset)); value is the top-left byte offset in
; the SNES 64x32 BG map split across two 32x32 nametables.
.org $AA00
.a16
.i16
bg_offset_table_init:
    rep #$30
    stz $D0              ; source column 0..15
    ldx #$0000           ; table byte offset
boti_column:
    stz $D2              ; source offset 0..31
boti_offset:
    lda $D2
    and #$001E
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta $D4              ; vertical byte offset = (offset & ~1) * 64
    lda $D0
    asl a
    asl a
    asl a
    sta $D6              ; raw x byte offset = column * 8
    lda $D2
    and #$0001
    asl a
    asl a
    clc
    adc $D6              ; odd source cell adds two SNES tiles = four bytes
    sta $D6
    and #$0040
    beq boti_left_nt
    lda $D6
    and #$003F
    clc
    adc #$0800           ; columns 8-15 select nametable 1
    sta $D6
boti_left_nt:
    lda $D6
    clc
    adc $D4
    sta $7E7500,x
    inx
    inx
    lda $D2
    inc a
    sta $D2
    cmp #$0020
    bne boti_offset
    lda $D0
    inc a
    sta $D0
    cmp #$0010
    bne boti_column
    lda #$0000           ; restore vid_init's zero-fill accumulator contract
    rts

; Direct immutable-tile upload.  $E4 is the 14-bit arcade code and $DA the
; destination BG slot.  Native tile records are packed at $C9:0000+code*128;
; 128-byte alignment guarantees no individual DMA crosses a ROM bank.
bg_tile_dma_direct:
    php
    rep #$30
    lda $E4
    sta $D0
    stz $D2
    ldy #$0007
btd_shift:
    asl $D0
    rol $D2
    dey
    bne btd_shift
    lda $D2
    clc
    adc #$00C9
    sta $D2              ; $D0/$D1 address, $D2 low byte source bank
    lda $DA
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$1000
    sta $D4              ; destination VRAM word
    sep #$20
.a8
    lda #$80
    sta VMAIN
    lda $D4
    sta VMADDL
    lda $D5
    sta VMADDH
    lda #$01
    sta DMAP0
    lda #$18
    sta BBAD0
    lda $D0
    sta A1T0L
    lda $D1
    sta A1T0H
    lda $D2
    sta A1B0
    lda #$80
    sta DAS0L
    stz DAS0H
    jsr dma0_blank_pulse
    plp
    rts

; Snapshot the producer-prepared representation while the SA-1 is asleep.
; Channel 7 is already configured for stable bank-$41 -> $7E WRAM-port DMA.
psd_prepared_dma:
    rep #$30
    ldx #$8000
    ldy #$9000
    lda #$1000
    jsr pacing_snapshot_dma ; complete producer-built 64x32 SNES tilemap
    lda $7E89C4
    beq ppd_palette_map
    ldx #$9000
    ldy #$7900
    jsr pacing_snapshot_dma ; deterministic unique 14-bit code list
ppd_palette_map:
    ldx #$9200
    ldy #$8940
    lda #$0020
    jsr pacing_snapshot_dma ; arcade palette-bank -> SNES BG palette slot
    rts

; Consume a producer-prepared full image.  The ready map is already private in
; BGMAP, and the sorted code list defines the exact slots embedded in it.
; Consecutive codes share one DMA run.
bg_dispatch_prepared:
    jsr bg_prepared_render
    plp                  ; balance bg_dispatch's entry PHP
    rts

bg_prepared_render:
    rep #$30
    jsr bg_hclr
    jsr bg_refresh_pal

    ; Populate the persistent code hash without uploading yet.  Y/2 is both
    ; sorted-list index and the tile slot used in every prepared map entry.
    ldy #$0000
bpr_hash_loop:
    tya
    cmp $7E89C4
    beq bpr_hash_done
    tax
    lda $7E7900,x
    and #$3FFF
    sta $E4
    asl a
    clc
    adc $E4
    and #$01FF
    asl a
    sta $D8
bpr_hash_probe:
    ldx $D8
    lda $7EA000,x
    beq bpr_hash_store
    inx
    inx
    txa
    and #$03FF
    sta $D8
    bra bpr_hash_probe
bpr_hash_store:
    lda $E4
    sta $7EA000,x
    tya
    lsr a
    sta $7EA400,x
    tyx
    lda $E4
    sta $7ED000,x        ; Y is already two bytes per physical prepared slot
    iny
    iny
    bra bpr_hash_loop
bpr_hash_done:
    lda $7E89C4
    lsr a
    sta $DC

    ; Coalesce adjacent source codes/slots.  Stop at each 64 KiB ROM-bank seam
    ; because SNES DMA wraps its 16-bit source address within the current bank.
    ldy #$0000
bpr_run_outer:
    tya
    cmp $7E89C4
    beq bpr_upload
    tax
    lda $7E7900,x
    sta $E4              ; first code in run
    tya
    lsr a
    sta $DA              ; first destination slot
    lda #$0001
    sta $E6              ; run length in 128-byte records
    iny
    iny
bpr_run_extend:
    tya
    cmp $7E89C4
    beq bpr_run_emit
    tax
    lda $7E7900,x
    sta $C4
    lda $E4
    clc
    adc $E6
    cmp $C4
    bne bpr_run_emit
    lda $C4
    and #$01FF
    beq bpr_run_emit     ; next record begins a new source ROM bank
    inc $E6
    iny
    iny
    bra bpr_run_extend
bpr_run_emit:
    phy
    jsr bg_tile_run_dma
    ply
    bra bpr_run_outer
bpr_upload:
    jsr bg_upload
    rts

; Upload E6 consecutive native 128-byte records beginning at code E4 to
; consecutive BG slots beginning at DA.  The caller already split ROM seams.
bg_tile_run_dma:
    php
    rep #$30
    lda $E6
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta $D6              ; DMA byte length = records * 128
    lda $E4
    sta $D0
    stz $D2
    ldy #$0007
btr_shift:
    asl $D0
    rol $D2
    dey
    bne btr_shift
    lda $D2
    clc
    adc #$00C9
    sta $D2
    lda $DA
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$1000
    sta $D4
    sep #$20
.a8
    lda #$80
    sta VMAIN
    lda $D4
    sta VMADDL
    lda $D5
    sta VMADDH
    lda #$01
    sta DMAP0
    lda #$18
    sta BBAD0
    lda $D0
    sta A1T0L
    lda $D1
    sta A1T0H
    lda $D2
    sta A1B0
    ; A producer-prepared transition can coalesce tens of KiB into one native
    ; run.  A single DMA of that size outlives VBlank and Mesen correctly
    ; rejects the visible-period tail, leaving noisy pattern data.  Transfer
    ; full 5.75 KiB chunks on separate NMI edges.  DMA0 advances A1T0 and VMADD
    ; automatically; only the remaining byte count must survive the NMI, so
    ; keep it on the protected 5A22 stack rather than in clobberable DP scratch.
    jmp bg_tile_run_dma_chunks

; =============================================================================
; Deferred native OBJ tile uploads.
;
; A new persistent-cache entry used to decode/copy 128 bytes on the 5A22 and
; eventually re-DMA the complete 16 KiB OBJ cache. Queue only the new code/slot
; pairs while OAM is built, then DMA each native ROM record immediately before
; publishing the replacement OAM. $7E:2D00 is safe scratch after BG rendering;
; $7E:2F00-$2FFF is the otherwise-unused gap before the coherent OBJ planes.
; =============================================================================
.org $AC00
.a16
.i16
obj_queue_prepare:
    jmp obj_queue_prepare_extended

.org $AC0C

obj_tile_queue:
    rep #$30
    lda $7E89C6          ; LDX has no 24-bit form; load long explicitly, then transfer
    tax
    cpx #$0080           ; at most one insertion for each hardware OAM entry
    bcc otq_capacity
    lda #$0002
    sta $7E89C8          ; persistent diagnostic: deferred queue reached its hard bound
    lda $DE
    sta $7E89CA
    lda $7E89C6
    sta $7E89CC
    pla                  ; discard obj_tile_queue's and obj_slot's JSR returns
    pla                  ; while retaining the renderer's saved status frame
    jmp obj_cache_restart ; defensive: restart coherently instead of overrunning scratch
otq_capacity:
    sep #$20
.a8
    lda $D8
    sta $7E2D00,x        ; one-byte destination cache slot
    rep #$20
.a16
    txa
    asl a
    tax
    lda $C4
    sta $7E2F00,x        ; corresponding 14-bit native tile code
    lda $7E89C6
    inc a
    sta $7E89C6
    jsr obj_T            ; obj_slot must still return the top-left OAM tile in E4
    rts

obj_cache_full:
    rep #$30
    lda #$0001
    sta $7E89C8          ; persistent diagnostic: 128-slot cache exhausted
    lda $DE
    sta $7E89CA
    lda $7E89C6
    sta $7E89CC
    pla                  ; discard this helper's JSR return
    pla                  ; discard obj_slot's JSR return; retain vid_obj's saved P
    jmp obj_cache_restart

obj_upload_queued:
    rep #$30
    ldy #$0000
ouq_loop:
    tya
    cmp $7E89C6
    beq ouq_done
    tax
    sep #$20
.a8
    lda $7E2D00,x
    rep #$20
.a16
    and #$00FF
    sta $D8
    tya
    asl a
    tax
    lda $7E2F00,x
    sta $C4
    phy
    jsr obj_tile_dma_direct
    ply
    iny
    bra ouq_loop
ouq_done:
    lda $DE
    sta $7E8988          ; retain the existing cache-count telemetry
    sep #$20
.a8
    jmp obj_upload_oam   ; positions/attributes remain one final 544-byte DMA

; One packed record is TL,TR,BL,BR. OBJ's 16-tile-wide grid stores TL/TR
; together and BL/BR sixteen tile numbers later, so two 64-byte ROM DMAs are
; exact and avoid both the intermediate decode buffer and the bulk cache copy.
obj_tile_dma_direct:
    php
    rep #$30
    lda $C4
    sta $D0
    stz $D2
    ldy #$0007
otd_shift:
    asl $D0
    rol $D2
    dey
    bne otd_shift
    lda $D2
    clc
    adc #$00C9
    sta $D2              ; native record source = $C90000 + code*128
    jsr obj_T
    lda $E4
    asl a
    asl a
    asl a
    asl a                ; sixteen VRAM words per 8x8 tile
    clc
    adc #$4000
    sta $D4              ; TL/TR destination

    sep #$20
.a8
    lda #$80
    sta VMAIN
    lda $D4
    sta VMADDL
    lda $D5
    sta VMADDH
    lda #$01
    sta DMAP0
    lda #$18
    sta BBAD0
    lda $D0
    sta A1T0L
    lda $D1
    sta A1T0H
    lda $D2
    sta A1B0
    lda #$40
    sta DAS0L
    stz DAS0H
    jsr dma0_blank_pulse

    rep #$20
.a16
    lda $D0
    clc
    adc #$0040           ; record alignment proves no 64 KiB bank crossing
    sta $D0
    lda $D4
    clc
    adc #$0100           ; BL/BR begin sixteen tile numbers after TL/TR
    sta $D4
    sep #$20
.a8
    lda $D4
    sta VMADDL
    lda $D5
    sta VMADDH
    lda $D0
    sta A1T0L
    lda $D1
    sta A1T0H
    lda #$40
    sta DAS0L
    stz DAS0H
    jsr dma0_blank_pulse
    plp
    rts

; Fast-renderer-specific persistent OBJ lookup.  Its hit/insert contract is
; identical to obj_slot, but a full 128-slot cache restarts the compact
; manifest renderer instead of falling through the old 512-record reference
; scan.  The current frame then repopulates a coherent cache from only its
; active codes and queues their exact native records before publishing OAM.
obj_slot_fast:
    jmp obj_slot_fast_hash
    nop                   ; retain every established cache/reclaimer address below

; The production lookup lives in the guarded $9C40 island.  Keep its former
; inline body as an explicit zero seam so the reclamation entries below retain
; their established offsets without leaving a second, stale hash algorithm.
.org $ADDF
.a16
.i16

; Reclaim at a high-water mark before an actual overflow makes one rare cache
; transition incremental instead of doing most of a frame twice.  Below 120
; effective occupied slots this is a load/compare fast path.  At 120, mark the
; current manifest's live cached slots and free every stale mapping; missing
; codes are allocated normally later in the same or following visual frame.
obj_fast_prepare:
    ; obj_cache_prepare may invalidate the hash and reset DE.  Do that before
    ; interpreting the persistent reclaimed-slot count; the opposite order
    ; let a stale nonzero $89CE survive obj_hclr and underflow occupancy.
    jsr obj_cache_prepare
    jmp obj_cache_preflight

obj_cache_preflight:
    rep #$30
    lda $DE
    cmp $7E89CE
    bcs ocp_count_ready
    lda #$0000           ; obj_hclr predates reclamation and resets DE only
    sta $7E89CE          ; impossible free>high-water means discard stale state
ocp_count_ready:
    lda $DE
    sec
    sbc $7E89CE          ; effective occupied slots after an earlier reclamation
    cmp #$0078
    bcs ocp_scan_needed
    rts                  ; ordinary cache occupancy keeps the zero-scan fast path
ocp_scan_needed:
    lda #$0000
    ldx #$0000
ocp_used_clear:
    sta $7E2E00,x        ; one byte per physical OBJ slot (cleared two at a time)
    inx
    inx
    cpx #$0080
    bne ocp_used_clear
    jsr obj_cache_protect_displayed
    ldy #$0000
    lda $7E89BA
    bpl ocp_manifest_loop
ocp_manifest_packed_loop:
    tya
    ora #$8000
    cmp $7E89BA
    bne ocp_manifest_packed_entry
    jmp ocp_reclaim
ocp_manifest_packed_entry:
    tax
    lda $7EBC02,x        ; packed raw code word follows Y
    xba
    bra ocp_manifest_code
ocp_manifest_loop:
    tya
    cmp $7E89BA
    bne ocp_manifest_entry
    jmp ocp_reclaim
ocp_manifest_entry:
    tax
    lda $7EBC00,x
    tax
    lda $7E4000,x
    xba
ocp_manifest_code:
    cmp #$FFFF
    beq ocp_next
    and #$3FFF
    beq ocp_next
    sta $C4

    asl a
    clc
    adc $C4
    and #$03FF
    asl a
    sta $D8
ocp_hash_probe:
    ldx $D8
    lda $7E5000,x
    beq ocp_next
    cmp $C4
    beq ocp_hash_live
    inx
    inx
    txa
    and #$07FF
    sta $D8
    bra ocp_hash_probe

ocp_hash_live:
    ldx $D8
    lda $7E5800,x
    and #$00FF
    sta $D0
    tax
    sep #$20
.a8
    lda $7E2E00,x
    bne ocp_hash_seen
    lda #$01
    sta $7E2E00,x
    rep #$30
.a16
    lda $7E89C6          ; compact retained-pair index; queue is still empty here
    tax
    sep #$20
.a8
    lda $D0
    sta $7E2D00,x        ; retained physical slot
    rep #$30
.a16
    txa
    asl a
    tax
    lda $C4
    sta $7E2F00,x        ; retained 14-bit code
    lda $7E89C6
    inc a
    sta $7E89C6
    bra ocp_next
ocp_hash_seen:
    rep #$30
.a16
    bra ocp_next
ocp_next:
    lda $7E89BA
    bmi ocp_next_packed
    iny
    iny
    jmp ocp_manifest_loop
ocp_next_packed:
    tya
    clc
    adc #$0006
    tay
    jmp ocp_manifest_packed_loop

ocp_reclaim:
    lda #$0001
    sta $7E89C8
    lda $DE
    sta $7E89CA
    lda #$0000
    sta $7E89CC          ; proactive high-water reclamation, before queue construction
    jsr obj_cache_reclaim_fast
    rts

; Rebuild a clean zero-terminated hash from the manifest's unique retained
; code/slot pairs, then publish every unused physical slot as a descending
; allocation stack.  Physical VRAM slots never move, but ordinary per-sprite
; lookup avoids a long-lived tombstone tax after this rare transition.
obj_cache_reclaim_fast:
    rep #$30
    jsr obj_hclr
    ldy #$0000
ocr_rehash_loop:
    tya
    cmp $7E89C6
    beq ocr_free_build
    tax
    sep #$20
.a8
    lda $7E2D00,x
    rep #$20
.a16
    and #$00FF
    sta $D0              ; retained physical slot
    tya
    asl a
    tax
    lda $7E2F00,x
    sta $C4              ; retained code
    asl a
    clc
    adc $C4
    and #$03FF
    asl a
    sta $D8
ocr_rehash_probe:
    ldx $D8
    lda $7E5000,x
    beq ocr_rehash_store
    inx
    inx
    txa
    and #$07FF
    sta $D8
    bra ocr_rehash_probe
ocr_rehash_store:
    lda $C4
    sta $7E5000,x
    lda $D0
    sta $7E5800,x
    iny
    bra ocr_rehash_loop

ocr_free_build:
    ldx #$0000
    ldy #$0000
    sep #$20
.a8
ocr_slot_loop:
    lda $7E2E00,x
    bne ocr_slot_used
    txa
    ; 65816 has no absolute-long,Y store.  Poppy silently encoded the old
    ; `sta $7E7B00,y` as bank-$00 absolute,Y, leaving the real free list zero.
    phx
    tyx
    sta $7E7B00,x
    plx
    iny
ocr_slot_used:
    inx
    cpx #$0080
    bne ocr_slot_loop
    rep #$30
.a16
    tya
    sta $7E89CE          ; number of reusable physical slots in $7E:7B00
    lda #$0000
    sta $7E89C6          ; retained-pair scratch becomes the real upload queue
    lda #$0080
    sta $DE              ; sequential high-water mark; allocator now consumes the stack
    rts
obj_cache_reclaim_fast_end:

; Consume packed visible-OBJ records directly from their bounded DMA image.
; Keeping Y/code/X together avoids both 4 KiB raw-plane transfers and
; the rejected v59/v60 sparse-unpack loop.  The legacy path above remains exact
; for old checkpoints and the rejected $CA02 lab token.  The producer already
; applied Y/X/code visibility and the 128-object cap; the defensive code check
; below preserves the legacy renderer's behavior if a malformed record appears.
.org $AF68               ; reclaimer grew by one displayed-OAM quarantine call
.a16
.i16
vid_obj_packed:
    rep #$30
    lda $7E89BA
    cmp #$8000
    bne vop_nonempty
    jmp vop_done
vop_nonempty:
    lda #$FFFF
    sta $F4              ; last logical palette bank; F0 remains its assigned slot
    sta $F8              ; last logical tile code; E4 remains its physical OAM tile
vop_loop:
    ldx $E0
    lda $7EBC02,x
    xba
    sta $F6              ; logical arcade code/flip word
    and #$3FFF
    beq vop_next
    lda $F6
    cmp #$FFFF
    beq vop_next

    ldx $E0
    lda $7EBC04,x
    xba
    sta $E8              ; logical arcade X/palette word
    lda $7EBC00,x
    xba
    and #$00FF
    sta $EC              ; logical arcade Y byte

    lda $E8
    and #$01FF
    ; Preserve the wrapped-right raw $100-$13F interval exactly as in the
    ; legacy path above.  Eight NOP bytes retain the established layout.
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
vop_sx_ready:
    sec
    sbc #$0040           ; centered crop: SNES X = arcade X - 64
    sta $EA
    lda $E8
    xba
    lsr a
    lsr a
    lsr a
    and #$001F
    sta $EE
    cmp $F4
    beq vop_palette_ready
    sta $F4
    jsr obj_palslot
vop_palette_ready:
    lda $F6
    and #$3FFF
    sta $C4
    cmp $F8
    beq vop_slot_ready
    sta $F8
    jsr obj_slot_fast
vop_slot_ready:
    jsr obj_oam_fast
    inc $E2
    lda $E2
    cmp #$0080
    beq vop_done
vop_next:
    lda $E0
    clc
    adc #$0006
    sta $E0
    ora #$8000
    cmp $7E89BA
    bne vop_loop
vop_done:
    jmp vof_done
vid_obj_packed_end:

bg_cache_extended_end:

; =============================================================================
; Two-entry compressed render queue.
;
; This capture island intentionally executes from ROM only while arm=$0003 has
; the SA-1 asleep.  The renderer never executes it concurrently with SA-1 ROM
; traffic.  Busy deadlines can therefore retain two complete candidates instead
; of silently losing them.  Packed OBJ records are copied directly;
; incremental BG candidates retain their offset list plus only four bytes per
; changed cell.  Full/prepared candidates use mutually exclusive payload shapes,
; keeping the complete queue below $7E:EA40 and clear of the $7E:F000 worker.
; =============================================================================
.org $B000
.a16
.i16
render_queue_capture:
    php
    rep #$30
    lda $D0
    pha
    lda $D4
    pha                 ; NMI/IRQ capture must not poison interrupted renderer scratch
    jsr render_queue_install ; lazy, one-time install after the boot RAM test
    lda #$0002
    sta $7E89D2          ; claimed until every payload and metadata byte is private

    lda $410138
    bmi rqc_packed
    jmp rqc_abort        ; production pacing publishes packed records only
rqc_packed:
    sta $7ED182
    lda $410132
    sta $7ED180
    lda $41013A
    sta $7ED184
    lda $41013C
    sta $7ED186
    lda $410146
    sta $7ED188
    lda $3300
    sta $7ED18A

    ; Channel 7 -> WRAM data port.  The SA-1 remains asleep until this routine
    ; returns to pacing_try_wake, so every BW-RAM source is stable.
    sep #$20
.a8
    stz $4370
    lda #$80
    sta $4371
    lda #$41
    sta $4374
    stz $2183
    rep #$30
.a16

    lda $7ED186
    beq rqc_palette_done
    ; Production pacing does not populate the retired legacy snapshot at
    ; $41:6800.  arm=$0003 keeps the SA-1 asleep here, so the authoritative
    ; live palette at $41:2000 is stable.  Copying $6800 promoted a zero
    ; palette after busy frames: Mesen showed the post-TAITO scene for three
    ; video frames, then black for ~37, repeating every 40 frames.
    ldx #$2000
    ldy #$D1A0
    lda #$0400
    jsr pacing_snapshot_dma
rqc_palette_done:

    lda $7ED182
    and #$7FFF
    beq rqc_obj_done
    ldx #$1600
    ldy #$D5A0
    jsr pacing_snapshot_dma
rqc_obj_done:

    lda $7ED184
    beq rqc_bg_done
    cmp #$FFFE
    beq rqc_bg_prepared
    cmp #$FFFF
    beq rqc_bg_full

    ; Incremental candidate: retain the producer-unique offset list and gather
    ; only the corresponding code/color words from the stable live shadow.
    ldx #$1A00
    ldy #$E0A0
    jsr pacing_snapshot_dma
    ldy #$0000
    stz $D4              ; packed value byte cursor
rqc_bg_sparse_loop:
    tya
    cmp $7ED184
    beq rqc_bg_done
    tax
    lda $411A00,x
    sta $D0              ; arcade cell byte offset
    tax
    lda $414800,x
    ldx $D4
    sta $7EE4A0,x
    inx
    inx
    stx $D4
    ldx $D0
    lda $414C00,x
    ldx $D4
    sta $7EE4A0,x
    inx
    inx
    stx $D4
    iny
    iny
    bra rqc_bg_sparse_loop

rqc_bg_full:
    ldx #$4800
    ldy #$D8A0
    lda #$0800
    jsr pacing_snapshot_dma
    bra rqc_bg_done

rqc_bg_prepared:
    ldx #$8000
    ldy #$D8A0
    lda #$1000
    jsr pacing_snapshot_dma
    lda $7ED188
    beq rqc_bg_prepared_pal
    ldx #$9000
    ldy #$E8A0
    jsr pacing_snapshot_dma
rqc_bg_prepared_pal:
    ldx #$9200
    ldy #$EA20
    lda #$0020
    jsr pacing_snapshot_dma
rqc_bg_done:

    jsr capture_bg_vscroll
    sta $7ED18C
    nop
    lda $413604
    sta $7ED18E

    ; Acceptance has the same producer contract as the direct snapshot: only a
    ; complete private image advances ACK and clears cumulative dirty flags.
    lda $7ED180
    sta $410134
    lda #$0000
    sta $41013E
    jsr producer_touch_reset
    nop
    lda #$0001
    sta $7E89D2          ; publish complete queue entry last
    bra rqc_restore
rqc_abort:
    lda #$0000
    sta $7E89D2
rqc_restore:
    pla
    sta $D4
    pla
    sta $D0
    plp
    rtl
render_queue_capture_end:

; A second arrival needs only the overwhelmingly common packed/sparse shape.
; Its 3 KiB slot reuses the legacy $CA02 raw-OBJ capture area, which production
; packed rendering never reads.  Full/prepared BG and the lab-only $CA02 token
; are rejected explicitly rather than overrunning or aliasing live data.
.org $B140
.a16
.i16
render_queue_capture_secondary:
    php
    rep #$30
    lda $D0
    pha
    lda $D4
    pha                 ; preserve the renderer across a busy-deadline interrupt
    lda #$0002
    sta $7E89D6
    lda $410128
    cmp #$CA02
    bne rqc2_token_ok
    jmp rqc2_abort
rqc2_token_ok:
    lda $410138
    bmi rqc2_packed
    jmp rqc2_abort
rqc2_packed:
    sta $7EB002
    lda $41013A
    cmp #$FFFE
    bne rqc2_not_prepared
    jmp rqc2_abort
rqc2_not_prepared:
    cmp #$FFFF
    bne rqc2_not_full
    jmp rqc2_abort
rqc2_not_full:
    cmp #$0100
    bcc rqc2_sparse_fit
    jmp rqc2_abort
rqc2_sparse_fit:
    sta $7EB004
    lda $410132
    sta $7EB000
    lda $41013C
    sta $7EB006
    lda $410146
    sta $7EB008
    lda $3300
    sta $7EB00A

    sep #$20
.a8
    stz $4370
    lda #$80
    sta $4371
    lda #$41
    sta $4374
    stz $2183
    rep #$30
.a16

    lda $7EB006
    beq rqc2_palette_done
    ldx #$2000          ; same stable live-palette contract as the primary queue
    ldy #$B020
    lda #$0400
    jsr pacing_snapshot_dma
rqc2_palette_done:
    lda $7EB002
    and #$7FFF
    beq rqc2_obj_done
    ldx #$1600
    ldy #$B420
    jsr pacing_snapshot_dma
rqc2_obj_done:
    lda $7EB004
    beq rqc2_bg_done
    ldx #$1A00
    ldy #$B720
    jsr pacing_snapshot_dma
    ldy #$0000
    stz $D4
rqc2_bg_loop:
    tya
    cmp $7EB004
    beq rqc2_bg_done
    tax
    lda $411A00,x
    sta $D0
    tax
    lda $414800,x
    ldx $D4
    sta $7EB820,x
    inx
    inx
    stx $D4
    ldx $D0
    lda $414C00,x
    ldx $D4
    sta $7EB820,x
    inx
    inx
    stx $D4
    iny
    iny
    bra rqc2_bg_loop
rqc2_bg_done:
    jsr capture_bg_vscroll
    sta $7EB00C
    nop
    lda $413604
    sta $7EB00E
    lda $7EB000
    sta $410134
    lda #$0000
    sta $41013E
    jsr producer_touch_reset
    nop
    lda #$0001
    sta $7E89D6
    bra rqc2_restore
rqc2_abort:
    lda #$0000
    sta $7E89D6
rqc2_restore:
    pla
    sta $D4
    pla
    sta $D0
    plp
    rtl
render_queue_capture_secondary_end:

; =============================================================================
; Title text BG2 overlay.
;
; The arcade title represents each 8x8 legal-text glyph as a 16x16 X1-001 OBJ.
; Six rows contain 149 such records: beyond both the SNES 128-OBJ frame limit
; and the 34 OBJ-tile scanline limit.  The SA-1 manifest removes only those
; signature-gated rows.  Here the 5A22 copies the same glyphs' nonempty
; top-left 8x8 tiles from the native graphics records into otherwise-unused
; BG2 VRAM, publishes a static 32x32 map for the centered crop, and leaves OAM
; capacity to the Superman/TAITO artwork.  No private graphics bytes are
; embedded in source; they are read from the already packed private ROM image.
; =============================================================================
.org $B300
.a16
.i16
title_bg_overlay:
    php
    phb
    sep #$20
.a8
    lda #$00
    pha
    plb                         ; PPU/DMA absolute registers require DBR=$00
    rep #$30
.a16

    lda $7E89DC
    cmp #$A55B
    beq tbo_palette
    jsr title_bg_build_font
    jsr title_bg_build_map

    ; MVN leaves DBR at its destination bank.  Restore zero before touching
    ; PPU/DMA registers, while retaining the caller's original DBR below it.
    sep #$20
.a8
    lda #$00
    pha
    plb
    jsr title_bg_upload
    rep #$30
.a16
    lda #$A55B
    sta $7E89DC

tbo_palette:
    ; Logical arcade palette bank zero is assigned dynamically in the OBJ
    ; palette cache.  Copy its already converted physical OBJ slot to reserved
    ; BG palette 7 so the BG2 glyph pixels remain color-identical.
    sep #$20
.a8
    lda $7E8580
    cmp #$FF
    beq tbo_registers
    rep #$20
.a16
    and #$00FF
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$8100
    sta $D0
    lda #$80E0
    sta $D4
    lda #$007E
    sta $D2
    sta $D6
    jsr copy32

tbo_registers:
    sep #$20
.a8
    lda #$70
    sta BG2SC                   ; 32x32 BG2 map at VRAM word $7000
    lda #$61
    sta BG12NBA                 ; BG1 chars $1000; BG2 chars $6000
    stz BG2HOFS
    stz BG2HOFS
    stz BG2VOFS
    stz BG2VOFS
    lda #$13
    sta TM                      ; BG1 starfield + BG2 text + OBJ artwork
    plb
    plp
    rtl

.a16
.i16
title_bg_build_font:
    ; Tile zero is transparent.  Tiles 1-41 are A-Z, 0-9, @, period, comma,
    ; hyphen, and ampersand.  Every glyph's other three 8x8 quadrants are transparent in
    ; the arcade record, so copying the first native 32-byte tile is exact.
    lda #$0000
    ldx #$0000
tbf_clear:
    sta $7E6800,x
    inx
    inx
    cpx #$0540
    bne tbf_clear

    stz $D8
tbf_glyph:
    ldx $D8
    sep #$20
.a8
    ; Poppy records same-bank labels with bank byte zero; force the physical
    ; ROM bank exactly as the fixed renderer wrappers do.
    lda.l title_font_codes|$E90000,x
    rep #$20
.a16
    and #$00FF
    xba
    lsr a                       ; source = $C9:0000 + logical code * 128
    sta $D0
    lda #$00C9
    sta $D2

    lda $D8
    inc a                       ; physical BG tile zero remains transparent
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$6800
    sta $D4
    lda #$007E
    sta $D6
    jsr copy32

    inc $D8
    lda $D8
    cmp #$0029
    bne tbf_glyph
    rts

title_bg_build_map:
    lda #$0000
    ldx #$0000
tbm_clear:
    sta $7E6000,x
    inx
    inx
    cpx #$0800
    bne tbm_clear

    ; Six 64-byte rows land at screen tile rows 14,16,18,20,22,24.  The two
    ; arcade legal lines wider than 256 pixels are edited without changing
    ; their meaning: one trailing comma is omitted and "AND" becomes "&".
    ; This keeps every word coherent instead of clipping the initial/final S.
    lda #$003F
    ldx #title_text_row14
    ldy #$6380
    mvn $7E,$E9
    lda #$003F
    ldx #title_text_row16
    ldy #$6400
    mvn $7E,$E9
    lda #$003F
    ldx #title_text_row18
    ldy #$6480
    mvn $7E,$E9
    lda #$003F
    ldx #title_text_row20
    ldy #$6500
    mvn $7E,$E9
    lda #$003F
    ldx #title_text_row22
    ldy #$6580
    mvn $7E,$E9
    lda #$003F
    ldx #title_text_row24
    ldy #$6600
    mvn $7E,$E9
    rts

.a8
.i16
title_bg_upload:
    lda #$80
    sta VMAIN
    stz VMADDL
    lda #$60
    sta VMADDH
    lda #$01
    sta DMAP0
    lda #$18
    sta BBAD0
    stz A1T0L
    lda #$68
    sta A1T0H
    lda #$7E
    sta A1B0
    lda #$40
    sta DAS0L
    lda #$05
    sta DAS0H                   ; blank tile + 41 glyphs = 1344 bytes
    jsr dma0_blank_pulse

    stz VMADDL
    lda #$70
    sta VMADDH
    lda #$01
    sta DMAP0
    lda #$18
    sta BBAD0
    stz A1T0L
    lda #$60
    sta A1T0H
    lda #$7E
    sta A1B0
    stz DAS0L
    lda #$08
    sta DAS0H                   ; complete 32x32 BG2 map
    jsr dma0_blank_pulse
    rts

; Logical-code order for physical BG tiles 1-41.
title_font_codes:
    .db $41,$42,$43,$44,$45,$46,$47,$48,$49,$4A,$4B,$4C,$4D
    .db $4E,$4F,$50,$51,$52,$53,$54,$55,$56,$57,$58,$59,$5A
    .db $30,$31,$32,$33,$34,$35,$36,$37,$38,$39,$40,$2E,$2C,$2D,$26

; Palette 7 ($1C00) plus high-priority bit ($2000), followed by tile 1-40.
title_text_row14:
    .word $0000,$0000,$0000,$0000,$3C25,$0000,$3C14,$3C01
    .word $3C09,$3C14,$3C0F,$0000,$3C03,$3C0F,$3C12,$3C10
    .word $3C0F,$3C12,$3C01,$3C14,$3C09,$3C0F,$3C0E,$0000
    .word $3C1C,$3C24,$3C23,$3C23,$0000,$0000,$0000,$0000
title_text_row16:
    .word $3C13,$3C15,$3C10,$3C05,$3C12,$3C0D,$3C01,$3C0E
    .word $3C27,$0000,$3C01,$3C0C,$3C0C,$0000,$3C12,$3C05
    .word $3C0C,$3C01,$3C14,$3C05,$3C04,$0000,$3C03,$3C08
    .word $3C01,$3C12,$3C01,$3C03,$3C14,$3C05,$3C12,$3C13
title_text_row18:
    .word $3C13,$3C0C,$3C0F,$3C07,$3C01,$3C0E,$3C13,$0000
    .word $3C29,$0000,$3C09,$3C0E,$3C04,$3C09,$3C03,$3C09
    .word $3C01,$0000,$3C01,$3C12,$3C05,$0000,$3C14,$3C12
    .word $3C01,$3C04,$3C05,$3C0D,$3C01,$3C12,$3C0B,$3C13
title_text_row20:
    .word $0000,$0000,$0000,$0000,$0000,$3C0F,$3C06,$0000
    .word $3C04,$3C03,$0000,$3C03,$3C0F,$3C0D,$3C09,$3C03
    .word $3C13,$0000,$3C09,$3C0E,$3C03,$3C26,$3C25,$3C1C
    .word $3C24,$3C23,$3C23,$0000,$0000,$0000,$0000,$0000
title_text_row22:
    .word $0000,$0000,$0000,$0000,$3C13,$3C15,$3C10,$3C05
    .word $3C12,$3C0D,$3C01,$3C0E,$0000,$3C14,$3C08,$3C05
    .word $3C0D,$3C05,$0000,$3C25,$0000,$3C17,$3C01,$3C12
    .word $3C0E,$3C05,$3C12,$3C28,$0000,$0000,$0000,$0000
title_text_row24:
    .word $3C14,$3C01,$3C0D,$3C05,$3C12,$3C0C,$3C01,$3C0E
    .word $3C05,$0000,$3C10,$3C15,$3C02,$3C0C,$3C09,$3C13
    .word $3C08,$3C09,$3C0E,$3C07,$0000,$3C03,$3C0F,$3C12
    .word $3C10,$3C26,$3C27,$0000,$3C1C,$3C24,$3C23,$3C22
title_bg_overlay_end:

; The first primary capture lazily copies this island to the identical private
; $7E:ED00 offset after production pacing has armed and while the SA-1 sleeps.
; Bank $7F is deliberately never used: it is the game's entire emulated 68000
; work RAM.  vf_tick reaches this copy through render_queue_finish only while at
; least one queue is complete; the final PLP/RTL preserves the original ABI.
; Promotion changes the direct-cache generation only after a complete queued
; image is ready for snapshot_acquire_paced.
.org $ED00
.a16
.i16
render_queue_promote:
    phb
    rep #$30
    lda $7E89D2
    cmp #$0001
    beq rqp_primary_valid
    lda $7E89D6
    cmp #$0001
    beq rqp_choose_secondary
    jmp rqp_finish
rqp_primary_valid:
    lda $7E89D6
    cmp #$0001
    bne rqp_choose_primary
    ; Both slots are complete.  Their candidate sequences are at most a few
    ; ticks apart; a signed modular delta chooses the older entry across wrap.
    lda $7EB000
    sec
    sbc $7ED180
    bit #$8000
    bne rqp_choose_secondary
rqp_choose_primary:
    stz $D8
    lda #$0002
    sta $7E89D2          ; NMI must not overwrite storage during promotion
    bra rqp_have_entry
rqp_choose_secondary:
    lda #$0001
    sta $D8
    lda #$0002
    sta $7E89D6
rqp_have_entry:

    lda $7E899A
    and #$FFFE
    inc a
    sta $7E899A          ; odd until every canonical cache is complete

    lda $D8
    beq rqp_primary_copy
    jmp rqp_secondary_copy
rqp_primary_copy:

    lda $7ED180
    sta $7E89B8
    lda $7ED182
    sta $7E89BA
    lda $7ED184
    sta $7E89BC
    lda $7ED186
    sta $7E89BE
    lda $7ED188
    sta $7E89C4

    lda $7ED186
    beq rqp_palette_done
    lda #$03FF
    ldx #$D1A0
    ldy #$2800
    jsr rqp_copy
rqp_palette_done:

    lda $7ED182
    and #$7FFF
    beq rqp_obj_done
    dec a
    ldx #$D5A0
    ldy #$BC00
    jsr rqp_copy
rqp_obj_done:

    lda $7ED184
    bne rqp_bg_select
    jmp rqp_bg_done
rqp_bg_select:
    cmp #$FFFE
    beq rqp_bg_prepared
    cmp #$FFFF
    beq rqp_bg_full

    ; Restore the compact offset list, then apply its parallel code/color pairs
    ; to the canonical raw planes.  The preceding rendered candidate is the
    ; accepted baseline, so this sparse application reconstructs the queued
    ; candidate exactly.
    dec a
    ldx #$E0A0
    ldy #$8C00
    jsr rqp_copy
    ldy #$0000
    stz $D4              ; packed value byte cursor
rqp_bg_sparse_loop:
    tya
    cmp $7ED184
    beq rqp_bg_done
    tyx
    lda $7EE0A0,x
    sta $D0              ; canonical cell byte offset
    ldx $D4
    lda $7EE4A0,x
    sta $D2
    inx
    inx
    lda $7EE4A0,x
    sta $D6
    inx
    inx
    stx $D4
    ldx $D0
    lda $D2
    sta $7E2000,x
    lda $D6
    sta $7E2400,x
    iny
    iny
    bra rqp_bg_sparse_loop

rqp_bg_full:
    lda #$07FF
    ldx #$D8A0
    ldy #$2000
    jsr rqp_copy
    bra rqp_bg_done

rqp_bg_prepared:
    lda #$0FFF
    ldx #$D8A0
    ldy #$9000
    jsr rqp_copy
    lda $7ED188
    beq rqp_bg_prepared_pal
    dec a
    ldx #$E8A0
    ldy #$7900
    jsr rqp_copy
rqp_bg_prepared_pal:
    lda #$001F
    ldx #$EA20
    ldy #$8940
    jsr rqp_copy
rqp_bg_done:

    lda $7ED18C
    sta $7E3408
    lda $7ED18E
    sta $7E3604
    jmp rqp_publish

rqp_secondary_copy:
    lda $7EB000
    sta $7E89B8
    lda $7EB002
    sta $7E89BA
    lda $7EB004
    sta $7E89BC
    lda $7EB006
    sta $7E89BE
    lda $7EB008
    sta $7E89C4

    lda $7EB006
    beq rqp2_palette_done
    lda #$03FF
    ldx #$B020
    ldy #$2800
    jsr rqp_copy
rqp2_palette_done:
    lda $7EB002
    and #$7FFF
    beq rqp2_obj_done
    dec a
    ldx #$B420
    ldy #$BC00
    jsr rqp_copy
rqp2_obj_done:
    lda $7EB004
    beq rqp2_bg_done
    dec a
    ldx #$B720
    ldy #$8C00
    jsr rqp_copy
    ldy #$0000
    stz $D4
rqp2_bg_loop:
    tya
    cmp $7EB004
    beq rqp2_bg_done
    tyx
    lda $7EB720,x
    sta $D0
    ldx $D4
    lda $7EB820,x
    sta $D2
    inx
    inx
    lda $7EB820,x
    sta $D6
    inx
    inx
    stx $D4
    ldx $D0
    lda $D2
    sta $7E2000,x
    lda $D6
    sta $7E2400,x
    iny
    iny
    bra rqp2_bg_loop
rqp2_bg_done:
    lda $7EB00C
    sta $7E3408
    lda $7EB00E
    sta $7E3604

rqp_publish:

    lda $7E899A
    inc a
    bne rqp_generation_done
    lda #$0002
rqp_generation_done:
    sta $7E899A          ; even: queued image is now atomically consumable
    lda $D8
    beq rqp_publish_primary
    lda $7EB00A
    bra rqp_publish_req
rqp_publish_primary:
    lda $7ED18A
rqp_publish_req:
    sta $1F1E            ; worker observes the queued request after this RTL
    lda #$0000
    ldx $D8
    bne rqp_release_secondary
    sta $7E89D2
    bra rqp_finish       ; release queue storage before declaring renderer idle
rqp_release_secondary:
    sta $7E89D6

rqp_finish:
    lda #$0000
    sta $7E899C
    plb
    plp                  ; balance vf_tick's entry PHP
    rtl

rqp_copy:                ; A=byte count-1, X=source, Y=destination, all in WRAM $7E
    mvn $7E,$7E
    rts
    nop                   ; keep rc_copy's word-counted promoter image even-sized
render_queue_promote_end:

; =============================================================================
; Immediate 5A22-owned boot display
;
; The genuine 68000 reset/self-test takes thousands of SNES video frames. Until
; the production renderer can claim a coherent arcade image, show the user's
; SA-1 logo and OBJ status text instead of an unexplained black screen. The
; logo performs one non-rotating huge-to-fitted zoom, then a tiny palette-
; pulsed status diamond remains active. All assets are
; generated by tools/gen_boot_screen.py and packed at 5A22 ROM
; $F0:0000-$F0:7FFF; they contain no arcade ROM material.
;
; PPU ownership is one-way: this routine runs once under forced blank before NMI
; is enabled. NMI advances the one-shot scale table and pulses one private OBJ
; palette color while $7E:1F1B bit7 is set. The first vf_tick clears that bit,
; and the existing game renderer then replaces BGMODE, VRAM, CGRAM, OAM, OBSEL,
; and TM through its normal paths.
; =============================================================================
.org $F000
.a16
.i16
boot_screen_init:
    php
    phb
    sep #$20
.a8
    lda #$00
    pha
    plb                  ; DBR=$00 for PPU/DMA and private-WRAM accesses
    lda #$80
    sta INIDISP
    stz NMITIMEN
    stz TM
    stz TS

    ; Mode 7 tilemap: one byte per VRAM word through VMDATAL.
    stz VMAIN
    stz VMADDL
    stz VMADDH
    stz DMAP0
    lda #$18
    sta BBAD0
    stz A1T0L
    stz A1T0H
    stz DAS0L
    lda #$40
    sta DAS0H
    jsr boot_dma0

    ; Mode 7 8bpp tile pixels: high byte of each VRAM word.
    lda #$80
    sta VMAIN
    stz VMADDL
    stz VMADDH
    stz DMAP0
    lda #$19
    sta BBAD0
    stz A1T0L
    lda #$40
    sta A1T0H
    stz DAS0L
    lda #$28
    sta DAS0H
    jsr boot_dma0

    ; 4bpp 8x8 status font at OBJ character base word $6000.
    lda #$80
    sta VMAIN
    stz VMADDL
    lda #$60
    sta VMADDH
    lda #$01             ; DMA mode 1 -> VMDATAL/VMDATAH
    sta DMAP0
    lda #$18
    sta BBAD0
    stz A1T0L
    lda #$68
    sta A1T0H
    stz DAS0L
    lda #$10
    sta DAS0H
    jsr boot_dma0

    ; Complete OAM image: visible text sprites plus hidden unused entries.
    stz OAMADDL
    stz OAMADDH
    stz DMAP0
    lda #$04
    sta BBAD0
    stz A1T0L
    lda #$78
    sta A1T0H
    lda #$20
    sta DAS0L
    lda #$02
    sta DAS0H
    jsr boot_dma0

    ; Full CGRAM image, including Mode 7 colors and OBJ palette zero.
    stz CGADD
    stz DMAP0
    lda #$22
    sta BBAD0
    stz A1T0L
    lda #$7C
    sta A1T0H
    stz DAS0L
    lda #$02
    sta DAS0H
    jsr boot_dma0

    ; Copy the deterministic 64-entry, scale-only matrix table to private WRAM.
    ; The NMI path reads it for one pass and never rotates or restarts it.
    rep #$30
.a16
    ldx #$0000
bsi_matrix_copy:
    lda $F07E00,x
    sta $7EF100,x
    inx
    inx
    cpx #$0200
    bne bsi_matrix_copy

    sep #$20
.a8
    lda #$07
    sta BGMODE
    lda #$80             ; outside the 128x128 map uses blank character zero
    sta M7SEL
    lda #$03             ; OBJ 8x8/16x16; character base word $6000
    sta OBSEL

    ; Start at 0.125 scale, making the centered logo a huge close-up. The NMI
    ; table converges monotonically to the established fitted 0.75 scale.
    lda #$20
    sta M7A
    stz M7A
    stz M7B
    stz M7B
    stz M7C
    stz M7C
    lda #$20
    sta M7D
    stz M7D
    lda #$7C             ; source center X = 124 (map columns 8..22)
    sta M7X
    stz M7X
    lda #$70             ; center Y = 112
    sta M7Y
    stz M7Y
    stz BG1HOFS
    stz BG1HOFS
    stz BG1VOFS
    stz BG1VOFS

    lda #$11             ; Mode 7 BG1 + static OBJ status text
    sta TM
    lda #$0F
    sta INIDISP
    plb
    plp
    rts

boot_dma0:
    lda #$F0             ; every generated boot-asset section is in bank $F0
    sta A1B0
    lda #$01
    sta MDMAEN
    rts
boot_screen_init_end:
video_image_end:
