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
    sta 1,s
    sep #$21
.a8
    lda.l Tad_DataTable+2,x
    adc #(AUDIO_DATA_BANK-1)&$ff       ; carry set -> +bank
    plx
    sec
    rtl
