; ============================================================================
; tad_glue.pasm — TAD LoadAudioData callback (ported from the ca65 `audio-data.s`
; that `tad-compiler ca65-export` generates). HIROM variant.
;
; Blob symbols (Tad_Loader_Bin/Tad_AudioDriver_Bin/Tad_DataTable/N_DATA_ITEMS...)
; are GENERATED per-blob into soundwork/tad/build/tad_blob_syms.pasm by
; build_blob.sh, and concatenated BEFORE this file by tools/build_interp.sh.
;
; LAYOUT (P3, multi-bank): the bare blob is .incbin'd at file $2D002B = 5A22
; $ED:002B — segment offset 43, mirroring stock ca65's [43-byte LoadAudioData
; proc][blob] single-segment layout. The DataTable's u24 entries are offsets from
; the SEGMENT start, so with the blob at +43 they resolve UNSKEWED:
;   far addr = $ED:0000 + entry, linear across banks $ED/$EE/... (HiROM $C0-$FF
;   is file-linear; the entry's third byte + carry feeds the bank byte below).
; P1's single-bank layout instead incbin'd at $ED:0000 and subtracted a
; DATA_SEGMENT_SKEW=43 from the low16 — the borrow never reached the bank byte,
; so it could NOT work for a >64KB blob (and forgetting the skew entirely was
; the P1 boot-flakiness root cause: common+song uploaded 43 bytes skewed, the
; driver parsed a garbage song header and executed random power-on ARAM).
; ============================================================================

; This module is CONCATENATED after src/video.pasm (Poppy has no .include). It occupies the
; supervisor bank $E9 tail, past all pinned resume PCs — .org $9000 so nothing upstream shifts.
.org $9000

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
    ; data size = DataTable[i+1] - DataTable[i]  (assumes 0 < size <= $ffff;
    ; for the LAST item the 16-bit read at +3 lands on the u16 end footer)
    lda.l Tad_DataTable+3,x
    sec
    sbc.l Tad_DataTable,x
    tay
    lda.l Tad_DataTable,x
    sta 1,s
    sep #$21
.a8
    lda.l Tad_DataTable+2,x
    adc #(AUDIO_DATA_BANK-1)&$ff       ; carry set -> +bank; entry byte2 carries the bank delta
    plx
    sec
    rtl
