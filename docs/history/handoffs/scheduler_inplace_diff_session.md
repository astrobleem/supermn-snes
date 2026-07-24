# TRACK B kickoff — re-firing-freeze instrument + in-place differential (session handoff)

Plan: close the realtime gap via the native scheduler context-switch (TRACK B). Full plan in the
approved plan file; this note covers the two **build-independent** artifacts produced this session
and the **local** steps that depend on the toolchain (dotnet+Poppy) and emulator (Nexen), which are
not present in the cloud container where these were authored.

## What changed this session (committed source, NOT yet built)

1. **`src/interp.pasm` — `df_gap` re-firing-freeze instrument** (Step 2 of the plan).
   - Gated the one-shot `stz $0710` on a new IRAM debug flag **`$0730 == $5A5A`**: when set, the
     `$0710` PC-freeze stays armed and **re-fires at the next matching PC**, so a harness can
     single-step yield-by-yield across one whole tick.
   - +8 bytes in the `$D1BF` gap (`lhs_rdbe`+`df_gap` ≈ 36 B in a 46 B gap → ~10 B slack before
     `.org $D1ED`). **Verify at build:** if Poppy errors on the gap overflowing `$D1ED`, apply the
     documented zero-shift fallback (replace `stz $0710` with `jmp dfg_rff_ext` and host the
     `lda/cmp/beq + stz` in the `$F9AA` gap). If any bank-$00 byte shifts, regen `b0_native`
     (`tools/dump_b0_native.py`).
   - **Inert in production**: `$0730` is 0 everywhere except the new harness, so every existing
     lockstep/cycle tool is byte-for-byte unaffected. Safe to keep permanently in the source, so it
     builds into BOTH `interp_committed.sfc` and `interp.sfc`.

2. **`tools/swo_inplace_diff.py` — in-place single-yield differential** (Step 3).
   - Drives the committed ROM and the escape ROM through ONE faithful ce4trip64 tick, re-firing-freeze
     at `$0532` (env `FREEZE_PC`, default), snapshots DP/reg-file + 64 KB work RAM at each yield, and
     reports the **first yield index where committed ≠ escape** plus the differing bytes.
   - No injection (yield_faithful.py PHASE B proved injection can't reproduce mid-tick state); reads
     the interp's own reg file (no MAME prefetch skew); relies on the re-firing freeze above.
   - Key correctness fact: `jsr dbg_fetch` (interp.pasm L231) runs **before** `loop_hook` (L239), so
     both builds freeze at `$0532` *pre*-switch-out symmetrically; the committed build then interprets
     `$0532-$0550`, the escape build runs `entry_swo`.
   - Masks the legitimately-divergent IRAM (PC ring `$0400-$05FF`, ring idx `$48`, instr counter
     `$4A/$4C`) so the real signal (work-RAM `$F0xxxx` + 68K reg file) stands out.
   - Compiles clean (`python3 -m py_compile`). Cannot be *run* in the container (no Nexen).

## Local workflow to resume (needs toolchain + Nexen)

1. **Re-apply the parked escape** from `docs/history/handoffs/scheduler_switchout_wip.md` (escbank slot 19 +
   `entry_swo`; interp `lh_gen`→`swo_tramp`@`$FFCA`; `gen_escbank_syms` `NEEDED += "lh_sched"`).
2. **Build both ROMs** (df_gap instrument is in `src/interp.pasm` for both):
   - committed (escape reverted, GREEN) → `build/interp_committed.sfc`
   - escape (entry_swo wired) → `build/interp.sfc`
   - Confirm the `$D1BF`-gap byte budget held (no Poppy overflow error).
3. **Re-confirm symptom:** `FULLDIFF python3 tools/lockstep_trap.py /tmp/supermn-scratch/ce4trip64 2F60 0`
   on the escape ROM → record the current DIFF (handoff §3 expects ~44 near `$F00001/2` + sprite coords).
4. **(Optional cheap diagnostic, Step 1):** `tools/sched_trace.py` on both ROMs, diff the dispatch
   sequences.
5. **Pin it:** `python3 tools/swo_inplace_diff.py /tmp/supermn-scratch/ce4trip64`
   → first diverging yield + bytes. Try `FREEZE_PC=075C` to bracket post-switch-out+scan if `$0532`
   (pre) is identical across yields. Extend `snapshot()` to also read `$41:0000+` if the divergence
   isn't in DP+workRAM.
6. **Fix `entry_swo`**, re-deploy, gate: ESC=0 GREEN + ESC=1 DIFF≤48 on ce4trip64 + trip2500/4000/5000;
   measure the cycle win (`CYCLES=1`; for an entry hook use the bank-$00 trampoline `swo_tramp`@`$FFCA`
   since SA-1 hooks don't fire on bank-$92).
7. **Switch-IN (Step 5):** reuse `swo_inplace_diff.py` with `FREEZE_PC=075C`/`07E4`.

## Self-test for the instrument (do once, locally)
- With `$0730=$5A5A`, confirm the freeze re-fires across all ~21 `$0532` of one tick (snapshot count ==
  switch-out count).
- With `$0730` unset, confirm a normal lockstep run is byte-identical to pre-change (no regression).
