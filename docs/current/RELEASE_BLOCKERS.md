# Superman release blockers

There is no promoted human-test ROM. Rejected bounded renderer/scroll build
`f25a0e68…` is not playable or shippable. This file
lists what must change or be proven before either label can return. The preserved
`a9765fbf…` timing evidence line is a 66-byte, hash-guarded patch of preserved `5c7e…`, limited to two terminal
native `TST.B` CCR publications in `$02429C/$0259CA`; it does not repair the
common virtual-IRQ clock. `build/interp-current-5c7e-before-vtime-esc9.sfc`
retains the exact predecessor.

## Playable-demo gate

The corrected README showcase initially passed Chad's August 12 still-image review,
but live Mesen playtests subsequently found repeated/corrupt gameplay backgrounds
and flashing while scrolling. Preserved parent `11aefd2c…` and superseded
`5f5dc9d7…` are explicitly renderer-red. Preserved renderer/scroll predecessor
`c6ec69a1…` retains `6413924c…`'s blank physical
BG slot zero and single staging/PPU map authority, and adds the per-column
vertical-scroll/Mode-2 path. It is now explicitly red on an organic same-hash
coin/Start suffix: corrected movie replay proves 457 consecutive actual video
frames (5,634–6,090), all with gameplay HUD and sprites over black. The older
601-sample capture remains negative evidence but is not consecutive coverage.
The producer's exact prepared Stage-1 entry was promoted without replacing the
canonical raw BG code/color baseline, so later clean candidates used the
preceding title image. The first reconstruction proof then exposed a second
root: `$1700`-byte BG graphics chunks overran the safe VBlank budget and left
partial 128-byte tile records at physical slots 46 and 138.

Rejected successor `d4873020…` now proves that source reconstructs
`$7E:2000/$2400` only on the queued primary prepared path. It otherwise reads
the prepared tilemap/code
list/palette map, reads the immutable table at the correct 5A22 address
`$EF:6800`, limits chunks to record-aligned `$1600`, and resets `OPVCT` phase in
both DMA paths. The actual assembled helper/promoter was executed under a fully
recorded same-ROM intervention: its raw outputs match live X1 byte-for-byte,
the scene scrolls for 500 frames, manually reviewed screenshots contain the
complete wall/floor without black chunks, and the final inspector has 178/178
correct graphics owners with zero graphics/ownership/stale/palette mismatches.
The fresh gate for `d4873020…` covers power-on through frame 6,051
and 601 consecutive post-Start frames. It is visual-red from post-Start frame 50
through 600. The contact sheet was manually reviewed. Native graphics are exact,
but live X1 has 392 cells/178 codes while `$7E:2000/$2400` retain the exact
35-cell/27-code title hashes.

The helper/promoter bytes are present and exact, but `$E9:C400` never executes
across the fresh transition. Organic gameplay uses direct
`snapshot_acquire_paced` → `psd_prepared_dma`; only queued promotion calls the
helper. Current `50bbed41…` adds that direct call, while pack-time guards require
exactly one call in both prepared consumers. Its fresh organic movie retains 602
consecutive post-Start frames. Manual review shows the Stage-1 fade completing by
frame 90 and the complete wall/floor remaining through frame 601. Authenticated
offline reanalysis verifies every framebuffer and is clear from frame 100 onward.
At frame 100 raw code/color planes match live X1 byte-for-byte, ownership is
392/392, and all 178 BG graphics records match. This closes the reproduced
missing-background regression only; `d4873020…` and `c6ec69a1…` remain red.

Chad's next live playtest found that this whole background still moved in hard
skips. Retained consecutive-frame evidence confirms a temporal failure that the
still-image and repetition gates did not measure: over 100 video frames from
frame 5,871 / tick 370, the X1 source camera takes 50 exact -3-pixel steps while
`50bbed41…` changes BG1HOFS only 17 times. Both renderer queues remain saturated,
33 newer candidates are dropped, and the visible steps accumulate into irregular
6-15-pixel jumps. The offline temporal-scroll gate is deliberately red for the
predecessor (49 measured source steps, 16 PPU steps after warmup).

Rejected `3a5f3694…` published the latest coherent X1 scroll byte independently
of the immutable image queue, but its original gate checked only source-change
frames. It therefore missed the intervening 60 Hz holds and falsely promoted a
`hold, +3 pixels` cadence that remained visibly jerky. The rewritten gate examines
every consecutive authenticated framebuffer and makes this predecessor red: 48
holds and 49 three-pixel moves.

Preserved `21abe04c…` integrates each -3-pixel 30 Hz source step as one- and
two-pixel 60 Hz presentations without treating an X1 layout-gap jump as camera
motion. Its exact-hash fresh-power coin/Start gate retains 601 consecutive
post-Start frames 5,512–6,112 / ticks 190–490 and is framebuffer-clear. The
same authenticated images pass the every-frame temporal gate: 152 exact
-3-pixel source changes, 151 one-pixel and 152 two-pixel presentations, no
hold/reversal/oversized step, and no background mismatch. All 15 physical-map
changes have zero residual pixel mismatch. The contact sheet and former rebase
points were manually reviewed. Its real-65816/PPU bridge is green 16/16.

Preserved `382b76a4…` extends that authority to world-space OAM. The foreground
plane contains both fixed HUD and player/crate/pillar records, so NMI now advances
only compact world-X descriptors with the same one/two-pixel BG cursor while
keeping HUD rows fixed. It preserves renderer-base delta publications through
alignment and samples the quiescent camera before every due wake; the focused
real-core bridge is green 21/21. A fresh rejected `$1600` build exposed truncated
BG graphics at every 44-record boundary after the added NMI work. Current
`$1500` chunks contain 42 complete records and leave the required two-record
margin. Its exact-hash fresh run retains frames 5,581–6,181 / ticks 223–523:
framebuffer clear, 153 exact -3 source steps presented as 152 one-pixel and 153
two-pixel moves, zero BG holds/discontinuities, zero OBJ violations across 358
same-base transitions, and exact former boundary slots 43/44, 87/88, 131/132,
175/176. Sol reviewed the contact sheet and key frames.

Chad's live fence checkpoint exposed a different 64-pixel registration failure.
The retained modal map origin was stale by `+64`; the immutable image instead
proves absolute basis `$60` from slot/phase/raw-column metadata. Rejected
`60481722…` diagnosed this with a resized X1 reference and removed the required
centered crop, shifting the scene the opposite way. Rejected `893d467b…` retained
the crop and replaces only the stale map basis. The real-core bridge is green
22/22, including the exact `$A0->$60`, camera `$66`, HScroll `$3A` regression.

Rejected `36d664e6…` first implemented that absolute basis but deadlocked the
fresh transition: ACK `$0100` was tested in 8-bit mode as low byte zero, so NMI
skipped BG/OBJ forever while foreground waited on OAM due `3`. Its retained
601-frame run is red for 303 held moving-camera frames. Rejected `893d467b…`
tests the complete request/ACK readiness state. The exact red checkpoint now
clears due `3` on the first NMI and resumes ACK, renderer, and OAM publication.
A focused continuation of the supplied fence state keeps the player at world X
224 with HScroll 58 and halt zero; its X1/SNES side-by-side aligns the wall,
windows, doorway, floor, and fence. It is not canonical-MAME alignment: the
tick-3718 SNES/MAME work images differ in 2,291 bytes and player health/position.

The fresh `893d467b…` run then exposed one persistent wrong native record:
slot 2 owned `$19AE` but retained 127 bytes of Mode-7 data. Passive tracing proves
that `HVBJOY=$C2` remained VBlank-high at `OPVCT=$0000`; the low-page helper
mistook line 0 for lines 225-255, took direct DMA, and returned after Mesen
rejected the VRAM write. Rejected `b92ac14f…` disabled only line-256+ direct DMA
and stayed red. Current `f25a0e68…` rejects all low-page lines below 225 as well.
Its exact frame-5,250 slot matches 128/128 bytes, and its exact-title organic
coin/Start run retains 601 clear post-Start framebuffers 5,704-6,304. The temporal
gate is green (302 PPU steps, 151 source steps, no discontinuity), and Sol reviewed
the contact sheet plus frames 100/300/600. This closes the reproduced title-slot
corruption and bounded black-seam regression only.

The same `f25a0e68…` ROM is nevertheless human-test red. Chad's live cold-boot
screenshot shows the SA-1 logo shifted and clipped against the far left edge, and
the post-Start playtest reports Superman walking with visibly wrong/opposite motion
presentation. The prior validator captured boot milestones but did not assert their
geometry; its pass/fail loop covered post-Start background/cache conditions and did
not assert player facing or animation order. No narrow `clear` result may be widened
into a visual handoff claim again.

Promotion is now fail-closed through `tools/promote_human_test_rom.py`. The tool
requires exact-hash green fresh-power evidence for boot, title/credit/Start, both
walking directions, attack motion, every-frame scrolling, fence collision/break/
passage, aligned full-composite background/OBJ/HUD comparison, intervening-frame
conservation, and recorded Sol review. Any absent, incomplete, `unknown`, red,
cross-hash, mutated, or unauthenticated evidence blocks creation of a test ROM.

Intermediate candidates were correctly rejected by the new gate. `b1e57e0e…`
had the correct 1/2-pixel cadence but flashed at tilemap publications;
`d43c8bb4…` rebased one frame after the DMA; and `562928a5…` still had nine
background discontinuities because Poppy silently encoded the impossible long
`STZ` marker clear as a bank-relative store. Current source uses a legal explicit
long store and pack-time guards pin same-NMI commit/clear ownership.

This closes only the reproduced bounded Stage-1 black-band and cadence
regressions; it does not promote `f25a0e68…`. Aligned exact-MAME pixels, formal MAME-frame conservation, later
stages/organic Stage 2, renderer throughput, current performance, hardware, and
human combat/audio acceptance remain open. No full long gameplay replay has
been started for `f25a0e68…`.

Promotion of a successor still requires this one
ROM identity and one exact tick range to pass the machine-enforced state oracle,
aligned exact-MAME pixels at every game tick, and conservation of every
intervening SNES video frame. Missing, incomplete, cross-hash, or cross-range
evidence is `unknown`, never green. The same ROM must additionally pass
fresh-power-on stage/boss continuity, organic Stage 2 and later renderer coverage,
a live human combat/audio playtest, the 30 game-ticks/s and 358K SA-1 cycles/tick
gates, and real-hardware acceptance.

Retain the current-hash organic failure and intervened proof at
`build/playback-watcher-20260813/c6ec-poststart-exact-video-frames-v1/`,
`c6ec-prepared-cache-proof-v4-final-cache-v3/`, and
`c6ec-assembled-prepared-dma1600-proof-v3/` plus its `-final-cache-v1`
inspector. A new hash invalidates the `c6ec69a1…` save-state suffix as acceptance
evidence for the successor; every artifact remains regression and root-cause
evidence.

Retain the failed successor at
`build/interp-prepared-bg-dma1600-d4873020.sfc` and its fresh evidence at
`build/playback-watcher-20260813/d487-fresh-poststart-framebuffers-v2/`.
Focused same-hash inspection and helper-flow reports are under the adjacent
`d487-fresh-poststart-inspect-*`, `d487-fresh-poststart-x1-*`, and
`d487-organic-helper-poststart0-v1` directories. No longer campaign was started.

Retain current `50bbed41…` evidence at
`build/playback-watcher-20260813/50bbed41-fresh-poststart-framebuffers-v1/`,
including `reanalysis-grace100.json`, plus adjacent
`50bbed41-fresh-poststart-x1-100-v2` and
`50bbed41-fresh-poststart-inspect-100-v1`. No long campaign was started.

The fresh successor gate starts from `StartWithoutSaveData`, not a retained
checkpoint. `tools/validate_fresh_poststart_framebuffers.py` records and replays
one organic power-on/coin/Start movie, retains loading/title/credit milestones,
every actual post-Start frame, periodic states and BG graphics records, and a
contact sheet. Blank/repeated playfields, hidden BG1, absent ownership, partial
tile DMA, frame gaps, or halt are machine-red, and Sol must manually inspect the
contact sheet before any visual-clear report. Even a clear result remains
acceptance-unknown until exact-MAME pixel and temporal-conservation gates run.
Its default 100-frame grace covers the observed organic Stage-1 fade;
`tools/reanalyze_fresh_poststart_framebuffers.py` can authenticate and reclassify
all retained PNGs after threshold-only changes without replaying the boot prefix.
Builds and this bounded fresh-power regression gate do not require separate
approval. A full long gameplay campaign does. Before rebuilding, report the
confirmed cause, why a new hash is necessary, and which exact-hash acceptance
evidence will no longer transfer.

The preserved-parent Mesen repetition diagnostic is deterministically red. Lossless
capture reports mismatch ranges 165–174 and 225–232. Clean-to-first-bad comparison
changes 98.93% and 60.34% of playfield pixels, respectively. A no-write 5A22 trace
proves that the bad frames follow heavy-path map uploads with 1,984/2,048 and
1,938/2,048 zero tilemap words; the recovering maps contain only 524 and 517.
Zero was simultaneously the staging sentinel and a live physical BG-cache slot,
so the near-empty obsolete maps became repeated tile fields while the separately
rendered HUD/foreground survived. The `5f5dc9d7…` heuristic delays a below-
256-nonzero-word map only when a complete successor is queued, preserves X/Y,
and keeps live scroll. Its retained ticks 881→1,020 scan saw no dominant-tile
collapse across 231 frames, but that scan is diagnostic-only and did not establish
aligned pixels or intervening-frame conservation.

Chad's exact Mesen 2.1.1 state `interp_1.mss` proves `5f5dc9d7…` remains red at
frame 10,118 / tick 2,465. Its displayed and staged tilemaps match and contain
1,589/2,048 zero words; all 228 retained lossless continuation frames trigger the
repetition diagnostic. The heuristic admits this 459-nonzero-word map, and eight
of 15 traced attempts commit it or similarly sparse successors. That proved the
first root: physical BG tile slot zero must remain blank. A controlled
slot-zero-only migration changed the repeated red artwork to blank holes without
restoring missing columns, proving the root was incomplete. The second root was
the sparse gate advancing staging/cache authority after suppressing the
corresponding PPU upload. `6413924c…` applies both repairs.

`tools/validate_gameplay_acceptance.py` is the sole tool authorized to issue a
bounded gameplay `green`. It accepts only matching reports from the state oracle,
the every-tick exact-MAME pixel oracle, and every-video-frame temporal
conservation. Capture, trace, cross-emulator, single-frame, and repetition tools
always carry diagnostic-only or bounded-oracle authority and cannot fill missing
aggregate gates.

Current source builds rejected SHA `f25a0e68…` at the unverified ordinary path
`build/interp.sfc`. There is no reviewed or promoted byte-identical test copy.
The superseded `3a5f3694…` pin and earlier ROMs/evidence are preserved outside
the repository under `/home/chad/supermn-snes-artifacts/`; the archive README
maps former `build/` paths to their retained locations. Predecessor `6413924c…`'s focused token and producer
fixtures are green 3/3 and 12/12. A controlled cross-ROM migration from a retained
`4eb9a408…` tick-2,437 snapshot continues through tick 2,554; its reviewed first
and last post-vblank frames retain the full background and the 273-frame
heuristic finds no repetition/flash ranges. This closes the reproduced symptom
only in a bounded diagnostic: the snapshot is not resumable campaign
lineage, its video mirror/cache migration is an intervention, and no exact-MAME
pixel oracle was run. The exact-hash fresh-boot, aligned-pixel, and every-frame
temporal gates therefore remain `unknown`.

Rejected intermediate `95b44eb7…` never exited loading because Poppy silently
encoded invalid source `sta $7E74C0,y` as DB-relative absolute,Y bytes
`99 C0 74`, corrupting the arcade boot RAM test. Current `c6ec69a1…` uses an
X-preserving legal long-X store and adds a ROM-pack assertion against recurrence.
Its bounded cold-boot smoke reaches tick 185/render 89/PC `$0818` with halt zero,
and the exact-hash vertical-scroll bridge gate is green 10/10. Both supplied old
Mesen states now pass the explicit same-emulator checkpoint rebuild contract.
State one has 384/384 final-target ownership with 58 intentional draw-order
overlaps; state two has 392/392 with no overlaps. Both have zero stale-empty,
palette, and native-graphics mismatches, matching live/applied column maps, equal
completed generations, and complete two-frame-settled PNGs. This required fixing
the lab itself: serialize Mesen's global screenshot path, refuse non-drained
migration, publish a private generation/worker request, seed live X1 cache and
palette, invalidate serialized applied-map authority, and wait out screenshot
latency. These are intervened checkpoint diagnostics, not formal aligned-pixel or
temporal-conservation acceptance.

The exact-hash fresh gameplay, aligned-pixel, and every-frame temporal gates
remain `unknown`. Its red parents `5f5dc9d7…` and
`11aefd2c…`, plus rejected queue-wide guard `10dc1a0b…`, remain preserved;
superseded diagnostic-clear `9ab9a1db…` omitted X/Y preservation.
None inherits evidence from predecessor `4eb9a408…`, preserved as
`build/interp-visual-eightfix-4eb9a408.sfc`. Superseded `2f590fb1…`
is fresh-power-on green through tick 3,300 for gameplay/liveness, clean SA-1
boot, centered P2 HUD, and the repaired crate area, but its tick-1,278 combat
background is still the red-brick failure. Read-only state inspection proved
the column classifier correct and confirmed the root: title already owned the
baseline, so the expected 784-byte title-to-gameplay delta cleared the valid
C0BC token as though it were a later mutation. Superseded `6f7b1084…` compares the live
2 KiB code/color planes with their publication-time snapshot before retaining
or invalidating C0BC. Its exact transition gate is green in both directions and
its PC-ring whole-function MAME/Nexen differential is green 6/6 with zero
work/video mismatch, but its fresh/same-lineage tick-3,300 campaign still shows
red-brick combat because the accepted token changed without a consumer upload.
`4eb9a408…` restores the complete immutable prepared caches and publishes the
existing prepared PPU-upload path on token-only acceptance. Its three-case 5A22
fixture is green, and a migrated tick-1,280-to-1,300 suffix restores storefront
geometry without oracle/liveness failure. Its authorized exact-hash fresh prefix
then repeat-hashed a safe tick-1,280 checkpoint; the same-lineage suffix resumed
at 1,281 and completed tick 3,300 with no observed oracle/liveness divergence.
Retained frames show clean SA-1 boot, the restored tick-1,278 storefront, no
bogus crate-area tile chunk at tick 3,214, and the full centered P2 HUD. This
closes those four bounded showcase regressions on `4eb9a408…`, but does not
transfer `a976…` acceptance or prove aligned pixels, renderer conservation,
performance, full playthrough, production, or release acceptance. The compact
report is
`build/playback-watcher-20260811/visual-eightfix-4eb-fresh-to3300-v1/watcher-report.json`.
The latest
focused VTIME image is v7 `45c9096d…`; its ROM-only migrated tick-14,745-to-
14,750 seam and all exact-v7 player/input/death rows through tick 16,000 are
green after the delayed input-publication repair. The first two boss fixtures
are also green in the corrected checkpoint replay at 15,908/15,990. The
superseded frame-minus-75 comparisons sampled before the write-containing
update; authenticated frame-minus-74 write ticks require observation one tick
later. This is a harness defect, not a demonstrated ROM scheduler defect. V7
has no fresh-boot, full-boss,
performance, or production authority. The concise identity/evidence handoff is
[ENGINEERING_CHECKPOINT_20260811.md](ENGINEERING_CHECKPOINT_20260811.md).

Exact-v7 evidence remains oracle-green through completed tick 21,200. The
retained safe state `6c3eaab1…` has pre-counter `$07FEF8A5`; terminal tick
21,203 reaches `$08000000`, writes `$CAFE`, and spins at SA-1 `$00D15A` with
virtual PC `$000D42`. The surrounding valid instructions are `$0D40`
`MOVE.W (A1)+,D4` and `$0D42` `BEQ`, so this is the confirmed lifetime guard,
not an illegal opcode or corruption. The unpromoted v8 successor `162b757c…`
differs from exact v7 only in the four mirrored threshold bytes. Its ROM-only
migration crosses the old cap and reaches counter `$0809A799` at tick 21,300:
`build/playback-watcher-20260812/v8-stepcap-migrated21200-to21300-v1/watcher-report.json`.
Same-ROM v8
continuations through MAME 31,000 / SNES 30,994 have first divergence NONE, no
mismatch ranges, halt 0. Minimum stack and renderer drops were not sampled at
the intentional stop. Reports:
`build/playback-watcher-20260812/v8-stepcap-resume21301-to21500-v1/watcher-report.json`
and `build/playback-watcher-20260812/v8-stepcap-resume21501-to22000-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume22001-to22500-v1/watcher-report.json`,
and
`build/playback-watcher-20260812/v8-stepcap-resume22501-to23000-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume23001-to25000-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume25001-to27000-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume27001-to30000-v1/watcher-report.json`,
and the endpoint report
`build/playback-watcher-20260812/v8-stepcap-resume30001-to33000-v1/watcher-report.json`;
state `613c6566788e4b81408b87efbd278d35fa9f75c6ca762eb14a17b65f1ff4f32c`, IRAM
`7ab15b2dad152aa2d3b37401c6534e0ae4c4a42dc3a44beef6c21c5c9988ef4c`, resume
31,001. The retained movie ends at game tick 139,925 / frame 140,000, leaving
108,925 game ticks (22.15% covered); the campaign is intentionally paused for
human screenshot review. No fresh campaign was started; fresh boot, full
playthrough, and production acceptance remain open.

The active hash is green for its direct exact MAME/native-off/native-on 9/9
CCR differential (`build/validate-2429c-distinct-arm-isolated-a976-pinned-v1.jsonl`),
a fresh power-on MAME-controller replay through tick 10,000 with 2,062 green
comparisons and five matched deaths
(`build/fresh-candidate-2429c-tstb-ccr-isolated-a976-to10000-v1`), and a fresh
one-credit HUD/art check
(`build/validate-fresh-one-credit-prompt-isolated-a976-v1/summary.json`).
The same active image independently passes the legacy-Mesen cold-boot prompt
gate at `build/validate-fresh-one-credit-prompt-isolated-a976-mesen211-v1/summary.json`.
Those checks cover Button 1 punch/charge, Button 2 kick, Up flight, and crate
pickup/carry/throw, but not an organic boss encounter, Stage-3 transition,
usable rate, or a full playthrough.

The active ordinary-enemy differential is green 4/4 at
`build/validate-gameplay-damage-current-a976-v1`: exact MAME, native-off, and
native-on agree on Button 1 punch damage 1, Button 2 kick damage 2, contact
damage 4, and charged-projectile damage 4. The active boss differential is
green 118/118 at `build/validate-boss-health-current-a976-v1.json`: the
bounded exact sequences are Stage 1 40 HP/13 hits, Stage 2 40/37, and Stage 3
20/6. Both retain register/CCR/X, stack, work-RAM, collision, and health-write
comparisons but mask IRQs within each handler, so they do not prove an organic
continuous boss fight.

The active organic crate carry/throw and flight-contact branches are also
green. `build/validate-organic-crate-current-a976-v1/summary.json` continues a
same-hash fresh-boot tick-3,000 checkpoint with no migration and compares all
87 exact controller entries per arm in original MAME, native-off, and
native-on. Its 17 carried crate/enemy contacts produce zero health transitions;
only Button 1 throw produces the original one-point transitions at ticks 3,274
and 3,283. The distinct Up+Right route at
`build/validate-organic-crate-flight-current-a976-v1/summary.json` switches
from carrying to flight at tick 3,253, confirms material ascent and real enemy
overlap, and still has zero health transitions in all three configurations.
This closes the reported carried-crate damage path in these organic checkpoint
branches, not a full campaign or continuous combat proof.

The active hash's Stage-3 blocker is now independently current evidence, not
an inherited `5c7e…` claim. A fresh native-on root reaches tick 14,746 and
retains its tick-14,743 safe checkpoint and tick-14,745 boundary. Exact MAME
0.287/native-off/native-on snapshots from that one authenticated state are
red at tick 14,746 in `build/validate-stage3-irq-order-current-a976-v1.json`:
MAME task 15 has `$0259B0/$0242BE`/SR `$2400`; both SNES configurations have
`$02429C/$00044E`/SR `$2404`. Because native-off and native-on match, this
remains a hardware-boundary/virtual-IRQ timing root rather than a native-only
defect. Its current checkpoint-local neutral measurement also misses the rate
gate: 2,471,287.70 native-on and 11,320,496.0 all-native-off SA-1 cycles/tick
versus the 358,000 budget
(`build/measure-stage3-current-a976-safe14743-v1/summary.json`). Neither is
fresh-ROM FPS or full-playthrough evidence.

The two earlier fresh gameplay-root-off campaign attempts are retained as
harness-only red results: after their tick-221 gate configuration, they waited
for native `$92:DB82`, which is intentionally unreachable with `$071A/$073A`
cleared, then timed out and lost the bridge
(`build/fresh-campaign-current-a976-to14746-native-off-v1` and `-v2`). The
corrected fresh power-on prefix
`build/fresh-campaign-current-a976-native-off-first-entry-v6` is
`partial-green`: it stops once at the checked rising virtual-PC `$003A92`
edge in IRAM `$0040`, after a MAME-matched tick-221 origin. At tick 222 the
disabled gates are zero, player state still matches MAME, and halt is zero.
Its fresh companion
`build/fresh-campaign-current-a976-native-off-first-movement-v1` reaches tick
1,060 and has two green MAME player comparisons around a real Left transition
at tick 1,054 (the tick-1,056 X response is 64 to 61 in both). This repairs
the harness classification and, with the retained fresh native-on response,
proves that small MAME/native-off/native-on movement differential. It has no
attack, boss, death, Stage-3, rate, or
all-escapes-disabled coverage. The authenticated same-safe-state native-off
capture in the exact three-way gate remains the valid Stage-3 disabled-mode
evidence.

The exact fresh-lineage native-on state at tick 14,743 was also continued to
tick 15,050 at
`build/continue-stage3-current-a976-safe14743-native-on-v1`. Its 15 player
differences are downstream of the tick-14,746 three-way timing failure; the
suffix has no halt, invalid task stack, or renderer stall, but is not recovery,
fresh-boot exact-state proof, Stage-3 completion, or a rate result. The focused
rerun `build/continue-stage3-current-a976-safe14743-native-on-prefailure-v2`
reproduces the first visible result at tick 14,841 after a green tick-14,839
input boundary and retains immutable hash-checked state/IRAM copies before the
input response. Because that copy is an exact-entry forensic snapshot, it must
not be reloaded as a production checkpoint. It demonstrates deterministic
downstream propagation only; the current exact MAME/native-off/native-on
task-frame comparison at tick 14,746 remains the root-cause classification.

The campaign harness now freezes any retained input pre-state at the first
oracle observation instead of allowing a later controller edge to overwrite
it. `tools/test_campaign_pre_failure_state.py` protects that artifact contract;
`tools/test_stage3_post_irq_continuation_a976_evidence.py` protects the current
post-IRQ result and its explicit non-acceptance scope.

The root's bounded timing ledger has also advanced without changing its
release classification. Four controlled distinct-arm fixtures now pass 12/12
active-`a976…` MAME/native-off/native-on function comparisons at
`build/validate-2429c-distinct-arm-isolated-a976-pinned-v2.jsonl`; each
compares D/A, CCR/X/mask, mapped work RAM, and audited return/stack residue
while IRQs are deliberately masked inside the isolated function. Their exact
original-MAME debugger traces at `build/mame-2429c-fixture-cycles-original-v2`
collectively cover every dynamic `$02429C` branch/DBcc PC (14) and every
dynamic PC in its direct native children (19), with zero timing prediction
failures in `build/validate-mame-2429c-fixture-cycle-coverage-a976-v1.json`.
This is enough to prevent a static-cost guess at those bounded blocks; it is
not a parent/child ownership handoff, common clock, IRQ-cadence, rate, organic
Stage-3, or full-playthrough result.

The refreshed static promotion guards still prohibit partial VTIME promotion.
The opt-in bank-$F3 `$02429C` copy now consumes all 35 block records, owns and
flushes all 11 parent handoffs, interprets each child, and resumes via genuine
MC68000 returns. The local closure audits are green at
`build/audit-stage3-2429c-handoff-protocol-b758-v3.json` and
`build/audit-stage3-2429c-common-clock-closure-b758-v3.json`; bounded exact
runtime evidence is green 8/8 at
`build/validate-vtime-2429c-root-b758-v3.jsonl`, with separate green handoff
and synthetic deadline-unwind reports at
`build/validate-vtime-esc5-root-handoff-b758-v3.json` and
`build/validate-vtime-esc5-root-due-b758-v3.json`. This is diagnostic source
based on the unaccepted ordinary `b758…` rebuild, not active `a976…` promotion.
Follow-on diagnostic `efeb08e8…` adds a VTIME-valid `$074C` scheduler-scan
fallback to the exact interpreter clock; its active and invalid branches are
green at `build/validate-vtime-scheduler-scan-fallback-b758-v4.json`. Eleven
of 26 direct `$AC` writers remain unmigrated and 12 accelerated
boundaries remain uncovered in
`build/audit-vtime-legacy-ac-writers-b758-v3.json` and
`build/audit-vtime-accelerated-boundaries-b758-v3.json`. Both fresh controller
controls are red before gameplay: v3 observes 7 credits instead of 8, while
v4 observes 5 instead of 8, with zero gameplay transitions in either report.
See `build/playback-watcher-20260808/vtime-2429c-root-3dc-fresh-to3000-native-on-v1/watcher-report.json`
and
`build/playback-watcher-20260808/vtime-2429c-root-schedfallback-efeb-fresh-to3000-native-on-v1/watcher-report.json`.
The v4 gameplay-native-off control is identically red at 5/8 credits with zero
gameplay transitions at
`build/playback-watcher-20260808/vtime-2429c-root-schedfallback-efeb-fresh-to3000-native-off-v1/watcher-report.json`.
Thus the scheduler fallback is locally exact but campaign-rejected, and the
failure is in shared VTIME/scheduler timing rather than gameplay-native
dispatch. Focused pulse probes show v3 advances 69 game ticks and v4 only 44
over the fixed 215-frame credit window, reproducing 7 and 5 credits exactly at
`build/probe-vtime-credit-pulses-3dc-v3/summary.json` and
`build/probe-vtime-credit-pulses-efeb-v4/summary.json`. The fallback was removed
from current source and v4 is retained only as negative evidence. Checked-call
fast path `9aa32c55…` and dynamic-class prefilter `9ae08316…` improve the same
window only to 71 and 72 ticks; both still recognize 7/8 credits and were
reverted. The one-word Select latch `2567dd89…` is worse at 6/8 because it
delays neutral releases, and was reverted as well. The exact lost boundary is
the second four-frame Select hold wholly inside game tick 82. The unchanged v3
ROM reaches 8/8 only when the harness extends its pre-game bootstrap to
eight-frame Select/eight-frame neutral intervals
(`build/probe-vtime-credit-pulses-3dc-v3-long8-v1/summary.json`). Fresh
disk-first Luna controls prove that this is bootstrap calibration only. The
155-frame settle reaches origin RNG 22,330, one recurrence before the expected
200; the 95-frame settle reaches 28,686, 20 recurrences before it. A calibrated
158-frame settle passes the origin RNG gate but requests 29 gameplay
`$92:DB82` entries and observes only 6 over frames 5,650--8,106, without
reaching any gameplay input transition or oracle comparison. See the compact
reports under
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-fresh-to3000-native-on-v1/`,
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-wait95-fresh-to3000-native-on-v1/`,
and
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-wait158-fresh-to3000-native-on-v1/`.
The apparent gameplay-phase throughput/exact-entry blocker was superseded by
terminal capture. The 5A22 was eventually returning into data after nested
interrupt growth: NMI modified a saved status byte instead of preserving the
interrupted mask state, while `service_pending_dma0` left `$1F11` published
during `MDMAEN`, allowing an NMI at long-DMA completion to replay the same
descriptor recursively. Preserving both status bytes and clearing the
publication before DMA removes that corruption. Preserving renderer scratch
`$D0` around the asynchronous NMI `bg_scroll` keepalive fixes the remaining
renderer stall. The resulting opt-in `e00fb0cb…` image is bounded
partial-green in fresh native-on and matching diagnostic-tool native-off runs
through tick 250, and fresh native-on reaches tick 1,100 with 98/98 retained
exact-entry spans, six green input transitions, 12 green player references,
valid task floors, advancing renderer state, both CPUs running, and no oracle
divergence. See the compact reports at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-long8-wait158-to250-native-on-v1/watcher-report.json`,
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-long8-wait158-to250-native-off-mcpdiag-v1/watcher-report.json`,
and
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-long8-wait158-to1100-native-on-v1/watcher-report.json`.
The authenticated native-on continuation from `resume_mame_tick` 1,098 is
also partial-green through tick 3,000 with no divergence or mismatch range at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume1098-to3000-native-on-v2/watcher-report.json`.
Its cumulative lineage records 168/168 green player references, one organic
death at tick 2,461, 2/2 green death/respawn references, observed actions 0,
1, 2, 8, and 9, valid task floors, live rendering, and halt zero. The next
authenticated continuation is also partial-green through tick 6,000 at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume2998-to6000-native-on-v1/watcher-report.json`:
1,134/1,134 player references, 4/4 death/respawn references, two organic
deaths, all listed action and button gaps closed, valid floors, live rendering,
halt zero, and no divergence. The following authenticated continuation is
partial-green through tick 10,000 at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume5998-to10000-native-on-v1/watcher-report.json`,
with 2,062/2,062 green player references, 10/10 green death/respawn references,
five organic deaths, valid floors, live rendering, halt zero, and no mismatch.
The next authenticated continuation reaches tick 14,750 with no sampled
player-oracle mismatch at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume10008-to14750-native-on-v2/watcher-report.json`.
It crosses retained boundaries 14,743--14,747, including the historical
tick-14,746 input/order seam, and ends with 2,745/2,745 green player references,
12/12 green death/respawn references, live CPUs/rendering, valid floors, and
halt zero. Exact retained-state work-RAM comparison now proves that the sampled
run missed the earlier task-frame seam: `e00f…` first differs at tick 14,746
in task 15, RNG, and collision state; its false-hit marker differs at 14,839
and exact player state at 14,840. See
`build/playback-watcher-20260809/vtime-2429c-root-b758-nmi-dma-d0-native-on-attribution-v1/watcher-report.json`.
The phase validator `build/validate-vtime-stage3-phase-e00f-v3.json` further
measures a 114,978-cycle pre-root undercharge. The candidate reaches
`$02429C` with 61,448 two-cycle units remaining even though MAME interrupts
only 7,692 cycles later inside `$025110`; route hooks prove that child is
interpreted, with zero collision-native/ESC3-ledger hits. The blocker is
upstream/global common-clock coverage, not a final-root flush or hidden child
re-acceleration. Its retained pre-root inventory observes 192 known entry hits,
185 of them across 52 labels not admitted to a selected VTIME ledger, with a
complete five-phase split and `safe_narrow_fix_available=false`. The opt-in
ROM-selected interpreter-only fallback `0bfae7d0…` now has a correctly aligned
fresh prefix through tick 250: MAME origin tick 221/RNG 200, 29/29 interpreted
entries, no mismatch range, and a byte-identical resumable checkpoint at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-fresh-to250-v6/watcher-report.json`.
The apparent missing sixth root in its first longer continuation was an
observation-gate leak, not a missing game update: the VTIME-only `$02429C`
return dispatcher unconditionally restored `$071A=1` after an interpreted
child. The mode-aware repair leaves `$071A=0` only for the explicit
interpreter-only bit and preserves ordinary VTIME's `$071A=1` behavior across
all eleven returns. Its repaired diagnostic ROM is
`build/interp-vtime-interpreter-only-e00f-gate-restore-v1.sfc` (`96d1b193…`).
Retained-state roots 6--16 are semantically exact against MAME ticks 796--806,
and the separate ordinary-mode control restores the gate and remains live.
More importantly, a fresh repaired-ROM root reaches tick 806 across 585/585
interpreted entries with no divergence and a byte-identical safe checkpoint;
an authenticated continuation reaches tick 1,100 across 878/878 cumulative
entries, six gameplay transitions, and 12/12 green player references. A second
authenticated continuation reaches tick 3,000 with 84 cumulative transitions,
168/168 green player references, one green death/respawn sequence, gates and
halt zero, live zero-drop renderer state, valid task floors, and a repeated-
identical safe checkpoint authenticating resume tick 3,001. Compact reports
are under
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-{fresh-to806-v1,resume807-to1100-v1,resume1101-to3000-v1}/`.
That closes the false exact-entry-starvation classification and proves bounded
fallback liveness/semantics only. VTIME, the dirty supervisor changes, fresh
ordinary-ROM acceptance, matching ordinary/native-off recovery, Stage-3 rate,
boss coverage, and a playthrough all remain open.

The next interpreter-only continuation remained oracle-green through tick
4,965 (906/906 cumulative player references, all listed action states, and
4/4 death/respawn references) but is harness-red because Nexen closed MCP
during capture before a terminal snapshot or requested tick-6,000 save. Its
compact report is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume3001-to6000-v1/watcher-report.json`.
The exact tick-4,000 state was recovered without replay into an authenticated
post-entry-safe checkpoint at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-recover4000-v3/summary.json`;
its three copies share SHA-256 `786f2f72…` and resume at tick 4,001. The
machine-readable reuse guard is `docs/current/CAMPAIGN_EVIDENCE_LEDGER.json`
with `tools/validate_campaign_evidence_ledger.py`. This prevents an automatic
tick-3,001 prefix replay. Luna-owned authenticated continuations from that
recovery are now green through tick 14,000 at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume{4001-to6000-v1,6001-to8000-v1,8001-to10000-v1,10001-to12000-v1,12001-to14000-v1}/watcher-report.json`:
9,995/9,995 segment entries and 13,771/13,771 cumulative entries, no divergence
or mismatch range, 1,325 cumulative input transitions, 2,650/2,650 green player
references, all timeline action states, six organic deaths with 12/12 green
death/respawn references, gates and halt zero, zero renderer queue drops, and
15 valid initialized task stacks with 138-byte minimum margin. Three
byte-identical tick-14,000 safe states share SHA-256 `9a7173a1…` and
authenticate resume tick 14,001. Boss coverage is still zero; this remains fallback
correctness/liveness evidence, not rate, Stage-3, ordinary-ROM, boss, or
playthrough acceptance.

The following Luna-owned tick-14,001--15,000 request stops normally at the
first compared mismatch, MAME tick 14,841, after 840/840 segment and
14,611/14,611 cumulative exact entries:
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume14001-to15000-v1/watcher-report.json`.
MAME is action 0, health 4, `(52,112)`; the interpreter-only SNES is action 9,
health 20, `(68,96)`. Both gameplay-native gates remain zero and halt remains
zero. This is the same downstream false-respawn signature already shared by
production-native-on and gameplay-native-off after their exact tick-14,746
task-frame split, so it preserves the hardware-boundary/common-clock root and
rejects a native-only collision or repaired-gate explanation. The three
tick-14,743 post-entry-safe saves are byte-identical at SHA-256 `5ccbc509…`;
the ledger now reuses that accepted prefix at resume tick 14,744 rather than
replaying the campaign. `tools/test_vtime_interpreter_only_stage3_divergence.py`
guards the compact failure. No safe narrow timing fix is established: the
remaining repair is still common path-sensitive cycle accounting across the
unmigrated scheduler, renderer, native/HLE, idle, and pacing boundaries. The
focused exact-state attribution at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-stage3-attribution-v1/watcher-report.json`
pins the same first internal divergence at tick 14,746 and the same
114,978-cycle pre-root deficit; `tools/test_vtime_interpreter_only_stage3_attribution.py`
guards those task-frame and phase claims.

The next bounded diagnostic makes scheduler scan `$074C`, select `$075C`,
switch-in `$0796`, and switch-out `$0532` decline before mutation in explicit
interpreter-only mode. Its corrected artifact is
`build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-v2.sfc`,
SHA-256 `60087042d9b0ecc48525258033009a634085deb661899724d917b8df78266ae9`.
The first migrated seam retained stale armed scheduler gates and is explicitly
non-testing. The corrected Luna-owned seam at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-seam-v2/watcher-report.json`
has `$071A/$073A/$0736/$073C=0` at all four boundaries but leaves the first
task-frame divergence at tick 14,746 with the same 21/21/78/81 differing-byte
counts. `tools/test_vtime_interpreter_only_scheduler_fallback_evidence.py`
pins both the invalid v1 scope and valid v2 negative. Therefore disabling the
four shortcuts is not a sufficient narrow repair. The result is ROM-migrated,
does not directly instrument path firing, and supplies no fresh, rate, or
acceptance claim.

A disk-only Luna reduction at
`build/playback-watcher-20260809/stage3-remaining-loop-idle-owner-scope-v1/watcher-report.json`
then checks the remaining named loop/idle owners without launching another
emulator. Across 46,900 retired MAME rows, `$0818` retires 1,993 times in the
preceding tick-14,744--14,745 interval but zero times in the failing
14,745--14,746 interval; `$3B84/$3FEA/$ADBE` are absent, while the active
failing path retires `$02429C/$025110/$0259B0` 1/1/27 times. A bounded
preceding-owner diagnostic therefore makes `$0818` decline before its paced
helper under explicit interpreter-only VTIME. The candidate
`build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-v1.sfc`
has SHA-256 `7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387`.
Its Luna seam at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-seam-v1/watcher-report.json`
directly counts 17,133 new `$99:FBB0` gateway hits, zero old `$99:FB00` paced
helper hits, zero fallback gates, and zero halt. It still first diverges at
tick 14,746 with MAME `$0259B0` versus SNES `$02429C`; mismatch counts are
21/21/78/83. `$0818` fallback is therefore not a sufficient repair, and no
fresh long replay is warranted. The artifact guards are
`tools/test_stage3_remaining_loop_idle_owner_scope.py` and
`tools/test_vtime_interpreter_only_0818_fallback_evidence.py`. This remains a
ROM-migrated forensic negative; the next narrow owner is the active
`$02429C -> $025110 -> $0259B0` child-handoff group and its already-late
upstream clock, not another continuation from a red checkpoint.

That disk-only child ledger is now
`build/playback-watcher-20260809/stage3-2429c-25110-259b0-owner-ledger-v1/watcher-report.json`.
It partitions the 139,486-cycle failing MAME interval as 1,554 cycles from
root to child, 1,176 to `$02582E`, 146 to first `$0259B0`, 4,580 across its
27 continuation rows, 216 to the IRQ boundary, and a 64-cycle IRQ entry gap.
The 2,876 root-to-first-continuation cost is not enough to explain the
already-retained 114,978-cycle pre-root deficit/115,204-cycle lateness. Root,
child, resume, and IRQ handoffs remain incomplete, but no single owner is
isolated. `tools/test_stage3_2429c_25110_259b0_owner_ledger.py` pins that
scope. The next bounded run may observe those source-authenticated seams
read-only; it must not mutate the clock or promote a production fix yet.

The bounded read-only seam is now
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-child-hooks-v1/watcher-report.json`.
Every native root/child/branch/Stage-2/return/resume hook is zero, while the
actual IRQ entry fires four times and `$071A/$073A/$0736/$073C` stay zero.
The authoritative task-frame split remains tick 14,746 with 21/21/78/83
differing bytes. The native `$02429C/$025110/$0259B0` implementation is thus
not active in this explicit interpreter-only seam and cannot be selected as
its repair owner. The ROM-migrated exclusion is guarded by
`tools/test_vtime_interpreter_only_root_child_hooks_evidence.py`. Next work
must count remaining accelerated owners that really execute, including CE4
renderer and dynamic loop paths, before another mutation.

That owner inventory is now
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-active-owner-inventory-v1/watcher-report.json`.
CE4 and the separately addressable unmigrated native/renderer charge writers
are zero. Scheduler scan/switch entries hit 64/42/42 times but are forced to
fallback by their zero gates. The generic
`gm_memclr/gm_verify_far/gm_memset_far` gateway labels each hit 19,262 times;
their identical counts prove chained checks, not accepted loop acceleration.
The task-frame split is still tick 14,746. The bounded result is pinned by
`tools/test_vtime_interpreter_only_active_owner_inventory.py`. A source-
authenticated accept/decline ledger inside that generic cluster is required
before disabling any loop or changing clock state.

The generic-loop ledger is now
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-generic-loop-ledger-v1/watcher-report.json`.
All 19,262 entries per family decline: accepted memclr, verify, and memset
counts are zero, including 1,594 word-shaped memset attempts. No collapsed
generic mutation occurs around any captured IRQ, and the split stays at tick
14,746. `tools/test_vtime_interpreter_only_generic_loop_ledger.py` pins this
exclusion. Another loop fallback is unjustified; the remaining narrow work is
disk-only comparison of the interpreter/common-clock cycle ledger with MAME's
retired-cycle truth.

That comparison is now
`build/playback-watcher-20260809/stage3-interpreter-common-clock-model-v1/watcher-report.json`.
It binds the published 16,308-cycle charge and 114,978-cycle deficit to the
older mixed preserve/native-on VTIME artifact, not SHA `7a22…` bit 1. The
16,308 value is 8,154 selected two-cycle units; MAME's pre-root span contains
11,006 instruction intervals, with 9,193 static-table exact and 1,813 dynamic
cases. Current bit-1 source already uses the static CPU-000 table and proven
dynamic corrections per interpreted fetch. The old deficit is therefore not
a license to retune the reload or charge formula.
`tools/test_stage3_interpreter_common_clock_model.py` pins this provenance.
The direct Luna measurement is now
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-phase-v1/watcher-report.json`.
After one invalid zero-boundary launch against the wrong Nexen companion set,
the corrected custom-build run exits zero, captures 4/4 boundaries, and matches
root 1/1. Between the tick-14,745 boundary and `$02429C`, SHA `7a22…` consumes
34,856 two-cycle units = 69,712 MC68000 cycles with no reload or IRQ, versus
MAME's 131,286. The candidate reaches root with 69,494 virtual cycles left;
MAME reaches IRQ 7,692 cycles later, leaving a direct 61,802-cycle phase error.
All four fallback gates and halt stay zero and the first split remains tick
14,746. `tools/test_vtime_interpreter_only_root_phase.py` pins the bounded
undercharge. The Luna fetch-count seam at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-fetch-count-v1/watcher-report.json`
then observes 6,471 prepare and 6,471 consume events, only 58.795% of MAME's
11,006 retired intervals (4,535 fewer), with no reload or IRQ in the exact
window. Gates and halt stay zero and both captured ticks retain their 21-byte
mismatch ranges. `tools/test_vtime_interpreter_only_root_fetch_count.py` pins
the result. A cycle-table retune is now rejected: the required next bounded
logical-PC comparison is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-pc-sequence-v1/watcher-report.json`.
Its valid 6,471/11,006 alignment records 4,551 MAME deletions and 13 SNES
insertions. The first deleted block is indices 223--234 at
`$0008E6…$0008D8`, immediately downstream of the unconditional `$0008DE`
MOVE.L run collapse at bank-$00 `mvc_check`; that owner explains 759 deleted
MOVE rows, not all 4,535 net missing fetches. The largest deletion is 2,970
rows dominated by `$024998` pool-scanner PCs, but direct native ownership is
not proven with all four gates zero. `tools/test_vtime_interpreter_only_root_pc_sequence.py`
pins the compact result.

The accelerator inventory had omitted `mvc_check`; it now declares that
boundary. The narrow VTIME pack patch sends its four-byte prefix to `$F2:B4D1`
and makes bit 1 fall back to `op_move_g` before any collapse mutation. Ordinary
ROM bytes and SHA `2dadd…` remain unchanged. Candidate SHA `a49eedc7…` is
`build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-v1.sfc`,
guarded by `tools/test_vtime_interpreter_only_mvc_fallback.py`; its bounded
checkpoint seam is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-fetch-v1/watcher-report.json`.
It recovers exactly 759 prepare/consume events (6,471→7,230), exactly matching
the aligned deleted MOVE rows, and increases virtual charge by 7,590 units to
42,446. Root remaining falls to 27,157 units, with no reload/IRQ or sampled
gate/halt/task/player regression. Both 21-byte mismatch ranges remain, and the
candidate is still 3,776 fetches short of MAME. The evidence guard is
`tools/test_vtime_interpreter_only_mvc_fallback_evidence.py`. This is a positive
partial fallback, not a common-clock repair or replay result. Its bounded PC
alignment at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-pc-v1/watcher-report.json`
confirms all 759 MVC rows now align, leaving 3,792 MAME deletions and 13 SNES
insertions. The same first 12-row deletion and largest 2,970-row deletion
remain; MAME has 2,096 `$0249xx` rows and the candidate zero. The next bounded
step is a real-bank `$9D:C000/$B000/$B800` ownership hook, not replay. The
compact guard is `tools/test_vtime_interpreter_only_mvc_pc_sequence.py`. The
completed owner probe at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-native-owner-v1/watcher-report.json`
records zero hits at `$00:D360/$D36E`, `$9D:C000`, `$9D:B000`, and `$9D:B800`
in the exact boundary-to-root window. Prepare/consume stays 7,230/7,230 and no
reload or IRQ fires. Therefore MAME takes an allocator/pool path the candidate
does not take; the missing PCs are not hidden inside native execution. The
guard is `tools/test_vtime_interpreter_only_root_native_owner.py`; reduce the
existing branch context and 21 differing bytes before another run. The
disk-only reduction at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-branch-context-v1/watcher-report.json`
places the whole 2,970-row MAME path between equal `$0007E4/$000766` scheduler
anchors; SNES executes no PC between them. MAME calls `$0249C2` and `$02498C`
from `$02E8B8/$02E8C4`. None of the 21 differing bytes is a named operand;
only eight lie in mapped work RAM. The tracked game-tick low byte `$F01C57`
is nevertheless MAME `$97` versus candidate `$96`. This pins a one-count
boundary offset, not a causal dependency on the skipped path. Zero-advance,
ROM-migrated reads of retained v6 gameplay-origin tick 221 and safe tick 250
already contain the same one-count offset (`$00DA/$00DB` and `$00F7/$00F8`),
so Stage 3 did not create it. Those reads are checkpoint provenance, not a
fresh-current-candidate acceptance run. The corrected tick-14,000--14,002
comparison shows `$F01C56` advancing on both sides; its initially reported
stall was instead the separate IRAM `$0760` exact-entry counter.
`tools/test_vtime_interpreter_only_root_branch_context.py`,
`tools/test_vtime_interpreter_only_origin_phase_bytes.py`, and
`tools/test_vtime_interpreter_only_phase_counter_scope.py` guard this scope.
The bounded exact-selection probe then records tasks
`0,1,2,3,4,5,6,12,13,14,15`; task 13 restores `$02E864` before task 15, so
the scheduler does not skip it. The retained VTIME prepare stream has zero
interior prepares between task 13's exact `$0007E4/$000766` anchors versus
2,970 retired MAME rows. That is an accounting gap, not a path verdict: the
independent IRAM-PC-write reduction records `$0007E8→$02E864`, twelve ordered
`$02E8B8→$0249C2→$02498C` visits, and `$000532→$000766`, matching MAME's
target counts. The pool route therefore runs, but bypasses VTIME prepare/clock
ownership. PC writes establish ordered state updates, not retirement; identify
the physical fetch-control owner before changing gameplay code. The compact
guards are `tools/test_vtime_interpreter_only_root_task_selection.py`,
`tools/test_vtime_interpreter_only_root_task13_pc.py`, and
`tools/test_vtime_interpreter_only_root_task13_pcwrite.py`.
The fetch-control probe then sees 2,971 `choke_tramp` entries but only one
VTIME choke/consume/prepare. The packed pre-arm check was direct-page
`LDA $2E`—emulated A3.H—not absolute `$072E`. The diagnostic-only repair uses
the exact absolute gate; the then-ordinary ROM SHA `2dadd12c…` remained
unchanged and
the fixed candidate SHA is `d91e28e9…`. Its task-13 fetch/choke/consume/prepare
counts are all 2,971 with unchanged scheduler frame, gates, halt, and exact
next-scan stop. Boundary-to-root prepares rise from 7,230 to 11,010 against
11,006 MAME rows. Prefix-normalized PC alignment fully restores the former
2,970-row task-13 region and leaves only the same twelve-PC signature deleted
then reinserted plus a terminal candidate `$0007E8`. The completed disk-only
reduction resolves those twelve PCs as one complete palette loop with equal
active counts but different mask phase: MAME `$00030000` selects ordinals
16--17 and the candidate `$0000C000` selects 14--15. Task-15 producer evidence
follows the same `$003B42→$003B46→$003B4C→$003B50→$0008C2` chain on both sides.
The candidate's `$F01C56/$F01C58` rolling state is one call behind, exactly as
it already was in zero-advance retained tick-221 and tick-250 states. Thus the
ordering seam is checkpoint-origin provenance, not a new Stage-3 execution or
clock deficit. MAME's intermediate write/read/clear is directly retired;
candidate `$F01B12` is inferred from the PC sequence and work state because the
single bounded hook attempt ended before its target. Proceed with a bounded
checkpoint continuation; do not call the repair global clock, rate, or
acceptance. Guards are
`tools/test_vtime_interpreter_only_root_task13_fetch_control.py`,
`tools/test_vtime_interpreter_only_choke_gate.py`,
`tools/test_vtime_interpreter_only_choke_gate_evidence.py`,
`tools/test_vtime_interpreter_only_choke_gate_root_fetch.py`, and
`tools/test_vtime_interpreter_only_choke_gate_pc_sequence.py`, plus the
`...first12_context.py`, `...first12_mask.py`, and `...mask_writer.py` guards.
At the time of the retained `d91e…` experiment, the campaign runner rejected
cross-ROM continuation from the old tick-14,743 state because serialized WRAM
carried the prior video supervisor. The runner now has an explicit
diagnostic-only migration path: it authenticates the old atomic checkpoint,
refreshes only `$7F:8000-$7F:AFFF` from the selected ROM, and proves every
other visible CPU/PPU/memory domain unchanged. This permits focused candidate
iteration from a nearby pre-divergence state, but does not bypass the fresh-
boot acceptance blocker. The retained 89-image forensic continuation still
moves the observed task-15 split to tick 14,747 and remains neither resumable
nor accepted evidence for its candidate.

The requested exact tick-14,746 boundary-to-root reduction is now complete on
the aligned `d91e28e9…` ledger. Candidate charge is 61,277 two-cycle units and
MAME charge is 60,699, an endpoint overrun of +578 units/+1,156 cycles. Its
largest equal-PC discrepancies exposed a real diagnostic defect: both DBcc
timing helpers used a two-byte rather than four-byte D-register stride. The
conditional VTIME fix produces interpreter-only SHA `7583d110…` while leaving
the then-ordinary SHA `2dadd12c…` byte-identical.

A disk-only aligned counterfactual covers 493 DBcc pairs at 22 PCs. Correcting
their outcomes removes 246 units/492 cycles. The remaining +332 units are not
another DBcc overcharge: after deferred native/RTS charge observability
cancels, they consist of a candidate-only 61-row collision path (+326), the
known checkpoint-origin mask phase (+5), and +1 common-path timing unit
(`DIVU` +2, Bcc -1). Do not add a PC-specific DIVU exception; exact MAME 0.287
expresses its operand-dependent division timing in the cycle-core microcode,
not a compact helper suitable for a general repair.

The bounded cumulative `7583d110…` result is not an aligned oracle closure.
Although its endpoint is -19 units from MAME, its task-15 frame already differs
at tick 14,746 (`$025856` versus `$0259B0`). The one attempted isolated replay
from the old exact tick-14,746 state reached no requested boundary in 719
frames and ended at `$F01B6C`/halt `$DEAD`; that ordinary paused state is
explicitly nonresumable. Do not repeat it.

Fresh `7583d110…` then accepted zero of eight credit pulses. The preserved-ROM
bisect at
`build/playback-watcher-20260810/fresh-credit-bisect-v1/watcher-report-v2.json`
brackets the regression between `60087042…` (8/8 credits) and `7a22b819…`
(0/8), exactly at the diagnostic `$0818` pre-mutation fallback. Both CPUs are
running in the retained red state, but pacing arm/last-release/debt are zero
and frame request/ack is 64/0. The gateway bypassed the paced S-CPU/NMI input,
render, and release rendezvous; later MVC, choke, and DBcc stages are excluded.

The pure-interpreter `$0818` fallback is now explicit opt-in bit 2. Default
interpreter-only VTIME uses the paced helper and produces diagnostic SHA
`14e920eb…`; the then-ordinary SHA `2dadd12c…` remained byte-identical. Same-ROM neutral
calibration found the changed gameplay-origin phase at a 3,224-frame credited
wait. Its single calibrated fresh run is partial-green through MAME tick 250:
8/8 credits, exact interpreted tick-221/RNG-200 origin, 29 neutral gameplay
ticks, zero oracle divergence, and halt zero. The repeat-validated resumable
tick-250 state has SHA `ba6f0490…` and sidecar SHA `8950c547…` at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-fresh-to250-calibrated-v1/`.
This is only a bounded lineage seed. Resume it in bounded same-ROM segments;
do not replay the fresh bootstrap. The first supplied resume used completed
tick 250 rather than resume tick 251 and was rejected before emulator launch;
the event contract and regression now pin 250-completed/251-resume. The
corrected lineage is partial-green through tick 806 (555/555 entries) and then
tick 1,100 (293/293): cumulative 877/877 interpreted entries, 12/12 player
references, six real input transitions, zero oracle divergence, and halt zero.
Repeat-identical resumable checkpoints at ticks 806 and 1,100 have SHAs
`fe4a5409…` and `27207e5f…`; the latter sidecar is `5cb96e4f…` and resumes at
1,101. The exact lineage then continues partial-green to tick 3,000 across
1,899/1,899 more entries and 2,776/2,776 cumulative entries. It has 168/168
player references, 84 real input transitions, every gameplay button, actions
0/1/2/8/9, one death with 2/2 green death references, zero oracle divergence,
halt zero, valid task stacks, and live rendering. Actions 3/4/5/7/10 and bosses
remain missing. Repeat-identical safe checkpoints at 1,500/2,000/2,500/3,000
prevent prefix replay; tick 3,000 is SHA `47dc58a1…`, sidecar `4ee69101…`, and
resumes at 3,001. Preflight-only wrong-Nexen and pinned-MAME-launcher negatives
are retained but launched no gameplay. The next same-ROM segment remained
green through tick 4,559 before an isolated Nexen MCP server exit. It produced
no oracle mismatch, halt, invalid stack, or renderer failure, and its repeat-
identical tick-4,500 bundle was safe. A bounded same-hash recovery replayed
only ticks 4,501--4,559 and reached tick 5,000 with
`--continue-oracle-divergences`: 499/499 segment and 4,833/4,833 cumulative
entries, 921/921 player references, 85 real transitions, every action ID, two
deaths with 4/4 green death references, zero divergence, halt zero, and
minimum task-stack margin 138. Bosses remain missing. Tick 5,000 is SHA
`0fd2e312…`, sidecar `9e6e7605…`, and resumes at 5,001. The transport stop
invalidates no accepted gameplay evidence and requires neither a rebuild nor
a fresh boot.

The next Luna-owned same-hash segment reaches tick 6,500 with zero divergence:
1,499/1,499 segment and 6,332/6,332 cumulative entries, 1,210/1,210 player
references, 605 real transitions, every action ID, two deaths with 4/4 green
death references, halt zero, live rendering, and minimum task-stack margin
138. Bosses remain missing. Repeat-identical checkpoints at 5,500/6,000/6,500
cap replay cost; tick 6,500 is SHA `fb9644dd…`, sidecar `26c824b3…`, and
resumes at 6,501.

The first child launched at 6,501 exposed a harness-only boundary bug before
completing any entry: because the resume tick itself was an input edge, the
event loop correctly had zero entries to execute but indexed `spans[-1]`.
`OSError(9)` was secondary cleanup. The harness now skips zero-entry execution
and span indexing, processes the edge once, and advances at 6,502; the focused
resume-edge regression is green. The failed child invalidates no tick-6,500
evidence and does not implicate or rebuild the ROM.
The first corrected retry was preflight-only: the finite runner-identity gate
rejected the changed harness before emulator launch. Exactly the tick-6,500
parent runner SHA `2030c213…` is now admitted for this reviewed zero-entry-only
successor, while arbitrary runner drift remains rejected by regression. The
preflight negative invalidates no evidence.

The corrected v3 continuation is partial-green through tick 8,000:
1,499/1,499 segment and 7,831/7,831 cumulative entries, 375/375 segment and
1,585/1,585 cumulative player references, 188 segment and 793 cumulative real
transitions, every action ID, two deaths in this segment, 6/6 cumulative death
references, zero divergence, halt zero, live rendering, and all 15 initialized
task stacks valid with minimum margin 130. Bosses remain missing. Repeat-
identical checkpoints at 7,000/7,500/8,000 cap replay cost; tick 8,000 is SHA
`aea7ce50…`, sidecar `99bab411…`, and resumes at 8,001. No rebuild or fresh
boot occurred.

The next same-hash segment is partial-green through tick 9,500: 1,499/1,499
segment and 9,330/9,330 cumulative entries, 1,852/1,852 cumulative player
references, 926 cumulative real transitions, every action ID, two deaths in
this segment, 8/8 cumulative death references, zero divergence, halt zero,
live rendering, and all 15 initialized stacks valid with minimum margin 138.
Bosses remain missing. Repeat-identical checkpoints at 8,500/9,000/9,500 cap
replay cost; tick 9,500 is SHA `efd193b0…`, sidecar `fabcd919…`, and resumes
at 9,501. No prefix replay, rebuild, or fresh boot occurred.

The next same-hash segment is partial-green through tick 11,000: 1,499/1,499
segment and 10,829/10,829 cumulative entries, 2,402/2,402 cumulative player
references, 1,201 cumulative real transitions, every action ID, two deaths in
this segment, 10/10 cumulative death references, zero divergence, halt zero,
live rendering, and all 15 initialized stacks valid with minimum margin 138.
Bosses remain missing. Repeat-identical checkpoints at 10,000/10,500/11,000
cap replay cost; tick 11,000 is SHA `6fd49508…`, sidecar `ef9a8033…`, and
resumes at 11,001. No prefix replay, rebuild, or fresh boot occurred.

The next same-hash segment is partial-green through tick 12,500: 1,499/1,499
segment and 12,328/12,328 cumulative entries, 2,566/2,566 cumulative player
references, 1,283 cumulative real transitions, every action ID, two deaths in
this segment, 12/12 cumulative death references, zero divergence, halt zero,
live rendering, and all 15 initialized stacks valid. Minimum stack margin fell
from 138 to 92 and remains an explicit safety watch. Bosses remain missing.
Repeat-identical checkpoints at 11,500/12,000/12,500 cap replay cost; tick
12,500 is SHA `0ff1242f…`, sidecar `83608462…`, and resumes at 12,501. No
prefix replay, rebuild, or fresh boot occurred.

The next same-hash segment is partial-green through tick 14,000: 1,499/1,499
segment and 13,827/13,827 cumulative entries, 2,650/2,650 cumulative player
references, 1,325 cumulative real transitions, every action ID, no new deaths,
12/12 cumulative death references, zero divergence, halt zero, live rendering,
and all 15 initialized stacks valid; minimum margin recovered to 138. Bosses
remain missing. Repeat-identical checkpoints at 13,000/13,500/14,000 cap replay
cost; tick 14,000 is SHA `234ef4ad…`, sidecar `a5d1d340…`, and resumes at
14,001. No prefix replay, rebuild, or fresh boot occurred.

The same-hash continuation then runs safely through tick 15,500, but the exact
green prefix ends at 14,747. At tick 14,748 SNES player Y is 139 versus MAME
136 while the other compared player fields match. There are 27 Y-only records
at 24 sparse ticks through 14,866, followed by no further recorded mismatch
through 15,500. The segment completes 1,499/1,499 entries and 15,326/15,326
cumulative entries with halt zero, live rendering, and 15 valid initialized
stacks at minimum margin 138. End SNES tick 15,494 versus MAME 15,500 exposes
a changed tick offset that is being tested as a possible alignment cause rather
than assumed to be semantic Y corruption. No Stage-transition or boss event
was emitted. Repeat-identical checkpoints at 14,500/15,000/15,500 cap focused
replay; tick 15,500 is SHA `43f9c07c…`, sidecar `d5dff99d…`, resume 15,501.
Focused same-ROM reduction initially identified an interrupt-entry/endpoint-
ownership defect, but its causal attribution to the Y mismatch is superseded.
The corrected `$025110` alignment has 553 common retired rows with
identical PCs/opcodes and zero adjusted-cost delta; the earlier repeated-loop
`+132` and `$02584A` mismatch claims were bad endpoint alignment and are
invalid. At the real `$0818` virtual IRQ, the staged pre-IRQ cost survives
expiry/reload and is consumed by the first ISR fetch, the last ISR JSR remains
staged across the first `$003A92` observation, and the separate 66-cycle MAME
IRQ edge has no VTIME owner. The aligned `$003A92->$025110` span is only `+26`
candidate cycles. This remains a real clock-accounting defect, while later
counterfactuals exclude it as the causal repair target for tick 14,748. The
compact report is
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume14001-to15500-v1/focused-y-write-v1/irq-cost-pipeline-v1/irq-cost-report.json`;
`tools/test_vtime_interpreter_only_irq_cost_pipeline.py` guards it.

The active blocker at this seam was ordered input publication. On retained v4
`4a3555fd…`, neither a `+2` clock seed nor a direct one-unit child-entry
countdown decrement changes the tick-14,748 Y mismatch. The corrected immediate
ordering instead has `$003AD8` read before any next `$0818` re-arm; arm=2 keeps
the ordered mailbox publisher out, leaving `$410000=0000` and candidate P1
`$FF` despite the completed `$0088` NMI sample, while MAME consumes `$EE`.
Direct latest-sample staging in v6 `928d2e72…` moves the mismatch one tick early,
confirming that the missing contract is a one-game-tick ordered delay rather
than immediate publication.

The v7 diagnostic implements that delay only at `input_p1`, preserves generic
`joy_read` and real `$0818` mailbox ownership, and uses `$41012B` to distinguish
a genuine release from an intervening virtual tick. ROM
`build/interp-vtime-interpreter-only-paced0818-dbcc-irq-entry-vpa-input-delayed-v7.sfc`
is SHA-256 `45c9096dfda3d4203878c18954725ff4814f23f4e28a1e623f3cf07b647e6c72`.
Luna's ROM-only tick-14,745 checkpoint continuation is green through 14,750:
2,746/2,746 player rows, 12/12 death rows, no oracle divergence, and three
byte-identical tick-14,750 checkpoints. See
`build/playback-watcher-20260811/v7-input-delayed-migrated14745-to14750-v2/watcher-report.json`.
The same-ROM suffix at
`build/playback-watcher-20260811/v7-input-delayed-resume14751-to15000-v3/watcher-report.json`
is then partial-green through tick 15,000: 2,772/2,772 cumulative player rows,
12/12 death rows, 1,386 input transitions, no oracle or liveness divergence,
live rendering with zero queue drops, and all 15 initialized task stacks valid
at minimum margin 138. The former tick-14,748 input/Y seam remains corrected.
The repeat-identical tick-15,000 state is `918098c4…`, IRAM `43c45f3c…`, and
resumes at 15,001. An initial retry was rejected before emulator launch because
the retained lineage's runner and Nexen identities were not selected. The
finite `b1e0c365…` predecessor-runner admission is guarded without accepting
arbitrary drift; a later external termination at 14,761 was green and produced
no new checkpoint. Neither negative implicates the ROM. This clears only the
bounded migrated-lineage Y/input seam. V7 still lacks fresh-boot, boss,
performance, hardware, production, and playthrough acceptance; no fresh
campaign was started.

The exact-v7 continuation remains player/input/death-oracle green through
16,000. Its original report marks Stage-1 boss rows at 15,906 and 15,988 red,
but those rows are invalid comparisons. The runner subtracted 75 from fixture
write frames while all 139,925 authenticated timeline tick rows use an exact
frame-minus-74 write boundary; since campaign stops are pre-body, committed
health is observed at the following tick start. The final 100-tick replay is
green at 15,908/15,990. At 16,000 it has 2,889/2,889 cumulative player rows,
12/12 death rows, 1,445 input transitions, 2/2 boss rows, halt zero, zero
renderer queue drops, and 15 valid initialized task stacks at minimum margin
138. See
`build/playback-watcher-20260811/v7-input-delayed-resume{15001-to15500-v1,15501-to16000-v1}/watcher-report.json`.
The boss writes occur during MAME/SNES `15907/15901` and `15989/15983` and are
observed at the next pre-body stops, `15908/15902` and `15990/15984`. Focused
exact-state hooks show init storing big-endian `$0028` and hit 1 storing
`$0024`; both words commit exactly. The compact reduction is
`build/playback-watcher-20260811/v7-boss-health-write-window-v2/raw-classification.json`,
produced by `tools/trace_v7_boss_health_window.py`. The focused regression
`tools/test_boss_fixture_frame_tick_boundary.py` pins the runner constant, both
write/observation pairs, health transitions, and every retained timeline tick
row. The final green compact report is
`build/playback-watcher-20260812/v7-boss-observation-resume15901-to16000-v1/watcher-report.json`.
This excludes an independent initializer/subtractor defect for those writes
and removes the supposed organic one-update scheduler root; later boss hits
are not yet v7-proven. The
repeat-identical tick-16,000 state is `06da361f…`, IRAM `3a672763…`, resume
16,001. No ROM rebuild or fresh boot occurred; this harness correction does
not justify either one.

The corrected v7 suffix continues through tick 16,500 with six cumulative
Stage-1 boss observations green. New green rows are MAME ticks
16,102/16,201/16,285/16,403, with health 34/31/29/25; player, input, and
death references remain green, with no oracle divergence, halt zero, zero
renderer queue drops, and minimum initialized-stack margin 138. The
repeat-identical tick-16,500 state is `f6c5b389…`, IRAM `5de396c8…`, and
resumes at 16,501. Report:
`build/playback-watcher-20260812/v7-boss-observation-resume16001-to16500-v1/watcher-report.json`.
This validates only the first six Stage-1 fixtures, not full-boss behavior,
fresh boot, production, performance, or playthrough acceptance.

The corrected v7 suffix then reaches tick 17,000 with 11 cumulative Stage-1
boss observations green. New rows are MAME ticks 16,519/16,624/16,750/16,837/
16,921 with expected and observed health 21/18/14/11/9. Player, input, and
death references remain green with no oracle divergence, halt zero, zero
renderer queue drops, and minimum initialized-stack margin 138. The
repeat-identical tick-17,000 state is `1bab53c8…`, IRAM `bf80c888…`, and
resumes at 17,001. Report:
`build/playback-watcher-20260812/v7-boss-observation-resume16501-to17000-v1/watcher-report.json`.
This validates the retained first 11 Stage-1 fixtures only, not complete
Stage-1 boss behavior, full-boss, fresh boot, production, performance, or
playthrough acceptance.

The corrected v7 suffix reaches tick 17,500 with 12 cumulative Stage-1 boss
observations green. The new row is MAME tick 17,020 with expected and observed
health 6. Player, input, and death references remain green with no oracle
divergence, halt zero, zero renderer queue drops, and minimum initialized-stack
margin 138. The repeat-identical tick-17,500 state is `9f785e78…`, IRAM
`b1a53fde…`, and resumes at 17,501. Report:
`build/playback-watcher-20260812/v7-boss-observation-resume17001-to17500-v1/watcher-report.json`.
The last two Stage-1 fixtures remain pending; this is not complete Stage-1 boss
behavior, fresh boot, full-boss, production, performance, or playthrough
acceptance.

The corrected v7 suffix reaches tick 18,000 with all 14 retained Stage-1 boss
fixtures green. New rows are MAME ticks 17,562 and 17,656 with expected and
observed health 2 and `$FFFF`. Player, input, and death references remain
green with no oracle divergence, halt zero, zero renderer queue drops, and
minimum initialized-stack margin 138. The repeat-identical tick-18,000 state
is `d06e3fb9…`, IRAM `fdfe1d7d…`, and resumes at 18,001. Report:
`build/playback-watcher-20260812/v7-boss-observation-resume17501-to18000-v1/watcher-report.json`.
This completes the retained Stage-1 fixture set only; it is not fresh boot,
full organic boss behavior, full playthrough, production, or acceptance.
Stage-2/3 boss fixtures remain pending.

The corrected v7 lineage continues from ticks 18,001 through 20,000 with no
new divergence and the 14/14 retained Stage-1 boss fixtures cumulatively green.
Successful compact reports are
`build/playback-watcher-20260812/v7-boss-observation-resume18001-to18500-v1/`,
`.../resume18601-to19000-v3/` (after recovery),
`.../resume19001-to19500-v1/`, and
`.../resume19501-to20000-v1/`. The 18,501–18,649 transport attempt stalled
after a repeat-safe 18,600 state; stale exact processes were terminated, a
first retry timed out before session establishment because of a stale port,
and the secondary unbound-`m` capture bug was fixed in `d309c67` before fresh-
port recovery completed green. Endpoint tick 20,000 is state `25b60a…`, IRAM
`128013bd…`, resumes at 20,001, with halt zero, minimum stack margin 136, and
zero renderer drops. This remains checkpointed-v7 evidence; the next boss
fixture is Stage 2 at MAME tick 36,227, and fresh boot, full playthrough, and
production acceptance remain unproven.

The older `14e920eb…` unchanged-hash continuation reaches tick 17,000 with halt zero,
15 valid initialized stacks at minimum margin 138, and live rendering. Its 38
segment divergences comprise 13 input, 14 input-response, and 11 Stage-1 boss
rows. The boss fixtures span sparse MAME ticks 15,906--16,919 and every SNES
row is exactly six game ticks behind. Initialization reads 0 instead of 40;
each later observed health is the prior fixture's expected health. This is
the signature of the now-rejected frame-minus-75 comparison, not downstream
ROM timing evidence or an independently proven boss-health semantic root.
Those rows are neither red nor green boss acceptance. Repeat-
validated checkpoints exist at 16,000/16,500/17,000; tick 17,000 is state
`a9826e63…`, sidecar `cdf1a8c7…`, resume 17,001. The compact reports are under
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume15501-to17000-v1/`.

The next same-hash Luna continuation reaches tick 18,500. Its three new boss
rows retain the same one-fixture lag: expected/observed health is `6/9` at
17,018, `2/6` at 17,560, and `$FFFF/2` at 17,654. Cumulative divergence
classes in that historical report are 13 input, 14 input-response, and 14
invalidly sampled boss rows. They need corrected post-write observation before
being classified green or red. Halt is zero, rendering remains live,
and all initialized stacks remain valid at minimum margin 138. Repeat-
validated checkpoints at 17,500/18,000/18,500 cap replay cost; tick 18,500 is
state `718d3dd3…`, sidecar `a14d74b7…`, resume 18,501. This remains forensic
post-divergence coverage only.

The same-hash continuation then reaches tick 20,000 with no new mismatch or
boss-fixture row. Historical counts remain 13 input, 14 input-response, and 14
invalid boss classifications. Halt stays zero, rendering is live, and all
initialized stacks remain valid at minimum margin 136. Repeat-validated
checkpoints at 19,000/19,500/20,000 cap replay cost; tick 20,000 is state
`caf9df72…`, sidecar `f06ec2ad…`, resume 20,001. This expands forensic
coverage only; it does not move the accepted tick-14,000 boundary.

Fixing the packed VTIME/IRQ handoff requires a new ROM hash, but the exact
replacement charge and boundary protocol still require focused proof. No
timing edit, rebuild, or fresh replay has occurred. A new lineage would need
fresh acceptance replay from calibrated tick 221 through this boundary;
current-hash evidence remains preserved as historical/diagnostic evidence.

Do not claim Stage 3, complete boss behavior, rate, promotion, or acceptance
from this Stage-1 prefix. Keep long playback Luna-owned and on this ROM hash;
continue post-divergence when state safety permits, diagnose from the nearest
checkpoint, and batch nonblocking fixes. Before creating another ROM lineage,
state the confirmed root cause, rebuild necessity, and fresh evidence that
would be invalidated. Builds and bounded fresh-power regression gates do not
require separate approval; a full long gameplay campaign requires explicit
user approval. The old ledger, fresh bisect, paced default, calibration, and
checkpoint contracts are guarded by the focused
`tools/test_vtime_interpreter_only_*dbcc*.py`,
`tools/test_vtime_interpreter_only_choke_gate_vtwrite_charge.py`, and
`tools/test_vtime_interpreter_only_0818_paced_default.py` tests. The transport
and recovery artifacts are guarded by
`tools/test_vtime_interpreter_only_paced_campaign_current_hash.py`.

The new power-on exact-MAME owner-activity probe at
`build/mame-scheduler-cycle-phase-current-a976-14743-14747-v3` observes 5,055
program-space reads across ticks 14,743--14,747. Its labels cover scheduler,
idle, task-15, and collision seams but may be data reads or prefetches, so they
are never treated as retired instructions or block-cost evidence. The joined
and guarded report `build/validate-mame-scheduler-cycle-phase-current-a976-v2.json`
uses the instruction-only MAME trace for the actual IRQ record: `$000818`,
`$0259B0`, `$02582E`, `$000810`, at periods 139,300/139,302/139,296/139,342 cycles.
It leaves parent/child handoff timing, the common clock, the SNES Stage-3
repair, rate, and playthrough explicitly open.

The one-tick Stage-3 native-entry trace has an active-ROM/source address
provenance guard at
`build/validate-active-native-entry-alignment-current-a976-safe14743-v2.json`
(`tools/test_active_native_entry_alignment.py`). Its 240 source-labelled
events are 236 exact source-byte matches plus four hits at the two documented
production counter-strip sites. This corrects the initial `$9F` packing
mistake: `escbank9` is packed at `$9F:A100` / file `$2FA100`. It makes the
observed hook addresses usable for diagnosis, but does not make dirty-source
`b758…` a substitute for `a976…`, prove unobserved code, or reduce the
common-clock/timing blocker.

The active `a976…` checkpoint now has one same-hash stop-by-stop hotspot
sample at `build/profile-stage3-tick-current-a976-safe14743-v1/profile.json`,
guarded by `tools/test_stage3_current_a976_profile_evidence.py`: 1,936,861
SA-1 cycles, 11 video frames, and 413 genuine interpreter fetches for one
perturbed update. `$0242BE` is largest at 101,454 cycles (5.24%) and the top
20 account for 40.35%, so neither one bridge nor CE4 alone can be asserted as
the usable-rate root. It is selection evidence only; the no-hook rate miss,
common-clock repair, and full fresh-boot performance gate remain open.

The explicit logical-region reduction
`build/analyze-stage3-current-a976-hot-regions-safe14743-v1.json`
(`tools/test_stage3_current_a976_hot_regions.py`) identifies two larger but
still nonexclusive candidate families: `$027B00-$027BFF` record emission is
32.52% and `$02E40E-$02E55B` draw dispatch/call setup is 18.71% of the
perturbed tick. The profile's top rows cover 88.50% and leave a further 23.99%
of the complete tick outside these families; do not treat either percentage as a native
block-cost or a standalone rate-fix prediction.

The full dirty-source `b758…` terminal-CCR build is rejected: its 2,749-byte
drift fails its fresh campaign after only 10 requested updates in 2,456 video
frames (`build/fresh-candidate-2429c-tstb-ccr-b758-to3000-v2/summary.json`).
All later `5c7e…` boss, crate, and renderer references are predecessor evidence
until their exact current-hash reruns. The current Stage-3 timing/rate blocker
above remains open.

The exact current `5c7e…` fresh one-credit title/HUD checks are green in Nexen
(`build/validate-fresh-one-credit-prompt-current-5c7e-nexen-v1/summary.json`)
and legacy Mesen
(`build/validate-fresh-one-credit-prompt-current-5c7e-mesen211-v1/summary.json`):
the right artwork wedge, transparent CREDIT underlay, lower-right area, one
credit, and halt checks pass. The current-hash fresh-power-on continuation is
also green through tick 10,000 at
`build/fresh-campaign-current-5c7e-resume10000-v2`: 2,062 player reference
comparisons, five matched deaths, zero player-oracle divergences, zero halts,
and action states 0/1/2/3/4/5/7/8/9/10. It is bounded coverage only; current
crate matrix, Stage-3 three-way, Stage-3 rate, and a full campaign remain
queued. The current-hash ordinary-enemy matrix is green 4/4 at
`build/validate-gameplay-damage-current-5c7e-v1`: exact MAME,
gameplay-native-off, and production-native-on agree for Button 1 punch,
Button 2 kick, contact, and charged-projectile health damage. Do not promote
preceding 9dcc boss/crate matrices solely because the disabled path is
byte-checked.

After the focused diagnostic tests, the restored active hash has a second
fresh-power-on Nexen renderer/HUD replay at
`build/validate-fresh-one-credit-prompt-current-5c7e-esc9-post-v1/summary.json`.
One real credit again passes all seven prompt predicates. This confirms only
the fresh title/HUD path; it does not close the Stage-3 timing or gameplay
blockers.

The post-focused active ROM has also passed a separate fresh-power-on root
controller replay through tick 10,000 at
`build/fresh-campaign-current-5c7e-post-focused-to10000-v1`: 1,031 real input
transitions, 2,062 green player comparisons, five matched deaths, action
states 0/1/2/3/4/5/7/8/9/10, no state load, no ROM/game-state mutation, no
halt, and no divergence. It covers punch/charge, kick, flight, crate
pickup/carry/throw, hurt, and respawn, but does not prove a boss, rate, or
full playthrough.

The current-hash boss matrix is also green 118/118 at
`build/validate-boss-health-current-5c7e-v1.json`: both SNES configurations
and original MAME agree across retained organic init/damage-handler states for
the arcade 40 HP / 13-hit, 40 HP / 37-hit, and 20 HP / 6-hit sequences. This
is bounded IRQ-masked handler evidence, not an organic continuous SNES boss
fight.

The current-hash organic crate carry/throw branch is green at
`build/validate-organic-crate-current-5c7e-v1/summary.json`, resumed from its
same-hash fresh-power-on tick-3,000 safe state. All 87 MAME/native-off/native-
on controller entries agree: carried contact has no enemy-health transition,
while the Button-1 throw has the two original one-point transitions at ticks
3,274 and 3,283. Up+Right flight-contact is also green at
`build/validate-organic-crate-flight-current-5c7e-v1/summary.json`: the
MAME-confirmed carried-crate/enemy overlap and Up+Right ascent have zero
enemy-health transitions in native-off and native-on as well as original MAME.

The current-hash continuation is green through its authenticated tick-14,743
safe state (`build/fresh-campaign-current-5c7e-resume14743-v1`), then the
three-way task-frame gate is intentionally red at tick 14,746
(`build/validate-stage3-irq-order-current-5c7e-v1.json`). Original MAME saves
task 15 at `$0259B0` / `$0242BE`, SR `$2400`; both gameplay-native-off and
production-native-on SNES save `$02429C` / `$00044E`, SR `$2404`, and then
shift collision/RNG. The fresh current-hash replay independently reaches the
downstream false respawn at tick 14,841
(`build/fresh-campaign-current-5c7e-resume14841-v1`); it retains the
deterministic pre-failure tick-14,839 state. This keeps virtual-IRQ timing as
the priority-zero root, not a native-only collision or stale-save-state issue.
The current native-on delivery reproducer
`build/capture-stage3-irq-delivery-current-5c7e-v3/summary.json` additionally
reloads that authenticated state in a fresh Nexen process and requires exact
public-state/SA-1-IRAM restoration before it restores the recorded controller
input. It remains red: the third `$025110` entry completes without a mid-call
yield and the virtual IRQ begins at `$0818` while task 15 remains
`$02429C`/`$00044E`, rather than the MAME `$0259B0`/`$0242BE` frame. This
does not make a fresh-boot, native-off, rate, or repair claim.

The authenticated active-ROM call-site trace at
`build/trace-stage3-ac94-callers-current-5c7e-v1/summary.json` narrows the
same physical window: all 82 bank-$94 legacy-charge call sites were observed,
and the 36 additional calls in red tick 14,746 are 12 visits each to the
three `$02E40E` 3/2/5-instruction blocks at `$94:D548/$94:D567/$94:D586`.
This is a variable-work trigger for the late IRQ, not a safe one-leaf fix:
the all-interpreted/native-off configuration fails at the same logical frame.
The priority-zero repair remains a common virtual MC68000 cycle clock across
interpreter, native helpers, scheduler, renderer, and `$0818` pacing. The
focused reproduction guard is green at
`build/validate-stage3-ac94-variable-work-current-5c7e-v1.json`; that green
result preserves the red failure trigger and is not a repair verdict. The
original-MAME ledger reduction at
`build/analyze-stage3-2e40e-cycles-current-5c7e-v1.json` measures this leaf at
80 cycles for `D0.b < 7` and 94 for `D0.b >= 7` (the red update has 7 and 14
of those paths, respectively); it remains a component ledger, not a safe
one-leaf timer patch. The authenticated native countdown trace directly
observes each red-tick `$94:D548/$94:D567/$94:D586` triple subtracting 3/2/5
legacy `$AC` units, instead of the MAME leaf's 80/94 cycles. Its regression is
`build/validate-stage3-ac94-countdown-current-5c7e-v1.json` and
`tools/test_stage3_ac94_countdown.py`; green means the mixed-unit defect is
still reproduced, never that a leaf or timer fix was accepted.

The diagnostic source now has an **unwired** `$F2:FE40` native-parent to
interpreter-child handoff helper, packed in
`build/interp-vtime-native-handoff-diagnostic-v1.sfc` (SHA-256
`ace8098e…`). It can flush one selected `$025110` or player deferred block,
fails closed for an unknown owner, and deliberately leaves the caller's
post-transfer PC/stack/IRQ decision untouched. Its assembled-byte guard is
`tools/test_vtime_native_handoff.py`. No escape invokes it, so this is a
ledger-ownership prerequisite only—not a timing repair, performance result, or
fresh-ROM validation. The authoritative active image remains `5c7e…`.

The same helper's retained direct-Nexen synthetic execution is green at
`build/validate-vtime-native-handoff-runtime-v1/summary.json`, with pre-call
states retained for both admitted owners and the fail-closed unknown-owner
case. `tools/test_validate_vtime_native_handoff_runtime.py` guards the result.
It tests no organic caller and therefore does not reduce the timing blocker.

The matching emitted-source audit
`build/audit-stage3-2429c-handoff-protocol-current-5c7e-v1.json` prevents a
parent-only `$02429C` timer change: the root has zero local charges, its first
site is a guarded three-callee fusion, and its other emitted children are four
direct-native and six OJMP transfers. Each needs the parent flush, successor
owner, and exact deadline return decision at the same seam. The source guard
is `tools/test_stage3_2429c_handoff_protocol.py`; it describes an unimplemented
ownership protocol, not a VTIME implementation or timing result.

The unconsumed root metadata generator
`tools/gen_vtime_esc5_charge_table.py` and its guard
`tools/test_vtime_esc5_charge_table.py` retain 35 ordinal records in
`build/gen-vtime-esc5-charge-table-current-5c7e-v1.json`. The output is not
packed and has no return-address index; no source charge seam exists to select
one. It is a ledger prerequisite, not an implementation advance.

The canonical fused empty-helper span is exact-MAME measured at 798 cycles
(399 two-cycle units) from `$023342` to `$0242B2` in all four retained cases:
`build/validate-mame-2429c-empty-fusion-current-f369-v1.json` and
`tools/test_mame_2429c_empty_fusion.py`. Any opaque-fusion path must fall back
before the span when it could cross a deadline. This is a limited future-policy
input, not admission of the fusion to VTIME.

The direct-child MAME ledger subset is green at
`build/validate-mame-2429c-native-child-timing-current-f369-v1.json` (124
observed MOVEM/Bcc/DBcc records), but leaves `$02360C/$023618/$023660/$025A0E`
unobserved. `tools/test_mame_2429c_native_child_timing.py` pins this as a
bounded oracle input. It does not admit the fusion or any root handoff to the
clock.

The widened exact-MAME power-on capture
`build/mame-2429c-irq-phase-current-f369-wide-v1/summary.json` spans ticks
14,720--14,860 and 141 `$02429C` entries. Its 4,371 matching child dynamic
records and observed root branches leave exactly the same four child and ten
root dynamic PCs unobserved. `tools/test_mame_2429c_wide_coverage.py` keeps
that negative result visible. Repetition of the current controller route is
therefore not coverage of the missing arms and cannot authorize the root's
timer/owner handoffs.

MAME alone was continued through ticks 14,861--15,000 after the current SNES
lineage has already diverged. The 56,179-event retained oracle trace adds 140
root visits and 4,340 exact child records but exercises the same subset and
leaves all four child and ten root gaps. This is useful negative MAME coverage
only; it must not be described as a native-off/native-on continuation,
Stage-3 completion, or a full playthrough.

The separate post-focused fresh-power-on root run
`build/fresh-campaign-current-5c7e-post-focused-to14841-v1` is intentionally
red at tick 14,841 after 2,757 green player comparisons and 12 matched deaths.
It makes no state load, ROM patch, or game-state write. Its atomic forensic
`states/failure.mss` (`85664aaa…`) records MAME action 0, 4 HP, `(52,112)`
against SNES action 9, 20 HP, `(68,96)`. This removes stale-save-state data as
an explanation; the exact three-way tick-14,746 task-frame regression remains
the hardware-boundary/virtual-IRQ root evidence.

The companion authenticated continuation
`build/reproduce-current-5c7e-14841-preinput-v2` arms only the tick-14,839
controller edge and reproduces the same red tick-14,841 response. It retains
`states/pre-failure-input.mss` (SHA-256 `1c4a5cec…`) before the neutral input
is applied, as well as the failure state. This is deterministic pre-failure
evidence from the current fresh lineage; it is not presented as a fresh-boot,
rate, or repair result.

The corrected organic-path continuation proceeds farther without concealing
that failure. `build/campaign-stage3-current-5c7e-continue15000-v2/summary.json`
authenticates the tick-14,743 fresh-lineage safe checkpoint and continues to
tick 15,000. Its exact prefix ends at the same retained tick-14,841 false
respawn; its later suffix has 15 player discrepancies (7 input-boundary and 8
response-boundary) but no halt, invalid task stack, or renderer failure. The
tick-15,000 save is an explicitly post-divergence organic-path checkpoint, not
fresh-boot, exact-state, boss, rate, Stage-3-completion, or full-playthrough
evidence. `tools/test_campaign_oracle_continuation.py` prevents the harness
from aborting such an explicitly requested suffix; its resume allowance admits
only the named predecessor harness hash, while every ROM, MAME, emulator,
bridge, symbol, checkpoint, and other runner-hash mismatch remains fatal.
The chained tick-15,001--15,250 continuation at
`build/campaign-stage3-current-5c7e-continue15250-v1/summary.json` adds 14
green player comparisons with no new discrepancy, halt, invalid stack, or
renderer failure. It is still post-divergence liveness coverage, not recovery
or a Stage-3/full-playthrough claim.

The current-source timing audits continue to block any partial VTIME promotion:
`build/audit-vtime-legacy-ac-writers-current-5c7e-v6.json` reports 11
unmigrated direct legacy-counter writers out of 26, and
`build/audit-vtime-accelerated-boundaries-b758-v3.json` reports 12 uncovered
boundaries plus 57 unadmitted live native labels. The rejected `$074C`
fallback is not part of current source. The shared,
path-sensitive MC68000 clock remains the priority-zero repair.

Exact-Nexen stop-by-stop attribution from that tick-14,743 safe state is at
`build/profile-stage3-tick-current-5c7e-safe14743-v1/profile.json`: one
update consumed 1,938,567 SA-1 cycles, 11 video frames, and 310 genuine
interpreter fetches. The `$02429C` native fusion and `$025110` native collision
guard fire in that trace. It is a perturbed checkpoint hotspot measurement,
not an uninterrupted fps or fresh-boot rate result, but it confirms the 358K
cycles/tick target is substantially missed.

The paired no-hook controller measurement independently keeps the rate blocker
open. `build/measure-stage3-current-5c7e-safe14743-nohooks-v2/summary.json`
loads the authenticated fresh-lineage tick-14,743 state in separate neutral
Nexen sessions and installs no execution hooks. Native-off needs 13,802,658
SA-1 cycles / 77 video frames for one tick; native-on needs 14,091,718 cycles
for five ticks, or 2,818,343.6 cycles/tick and 15.8 video frames/tick. That is
an approximately 4.90× bounded native speedup but still nearly eight times the
358K budget. Its green result means only no-halt/checkpoint-liveness; without
hooks it does not assert route coverage, and it is not fps, fresh-boot rate,
or same-tick gameplay proof.

One narrow `$027952→$02E524` native-edge candidate was rejected rather than
promoted. Candidate `8a4e8aed…` is semantically green in the focused 12-case
MAME/native-off/native-on differential at
`build/validate-stage3-27952-local-2e524-current-8a4e8ae-v1.jsonl`, including
CCR/X, stack, work RAM, AC, and its gate-off fallback. However, its private
bridge has zero observed entries in the current tick-14,743 state over frames
50,676–50,688 (`build/profile-stage3-27952-local-2e524-current-8a4e8ae-v2/results.json`).
It is not the live rate root and was removed; the active ROM
has been restored and hash-verified as `5c7e…`.

A distinct `$027952→$027AEA` bridge candidate is retained for further
integration testing, not promoted. The byte-minimal exact-accepted-ROM
artifact `build/interp-stage3-27952-direct-27aea-current-5c7e-v1.sfc`
(`23268b5d…`) changes only the verified three-byte JML address operand at `$94:B61A`
to the pre-existing guarded `$9F:C000` child. Its 12 retained parent fixtures
are green in exact MAME 0.287, native-off, and native-on at
`build/stage3-27952-direct-27aea-current-5c7e-isolated-v2.jsonl`: D/A,
CCR/X, real stack/return, mapped work RAM, upper backing, and AC agree. The
native-on isolated semantic run explicitly starts at the native parent; an
independent same-hash, exact-Nexen neutral-input route probe retains zero
child hits with gates off and 36 hits with gates on
(`build/stage3-27952-direct-27aea-current-5c7e-route-v2` and
`build/stage3-27952-direct-27aea-current-5c7e-route-on-v1`).
`tools/test_stage3_27952_child_bridge.py` pins both the generator rule and
the packed bytes. It does not cure the common-clock timing fault, establish a
rate, recover the tick-14,746 order, or
authorize replacing active `5c7e…`.
The candidate's later fresh-power-on native-on replay to MAME tick 3,000 at
`build/fresh-candidate-27952-direct-27aea-to3000-v1` has real title/credit/
start states, 168 green player comparisons, one matched death/respawn, no
oracle divergence, no halt, and a valid safe checkpoint. Its result remains
red solely for insufficient action-state coverage in that shortened segment;
it is not a Stage-3, rate, or promotion result.

The same bridge has now been rebuilt correctly from the active `a976…` ROM as
`build/interp-stage3-27952-direct-27aea-current-a976-v1.sfc`
(`43ee45ee…`). The new builder permits only the three destination bytes of
the `$94:B61A` JML and recalculates the four SNES header checksum bytes; the
authoritative `build/interp.sfc` remains `a976…`. Exact original MAME 0.287 /
native-off / native-on parent evidence is green 14/14 at
`build/validate-stage3-27952-direct-27aea-current-a976-isolated-v1.jsonl`
(12 D/A/CCR/X/stack/work-RAM semantic cases plus two dispatcher route probes).
It also passes a new fresh-power-on replay through tick 10,000 at
`build/fresh-candidate-27952-direct-27aea-current-a976-to10000-v1`: 2,062
green player comparisons, ten green death/respawn comparisons, all retained
action states, no divergence, no halt, and a safe checkpoint. This is fresh
title/credit/start/gameplay evidence for that *candidate*, not a promotion or
a Stage-3 completion claim. Its separate fresh one-credit HUD/art gate is also
green at `build/validate-fresh-one-credit-prompt-stage3-27952-current-a976-v1/summary.json`:
the artwork wedge, transparent CREDIT underlay, and lower-right status region
all pass from a cold boot.

Its current Stage-3 safe-state no-hook A/B at
`build/measure-stage3-27952-direct-27aea-current-a976-safe14743-v1/summary.json`
is liveness-green but still needs 2,375,601.72 native-on SA-1 cycles/tick,
6.64× the 358K budget. The command wall-time guard yielded different actual
video spans than the active-`a976…` counterpart (candidate first chunks
213/211 frames; active 190/189), so the small absolute cycle/tick difference
is not a cross-ROM speed claim. This does not repair the tick-14,746 timing
order, establish usable Stage-3 rate, or authorize promotion. The regression
guard is `tools/test_stage3_27952_current_a976_evidence.py`.

The next `$027B` investigation found a real active-ROM native/HLE coverage
gap rather than a renderer or stale-state explanation. In the retained MAME
Stage-3 instruction trace, `$027B44` and `$027B7C` each execute 60 times; in
the same authenticated SNES safe-checkpoint trace, active `a976…` enters their
native parent `$027952` 12 times but enters both wrappers zero times. The
bank-$02 sparse `$9D:DA00` dispatcher omitted those exact values and fell back
to interpretation. Candidate `387855da…`
(`build/interp-stage3-record-emitter-route-current-a976-v1.sfc`) combines the
already-proven guarded `$027AEA` parent edge with the two missing sparse cases,
leaving the accepted active ROM untouched. It is green for 12 complete
same-state original-MAME/native-off/native-on parent cases plus two production
route probes at
`build/validate-stage3-record-emitter-route-current-a976-isolated-v1.jsonl`;
its organic candidate trace reaches `$027AEA/$027B44/$027B7C` 12 times each.
The narrow candidate builder and joined failure/recovery evidence are guarded
by `tools/test_stage3_record_emitter_route_candidate.py` and
`tools/test_stage3_record_emitter_route_coverage.py`. The joined v4 report
also retains a newly exposed live `$02E524` sparse-route miss: MAME executes
it 60 times while both active and this candidate enter its wrapper zero times.
A fresh one-credit
candidate boot remains green for the artwork/HUD checks at
`build/validate-fresh-one-credit-prompt-stage3-record-emitter-route-current-a976-v1/summary.json`.
Its sustained checkpoint native-on cost is lower, 1,800,936.97 cycles/tick,
but still 5.03× the 358K budget
(`build/measure-stage3-record-emitter-route-current-a976-safe14743-v1/summary.json`).
It is rejected, not merely unpromoted: a separate fresh-power-on candidate
controller replay is red at the Button 1 response at MAME tick 2,958 after
the tick-2,956 input edge
(`build/fresh-campaign-stage3-record-emitter-route-current-a976-to14746-native-on-v1/summary.json`).
MAME enters action 1 while the candidate remains action 0 with the same health
and position. The source build's static guard explains the otherwise broad
harness timing label: `$9D:DA00` is shared by Stage 1, and the candidate's
canonical pointer/stack checks do not prove Stage-3 provenance. The unsafe
source cases were removed; the candidate builder reproduces the rejected ROM
only for forensics, and `tools/test_shared_dispatch_stage_provenance.py`
guards the conservative dispatcher. The deterministic pre-input state and
mismatch metadata are guarded by
`tools/test_rejected_shared_dispatch_fresh_failure.py`: its exact-entry
forensic state is `states/pre-failure-input.mss` (SHA-256 `80799f…`, SA-1
IRAM sidecar `ca40bb…`) under that replay artifact.
The shared-clock, hardware-boundary timing fault and full fresh Stage-3 replay
remain open.

A parent-local alternative repairs the route coverage without the shared
Stage-1 regression. Candidate `0453ef75…`
(`build/interp-stage3-parent-local-record-emitter-current-a976-v1.sfc`) changes
initially only the `$027AEA/$027B44/$027B7C` child-call destinations inside native
`$027952`; `$9D:DA00` remains conservative. It is exact 14/14 in the bounded
MAME/native-off/native-on parent matrix, fires all three children 12 times in
the authenticated Stage-3 checkpoint tick, and has zero oracle divergences in
a fresh controller replay through tick 3,000, including the formerly delayed
tick-2,958 Button 1 response. The red terminal is only incomplete action
coverage. This is retained at
`build/validate-stage3-parent-local-record-emitter-current-a976-v1.json` and
guarded by `tools/test_stage3_parent_local_record_emitter.py`.
The follow-on `$02E524` parent-local bridge (`91cf499f…`) also clears its
14/14 exact parent matrix, Stage-3 route tick (12 entries), and fresh tick-3,000
segment with zero oracle divergences; it lowers the local rate to
1,571,650.55 cycles/tick, still 4.39× the gate. Neither candidate can be
promoted, and neither has completed a fresh Stage-3 or full organic campaign;
`tools/test_stage3_parent_local_draw_evidence.py` guards its retained proof.
Its authenticated continuation from the fresh-lineage tick-10,000 checkpoint
reaches requested MAME tick 14,746 with zero oracle divergences, 2,744 green
player references, and six deaths at
`build/playback-watcher-20260808/parent-local-draw-91cf-resume10001-to14746-native-on-v3/watcher-report.json`.
It remains `partial-green` because boss-event coverage is zero and the segment
is resumed, not an uninterrupted full campaign.

A corrected no-hook exact-Nexen checkpoint comparison establishes a bounded
speedup only. With the same retained tick-14,743 state and neutral 90-frame
window, active `5c7e…` completes three ticks at 3,468,814 SA-1 cycles/tick
(`build/measure-stage3-current-5c7e-safe14743-onechunk-nohooks-v5/summary.json`),
while the three-byte operand candidate completes four at 2,669,361.75 cycles/tick
(`build/measure-stage3-27952-direct-27aea-current-5c7e-safe14743-onechunk-nohooks-v2/summary.json`).
The 23.0% native-on reduction is real but still 7.46× the 358K budget.
The repaired harness identifies the safe Nexen publish, state hashes, neutral
MCP input, and absence of hooks; it intentionally does not compare end RAM
across unequal tick counts. This remains checkpoint-only, not fps, fresh-boot,
virtual-IRQ recovery, or promotion evidence.

The focused non-pausing CE4 attribution at
`build/profile-stage3-ce4-current-5c7e-safe14743-v1.json` is green for its
checkpoint instrumentation contract. Across two spans it measures 16 CE4
calls and 66,386.5 CE4 cycles/update (27,060 from the twelve fast 2×2 calls)
versus a 3,303,291.5-cycle mean span. It is not rate evidence and crosses the
known timing-failure window, but CE4 is not large enough to be treated as the
sole usable-rate root; no renderer-only optimization should be claimed as a
timing repair.

The exact `$92:FB00-$92:FC9F` switch-in body is likewise not a dominant raw
cycle consumer in its narrow checkpoint profiler:
`build/profile-stage3-swin-span-current-5c7e-safe14743-v2/results.json` has
94 complete calls over eight updates, at 715.35 mean SA-1 cycles/call and
8,405.375 cycles/update. It excludes fast RTE, switch-out, and select work and
crosses the bad timing boundary, so it leaves scheduler semantics/rate open;
it only prevents attributing the full Stage-3 rate failure to this one body.

The larger `$99:85D3-$99:8621` `$02429C → $0242BE` bridge, including its
nested `$025110` collision call, averages 97,734.125 SA-1 cycles once per
checkpointed update in
`build/profile-stage3-2429c-pre25110-span-current-5c7e-safe14743-v1/results.json`.
It stops before continuation work and crosses the bad timing boundary. This is
hotspot attribution only, but it rules out treating that one bridge or
`$025110` alone as the entire usable-rate failure.

The current-ROM all-entry trace
`build/trace-stage3-active-native-current-5c7e-safe14743-v1.json/trace.json`
has 65 active entry-labelled native seams and 279 hits in one Stage-3
update—not merely `$025110` and the six player leaves. The hook set includes
callable entries and continuation/end seams; it includes CE4, `$02429C`, task
switch-in/out, object, and callback bridges. The focused audit
`build/audit-stage3-vtime-coverage-current-5c7e-v1.json` is green because it
correctly blocks promotion: the partial `$025110` ledger leaves the six player
paths, CE4, `$02429C`, and task switching uncharged. Its regression is
`tools/test_stage3_vtime_coverage.py`. Any timing patch that accounts for only
one of those groups remains out of scope for acceptance.

The wider source boundary gate,
`build/audit-vtime-accelerated-boundaries-current-5c7e-v3.json`, also keeps
the non-Stage-3 loop accelerators in scope: six collapse paths, four scheduler
shortcuts, `$0818` idle pacing, and CE4. It finds 12 uncovered boundaries;
the `$025110`, `$02429C`, and six player entries are only selected diagnostic
ledgers, not a shared clock. It also leaves 57 of the captured 65 entry labels
unadmitted pending an exact charge-route proof; continuation/end hooks are not
automatically called uncharged. The green audit and
`tools/test_vtime_accelerated_boundaries.py` mean this partial design is
blocked from promotion. They are static/source-and-trace boundary evidence,
not a rate measurement or an exhaustive generated-escape reachability proof.

The current opt-in `68c9…` VTIME player-ledger diagnostic also fails a fresh
native-off boot/credit probe before gameplay:
`build/validate-vtime-esc9-nativeoff-fresh3000-v1/summary.json` remains on
the SA-1 boot screen after the standard 5,248-frame wait and eight real coin
edges, with `$F01C62=0` but halt zero. This is VTIME
hardware-boundary/timing-or-boot-alignment evidence. It proves that its prior
short liveness result is not boot proof and blocks any diagnostic-clock
promotion independently of the incomplete native ledger.

The matching VTIME native-on fresh controller run is also red at
`build/validate-vtime-esc9-nativeon-fresh3000-v1/summary.json`: both SNES
configurations have zero credits after the standard 5,248-frame wait and
identical boot-screen pixels. A freshly launched exact MAME 0.287
boot-aware-one-credit control reaches gameplay at reported frame 1,952 and
retains `build/mame-vtime-boot-oracle-v1/states/superman/fresh-original-booted-before-vtime-comparison.sta`.
The VTIME paths do not reach a gameplay PC, so this is not a fake MAME/SNES
register differential.

The long fresh diagnostic probe proves the failure is not a stopped virtual
timer: `build/probe-vtime-esc9-boot-clock-v4/summary.json` retires 862,681
instructions and advances its fractional phase from 50 to 2,700 (53 observed
virtual deadlines) over 5,248 real frames, but remains in the `$003Fxx` boot
RAM-test path. Its paired native-off/on forensic state probes agree on
`$003FF6→$003FEE`, `$00AC=$7000`, `$00AA=1`, phase 2,700, no game tick, and no
active native ledger. The unimplemented common-clock route is therefore also
a hardware-rate boundary: the diagnostic runs roughly 99 real video frames
per observed virtual deadline. Do not repair it by changing only `$AC`, the
idle accelerator, or one native bank; that would retain a mixed clock and is
not a safe Stage-3 fix.

The two later post-boot `$0818` VTIME handoff images are rejected as well.
They route the diagnostic-only `$99:FBA1` release through `$F2:B400`, but
retain exact legacy bytes in `5c7e…` (guarded by
`tools/test_vtime_paced_release_pack.py`). The `$0734`-only variant
`9d3e7517…` activates before the task scheduler exists; the `$0734` plus task
mask variant `0de24905…` has not activated by frame 5,407 because its fallback
still pays per-fetch cross-bank prepare/consume traffic. Both fresh one-credit
controls are red, at
`build/validate-vtime-postboot-pacing-fresh-prompt-v1/summary.json` and
`build/validate-vtime-taskmask-pacing-fresh-prompt-v2/summary.json`.
They are diagnostic rejection evidence, not a source repair, title proof,
Stage-3 comparison, or rate result.

The third `$0818`-handoff diagnostic is also red. Its local-prearm pack
(`build/interp-vtime-local-prearm-experiment-v3.sfc`, `1ea6ff85…`) retains the
ordinary fetch JSR and waits for the existing `$072E` post-self-test gate before
crossing to `$F2`. Its real fresh one-credit result,
`build/validate-vtime-local-prearm-fresh-prompt-v3/summary.json`, still has
zero task mask and credits at frame 5,407 with no halt. The retained-state
readback (`build/probe-vtime-local-prearm-after5407-v3.json`) has zero
VTIME magic/valid, proving that the gate never opened: even the local
top-of-iloop JSR plus legacy branch slows self-test throughput too far. This
rejects the pack mechanics, not the production path; its exact seams and the
restored active bytes are guarded by `tools/test_vtime_local_prearm_pack.py`.

The fourth diagnostic uses the already-called bank-$00 fetch choke rather than
adding a top-of-iloop helper before `$072E`. Its v6 image
`build/interp-vtime-choke-gateway-experiment-v6.sfc` (`d4bc57e6…`) reaches a
fresh one-credit checkpoint but is red: the retained
`build/probe-vtime-choke-gateway-after5407-v6.json` has valid VTIME state and
`VT_DUE=1` at the `$0818` self-refetch wait, which bypasses choke before the
pending IRQ is delivered. The corrected v7 image
`build/interp-vtime-choke-gateway-experiment-v7.sfc` (`b28f72c7…`) sets the
existing one-countdown IRQ entrance on both native and `$0818` virtual due
events, so the retained IRQ reload consumes the signal and clears the virtual
due state. Its separate fresh one-credit title/HUD proof is green at
`build/validate-vtime-choke-gateway-fresh-prompt-v7/summary.json`; the
one-frame probe at `build/probe-vtime-choke-gateway-after5407-v7.json` has
live magic/valid, a changing virtual remainder, and `VT_DUE=0`.
`tools/test_vtime_choke_gateway_pack.py` and
`tools/test_vtime_due_bridge_pack.py` pin those byte-level paths. The synthetic
due-through-retained-reload regression is green at
`build/validate-vtime-choke-due-bridge-v7/summary.json`; it retains the forced
prestate and proves the one-countdown signal reaches `$F2:8500`, clears
`VT_DUE`, and returns to iloop. This removes one diagnostic boot/due-delivery
obstruction only. It does not prove MAME
cadence, a common clock, Stage-3 recovery, rate, gameplay, or acceptance.

The source-level promotion gate now identifies every direct legacy counter
writer: `build/audit-vtime-legacy-ac-writers-current-5c7e-v5.json` records 26
in the current diagnostic source, of which 11 are not routed through VTIME
(nine native-charge, the CE4 residue, and one `$0818` idle-scheduler write).
The two selected `$025110`, two selected player, and one diagnostic `$0818`
release seams do not constitute complete coverage; two new writes are only
virtual-due delivery bridges, three are countdown quarantines, and three are
disabled-mode compatibility. Its regression,
`tools/test_vtime_legacy_ac_writers.py`, must remain blocked until all active
writers are migrated and the resulting clock survives the exact Stage-3
three-way and fresh-boot tests.

The companion static audit at
`build/audit-stage3-native-charge-helpers-current-5c7e-v2.json` identifies a
second common-clock boundary: `$92` (100 entry-labelled seam hits), `$98`
(one), and `$99` (13) have no direct legacy per-block charge helper; `$94`,
`$97`, and `$9F` use different helper families.
`tools/test_native_charge_helpers.py`
guards that inventory. It does not pretend helper presence is per-entry reach
or cycle accuracy, but it rules out converting only the `$025110` helper.

The checkpoint trace now rejects a post-load native-gate change if the state
resumes inside an escape handler. The retained tick-14,743 state resumes at
`$92:DB8C`, the native game-tick handler, and the rejection record is
`build/trace-stage3-gameplay-native-off-current-5c7e-safe14743-v2-rejected/rejected-gate-mutation.json`.
Clearing `$071A/$073A` after loading it therefore cannot constitute a
native-off comparison. Configure native-off before checkpoint capture; this
does not invalidate the separately prepared native-off variants in the
existing IRQ and gameplay differentials.

The generic Stage-3 hot-handler route assertion was corrected: the six player
leaves are BSR-gateway entries, not ordinary `$00:D1B3` table targets. It now
rejects that invalid direct route. The current-ROM real-BSR differential is
green: `build/validate-stage3-13282-bsr-current-5c7e-v3.json` (six `$013282`
cases plus `$9F:E000` route),
`build/validate-stage3-13314-bsr-current-5c7e-v2.json` and
`build/validate-stage3-1337e-bsr-current-5c7e-v2.json` (one retained case
each plus `$9F:D800`/`$9F:BA00` routes), and
`build/validate-stage3-player-bsr-current-5c7e-v2.json` (18
`$0133EA`/`$013468`/`$013538` cases plus
`$9F:EC00`/`$9F:F100`/`$9F:F700` routes). All 26 MAME/native-off/native-on
semantic cases and six native-on route probes preserve registers, CCR/X,
stack, mapped work, upper backing, and AC. This removes a validation-harness
false alarm; it neither repairs nor reduces the shared virtual-IRQ/rate
blocker.

The `$02E42C` selector has its own route contract: the retained states split
between PC-relative JSR `$0278E2→$0278E6` and `$02F2DA→$02F2DE`, not a
generic OJMP target and not one interchangeable call site. The repaired real
call validator records the return-specific route and is green 6/6 plus the
`$9F:A140` natural-route probe at
`build/validate-stage3-2e42c-real-jsrpc-current-5c7e-v4.json`. It compares
original MAME 0.287, native-off, and native-on D/A, CCR/X, stack/return,
mapped work, upper backing, and AC. This fixes a validator classification
error only; it is not a timer repair, fresh Stage-3 replay, or rate result.

The reported title/HUD and bounded combat symptoms are no longer current
focused failures on `9dcc…`:

- a fresh cold boot with one real credit is green at
  `build/validate-fresh-one-credit-prompt-current-9dcc-nexen-v2/summary.json`;
  the right artwork gap, opaque CREDIT overlay, and lower-right status garbage
  are absent. The independent legacy-Mesen fresh run is also green at
  `build/validate-fresh-one-credit-prompt-current-9dcc-mesen211-v5/summary.json`
  (its native 256x224 capture geometry is recorded separately from Nexen's
  256x239 output);
- normal enemy attacks are green 4/4 at
  `build/validate-gameplay-damage-current-9dcc-v1` in MAME, native-off, and
  native-on; Button 1 is punch and Button 2 is kick;
- the ordinary-ROM boss matrix is green 118/118 at
  `build/validate-boss-health-current-9dcc-v3.json`, with arcade health/hit
  sequences 40/13, 40/37, and 20/6;
- carried and thrown crates are green in the ordinary organic branch, and the
  separate Up+Right flight-contact branch is green at
  `build/validate-organic-crate-flight-current-9dcc-v3/summary.json`.
  It has 17 original-code carried crate/enemy contact boundaries, followed by
  a 112-pixel ascent, with zero enemy-health writes in MAME, native-off, and
  native-on.

The `9dcc…` fresh campaign reaches tick 3,000 from power-on with no player
oracle mismatch or halt (`build/fresh-campaign-current-9dcc-safe3000-v1`), and
its authenticated continuation is green through tick 10,000
(`build/fresh-campaign-current-9dcc-coverfix-resume10000-v1`): 1,031 real
controller transitions, five matched deaths, walking, Button 1 punch/charge,
Button 2 kick, Up flight, crate pickup/carry/throw, and action states
0/1/2/3/4/5/7/8/9/10. This is still bounded coverage: it has no organic boss
fight or Stage-3 transition.

The same controller lineage fails deterministically at tick 14,841 in
`build/fresh-campaign-current-9dcc-coverfix-resume18000-v1`. Its retained
pre-input state is
`build/reproduce-fresh-14841-current-9dcc-v1/states/pre-failure-input.mss`
(SHA-256 `7c12101135dacd2bb0467a255f1717d2ada53cd60dd0034bf07b7e223ad63e77`).
The focused three-way gate
`build/validate-stage3-false-hit-chain-current-9dcc-v1.json` is intentionally
red: MAME has `$F03A02=$0000` and a live 4-health player at ticks 14,839–
14,840; both SNES gameplay-native-off and production-native-on write `$80F0`
then respawn (action 9, health 20). `$025110` interpreter fallback reproduces
the marker, so suppressing its collision output would only mask the fault. The
upstream authenticated task-15 IRQ-order failure at tick 14,746 remains the
root classification: hardware-boundary/virtual-IRQ timing affects both SNES
configurations before the later collision geometry reaches `$025110`.

The refreshed exact current-ROM gate,
`build/validate-stage3-irq-order-current-9dcc-v2.json`, is green at ticks
14,744--14,745 and intentionally red from tick 14,746. It compares exact
original-code MAME captures with the same authenticated SNES checkpoint in
gameplay-native-off and production-native-on modes. At the failing boundary
MAME has task 15 at `$0259B0`/`$0242BE`, SR `$2400`; both SNES modes have the
same `$02429C`/`$00044E`, SR `$2404`. The next checked boundary has the expected
collision-table/RNG divergence. This confirms the root is shared virtual-IRQ
delivery timing, not a remaining gameplay-native escape.

The current active blockers are therefore the virtual-IRQ/timing root and
usable-rate proof, organic boss/transition coverage, renderer conservation
through a fresh Stage-3 entry, and a real complete playthrough. The supplied
Stage-3 blue-strip state remains stale-save-state diagnosis only; its final-hash
Mesen after-input recovery is green at
`build/validate-stage3-scroll-input-current-9dcc-v1/summary.json`, but it
advances only 2 native-off or 11 native-on game ticks across 120 video frames.
An isolated unpromoted source candidate (`3b7000…`) instead clears all 51
columns after one neutral vblank with no game-tick advance in both legacy-Mesen
native modes (`build/validate-stage3-scroll-nmi-cache-reapply-candidate-3b7000-v2/summary.json`),
and passes a separate cold-boot one-credit HUD check. The active ROM remains
`5c7e…`; Nexen cannot restore the legacy-Mesen checkpoint as Stage 3 and MAME
has no equivalent serialized SNES PPU state, so this candidate is not a
three-way, fresh-entry, renderer-conservation, or rate closure.
The final-hash short exact-Mesen rate probe is also red at 2,322,889.5
SA-1 cycles/native-on tick, with no native-off tick completed in its bounded
window (`build/measure-stage3-current-9dcc-v1/summary.json`). Neither is
fresh-entry or fps evidence, but both leave the usable-rate blocker open.

The unaccepted `VTIME=1` diagnostic image is
`build/interp-vtime-native-ledger-diagnostic-v2.sfc` (`590f1dfb…`), not this
candidate. Its fresh 12-frame liveness probe is green at
`build/validate-vtime-native-ledger-liveness-v2/summary.json`. The diagnostic
now has an opt-in `$025110` native ledger: its 226 blocks are static/dynamic
MAME-checked, the forced-deadline unwind is green, and a synthetic no-deadline
MAME/native-off/native-on local fixture is green 2/2. None proves a hardware
phase, native/HLE common clock, Stage 3 three-way recovery, rate, or gameplay.
The normal pack now byte-asserts the legacy per-fetch counter and debug path
when `VTIME` is off, and keeps all three collision seams legacy. This corrected
a `cd4a6a93…` packing regression in which a disabled helper still imposed a
JSL/RTL on every interpreted instruction; its frame-5,407 prompt check is
retained red. The repaired ordinary dirty image (`8b9adc92…`) passes a new
fresh one-credit title/HUD check at
`build/validate-fresh-one-credit-prompt-vtime-default-8b9a-v1/summary.json`.
Neither dirty image is the `f369…` candidate or VTIME acceptance evidence. The
prior `adac11f4…` rebuild and v4 fetch-gateway runs are historical evidence only.

The current-source `VTIME=1` experiment is explicitly rejected. Its v1
checkpoint result is not evidence against the partial `$025110` ledger because
65816-long-state writes had silently aliased SA-1 IRAM. The repaired v2 image
passes the strengthened 24-frame liveness/reload check
(`build/validate-vtime-stage3-9dcc-experiment-liveness-v3/summary.json`) and
the all-native-off forensic probe records its high countdown decrement and
phase reload (`build/probe-vtime-stage3-9dcc-all-off-long-store-v4`). Both are
diagnostic-only: the ROM-mismatched checkpoint and missing charges for the
other native/HLE spans mean this cannot become a timer fix before every active
span uses the same virtual clock. The ordinary active image is `5c7e…` with
VTIME disabled.

The later explicit interpreter-only VTIME flag image
`build/interp-vtime-interpreter-only-escapes-off-diagnostic-v1.sfc`
(`0ee4e331…`) is rejected before its proposed gate switch can be observed.
The fresh neutral framewise probe at
`build/validate-vtime-interpreter-only-liveness-5500-framewise-v3/summary.json`
stops **inconclusively** at its declared 180-second host budget after frames
137→3,173 and interpreter step 785,106: it has no halt but stays at boot PC
`$003FFA`, tick zero, and VTIME magic/valid zero. Because `$071A/$073A` power
up clear, their clear samples are not evidence that the deferred
interpreter-only switch ran. The retained state/screenshot show only
``ARCADE BOOT IN PROGRESS``; they are not a title, credit, gameplay, MAME
differential, rate, or Stage-3 proof. The framewise tool records an atomic
host-side completed-request boundary so this negative result cannot be
relabelled as an MCP timeout. It reinforces the cold-boot hardware-rate/common
clock blocker and does not alter active `5c7e…`.

A newer explicit `VTIME=1 VTIME_INTERPRETER_ONLY=1` helper variant is likewise
rejected, rather than treated as a renderer regression in the active ROM.
`build/interp-vtime-interpreter-only-native-handoff-v1.sfc` (`598f0acc…`)
performs a fresh power-on and one real Select edge with no state load or
runtime game-memory write. At frame 5,407 it has task mask 3 and no halt, but
still has zero credits; the one-credit prompt's right-wedge, CREDIT-underlay,
and lower-right pixel predicates fail (775, 0, and 156 respectively) in
`build/validate-vtime-interpreter-only-native-handoff-fresh-prompt-v1/summary.json`.
The saved state is explicitly nonresumable forensic evidence. Its expected-red
artifact guard is `tools/test_vtime_interpreter_only_native_handoff_prompt.py`.
The candidate does not reach a MAME-comparable gameplay state, so it neither
supplies a three-way gameplay differential nor changes the priority-zero
hardware-rate/common-clock blocker or current `5c7e…` fresh HUD result.

The live `$02429C` root has a source-authenticated CPU-000 block inventory
at `build/audit-stage3-2429c-charge-blocks-current-5c7e-v4.json`: 78
instructions, 35 blocks, 520 static two-cycle units, and 14 terminal Bcc/DBcc
outcomes. `tools/test_stage3_2429c_charge_blocks.py` guards that prerequisite.
The VTIME-only bank-$F3 copy now routes its eleven child JSR/BSR/indirect
handoffs through an exact parent flush and common interpreter child clock,
reducing the uncovered boundary count to 12. This locally authorizes only that
diagnostic seam; it does not authorize promotion, a rate claim, or IRQ-order
repair.

The exact current-hash `$02429C` MAME/native-off/native-on function
differential is green 9/9 at
`build/validate-2429c-current-5c7e-live-v1.jsonl`. Its three organic entries
come from the fresh-lineage tick-14,743 checkpoint; each preserves D/A,
CCR/mask, mapped work RAM, and the audited stack/return mappings through the
handler terminal. It intentionally masks IRQ6 and forces a no-deadline
counter, so it proves no live hardware-phase ordering, Stage-3 recovery,
fresh-boot behavior, or rate. The root remains unadmitted until its child
owner/return and timing-adjustment work is complete.

The controlled distinct-arm audit found and repaired a separate native/HLE
semantic defect in the unaccepted `b758…` candidate: the byte-reader branch
at `$02429C` and the four-record `$0259CA` scan preserved control flow but
lost the architectural `TST.B` NZVC result before a final `DBRA`. Original
MAME 0.287, native-off, and native-on now agree 9/9 at
`build/validate-2429c-distinct-arm-candidate-b758-pinned-v2.jsonl`, including
all D/A registers, CCR/X, mask, mapped work RAM, and exact private returns;
the three retained organic entries are green 9/9 at
`build/validate-2429c-organic3-candidate-b758-pinned-v1.jsonl`. The candidate
also passes a new power-on/one-credit HUD-artwork check at
`build/validate-fresh-one-credit-prompt-candidate-b758-v1/summary.json`.
The prior scan-arm stack bytes are now recognized as the exact private
`$0259FC → $99:97FD` continuation, not a hidden write. This is a bounded
candidate semantic repair, not production promotion, IRQ-order recovery,
Stage-3 rate proof, or a continuous gameplay result. Its focused regression
is `tools/test_2429c_tstb_ccr_regression.py`.

The VTIME build entrypoint now has a mode-specific regression guard:
`tools/test_vtime_build_mode_guard.py` requires diagnostic builds to skip only
the ordinary disabled-pack assertion and keeps that assertion mandatory for
`VTIME=0`. The latest unaccepted diagnostic image is
`build/interp-vtime-current-5c7e-diagnostic-v3.sfc` (`b55274a8…`); the normal
rebuild immediately afterward was historically byte-identical to the preserved
`5c7e…` ordinary image. The later dirty player-ledger source instead produces
the unaccepted `18bbee7f…` ordinary output described above. Production save
states cannot be migrated to validate either diagnostic ROM.

The six active Stage-3 player-native handlers have now been source/assembly
audited at `build/audit-stage3-player-charge-blocks-current-5c7e-v1.json`:
83 generated charge sites map to 83 decoded blocks (238 original
instructions). Four immediate shifts can be precomputed; terminal Bcc/DBcc
still need deferred post-block charging. This narrows the common-clock work;
it is not a VTIME repair or rate result.

The subsequent `VTIME=1` player-ledger diagnostic (`68c9bccc…`) routes those
83 blocks and 15 audited player call/return handoffs through an owner-tagged
ledger. Its fresh liveness, first-block forced-deadline, and shared exit-gateway
forced-deadline checks are green at
`build/validate-vtime-esc9-ledger-liveness-v2/summary.json`,
`build/validate-vtime-esc9-ledger-due-v5/summary.json`, and
`build/validate-vtime-esc9-finish-gateway-v1/summary.json`. The bounded actual
`$013282` handoff probe did not reach OJMP in any of six retained route cases.
This preserves a route-coverage gap and keeps the extension diagnostic-only:
CE4, `$02429C`, task-switch, and other active native/HLE paths are still not a
common virtual clock. The profile audit
`build/audit-stage3-vtime-coverage-player-ledger-current-5c7e-v1.json` is
green only because it blocks promotion: its required uncovered set is
`$02429C`, CE4, task switch-in, and task switch-out. It is not a tick-14,746,
usable-rate, gameplay, or fresh Stage-3 repair.

The later ordinary `8b9adc92…` fresh controller replay is red at MAME tick
2,958: 108 updates took 532,224,800 SA-1 cycles and delayed the Button 1
punch response. Root cause is a native/HLE routing error in the shared
`$9D:DA00` sparse dispatcher, which entered Stage-3 direct handlers during
Stage 1 without a stage-provenance guard. Normal build `3d0cc84d…` removes
those routes and restores the local legacy IRQ reload. Its fresh power-on
native-on replay through tick 3,000 has 168 green player comparisons and zero
oracle mismatches, including the repaired tick-2,958 Button 1 response. This
same build also passes a fresh power-on, one-credit HUD/art check at
`build/validate-fresh-one-credit-prompt-current-3d0c-v1/summary.json`, with
the right artwork wedge and credit-text underlay intact. This is bounded
evidence only; native-off fresh replay currently exhausts its
2,456-frame exact-entry watchdog before its first interpreter-only update, so
the required native-off semantic comparison remains open.

The current ordinary-ROM boss matrix is now independently green at
`build/validate-boss-health-current-3d0c-v3`: 118 MAME/native-off/native-on
bounded cases use a reversible terminal trap (not the old PC-ring diagnostic
ROM), with Stage 1 health/hits 40/13, Stage 2 40/37, and Stage 3 20/6. This
removes the reported one-hit boss initialization from the current focused
failure set, but does not replace an organic boss battle or transition test.

Current crate-chain roots are green but bounded: the emitter is 4/4 at
`build/validate-25110-current-3d0c-held-thrown-v1` and the corrected consumer
is 6/6 at `build/validate-1e7c0-current-3d0c-held-thrown-v2`. The consumer's
all-gates-off configuration now starts from `inext`, and every configuration
retains its pre-execution state. MAME's canonical carried `$2000` fixture has
no health write; thrown `$2001` has exactly one, and both SNES configurations
match the full post-state. An organic carry/flight/throw replay is still
required.

The supplied Stage-3 state continues to display its 51-column blue bar at
initial stale hscroll 288, then clears after input in both native modes
(`build/validate-stage3-scroll-current-3d0c-v1/summary.json`). It is a
checkpoint renderer/publication diagnosis, not fresh-ROM transition evidence.
The newer NMI cache-reapply candidate supplies a one-vblank renderer-specific
recovery regression but remains unpromoted; retain the active-state symptom
and the missing Nexen/MAME-equivalent proof as blockers.
The current short checkpoint performance probe is red at 2,299,747 SA-1
cycles/tick across two native-on ticks
(`build/measure-stage3-current-3d0c-v1/summary.json`); its short span is not a
steady-state rate claim, but the Stage-3 performance gate remains unmet.

## Priority 0 — correctness and stability

1. **Fresh organic campaign coverage and stability.** The post-fix current-hash
   replay `build/fresh-campaign-current-f369-to10158-v2/summary.json` starts from
   power-on with `TESTFLAG=0`, reaches MAME tick 10,158 with 1,068 transitions,
   five deaths, zero oracle divergences, and zero SA-1 halts. It has no boss or
   Stage 3 transition. The completed 1,031-transition replay
   `build/fresh-campaign-current-4359-to10000-exact-v1/summary.json` is predecessor
   hash evidence: it covers walking, punch/charge, kick, flight, Down, crate
   pickup/carry/throw, hurt, death/respawn, and action states 0/1/2/3/4/5/7/8/9/10
   without a halt or MAME/native-on divergence, but reaches no boss or Stage 3.
   A full-length current-hash replay remains required before calling the ROM
   playable. The retained `94158832…` run still documents the historical
   `$001000B0/$F800` interpreter halt.
   The pre-fix red regression `build/validation-13be-sentinel-route-current-v1.json`
   narrowed one native `$13BE` table-route failure to the CE58→D18A return-frame
   convention. The landed CE58-specific no-push body entry is covered by the green
   `build/validation-13be-sentinel-route-current-v4.json` (44/44 entries preserve
   task-5 context). The separate fresh-route `$001000B0/$F800` interpreter halt
   remains open.
2. **Fresh organic Stage 1–3 retest.** Exercise bosses, stage transitions, and the
   post-boss vertical sections on exact hash `f369…`. Punch, kick, flight, charged
   release, crate pickup/throw, ordinary enemies, and deaths have bounded coverage;
   current-hash focused enemy/boss/Stage 3 handler reruns are green, but organic
   boss fights, stage transitions, and post-boss vertical sections remain open.
   A fresh-lineage continuation now reaches Stage 3 and deterministically diverges
   at MAME tick 14,746: MAME saves task 15 at `$0259B0`/`$0242BE`, while SNES
   completes its batch to `$0818` before virtual IRQ delivery and retains
   `$02429C`/`$00044E`. The exact MAME/full-all-escape-off/native-on gate is red
   there after matching through ticks 14,744–14,745; the defined native-off
   control agrees. The retained pre-failure recovery state is
   `build/forensic-fresh-stage3-rng-safe14743-v1/states/safe-checkpoint-14743.mss`.
   The cycle-stamped original-code MAME regression
   `build/validation-mame-25110-irq-phase-current-f369-v5.json` is green and
   proves the IRQ's path-dependent MC68000-cycle boundary (`$000818`, `$0259B0`,
   `$02582E`, `$000810`), not a fixed instruction count. The paired trace
   reducer records variable costs for the same branch/DBRA PCs, and the exact
   MAME static-table audit `build/audit-m68k-cycle-model-current-f369-v6.json`
   finds 7,986/46,874 comparable instruction pairs that disagree with its
   development-only static table, concentrated at branch, loop, shift, MOVEM,
   and arithmetic sites. Do not replace `$7000`
   with another global literal: the rejected `$2328`, `$2354`, and all-off
   `$2D82` probes show a constant can move one seam while corrupting a later
   SR/register frame. A scheduler-safe dynamic cycle-accounting repair,
   three-way differential, and fresh-boot replay through and beyond this point
   are required.
   The green register-qualified branch proof
   `build/validation-mame-25110-branch-timing-current-f369-v2.json` provides
   exact CPU-000 rules for every retained Bcc/DBcc record; use it as a focused
   regression when implementing branch and loop charges, while preserving the
   broader timing/three-way gates.
   The paired variable-cost regression
   `build/validation-mame-25110-variable-timing-current-f369-v2.json` is green
   for all 830 retained MOVEMs and 452 data-register shifts/rotates. The
   exception/arithmetic sentinel
   `build/validation-mame-25110-exception-arithmetic-timing-current-f369-v1.json`
   is green for all 44 retained `TRAP #n` rows and six observed multiply/divide
   operand rows. These close those trace samples but do not yet provide a
   general multiply/divide formula; preserve that explicit coverage gap in any
   timer implementation and acceptance report.
   The green MAME driver clock reduction
   `build/validation-mame-superman-vblank-clock-current-f369-v1.json` fixes
   the nominal deadline at `139300 + 100/5743` CPU cycles. The timer design
   must retain that fractional phase and deliver the held IRQ only at a valid
   emulated-instruction boundary. The full unimplemented contract is in
   [VIRTUAL_IRQ_TIMING.md](VIRTUAL_IRQ_TIMING.md).
   The staged VTIME diagnostic has a green fresh liveness probe and an opt-in
   `$025110` ledger, but remains diagnostic until all native/HLE charges,
   general arithmetic timing, the exact tick-14,746 three-way gate, and a
   fresh replay are green. The first always-active native gateway is retained
   red rather than promoted: the unaccepted current-source build did not reach
   its prompt by video frame 5,407; normal packing now byte-asserts legacy
   collision seams.
   The `$025110` charge inventory establishes that its 226 legacy charge
   calls represent 545 original instructions but 3,064 static two-cycle units,
   179 with dynamic branch/loop outcomes
   (`build/audit-native-charge-blocks-25110-current-v3.json`). The active
   diagnostic charges a completed block only after its terminal control flow;
   the exact-MAME post-state regression is green across 4,320 complete blocks
   (`build/validation-mame-25110-deferred-charge-current-v2.json`). A
   return-residue key defect was caught by a retained forced-prestate test and
   is green after correction at
   `build/validate-vtime-25110-due-path-v7/summary.json`. These narrowly prove
   this escape's diagnostic boundary mechanics, not the production clock.
3. **Complete at least one full playthrough.** Every stage, boss, continue, game-over,
   and ending path remains outside the current stability claim.
4. **Resolve wrong player-animation tiles.** Superman has displayed unrelated tiles
   during punch/attack animation. The displayed-slot quarantine fixed one cache hazard,
   but no current human result closes the symptom.
5. **Close renderer conservation and Stage 3 rate.** The retained 1,200-frame burst test completed only
   568 true renders for 600 ticks/requests/ACKs and recorded 31 new coalesces. The
   current-hash checkpoint regression clears the reported blue strip after input in
   both native configurations, but this is stale-save-state recovery, not current
   fresh organic Stage 3 acceptance. The `3b7000…` NMI cache-reapply candidate
   clears the same strip after one neutral vblank without a game tick, but is
   retained only as a legacy-Mesen candidate. A future candidate must preserve scheduler ordering
   without silently dropping complete images. Do not promote the `$2328` timing
   probe as a fix: its literal checkpoint result repaired the first task-15
   seam, but the production-gated dynamic version deadlocked at the next
   coroutine boundary and the one-shot and packed-memory versions changed the
   MAME state. All were rejected and are forensic evidence only.
   The read-only delivery capture
   `build/capture-stage3-irq-delivery-current-f369-v3/summary.json` further
   shows native-on reaching `$00:B404` with task 15 still at `$02429C` and
   logical PC `$0818`; it corroborates the three-way failure but does not
   replace its fresh-lineage/native-off comparisons.
   The retained original-MAME cycle oracle now rules out scalar calibration:
   its 139.3K-cycle IRQ services land at different instruction boundaries and
   the same branch/DBRA PCs have path-dependent costs. Any accepted repair must
   account for interpreted instructions and native/HLE spans in common units;
   it must not be another reload-literal or wall-clock pacing shortcut.
6. **Complete the `$0026FA` dynamic regression.** The source guard is green and the
   root writeback fix is built, but a current-ROM paired MAME/native-off/native-on
   capture has not yet reached the retained screen-shake window.
7. **Do not revive the rejected pool-scanner shortcut.** The table/rts clones for
   `$02498C` and `$0249C2` failed exact MAME/native-off/native-on entry fixtures:
   native-off was green, native-on corrupted registers and mapped work RAM in both
   cases. The clones and sparse route have been removed from the diagnostic source;
   a future optimization needs a new root-cause differential and must not reuse this
   return-frame design.

## Priority 1 — fidelity

1. **Stage 2/3 camera fidelity and rate.** Current-hash Stage 3 route/handler
   fixtures are green (9/9 scroll, 32/32 hot handlers), but the current five-chunk
   checkpointed production measurement is 690,322 SA-1 cycles/tick and 3.84375
   video frames/tick. In the exact checkpoint probe, native-off advanced
   2 game ticks and native-on 32 over the same 120 video frames, confirming a
   timing/rate gap even though both recovered the artwork. The arcade scene uses
   several simultaneous X1-001 column offsets; test the approximation organically
   and profile the remaining renderer/dispatcher cost before accepting a usable
   rate.
2. **Aligned MAME pixel comparison.** Recognizable output and isolated palette/tile
   oracles are not an exact same-state frame verdict. Capture aligned arcade and SNES
   states and quantify pixels, viewport, sprites, palette, and scroll.
3. **Music transcription and timbre.** Keep VGM as the source oracle, but compare all
   21 tracks by ear. Preserve pitch bends, LFO, portamento, dynamics, sample tails, and
   octave/timbre choices instead of accepting byte transport as musical proof. Fresh
   profiling confirms zero SSG writes in all 21 VGMs, so the reviewed one-voice SPC700
   software PSG is not a music solution; see
   [the evaluation](../toolchain/SOUND_SPC_PSG_EVALUATION.md).
4. **Real sound effects.** Enemy IDs remain ignored and most effects are placeholders.
   Validate priority and interaction with music, not only isolated playback. Retain a
   time-stamped YM2610 `$00-$0D` SSG census during the next MAME SFX sweep before deciding
   whether a real-time PSG is justified.
5. **Boot latency and presentation.** The Mode 7 zoom/heartbeat makes the long original
   initialization visible, but startup remains long and the indicator is liveness rather
   than progress.

## Priority 2 — release evidence

1. **Formal performance on the final candidate.** Start from power-on with
   `TESTFLAG=0`, arm organically, use real input, include pacing/rendering/audio, cross
   the ordering event, and retain the raw log. The current formal reference is v124 at
   29.700167 game-fps and 360,990.164 cycles/tick, which fails both gates.
2. **Fresh full interpreter/layout gates after risky changes.** Run semantic
   differentials, bank/seam assertions, cold boot, focused lockstep, and the relevant
   renderer/sound checks.
3. **Real-hardware scope.** Decide whether emulator-only is an acceptable release
   target. No FXPak/real SA-1 result is recorded.
4. **Build reproducibility.** Parameterize hardcoded host paths and make the selected
   VGM/ymfm FM-authoring workflow reproducible enough for a fresh legal-input checkout.
5. **Rights review.** ROM-derived data stays private. Public distribution also needs a
   decision about music rights, including the John Williams-derived cues.

Resolved on this host: `bash tools/stage_mame_0287.sh` now provisions snap revision
4339 under the gitignored durable build tree without replacing the installed snap.
Both launchers discover it and still enforce MAME 0.287 plus SHA-256
`297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f`.

## Decisions Chad still owns

- Whether the Stage 2 center-column approximation is acceptable or exact per-column
  rendering is required.
- Whether to keep the boot-time `Tad_LoadSong(1)` convenience or match the arcade's
  delayed organic attract command.
- Whether real-hardware validation is mandatory for the first release.

The repository's performance contract is currently 30 game ticks/s on a 60 Hz SNES
display with a 358,000-SA-1-cycle representative-tick budget. Older 60 Hz/150K/178K
campaign targets are historical, not an unresolved status conflict.
