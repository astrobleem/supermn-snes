# Superman (Taito X) → SNES/SA-1 — Project Status

Last updated: July 23, 2026. Per-area detail lives in the linked docs.
**Start any new session at [RECOVERY.md](RECOVERY.md).**

> ## ⚠️ R11 SECOND-v130-PLAYTEST RESPONSE — July 23, 2026
>
> Exact v130 is human-rejected. Before reaching the first wall, the tester froze while throwing a
> crate and while killing a silver enemy with a held charged shot. They also saw wrong tiles in
> Superman's attack animations, an upper-left gameplay crop, and a rotating boot logo that caused
> dizziness.
>
> Exact v131 response-candidate SHA-256
> `be0ed971b90ce4ce48e0c6b1ad3356eba41c5b12484c11506154ce40dbe8c1aa`
> uses a static indexed derivative of the supplied SA-1 logo with only an 8x8 palette-pulsed
> activity diamond, centers the MAME oracle's 384x240 view at arcade origin `(64,8)`, and
> quarantines every displayed OAM physical slot before high-water OBJ-cache reclamation. Twenty
> packed-manifest boundaries are exact; the full-cache fixture marks all 12 displayed slots and
> leaves both displayed/free and displayed/upload intersections empty.
>
> Fresh `TESTFLAG=0` Nexen and stock-Mesen-2.1.1 sequences remain live through real coin/Start,
> transition, two charged releases, enemy damage, and 600 post-release frames; the Mesen endpoint
> is frame 8,177 / tick 1,524 / render 1,472 / halt zero. A focused checkpoint with the current ROM
> renderer mirror explicitly refreshed visibly lifts and throws the crate through tick 1,483 at
> halt zero. That crate result is not an organic v131 stage run, and the exact charged shot killing
> a silver enemy has not been reproduced.
>
> v131 is an **interactive technical-demo response candidate, not playable or shippable**. It still
> needs the user's exact crate/silver-enemy/wall/viewport/boot retest; timbre, renderer conservation,
> aligned MAME pixels, a full playthrough, and formal performance remain open. v124's
> 29.7002 game-fps / 360,990.164 cycles/tick run remains the latest formal rate evidence. See
> [RECOVERY.md](RECOVERY.md) R11 and
> [the focused handoff](docs/handoff/V130_SECOND_PLAYTEST_20260723.md).

> ## HISTORICAL R10 WALL/AUDIO/BOOT CANDIDATE — July 23, 2026 (SUPERSEDED BY R11)
>
> The tester human-confirmed v128's post-TAITO title, pre-round bars, charged-shot, and gameplay-
> music repairs, then found a new first-wall mixed-tile freeze and excessive sample transposition.
> The wall crash was a zero-length bug in both background-reconcile helpers: `BEQ` consumed flags
> from `CMP #$0100`, entered a wrapped Y loop, crossed BW-RAM mirrors, and corrupted coroutine
> contexts. The repaired helpers are byte-exact for 6/6 empty/compact/full cases.
>
> Exact v130 candidate SHA-256
> `1ec22cbc92ad7beef0e20d8af6ff12f57023b7c437311f4bc6be56ce37cdd928`
> reaches the same wall replay at frame 12,372 / tick 3,622 with halt zero, 14 valid task stacks,
> 136-byte minimum margin, and no suspicious context write. A controlled 1,800-frame idle run
> activates enemy offense and changes health 20→18. The sound pipeline adds five note-aware
> source-octave anchors; exact SPC ARAM is byte-correct and a 29.985-second organic capture has no
> internal 200 ms or 750 ms digital silence. Musical quality still requires listening.
>
> The old black initialization interval now has an original Mode 7 rotating SA-1 shield and status
> text. Fresh Mesen 2.1.1 frames 150-450 remain in Mode 7 with 11 distinct images and a changing
> activity byte; at frame 5,150 the indicator is clear and the normal Mode 1 renderer owns the
> display. A fresh `TESTFLAG=0` run organically arms, accepts real coin/Start, and settles gameplay
> at frame 5,976 / tick 423 / halt zero. A same-hash Mesen coin/Start/charged-shot sequence has no
> failed checks (entry/continuation/tick hooks 2/2/321).
>
> This is still **not playable or shippable**. The first wall, octave timbres, and boot presentation
> await human confirmation; full-stage/playthrough, aligned MAME pixels, renderer conservation, and
> formal 30 Hz gates remain open. v124's 29.7002 game-fps / 360,990.164 cycles/tick run remains the
> latest formal performance evidence. See [RECOVERY.md](RECOVERY.md) R10 and
> [the focused handoff](docs/handoff/FIRST_WALL_OCTAVE_AUDIO_AND_BOOT_20260723.md).

> ## ⚠️ R9 EXACT-MESEN REGRESSION CORRECTION — July 23, 2026
>
> The tester's Mesen 2.1.1 reports were correct. After TAITO faded, the no-credit title alternated
> between a few visible frames and a long black interval because the queued renderer copied retired
> zero palette `$41:6800`. The pre-round bars came from mid-screen forced-blank DMA, large transition
> uploads could outlive VBlank and mix tiles, and arcade overlay command `$19` loaded a standalone
> TAD credit track that replaced the active song.
>
> Exact v128 candidate SHA-256
> `7c4b757ddf5c0297eb1b3aa65f4f6d74ecf289fdfa5f70d0d71811843906db57`
> uses live palette `$41:2000`, NMI/VBlank DMA publication with chunked/size-aware transfers, and
> suppresses `$19` while a song is active. A fresh exact-Mesen capture keeps all 16 post-TAITO title
> samples visible. A same-ROM real-input sequence records coin/Start, the 450-frame Clark transition,
> and a 272-frame B charge plus 360 post-release frames with no stall; it ends at frame 7,935 /
> tick 1,403 / render 1,342, halt zero. Gameplay audio has no internal 200 ms or 750 ms digital
> silence, but it is not musically validated.
>
> This candidate is still **not playable**. A checkpointed 1,200-frame Nexen ordering window remains
> live and balanced at 600 ticks/requests/ACKs, but completes 568 true renders and adds 31 queue
> coalesces during cache-heavy bursts. No formal cold-boot rate result supersedes v124's 29.7002
> game-fps measurement. R10 above records the later human confirmation of v128's four focused
> repairs; the renderer-conservation failure remains current. See [RECOVERY.md](RECOVERY.md) R9 and
> [the focused Mesen handoff](docs/handoff/MESEN211_PLAYTEST_REGRESSIONS_20260723.md).

> ## ⚠️ R8 CHARGED-SHOT CORRECTION — July 23, 2026
>
> Exact v124 froze when a held Button 1 charge was released. The `$00D3B0` native handler started
> at `$92:EFFB` but crossed a later fixed `.org $F000` island; Poppy silently let that island
> overwrite 201 bytes in the middle of the handler. Exact v127 candidate SHA-256
> `1a8a5742536b6142a42387546524bb0e785fac508a01e6ff5e5c53027b06db35` relocates the full body to
> audited `$94:B400` space and adds pack-time seam assertions.
>
> Real-controller holds of 96, 120, and 180 video frames are green; the longest observes 600 game
> ticks and 600 completed renders over 1,200 post-release frames with halt zero and a 138-byte
> minimum stack margin. Normal punch/jump, enemy offense, optest 160/160, and opsweep 782/782 remain
> green. A fresh `TESTFLAG=0` smoke also organically arms the gates and reaches gameplay at halt
> zero. This is a charged-shot-fixed **playtest candidate**, not a playable verdict or a new FPS
> result. v124's 29.7002 game-fps measurement remains the latest formal rate evidence. See
> [RECOVERY.md](RECOVERY.md) R8 and
> [the focused handoff](docs/handoff/CHARGED_SHOT_FREEZE_20260723.md).

> ## ⚠️ R7 USER-PLAYTEST CORRECTION — July 22, 2026
>
> The first real v105 playtest disproved the **playable** label below. It eventually booted and
> accepted coin/Start, rendered movement/enemies/backgrounds, and played recognizable music, but
> player attacks did nothing, enemies did not damage Superman, and the soundtrack audibly cut out.
> The combat root cause was `$012B6C` returning every one of its 34 BSR callers to `$01177C`.
>
> Retained v124 (ROM SHA-256 `777507c9…`) propagates the real return PC. It is green for 35/35
> focused MAME cases and 4/4 live combat-spine differentials; attack/jump visibly respond, and an
> 800-frame idle window activates enemy attacks and changes health 20→18. Its formal power-on result
> is stable through tick 2,210 but measures **29.7002 game-fps / 360,990.164 cycles/tick**, missing
> both explicit 30 Hz thresholds. Current verdict: **combat-fixed near-30 Hz technical demo, not
> playable or shippable**. Audio transport remains organic, but ignored/placeholder SFX, trimmed
> samples, and incomplete pitch/LFO/portamento transcription make the music musically unvalidated.
> Final-v124 interpreter gates are optest 160/160 and opsweep 782/782. See
> [CONFESSION.md](CONFESSION.md) and [RECOVERY.md](RECOVERY.md) R7.

> ## HISTORICAL R6 PERFORMANCE RESULT — July 22, 2026
>
> [CONFESSION.md](CONFESSION.md) and [RECOVERY.md](RECOVERY.md) R6 supersede the old performance
> banners below. Exact production candidate v105 (ROM SHA-256 `72d925ac…`) now clears the defined
> playability gate from power-on: 1,802 real game ticks in 3,603 uninterrupted SNES video frames =
> **30.0083 game-fps**, at **357,281.999 mean SA-1 cycles/tick**. The same continuous trace observed
> 1,802 requests, 1,802 unit ACKs, and 1,802 true draws with zero queue drops; real input, sound ring,
> ROM/WRAM mirror, all 16 task stacks, and halt state remained healthy through tick 2,230—well past
> the former 765/767 ordering failure. Final-ROM MAME gates are 160/160 optest and 782/782 opsweep.
> This was the R6 evidence-backed playable verdict. R7 supersedes that label after real playtesting;
> the timing, renderer, input, and scheduler measurements remain valid historical evidence for exact
> v105. The remainder of this file is retained as engineering history and partial evidence.

> ## ⚠️ SOUND PORT — INTEGRATED, AUTOMATED GATES GREEN, MUSICAL VALIDATION INCOMPLETE
> The full TAD/YM2610 sound port is done and verified end to end: real FM instruments
> (ymfm-rendered patches, per-note switches + carrier-TL velocities) + arcade-verified
> ADPCM-A drums; ONE consolidated 21-song project (62.0/64KB ARAM, 3.5KB SFX headroom);
> multi-bank blob at `$ED:002B` (unskewed; glue symbols generated); the GROUND-TRUTH
> arcade command map for all 21 tracks (music ids = the contiguous `$05-$19` block —
> obtained by stimulating every byte on the arcade machine and fingerprint-matching the
> YM2610 output; corrected two P2 correlation guesses) wired through a 128-entry
> `snd_map` table via `Tad_LoadSongIfChanged`. Verified with independent oracles: ARAM
> uploads byte-perfect vs `tad-compiler`'s own exports (incl. the bank-`$EE` DataTable
> carry path), 8/8 random-power-on boots, live trigger-injection chains, and audio
> playing WHILE the game runs. Docs: `tools/sound/README.md` (pipeline + close-out),
> `docs/SOUND_COMMAND_MAP.md` (byte map + method). Remaining (non-blocking): the by-ear
> listening pass, real SFX authoring, rights review (tracks 3/8/19 = John Williams). R7 confirms
> these are audible fidelity defects, not merely optional release polish.

> ## ✅ COLD BOOT RESTORED + LOOP_HOOK ROOT-CAUSED (2026-07-10/11, `sound-p3`)
> Production cold boot had been silently dead for months (code growth covered the
> `$F600` TESTFLAG — the second occurrence of that failure class; relocated to `$F7E0`
> with a build-time assert). That exposed and led to root-causing the whole loop_hook
> failure family via the interp's BUILT-IN debug plumbing (the always-on 68K PC ring at
> IRAM `$0400` + the `$0710` PC-freeze — no MAME lockstep needed): (1) an `.org` overlap
> had truncated/buried three lh handlers under gm_verify (bodies relocated to escbank5
> behind stubs; slack seams now build-asserted); (2) the generic matchers were unsound
> in gameplay (gm_verify now actually verifies; exit-CCR set everywhere; count==0
> guards); (3) the `$0818` idle-collapse's "fire the IRQ now" corrupted a coroutine
> context at a fixed game event — re-shipped as a CLAMP (`$AC` lowered to `$2000`,
> never raised), keeping ~18x game speed, soak-verified through the event repeatedly.
> Accelerators (lh + all escapes) now arm via `snd_vframe` AFTER the boot self-test
> (ring-init signature `$00F01C2x`). Full regression suite green on the ship config.
**Repo consolidated 2026-07-05: PRs #1–#13 ALL MERGED — `main` is the single source of truth; branch off `main` for pt.22.**

> ## ⭐ DIRECTION SET (user decision 2026-07-04): 30fps retarget + SOUND — realtime-60 abandoned
> The CP0 STOP-rule fired (optimistic projections still 2.2-3.1× over the 60fps budget = at the
> ISA floor), and the fork is settled: **logic at 30Hz / display at 60Hz (budget 358K cyc/tick,
> tick = 2 display frames) + the TAD/YM2610 sound port in parallel.** Coverage state at the
> decision: trip2500 9.28×, light 7.44×, quiet 7.27× (PRs #1-#10). Sound kickoff shipped
> (PR #11): 21/21 arcade VGM tracks converted to TAD MML projects, compile-checked, SPC render
> proven; remaining = the musical pass + engine integration (TAD driver, SPC700 upload,
> sound-command mailbox → TAD triggers). Steering: docs/PROFILE_CAMPAIGN.md.

> ## ✅ pt.21 RENDER-TO-WRAM — SHIPPED + VALIDATED, small win (PR #13 MERGED, `50dfc62`+`3c79000`)
> Relocated the 5A22 render to WRAM `$7F` via a verbatim same-offset copy (`rc_copy` mirrors
> $E9:8000-$8FFF → $7F:8000 at boot; the $8004 wrapper jml's the $7F copy) — simpler than the
> pt.20-plan's `$7E:D000` re-assembly. Byte-faithful, zero-shift, smoke-GREEN, render **provably
> runs from $7F**. **BUT measured win = ~3.4% (~68K/combat-tick), NOT the projected ~27% (~550K):**
> the render is DMA/$7E-write-heavy, so its code-fetch (the only WRAM-recoverable share) is a minor
> Bus-A conflict. **Render lever SPENT.** Harness lesson: the NAT strands the 5A22 out of its
> supervisor loop ($00:D161) → render is dead under NAT/injected harnesses; measure on a FRESH boot
> (`tools/measure_render_wram.py`). Memory `render-to-wram-pt21`; docs/PROFILE_CAMPAIGN.md §pt.21.
> **NEXT (pt.22): re-rank levers — 30fps pacing change / scheduler rewrite (244K) / contiguous (335K).**

> ## ✅ 5A22-CONTENTION PROBE + WRAM SUPERVISOR — SHIPPED `8933076` (2026-07-04, PR #12 MERGED)
> The combat tick's "unattributed 1.08M" is mostly **5A22↔SA-1 bus contention**: the video
> supervisor busy-polled from ROM at 100% duty, taxing the SA-1 +1-2 cyc per ROM/IRAM access and
> doubling BW-RAM (Nexen `Sa1Cpu::ProcessCpuCycle`, hardware-shaped). Parking the 5A22 measured
> **411K/tick light (28.8%) / 578K combat (28.7%)**. Fix shipped: the supervisor loop now
> EXECUTES FROM WRAM ($7E:F000 blob; throttled IRAM poll; `jsl $E98004` → per-tick joy+render;
> zero-shift + old-save-state-resume-safe). **Light free-run 1.426M → 1.137M cyc/tick (−20%,
> 3.18× of the 30fps budget).** Combat unchanged (~2.0M): its 5A22 renders ~100% of the wall
> window, so the tax there is RENDER-code ROM fetches → **next lever: relocate the render inner
> loops to WRAM too** ($7E:D000 has room; video.bin is ~2.4KB). THE LATCH RULE for all future
> 5A22 idle work: `_memTypeBusA` latches — wai/stp fetched from ROM fake-conflicts forever; idle
> code must EXECUTE from WRAM. Tools: contention_probe.py / contention_combat.py /
> validate_wl_fix.py; memory `contention-probe-wram-supervisor`.

> ## ✅ HLE SPIKE — GO verdict, SHIPPED `0aac3c6` (2026-07-02)
> Hand-wrote the `$012B6C→{$012B84,$012C04}` tree as native 65816 (`hle_12b6c`, escbank2 `$94:E000`;
> dispatched by the new bank-aware `bhp_bank_ext` bsr catch, zero-shift). **Bit-exact** (ESC=full
> FULLDIFF identical 4-byte set, ESC=0 GREEN, smoke OK) and ships ENABLED (rides `$071A`).
> **Measured** (ce4trip64, production gates, spin-free `tools/hle_span.py`): interp **82,019 cyc** →
> HLE **34,746 = 2.36×** end-to-end; the replaced marshalling alone 1,572 vs ~49K ≈ **30×**.
> **Load-bearing corrections:** the prior 11,300 "interp baseline" was a spin-pollution artifact →
> the pt.15 "contiguous-compile LOSES to interp / loop_hook collapses loops to ~free" conclusion is
> **INVERTED** (the transpiled tree actually beat interp 2.2-3.2×; Option B is back on the table);
> `$012B84` has NO loop (straight-line marshalling — the loops are in its `jsr(a1)` callee `$0CE4`);
> hand-native beats the transpiled body **1.62×** on the same function (entry_ce4 24.5K vs ce4t 39.7K).
> **Campaign shape (GO):** (1) make the remaining ~1040 interp instrs/tick native (~2K cyc each,
> ~2.1M of the 3.8M combat tick) — transpile where possible, HLE where transpile fails (the
> state-cluster floor); (2) hand-rewrite the hottest native bodies (1.6×). Effort: ~half a session
> for this 51-instr 3-fn tree; est. 2-4h per marshalling-class routine, 1-2 sessions per loop-heavy
> body. Pattern confirmed toolchain-clean (standard escape slot + validation → Gigandes-safe).
> Details: memory `hle-spike-verdict`; measurement tool `tools/hle_span.py` (df_spin exec-hook,
> same-run deltas only; HLE-off arm must poke BOTH bank-$00 ROM copies).

> ## ✅ BANKED — Phase-2 escape/codegen sprint complete (2026-07-02, branch `boot-scheduler-progress`)
> The escape-coverage + transpiler-correctness work of this sprint is committed, pushed, and validated
> bit-exact. **Banking here** — the mechanical/scheduler/background/HUD levers are captured, the
> transpiler is now correct + cheaper, and the remaining moderate cost is dynamic-dispatch game-logic
> that does not escape cleanly (the coverage floor). Realtime (~24-40× over the 179K/frame budget) is
> NOT reachable by more coverage; the next move is a strategic-direction decision, not another campaign.
>
> **Shipped this sprint (all bit-exact: ESC=0 regression unshifted, vs-MAME GREEN, 20-tick self-diff 0 LIVE):**
> | | what | commit |
> |---|---|---|
> | Campaign 1 | native scheduler SWITCH-IN (`entry_swin`) | `2e39b98` |
> | Campaign 2 | heavy-tick background loops (`8fat`/`fd2t`) — heavy tick **−48%** | `5aea367` |
> | Campaign 3 | HUD decimal formatter (`entry_c9a6`) | `11078ba` |
> | Campaign 4 | native scheduler SELECT (`lhs_sel`) — biggest moderate lever, zero-shift | `0a36f95` |
> | transpiler fix | 32-bit `.l` cmp/cmpi/cmpa/tst/sub flag codegen (+ `val_branch32.py` guard) | `97d5049` |
> | transpiler fix | dbra-fallthrough CCR gap → **escbank2 now 0 hand-patches** | `8600fc6` |
> | codegen | 16-bit `INLINE_MEM` — ~2× cheaper inline work-RAM access (all escapes) | `c4a5e60` |
>
> **Cumulative (full-on, all escapes armed):** moderate GAME_TICK 4666→3714 interp-instr, heavy 8010→2917.
>
> **Coverage FLOOR reached (Campaign 5 verdict, `51c017f`):** the remaining moderate clusters
> (`$01C9xx` object-processor — a >300-instr coroutine with dynamic `jsr(a4)`, doesn't transpile;
> `$00CBxx`/`$023xx` jump-table/coroutine fns; `$012xx` mid-flow) are core game-logic — no clean,
> low-risk escape. Both transpiler CCR gaps are closed, so future escapes transpile correct.
>
> **STANDING DECISION (the realtime goal, deferred to the user — see MAIN_PLANNING_HANDOFF.md pt.11):**
> more coverage won't close the ~24× gap. Options: (a) codegen efficiency (bounded ~1.2×);
> (b) a big game-logic transpile (blocked — needs major transpiler work, bridge-dominated);
> (c) **accept sub-realtime & bank** (this snapshot); (d) re-architect hybrid→full-AOT. No work is
> queued against realtime pending that call.

> **UPDATE 2026-07-01 — rts-class dispatch is RESOLVED; a transpiler flag bug was found + fixed.**
> The "rts-class dispatch fires 0×" blocker below is superseded: a bank-$00 `jsr choke_tramp` FETCH-
> CHOKEPOINT at the interpreter's `lh_off` routes the about-to-decode PC through the AOT table, so
> rts/branch-reached hot handlers dispatch natively regardless of reach. `$0CE4` (entry_ce4t) — the
> hottest cluster — now dispatches **bit-exact** (all 6 ce4 triples + 20-tick self-diff). An every-
> fetch cross-bank `jml` round-trip is FATAL; the bank-$00 `jsr`/`rts` trampoline is the fix. This
> exposed + fixed a **transpiler D1 gap**: escapes never wrote the 68K CCR memory an interp-caller
> reads after `rts` (stale flags → the trip1000 divergence); `transpile.py` now materializes the CCR at
> branch-to-exit edges (`emit_ccr_native`). ce4t regenerated from the fixed transpiler. Strategic
> picture UNCHANGED (still 24× over budget; codegen is the wall — the chokepoint is a dispatch enabler +
> correctness fix, not the 24×-closer). See [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md) top
> block + memory `fetch-chokepoint-rts-escape`.

> **UPDATE 2026-07-02 (pt.8) — dbra-CCR transpiler gap CLOSED `8600fc6`; escbank2 fully transpiler-gen.**
> The Campaign-2 dbra-fallthrough CCR hand-fix is now in the transpiler (emit_ccr_from_value + main-loop
> dbra-to-exit detection). Re-transpiled 8fat/fd2t (hand-fix removed) + ce4t clean. **escbank2 now has 0
> hand-fixes** — both transpiler CCR gaps (32-bit .l flags + dbra-fallthrough) closed. All GREEN
> (ESC=0 unshifted; vs-MAME; 20-tick self-diffs 0 LIVE; val_branch32 5460/0). See handoff pt.13.

> **UPDATE 2026-07-02 (pt.7) — Codegen efficiency: 16-bit INLINE_MEM shipped `c4a5e60`.**
> Inline work-RAM access rewritten 8-bit byte-by-byte → 16-bit `lda $400000,x`+`xba` (LE load+swap =
> 68K BE word): ~2× cheaper on EVERY inline word/byte access, all escapes uniformly (distinct from the
> bounded --workram). Rolled out to ce4t/13bet/29b6t/295at (~309 native ops/tick removed); bit-exact
> (ESC=0 unshifted; vs-MAME GREEN; 20-tick self-diffs 0 LIVE). Codegen is polish, not the realtime
> closer. (Campaign 5 gate found no clean coverage escape left — strategic fork stands.) See handoff
> pt.12 + memory `inline-mem-16bit-codegen`.

> **UPDATE 2026-07-01 (pt.6) — Campaign 4 COMPLETE: native scheduler SELECT shipped `0a36f95`.**
> `lhs_sel` ($075C-$0778 task-select+readiness, the biggest moderate lever) via a ZERO-SHIFT
> lhs_found→`jml $92FD00` (5B→5B; no bank-$00 space fight). Completes lh_sched→select→entry_swin.
> All gates GREEN (ESC=0 regression unshifted; 20-tick self-diff 0 LIVE ×3; composes with entry_swin
> + full-on 0 LIVE). Measured: moderate −110 interp-instr/tick (10 selects; ~7%). Cumulative C1-4
> full-on: moderate 4666→3714 interp-instr, heavy 8010→2917. Also this session: the transpiler 32-bit
> .l flag bug FIXED properly (97d5049, guard tools/val_branch32.py). See MAIN_PLANNING_HANDOFF.md pt.10.

> **UPDATE 2026-07-01 (pt.5) — Phase-2 Campaign 3 COMPLETE: HUD formatter shipped `11078ba`.**
> `entry_c9a6` ($00C9A6 number→ASCII decimal, the hottest leaf of the $C8C0-$CAFF HUD cluster;
> bsr+jsr.l → both jah2 chains, $94 cross-bank). ESC=1 heavy: 3.14M → 2.80M cyc (−337K/3 fires).
> All gates GREEN (all-off regression unshifted; ESC=1 c9a6-ON matches the MAME oracle). **Surfaced a
> GENERAL transpiler bug** (`.l` cmp/cmpi/cmpa/tst compare only the LOW word — `ea_load_A` is
> `.w`-only); hand-fixed cmpi.l+tst.l in the body, proper transpiler fix TODO (matters for Gigandes).
> See MAIN_PLANNING_HANDOFF.md pt.7 + memory `transpiler-32bit-flag-bug`.

> **UPDATE 2026-07-01 (pt.4) — Phase-2 Campaign 2 COMPLETE: heavy-tick background loops shipped `5aea367`.**
> ALLSTREAM profile gate found 62% of the heavy tick's remaining interp = the $0008FA block-copy +
> the $0FB8 fill's **IRQ-slice mid-loop resume at $0FD2** (a NEW reach class: ISR-exit rte lands at a
> mid-loop PC — only the fetch-chokepoint catches it). entry_8fat + entry_fd2t shipped via choke_tramp
> arms (zero-shift). All gates GREEN (0 LIVE ×3 triples; MAME GREEN ×3; ESC=1 unchanged). **Heavy tick
> 12.3M → 6.35M cyc (−48%, ~70× → ~35× budget); moderate −14%; quiet noise.** Transpiler gap found
> (dbra-fallthrough CCR; hand-patched, proper fix TODO). See MAIN_PLANNING_HANDOFF.md pt.6 block.

> **UPDATE 2026-07-01 (pt.3) — Phase-2 Campaign 1 COMPLETE: scheduler SWITCH-IN shipped `2e39b98`.**
> `entry_swin` ($0796→movem-restore→rte, escbank $FB00 + swo_tramp arm) deployed & fully validated:
> gate-off bit-identical; single-tick vs MAME GREEN ×3 triples; 20-tick SP-aware self-diff 0 LIVE ×3;
> bit27 wake-up path closed synthetically (`tools/synth_swin_b27.py`); composition CHOKE+SWIN GREEN
> (heavy 12.78M→9.87M cyc). **Model correction:** the "19–28 restores/tick" below was a 2× sched_trace
> WINDOW artifact (trap never fires ⇒ ~2-tick stream) — true rate 11/4/1 per tick (mod/heavy/quiet),
> measured win ~0.5M cyc/tick (~6%) moderate. See the top of
> [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md) + memory `scheduler-switchin-shipped`.

> **UPDATE 2026-07-01 (pt.2) — chokepoint generalized ($13BE, shipped `a013dee`); Phase-2 plan APPROVED.**
> Reconciled activity-spectrum budget (bit-exact): per-tick cost is scene-dependent 2.7M(quiet)..12.6M
> (heavy combat) cyc — worst-case ~70× budget. Measured-cost gate picked the first Phase-2 campaign:
> **native scheduler SWITCH-IN** (~19–28 restores/tick, ~0.9–1.5M cyc/tick), rejecting the structurally-
> tempting-but-COLD ce58 call-tree (0× measured). **NEXT ACTION: execute
> `/home/chad/.claude/plans/yes-please-enter-plan-splendid-brooks.md`** (self-contained, cost-confirmed;
> start at task #10). See the [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md) "IMMEDIATE NEXT ACTION".

> **UPDATE 2026-06-30 — read [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md) for the
> authoritative current state.** Two things below are now CORRECTED:
> - **rts-class table dispatch fires 0× in gameplay** (verified with SA-1 exec-hooks). The "rts
>   class unified bit-exact / ce4t fires 63451×" claim was a corrupted `$07xx`-counter artifact;
>   `ce4t` never runs. Hot handlers ($CE4/$13BE) are reached via the scheduler's rte→rts chain,
>   which bypasses the table. Only the **jmp-state** and **coroutine (rte-resume)** classes fire.
> - The bottleneck is the **coroutine scheduler**, not dispatch. This session: shipped `entry_c172`
>   (first COROUTINE escape, table 12→13) and `lh_sched` (native scheduler disabled-task-skip via
>   loop_hook) — interpreted gameplay cost dropped ~125/tick ($0740 region 246→121). The `$AC`
>   frame-charge question (#73) is resolved (esc_ac_charge works; residual $1401 is vblank timing,
>   not $AC). See the handoff §1 + the `scheduler-escape-loophook` / `coroutine-shells-low-value`
>   / `rts-class-dispatch-nonfunctional` memories.

> **UPDATE 2026-06-30 (pt.3):** the scheduler is now understood as a coroutine CONTEXT-SWITCHER —
> `lh_sched` only collapsed the `$074C` scan; the switch-IN/OUT machinery is **~30% of the tick** and
> is the biggest collapsible lever (`tools/sched_trace.py`). A native switch-OUT was built — **body
> PROVEN bit-exact** but a ~44-byte integration divergence is unpinned, so it's **reverted (build is
> GREEN)**. STRATEGIC: the SA-1 cycle meter shows we're **24x over the 60fps budget** and **codegen
> (not coverage) is the wall** — see handoff §0. New single-yield differential toolchain + memories
> `scheduler-context-switch-lever` / `cycle-budget-realtime-gap`.

> **The engine is named Cambium** — the graft-union layer where rootstock and scion fuse. It is
> the whole graft system: the 68K **interpreter rootstock** (`src/interp.pasm`) + the transpiled
> native **scions** (escbank/escbank2, `tools/transpile.py`) + **the global AOT dispatch table that
> unites them** (`xlat_dispatch`). The name points at the dispatch union — that, not the codegen, is
> the crown jewel. Cambium belongs to the Game Garden botanical family (Poppy/Peony).

## CURRENT STATE (June 29) — DIRECTIONAL PIVOT to AOT; one dispatch table replaces per-target hooks; PoC proven

The project changes gear from **hand-escaping one hot cluster at a time** to **ahead-of-time
(AOT) transpilation**. The realization (forced by the per-cluster grind — see the `$D5A0` saga
below): the transpiler already produces bit-exact native code per function; the *one* hard,
recurring problem is **dispatch** — every hot cluster turned into a multi-hour hunt for how its
control transfer (jmp/rts/rte/coroutine) is reached, with a bespoke hook per case. AOT flips it:
build **ONE global 68K-PC→native-entry table** that all control flow consults (hit → run native,
miss → interpret). That converts "every dispatch is a custom hunt" into "one indirection," and is
the single piece that makes coverage *compose* instead of fighting back. The interpreter is
demoted from engine to cold-path fallback. Everything we'd been doing with hooks is a hand-rolled,
per-case version of that table.

- **Dispatch-table PoC — PROVEN bit-exact** (`val_frame_diff` GREEN; 3 escapes across 3 pages).
  The machinery, all reusing existing tools:
  - `tools/gen_xlat_table.py` builds a 2-level page table (page[PC>>8] → 256-entry sub-table of
    3-byte native addrs; 0 = miss) offline from the escape banks' `.sym` + the `transpiled from`
    comments. Placed at file `$2B0000` = **SA-1 `$96:8000`** (free MMC-window bank, verified
    live-readable by the executing CPU, not just the debugger).
  - `xlat_dispatch` (escbank2 `$94:F900`) indexes it; `ojmp_hook` now `jml`s there instead of its
    hardcoded cmp-chain → `ojmp_disp` re-scan. HIT → dispatch native, MISS → `jml inext`.
  - Two gotchas burned in: `jml [abs]` is **Poppy-mis-sized** (tracks 2 / emits 3 → branches land
    on a `BRK` → hang); use **push PBR + push (lo16−1) + RTL** instead. And diagnose dispatch hangs
    with a DIAG build that computes-but-always-misses (records to scratch, never jumps).
- **The table earns its keep immediately — it exposed a latent escape interaction.** Routing
  *real* dispatch through the table surfaced that `entry_d386`/`entry_d3b0` (`$D3` jmp-state
  handlers) each run bit-exact ALONE but **diverge when co-dispatched alongside `entry_d0d0`** — a
  shared `$D0`-`$D3` state-machine interaction the old per-target cmp-chain silently never
  exercised (it never co-dispatched them; cf. the vacuous-GREEN `$D5A0` had). Excluded from the
  table (→ interpreted, bit-exact) pending a separate debug. This is the AOT thesis in action.
- **`$D5A0` closed (the pivot's trigger).** An 8-instr leaf reached only by `bra` *inside* the
  already-escaped `$D5C4` handler (NOT a jmp-table target — the ojmp approach was structurally
  wrong); `entry_d5c4` was bailing to the interpreter at that branch. Fixed by `jml entry_d5a0`.
  Bit-exact. The hours this took (5 min to transpile, the rest dispatch archaeology) is the
  argument for the table.
- **NEXT (the AOT build-out, in order):** (1) convention-unify so the jsr/coroutine classes share
  one table (the jmp-state class is convention-uniform today); (2) move the lookup to the **`inext`
  chokepoint** — one edit catches every transfer, convention-free, and is cheap precisely because
  the interp is demoted; (3) scale bank allocation to `$80`-`$9F` (~20+ banks for full coverage);
  (4) batch-transpile from the CDL block list (`g1-coverage`); (5) build a **divergence-bisection**
  harness (first divergent block) to validate at scale; (6) debug the `d0d0`/`$D3` interaction.
  See `aot-dispatch-table` memory + task #70.

## CURRENT STATE (June 27) — realtime budget MEASURED; ~25 escapes deployed; both gates green

Bulk transpilation continued, and the **realtime budget is now measured** — the decisive
go/no-go number the project hinged on. Headline: **the per-frame game logic is only ~2,400
68K-instructions**, not the 28,672 IRQ-pacing countdown, so the SA-1 budget closes at full
native coverage with headroom. Playable (incl. 60fps) is realistic; the remaining work is
bounded — transpile the per-frame hot path toward ~99% native coverage.

- **Frame budget (measured, one gameplay frame; `f450n.tr` + `analyze_trace68k.py`).** Of
  ~13,000 68K-instr/frame, **~82% is the `$0818` idle spin** (the 68K spinning until the vblank
  IRQ); **real game logic is only ~2,391 instr/frame**. At full native (~18 cyc/instr transpiler
  codegen) that's ~43K SA-1 cycles vs the ~178K/frame budget — **~4× headroom, 60fps fits**. The
  deployed escapes cover **~40%** of real per-frame work; **~18 functions cover 99%** (→60fps).
  It's a coverage *cliff*: the interpreted tail dominates until ~99% (the interp measured
  ~16,500 cyc/instr, ~4× the old estimate). Tools: `tools/measure_fps.py`, `tools/onon_capture.py`.
- **`$0818` idle-spin COLLAPSED** (`loop_hook`): detect the spin → fire the vblank IRQ immediately
  instead of interpreting ~26K dead spins/frame (~10× faster). Measured game-fps now **0.27
  (escapes off) / 0.40 (escapes on)**, up from sub-0.05. Real 60Hz pacing comes from the 5A22-side
  vblank, not this wait.
- **~25 escapes wired** (was 8). The **escape bank** (ROM file `$290000` = SA-1 `$92:8000`) is a
  2nd executable SA-1 bank (32KB free) holding **18 transpiler escapes** (`transpile.py --bank1`);
  plus the bank-$00-gap escapes (`$025110` bridged collision, `$0020e8` video, the `entry_ce4`/
  `entry_111a` hand oracles, and leaves). The "bank-$00-full" problem is solved — multi-bank is no
  longer a blocker. See `escape-bank` memory.
- **Transpiler hardened + faster.** Fixed `move.l` with memory EAs and **`sub`-to-memory writeback**
  (it was emitted as a flagless `cmp` — a real bug a frame-sharing list-walker exposed). New
  **memory-access inlining**: `$40` BW-RAM ops inline `lda $400000,x` instead of a `jsl` helper call
  (−26 SA-1 cycles/op), applied to all 18 escape-bank escapes (verified behavior-preserving via
  ON-vs-ON `onon_capture`).
- **New validation — escape-vs-MAME ground truth** (`tools/val_cc10_mame.py` + `extract_exit.py`):
  inject a MAME-captured entry frame on the deterministic native base, run the escape to the trap,
  diff its work RAM against MAME's exit. Bypasses the non-deterministic synthetic-jsr OFF reference.
  (Gotcha: capture a leaf's exit at the RETURN address, not its `rts` — MAME read-taps are
  prefetch-stale and miss the last store.)
- **Both interp gates GREEN: `opsweep` 782/782** (op×EA grid) **+ `optest` 154/154** (curated
  per-opcode vs MAME). optest was ported to the SA-1 memory model (`Sa1Memory`/`snesMemory`) — the
  earlier "optest deprecated" note is RETIRED.
- **NEXT** = transpile the named hot functions toward 99% per-frame coverage (path to playable):
  `$003A92` (the GAME_TICK dispatcher, ~15 indirect-jump sites/frame), `$001008`, `$00158E`,
  `$0008C2`, `$004A9E`, `$00C9F8`. ~6 → ~90% (~10fps); ~12 more → 99% (60fps). See `ROADMAP.md`.

## CURRENT STATE (June 25) — superseded by the June 27 state above; transpiler AUTOMATED, bulk transpilation underway

The interpret-cold/transpile-hot hybrid is now a **working production pipeline**, not just a
mechanism. An **automated 68K→65816 transpiler** (`tools/transpile.py`) replaces hand work, and
the hottest gameplay functions are transpiled to native 65816 and **deployed in the live ROM**.

- **Transpiler tool — BUILT + validated bit-exact.** Capstone-decodes a 68K function and emits a
  native escape (`entry_<addr>`) operating on the interpreter's DP register file. It reproduces
  the hand-written, MAME-validated oracles `entry_ce4`/`entry_111a` byte-for-behavior (flyval
  ON-vs-OFF=0). Codegen covers the full EA matrix, the signed-branch lowering (D1), `link`/`movem`
  (incl. the `movem.w` sign-extension), byte/word/long ops, shifts, `moveq`, `dbra`, and two
  extension paths:
  - **Call-bridge** (non-leaf functions): each `jsr`/`bsr` hands control back to the interpreter
    via a `$00FF:cont` sentinel return (`op_rts_sentinel` resumes the native continuation); the
    callee runs interpreted. Validated end-to-end.
  - **`--video`**: non-frame stores route through `writeword`/`writebyte` → the `$41` video shadow
    (`$B0/$D0/$E0`), `$40` for work RAM. Validated by diffing the shadow, not just work RAM.
- **Hot functions transpiled + deployed** (all bit-exact vs the MAME-validated interpreter, all in
  free **bank-$00 gaps** — no ROM-layout change needed):
  | escape | 68K fn | ~%frame | kind |
  |---|---|---|---|
  | `entry412` | `$000412` | RNG | leaf |
  | `entry_cb9e`/`entry_15b4`/`entry_3e6a` | sprite pos / block copy / classifier | — | leaf |
  | `entry_ce4` | `$000CE4` | ~12.5% | hottest in-game (sprite/object builder) |
  | `entry_111a` | `$00111A` | ~5.9% | 2-stream sprite builder |
  | **`entry_25110`** | `$025110` | **~12.6%** | collision detect — **2 bridged `jsr.l`** |
  | **`entry_20e8`** | `$0020e8` | **~5.9%** | video render — **`$41` shadow stores** |
- **Validation harness:** the fresh-adjacent-tick lockstep pipeline (`flyval.py`/`val_*` +
  `record_playthrough.sh`/`extract_flytick.py`) injects one MAME game-tick, runs it hook-ON
  (native) vs OFF (interpreted), and requires the live state to match. KEY refinements this phase:
  classify diffs vs the stack pointer (bridge sentinels below `a7` are dead, not a bug); compare
  the `$41` video shadow for video functions.
- **Profiler** (`tools/stream_profile.py`) ranks the real in-game hot set from the interpreter's
  per-frame PC stream (MAME can't reach gameplay under `-debug`). Used to pick `$025110`/`$0020e8`.
- **Key finding:** the **multi-bank interpreter is NOT needed** — bank $00 has ~6.7KB of free
  gaps; the unoptimized escapes deploy there. (A multi-bank attempt is documented as superseded.)
- **NEXT = keep transpiling the hot set toward the G3 cycle budget** (realtime) + measure it.

<details><summary>Earlier CURRENT STATE (June 24) — superseded by the above</summary>
- **Interpreter is BIT-EXACT vs MAME** on busy attract AND deep active gameplay (frames
  400/450/900/1500; Superman moving, 14 active actors incl. enemies) — modulo only 1-2
  unmodeled sound-CPU bytes. Validated via a frame-boundary **lock-step differential harness**
  (`tools/lockstep.py`: inject MAME's 68K state, run one game-frame, diff work RAM). 4 real
  opcode bugs found+fixed this way (relative-branch bank carry; `movem.l (d16,An)` load+store;
  `lea (xxx).W`) — all invisible to the op×mode sweep.
- **Correctness gate is `opsweep` 782/782** (`tools/opsweep.py`, SA-1-aware). NOTE: the older
  `optest 154/154` claim is DEAD — optest predates the SA-1 move and reads `snesWorkRam`; it
  fails build-wide and is deprecated. Use opsweep.
- **Phase A (SA-1) DONE** and **Phase B (hybrid native-escape) DONE**: a PC-hook
  (`bsr_hookpush`) routes a hooked 68K call to a native 65816 routine (ends `jmp inext`, never
  touches the 68K stack); `$000412` RNG runs natively, **bit-identical** hook off/on. Profiler
  (`rank_hot.py`/`sample_pcring.py`/`analyze_trace68k.py`) + live save-state + speedup harness
  built. Foundation HARDENED for bulk transpile: a latent per-hit stack leak fixed; sound
  STATIC leaf classifier (`tools/leaf_check.py`); FOUNDATION CONTRACT documented in
  `interp.pasm`. See `TRANSPILER_DESIGN.md` §D5.
- **NEXT = bulk transpilation**: hand-transpile `rank_hot`'s hot SAFE-LEAFs (first: `$00CB9E`),
  add each to the escape chain, validate hook off/on, measure speedup. The interpreter is the
  cold-path fallback. Open: cycle-aware `$AC` for self-paced realtime; the sound CPU model.
- Inputs are WIRED + validated (held Right drives Superman bit-identically to MAME).
</details>

## TL;DR
Discovery/validation phase is done and *grounded against ground truth* (MAME for
the arcade, real SNES PPU for the target). The graphics path is reproduced
end-to-end; the 68K→SA-1 transpiler is de-risked with a working differential
harness (gate G2 green); disassembly coverage (G1) has a reliable trace-driven
pipeline and a full beat-the-game playthrough trace. **The 68000 interpreter now
boots Superman all the way to its live per-frame game loop on real SNES hardware**
— past the cooperative scheduler, the C-Chip GWK routine download, and full init;
both scheduler tasks run (`tmask=$0003`, matches MAME), the per-frame frame counter
increments, and work RAM evolves every frame. The interpret-cold/transpile-hot
hybrid is fully de-risked on the "cold" side. **Video plumbing is complete**: the
interpreter mirrors every 68K video-bank write into SNES `$7E` shadow RAM and, once
per game-frame, renders to the real PPU — **palette→CGRAM byte-exact (100%)**, tile
decode **128/128** vs the Python oracle, and **OBJ sprites + the BG1 playfield render a
recognizable arcade frame** (injecting a captured MAME gameplay frame produces the
church/GAME-OVER scene with Superman, validated vs an independent Python renderer). All
four polish items are done: OBJ tile dedup (sprites share tiles, up to 128 OAM),
cross-frame BG tile cache (persistent hash + VRAM, skips re-decode), vblank-safe
forced-blank DMA, and the integration validation. The render subsystem was relocated to
ROM bank `$E9` (`src/video.pasm`) to free interp-bank space; `map_snes` (hot store
dispatch) stays in-bank, reached + 3 `jsl`/`jml` wrappers. See `VIDEO_PLUMBING.md`.
**Inputs are wired**: a manual `$4016` joypad read (`joy_read`) feeds the C-Chip input
mailbox — `$900001`→P1 (active-low Up/Down/Left/Right/Btn1=B·Y/Btn2=A·X/Start),
`$900005`→Coin (SNES Select). `readbyte` routes those addresses to the mappers once the
boot handshake completes (`$A8`=1 input phase, command `$62`≠1). Validated end-to-end on
real SNES (Mesen): injecting a coin flips the game's own mailbox copies (`$F016BD/C1/C5`,
`$F01C50/54`) `$FF`→`$FE`; idle stays clean `$FF`. A harness-only virtual-controller word
at `$00:0200` (cleared at reset; OR'd into `joy_read`) injects input in emulation since
Mesen `set_input` doesn't reach the manual read path here — harmless on hardware (`$4016`
is the real source).

**Speed work — SA-1 enablement underway** (the interpreter runs ~14 68K-instr/real-frame,
~2,000× too slow; transpiling the per-frame path on the SA-1's 10.74 MHz CPU is the only
path to realtime — see `expressive-jumping-sparrow` plan). **A0 DONE**: the ROM is now a
real SA-1 cart (RomType `$FFD6=$33`, BW-RAM via SramSize `$FFD8=$07`=128 KB) and the 5A22
still boots the interpreter via a LoROM mirror of the interp into ROM `$0-$7FFF` (the SA-1
map exposes `$00:8000` as LoROM, breaking the HiROM layout otherwise). **A1 DONE**: the
SA-1 coprocessor is fully brought up and verified — it runs code from the mirror, writes
shared IRAM, write/reads BW-RAM (`$40` work RAM + `$41` shadow, both CPUs coherent), reads
high ROM banks (`$C1`/`$C9`/`$E9`), and the 5A22 still boots (`tmask=$0003`). Five fixes
cracked it (CIWP `$222A=$FF` first; Poppy 8-bit immediates via `sep #$20`; SA-1 `stp` to
free the ROM bus; BW-RAM via SramSize not ExpansionRamSize; SBWE `$2226=$80`). Added a
`get_cpu_state` tool to the Mesen MCP (SA-1 PC/regs) — decisive for debugging. **A2 DONE**:
the interpreter now RUNS ON THE SA-1 (work RAM `$7F→$40` BW-RAM, 65816 stack in IRAM, the
5A22 bootstraps the SA-1 then idles) and boots to the live loop **~5.7× faster** (80 vs 14
68K-steps/frame) with zero transpilation. **A3 in progress**: the video shadow moved
`$7E→$41` BW-RAM (SA-1 writes it), a 5A22 supervisor reads `$41` and drives the PPU on an
IRAM frame-signal — the dual-CPU render works (CGRAM/VRAM populated). Found+fixed a real
pre-existing bug (op_bitop BTST/etc. used the iloop's `$88/$8A` IRQ/countdown as scratch →
spurious frame IRQs kept the game in attract; moved iloop state to private `$AA/$AC`). The
fix advances the game far past attract. **A3 grind (June 21): fixed a MAJOR cross-bank
return bug** — `push32` hard-coded the pushed return's high 16 bits to `$00` and `op_rts`
did `stz $42`, truncating 68K addresses to bank 0; any `jsr`/`bsr` returning into banks
1-7 (the program is 512 KB) crashed on RTS. Fixed via `push32r` (return bank = PC bank
`$42` + carry) + `op_rts` popping the bank byte; added general EA-engine handlers
(`op_move_g`/`op_clr_g`/`op_pea_g`/`op_cmpib_g`). **The game now runs 165k → 718k
68K-instructions, reaches a steady IRQ-driven idle loop (`$0818`), and executes BANK-1 code
(`$01:370C`) — impossible before.** Next halt: `$066D` = `ADDI.W #imm,(d16,An)` (keep
grinding general ADDI/SUBI/etc.). Known follow-up: `op_jsr_abs`/`op_jsr_an` still force the
JSR *target* to bank 0 — needed for direct cross-bank calls. Then A3 cadence, then Phase B
(hybrid hook + transpiler). See `sa1-bringup`. Not started: audio.

ROM layout (4 MB HiROM): interp `$C0:8000` · 68K image `$C1:0000`–`$C8` · arcade tiles
`gfx1` `$C9:0000`–`$E8` · video subsystem `$E9:8000` (file `$298000`) · **escape bank**
`$92:8000` (file `$290000`, 2nd executable SA-1 bank holding the transpiler escapes).

## Workstream status

| Area | State | Evidence / doc |
|---|---|---|
| **Graphics pipeline** | ✅ validated on real SNES PPU vs MAME | `PALETTE_VERDICT.md` |
| **Transpiler design (D1–D4)** | ✅ settled | `TRANSPILER_DESIGN.md` |
| **Transpiler spike (gate G2)** | ✅ GREEN — 2 functions differentially verified | `SPIKE_RESULT.md` |
| **68K interpreter** | ✅ **BIT-EXACT vs MAME** on busy attract + active gameplay (lock-step diff; 4 opcode bugs fixed). Runs on the **SA-1**. Correctness gates **opsweep 782/782 + optest 154/154** (`tools/opsweep.py` op×EA grid + `tools/optest.py` per-opcode vs MAME — both SA-1-correct). Clears the **C-Chip boot handshake** (replay, not emulation). | `INTERPRETER_SPIKE.md`, `lockstep-harness-progress` memory |
| **Phase A — SA-1** | ✅ **DONE** — cart runs on SA-1 (work RAM in BW-RAM `$40`, shadow `$41`, dual-CPU video). | `sa1-bringup` memory |
| **Phase B — native-escape hook** | ✅ **DONE** — PC-hook routes hooked 68K calls (jsr.l / jsr(An) / bsr) to native 65816; `$412` RNG native, bit-identical. Profiler + save-state + speedup harness. Foundation hardened (leak fixed, `leaf_check.py`, FOUNDATION CONTRACT). | `TRANSPILER_DESIGN.md` §D5 |
| **Transpiler TOOL (automated)** | ✅ **BUILT + validated** — `tools/transpile.py` emits native escapes from 68K functions; reproduces the hand oracles bit-exact. Call-bridge (non-leaf) + `--video` (shadow stores). | `TRANSPILER_TOOL_SCOPE.md`, `transpiler-tool` memory |
| **Video plumbing** | ✅ **COMPLETE** — 68K video-bank writes → `$7E` shadow → real PPU each game-frame. Palette byte-exact, tile decode 128/128, OBJ+BG render the correct arcade frame; OBJ/BG tile dedup, cross-frame BG cache, vblank-safe DMA. Render subsystem in ROM bank `$E9` (`src/video.pasm`). | `VIDEO_PLUMBING.md` |
| **Disassembly coverage (gate G1)** | ⬆ in progress — reliable pipeline + full playthrough | `COVERAGE_G1.md` |
| **Tooling (MAME/Mesen MCP, trace/CDL)** | ✅ built & validated | below |
| **C-Chip** | ✅ SOLVED — patch + input mailbox + **boot handshake replay**, still **no MCU emulation** | `CCHIP_BOOT_HANDSHAKE.md`, `CCHIP_FIRMWARE.md` |
| **Audio (YM2610→TAD)** | 🔬 analyzed; `vgm-to-tad-mml` skill exists | `CONVERTSOUND.md`, `SOUNDHARDWARE.md` |
| **Bulk transpilation (native escapes)** | ⬆ **UNDERWAY (automated)** — **~25 escapes live**: 18 in the **escape bank** (`$92:8000`, file `$290000`) + bank-$00 gaps; incl. the ~12.6% collision (bridged), ~5.9% video (shadow), a list-walker. **~40% of real per-frame work covered**; ~18 functions → 99%. The interpreter is the cold-path fallback. | `escape-bank` / `transpiler-tool` / `bulk-transpile-phase` memory |

## Graphics — done
Arcade palette decode (`xRGB555` big-endian) and the **two X1-001 draw paths**
(foreground→SNES OBJ, background playfield→SNES BG) are reproduced on a real SNES
PPU and match MAME pixel colors (47/47). Sprite palette is per-bank/dynamic, ≤7
banks/frame → 8 OBJ palettes suffice, no quantization. See `PALETTE_VERDICT.md`.

## Transpiler — design settled + spike green (G2)
- **Design (`TRANSPILER_DESIGN.md`)**: D1 carry/branch lowering (carry inverted on
  sub/compare; `tst;ble`→`beq/bmi`), D2 32-bit regs in direct page, D3 byte-swap
  endianness, D4 the corrected address map (`$B00000/$D00000/$E00000/$F00000` —
  the old docs had a digit-dropped version).
- **Spike (`SPIKE_RESULT.md`)**: two real 68K leaves hand-transpiled to 65816 and
  verified against MAME goldens on a real SNES — **$412** (Lehmer RNG: signed
  `muls`/`divs`/`swap`, 22/22) and **$24D98** (timer/clamp: signed `ble`, `btst`,
  loop, trap-path, 12/12). The differential harness (the safety net the risk doc
  demanded) works end-to-end.

## Disassembly coverage (G1) — reliable pipeline, climbing
The MAME execution trace *is* the CDL: confirmed code only, exact lengths from the
trace, and it resolves the indirect jumps (H6) that froze static disassembly.
Driven by scripted states + a faithful **full beat-the-game playthrough** (your
0.287 recording, 131k frames) + service menu:
- **10.2%** of the ROM is confirmed-executed code (15,148 instr) — zero false
  positives, up from a reliable 3.4% baseline.
- **779 indirect jump-table targets resolved** (was 0 — the H6 blocker).
- Peony recursive descent from these seeds → **35,047 blocks** (vs 483 baseline);
  measured byte-coverage on a prior smaller run was 43.6% code / 67.5% ROM
  classified. See `COVERAGE_G1.md`.

## Acceptance gates (from `RISK_TRANSPILER.md`)
- **G1 — coverage ≥85% code/data separated:** ⬆ in progress (reliable 10.2% floor;
  descent ~67.5% classified; needs full descent %, maybe more playthroughs).
- **G2 — differential harness green:** ✅ done (2 functions).
- **G3 — cycle budget <150k/frame:** ⬆ **MEASURED** — real per-frame work is only ~2,391
  68K-instr (the $0818 spin is collapsed); ~43K SA-1 cyc at full native coverage (well under the
  178K/frame budget). ~40% covered now → ~0.4 game-fps; path to 99% (60fps) mapped. Not yet *met*
  (needs the hot-set transpiled), but the budget provably closes.
- **G4 — endianness manifest:** ⬜ not started (policy set in D3).

## Tooling built this phase
- **MAME MCP** (`/home/chad/mame-mcp`, server `mame`): added `capture_leaf_io`
  (golden-vector oracle) + `run_lua_inline`. See memory `mame-mcp`.
- **Mesen MCP** (`mesen`): real SNES PPU validation; ROM patched via `snesPrgRom`
  + `reset_emulator` (survives reset) for restart-free harness iteration.
- **Trace/coverage**: `tools/mame-trace/trace68k*.lua` (+ playback/scenario/service
  variants), `tools/build_cdl.py`, `tools/analyze_trace68k.py`,
  `tools/measure_coverage.py`, save-state (`save_state.lua`/`trace_from_state.lua`)
  and `.inp` playback (`playback_trace.sh`) infra.
- **Disassembler**: Peony (`/home/chad/peony`, build `Peony.Cli`, .NET 10) — note:
  single-threaded, very slow to write large disassemblies.

## Recommended next steps

**Current correction:** the historical throughput list below predates R6-R11 and is retained only
as campaign history. The immediate playability work is to reproduce the exact charged-shot
silver-enemy kill, run the first wall and crate path organically on exact v131, have the tester
judge the centered/static-boot/timbre result, close renderer conservation, and only then rerun the
formal power-on rate/budget gate.

The cold side (interpreter) and the hot side (automated transpiler + bridge + video
codegen) are both built and validated. The remaining work is **throughput** — transpile
enough of the per-frame hot path to hit the realtime cycle budget. Detailed plan in
**[ROADMAP.md](ROADMAP.md)**. In short, in priority order:
1. **Keep transpiling the hot set** — the profiler (`stream_profile.py`) ranks the
   remaining in-game hot functions ($0028d4 video, $00267a, the $025xxx cluster
   siblings, etc.). Transpile each (`transpile.py [--video]`), deploy in a bank-$00 gap,
   validate ON-vs-OFF=0 (a7-classify stack diffs; diff `$41` for video). Mechanical now.
2. **Measure G3 (cycle budget <150k SA-1 cycles/frame).** With the hot mass native,
   benchmark steps/frame and the SA-1 cycle count; decide if the cold interpreter tail
   needs a faster dispatch or more transpilation to reach realtime. Then realtime IRQ
   pacing (cycle-aware `$AC`).
3. **Watch bank-$00 space** — ~6.7KB of gaps, partially consumed. As more functions
   land, either a transpiler code-size pass (An-addr caching; non-frame reads are ~6
   instrs each) or revisit a 2nd executable bank (see `multibank-interp` memory).
4. **Audio (YM2610→TAD)** in parallel; then **integration** — full playable ROM,
   full-level validation vs MAME, G1 coverage + G4 manifest as needed.
