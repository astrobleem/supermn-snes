# Scheduler switch-OUT escape — WIP handoff (task #15)

Status: WIRED + FIRES but has a resume bug (task bodies resume at PC=$0000 -> corrupted
save/SP-save). REVERTED from the build to restore ESC=0 GREEN. Re-attempt with the notes below.

## The finding (stands): see memory scheduler-context-switch-lever.md
Scheduler = ~30% of tick = pure coroutine context-switch plumbing. sched_trace.py is the tracer.

## Implementation that was tried (revert below restores GREEN):
```
diff --git a/src/escbank.pasm b/src/escbank.pasm
index ac54647..a4d58ab 100644
--- a/src/escbank.pasm
+++ b/src/escbank.pasm
@@ -26,6 +26,7 @@ ojmp_hook=$00D1B3
 jsrabs_hook=$00E200
 bhp_after=$00E454
 ors_pre=$00D16F
+lh_sched=$00F9B2
 entry_c9f8=$948039
 entry_d5a0=$94849E
 entry_1008=$94855B
@@ -62,6 +63,7 @@ escbank_jmptab:                  ; dispatcher jml's to $928000 + slot*3 (each jm
     jmp entry_2bc2               ; slot 16 ($928030)  <- $002BC2 gf260-reached, C-Chip abs
     jmp entry_ccd8               ; slot 17 ($928033)  <- $00CCD8 frame-sharing
     jmp entry_cc10               ; slot 18 ($928036)  <- $00CC10 frame-sharing leaf (move.l fixed)
+    jmp entry_swo                ; slot 19 ($928039)  <- $0532 scheduler switch-OUT (yield trap)
 
 ; --- transpiled from $000D96 (60 instrs) by tools/transpile.py [bank1] ---
 entry_d96:
@@ -14037,6 +14039,153 @@ ib_miss:
     sta $42
     jml.l inext
 
+; ===================== SCHEDULER SWITCH-OUT ($0532 yield trap) =====================
+; entry_swo — native coroutine SWITCH-OUT. Reached from bank-$00 swo_tramp (jml $928039) when the
+; interp is about to fetch $0532 (a task yielded via trap; op_trap already pushed PC+SR, so a7 = the
+; post-trap SP). Faithfully replicates $0532-$0550 (verified vs the disasm + op_movem_pre/op_ori_sr):
+;   $0532 ori #$700,sr      -> mask=7   (sr_apply model: $7C = (SR>>8)&7, so $7C|=7)
+;   $0536 movem.l d0-a6,-(a7) -> a7-=60; save 15 regs (slots $00..$38) ascending, BIG-ENDIAN
+;   $053A movea.l $6(a5),a6 ; $053E move.l a7,(a6)   -> a6=*(a5+6); save the new task SP there
+;   $0540 movea.l $4a(a5),a4 ; $0544-$054E  -> a4=*(a5+$4a); (a4).w = ((a4)&$cfff)|$c000  (yield mark)
+;   $0550 bra $74c          -> re-enter the scheduler scan (we jml lh_sched, collapsing it too).
+; DP reg file: D0=$00..D7=$1C, A0=$20..A6=$38, A7=$3C/$3E, a5=$34/$36. Work RAM = $400000+(addr&FFFF).
+entry_swo:
+    rep #$30
+    ; --- DEBUG SENTINELS via LONG addressing to work-RAM scratch $40:7FE0 (bank-safe; absolute $07xx
+    ;     would hit ROM in bank $92). Capture a7(pre), a5, and the trap-frame resume-PC at (a7+2). ---
+    lda $407FE0
+    inc a
+    sta $407FE0          ; +0 fire counter
+    lda $3C
+    sta $407FE2          ; +2 a7 lo16 (pre-decrement)
+    lda $3E
+    sta $407FE4          ; +4 a7 hi16
+    ldx $3C
+    sep #$20
+    lda $400002,x        ; trap-frame PC bits23-16 (a7+2)
+    sta $407FE6
+    lda $400003,x        ; bits15-8
+    sta $407FE7
+    lda $400004,x        ; bits7-0
+    sta $407FE8
+    rep #$20
+    lda $7C              ; $0532 ori #$700,sr : mask |= 7
+    ora #$0007
+    sta $7C
+    ; --- $0536 movem.l d0-a6,-(a7) : a7 -= 60 (lo16 only, faithful to op_movem_pre) ---
+    lda $3C
+    sec
+    sbc #$003C           ; -60
+    sta $3C              ; new a7 lo16 ($3E hi16 unchanged)
+    sta $54              ; $54 = work-RAM write ptr
+    stz $56              ; $56 = reg slot (0,4,..,$38)
+swo_lp:
+    ldx $56
+    lda $0002,x          ; reg hi16
+    sta $50
+    lda $0000,x          ; reg lo16
+    sta $52
+    ldx $54
+    sep #$20
+    lda $51              ; bits31-24
+    sta $400000,x
+    inx
+    lda $50              ; bits23-16
+    sta $400000,x
+    inx
+    lda $53              ; bits15-8
+    sta $400000,x
+    inx
+    lda $52              ; bits7-0
+    sta $400000,x
+    inx
+    rep #$20
+    stx $54              ; advance write ptr (X += 4)
+    lda $56
+    clc
+    adc #$0004
+    sta $56
+    cmp #$003C           ; processed slots $00..$38 (15 regs); stop before A7 ($3C)
+    bne swo_lp
+    ; --- $053A movea.l $6(a5),a6 : a6 = BE long at (a5+6) ---
+    lda $34
+    clc
+    adc #$0006
+    tax
+    sep #$20
+    lda $400000,x
+    sta $3B              ; a6 bits31-24
+    inx
+    lda $400000,x
+    sta $3A              ; bits23-16
+    inx
+    lda $400000,x
+    sta $39              ; bits15-8
+    inx
+    lda $400000,x
+    sta $38              ; bits7-0
+    rep #$20
+    ; --- $053E move.l a7,(a6) : write new a7 as BE long ---
+    ldx $38              ; a6 lo16
+    sep #$20
+    lda $3F              ; a7 bits31-24
+    sta $400000,x
+    inx
+    lda $3E
+    sta $400000,x
+    inx
+    lda $3D
+    sta $400000,x
+    inx
+    lda $3C
+    sta $400000,x
+    rep #$20
+    ; --- $0540 movea.l $4a(a5),a4 : a4 = BE long at (a5+$4a) ---
+    lda $34
+    clc
+    adc #$004A
+    tax
+    sep #$20
+    lda $400000,x
+    sta $33              ; a4 bits31-24
+    inx
+    lda $400000,x
+    sta $32
+    inx
+    lda $400000,x
+    sta $31
+    inx
+    lda $400000,x
+    sta $30              ; a4 bits7-0
+    rep #$20
+    ; --- $0544-$054E  d0.w = ((a4).w & $cfff) | $c000 ; (a4).w = d0.w  (BE word) ---
+    ldx $30              ; a4 lo16
+    sep #$20
+    lda $400000,x        ; hi byte
+    sta $51
+    inx
+    lda $400000,x        ; lo byte
+    sta $50
+    rep #$20
+    lda $50              ; $51:$50 = BE word
+    and #$CFFF
+    ora #$C000
+    sta $50
+    sta $00              ; move.w d0,... : d0 lo16 = result (d0 hi16 $02 unchanged)
+    ldx $30
+    sep #$20
+    lda $51              ; hi byte
+    sta $400000,x
+    inx
+    lda $50              ; lo byte
+    sta $400000,x
+    rep #$20
+    ; --- $0550 bra $74c : re-enter the scheduler scan natively ---
+    lda #$074C
+    sta $40
+    stz $42
+    jml lh_sched         ; lh_sched scans current+1.. and exits via lhs_found (sec;rts -> re-fetch)
+
 ; ===================== JMP-TABLE STATE-HANDLER DISPATCH ($92:F900) =====================
 ; Reached from bank-$00 ojmp_hook via `jml $92F900`. $40 = the jmp(a0) target (a state-machine
 ; handler). Run with the CURRENT reg file (we're mid-task; no movem). The handler escape (--coroutine,
diff --git a/src/interp.pasm b/src/interp.pasm
index f421fbe..01f0de3 100644
--- a/src/interp.pasm
+++ b/src/interp.pasm
@@ -18357,7 +18357,7 @@ lh_chk_adbe:
     jmp lh_adbe          ; $ADBE: walking-bit WORD RAM test -> net memset 0 (721K instr)
                          ; ($3F86 byte verify retired -> subsumed by the generic gm_verify)
 lh_gen:
-    jmp lh_sched_pre     ; STEP C: check the scheduler-scan PC ($074C), else fall to gm_memclr
+    jmp swo_tramp        ; STEP C: $0532 switch-OUT trampoline, then $074C scan (lh_sched_pre), else gm_memclr
 lh_nofire:
     clc
     rts
@@ -19784,6 +19784,18 @@ oror_dir0:
     jsr ea_write
     jmp imm_pc
 
+; swo_tramp — scheduler SWITCH-OUT trampoline (STEP C). lh_gen's `jmp lh_sched_pre` is retargeted
+; here (zero-shift). A = $40 (PC). $0532 = the coroutine yield-trap handler -> dispatch the native
+; switch-out (escbank slot 19 @ $928039); any other PC falls through to lh_sched_pre unchanged.
+; Lives in the free $FFCA-$FFDF gap (zero-run before the vectors), so it adds no bytes to lh_gen.
+.org $FFCA
+swo_tramp:
+    cmp #$0532
+    bne swo_pass
+    jml $928039          ; entry_swo (escbank jmptab slot 19) -> does the save, jml lh_sched
+swo_pass:
+    jmp lh_sched_pre
+
 .org $FFE0
 .word $0000,$0000,irq,irq,$0000,nmi,reset,irq
 .org $FFF0
diff --git a/tools/gen_escbank_syms.py b/tools/gen_escbank_syms.py
index cb629bc..d9c9d42 100644
--- a/tools/gen_escbank_syms.py
+++ b/tools/gen_escbank_syms.py
@@ -15,7 +15,8 @@ NEEDED = ["inext", "rdw40_l", "wrw40_l", "rdb40_l", "wrb40_l", "push32_l",
           "rdw_ea_l", "readbyte_l", "writeword_l", "writebyte_l", "usmul_l", "op_rts_sentinel", "ojmp_hook",
           "jsrabs_hook",  # jah2_ext (escbank extension chain) tail-calls the original miss handler
           "bhp_after",    # jah2_ext_bsr tail-calls back into bsr_hookpush's miss continuation
-          "ors_pre"]      # an escbank escape's terminal rts routes here (bank-aware sentinel resume)
+          "ors_pre",      # an escbank escape's terminal rts routes here (bank-aware sentinel resume)
+          "lh_sched"]     # entry_swo (scheduler switch-OUT) tail-jumps into the native $074C scan
 
 sym_path = Path("src/interp.sym")
 esc_path = Path("src/escbank.pasm")
```

## Debugging BLOCKERS hit (solve these first next session):
1. SA-1 exec-hooks (add_exec_hook cpu_type=Sa1) do NOT fire on escbank bank $92 addresses
   ($92F86E got 0 fires) — can't bracket/measure escbank escapes by entry hook.
2. The $0710 PC-trap freeze can't isolate ONE $0532: df_gap does stz $0710 on every release,
   and runf granularity is 1 frame (all 21 $0532s pass). Need release-then-rearm WITHIN the tick.
3. The PC=$0000 crash runs garbage that CLOBBERS work-RAM sentinels after entry_swo writes them,
   so post-run reads show 0. Need to FREEZE on the FIRST entry_swo (e.g. a self-disabling guard
   in entry_swo that sets $0710=<something bank0> or spins) to read inputs/outputs pre-crash.

## Verified-correct by inspection (NOT the bug): trampoline+slot19 assembled right (cmp #$0532 /
jml $928039 -> jmp $F86E=entry_swo); movem-save layout matches op_movem_pre; mask=$7C|=7 matches
op_ori_sr; descriptor (a4).w=((a4)&$cfff)|$c000 matches; a6/a4 BE reads verified. Bug is subtle —
likely the SP-save ($053E move.l a7,(a6)) target or an ordering/state detail. Build a SINGLE-YIELD
differential (freeze-on-first-entry_swo, snapshot, compare escbank result vs interpreting $0532-$0550).
