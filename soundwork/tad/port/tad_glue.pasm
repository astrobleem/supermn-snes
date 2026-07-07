; ============================================================================
; tad_glue.pasm — TAD ROM-data symbols + LoadAudioData callback (ported from the
; ca65 `audio-data.s` that `tad-compiler ca65-export` generates). HIROM variant.
; The audio-data.bin blob is .incbin'd at file $2D0000 = 5A22 HiROM $ED:0000
; (see tools/build_interp_rom.py). Assembled with the supervisor at bank $E9.
; ============================================================================

; This module is CONCATENATED after src/video.pasm (Poppy has no .include). It occupies the
; supervisor bank $E9 tail, past all pinned resume PCs — .org $9000 so nothing upstream shifts.
.org $9000

; --- blob-derived symbols (blob base = $ED:0000; layout from soundwork/tad/vendor/VERSION.md) ---
AUDIO_DATA_BANK      = $ED
Tad_Loader_Bin       = $ED0000
Tad_Loader_SIZE      = 116
Tad_AudioDriver_Bin  = $ED0074
Tad_AudioDriver_SIZE = $0C92          ; 3218
Tad_DataTable        = $ED0D06        ; blob base + 3334
N_DATA_ITEMS         = 2
; DataTable entries are SEGMENT-relative, NOT blob-relative: tad-compiler's ca65-export
; emits [43-byte LoadAudioData proc][blob] in ONE segment, and the u24 entries (+ u16 end
; footer) are offsets from the SEGMENT start ("table of PRG ROM offsets (from the start of
; the first Audio Data segment)"; footer = 43+4169 = $1074). This ROM incbins the BARE blob
; at $ED:0000 (no 43-byte proc prefix), so every entry is 43 too high; subtract it when
; forming the far address. Sizes (entry-to-entry deltas) are unaffected.
; THIS WAS THE SOUND-P1 BOOT-FLAKINESS ROOT CAUSE (2026-07-07): common+song uploaded 43
; bytes skewed -> driver parsed a garbage song header -> channels executed random power-on
; ARAM as bytecode -> seed-dependent loud/quiet/silent boots (NOT a Mesen/SA-1 artifact).
DATA_SEGMENT_SKEW    = 43

; --- LoadAudioData (HIROM) — jsl-called (rtl). IN: A=0 common (returns carry SET); A>=1 song.
;     OUT: carry set if valid; A:X = far address; Y = size. ------------------------------------
.a8
.i16
LoadAudioData:
    cmp #N_DATA_ITEMS
    bcc LoadAudioData__Valid
        clc
        rtl
LoadAudioData__Valid:
    rep #$30
.a16
    and #$ff
    pha
    asl
    adc 1,s
    tax
    ; data size = DataTable[i+1] - DataTable[i]  (assumes 0 < size <= $ffff)
    lda.l Tad_DataTable+3,x
    sec
    sbc.l Tad_DataTable,x
    tay
    lda.l Tad_DataTable,x
    sec
    sbc #DATA_SEGMENT_SKEW             ; segment offset -> bare-blob offset. NOTE: subtracts from the
                                       ; low16 only; the sep #$21 below re-forces carry, so a borrow is
                                       ; NOT propagated to the bank byte. Safe here because every item's
                                       ; low16 >= $D06 (single-bank P1 blob). P3 (multi-bank real songs,
                                       ; an item whose low16 < $2B) must instead incbin the blob at
                                       ; $ED:002B to match stock's segment layout and drop this -$2B.
    sta 1,s
    sep #$21
.a8
    lda.l Tad_DataTable+2,x
    adc #(AUDIO_DATA_BANK-1)&$ff       ; carry set -> +bank
    plx
    sec
    rtl
