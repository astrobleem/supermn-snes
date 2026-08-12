# Authoritative Superman project status

Last evidence review: August 12, 2026.

This is the only authoritative project-status summary. Dated reports under
`docs/history/` retain the evidence and failed experiments behind it, but their
“current,” “playable,” and “next” labels are historical.

## Verdict

The port is an **interactive technical-demo response candidate**. It is **not
playable, release-ready, or shippable**.

The current ordinary `build/interp.sfc`, SHA-256
`5f5dc9d79e04fe9b0e9c3a59eed55437974b30ad3803502383c692a7fd4e0cd5`, is an
unpromoted **focused renderer repair candidate**. Its preserved parent
`11aefd2cfdc6a0c28ad6a69e607d4e5c7f1884db6757b8f385f675d51f965f90` is
explicitly **red for live Mesen gameplay presentation**. Chad's August 12
playtest found a repeated/corrupt playfield immediately after coin/start and
background flashing while scrolling; the supplied window capture is retained at
`docs/assets/evidence/current-11ae-user-mesen-background-red-20260812.png`
(SHA-256 `1ee9cdbb5e3564ca0d6fbce979f98362d0ead49610d6de1a57d7656c8c514eda`).
This invalidates the recommendation to run that ordinary artifact and supersedes
the earlier still-montage review as a statement about current behavior. Exact
Mesen reproduction and consecutive-frame comparison are now red: lossless real-
controller capture finds corruption at extracted frames 165–174 and 225–232.
The first bad frame changes 50,653/51,200 playfield pixels (98.93%); the second
changes 30,896/51,200 (60.34%). Focused 5A22 tracing ties them to tilemap uploads
at emulator frames 6,915 and 6,988. Those maps contain 1,984/2,048 and
1,938/2,048 zero words, versus 524 and 517 in the immediately recovering maps.
Because the BG cache allocates real artwork to physical tile slot zero, those
near-empty maps render as repeated live art rather than transparent cells. The
slow heavy-render/queue path leaves each obsolete map visible until the fuller
map arrives; foreground and HUD remain intact. This is confirmed parent-hash
renderer negative evidence, not a MAME-aligned comparison. The preserved reports
are under `build/playback-watcher-20260812/current-11ae-mesen211-right-lossless-from6719-v1`
and `build/playback-watcher-20260812/current-11ae-mesen211-right-bg-map-values-from6891-v5`.
The repair counts staged nonzero map words only when a complete successor is
queued. It retains the displayed map below 256 nonzero words, reapplies live
scroll, and preserves X/Y; queue-free and fuller maps retain the original path.
The final `5f5d…` checkpoint migration from exact state `02ba3ab7…` advances
Mesen frames 6,891→7,168 and game ticks 881→1,020 with halt zero. The sparse
35-cell attempt is suppressed; its fuller successor (1,524 nonzero / 524 zero
words) commits. Analysis of all 231 lossless framebuffers finds no first
divergence or mismatch ranges; maximum dominant-tile ratio is 0.11125. Candidate frame 34
matches the preserved clean-parent background exactly outside local box
`[127,16,177,98]`; it differs from the corrupt parent frame across the full
display. Evidence is under
`build/playback-watcher-20260812/renderer-sparse-conservation-5f5dc9d7-migrated6891-v1`.
This is migrated-checkpoint evidence only, not fresh boot, MAME-aligned pixels,
performance, broad renderer conservation, or human acceptance. The first
queue-wide guard `10dc1a0b…` remained visually red and is rejected; checkpoint-
green `9ab9a1db…` was superseded before acceptance because its scan did not
preserve the original X/Y register contract.

The best evidence-backed ordinary line is the following narrow repair candidate.
It remains unaccepted for release because the Stage-3 timing and rate blockers
remain open:

- production ROM size: 4,194,304 bytes;
- SHA-256:
  `a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60`;
- preserved image:
  `build/interp-2429c-tstb-ccr-isolated-current-5c7e.sfc`.
- It is a 66-byte, hash-guarded patch of preserved predecessor `5c7e…`; the untouched
  predecessor remains at `build/interp-current-5c7e-before-vtime-esc9.sfc`.
  The patch repairs two terminal native `TST.B` paths at `$02429C` and
  `$0259CA` by publishing MC68000 NZVC before their following `DBRA`, while
  preserving X. The direct exact-MAME/native-off/native-on differential is
  green 9/9 at
  `build/validate-2429c-distinct-arm-isolated-a976-pinned-v1.jsonl`.
- A fresh power-on MAME-controller replay of this exact hash is green through
  tick 10,000 at
  `build/fresh-candidate-2429c-tstb-ccr-isolated-a976-to10000-v1`: 2,062
  green player comparisons, five matched deaths, and action states
  0/1/2/3/4/5/7/8/9/10, including Button 1 punch/charge, Button 2 kick, Up
  flight, and crate pickup/carry/throw. It has no save-state load, ROM patch,
  game-state write, halt, or oracle divergence. The independently cold-booted
  one-credit HUD/art check is also green at
  `build/validate-fresh-one-credit-prompt-isolated-a976-v1/summary.json`:
  transparent CREDIT underlay, intact right artwork, no lower-right garbage,
  one credit, nonzero task mask, and no halt. These are bounded Stage-1/2 and
  renderer/HUD proofs—not boss-continuity, Stage-3 transition/timing/rate, or
  full-playthrough proof. The same active hash independently passes the legacy
  Mesen fresh cold-boot prompt gate at
  `build/validate-fresh-one-credit-prompt-isolated-a976-mesen211-v1/summary.json`.

## August 11–12 engineering checkpoint

Three ROM identities must not be conflated:

- `a9765fbf…` is the preserved ordinary candidate with the strongest accepted
  ordinary evidence: fresh controller coverage through tick 10,000 plus its
  focused semantic, combat, crate, HUD, and Stage-3 blocker results.
- The current source ordinary build is renderer candidate `5f5dc9d7…`, based on
  red step-cap parent `11aefd2c…`. Neither inherits preserved predecessor
  `4eb9a408…` evidence. Exact-v7 successor `162b757c…` is a separate unpromoted
  diagnostic lineage.
- The latest focused VTIME diagnostic is v7 SHA-256
  `45c9096dfda3d4203878c18954725ff4814f23f4e28a1e623f3cf07b647e6c72`.
  A ROM-only migration from the authenticated v4 tick-14,745 checkpoint is
  green through tick 14,750 after repairing the one-game-tick input-publication
  order. Exact-v7 suffixes keep every player/input/death row green through
  tick 16,000, and a corrected checkpoint replay makes the first two boss rows
  green at 15,908/15,990. The formerly red 15,906/15,988 rows sampled before
  the write-containing update because of a harness observation-boundary error,
  not a ROM scheduler defect. This is bounded checkpoint evidence, not
  fresh-boot or production acceptance.

The checkpointed `14e920eb…` interpreter-only VTIME lineage is oracle-green
through tick 14,000 and has safe post-divergence coverage through tick 20,000.
Its retained first mismatch at 14,748 led to the input-publication diagnosis;
v7 corrects that input seam. The later apparent one-update boss split was an
invalid frame-to-tick fixture comparison and is not ROM evidence.
Save-state reuse, cross-ROM
diagnostic migration, NMI/DMA/renderer liveness repairs, common-clock coverage,
rejected experiments, exact hashes, and the next decisions are summarized in
[ENGINEERING_CHECKPOINT_20260811.md](ENGINEERING_CHECKPOINT_20260811.md).

Exact-v7 evidence is green with no oracle divergence through completed tick
21,200, then intentionally exhausts the global interpreter lifetime guard at
terminal tick 21,203. Safe state is `6c3eaab1…` (IRAM `0d4f91e8…`), with
pre-counter `$07FEF8A5`; terminal counter `$08000000`, halt `$CAFE`, SA-1
`$00D15A`, virtual PC `$000D42`. `$0D40` is valid `MOVE.W (A1)+,D4` and
`$0D42` is `BEQ`, confirming a cap stop rather than corruption or an unsupported
opcode. No exact MAME tick-21,203 state was needed for this arithmetic. ROM-only
v8 migration crossed the old cap and reached counter `$0809A799` at tick 21,300.
The subsequent same-ROM continuation remains divergence-free through MAME tick 31,000
(SNES tick 30,994): first divergence NONE and no mismatch ranges; halt 0. Minimum
stack and renderer drops were not sampled at this intentional stop.
Reports are
`build/playback-watcher-20260812/v8-stepcap-migrated21200-to21300-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume21301-to21500-v1/watcher-report.json`
and
`build/playback-watcher-20260812/v8-stepcap-resume21501-to22000-v1/watcher-report.json`.
The later segments are
`build/playback-watcher-20260812/v8-stepcap-resume22001-to22500-v1/watcher-report.json`
and
`build/playback-watcher-20260812/v8-stepcap-resume22501-to23000-v1/watcher-report.json`,
followed by
`build/playback-watcher-20260812/v8-stepcap-resume23001-to25000-v1/watcher-report.json`
and
`build/playback-watcher-20260812/v8-stepcap-resume25001-to27000-v1/watcher-report.json`
and
`build/playback-watcher-20260812/v8-stepcap-resume27001-to30000-v1/watcher-report.json`
and
`build/playback-watcher-20260812/v8-stepcap-resume30001-to33000-v1/watcher-report.json`.
The endpoint safe state is
`613c6566788e4b81408b87efbd278d35fa9f75c6ca762eb14a17b65f1ff4f32c`, IRAM
`7ab15b2dad152aa2d3b37401c6534e0ae4c4a42dc3a44beef6c21c5c9988ef4c`, resume
31,001. The retained movie ends at game tick 139,925 / frame 140,000, leaving
108,925 game ticks (22.15% covered); the campaign is intentionally paused for
human screenshot review. The README and committed
`docs/assets/readme/showcase-20260812.png` replace the stale montage with four
fresh-`4eb…` visual panes and two clearly labeled v7 checkpoint panes. The README
describes the project as an interactive technical preview, not a playable demo.
Chad's August 12 review found no visible defect in the corrected six-pane montage;
that is still-image review only. This remains checkpoint evidence: no fresh boot,
full playthrough, live combat/audio playtest, or production acceptance for v8.

Superseded candidate `2f590fb1…` has an authorized fresh-power-on Luna campaign
through tick 3,300 with 118 controller transitions, no gameplay-oracle
divergence, and no liveness failure. Its retained boot samples show a clean
black SA-1 logo with no orange/lower-half corruption, its P2 HUD is fully visible
and centered, and its tick-3,214 crate capture has no bogus left-edge tile chunk.
Combat remains red: the tick-1,278 foreground is present over the wrong red-brick
field instead of the known-good storefront. The compact report and images are at
`build/playback-watcher-20260811/visual-fivefix-2f5-fresh-to3300-v1/watcher-report.json`.

Read-only inspection proved the tick-1,278 column classifier exact (kind `$003F`,
map `00..0D,00,00`) and found that C0BC gameplay initialization was not the
renderer's first image: title had already established the baseline. C0BC
published the right token, but the expected 784-byte title-to-gameplay delta was
then misclassified as a post-publication mutation and cleared `$41:014A/$015A`
before prepared-map selection. Superseded candidate `6f7b1084…` snapshots the exact
2 KiB C0BC code/color planes at token publication. A later nonzero manifest
retains C0BC only while the live planes still equal that snapshot; a genuine
later writer clears both tokens. The exact transition gate is green for retained
publication and forced post-publication mutation at
`build/playback-watcher-20260811/visual-sixfix-6f7-bg-producer-transition-v2/watcher-report.json`.
The separate PC-ring whole-function MAME/Nexen differential is green 6/6 with
zero work/video mismatch at
`build/playback-watcher-20260811/visual-sixfix-pcring-cc9-c0bc-v1/watcher-report.json`.
Its authorized fresh campaign safely checkpointed at tick 1,280 and resumed the
same lineage through tick 3,300 without replaying the prefix. Gameplay/liveness,
centered P2 HUD, and crate remain green, but combat was still red brick; early
boot was not sampled. The compact report is
`build/playback-watcher-20260811/visual-sixfix-6f7-fresh-to3300-v1/watcher-report.json`.

Fresh-state forensics found a second consumer defect: by tick 1,000 all direct
and queued C0BC tokens were accepted, but unchanged physical geometry let
`bg_column_map_update` return without applying the token-only provenance change.
Rejected intermediate `32decddf…` cached the token and remapped WRAM, but did not
publish a prepared dirty event or restore the 90-byte code list and 32-byte
palette map, so PPU VRAM remained red brick. Current `4eb9a408…` reloads the
complete immutable C0BC prepared payload, records the applied token, and routes
the same foreground dispatch through the established prepared upload. Its
three-case real-5A22 synthetic fixture is green for exact cache/map reload,
`005A`/`FFFE` publication, idempotence, and non-C0BC control at
`build/playback-watcher-20260811/visual-eightfix-4eb-token-transition-v2/watcher-report.json`.
A ROM-migrated continuation from the authenticated `6f7…` tick-1,280 checkpoint
is oracle/liveness green through 1,300; resume-origin correctly retains the old
serialized PPU image, while the post-render capture restores the known-good
storefront geometry at
`build/playback-watcher-20260811/visual-eightfix-4eb-migrated1280-to1300-v1/watcher-report.json`.
That focused result is now backed by an authorized exact-hash fresh campaign at
`build/playback-watcher-20260811/visual-eightfix-4eb-fresh-to3300-v1/watcher-report.json`.
Its successful fresh prefix repeat-hashed a safe tick-1,280 checkpoint, and its
same-lineage suffix resumed at 1,281 and completed tick 3,300 without replaying
the prefix. There is no observed oracle/liveness divergence across 118 input
transitions and one death. Retained frames show a clean black SA-1 boot, the
known-good storefront at Button-1 tick 1,278 instead of red brick, no bogus
crate-area tile chunk at carry tick 3,214, and a fully visible centered P2 HUD.
This is partial-green bounded visual/gameplay evidence, not aligned-pixel,
performance, full-playthrough, production, or release acceptance.

## Detailed evidence

- The active ordinary-enemy matrix is green 4/4 at
  `build/validate-gameplay-damage-current-a976-v1`: Button 1 punch does 1,
  Button 2 kick does 2, body contact does 4, and a charged projectile does 4,
  with exact original MAME/native-off/native-on register, CCR/X, stack,
  mapped-RAM, and health-write comparisons. The active boss matrix is green
  118/118 at `build/validate-boss-health-current-a976-v1.json`: Stage 1
  initializes at 40 HP and takes 13 retained hits, Stage 2 40/37, Stage 3
  20/6. Both are IRQ-masked bounded handler tests, not continuous organic boss
  encounters or campaign-completion proof.
- The active organic crate differential is green at
  `build/validate-organic-crate-current-a976-v1/summary.json`. It continues a
  same-hash fresh-boot tick-3,000 checkpoint with no ROM migration and compares
  all 87 exact controller entries in original MAME, native-off, and native-on.
  The 17 carried crate/enemy contacts at ticks 3,253--3,269 cause zero enemy
  health transitions; only a legitimate Button 1 throw causes the two matching
  one-point transitions at ticks 3,274 and 3,283. The separate flight control
  at `build/validate-organic-crate-flight-current-a976-v1/summary.json` starts
  the same carry route and switches to Up+Right at tick 3,253. It confirms
  material ascent and the same 17 carried crate/enemy contacts with zero enemy
  health transitions in all three configurations. These are organic
  checkpoint branches, not a full campaign or FPS claim.
- The same fresh native-on root reaches tick 14,746 with no player-state
  mismatch at `build/fresh-campaign-current-a976-to14746-native-on-v1`, and
  retains a resumable tick-14,743 safe checkpoint plus a tick-14,745 boundary
  state. That endpoint is not an IRQ-frame pass. Exact pinned-MAME 0.287,
  native-off, and native-on snapshots from that same authenticated safe state
  are intentionally red at tick 14,746 in
  `build/validate-stage3-irq-order-current-a976-v1.json`: MAME task 15 is
  `$0259B0/$0242BE`, SR `$2400`, while both SNES modes are
  `$02429C/$00044E`, SR `$2404`. They match each other, so the classification
  remains hardware-boundary/virtual-IRQ timing, not a native-only or stale
  save-state cause. The current hash's checkpoint-local neutral rate is also
  red: native-on is 2,471,287.70 SA-1 cycles/tick and all-native-off is
  11,320,496.0, against the 358,000 budget
  (`build/measure-stage3-current-a976-safe14743-v1/summary.json`). This is
  not a fresh-ROM FPS result. `tools/test_stage3_irq_order_current_a976_evidence.py`
  guards both retained failures.
  The two earlier fresh gameplay-root-off attempts
  (`build/fresh-campaign-current-a976-to14746-native-off-v1` and `-v2`) are
  now classified as harness failures, not game stalls: after clearing
  `$071A/$073A`, their runner still waited for the intentionally unreachable
  native `$92:DB82` entry. The corrected fresh power-on prefix at
  `build/fresh-campaign-current-a976-native-off-first-entry-v6` uses Nexen's
  counted rising virtual-PC `$003A92` edge at IRAM `$0040` instead. It is
  `partial-green`: original MAME 0.287 and SNES agree at the tick-221 spawn
  origin and tick-222 player state; the disabled gates are zero, the one edge
  reply is fully checked, and halt remains zero. Its fresh companion
  `build/fresh-campaign-current-a976-native-off-first-movement-v1` extends to
  tick 1,060, applies the real Left input at tick 1,054, and matches MAME's
  tick-1,056 response (X 64 to 61); the separately fresh native-on campaign
  records that same MAME/native-off/native-on response. The root-off prefix
  has two green player comparisons, no halt, and no invalid task stack.
  Neither run covers attacks, bosses, deaths,
  Stage 3, rate, or all escapes disabled. The exact Stage-3
  native-off/native-on/MAME checkpoint matrix above remains the authority for
  the observed tick-14,746 timing failure.
- An authenticated native-on continuation from that exact fresh-lineage safe
  tick-14,743 state reaches tick 15,050 at
  `build/continue-stage3-current-a976-safe14743-native-on-v1`. It records 15
  downstream player discrepancies after the already-proven IRQ-order split,
  but no halt, invalid task stack, or renderer stall; its final task-stack
  margin is 138. That is post-divergence organic-path liveness evidence, not
  recovery, fresh-boot exact-state proof, a Stage-3 completion, or a rate
  result. The focused deterministic rerun at
  `build/continue-stage3-current-a976-safe14743-native-on-prefailure-v2`
  stays exact through the tick-14,839 input boundary and first turns red at
  tick 14,841: MAME is idle/4 HP at `(52,112)`, while SNES is state 9/20 HP at
  `(68,96)`. It immediately preserves the hash-matched pre-input state and
  SA-1 IRAM sidecar at
  `states/pre-failure-input_response_compare-tick-14841.mss`; its source is a
  nonresumable exact-entry forensic state, so it is deterministic reproduction
  evidence rather than a checkpoint-resume claim. This visible result is
  downstream of the existing current MAME/native-off/native-on tick-14,746
  task-frame divergence, not a newly classified combat, renderer, or
  native-only root. `tools/test_stage3_post_irq_continuation_a976_evidence.py`
  guards both retained artifacts.
- The bounded `$02429C` semantic/cycle ledger is now broader, but remains a
  fixture-local prerequisite rather than a timing repair. Four explicit
  distinct-arm fixtures from one authenticated pre-entry image pass 12/12
  exact MAME/native-off/native-on comparisons on active `a976…` at
  `build/validate-2429c-distinct-arm-isolated-a976-pinned-v2.jsonl`. They
  compare D/A registers, CCR/X/mask, mapped work RAM, and audited return/stack
  residue with IRQs masked only inside the function span. Matching original
  MAME 0.287 debugger traces at
  `build/mame-2429c-fixture-cycles-original-v2` have zero prediction failures
  and collectively observe all 14 `$02429C` dynamic branch/DBcc PCs plus all
  19 dynamic PCs in its direct native children; the joined guard is
  `build/validate-mame-2429c-fixture-cycle-coverage-a976-v1.json` and
  `tools/test_mame_2429c_fixture_cycle_coverage.py`. This supplies bounded
  path-cost inputs only. It does not prove parent/child ownership handoff,
  interpreter-child timing, global common-clock migration, unmasked IRQ
  cadence, organic Stage-3 completion, rate, or a playthrough.
- The opt-in VTIME diagnostic now has a locally closed `$02429C` root seam,
  without changing the preserved ordinary `a976…` ROM. The historical
  `b758…` artifact remains negative evidence; current source instead builds
  unpromoted ordinary `2dadd…`, including supervisor changes whose fresh
  ordinary-ROM acceptance remains open. The separate
  VTIME image is `build/interp-vtime-2429c-root-b758-v3.sfc`, SHA-256
  `3dc42f139e17747441ec4b576ee1e1b362c98da3f22014038b668b9c6e7845aa`.
  Its bank-$F3 copy owns all 35 original root blocks, flushes before all 11
  genuine-return child transfers, deliberately interprets each child, and
  restores the matching F3 continuation. The production bank-$99 root and
  ordinary `op_rts_sentinel` bytes remain unchanged when `VTIME=0`.
  Exact original-MAME-0.287 comparison is green 8/8 across four distinct-arm
  fixtures and two valid xlat/choke variants at
  `build/validate-vtime-2429c-root-b758-v3.jsonl`. The exact Nexen handoff
  guard is green at `build/validate-vtime-esc5-root-handoff-b758-v3.json`, and
  the synthetic first-block deadline unwind is green at
  `build/validate-vtime-esc5-root-due-b758-v3.json`. These prove bounded local
  semantics, parent/child stack/return ownership, and deadline unwind only.
  Promotion remains blocked: current audits retain 11 of 26 unmigrated direct
  legacy countdown writers and 12 other uncovered accelerated boundaries at
  `build/audit-vtime-legacy-ac-writers-b758-v3.json` and
  `build/audit-vtime-accelerated-boundaries-b758-v3.json`. Follow-on diagnostic
  `build/interp-vtime-2429c-root-schedfallback-b758-v4.sfc`, SHA-256
  `efeb08e841a39c775e0ee8a338cdb867e0134cb207729b02ef38f5b14df605c0`,
  additionally routes the collapsed `$074C` scheduler scan back through exact
  interpreter decoding only while VTIME is valid. Its active and invalid-clock
  branches are green in exact Nexen at
  `build/validate-vtime-scheduler-scan-fallback-b758-v4.json`, but fresh controller
  acceptance is red before gameplay for both diagnostic images. Base v3 stops
  at the credit gate with 7 credits instead of 8; v4 stops there with 5 instead
  of 8. Both process zero gameplay transitions and record no oracle divergence:
  `build/playback-watcher-20260808/vtime-2429c-root-3dc-fresh-to3000-native-on-v1/watcher-report.json`
  and
  `build/playback-watcher-20260808/vtime-2429c-root-schedfallback-efeb-fresh-to3000-native-on-v1/watcher-report.json`.
  The matching v4 gameplay-native-off control is identically red at 5/8
  credits with zero gameplay transitions at
  `build/playback-watcher-20260808/vtime-2429c-root-schedfallback-efeb-fresh-to3000-native-off-v1/watcher-report.json`.
  The credit-gate failure is therefore shared VTIME/scheduler timing, not a
  gameplay-native dispatch defect.
  Focused no-write pulse probes reproduce the exact final counts and explain
  them as throughput/input-sampling failures: over the fixed 215-frame credit
  window v3 advances 69 game ticks and reaches 7 credits, while v4 advances
  only 44 and reaches 5 (`build/probe-vtime-credit-pulses-3dc-v3/summary.json`
  and `build/probe-vtime-credit-pulses-efeb-v4/summary.json`). The exact
  interpreter fallback is therefore a locally proven but campaign-rejected
  slowdown. It has been removed from current source; v4 and its evidence are
  retained as a negative experiment. Two narrower throughput experiments are
  also rejected and reverted. `9aa32c55…` removes repeated checked long-call
  gateways but advances only 71 ticks and still reaches 7/8 credits; its exact
  MAME root differential remains green 8/8, with green handoff/deadline checks.
  `9ae08316…` additionally prefilters opcode classes with no dynamic cycle
  correction, advances 72 ticks, and still reaches the identical 7/8 sequence
  (`build/probe-vtime-credit-pulses-9aa-v5/summary.json` and
  `build/probe-vtime-credit-pulses-9ae-v6/summary.json`). A one-word Select
  latch (`2567dd89…`) is rejected at 6/8 because it delays neutral releases and
  collapses later coin edges; that source was reverted too. The concrete lost
  input is pulse 2, whose frame-5256--5260 hold lies wholly inside VTIME game
  tick 82. Leaving the ROM unchanged and lengthening only the pre-game
  bootstrap to eight-frame Select/eight-frame neutral intervals is green 8/8
  at `build/probe-vtime-credit-pulses-3dc-v3-long8-v1/summary.json`, but fresh
  Luna controls show that this is only bootstrap calibration. The default
  155-frame settle reaches origin RNG `$571A` (22,330), one Lehmer step before
  the expected 200; a 95-frame settle reaches `$700E` (28,686), 20 steps
  before it. A 158-frame settle passes the origin-RNG gate, then the first
  gameplay exact-entry synchronization requests 29 `$92:DB82` occurrences
  and observes only 6 over frames 5,650--8,106, with no gameplay input
  transitions or oracle divergence reached. The original compact reports are
  `build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-fresh-to3000-native-on-v1/watcher-report.json`,
  `build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-wait95-fresh-to3000-native-on-v1/watcher-report.json`,
  and
  `build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-wait158-fresh-to3000-native-on-v1/watcher-report.json`.
  That apparent throughput/exact-entry blocker has since been superseded by a
  terminal-capture diagnosis. The 5A22 could return into WRAM/data after
  repeated interrupt nesting: the NMI handler was modifying a saved status
  byte instead of preserving the interrupted mask state, and
  `service_pending_dma0` cleared `$1F11` only after `MDMAEN`, allowing an NMI
  arriving at long-DMA completion to replay the same descriptor recursively.
  Preserving both saved status bytes and clearing `$1F11` before `MDMAEN`
  removes the stack-corruption signature. A separate asynchronous failure then
  showed `nmi_video_keepalive` clobbering renderer direct-page scratch `$D0`;
  preserving `$D0` around `bg_scroll` restores continued render completion.
  The resulting opt-in image is
  `build/interp-vtime-2429c-root-b758-nmi-dma-d0-v1.sfc`, SHA-256
  `e00fb0cbba42bb5bb92808f70f3a42f1c0080c30aa0170ab01718cadefc07051`.
  Fresh native-on and matching diagnostic-tool native-off controls are bounded
  partial-green through tick 250 with no oracle divergence, both CPUs running,
  clean stacks, and advancing renderer state at
  `build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-long8-wait158-to250-native-on-v1/watcher-report.json`
  and
  `build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-long8-wait158-to250-native-off-mcpdiag-v1/watcher-report.json`.
  The native-off run uses a diagnostic Nexen managed publish to expose the
  exact IRAM-edge tool; its embedded emulator core matches the accepted
  publish, so this is tool-proven native-off behavior rather than a production
  emulator promotion. Fresh native-on then reaches tick 1,100 with exit zero,
  98/98 retained exact-entry spans, six green input transitions, 12 green
  player references, valid task-stack floors, continued renderer progress,
  and no divergence at
  `build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-long8-wait158-to1100-native-on-v1/watcher-report.json`.
  An authenticated continuation from the post-tick-1,097 safe boundary
  (`resume_mame_tick` 1,098) then reaches tick 3,000 with no divergence or
  mismatch range at
  `build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume1098-to3000-native-on-v2/watcher-report.json`.
  The cumulative lineage has 84 processed input transitions, 168/168 green
  player references, one organic death at tick 2,461, two green death/respawn
  references through tick 2,471, and observed actions 0, 1, 2, 8, and 9.
  Terminal render state remains live (`complete=2983`, `request=3040`,
  `ack=3039`, 14 queue drops), every initialized task floor is valid with
  minimum margin 138, and halt remains zero. The safe checkpoint created after
  tick 2,997 authenticates `resume_mame_tick` 2,998 and SHA-256
  `35bcb9843aee0163fdddf5c36eb874ea4b0081bec346133ec94f13ae0f059f4f`.
  A second authenticated continuation from `resume_mame_tick` 2,998 reaches
  tick 6,000 with no divergence or mismatch range at
  `build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume2998-to6000-native-on-v1/watcher-report.json`.
  The cumulative lineage now has 567 processed input transitions, 1,134/1,134
  green player references, two organic deaths at ticks 2,461 and 4,348, and
  4/4 green death/respawn references. Every listed action and button coverage
  gap is closed: actions 0, 1, 2, 3, 4, 5, 7, 8, 9, and 10 are observed.
  Terminal render state remains live (`complete=5981`, `request=6040`,
  `ack=6039`, 16 queue drops), task-floor minimum margin is 138, and halt is
  zero. The safe checkpoint created after tick 5,997 authenticates
  `resume_mame_tick` 5,998 and SHA-256
  `1b48921fac89f4e57f6c8f6c786dcb6950af5f27289a8a1c2ad41fc98d65d73d`.
  A third authenticated continuation from `resume_mame_tick` 5,998 reaches
  tick 10,000 with no divergence or mismatch range at
  `build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume5998-to10000-native-on-v1/watcher-report.json`.
  The cumulative lineage now has 1,031 processed input transitions,
  2,062/2,062 green player references, five organic deaths at ticks 2,461,
  4,348, 7,361, 8,132, and 9,672, and 10/10 green death/respawn references.
  Terminal render state remains live (`complete=9946`, `request=10040`,
  `ack=10039`, 51 queue drops), task-floor minimum margin is 136, and halt is
  zero. The safe checkpoint created after tick 9,997 authenticates
  `resume_mame_tick` 9,998 and SHA-256
  `fe8e364f20b9b0e415a0c86ed7e399e8bb43bbaca8d5458496840e03df074a7c`.
  The first attempt to continue from it was tool-red before comparison because
  tick 9,998 is itself a controller edge (`130 -> 128`). The harness now
  restores the pre-edge input, reaches the resumed exact entry, and schedules
  that edge once at the resumed tick. The focused regression
  `tools/test_campaign_resume_input_edge.py` is green, and the exact 12-tick
  proof is partial-green through tick 10,010 at
  `build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume9998-to10010-input-edge-v1/watcher-report.json`:
  one tick-9,998 compare, one `130 -> 128` apply, and one green tick-10,000
  response. Its safe checkpoint created after tick 10,007 authenticates
  `resume_mame_tick` 10,008 and SHA-256
  `f0ff546bdf69e9180612a312b0567a9978574fe48dbf0dc8d81aea4dfbe6e86d`.
  The authenticated continuation from that state reaches tick 14,750 with no
  *sampled player-oracle* divergence or mismatch range at
  `build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume10008-to14750-native-on-v2/watcher-report.json`.
  It retains and crosses every requested tick-14,743--14,747 exact boundary,
  including the tick-14,746 input apply and the tick-14,747/14,748 response
  comparisons. The cumulative lineage is 2,745/2,745 green player references
  and 12/12 green death/respawn references. At tick 14,750 both CPUs remain
  running, halt is zero, minimum task-stack margin is 138, and renderer state
  is `complete=14668`, `request=14790`, `ack=14789` with 79 queue drops. The
  safe checkpoint created after tick 14,747 authenticates `resume_mame_tick`
  14,748 and SHA-256
  `1b1eec1f30e8ce27c71359d34b13864cff31b41db1fc006508ba601ffdfd4b61`.
  It does **not** supersede the tick-14,746 ordering failure. Exact work-RAM
  attribution from those retained states now proves the opt-in `e00f…` lineage
  first differs at tick 14,746 as well: MAME task 15 is
  `$0259B0/$0242BE`, SR `$2400`, while `e00f…` still has
  `$02429C/$00044E`, SR `$2404`; RNG and collision state split in the same
  tick. The false-hit marker differs at tick 14,839, exact player state first
  differs at 14,840, and the sampled continuation stops at its first response
  mismatch at 14,841. The compact attribution is
  `build/playback-watcher-20260809/vtime-2429c-root-b758-nmi-dma-d0-native-on-attribution-v1/watcher-report.json`.
  This is sampled/transition liveness plus exact bounded attribution, not a
  production input or clock repair, a Stage-3 rate claim, or a playthrough.
  Boss coverage remains absent.
  The current audit again leaves the scheduler scan among 12 uncovered
  boundaries. The local closure
  records are `build/audit-stage3-2429c-handoff-protocol-b758-v3.json` and
  `build/audit-stage3-2429c-common-clock-closure-b758-v3.json`. Those local
  closure records alone do not repair fresh boot, Stage-3 rate, or the global
  common clock. The exact phase reduction
  `build/validate-vtime-stage3-phase-e00f-v3.json` is green for the retained
  negative diagnosis: from MAME tick 14,745's game boundary to task-15
  `$02429C`, original MAME consumes 131,286 cycles while VTIME charges only
  16,308, a 114,978-cycle pre-root undercharge. The candidate reaches
  `$02429C` with 61,448 two-cycle units remaining although MAME takes the IRQ
  only 7,692 cycles later inside `$025110`. Exact route hooks record zero
  `$97:8000` or ESC3-ledger hits, proving that child really is interpreted.
  Among the retained active-entry inventory hooks, 185 of 192 pre-root hits
  belong to 52 unadmitted entry labels; only seven hits belong to selected
  ledgers. The complete phase split is control/scheduler 16+0,
  scroll/player prepass 35+2, player/renderer fanout 48+4,
  selector/resume tail 8+0, and task-15 pre-root 78+1, where each pair is
  unadmitted+selected hits. The remaining defect is therefore broad
  upstream/global clock coverage; the validator explicitly records
  `safe_narrow_fix_available=false`, so no narrow `$02429C` flush or hidden-
  child-dispatch fix is established.
  A one-byte opt-in fallback now tests that diagnosis by clearing the gameplay
  root translation gate in the ROM rather than by debugger mutation:
  `build/interp-vtime-interpreter-only-e00f-v1.sfc`, SHA-256
  `0bfae7d05a152441f9df4d028677641420a6053ce4148711668a1c5c6b48456f`.
  Its manifest records only file offset `$328000`, `$01->$03`. The combined
  diagnostic Nexen publish used for this path has executable SHA-256
  `17d243c404b8ef32bbb1754a5b026584f2ae24cb047f54b9f250a6f4b721650a`,
  managed-assembly SHA-256
  `b6649c705e22b02a103710f0594c5abf99a805f94c7fdc8c55ca81a4dc918e9e`,
  the accepted embedded-core hash `42765c30…`, and exposes the exact IRAM edge,
  next-S-CPU-boundary, and call-stack tools. After exact fresh-bootstrap
  calibration, the retained v6 run reaches the MAME tick-221 origin with RNG
  200 and stays partial-green through tick 250 over 29/29 interpreted
  `$003A92` entries with no mismatch range. Its post-tick-250 checkpoint is
  resumable and non-nested: the exact-stop SA-1 PC advances `$008F56->$008F58`,
  no second IRAM `$0040` low-byte `$92` write occurs, and all three saves share
  SHA-256
  `f49d99bf5082efb6a40cdb42f1256338c5dbf26e0c245a924a244a71142e524a`.
  The compact report is
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-fresh-to250-v6/watcher-report.json`.
  The first longer retained-state investigation appeared to lose the sixth
  interpreted `$003A92` boundary after MAME tick 795. That was not a stopped
  game tick: 26 virtual IRQs and work-tick progress continued through logical
  tick 819. The VTIME-only bank-$F3 `$02429C` child-return dispatcher had
  unconditionally written `$071A=1`, leaking the global native gate back on in
  the explicit interpreter-only mode and making later roots invisible to the
  interpreted-edge counter. The generated dispatcher now restores the gate
  according to the ROM mode byte: ordinary VTIME returns to `$071A=1`, while
  `VTIME_INTERPRETER_ONLY=1` leaves it zero on all eleven child-return arms.

  The repaired interpreter-only image is
  `build/interp-vtime-interpreter-only-e00f-gate-restore-v1.sfc`, SHA-256
  `96d1b1935b3913400776e18c02c13591551d5e3cae98d714de80e76d118e1a99`.
  From the retained tick-790 state, exact roots 6--16 now compare green against
  MAME ticks 796--806: scheduler mask/current task/RNG, every initialized saved
  task frame, and the requested player fields are exact in all 11 pairs. The
  raw 22--32-byte ranges remain recorded; they consist of the accepted
  pre-opcode carry-forward cells, the SNES-only VTIME area, and four stable
  unclassified residue bytes, with no authoritative divergence. The compact
  reports are
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-capture6-8-v1/main-review.json`
  and
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-roots9-16-v1/watcher-report.json`.
  The ordinary-mode control
  `build/interp-vtime-e00f-mode-aware-normal-control-v1.sfc` (`5502cd72…`)
  independently restores `$071A=1`, keeps `$073A=0`, and remains live through
  tick 819, so the repair does not silently force ordinary VTIME native-off.

  A true power-on replay of the repaired hash is partial-green through MAME
  tick 806 at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-fresh-to806-v1/watcher-report.json`:
  origin tick 221/RNG 200, 585/585 exact interpreted entries, gates zero, halt
  zero, render request/ack 846/845, and 12 valid task stacks with 138-byte
  minimum margin. Its three post-entry-safe tick-806 saves are byte-identical
  at SHA-256 `4107fc4b…`. An authenticated same-ROM continuation then reaches
  tick 1,100 at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume807-to1100-v1/watcher-report.json`:
  293/293 segment and 878/878 cumulative exact entries, six gameplay input
  transitions, 12/12 green player references, no divergence, gates zero, halt
  zero, renderer request/ack 1140/1139 with zero queue drops, and the same
  138-byte minimum task-stack margin. Its three safe tick-1,100 saves share
  SHA-256 `adf24d89…`. A second authenticated continuation reaches MAME tick
  3,000 at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume1101-to3000-v1/watcher-report.json`.
  It adds 78/78 accepted input-transition/response pairs for 84 cumulative
  transitions and 168/168 green player references. The organic death at tick
  2,461 and respawn at tick 2,471 are green, with actions 0/1/2/8/9 observed.
  At the endpoint `$071A/$073A` remain zero, halt is zero, render
  request/ack is 3040/3039 with `complete=2997`, generation 6000, and zero
  queue drops; all 13 initialized task stacks are valid with minimum margin
  138. The three resumable tick-3,000 saves are byte-identical at SHA-256
  `3df18b31…` and authenticate `resume_mame_tick` 3,001. These are bounded
  interpreter-only fallback and checkpoint-control results, not ordinary-ROM
  recovery, Stage-3 rate, boss, or playthrough acceptance.

  The first attempt to extend that lineage from tick 3,001 requested tick
  6,000 and completed 1,964/1,964 segment exact entries through tick 4,965,
  with no oracle divergence or mismatch range. Its cumulative prefix has 454
  input transitions, 906/906 green player references, actions
  0/1/2/3/4/5/7/8/9/10, and 4/4 green death/respawn references, including the
  second organic death at tick 4,348. Nexen then closed its MCP connection
  during capture (`OSError(9)`), so the run is harness-red and has no terminal
  CPU/renderer snapshot or tick-6,000 checkpoint; it is not a successful
  6,000-tick campaign. The compact report is
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume3001-to6000-v1/watcher-report.json`.
  Instead of replaying the accepted prefix, the retained exact tick-4,000
  checkpoint was atomically reloaded, matched against its full public-machine
  and SA-1-IRAM bundle, rendezvoused off the nested interpreted entry with zero
  additional game-update entries, and saved three times byte-identically at
  SHA-256 `786f2f72…`. The recovery is green and authenticates resume tick 4,001
  at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-recover4000-v3/summary.json`.
  `docs/current/CAMPAIGN_EVIDENCE_LEDGER.json`, guarded by
  `tools/validate_campaign_evidence_ledger.py`, now selects that checkpoint
  automatically for the same ROM/oracle/emulator identity. Luna-owned
  authenticated continuations have since advanced that recovered lineage
  through MAME tick 14,000. The five 2,000-tick requested segments beginning
  at ticks 4,001 through 12,001 complete 9,995/9,995 exact entries with no
  first divergence or mismatch range; cumulative coverage is 13,771/13,771
  exact entries, 1,325 input transitions, 2,650/2,650 green player references,
  every action state in the controller timeline, six organic deaths, and
  12/12 green death/respawn references. At tick 14,000 both gates and halt
  remain zero; renderer request/ack is 14040/14039 with `complete=13997`,
  generation 28004, and zero queue drops. All 15 initialized task stacks are
  valid with minimum margin 138; the prior 92-byte tick-12,000 floor was
  transient, not progressive exhaustion. The three safe tick-14,000 states
  are byte-identical at SHA-256 `9a7173a1…` and authenticate resume tick 14,001.
  The compact reports are
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume{4001-to6000-v1,6001-to8000-v1,8001-to10000-v1,10001-to12000-v1,12001-to14000-v1}/watcher-report.json`.
  Boss coverage remains zero, so this is bounded fallback evidence rather
  than Stage-3, boss, rate, ordinary-ROM, or playthrough acceptance.

  The next Luna-owned continuation starts from that exact tick-14,000 state
  and stops normally at its first player-oracle divergence at MAME tick
  14,841:
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume14001-to15000-v1/watcher-report.json`.
  It completes 840/840 segment and 14,611/14,611 cumulative exact entries
  before the comparison; 2,757 player references are green and the first red
  reference is MAME action 0 / health 4 / `(52,112)` versus SNES action 9 /
  health 20 / `(68,96)`. `$071A/$073A` remain zero and halt remains zero, so
  the repaired gate neither leaked nor caused the split. This exactly matches
  the existing production-native-on/gameplay-native-off downstream false-
  respawn signature, whose upstream three-way task-frame divergence is already
  pinned at tick 14,746. It therefore strengthens the common virtual-MC68000-
  clock classification and rejects an interpreter/gameplay-native-only cause;
  it is not a new collision fix or Stage-3 completion. The run's three
  byte-identical post-entry-safe tick-14,743 states share SHA-256 `5ccbc509…`.
  The evidence ledger reuses that green pre-divergence boundary at resume tick
  14,744; `tools/test_vtime_interpreter_only_stage3_divergence.py` pins the
  compact discrepancy and checkpoint identity. A focused load of that exact
  safe state directly confirms the repaired fallback's internal split at
  tick 14,746 in
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-stage3-attribution-v1/watcher-report.json`:
  ticks 14,744--14,745 retain the MAME task-15 frame; at 14,746 SNES has
  `$02429C/$00044E`/SR `$2404` while MAME has
  `$0259B0/$0242BE`/SR `$2400`, then RNG/collision split. The retained phase
  ledger places the deficit at 114,978 cycles before the root. The focused
  guard is `tools/test_vtime_interpreter_only_stage3_attribution.py`.

  A bounded follow-up tests whether disabling all four scheduler shortcuts is
  sufficient to move that boundary. The diagnostic image
  `build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-v2.sfc`
  has SHA-256 `60087042d9b0ecc48525258033009a634085deb661899724d917b8df78266ae9`.
  Its per-fetch prepare path enforces `$071A/$073A/$0736/$073C=0` even when a
  restored state already contains a valid virtual clock. The first migrated
  v1 seam was non-testing because the old state retained `$0736=$5EEC` and
  `$073C=$A55A`; the corrected Luna-owned v2 seam records all four gates zero
  at ticks 14,744--14,747, yet retains the same 21/21/78/81-byte pattern and
  the same first task-15 divergence at tick 14,746. The compact report is
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-seam-v2/watcher-report.json`,
  guarded by `tools/test_vtime_interpreter_only_scheduler_fallback_evidence.py`.
  This rejects the four-shortcut fallback as a sufficient narrow repair. It
  is a ROM-migrated forensic negative, not direct path-fire instrumentation,
  fresh-boot evidence, a common-clock repair, or acceptance; no long replay
  was started.
  A Luna-owned disk reduction then narrows the remaining loop/idle scope at
  `build/playback-watcher-20260809/stage3-remaining-loop-idle-owner-scope-v1/watcher-report.json`.
  Its 46,900 retired MAME rows show `$0818` 1,993 times only in the preceding
  tick-14,744--14,745 interval and zero times in the failing
  14,745--14,746 interval; `$3B84/$3FEA/$ADBE` are absent there, while
  `$02429C/$025110/$0259B0` retire 1/1/27 times. This is path-owner scope,
  not a RAM oracle comparison. The smallest preceding-owner experiment makes
  `$0818` decline before its paced helper in explicit interpreter-only mode.
  Candidate
  `build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-v1.sfc`
  has SHA-256 `7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387`.
  In the bounded Luna seam at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-seam-v1/watcher-report.json`,
  read-only hooks prove `$99:FBB0` fires 17,133 times and the old `$99:FB00`
  helper never fires; all four fallback gates remain zero and halt remains
  zero. Nevertheless task 15 still first splits at tick 14,746 with the same
  MAME `$0259B0` versus SNES `$02429C` frame and 21/21/78/83 differing-byte
  progression. Thus `$0818` pre-mutation fallback is also insufficient and
  does not justify a fresh long replay. The results are pinned by
  `tools/test_stage3_remaining_loop_idle_owner_scope.py` and
  `tools/test_vtime_interpreter_only_0818_fallback_evidence.py`. This is
  ROM-migrated forensic evidence, not fresh-boot, rate, or acceptance truth;
  the next bounded timing target is the active failing-window
  `$02429C -> $025110 -> $0259B0` child-handoff group and its upstream clock
  ownership.
  The disk-only Luna ledger for that group is now
  `build/playback-watcher-20260809/stage3-2429c-25110-259b0-owner-ledger-v1/watcher-report.json`.
  In MAME's 139,486-cycle failing interval it measures 1,554 cycles from
  `$02429C` to `$025110`, 1,176 to `$02582E`, 146 to first `$0259B0`, 4,580
  across 27 continuation rows, 216 to the IRQ boundary, and a 64-cycle IRQ
  entry gap. Root to first continuation is only 2,876 cycles versus the
  retained 114,978-cycle pre-root deficit/115,204-cycle root-entry lateness.
  The path is real and its root/child/resume handoffs are not common-clock
  complete, but no single repair owner is isolated. The guard is
  `tools/test_stage3_2429c_25110_259b0_owner_ledger.py`; the next diagnostic
  is a source-authenticated, read-only root/child/IRQ hook ledger, not an
  architectural mutation.
  That Luna seam is now
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-child-hooks-v1/watcher-report.json`.
  All native root, child, canonical/interpreter branch, Stage-2, return, and
  `$02582A/$02582E/$0259B0` resume hooks record zero; the real IRQ entry hook
  records four hits and all four fallback gates remain zero. Task 15 still
  first splits at tick 14,746 with 21/21/78/83 differing bytes. Therefore the
  MAME child path is an oracle path but not an active accelerated owner in
  this interpreter-only candidate; changing its native handlers cannot fix
  this seam. `tools/test_vtime_interpreter_only_root_child_hooks_evidence.py`
  guards the ROM-migrated exclusion. Remaining attribution must inventory
  accelerated owners that actually fire, especially CE4 renderer and dynamic
  loop families.
  The resulting Luna inventory is
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-active-owner-inventory-v1/watcher-report.json`.
  CE4 and all ten separately addressable unmigrated native/renderer `$AC`
  writer labels are zero. Scheduler scan/switch entries execute 64/42/42
  times but their zero gates select the already-rejected fallbacks. The
  generic `gm_memclr/gm_verify_far/gm_memset_far` check chain executes
  19,262 times at each label; identical counts identify gateway traversal,
  not accepted acceleration or architectural mutation. `$0818` gateway and
  IRQ controls retain 17,133/four hits, and the divergence remains tick
  14,746. `tools/test_vtime_interpreter_only_active_owner_inventory.py`
  guards this bounded inventory. The only unresolved active cluster now needs
  accept-versus-decline entry/exit hooks before any loop fallback is changed.
  That Luna ledger is
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-generic-loop-ledger-v1/watcher-report.json`.
  Memclr, verify, and memset each receive 19,262 matcher entries but record
  zero accepted calls and zero collapsed mutations; all 1,594 word-shaped
  memset attempts decline. The task-frame split remains at tick 14,746.
  `tools/test_vtime_interpreter_only_generic_loop_ledger.py` guards the
  no-accept exclusion. With the observed accelerated owners now eliminated,
  the next disk-only attribution targets the interpreter/common-clock cycle
  model rather than another shortcut fallback.
  That audit is
  `build/playback-watcher-20260809/stage3-interpreter-common-clock-model-v1/watcher-report.json`.
  It proves the retained 16,308-versus-131,286-cycle comparison belongs to the
  older preserve/native-on mixed-ledger lineage: 16,308 is 8,154 selected
  two-cycle units, not an instruction count or a measured SHA `7a22…` bit-1
  phase. The MAME pre-root span has 11,006 retired intervals, of which 9,193
  match the static CPU-000 table and 1,813 require dynamic outcomes. Current
  source already applies the static table plus proven Bcc/DBcc/TRAP/MOVEM/
  shift corrections per interpreted fetch. Therefore the old 114,978-cycle
  deficit cannot be transferred to the interpreter-only candidate.
  `tools/test_stage3_interpreter_common_clock_model.py` guards that provenance.
  That direct Luna measurement is now
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-phase-v1/watcher-report.json`.
  The first launcher selected the wrong 51-tool Nexen companion set and is
  retained as invalid at zero boundaries; the corrected custom-build run exits
  zero, captures 4/4 boundaries, and matches `$02429C` 1/1. From the tick-14,745
  boundary to root, SHA `7a22…` consumes 34,856 two-cycle units = 69,712
  MC68000 cycles with no intervening reload or IRQ, versus MAME's 131,286
  cycles. It reaches root with 69,494 virtual cycles remaining while MAME takes
  IRQ only 7,692 cycles later: a 61,802-cycle phase error. All four gates and
  halt remain zero; the task split stays tick 14,746.
  `tools/test_vtime_interpreter_only_root_phase.py` guards this direct
  ROM-migrated undercharge. The bounded Luna fetch-count discriminator is now
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-fetch-count-v1/watcher-report.json`.
  It observes 6,471 prepare and 6,471 consume events in the exact boundary-to-
  root window, only 58.795% of MAME's 11,006 retired intervals (deficit 4,535),
  with zero reloads or IRQs. Gates and halt remain zero and ticks 14,744--14,745
  retain their 21-byte mismatch ranges. This rejects a cycle-table retune: an
  execution path is still skipped or collapsed despite the explicit fallbacks.
  `tools/test_vtime_interpreter_only_root_fetch_count.py` guards the result.
  The disk-only logical-PC alignment is now
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-pc-sequence-v1/watcher-report.json`.
  A valid 6,471-PC reconstruction against 11,006 MAME rows has 34 alignment
  operations, 4,551 MAME deletions, and 13 SNES insertions. Its first deletion
  is MAME indices 223--234 at `$0008E6…$0008D8`; disassembly makes the preceding
  `$0008DE` repeated MOVE.L run the unconditional bank-$00 `mvc_check` collapse.
  That owner explains 759 deleted MOVE rows, not the whole deficit. The largest
  2,970-row deletion is dominated by `$024998` pool-scanner PCs, but its native
  dispatch is not proven because all four gates remain zero. The full alignment
  stays on disk; `tools/test_vtime_interpreter_only_root_pc_sequence.py` guards
  the compact facts.
  Source and `tools/audit_vtime_accelerated_boundaries.py` now declare the
  previously omitted `mvc_check` boundary. A size-neutral VTIME pack patch
  routes it through `$F2:B4D1`; bit 1 falls back to `op_move_g` before mutation,
  while ordinary ROM bytes remain unchanged. The bounded candidate is
  `build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-v1.sfc`
  (SHA-256 `a49eedc7…`), guarded by
  `tools/test_vtime_interpreter_only_mvc_fallback.py`. Its bounded Luna seam at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-fetch-v1/watcher-report.json`
  raises prepare/consume from 6,471/6,471 to 7,230/7,230: an exact +759 recovery
  matching the deleted MOVE rows. Virtual charge rises from 34,856 to 42,446
  two-cycle units; root remaining falls to 27,157 units. MAME still has 3,776
  more retired intervals, and the two 21-byte mismatch ranges are unchanged.
  No reload, IRQ, gate, halt, task, or player regression appears in the seam.
  `tools/test_vtime_interpreter_only_mvc_fallback_evidence.py` guards this
  positive but partial result. The candidate PC alignment at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-pc-v1/watcher-report.json`
  reconstructs all 7,230 prepares and confirms the 759 MVC rows are now
  aligned. MAME still has 3,792 deleted rows and SNES 13 inserted rows across
  14 non-equal operations. The original first 12-row deletion remains, as
  does the largest 2,970-row deletion: MAME executes 2,096 `$0249xx` rows
  while the candidate records none. This establishes a skipped native/path
  owner, not a remaining MVC collapse; direct `$9D:B000/$B800` ownership still
  requires a real-bank hook. The compact guard is
  `tools/test_vtime_interpreter_only_mvc_pc_sequence.py`. That bounded owner
  probe is now
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-native-owner-v1/watcher-report.json`:
  strict boundary-to-root hooks see zero hits at `$00:D360/$D36E`,
  `$9D:C000`, `$9D:B000`, and `$9D:B800`, while prepare/consume remains
  7,230/7,230 with no reload or IRQ. That zero-hook result initially suggested
  a skipped allocator/pool path, but it did not prove one: the later PC-write
  reconstruction below shows the route executing outside VTIME prepare
  ownership. `tools/test_vtime_interpreter_only_root_native_owner.py` guards
  only the observed hook exclusion. The next discriminator was a disk-only alignment and
  21-byte branch-context reduction; no long replay is. That reduction is now
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-branch-context-v1/watcher-report.json`.
  The 2,970-row MAME-only region lies between equal scheduler anchors `$0007E4`
  and `$000766`; SNES executes no logical PC between them. MAME calls
  `$02E8B8→$0249C2` and then `$02E8C4→$02498C`. Of 21 captured byte
  differences, only eight are inside mapped 16-KiB work RAM; none is a direct
  operand of those calls/scans. `$F01C57`, the low byte of the project-tracked
  game-tick word at `$F01C56`, is MAME `$97` versus candidate `$96`. That is a
  one-count boundary offset, but it must not be called the cause of the
  apparently skipped scheduler region. Zero-advance, ROM-migrated reads of retained v6 gameplay-
  origin tick 221 and safe tick 250 at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-origin-phase-bytes-v1/watcher-report.json`
  already show the candidate one count behind (`$00DA/$00DB` and
  `$00F7/$00F8`). The offset therefore predates Stage 3 and is not a newly
  lost Stage-3 tick. This is checkpoint provenance, not fresh-current-candidate
  or acceptance evidence. A corrected tick-14,000--14,002 comparison also
  shows both MAME and candidate `$F01C56` advancing once per target; the
  apparently stalled value was the distinct IRAM `$0760` exact-entry counter.
  The guards are `tools/test_vtime_interpreter_only_root_branch_context.py`,
  `tools/test_vtime_interpreter_only_origin_phase_bytes.py`, and
  `tools/test_vtime_interpreter_only_phase_counter_scope.py`.
  The exact task-selection probe at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-task-selection-v1/watcher-report.json`
  then observes selectors `0,1,2,3,4,5,6,12,13,14,15`: task 13 is selected
  before task 15 with restored PC `$02E864`; it is not skipped by the
  scheduler. An exact-anchor join of the retained prepare stream at
  `...root-task13-pc-v1/watcher-report.json` contains no interior VTIME
  prepare between that task's `$0007E4/$000766` anchors while MAME retires
  2,970 rows. The independent PC-byte-write reduction at
  `...root-task13-pcwrite-v1/watcher-report.json` resolves the route question:
  the candidate PC states traverse `$0007E8→$02E864` and twelve ordered
  `$02E8B8→$0249C2→$02498C` visits, exactly matching MAME's target counts,
  before `$000532→$000766`. Thus the pool path is executing; the 2,970-row
  deficit is a VTIME prepare/clock-ownership bypass, not a gameplay-path skip.
  PC writes prove ordered state updates rather than retirement, and the
  uncharged executor still requires a bounded fetch-control owner probe. The
  compact guards are `tools/test_vtime_interpreter_only_root_task_selection.py`,
  `tools/test_vtime_interpreter_only_root_task13_pc.py`, and
  `tools/test_vtime_interpreter_only_root_task13_pcwrite.py`.
  The physical fetch-control probe at
  `build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-task13-fetch-control-v1/watcher-report.json`
  localizes that bypass: all 2,971 fetches reach `choke_tramp`, but only the
  first reaches VTIME choke/consume/prepare. The packed gateway encoded
  direct-page `LDA $2E`, which reads emulated A3.H, instead of the intended
  persistent absolute `$072E` loop-arm gate. The diagnostic-only pack repair
  uses `LDA $072E`; the then-ordinary ROM SHA `2dadd12c…` remained
  byte-identical. The
  rebuilt interpreter-only candidate is
  `build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-v1.sfc`
  (SHA `d91e28e9…`). Its same bounded task-13 probe is 2,971/2,971 for fetch,
  choke, consume, and prepare, with the same scheduler frame, gates, halt, and
  next-scan stop. The exact boundary-to-root count becomes 11,010 prepares
  versus 11,006 MAME rows, recovering 3,780 over `a49e…`; after the three-row
  capture-prefix drop, PC alignment leaves a twelve-row delete/reinsert of the
  same `$0008D6…$0008F0` signature and one terminal candidate `$0007E8`. The
  former 2,970-row task-13 deletion is fully aligned. Disk-only complete-call
  reduction at `...root-first12-mask-v1/watcher-report.json` resolves the
  twelve rows as a two-bit palette-mask phase: MAME loads `$00030000` and
  copies ordinals 16--17, while the candidate loads `$0000C000` and copies
  ordinals 14--15. Both calls have the same active count. Producer attribution
  at `...choke-gate-root-first12-mask-writer-v1/watcher-report.json` follows
  task 15 through `$003B42` load, `$003B46` `ROL.L #2`, `$003B4C` OR, and
  `$003B50→$0008C2`. Its `$F01C56/$F01C58` values remain exactly one rolling
  call behind MAME, the offset already present in zero-advance retained states
  at ticks 221 and 250. The residual ordering is therefore checkpoint-origin
  phase, not a newly observed Stage-3 path or clock loss. MAME writer/read/clear
  retirement is direct evidence; the candidate intermediate `$F01B12` write is
  inferred from its PC sequence and work state because the one bounded hook
  attempt stopped before the target. This is strong bounded
  common-clock progress, not fresh replay, global equality, rate, or
  acceptance. Guards are `tools/test_vtime_interpreter_only_choke_gate.py`,
  `tools/test_vtime_interpreter_only_root_task13_fetch_control.py`,
  `tools/test_vtime_interpreter_only_choke_gate_evidence.py`,
  `tools/test_vtime_interpreter_only_choke_gate_root_fetch.py`, and
  `tools/test_vtime_interpreter_only_choke_gate_pc_sequence.py`,
  `tools/test_vtime_interpreter_only_choke_gate_first12_context.py`,
  `tools/test_vtime_interpreter_only_choke_gate_first12_mask.py`, and
  `tools/test_vtime_interpreter_only_choke_gate_mask_writer.py`.
  The campaign runner still rejects the old tick-14,743 state as an
  *acceptance* resume under the new ROM because serialized WRAM contains the old
  video supervisor. It now supports an explicit diagnostic-only cross-ROM
  migration: authenticate the atomic old checkpoint, refresh only executable
  video WRAM `$7F:8000-$7F:AFFF` from the selected ROM, then prove CPU, PPU,
  game RAM, SA-1 IRAM, VRAM, CGRAM, OAM, SPC, and all other WRAM unchanged.
  This allows focused candidate iteration without replaying the accepted
  prefix; it never proves fresh boot, renderer/HUD continuity, rate, or release
  acceptance. No migration run or new ROM was created while enabling it.
  `tools/test_campaign_rom_migration.py` and
  `tools/test_campaign_resume_lineage.py` guard the contract. A separately
  labelled forensic capture preserved 89
  contiguous fixed-candidate work images for ticks 14,744--14,832. Disk
  reduction finds task mask/current equal to MAME throughout that evidence and
  task 15 exact through tick 14,746, then different at 14,747: candidate
  `$025876`/SR `$2409`, MAME `$02582E`/SR `$2408`. Player state is exact through
  14,746; input differs at 14,747 and Y at 14,748. This is bounded cross-ROM
  forensic evidence, not a resumable or accepted run.

  The exact old-candidate (`d91e28e9…`) tick-14,746 boundary-to-root ledger now
  closes the requested interval without replay. It has 10,173 matched
  prepare/consume events, charges 61,277 two-cycle units, and reaches the same
  pre-root instruction order before a MAME-only tail. Retained MAME 0.287
  charges 60,699 units, so the aligned endpoint is +578 units/+1,156 cycles;
  parent/native charges are present and the mismatch is inside interpreted
  timing/path work. The largest equal-PC deltas are DBRA sites.

  Both pre-state and deferred post-state DBcc helpers indexed the emulated Dn
  array with `2*n`, although D registers occupy four bytes. The opt-in VTIME
  wrapper now enables the corrected `4*n` stride; dormant production bytes are
  unchanged. The new interpreter-only diagnostic is
  `build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-dbcc-stride-v1.sfc`
  (SHA `7583d110…`), while the then-ordinary ROM remained exact SHA
  `2dadd12c…`.
  A disk-only counterfactual on the aligned old ledger replaces 493 DBcc
  outcomes at 22 PCs with retained MAME outcomes. It removes 246 units/492
  cycles and leaves +332 units/+664 cycles. After deferred native/RTS
  observability cancels, that remainder is one candidate-only 61-row collision
  path (+326), the known checkpoint mask phase (+5), and only +1 unit of
  common-path timing (`DIVU` +2, Bcc -1). MAME's exact cycle core provides no
  compact operand-cycle helper for a safe general DIVU repair, so no
  PC-specific timing exception was added.

  A cumulative `7583d110…` capture from the migrated tick-14,743 origin reports
  a superficially close -19-unit boundary-to-root endpoint, but task 15 is
  already different at the tick-14,746 interval start (candidate `$025856`,
  MAME `$0259B0`). It is not an aligned oracle comparison and does not close or
  promote VTIME. A single attempt to load the old exact tick-14,746 boundary
  under `7583d110…` reached no requested update in 719 frames and ended at
  virtual PC `$F01B6C`, halt `$DEAD`; the state is explicitly an
  `ordinary_paused_boundary` with `resumable_checkpoint=false`. It must not be
  retried.

  The required fresh validation then exposed a separate rejected experiment,
  not a DBcc regression. With the old fixed prompt timing, fresh `7583d110…`
  accepted zero of eight credit pulses. A preserved-ROM bisect at
  `build/playback-watcher-20260810/fresh-credit-bisect-v1/watcher-report-v2.json`
  brackets the loss between `60087042…` (8/8 credits) and `7a22b819…` (0/8):
  the only intervening stage is the diagnostic `$0818` pre-mutation fallback.
  The zero-advance state has both CPUs running but pacing arm/last-release/debt
  all zero and frame request/ack 64/0. The gateway had bypassed the complete
  S-CPU/NMI paced rendezvous. MVC fallback, choke, and DBcc changes are later
  than the bracket and are excluded as causes.

  That rejected pure-interpreter `$0818` fallback is now explicit opt-in bit 2;
  default interpreter-only VTIME retains the paced helper and its already-
  installed VTIME release callback. The then-ordinary ROM SHA `2dadd12c…`
  remained byte-identical. The corrected diagnostic is
  `build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-paced-mvc-fallback-choke-gate-dbcc-stride-v1.sfc`,
  SHA `14e920eb…`. Its first fresh run accepted 8/8 credits but proved that the
  old prompt delay no longer selected MAME's gameplay-origin RNG. A same-ROM,
  neutral, read-only frame calibration found the exact target at video frame
  9,432, tick `$0760` 168, RNG 2,716: a 3,224-frame credited wait. This is
  bootstrap alignment only, not timing acceptance.

  One calibrated fresh replay of exact `14e920eb…` is partial-green through
  MAME tick 250 at
  `build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-fresh-to250-calibrated-v1/watcher-report.json`.
  It accepts 8/8 credits, observes the requested interpreted `$003A92` origin
  at MAME tick 221/RNG 200, records zero oracle divergences through 29 neutral
  gameplay ticks, and has halt zero. Its repeat-validated same-ROM safe tick-
  250 checkpoint is SHA `ba6f0490…`, with SA-1 IRAM sidecar SHA `8950c547…`,
  and is explicitly resumable at the post-entry `$008F56->$008F58` boundary.
  The first supplied continuation command used completed tick 250 as the
  resume tick and was rejected in preflight; no emulator launched. The event
  contract correctly resumes at 251, and the regression now pins that
  distinction. The corrected same-ROM continuation is green through tick 806
  across 555/555 interpreted entries, then through tick 1,100 across another
  293/293 entries. Cumulative coverage is 877/877 entries, with 12/12 player
  references and six real input transitions green, zero oracle divergence,
  and halt zero. The repeat-validated tick-806 and tick-1,100 checkpoints have
  SHAs `fe4a5409…` and `27207e5f…`; the latter's IRAM sidecar is `5cb96e4f…`
  and resumes at tick 1,101.

  The authenticated child now extends that exact lineage through tick 3,000 at
  `build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume1101-to3000-v2/watcher-report.json`.
  It completes 1,899/1,899 segment entries and 2,776/2,776 cumulative entries,
  with 168/168 player references, 84 real input transitions, all gameplay
  buttons, actions 0/1/2/8/9, one death with 2/2 green death references, zero
  oracle divergence, halt zero, no invalid task stack, and no render-queue
  drop. Actions 3/4/5/7/10 and bosses remain uncovered. Repeat-identical
  resumable checkpoints exist at ticks 1,500, 2,000, 2,500, and 3,000; the
  latest is SHA `47dc58a1…`, IRAM `4ee69101…`, resume tick 3,001. Two launcher-
  only negatives are retained separately: one selected the wrong Nexen
  companion identity and one failed the pinned MAME version preflight; neither
  launched gameplay, and the completed exit-0 partial-count-Nexen run
  supersedes them. This remains bounded Stage-1 lineage evidence—not Stage 3,
  complete action/boss coverage, rate, promotion, production acceptance, or
  full-playthrough evidence.

  The next same-hash segment stayed oracle-green through tick 4,559, then its
  Nexen MCP server closed mid-call. This was a transport-only stop: 1,558/1,558
  segment and 4,334/4,334 cumulative entries were green, all action IDs were
  observed, halt remained zero, rendering remained live, and the repeat-
  identical tick-4,500 bundle was safe. A bounded recovery replayed only the
  59 already-green ticks after that checkpoint and then continued through tick
  5,000 with `--continue-oracle-divergences`: 499/499 segment and 4,833/4,833
  cumulative entries, 921/921 player references, 85 real input transitions,
  all action IDs, two deaths with 4/4 death references, zero divergence, halt
  zero, and minimum task-stack margin 138. Bosses remain unobserved. The
  repeat-identical tick-5,000 state is SHA `0fd2e312…`, IRAM `9e6e7605…`, and
  resumes at 5,001. The transport stop invalidates no gameplay evidence and
  does not justify a ROM rebuild or fresh boot. Subsequent long playback must
  remain Luna-owned, resume this current-hash checkpoint in bounded segments,
  and continue past oracle mismatches when state safety permits. Diagnose any
  discrepancy from its nearest checkpoint; batch nonblocking fixes. Before a
  new ROM lineage, report the confirmed root cause, why rebuilding is needed,
  and which fresh replay it invalidates, then obtain explicit approval for any
  fresh-boot campaign. Do not replay the 9,432-frame bootstrap implicitly.

  The next Luna-owned same-hash continuation is partial-green through tick
  6,500: 1,499/1,499 segment and 6,332/6,332 cumulative interpreted entries,
  1,210/1,210 player references, 605 real input transitions, every action ID,
  two deaths with 4/4 green death references, zero oracle divergence, halt
  zero, live rendering, and minimum task-stack margin 138. Bosses remain
  unobserved. Repeat-identical resumable checkpoints exist at ticks 5,500,
  6,000, and 6,500; the last is SHA `fb9644dd…`, IRAM `26c824b3…`, resume
  tick 6,501. This extends the accepted current-hash lineage; it does not alter
  the Stage-1, rate, promotion, fresh-boot, or full-playthrough limits above.
  The first 6,501 continuation attempt completed no new entry because tick
  6,501 itself is an input edge and the harness indexed an empty zero-entry
  span list. The accompanying `OSError(9)` was cleanup fallout, not transport.
  The guarded harness now processes the already-reached edge without running
  or indexing an entry, then advances at tick 6,502. The failed child
  invalidates no accepted parent evidence and requires no ROM rebuild.
  The first corrected retry was then rejected before emulator launch because
  the harness edit changed the runner hash. The finite lineage compatibility
  gate now admits exactly the parent runner SHA `2030c213…`, whose only
  successor change is this zero-entry handling; arbitrary runner drift remains
  rejected and guarded. That preflight negative invalidates no evidence.

  The corrected Luna-owned v3 continuation is partial-green through tick
  8,000: 1,499/1,499 segment and 7,831/7,831 cumulative interpreted entries,
  375/375 segment and 1,585/1,585 cumulative player references, 188 segment
  and 793 cumulative real input transitions, every action ID, two deaths in
  this segment, 6/6 cumulative death references, zero divergence, halt zero,
  live rendering, and all 15 initialized task stacks valid with minimum margin
  130. Bosses remain unobserved. Repeat-identical resumable checkpoints exist
  at ticks 7,000/7,500/8,000; the last is SHA `aea7ce50…`, IRAM `99bab411…`,
  resume tick 8,001. No ROM rebuild or fresh boot occurred.

  The next same-hash segment is partial-green through tick 9,500: 1,499/1,499
  segment and 9,330/9,330 cumulative entries, 267/267 segment and
  1,852/1,852 cumulative player references, 133 segment and 926 cumulative
  real input transitions, every action ID, two deaths in this segment, 8/8
  cumulative death references, zero divergence, halt zero, live rendering,
  and all 15 initialized stacks valid with minimum margin 138. Bosses remain
  unobserved. Repeat-identical checkpoints exist at 8,500/9,000/9,500; the
  last is SHA `efd193b0…`, IRAM `fabcd919…`, resume tick 9,501. No prefix
  replay, ROM rebuild, or fresh boot occurred.

  The next same-hash segment is partial-green through tick 11,000:
  1,499/1,499 segment and 10,829/10,829 cumulative entries, 550/550 segment
  and 2,402/2,402 cumulative player references, 275 segment and 1,201
  cumulative real input transitions, every action ID, two deaths in this
  segment, 10/10 cumulative death references, zero divergence, halt zero,
  live rendering, and all 15 initialized stacks valid with minimum margin 138.
  Bosses remain unobserved. Repeat-identical checkpoints exist at
  10,000/10,500/11,000; the last is SHA `6fd49508…`, IRAM `ef9a8033…`, resume
  tick 11,001. No prefix replay, ROM rebuild, or fresh boot occurred.

  The next same-hash segment is partial-green through tick 12,500:
  1,499/1,499 segment and 12,328/12,328 cumulative entries, 164/164 segment
  and 2,566/2,566 cumulative player references, 82 segment and 1,283 cumulative
  real input transitions, every action ID, two deaths in this segment, 12/12
  cumulative death references, zero divergence, halt zero, live rendering,
  and all 15 initialized stacks valid. The minimum stack margin fell from 138
  to 92 and remains an explicit continuation safety watch. Bosses remain
  unobserved. Repeat-identical checkpoints exist at 11,500/12,000/12,500; the
  last is SHA `0ff1242f…`, IRAM `83608462…`, resume tick 12,501. No prefix
  replay, ROM rebuild, or fresh boot occurred.

  The next same-hash segment is partial-green through tick 14,000:
  1,499/1,499 segment and 13,827/13,827 cumulative entries, 84/84 segment and
  2,650/2,650 cumulative player references, 42 segment and 1,325 cumulative
  real input transitions, every action ID, no new deaths, 12/12 cumulative
  death references, zero divergence, halt zero, live rendering, and all 15
  initialized stacks valid; minimum margin recovered to 138. Bosses remain
  unobserved. Repeat-identical checkpoints exist at 13,000/13,500/14,000; the
  last is SHA `234ef4ad…`, IRAM `a5d1d340…`, resume tick 14,001. No prefix
  replay, ROM rebuild, or fresh boot occurred.

  The same-hash post-divergence segment continues safely through tick 15,500,
  but the exact oracle-green prefix ends at tick 14,747. First divergence is
  MAME tick 14,748: SNES player Y 139 versus MAME 136 while action, health, X,
  flags, and animation match. There are 27 Y-only mismatch records at 24
  sparse ticks through 14,866, then no further recorded mismatch through
  15,500. The segment still completes 1,499/1,499 entries and 15,326/15,326
  cumulative entries; halt remains zero, rendering remains live, and all 15
  initialized stacks remain valid with minimum margin 138. Its end SNES game
  tick is 15,494 versus MAME tick 15,500, compared with the earlier two-tick
  offset; whether this is causal timing alignment or semantic Y drift is under
  focused diagnosis from the tick-14,500/pre-failure states. No Stage-
  transition or boss event was emitted. Repeat-identical checkpoints exist at
  14,500/15,000/15,500; the last is SHA `43f9c07c…`, IRAM `d5dff99d…`, resume
  tick 15,501.

  Focused same-ROM reduction from the retained tick-14,740 state initially
  appeared to confirm a causal class, but that causal conclusion is now
  superseded. The corrected `$025110` child alignment has 553 common
  retirement rows with zero PC/opcode mismatch and zero common adjusted-cost
  delta; every bounded segment is exact. The earlier repeated-loop `+132`
  claim and `$02584A` branch mismatch were endpoint-alignment errors and are
  invalid. At the real `$0818` virtual-IRQ boundary, however,
  `vtime_consume_expired` leaves the staged pre-IRQ `$0818/4E75` cost live,
  `vtime_reload_virtual` neither discards that stale cost nor stages an
  exception-entry owner, and `take_irq` constructs the frame without VTIME
  ownership. The first ISR fetch therefore consumes the stale eight-unit
  cost, while the final `$000708/4EB9` ten-unit cost crosses the first
  `$003A92` observation boundary. MAME separately spends 66 cycles on the IRQ
  edge. From first `$003A92` to `$025110`, candidate versus MAME is
  133,046 versus 133,020 cycles (`+26`). This isolates a real interrupt-entry
  plus prepare/consume endpoint-ownership defect, but later same-checkpoint
  counterfactuals prove that it is not the tick-14,748 Y cause. The compact
  reduction is `focused-y-write-v1/irq-cost-pipeline-v1/irq-cost-report.json`
  below the tick-14,001--15,500 watcher directory, guarded by
  `tools/test_vtime_interpreter_only_irq_cost_pipeline.py`.

  The current causal result is ordered input publication. On v4 ROM
  `4a3555fd…`, both a `+2` interval-clock seed and a direct one-unit countdown
  decrement at the authenticated `$025116` child entry leave first divergence
  at tick 14,748. The corrected immediate-boundary probe instead shows
  `$003AD8` reading 36,082,626 SA-1 cycles before the next `$0818` re-arm. NMI
  samples B+Up as `$0088`, but arm remains 2, the ordered publisher does not
  run, `$410000` remains neutral, and candidate `$900001` returns `$FF`; MAME
  returns `$EE`, produces D7=-3, and moves Y 139->136. The compact corrections
  are under `build/playback-watcher-20260811/` in
  `v4-clock-offset-counterfactual-v1/`,
  `v4-child-entry-remain-minus-one-counterfactual-v1/`,
  `v4-input-owner-v3-corrected/`, and `v4-input-rearm-order-v2/`.

  The first staging image, v5 `e517fb3e…`, is invalid gameplay evidence because
  its `$F2:B500` helper overlapped the live dynamic opcode-cost decoder and
  stalled at `$003A92/$48E7`. Relocating the helper to `$B740` in v6
  `928d2e72…` restored progress but exposed the newest NMI sample immediately,
  shifting the Y mismatch one tick early to 14,747. The corrected v7 diagnostic
  patches only the five-byte `input_p1` prefix; it preserves generic
  `joy_read`, commits any real `$0818` mailbox publication, and otherwise uses
  the preceding P1 sample before capturing the next one. Its ROM is
  `build/interp-vtime-interpreter-only-paced0818-dbcc-irq-entry-vpa-input-delayed-v7.sfc`,
  SHA-256 `45c9096dfda3d4203878c18954725ff4814f23f4e28a1e623f3cf07b647e6c72`.
  Luna's ROM-only migration from the authenticated v4 tick-14,745 checkpoint
  is partial-green through 14,750: Y is 139 at 14,747 and 136 at 14,748,
  2,746/2,746 player comparisons and 12/12 death references are green, and the
  three tick-14,750 checkpoints are byte-identical (state `9fde6a6b…`, IRAM
  `c98e718e…`). The compact report is
  `build/playback-watcher-20260811/v7-input-delayed-migrated14745-to14750-v2/watcher-report.json`.
  The exact-v7 same-ROM continuation at
  `build/playback-watcher-20260811/v7-input-delayed-resume14751-to15000-v3/watcher-report.json`
  then remains partial-green through tick 15,000: cumulative player comparisons
  are 2,772/2,772, death references 12/12, 1,386 input transitions, halt zero,
  live rendering with zero queue drops, all 15 initialized task stacks valid at
  minimum margin 138, and no oracle divergence. The former tick-14,748 input/Y
  seam stays corrected. Repeat-identical safe checkpoints at
  14,760/14,775/14,800/14,850/14,900/14,950/15,000 cap replay cost; tick 15,000
  state SHA is `918098c4…`, IRAM `43c45f3c…`, and resumes at 15,001. The first
  continuation request was rejected before launch on runner/emulator identity;
  a finite audited predecessor-runner admission fixed that without relaxing
  other identity fields. A second run was externally terminated green at
  14,761 without a new checkpoint. Neither negative is a ROM failure. This is
  bounded migrated-lineage evidence, not fresh-boot, performance, production,
  boss, or playthrough acceptance, and no fresh campaign was started.

  The exact-v7 lineage then stays fully player/input/death-oracle green through
  tick 16,000. The original runner reported red Stage-1 boss rows at MAME ticks
  15,906 and 15,988. Those are invalid comparisons rather than a ROM
  divergence: every one of the authenticated timeline's 139,925 tick rows has
  `frame - tick == 74`, while the old loader subtracted 75. More importantly,
  both MAME timeline rows and SNES campaign stops are pre-body `$003A92`
  boundaries, so a write during tick T becomes observable at T+1. A focused
  frame-minus-74 retry remained stale at 15,907/15,989 and confirmed that
  pre-body contract. The final harness keeps 15,907/15,989 as write ticks and
  compares at post-write boundaries 15,908/15,990. That 100-tick Luna replay
  is partial-green through 16,000: player rows 2,889/2,889, death references
  12/12, input transitions 1,445, boss rows 2/2, oracle divergences zero, halt
  zero, renderer queue drops zero, and all 15 initialized task stacks valid at
  minimum margin 138. The original compact reports are
  `build/playback-watcher-20260811/v7-input-delayed-resume15001-to15500-v1/watcher-report.json`
  and
  `build/playback-watcher-20260811/v7-input-delayed-resume15501-to16000-v1/watcher-report.json`.
  The stable counter relation remains MAME tick minus six. Focused exact-state
  traces show the init committing big-endian `$0028` during SNES tick 15,901
  and the first hit committing `$0024` during 15,983; they are observable at
  the next campaign stops, `15,908/15,902` and `15,990/15,984`. The compact
  byte reduction is
  `build/playback-watcher-20260811/v7-boss-health-write-window-v2/raw-classification.json`;
  `tools/trace_v7_boss_health_window.py` authenticates the exact ROM, Nexen,
  state, IRAM, controller mask, and two-byte physical write. The hook-reported
  logical PC is notification context, not routine-ownership proof.
  `tools/test_boss_fixture_frame_tick_boundary.py` pins the corrected runner
  write-frame constant, one-tick observation delay, both event pairs, health
  transitions, and the full retained timeline. The final compact report is
  `build/playback-watcher-20260812/v7-boss-observation-resume15901-to16000-v1/watcher-report.json`.
  This excludes an initializer/subtractor defect for these two writes and
  removes the alleged organic boss-ordering root; later hits remain unproven
  on v7. Repeat-identical
  safe tick-16,000 state SHA is `06da361f…`, IRAM
  `3a672763…`, and resumes at 16,001 without replay.

  The corrected v7 suffix then continues through tick 16,500 with six cumulative
  Stage-1 boss observations green: the new rows are MAME ticks 16,102/16,201/
  16,285/16,403 with observed health 34/31/29/25. Player, input, and death
  references remain fully green with no oracle divergence, halt zero, renderer
  queue drops zero, and all initialized task stacks valid at minimum margin 138.
  The repeat-identical tick-16,500 checkpoint is state `f6c5b389…`, IRAM
  `5de396c8…`, and resumes at 16,501. The compact report is
  `build/playback-watcher-20260812/v7-boss-observation-resume16001-to16500-v1/watcher-report.json`.
  This validates only the first six Stage-1 fixtures; it is not full-boss,
  fresh-boot, production, performance, or playthrough acceptance.

  The next corrected v7 suffix reaches tick 17,000 with 11 cumulative Stage-1
  boss observations green. New rows are MAME ticks 16,519/16,624/16,750/
  16,837/16,921 with expected and observed health 21/18/14/11/9. Player,
  input, and death references remain green with no oracle divergence, halt zero,
  renderer queue drops zero, and minimum initialized-stack margin 138. The
  repeat-identical tick-17,000 checkpoint is state `1bab53c8…`, IRAM
  `bf80c888…`, and resumes at 17,001. The compact report is
  `build/playback-watcher-20260812/v7-boss-observation-resume16501-to17000-v1/watcher-report.json`.
  This validates the retained first 11 Stage-1 fixtures only; it is not complete
  Stage-1 boss behavior, full-boss, fresh-boot, production, performance, or
  playthrough acceptance.

  The corrected v7 suffix reaches tick 17,500 with 12 cumulative Stage-1 boss
  observations green. The new row is MAME tick 17,020 with expected and
  observed health 6. Player, input, and death references remain green with no
  oracle divergence, halt zero, renderer queue drops zero, and minimum
  initialized-stack margin 138. The repeat-identical tick-17,500 checkpoint is
  state `9f785e78…`, IRAM `b1a53fde…`, and resumes at 17,501. The compact report
  is `build/playback-watcher-20260812/v7-boss-observation-resume17001-to17500-v1/watcher-report.json`.
  The last two Stage-1 fixtures remain pending; this is not complete Stage-1
  boss behavior, fresh-boot, full-boss, production, performance, or playthrough
  acceptance.

  The corrected v7 suffix reaches tick 18,000 with all 14 retained Stage-1 boss
  fixtures green. New rows are MAME ticks 17,562 and 17,656 with expected and
  observed health 2 and `$FFFF`. Player, input, and death references remain
  green with no oracle divergence, halt zero, renderer queue drops zero, and
  minimum initialized-stack margin 138. The repeat-identical tick-18,000
  checkpoint is state `d06e3fb9…`, IRAM `fdfe1d7d…`, and resumes at 18,001. The
  compact report is `build/playback-watcher-20260812/v7-boss-observation-resume17501-to18000-v1/watcher-report.json`.
  This completes the retained Stage-1 fixture set only; it is not fresh boot,
  full organic boss behavior, full playthrough, production, or acceptance.
  Stage-2/3 boss fixtures remain pending.

  The corrected v7 lineage then continues from ticks 18,001 through 20,000 with
  no new divergence and the 14/14 retained Stage-1 boss fixtures cumulatively
  green. Successful compact reports are
  `build/playback-watcher-20260812/v7-boss-observation-resume18001-to18500-v1/`,
  `.../resume18601-to19000-v3/` (after recovery),
  `.../resume19001-to19500-v1/`, and
  `.../resume19501-to20000-v1/`. The 18,501–18,649 transport attempt stalled
  after a repeat-safe 18,600 state; stale exact processes were terminated, a
  first retry timed out before session establishment because of a stale port,
  and the secondary unbound-`m` capture bug was fixed in `d309c67` before the
  fresh-port recovery completed green. Endpoint tick 20,000 is state
  `25b60a…`, IRAM `128013bd…`, resumes at 20,001, with halt zero, minimum stack
  margin 136, and renderer drops zero. This remains checkpointed-v7 evidence;
  the next boss fixture is Stage 2 at MAME tick 36,227, and fresh boot, full
  playthrough, and production acceptance remain unproven.

  Luna previously continued the older unchanged `14e920eb…` hash from tick
  15,501 through 17,000.
  The run remained live with halt zero, all 15 initialized stacks valid at
  minimum margin 138, and active rendering. It recorded 38 segment
  divergences: 13 input comparisons, 14 input-response comparisons, and 11
  boss fixtures. The boss rows are Stage-1 fixtures at sparse MAME ticks
  15,906--16,919; SNES is exactly six game ticks behind in every row. Health
  is `40->0` at initialization, then `36->40`, `34->36`, `31->34`,
  `29->31`, `25->29`, `21->25`, `18->21`, `14->18`, `11->14`, and
  `9->11`: each observed value after initialization is the preceding expected
  value because the superseded harness sampled two observation boundaries
  early. All 11
  rows use the invalid frame-minus-75 conversion; they provide boss-region
  coverage but neither red nor green boss-oracle evidence. Repeat-identical
  checkpoints exist at 16,000/16,500/17,000; the last is state SHA
  `a9826e63…`, IRAM `cdf1a8c7…`, resume tick 17,001. The compact reports are
  under `build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume15501-to17000-v1/`.

  The next unchanged-hash Luna segment reaches tick 18,500. Three further
  Stage-1 boss rows preserve the apparent one-fixture lag: tick 17,018 expected 6 and
  observed 9; tick 17,560 expected 2 and observed 6; tick 17,654 expected
  `$FFFF` and observed 2. Cumulative divergence classes are now 13 input, 14
  input-response, and 14 boss rows. All of those boss comparisons used the
  now-rejected frame-minus-75 boundary and are invalidated rather than accepted
  as red or green boss evidence. Halt stays zero, all initialized stacks remain
  valid at minimum margin 138, and rendering remains live. Repeat-identical
  checkpoints exist at 17,500/18,000/18,500; the last is state SHA
  `718d3dd3…`, IRAM `a14d74b7…`, resume tick 18,501. This is forensic coverage,
  not boss, timing, or acceptance evidence.

  Luna continued the same hash through tick 20,000. The 1,500-tick segment
  adds no oracle-mismatch or boss-fixture row; cumulative counts remain 13
  input, 14 input-response, and 14 boss divergences. It processes 161 segment
  and 1,742 cumulative input transitions, ending with halt zero, live
  rendering, and all initialized stacks valid at minimum margin 136.
  Repeat-identical checkpoints exist at 19,000/19,500/20,000; the endpoint is
  state SHA `caf9df72…`, IRAM `f06ec2ad…`, resume tick 20,001. Accepted truth
  remains capped at tick 14,000; tick 20,000 is forensic coverage only.

  Repairing that contract requires changing the packed VTIME/IRQ handoff and
  therefore a new ROM hash. No repair, rebuild, or fresh boot has been
  performed. A new lineage would require fresh acceptance replay from the
  calibrated tick-221 origin through the present boundary; the `14e920eb…`
  lineage remains valid only as preserved historical and diagnostic evidence.
  The exact replacement charge/handoff still requires focused implementation
  proof before a rebuild is justified.

  The charge ledger, counterfactual, cumulative non-comparability, and failed
  isolated-state contract are guarded by
  `tools/test_vtime_interpreter_only_choke_gate_vtwrite_charge.py`,
  `tools/test_vtime_dbcc_register_stride.py`,
  `tools/test_vtime_interpreter_only_choke_gate_dbcc_stride.py`, and
  `tools/test_vtime_interpreter_only_dbcc_isolated_state.py`, in addition to
  `tools/test_vtime_interpreter_only_0818_paced_default.py` and the existing
  resume/partial/player guards.
- A fresh power-on exact-MAME owner-activity capture now spans ticks
  14,743--14,747 at
  `build/mame-scheduler-cycle-phase-current-a976-14743-14747-v3`. Its 5,055
  program-read observations see scheduler, idle, task-15, and collision seam
  activity. Those taps also observe data reads and prefetches, so they are
  explicitly *not* used as instruction/block attribution. The qualified join
  at `build/validate-mame-scheduler-cycle-phase-current-a976-v2.json`, guarded
  by `tools/test_mame_scheduler_cycle_phase.py`, instead takes IRQ PC/cycle
  truth from the instruction-only MAME debugger trace: `$000818`, `$0259B0`,
  `$02582E`, `$000810` at 139,300/139,302/139,296/139,342-cycle periods. It confirms
  the existing hardware-boundary classification and owner scope; it proves no
  handoff ledger, common clock, SNES repair, rate, or completion.
- The one-tick native-entry trace used for Stage-3 owner scoping now has an
  explicit active-ROM/source alignment reduction at
  `build/validate-active-native-entry-alignment-current-a976-safe14743-v2.json`,
  guarded by `tools/test_active_native_entry_alignment.py`. All 240 source-
  labelled entry hits resolve: 236 hit exact current source bytes and four
  hit only the two documented production counter-strip sites. This corrects
  an initially wrong `$9F` packing assumption: `escbank9` starts at
  `$9F:A100` / file `$2FA100`, not `$9F:8000`. The result establishes address
  provenance for this observed tick only. It neither makes the rejected
  `b758…` rebuild equivalent to `a976…` nor proves unobserved banks, timing,
  gameplay, rate, or completion.
- The active ROM now also has a same-hash, tick-14,743 fetch-boundary hotspot
  profile at `build/profile-stage3-tick-current-a976-safe14743-v1/profile.json`,
  guarded by `tools/test_stage3_current_a976_profile_evidence.py`. One
  stop-by-stop update consumed 1,936,861 SA-1 cycles, 11 video frames, and
  413 genuine interpreter fetches. The `$02429C` fusion and `$025110` guarded
  collision route each fired once, while no pool-scanner entry fired. Its
  largest single attribution, `$0242BE`, is 101,454 cycles (5.24%); its top
  20 account for only 40.35%. This excludes a one-routine/renderer-only
  diagnosis. The probe itself perturbs execution and is neither no-hook rate,
  fresh-boot FPS, a timing repair, nor completion proof.
- The qualified logical-region reduction at
  `build/analyze-stage3-current-a976-hot-regions-safe14743-v1.json`, guarded
  by `tools/test_stage3_current_a976_hot_regions.py`, identifies selectable
  clusters without conflating them with native block costs: `$027B00-$027BFF`
  record emission is 629,772 cycles (32.52%), `$02E40E-$02E55B` draw
  dispatch/call setup is 362,358 (18.71%), task 15 is 101,454 (5.24%), and
  scheduler/idle is 156,010 (8.05%). The top-row coverage is only 88.50% and
  23.99% remains unassigned even within it, so no single-region rate or
  semantic repair is admitted.
- That `$027B` cluster exposed a concrete native/HLE route failure in active
  `a976…`: original MAME executes both `$027B44` and `$027B7C` 60 times in
  the retained Stage-3 trace, while the same safe-checkpoint native-on trace
  enters parent `$027952` 12 times but enters each child zero times. Bank `$02`
  reaches the compact `$9D:DA00` sparse dispatcher, whose two exact comparisons
  were absent and therefore rejoined the interpreter. The hash-guarded,
  non-promoted candidate
  `build/interp-stage3-record-emitter-route-current-a976-v1.sfc`
  (`387855da…`) changes only the existing `$027952→$027AEA` operand, the
  isolated dispatcher window, and the header checksum (112 changed bytes).
  It is green 14/14 in same-state original-MAME/native-off/native-on parent
  comparisons at
  `build/validate-stage3-record-emitter-route-current-a976-isolated-v1.jsonl`,
  and its organic safe-checkpoint trace now enters `$027AEA`, `$027B44`, and
  `$027B7C` 12 times each. The joined diagnosis and regression are
  `build/validate-stage3-record-emitter-route-coverage-current-a976-v4.json`,
  `tools/test_stage3_record_emitter_route_coverage.py`, and
  `tools/test_stage3_record_emitter_route_candidate.py`. Its fresh one-credit
  HUD/art boot is green at
  `build/validate-fresh-one-credit-prompt-stage3-record-emitter-route-current-a976-v1/summary.json`.
  Its checkpoint-local native-on cost improves to 1,800,936.97 cycles/tick
  with both emitters firing 356 times, but still fails the 358K budget at
  `build/measure-stage3-record-emitter-route-current-a976-safe14743-v1/summary.json`.
  The same joined report exposes a further live `$02E524` sparse-route miss:
  MAME executes it 60 times but both active and this candidate enter its
  wrapper zero times. It is now explicitly rejected, rather than merely
  unpromoted: its independent fresh power-on native-on controller replay is
  red at the Button 1 response boundary, MAME tick 2,958 after input tick
  2,956 (`build/fresh-campaign-stage3-record-emitter-route-current-a976-to14746-native-on-v1/summary.json`).
  Arcade enters action 1 while the candidate remains action 0 at the same
  health and position. The initial harness label is hardware-boundary/timing,
  but the bounded source audit identifies the root as native/HLE routing: the
  shared dispatcher also receives Stage-1 calls, and canonical pointer/stack
  guards do not establish Stage-3 provenance. Source keeps those routes absent;
  the builder now reproduces only the rejected `387855da…` experiment exactly.
  `tools/test_shared_dispatch_stage_provenance.py` guards that source and its
  freshly assembled dispatcher window, and
  `tools/test_rejected_shared_dispatch_fresh_failure.py` guards the fresh
  failure's ROM/state identity. The exact-entry forensic pre-input state is
  `build/fresh-campaign-stage3-record-emitter-route-current-a976-to2958-prefailure-v1/states/pre-failure-input.mss`
  (SHA-256 `80799f…`, with sidecar `ca40bb…`). This is not
  a promotion, FPS result, common-clock repair, Stage-3 completion, or
  full-playthrough claim.
- The safe replacement is parent-local, not dispatcher-wide. Source
  `src/escbank2.pasm` now sends only native `$027952`'s already-pushed-BSR
  children `$027B44/$027B7C/$02E524` directly to their guarded wrappers; interpreted
  Stage-1 calls retain the conservative `$9D:DA00` path. The isolated
  initial candidate `0453ef75…` proves the record emitters, and follow-on
  `91cf499f…` adds `$02E524` at
  `build/interp-stage3-parent-local-draw-current-a976-v1.sfc`. The follow-on
  is green 14/14 in exact original-MAME/native-off/native-on parent cases,
  enters `$027AEA/$027B44/$027B7C/$02E524` 12 times each in the retained Stage-3
  checkpoint tick, and clears a fresh power-on controller replay through
  tick 3,000 with zero oracle divergences. Its terminal is the intentional
  missing-coverage guard, not a player mismatch; this includes the repaired
  tick-2,958 Button 1 response. The joined report and source/candidate guards
  are `build/validate-stage3-parent-local-record-emitter-current-a976-v1.json`,
  `tools/test_stage3_parent_local_record_emitter.py`,
  `tools/test_stage3_parent_local_emitter_source.py`, and
  `tools/test_stage3_parent_local_record_emitter_candidate.py`; the `$02E524`
  follow-on is guarded by `tools/test_stage3_parent_local_draw_evidence.py`.
  Its authenticated fresh-lineage continuation from safe tick 10,000 reaches
  requested MAME tick 14,746 with zero oracle divergences, 2,744 green player
  references, and six observed deaths at
  `build/playback-watcher-20260808/parent-local-draw-91cf-resume10001-to14746-native-on-v3/watcher-report.json`.
  The report is `partial-green`, not a completion: it observed zero boss
  events and used a save-state continuation rather than one uninterrupted run.
  It remains
  non-promotable: the follow-on sustained Stage-3 native-on cost is
  1,571,650.55 cycles/tick
  against the 358K gate at
  `build/measure-stage3-parent-local-draw-current-a976-safe14743-v1/summary.json`.
  This is not a full source-build replacement, a common-clock repair, fresh
  Stage-3 replay, usable-rate result, or full-playthrough claim.
- The current dirty source builds a different, rejected terminal-CCR image
  (`b7584c6fbac001dc3ec30e4684443c1965c122e50bbddc7b2e41fff8958caf57`);
  it is retained as `build/interp-2429c-tstb-ccr-candidate-b758.sfc` and is
  not the active ROM. It differs in 2,749 bytes over 322 diff runs from its
  predecessor and its fresh power-on replay observes only 10 requested game
  updates in 2,456 video frames before a hardware-boundary/timing failure
  (`build/fresh-candidate-2429c-tstb-ccr-b758-to3000-v2/summary.json`). It is
  not a source-rebuild substitute for this isolated repair.
- Unless a later paragraph names `a976…`, its `5c7e…` evidence is predecessor
  evidence. The Stage-3 IRQ/rate blocker now has the exact current-hash rerun
  above; other predecessor boss/crate/renderer evidence still does not transfer
  silently.
- An isolated renderer candidate, SHA-256
  `3b7000fcb56c77ec10bcd1fbfcbdf9ca7287129224b42d3ebbb8693c156933c4`,
  is retained as `build/interp-nmi-cache-reapply-candidate-3b7000.sfc`; it
  was **not** promoted over active `5c7e…`. It adds only an NMI-side reapply
  of the already accepted BG scroll registers after a completed renderer
  frame. In legacy Mesen, the supplied stale Stage-3 checkpoint begins with
  all 51 blue columns and `BG1HOFS=288`; after exactly one neutral vblank,
  both native-off and native-on clear the strip with no game-tick advance
  (`build/validate-stage3-scroll-nmi-cache-reapply-candidate-3b7000-v2/summary.json`).
  Its separate cold-boot one-credit legacy-Mesen run is green for the title
  artwork, transparent CREDIT text, lower-right area, credit count, and halt
  (`build/validate-fresh-one-credit-prompt-nmi-cache-reapply-candidate-3b7000-v1/summary.json`).
  This is a renderer/save-state repair candidate, not current-production,
  MAME-pixel, Nexen-checkpoint, Stage-3-rate, or organic-transition proof.
  Nexen cannot restore the legacy-Mesen `stage3.mss` as Stage 3 (the hardened
  probe rejects its tick-zero boot-screen result), and MAME has no serialized
  SNES PPU-register analogue; classify this narrowly as stale save-state
  renderer data rather than a 68000 gameplay discrepancy.
- The only executable payload differences from the prior `9dcc…` image are
  the ROM checksum/header and the disabled diagnostic `$F2:8000-$F2:8856`
  VTIME bank. The ordinary per-fetch legacy countdown seams are byte-checked
  at both bank-$00 mirrors, and the VTIME enable byte is zero. This structural
  check does not replace current-hash gameplay or three-way replay evidence.
- Fresh one-credit title/HUD checks are green on this exact hash in Nexen
  (`build/validate-fresh-one-credit-prompt-current-5c7e-nexen-v1/summary.json`)
  and legacy Mesen
  (`build/validate-fresh-one-credit-prompt-current-5c7e-mesen211-v1/summary.json`).
  They prove the artwork/HUD repair survives this rebuild, not a full campaign.
  A further fresh power-on Nexen replay after the focused VTIME tests is also
  green at
  `build/validate-fresh-one-credit-prompt-current-5c7e-esc9-post-v1/summary.json`:
  it uses one real Select edge and again records the intact right artwork,
  transparent CREDIT underlay, clean lower-right area, one credit, and no
  halt. It is renderer/HUD evidence only.
- A post-focused **fresh-power-on root** controller replay is green through
  MAME tick 10,000 at
  `build/fresh-campaign-current-5c7e-post-focused-to10000-v1`: no state load,
  ROM patch, or game-state write; 1,031 real transitions, 2,062 green player
  comparisons, five matched deaths, no halt/divergence, and action states
  0/1/2/3/4/5/7/8/9/10. It covers punch/charge, kick, flight, crate
  pickup/carry/throw, hurt, and respawn, but is not a boss, rate, or full-run
  claim.
- The authenticated fresh-power-on continuation is now green through MAME tick
  10,000 at `build/fresh-campaign-current-5c7e-resume10000-v2`: 2,062
  controller-boundary comparisons, five matched deaths, zero oracle
  divergences, zero halts, and action states 0/1/2/3/4/5/7/8/9/10 (walking,
  Button 1 punch/charge, Button 2 kick, Up flight, crate pickup/carry/throw,
  hurt, and death/respawn). It is bounded Stage-1/2 coverage; no organic boss
  fight, Stage-3 transition, timer recovery, rate proof, or full playthrough
  is claimed. Its post-entry safe checkpoint is retained at tick 10,000 for
  the next authenticated segment.
- The current-hash focused ordinary-enemy matrix is green 4/4 at
  `build/validate-gameplay-damage-current-5c7e-v1`: exact MAME,
  gameplay-native-off, and production-native-on agree for Button 1 punch
  (damage 1), Button 2 kick (damage 2), contact (damage 4), and charged
  projectile (damage 4), including the bounded register/CCR/X, stack, work-RAM
  and health-write comparisons. It is direct combat coverage, not a rate or
  whole-playthrough result.
- The current-hash boss matrix is green 118/118 at
  `build/validate-boss-health-current-5c7e-v1.json`: original MAME,
  gameplay-native-off, and production-native-on agree on each retained organic
  init/damage-handler case, including the full Stage-1/2/3 sequences: 40 HP /13
  hits, 40 HP / 37 hits, and 20 HP / 6 hits. Its IRQ-masked bounded cases do
  not claim a continuous fresh SNES boss encounter.
- The current-hash organic crate carry/throw differential is green at
  `build/validate-organic-crate-current-5c7e-v1/summary.json`, from the
  authenticated fresh-power-on tick-3,000 checkpoint (no ROM migration).
  Across all 87 real controller entries, MAME, gameplay-native-off, and
  production-native-on agree: carried contact causes zero enemy-health
  transitions; a Button 1 throw causes the same two one-point enemy-health
  transitions at ticks 3,274 and 3,283. The separate Up+Right flight-contact
  control is also green at
  `build/validate-organic-crate-flight-current-5c7e-v1/summary.json`: the
  MAME-confirmed carried-crate/enemy overlap, switch to Up+Right, and material
  ascent retain zero enemy-health transitions in all three configurations.
- The next fresh-lineage segment is green through tick 14,743 at
  `build/fresh-campaign-current-5c7e-resume14743-v1` (2,742 green player
  comparisons, zero divergences and halts), and retains the authenticated
  post-entry state immediately before the Stage-3 timing fault. The current
  exact MAME / gameplay-native-off / production-native-on gate is intentionally
  red at tick 14,746 in
  `build/validate-stage3-irq-order-current-5c7e-v1.json`: MAME task 15 saves
  `$0259B0` / `$0242BE`, SR `$2400`; both SNES configurations save
  `$02429C` / `$00044E`, SR `$2404`, then differ in collision/RNG state.
  A refreshed, read-only original-MAME-0.287 cold-boot trace of precisely
  ticks 14,744--14,747 is green at
  `build/validate-mame-stage3-irq-phase-current-5c7e-v1.json`: its level-6
  services are 139,302 / 139,296 / 139,342 MC68000 cycles apart and land at
  `$000818`, `$0259B0`, `$02582E`, `$000810`. In particular, the failing
  tick's arcade IRQ lands at `$02582E`, not at a fixed instruction count.
  This refresh is an oracle baseline, not a timing repair or rate result.
  The current-hash physical-delivery reproduction is independently and
  deterministically red at
  `build/capture-stage3-irq-delivery-current-5c7e-v3/summary.json`. It first
  proves a fresh Nexen process restored the full recorded public state and
  SA-1 IRAM sidecar with no architectural write, restores the checkpoint's
  recorded port-0 buttons, then stops at the third `$025110` entry and at
  `$00:B404`. MAME requires task 15 `$0259B0`/`$0242BE`/SR `$2400`; SNES still
  has `$02429C`/`$00044E`/SR `$2404` at logical `$0818`, with no published
  mid-call yield. This is a native-on physical-delivery forensic that
  corroborates, but does not replace, the fresh-lineage three-way gate.
  The authenticated active-ROM caller trace at
  `build/trace-stage3-ac94-callers-current-5c7e-v1/summary.json` observes all
  82 bank-$94 legacy-charge sites and shows that the red update adds 12 visits
  each to `$94:D548/$94:D567/$94:D586`, the three 3/2/5-instruction blocks of
  `$02E40E`. That is the first concrete variable-work trigger for the late
  IRQ, not a one-leaf repair: native-off has the same task-frame failure.
  `build/validate-stage3-ac94-variable-work-current-5c7e-v1.json` is the
  focused green reproducer for this red condition, not a timing-fix verdict.
  The matching MAME leaf ledger at
  `build/analyze-stage3-2e40e-cycles-current-5c7e-v1.json` measures 80 cycles
  for D0 byte below 7 and 94 otherwise; the red update has seven and fourteen
  of those paths. The authenticated native countdown trace confirms that each
  red-tick 3/2/5 block subtracts exactly those 3/2/5 legacy instruction units
  from `$AC`; `build/validate-stage3-ac94-countdown-current-5c7e-v1.json`
  guards that observed unit mismatch. It is component evidence for the
  required common clock, not a timer repair.
  A corrected campaign harness then continued the same authenticated lineage
  from its safe tick-14,743 checkpoint through tick 15,000 at
  `build/campaign-stage3-current-5c7e-continue15000-v2/summary.json`.
  The exact prefix ends at the already-retained tick-14,841 false respawn;
  after it, the run records 15 expected downstream player discrepancies (7
  input-boundary and 8 response-boundary) but no halt, invalid task stack, or
  renderer failure. Its tick-15,000 safe checkpoint is post-divergence
  organic-path evidence only, not a fresh-boot run, exact-state recovery,
  Stage-3 completion, boss proof, or rate result. The harness now has a
  focused continuation regression (`tools/test_campaign_oracle_continuation.py`)
  and admits only its named predecessor runner hash for this historical
  checkpoint; ROM, MAME, emulator, bridge, symbol, and all other runner-hash
  mismatches remain hard failures.
  A chained continuation from that checkpoint through tick 15,250 is likewise
  coverage-complete-with-oracle-divergences at
  `build/campaign-stage3-current-5c7e-continue15250-v1/summary.json`. It adds
  14 green player comparisons and no new discrepancy, halt, invalid stack, or
  renderer failure; its tick-15,250 checkpoint remains post-divergence
  liveness coverage only.
  The refreshed source audits remain promotion-blocking:
  `build/audit-vtime-legacy-ac-writers-current-5c7e-v6.json` has 11 unmigrated
  writers out of 26, and
  `build/audit-vtime-accelerated-boundaries-b758-v3.json` has 12 uncovered
  accelerated boundaries and 57 unadmitted live native labels after admitting
  the `$02429C` diagnostic ledger. The rejected `$074C` fallback is not part of
  current source.
  This confirms that a common path-sensitive MC68000 clock is still required.
  The later diagnostic-only `$0818` handoff experiments are all rejected
  before title: `$0734` alone activates too early, while `$0734` plus task-mask
  activation remains in the boot loop because the inactive VTIME path still
  pays per-fetch cross-bank overhead. A third local-prearm pack retains the
  ordinary fetch JSR and delays `$F2` calls until `$072E`, but is also red at
  frame 5,407 with zero task mask/credits; its state readback has VTIME
  magic/valid zero, proving the gate never opened and the remaining local
  top-of-iloop JSR/legacy branch still throttles self-test. See
  `build/validate-vtime-postboot-pacing-fresh-prompt-v1/summary.json` and
  `build/validate-vtime-taskmask-pacing-fresh-prompt-v2/summary.json`, plus
  `build/validate-vtime-local-prearm-fresh-prompt-v3/summary.json` and
  `build/probe-vtime-local-prearm-after5407-v3.json`.
  The restored production `5c7e…` bytes are guarded separately by
  `tools/test_vtime_paced_release_pack.py` and
  `tools/test_vtime_local_prearm_pack.py`; none changes its status or supplies
  timing acceptance.
  A fourth, choke-gated diagnostic finally clears the fresh-title throughput
  obstacle without adding timer traffic before the existing `$072E` gate. Its
  first image (`build/interp-vtime-choke-gateway-experiment-v6.sfc`,
  `d4bc57e6…`) reached the one-credit checkpoint with live VTIME state, but
  was red: a native or `$0818`-paced deadline left `VT_DUE=1` while the
  `$0818` self-refetch loop bypassed the fetch choke. The retained probe is
  `build/probe-vtime-choke-gateway-after5407-v6.json`. The corrected v7 image
  (`build/interp-vtime-choke-gateway-experiment-v7.sfc`, `b28f72c7…`) bridges
  each virtual due event into the existing one-countdown IRQ entrance, whose
  retained reload then clears the virtual due state. Its independent fresh
  one-credit title/HUD result is green at
  `build/validate-vtime-choke-gateway-fresh-prompt-v7/summary.json`; the
  next-frame checkpoint probe has live magic/valid, a changing remainder, and
  `VT_DUE=0` at
  `build/probe-vtime-choke-gateway-after5407-v7.json`. Exact pack regressions
  are `tools/test_vtime_choke_gateway_pack.py` and
  `tools/test_vtime_due_bridge_pack.py`; the synthetic bridge-through-reload
  regression is green at `build/validate-vtime-choke-due-bridge-v7/summary.json`
  and retains its forced prestate. This is only fresh diagnostic
  boot/title evidence: it does not establish a common native/HLE clock,
  correct IRQ cadence, Stage-3 recovery, rate, gameplay, or promotion.
  The current fresh continuation reproduces the downstream false respawn at
  tick 14,841 in `build/fresh-campaign-current-5c7e-resume14841-v1`: MAME is
  action 0, 4 HP, `(52,112)` while SNES is action 9, 20 HP, `(68,96)`.
  `states/retained-boundary-14839.mss` in that artifact is the deterministic
  pre-failure state. This remains a hardware-boundary/virtual-IRQ timing root;
  no source repair, usable Stage-3 rate, or Stage-3 completion is claimed.
- A separate post-focused **fresh-power-on root** replay independently repeats
  the downstream divergence at tick 14,841 in
  `build/fresh-campaign-current-5c7e-post-focused-to14841-v1`: 2,757 green
  and one red player comparisons, 12 matched deaths, no halt, no state load,
  and no ROM/game-state mutation. Its atomic forensic `states/failure.mss`
  (SHA-256 `85664aaa…`) records MAME action 0, 4 HP, `(52,112)` against SNES
  action 9, 20 HP, `(68,96)`. This direct fresh result eliminates stale state;
  the exact MAME/native-off/native-on task-frame probe at tick 14,746 remains
  the root-cause classification authority.
- The targeted authenticated continuation from the fresh root's safe tick-10,000
  boundary now reproduces that same red result at
  `build/reproduce-current-5c7e-14841-preinput-v2`.  It retains the exact
  pre-input tick-14,839 state at `states/pre-failure-input.mss` (SHA-256
  `1c4a5cec…`) before the neutral edge, plus the post-failure state.  This
  satisfies the deterministic pre-failure-state requirement without treating
  the continuation itself as fresh-boot or rate proof.
- Exact-Nexen stop-by-stop attribution from the same current-hash tick-14,743
  state is retained at
  `build/profile-stage3-tick-current-5c7e-safe14743-v1/profile.json`: one
  update took 1,938,567 SA-1 cycles, 11 video frames, and 310 genuine
  interpreter fetches. The native `$02429C` fusion and `$025110` collision
  guard fired, but this perturbed checkpoint profile is hotspot evidence only,
  not uninterrupted fps or fresh-boot rate proof. It confirms the 358K
  cycles/tick target is substantially missed.
- A paired neutral-input Nexen checkpoint measurement removes all execution
  hooks at
  `build/measure-stage3-current-5c7e-safe14743-nohooks-v2/summary.json`.
  From the authenticated fresh-lineage tick-14,743 state, native-off needs
  13,802,658 SA-1 cycles and 77 video frames for one tick; native-on needs
  14,091,718 cycles for five ticks (2,818,343.6 cycles/tick and 15.8 video
  frames/tick). That is a bounded 4.90× native speedup, but native-on remains
  far above the 358K budget. With hooks deliberately absent, this is no-halt
  liveness/cadence evidence only—not route coverage, fps, fresh-boot rate, or
  a same-tick gameplay differential.
- A rejected `$027952→$02E524` local-native candidate is retained as negative
  evidence, not a production change. Its candidate hash `8a4e8aed…` passes
  the exact MAME/native-off/native-on `$027952` differential (12 semantic
  cases plus two route probes) at
  `build/validate-stage3-27952-local-2e524-current-8a4e8ae-v1.jsonl`, and an
  isolated gate probe reaches `$9D:E190`. But the current tick-14,743 state
  records zero visits to that private bridge across frames 50,676–50,688 at
  `build/profile-stage3-27952-local-2e524-current-8a4e8ae-v2/results.json`.
  It therefore cannot explain or repair the measured current slowdown; the
  source and active ROM retain the original route.
- A separate non-pausing Nexen CE4 renderer attribution over the next two
  current-lineage update spans is green at
  `build/profile-stage3-ce4-current-5c7e-safe14743-v1.json`. It finds 16 CE4
  calls/update and 66,386.5 CE4 SA-1 cycles/update (12 fast 2×2 calls account
  for 27,060; generic hot calls 36,495.5), against a 3,303,291.5-cycle mean
  for the hooked checkpoint spans. It is not an fps measurement and crosses
  the known timing-failure window, but it rules out CE4 alone as the primary
  rate blocker; no renderer speedup was applied on that basis.
- The focused `$92:FB00-$92:FC9F` switch-in body span is also bounded at
  `build/profile-stage3-swin-span-current-5c7e-safe14743-v2/results.json`:
  94 complete calls across eight checkpointed updates average 715.35 SA-1
  cycles/call (8,405.375 cycles/update). It excludes fast RTE, switch-out, and
  select paths and crosses the known bad boundary, so it is neither rate nor
  scheduler-correctness proof; it only rules out this one body as the dominant
  raw cycle consumer.
- The complete native `$02429C → $0242BE` bridge, including its nested
  `$025110` collision call, is separately measured at
  `build/profile-stage3-2429c-pre25110-span-current-5c7e-safe14743-v1/results.json`:
  eight checkpointed calls across eight updates average 97,734.125 SA-1
  cycles. It ends before `$0242BE` continuation work and crosses the known bad
  boundary, so it is only hotspot attribution; it rules out treating that one
  bridge or `$025110` alone as the Stage-3 rate explanation.
- The current-ROM all-entry trace at
  `build/trace-stage3-active-native-current-5c7e-safe14743-v1.json/trace.json`
  records 65 active entry-labelled native seams and 279 hits in one update,
  including callable entries as well as continuation/end seams for the six
  player bodies, `$025110`, CE4, task switch-in/out, `$02429C`, and multiple
  object/callback bridges. The new coverage gate
  `build/audit-stage3-vtime-coverage-current-5c7e-v1.json` is green only in
  the sense that it proves promotion must remain blocked: the existing
  `$025110` ledger leaves all six player handlers, CE4, `$02429C`, and the
  task-switch paths uncharged. `tools/test_stage3_vtime_coverage.py` guards
  that conclusion. This supersedes the narrower active-path inventory; no
  partial VTIME build is a timing fix.
- The companion current-source boundary inventory,
  `build/audit-vtime-accelerated-boundaries-current-5c7e-v3.json`, keeps the
  bootstrap loop collapses, scheduler scan/switch/select shortcuts, `$0818`
  idle pacing, `$02429C`, and CE4 explicit alongside the selected `$025110`
  and six-player ledgers. It is green only because it finds 13 still-uncovered
  boundaries and blocks promotion. Of the same trace's 65 active entry labels,
  58 are not yet admitted to a selected ledger and require route proof before
  they can be considered covered; this does not assert that every one is
  uncharged. The selected ledgers are not a common clock.
  `tools/test_vtime_accelerated_boundaries.py` guards that negative result.
- The matching static charge-helper audit at
  `build/audit-stage3-native-charge-helpers-current-5c7e-v2.json` confirms
  why a simple conversion of the existing `$025110` helper is insufficient.
  The traced update reaches entry-labelled seams in banks
  `$92/$94/$97/$98/$99/$9F`; `$92` (100 seam hits), `$98` (one), and `$99`
  (13) have no direct legacy per-block charge
  helper at all, while `$94/$97/$9F` use distinct helper conventions. The
  audit and `tools/test_native_charge_helpers.py` are planning regressions,
  not an assertion that every helper call is reachable or cycle-correct.
- A checkpoint trace now rejects an attempted post-load native-gate mutation
  while the serialized SA-1 PC is in an escape bank. The retained Stage-3
  checkpoint resumes at `$92:DB8C` (inside the native game-tick handler), as
  recorded in
  `build/trace-stage3-gameplay-native-off-current-5c7e-safe14743-v2-rejected/rejected-gate-mutation.json`.
  Consequently, clearing `$071A/$073A` after loading that ordinary state is
  not native-off evidence; a valid native-off checkpoint must be configured
  before its capture. This guard does not alter the separately prepared
  native-off artifacts used by the existing three-way IRQ/combat fixtures.
- The Stage-3 player route proof was corrected before accepting it as native
  evidence. These six leaves are reached through the BSR gateway, not the
  ordinary `$00:D1B3` table-dispatch path. The direct-table harness now
  refuses them; `tools/validate_stage3_player_bsr.py` reconstructs the real
  pre-BSR state and proves the production route. On this exact ROM,
  `build/validate-stage3-13282-bsr-current-5c7e-v3.json` is green for six
  `$013282` cases plus its `$9F:E000` entry probe;
  `build/validate-stage3-13314-bsr-current-5c7e-v2.json` and
  `build/validate-stage3-1337e-bsr-current-5c7e-v2.json` are each green for
  their retained case and `$9F:D800`/`$9F:BA00` route probe; and
  `build/validate-stage3-player-bsr-current-5c7e-v2.json` is green for 18
  retained `$0133EA`/`$013468`/`$013538` cases and their
  `$9F:EC00`/`$9F:F100`/`$9F:F700` probes. Across the 26 exact MAME,
  native-off, native-on semantic comparisons and six true-route probes,
  registers, CCR/X, stack, mapped work RAM, upper backing, and AC agree.
  This replaces a false direct-dispatch route assertion; it is bounded
  handler/route evidence, not virtual-IRQ, rate, or playthrough proof.
- A new narrow `$027952→$027AEA` bridge candidate is retained but **not
  promoted**. `build/interp-stage3-27952-direct-27aea-current-5c7e-v1.sfc`
  (`23268b5d…`) is the active `5c7e…` image with only the verified three-byte
  `$94:B61A` JML operand changed from the generic dispatcher to the existing
  guarded `$9F:C000` child. Exact MAME 0.287 / native-off / native-on
  parent-body comparisons are green for all 12 retained `$027952` states at
  `build/stage3-27952-direct-27aea-current-5c7e-isolated-v2.jsonl`: D/A,
  CCR/X, real stack/return, mapped work RAM, upper backing, and AC agree.
  The native-on half deliberately enters the assembled parent directly for
  bounded semantics; its separate exact-Nexen neutral-input route probe from
  the same-hash tick-14,743 state has zero `$9F:C000` hits with escapes off
  and 36 with them on (`build/stage3-27952-direct-27aea-current-5c7e-route-v2`
  plus `build/stage3-27952-direct-27aea-current-5c7e-route-on-v1`). The
  source-owned generator rule and packed-byte assertion are covered by
  `tools/test_stage3_27952_child_bridge.py`; a normal source build is
  `18bbee7f…` and also passes that assertion. This is a local semantic/route
  candidate, not a common-clock repair, rate result, Stage-3
  recovery, or production-ROM promotion.
  Its subsequent fresh-power-on native-on controller replay to MAME tick
  3,000 is retained at
  `build/fresh-candidate-27952-direct-27aea-to3000-v1`: it has real title,
  credit, start, and gameplay-origin states, 168/168 green player comparisons,
  one matching death/respawn, no oracle divergence or halt, and a valid
  safe checkpoint. Its overall result is correctly red only because this
  shortened segment lacks action states 3/4/5/7/10; it is not a gameplay
  discrepancy, a Stage-3 run, or a promotion result.
  The rebase of that candidate onto active `a976…` is
  `build/interp-stage3-27952-direct-27aea-current-a976-v1.sfc`
  (`43ee45ee…`), still **not promoted**. Its checksummed byte builder changes
  only the JML's three-byte destination operand. The new exact MAME/native-off/
  native-on run is green 14/14 (12 semantic cases and two dispatcher probes)
  at `build/validate-stage3-27952-direct-27aea-current-a976-isolated-v1.jsonl`,
  and its distinct fresh-power-on replay through tick 10,000 is green with
  2,062 player comparisons, ten death/respawn comparisons, all retained action
  states, no divergence, and no halt at
  `build/fresh-candidate-27952-direct-27aea-current-a976-to10000-v1`.
  Its separate fresh one-credit artwork/HUD gate is also green at
  `build/validate-fresh-one-credit-prompt-stage3-27952-current-a976-v1/summary.json`.
  Its safe-state rate probe remains red at 2,375,601.72 native-on cycles/tick
  (`build/measure-stage3-27952-direct-27aea-current-a976-safe14743-v1/summary.json`).
  Because that probe's command wall-time guard returned different actual video
  spans than the active-`a976…` control, it is liveness/budget-miss evidence,
  not a cross-ROM speed measurement. `tools/test_stage3_27952_current_a976_evidence.py`
  prevents those limits from being silently upgraded into a promotion claim.
  A follow-up no-hook exact-Nexen checkpoint comparison now establishes that
  the route does remove real work, but is still not a usable-rate fix. The
  active ROM completes three ticks in the retained 90-frame neutral window at
  3,468,814 SA-1 cycles/tick
  (`build/measure-stage3-current-5c7e-safe14743-onechunk-nohooks-v5/summary.json`);
  the three-byte operand candidate completes four at 2,669,361.75 cycles/tick
  (`build/measure-stage3-27952-direct-27aea-current-5c7e-safe14743-onechunk-nohooks-v2/summary.json`).
  That is a 23.0% local native-on reduction, but remains 7.46× the 358K
  budget. The harness now identifies the safe Nexen executable correctly and
  records neutral MCP input, state hashes, and no hooks. It intentionally does
  not compare end RAM across unequal tick counts, establish fps, prove a
  fresh boot, recover tick 14,746 virtual-IRQ order, or authorize promotion.
- The `$02E42C` Stage-3 selector is a separate real-call case, not an OJMP or
  BSR leaf. Its two PC-relative JSR callers are `$0278E2→$0278E6` and
  `$02F2DA→$02F2DE`; they have different callback A0/continuation state.
  `tools/validate_stage3_player_bsr.py` now derives the exact pre-call state
  from the stacked return rather than forcing every fixture through the first
  caller. `build/validate-stage3-2e42c-real-jsrpc-current-5c7e-v4.json` is
  green for all six retained states plus the natural `$9F:A140` route probe in
  original MAME 0.287, native-off, and native-on. It preserves D/A, CCR/X,
  stack/return, mapped work RAM, upper backing, and AC; it is local handler
  proof only and does not alter the tick-14,746 timing or rate blockers.
- The dirty source also has an **unaccepted VTIME=1 diagnostic extension** for
  the six active Stage-3 player handlers. Its retained image is
  `build/interp-vtime-current-5c7e-esc9-ledger-v2.sfc`, SHA-256
  `68c9bccc94ed79be173bfc342fa4f7b5f6583199e8484997fef620a83ff82175`.
  It source-checks and routes 83 generated player blocks plus 15 call/return
  handoff tails through a separate owner-tagged ledger. Fresh 24-frame
  diagnostic liveness is green at
  `build/validate-vtime-esc9-ledger-liveness-v2/summary.json`; the synthetic
  first-block deadline unwind is green at
  `build/validate-vtime-esc9-ledger-due-v5/summary.json`; and the synthetic
  shared exit-gateway deadline path is green at
  `build/validate-vtime-esc9-finish-gateway-v1/summary.json`. These do not
  establish organic handoff reachability, a common native/HLE clock, the
  tick-14,746 repair, Stage-3 rate, fresh gameplay, or acceptance. In
  particular, none of six retained `$013282` cases reached the OJMP handoff
  in the bounded actual-route probe; that negative coverage result is retained
  rather than converted into a timing claim. The profile-aware coverage audit
  `build/audit-stage3-vtime-coverage-player-ledger-current-5c7e-v1.json`
  confirms that this diagnostic covers `$025110` and the six player leaves but
  still leaves `$02429C`, CE4, and task switch-in/out uncovered; it is green
  only because promotion remains blocked.
- That same `68c9…` VTIME diagnostic fails a longer fresh native-off boot/coin
  probe at `build/validate-vtime-esc9-nativeoff-fresh3000-v1/summary.json`:
  after the ordinary 5,248-frame wait and eight real Select pulses it remains
  on the SA-1 boot screen with zero credits, although halt remains zero. This
  is retained VTIME hardware-boundary/timing-or-boot-alignment evidence, not
  a production-ROM or gameplay claim. It makes the short liveness check
  insufficient for promotion and rejects the diagnostic clock until boot
  behavior is explained and fixed.
- The matched fresh native-on VTIME controller run is red at
  `build/validate-vtime-esc9-nativeon-fresh3000-v1/summary.json`: it reaches
  the same 5,248-frame boot-screen/zero-credit failure and has the identical
  failure PNG SHA-256 as native-off, while the states remain distinct because
  their gate configuration is retained. In a freshly launched exact MAME 0.287
  session, the boot-aware one-credit controller path reaches gameplay at
  reported frame 1,952; its state is retained at
  `build/mame-vtime-boot-oracle-v1/states/superman/fresh-original-booted-before-vtime-comparison.sta`.
  No MAME/SNES gameplay register comparison is possible for this diagnostic
  failure because neither VTIME configuration reaches gameplay.
- The current-source chunked fresh VTIME timer probe is green only for timer
  liveness, not boot readiness:
  `build/probe-vtime-esc9-boot-clock-v4/summary.json` advances 5,248 real
  video frames and retires 862,681 interpreter instructions without a halt,
  but phase 50→2,700 records only 53 observed virtual deadlines and virtual PC
  remains in the boot RAM test (`$003F7C→$003FEE`). The native-off/native-on
  retained-state probes agree at `$003FF6→$003FEE`, opcode `$66F6`,
  `$00AC=$7000`, `$00AA=1`, no game tick, and no active native ledger
  (`build/probe-vtime-esc9-nativeoff-boot-failure-v1.json`,
  `build/probe-vtime-esc9-nativeon-boot-failure-v1.json`). This classifies the
  diagnostic as a hardware-rate/common-clock failure, not missing timer
  initialization, an interpreter-only opcode defect, or a native-only escape
  defect. It remains rejected and has not changed `build/interp.sfc`.
- The later explicit interpreter-only VTIME flag image
  (`build/interp-vtime-interpreter-only-escapes-off-diagnostic-v1.sfc`,
  `0ee4e331…`) is also rejected. Its fresh, neutral, one-frame-request probe
  is intentionally **inconclusive** at the 180-second host budget:
  `build/validate-vtime-interpreter-only-liveness-5500-framewise-v3/summary.json`
  advances emulator frame 137→3,173 and reaches interpreter step 785,106
  without a halt, but remains at boot PC `$003FFA`, game tick zero, and VTIME
  magic/valid zero. `$071A/$073A` are clear at power-on, so that observation
  does not prove the deferred post-task interpreter-only switch executed.
  The retained save and ``ARCADE BOOT IN PROGRESS`` screenshot are diagnostic
  artifacts only, not a fresh-gameplay, MAME differential, rate, or Stage-3
  result. Framewise MCP progress is now atomically retained between requests
  so a slow diagnostic cannot masquerade as a lost endpoint.
- The live Stage-3 `$02429C` coroutine root is now reduced in the read-only
  future-ledger audit
  `build/audit-stage3-2429c-charge-blocks-current-5c7e-v4.json`: 78 original
  instructions form 35 basic blocks with 520 static two-cycle units counted
  once; all 14 path-sensitive instructions are terminal Bcc/DBcc. The focused
  regression `tools/test_stage3_2429c_charge_blocks.py` is green. Its
  eleven JSR/BSR/indirect child handoff sites remain unadmitted; the eight
  direct children include non-terminal MOVEM and immediate-shift work beyond
  the existing `$025110` ledger; its 11 call sites classify to five native,
  five interpreter, and one dynamic-indirect route. This is neither an
  enabled VTIME seam nor a Stage-3 IRQ/rate repair.
- The new emitted-source `$02429C` handoff audit at
  `build/audit-stage3-2429c-handoff-protocol-current-5c7e-v1.json` is green
  only as an ownership blocker: the root has no local timing charge, a guarded
  fast arm represents three original native callees, and the remaining emitted
  sites are four direct-native plus six OJMP child transfers. All ten bypass a
  parent-owner flush today. `tools/test_stage3_2429c_handoff_protocol.py`
  pins the existing return protocols; a root timer cannot be wired until every
  transfer and the fused triple has an exact successor/return policy. It is
  not a common-clock, IRQ, rate, or fresh-gameplay result.
- `build/gen-vtime-esc5-charge-table-current-5c7e-v1.json` now retains the
  unconsumed 35-block `$02429C` ordinal metadata (cost, start PC, terminal
  opcode, and 14 dynamic-terminal ordinals), guarded by
  `tools/test_vtime_esc5_charge_table.py`. There is intentionally no native
  return index or packed reader because the root has no charge seam. It is
  preparation for, not proof of, a native timing implementation.
- The guarded three-callee `$02429C` fusion has exact-MAME bounded timing at
  `build/validate-mame-2429c-empty-fusion-current-f369-v1.json`: all four
  retained canonical paths cost 798 cycles/33 instructions from `$023342` to
  `$0242B2`. `tools/test_mame_2429c_empty_fusion.py` requires a future opaque
  fast arm to fall back before `$023342` if 399 two-cycle units could cross a
  deadline. It does not validate a fusion implementation or nonempty path.
- The exact-MAME direct-child timing subset is green at
  `build/validate-mame-2429c-native-child-timing-current-f369-v1.json`:
  124 observed child dynamic instructions (24 MOVEM.L, 56 Bcc, 44 DBcc) match
  with no errors. Four unobserved dynamic PCs remain explicit coverage gaps,
  and `tools/test_mame_2429c_native_child_timing.py` guards that bounded
  result. It is MAME ledger input only—not validation of the fusion, a native
  root ledger, timing repair, or rate.
- A wider, uninterrupted power-on original-MAME 0.287 capture through ticks
  14,720--14,860 now strengthens that negative coverage without closing it:
  `build/mame-2429c-irq-phase-current-f369-wide-v1/summary.json` has 70,436
  read-only trace events and 141 `$02429C` entries. All 4,371 observed native
  child dynamic instructions and all observed root branches remain exact, but
  the same four child PCs (`$02360C/$023618/$023660/$025A0E`) and ten root
  dynamic PCs are absent. `tools/test_mame_2429c_wide_coverage.py` pins both
  the original-oracle identity and those gaps. This proves the current movie's
  repeated arm does not cover a full root ledger; it is not a SNES comparison,
  a native promotion, an IRQ repair, or a Stage-3 rate result.
- Original MAME alone was then continued through ticks 14,861--15,000 in
  `build/mame-2429c-irq-phase-current-f369-postdivergence-v1/summary.json`.
  Its 56,179 read-only events add 140 more root visits and 4,340 exact child
  timing records, yet execute the identical observed subset and leave all 14
  gaps intact. This confirms that simply replaying farther on this controller
  route will not produce the targeted arm fixtures. It is explicitly
  post-SNES-divergence MAME oracle evidence only—not a three-way continuation,
  Stage-3 completion, rate result, or full playthrough claim.
- A narrowed exact-MAME `$02429C` branch reducer is green at
  `build/validate-mame-2429c-branch-timing-current-f369-v2.json`: 48 observed
  executions at `$0242A2/$0242C8/$0242E6/$0243E0` match the predicted
  10/12/14-cycle Bcc/DBcc outcomes. Ten other dynamic root PCs are absent from
  the retained trace, so this is a bounded oracle input—not complete root,
  child, SNES, timing-repair, or rate coverage.
- A current-hash, fresh-lineage checkpoint differential now independently
  proves `$02429C` function semantics at
  `build/validate-2429c-current-5c7e-live-v1.jsonl`. It organically captures
  three entries at ticks 14,741--14,743 from the authenticated fresh run, then
  compares original MAME 0.287 with native gates `(0,0)` and production
  `(1,1)` (plus the retained `(1,0)` route). All 9 cases agree in D/A, CCR,
  interrupt mask, mapped work RAM, and the audited stack/return residues;
  `$0242BE` retains its exact logical collision return. The probe deliberately
  masks IRQ6 and sets a no-deadline counter, so it validates handler semantics
  and handoff residue only—not the live IRQ phase, fresh-boot Stage 3, rate,
  or the common-clock repair.
- The reusable `$02429C` three-way fixture runner now rejects the mutable
  `/snap/bin/mame` launcher (currently 0.289) and requires the pinned 0.287
  payload identity before producing new evidence. Its source guard is
  `tools/test_validate_2429c_mame_oracle.py`. This corrects the validation
  boundary only; no older fixture is silently promoted and it is not a timing
  or gameplay repair.
- The terminal-CCR defect is now active only through the isolated `a976…`
  patch described above. The full dirty-source `b758…` image remains rejected;
  its focused checks are source/packing provenance, not promotion evidence.
  The apparent three stack-byte difference in the scan arm is correctly
  classified as `$0259FC → $99:97FD` private continuation residue, not a
  work-RAM discrepancy. `tools/test_2429c_tstb_ccr_regression.py` now guards
  both the source/packing seams and the isolated exact 9/9, fresh 10,000-tick,
  and fresh one-credit results. Neither repair changes the common virtual
  clock, establishes Stage-3 rate, or completes a playthrough.
- The opt-in VTIME source now packs an **unwired** `$F2:FE40` native-parent to
  interpreter-child deferred-block flush helper. It dispatches only the
  already-selected `$025110` or player owner, fails closed on an unknown owner,
  and leaves post-transfer PC/stack and actual route wiring to its future
  caller. `tools/test_vtime_native_handoff.py` checks the assembled helper and
  long BW-RAM stores; its first diagnostic image is
  `build/interp-vtime-native-handoff-diagnostic-v1.sfc` (SHA-256
  `ace8098e…`). This is neither enabled nor exercised, so it provides no
  common-clock, IRQ-order, Stage-3-rate, or fresh-gameplay proof. The active
  ROM is still `5c7e…`.
- Its 24-frame fresh power-on smoke is intentionally red at
  `build/validate-vtime-native-handoff-liveness-v1/summary.json`: VTIME has
  not reached its post-self-test arm, so magic/valid are zero. It records 5,605
  interpreter steps and no halt, but tests neither the unwired helper nor boot
  readiness and is not liveness or gameplay evidence.
- The unwired helper's synthetic Nexen execution is green at
  `build/validate-vtime-native-handoff-runtime-v1/summary.json`: owner-3 and
  owner-9 deferred blocks debit 14 and 10 two-cycle units respectively, clear
  their owner state, and an unknown owner invalidates VTIME and returns through
  a retained temporary interpreter-loop RTL target. The artifact guard is
  `tools/test_validate_vtime_native_handoff_runtime.py`. This is isolated
  helper behavior only; it does not prove an organic route, MAME parity, IRQ
  order, rate, or gameplay.
- A separate `VTIME=1 VTIME_INTERPRETER_ONLY=1` image incorporating that
  unwired helper is rejected by a full fresh power-on, one-real-Select probe:
  `build/interp-vtime-interpreter-only-native-handoff-v1.sfc` (SHA-256
  `598f0acc…`) reaches a nonzero task mask with no halt, but at frame 5,407
  `$F01C62` is still zero after the credit edge. Its right-wedge, CREDIT
  underlay, and lower-right pixel predicates are all red (775 black wedge
  pixels, zero required artwork-gray pixels, and 156 lower-right nonblack
  pixels) in
  `build/validate-vtime-interpreter-only-native-handoff-fresh-prompt-v1/summary.json`.
  The probe has no state load or runtime game-memory write and retains its
  nonresumable forensic state; `tools/test_vtime_interpreter_only_native_handoff_prompt.py`
  pins this rejection. This is a VTIME candidate failure, not a regression in
  the restored active `5c7e…` renderer/HUD evidence, and it never reaches a
  MAME-comparable gameplay state. It therefore adds no native-off/native-on,
  IRQ, Stage-3, rate, or common-clock proof.
- `build/audit-vtime-legacy-ac-writers-current-5c7e-v5.json` updates the
  static source boundary after the choke-gateway repair: the current diagnostic
  source has 26 direct legacy `$AC` writers, still with 11 explicitly
  unmigrated (nine native-charge, CE4 residue, and one `$0818` idle-scheduler
  writer). The added two writes are deliberate one-countdown virtual-due
  delivery bridges; three are diagnostic countdown quarantines and three are
  disabled-mode compatibility. Only selected `$025110`, player, and diagnostic
  `$0818`-release seams are intercepted. `tools/test_vtime_legacy_ac_writers.py`
  guards this inventory; its green result means the common-clock promotion is
  correctly blocked, not that the timer is repaired.
- `9dcc…`, `f369e327…`, and lower reports explicitly naming either remain
  predecessor evidence until their relevant current-hash focused replays are
  repeated.
- the preserved `build/playtest/superman-snes-v135-5aac64b6.sfc` is an older
  `5aac64b6…` artifact and is not evidence for the active image.

## Superseding 9dcc campaign evidence

The `9dcc…` campaign evidence below remains the most complete bounded
gameplay/IRQ record, but it is not silently promoted to `5c7e…`. The rebuild
fixes a VTIME-diagnostic BW-RAM addressing defect while VTIME remains disabled
in the ordinary image; `tools/test_vtime_disabled_pack.py` proves that normal
image takes the legacy countdown path. The new opt-in diagnostic reaches real
deadline reload in
`build/validate-vtime-stage3-9dcc-experiment-liveness-v3/summary.json`, but
the required common native/HLE clock, Stage-3 three-way recovery, rate proof,
and current-hash organic replay are still open.

The VTIME diagnostic build route is executable again: its mode-specific pack
guard permits `VTIME=1` while retaining the normal disabled-pack assertion for
ordinary builds. Earlier diagnostic artifact
`build/interp-vtime-current-5c7e-diagnostic-v3.sfc` (`b55274a8…`) is retained
historically. The later player-ledger diagnostic is `68c9…` above. The active
ordinary file is the restored `5c7e…` artifact; a later normal build from the
now-dirty source is `18bbee7f…`, so byte identity must not be claimed. A
production checkpoint cannot be treated as a valid diagnostic ROM state, so no
migrated-state result is claimed.

The current ROM repairs the CE58-to-D18A virtual-return convention: the CE58
bridge now enters the normal D18A entry, which supplies the return frame used
by the relocated cleanup tail. The source-overlap repair and route convention
are green in `build/validate-d18a-current-9dcc-v1.json` (12/12) and
`build/validate-13be-sentinel-route-current-9dcc-v1.json` (44/44). The
pre-repair fresh run and its retained failure state are forensic evidence only.

Fresh power-on proof is green at
`build/validate-fresh-one-credit-prompt-current-9dcc-nexen-v2/summary.json`: one
real credit has an intact right artwork wedge, transparent CREDIT underlay,
no lower-right status garbage, and halt zero. The separate fresh campaign
`build/fresh-campaign-current-9dcc-safe3000-v1/summary.json` starts from
power-on with `TESTFLAG=0` and reaches MAME tick 3,000 with zero player-oracle
mismatches and no halt. Its terminal is red only because that short movie does
not exercise every requested action class; it is not a full playthrough.
The independent legacy-Mesen fresh-boot rerun is also green at
`build/validate-fresh-one-credit-prompt-current-9dcc-mesen211-v5/summary.json`.
Mesen's native capture is 256x224 rather than Nexen's 256x239, and its
emulator-specific expected geometry is recorded in that report; the same
artwork, underlay, credit, task-mask, and halt checks pass. This is renderer/HUD
cross-emulator evidence only, not a gameplay or rate result.

The same authenticated fresh lineage was continued through MAME tick 10,000
at `build/fresh-campaign-current-9dcc-coverfix-resume10000-v1`: 1,031 real
controller transitions, five matched deaths, no player-oracle divergence, and
no SA-1 halt. It observes walking, Button 1 punch/charge, Button 2 kick, Up
flight, crate pickup/carry/throw, hurt, death/respawn, and action states
0/1/2/3/4/5/7/8/9/10. It reaches neither an organic boss fight nor a Stage-3
transition, so it is bounded fresh-lineage coverage rather than a playthrough.

The continued controller replay is deterministically red at MAME tick 14,841
(`build/fresh-campaign-current-9dcc-coverfix-resume18000-v1`): the retained
pre-input state
`build/reproduce-fresh-14841-current-9dcc-v1/states/pre-failure-input.mss`
(SHA-256 `7c12101135dacd2bb0467a255f1717d2ada53cd60dd0034bf07b7e223ad63e77`)
reproduces it. At boundary 14,839 original MAME retains collision response
`$F03A02=$0000` and a live 4-health player. Both SNES gameplay-native-off and
production-native-on instead have `$F03A02=$80F0`; at 14,840 both respawn the
player (action 9, health 20, x=68, y=96), while MAME remains action 0, health
4, x=52, y=112. The focused three-way regression
`build/validate-stage3-false-hit-chain-current-9dcc-v1.json` is intentionally
red and retains this exact chain. Temporarily routing `$025110` through its
interpreter fallback still produces the marker, so `$025110` is a correct
consumer of already shifted collision geometry, not the root native escape.
The earlier authenticated task-15 gate at MAME tick 14,746 remains the
upstream root: both SNES configurations deliver the virtual IRQ after the
arcade's `$0259B0` task frame. This is a hardware-boundary/virtual-IRQ timing
failure, not stale save-state data, HUD rendering, or a native-only collision
defect. No production timing repair has landed.

The predecessor-ROM four-boundary task-frame gate is retained at
`build/validate-stage3-irq-order-current-9dcc-v2.json`. It uses the same
authenticated safe checkpoint for production-native-on and gameplay-native-off
and exact original-code MAME captures. All three agree in the checked gameplay
regions and task-15 frame at ticks 14,744--14,745. At 14,746 MAME saves task 15
at `$0259B0` with return `$0242BE` and SR `$2400`; both SNES configurations
instead retain the identical `$02429C`/`$00044E` frame with SR `$2404`. The
following tick has the corresponding collision-table and RNG differences. This
is a predecessor-hash scheduler/timing regression, not a fresh-boot
completion, rate, or renderer result for `5c7e…`.

Predecessor focused gameplay evidence is green, but bounded:

- `build/validate-gameplay-damage-current-9dcc-v1` is 4/4 MAME/native-off/
  native-on for punch (1), Button 2 kick (2), contact (4), and charged
  projectile (4) damage, with register, CCR/X, stack, mapped-RAM, and health
  checks.
- `build/validate-boss-health-current-9dcc-v3.json` is 118/118 on the actual
  ordinary ROM using a reversible terminal trap. Boss health/hit sequences are
  Stage 1 40/13, Stage 2 40/37, and Stage 3 20/6. This is not an organic boss
  battle.
- `build/validate-organic-crate-current-9dcc-v1/summary.json` proves held
  contact is nondamaging and legitimate throws damage as in MAME. The separate
  `build/validate-organic-crate-flight-current-9dcc-v3/summary.json` routes
  Down+Right into the original 17-boundary crate/enemy overlap, then holds
  Up+Right through contact and a 112-pixel ascent. MAME, native-off, and
  native-on are green: a carried crate writes no enemy health. This replaces
  the reported carry/flight kill symptom for the tested organic route.

The supplied Stage-3 checkpoint's blue strip remains classified as stale
save-state renderer/scroll data, not a fresh-ROM repair. Its final-hash
Mesen check, `build/validate-stage3-scroll-input-current-9dcc-v1/summary.json`,
starts from the same 51 blue columns and stale hscroll 288 and clears after
60 Right plus 60 neutral frames in both modes. It advances only 2 native-off
or 11 native-on game ticks in that 120-frame window, so it is further
checkpoint-only evidence that the reported Stage-3 pace is unusable—not an
fps claim or a fresh transition. No `9dcc…` fresh Stage-3 transition has
completed. The final-hash short checkpoint rate probe is explicitly red at
2,322,889.5 SA-1 cycles/native-on tick
(`build/measure-stage3-current-9dcc-v1/summary.json`), far beyond the 358K
gate; native-off completed no tick in its bounded window. It is not fps or
fresh-entry proof, but it establishes that the usability blocker remains.
Stage-3 timing/performance, renderer
conservation through organic entry, organic boss battles/transitions, and a
full fresh-boot playthrough remain release blockers. Do not infer a fresh
Stage-3 result from the old checkpoint or a full-game result from the bounded
matrices above.

The uncommitted VTIME diagnostic is not a production candidate. Its current
retained opt-in image is
`build/interp-vtime-native-ledger-diagnostic-v2.sfc`, SHA-256
`590f1dfba2b1969be538439371cccf1556510ba8b24ae443d81c9c3ae8c8aff3`.
The 12-frame fresh neutral liveness/ownership probe is green at
`build/validate-vtime-native-ledger-liveness-v2/summary.json`, including the
new native-ledger workspace fields. The normal ROM pack has no VTIME runtime
traffic: byte-asserted packing restores the legacy `LDA/DEC/STA $AC` sequence
in both bank-$00 views and the legacy debug gateway unless `VTIME=1`; that
switch alone patches the three bank-$97 collision gateways. A fresh one-credit
run of the repaired ordinary dirty image (`8b9adc92…`) is green at
`build/validate-fresh-one-credit-prompt-vtime-default-8b9a-v1/summary.json`.
It records an intact right artwork wedge, transparent credit underlay, clean
lower-right area, one credit, and halt zero. The preceding `cd4a6a93…` pack is
retained red: although its helper took the legacy branch, it left a JSL/RTL on
every interpreted instruction and did not reach the prompt by frame 5,407.
This is a packing-overhead regression and its focused fresh-boot fix, not a
promotion of the dirty image or a VTIME acceptance result.

A current-source `VTIME=1` diagnostic remains rejected, not promoted, but the
first checkpoint experiment is now classified correctly. Its v1 image encoded
the high-word `DEC` and related state mutators as 16-bit absolute writes into
SA-1 IRAM, so the 856-frame ROM-mismatched checkpoint stall is an
addressing-broken diagnostic, not a conclusion about the partial `$025110`
ledger. The fixed v2 image is
`build/interp-vtime-stage3-9dcc-experiment-v2.sfc`
(`b55274a802ffde5a88e4f3559d05213ab44cf7eab1f07dcc9eaf901aa28ab37e`). Its
fresh 24-frame liveness run is green at
`build/validate-vtime-stage3-9dcc-experiment-liveness-v3/summary.json` and
requires an actual virtual-deadline reload. The all-native-off forensic probe
`build/probe-vtime-stage3-9dcc-all-off-long-store-v4` observes high-word
decrement and phase reload, but has a ROM-mismatched checkpoint. It is
bookkeeping evidence only: the partial native ledger is still not a common
clock or a Stage-3 timing repair.

The subsequent `8b9adc92…` fresh controller replay is retained red at MAME
tick 2,958: after the Button 1 edge at tick 2,956 its native-on player was
still idle because 108 updates consumed 532,224,800 SA-1 cycles. The saved
pre-failure boundary is under
`build/fresh-campaign-current-8b9a-to15000-v1/states/failure.mss`; it is a
nested-SA-1 forensic state, not a resumable or fresh-boot acceptance state.
The cause is an unproven native/HLE route: the shared `$9D:DA00` sparse
dispatcher sent Stage-1 visits to Stage-3 direct handlers on only canonical
pointer checks. Current normal build `3d0cc84d…` removes those routes until a
three-way Stage-3 provenance discriminator exists and restores the normal
local IRQ reload (rather than a disabled-VTIME cross-bank call). Its fresh
power-on replay through tick 3,000 has 168 green player comparisons, zero
oracle mismatches, and confirms the Button 1 response at tick 2,958; its red
terminal is only the intentional incomplete-coverage guard. The matching
fresh native-off run reaches the same origin, clears `$071A/$073A`, then
exhausts the old 2,456-frame exact-entry watchdog before one interpreter-only
update. That is an interpreter-performance/harness limitation, not a
native-off semantic pass. A separate fresh power-on, one-credit HUD/art check
on `3d0cc84d…` is green at
`build/validate-fresh-one-credit-prompt-current-3d0c-v1/summary.json`: it
records an intact right artwork wedge, transparent credit underlay, clean
lower-right area, and live task state. None of this promotes `3d0cc84d…` to a
candidate.

The ordinary-ROM boss validator now uses a reversible terminal `ILLEGAL` trap
instead of the diagnostic-only PC-ring hook when requested. On the actual
`3d0cc84d…` ROM, with that trap and the same ROM supplied as both production
and diagnostic input, `build/validate-boss-health-current-3d0c-v3` is green
118/118 for MAME, native-off, and native-on: Stage 1 initializes at 40 health
and takes 13 recorded hits, Stage 2 at 40/37, and Stage 3 at 20/6. It compares
the full D/A set, CCR/X/mask, stack context, mapped work RAM, object and
collision records, and each health write in IRQ-masked bounded spans. This is
current-ROM function proof, not an organic boss fight or IRQ-cadence result.

The current-ROM crate root reruns are also green, with a retained pre-execution
state for every SNES configuration. The collision emitter is green 4/4 at
`build/validate-25110-current-3d0c-held-thrown-v1` for the carried `$2000`
and thrown `$2001` responses across MAME, root-interpreted, and native-root
paths. The damage consumer is green 6/6 at
`build/validate-1e7c0-current-3d0c-held-thrown-v2`: its all-gates-off row
starts at `inext` (not at the native root), while the two native rows cover
the normal escape gates. All D/A registers, CCR/mask, stack residue, and
mapped work RAM match the MAME result. The canonical MAME fixture records no
health write for carried `$2000` contact and one health write after thrown
`$2001` consumption. This is a bounded collision-chain proof, not organic
carried-flight or IRQ-cadence proof.

The supplied `build/playtest/stage3.mss` still reproduces the reported blue
bar on the current ROM: 51 solid-blue columns with stale `BG1HOFS=288` at
load. Both native configurations clear it after a right/neutral input span,
with halt zero and valid task stacks
(`build/validate-stage3-scroll-current-3d0c-v1/summary.json`). That classifies
the checkpoint symptom as stale initial scroll/publication rather than missing
art, but does not prove an organic Stage 3 transition. A current short
checkpoint rate probe is red at 2,299,747 SA-1 cycles/tick over its two
native-on ticks (`build/measure-stage3-current-3d0c-v1/summary.json`); it is
too short to characterize steady state, yet confirms that the rate gate is not
met and remains open.

The diagnostic now charges the `$025110` native blocks after their terminal
branch/loop, but is still unaccepted. The checked inventory is 226 sites / 545
original instructions / 3,064 static two-cycle units, with 179 terminal
branch/loop-bearing blocks (`build/audit-native-charge-blocks-25110-current-v3.json`).
The exact MAME post-state regression is green over all 4,320 complete retained
blocks, including 4,234 dynamic terminal executions
(`build/validation-mame-25110-deferred-charge-current-v2.json`). It caught and
then fixed the 65816 JSR `return-PC−1` sparse-table key error; the forced
deadline regression is green at
`build/validate-vtime-25110-due-path-v7/summary.json` and retains its forced
pre-failure state. The active-clock MAME/native-off/native-on function-local
fixture is green 2/2 at tick 10,155
(`build/validate-25110-vtime-native-ledger-exact-v2.json`), with all compared
registers, CCR/X, stack return, and mapped work RAM equal. That fixture seeds a
synthetic no-deadline timer state and is not a hardware-phase result.

This does not supply a native/HLE common clock, an arbitrary-IRQ-boundary
three-way result at tick 14,746, a general multiply/divide model, a Stage 3
rate result, or fresh prompt/gameplay acceptance. It inherits none of the
`f369…` claims. The old v4 JSL/RTL fetch-gateway liveness remains historical;
its longer 115/120-frame timeout is not rate evidence.
The earlier `adac11f4…` diagnostic rebuild and its bounded prompt/combat
checks remain historical dirty-workspace evidence only. Neither binary is
tracked by Git.

## Current candidate evidence

- The native `$0026FA` screen-shake escape now publishes X and writes both
  `SUBI.W #1,$1B18(A5)` results back to work RAM. The packed-source guard
  `build/validation-26fa-writeback-current-f369-v1` is green;
  the paired dynamic three-way capture remains pending because the fresh campaign
  stalled before reaching the retained shake window.
- A fresh cold-boot one-credit regression is green at
  `build/validate-fresh-prompt-current-f369-v1/summary.json`: the right artwork wedge
  is filled, the credit label preserves its artwork underlay, and the lower-right
  status garbage is absent. The supplied Stage 3 checkpoint is not fresh proof;
  it has zeroed renderer-map metadata and retains `BG1HOFS=288`. The current-hash
  `build/validation-stage3-scroll-input-current-f369-v1/summary.json` begins from
  the same 51-column blue gap and stale hscroll, then clears the gap after an exact
  60-right/60-neutral video-frame span in both configurations, with halt zero and
  valid stacks. Native-off advances 2 game ticks versus 32 native-on, so final
  hscroll values differ (`40`/`56`) for this fixed wall-frame window. This is
  stale PPU/renderer-state recovery, not fresh organic Stage 3 proof; organic
  Stage 3 entry remains open.
- The current-hash ordinary-enemy differential is green 4/4 in
  `build/validation-gameplay-damage-current-f369-v2`, covering punch, Button 2
  kick, body/contact, and charged projectile with exact MAME/native-off/native-on
  registers, CCR/X, stack, mapped RAM, and health-write checks. The current-hash
  boss differential is green 118/118 in `build/validation-boss-current-f369-v1.json`:
  Stage 1 is 40 health/13 hits, Stage 2 is 40/37, and Stage 3 is 20/6 with arcade
  damage sequences. The carried/thrown crate emitter/consumer rerun
  `build/validation-crate-current-f369-v2.jsonl/summary.json` is green 12/12: held `$2000` is
  contact-only with zero health writes and thrown `$2001` performs one health write.
  These are focused differentials, not continuous organic battles or IRQ-cadence proof.
- Independent current-hash reruns confirm the reported prompt/HUD and crate paths:
  `build/validate-fresh-prompt-current-f369-v2/summary.json` is a new one-credit
  cold boot with no artwork gap, HUD overwrite, or lower-right status garbage;
  `build/validate-gameplay-damage-current-f369-v2` is green 4/4; and
  `build/validate-crate-damage-threeway-current-f369-v2/summary.json` is green
  12/12. The crate rerun retains MAME/native-off/native-on evidence that carried
  `$2000` contact writes no enemy health and thrown `$2001` writes health exactly
  once. These are not continuous organic flight or boss-fight proofs.
- Current-hash Stage 3 bounded handlers are green: scroll `9/9` in
  `build/validation-stage3-scroll-current-f369-v1` and hot handlers `32/32` in
  `build/validation-stage3-hot-current-f369-v1`, with exact MAME/native-off/
  native-on register/CCR/stack/work-RAM checks and real route probes. The current
  checkpoint rate measurement `build/measure-stage3-current-f369-v1.json/summary.json`
  is 690,322 SA-1 cycles/tick and 3.84375 video frames/tick with native-on
  (native-off 11,128,944.5 cycles/tick), so the 30 Hz/358K gate still fails.
  These are bounded checkpoint proofs, not fresh organic Stage 3 entry or full
  playthrough evidence.
- A later fresh-lineage Stage 3 continuation has a deterministic first ordering
  divergence at MAME logical tick 14,746. MAME's saved task-15 frame is
  `$0259B0`/`$0242BE`/SR `$2400`, whereas current SNES completes the batch to
  `$0818` and retains `$02429C`/`$00044E`, changing RNG, saved task state, and
  work RAM. The exact MAME/full-all-escape-off/native-on gate
  `build/validation-stage3-irq-order-all-native-off-current-f369-v1.json` is
  green through ticks 14,744–14,745 and red at 14,746 in both SNES
  configurations. The defined `$071A/$073A` native-off control agrees. This is
  a hardware-boundary/virtual-IRQ timing issue, not an escape/HLE or opcode
  issue.
  The retained safe state is
  `build/forensic-fresh-stage3-rng-safe14743-v1/states/safe-checkpoint-14743.mss`.
  A literal `$2328` probe reaches the first desired task frame but misses D7/A0
  on its following `$02582E` frame; `$2354` already misses the first seam.
  Production dynamic, one-shot, and packed-memory policies remain rejected.
  A separate uninterrupted original-code MAME capture from power-on,
  `build/mame-25110-irq-phase-current-f369-v5/summary.json`, is green under
  `build/validation-mame-25110-irq-phase-current-f369-v5.json`. Its debugger
  trace records level-6 service periods of 139,302, 139,296, and 139,342
  MC68000 cycles and the interruption PCs `$000818`, `$0259B0`, `$02582E`, and
  `$000810`; tick 14,746's IRQ services at the `$02582E` instruction boundary.
  The trace reducer `build/analysis-mame-25110-irq-cycle-model-current-f369-v1.json`
  observes path-dependent costs at the same PC/opcode (for example `$0259B6`
  DBRA is 10 or 14 cycles). The exact-MAME static-table audit
  `build/audit-m68k-cycle-model-current-f369-v6.json` has 46,874 comparable
  ROM-resident instruction pairs: 7,986 (17.04%) disagree with the
  development-only static table, chiefly 6,654 conditional branch/loop sites
  plus 830 MOVEM and 452 shift/rotate sites; 21 work-RAM-code pairs are
  explicitly outside this log's opcode-word coverage. Its 46,900
  register-qualified trace rows also retain the debugger's consistent
  two-byte pipeline-PC skew. The trace proves the root requirement is
  path-sensitive MC68000-cycle accounting, including native-span charges,
  rather than a new global `$AC` reload literal. The static-table comparison
  does not attribute every mismatch to one MAME-core mechanism. It is
  original-code timing evidence, not a SNES fix, fresh Stage-3 completion, or
  rate result.
  The narrower register-qualified proof
  `build/validation-mame-25110-branch-timing-current-f369-v2.json` is green:
  all 10,803 retained conditional-Bcc/DBcc records match the CPU-000 outcome
  rules exactly (short Bcc 10/8, word Bcc 10/12, DBcc branch/expired 10/14
  cycles), including 2,439 loop-back and 291 expired DBcc cases. This proves
  concrete path-sensitive timing rules, not just a histogram; it does not
  cover an unobserved DBcc condition-true exit or complete the SNES repair.
  The companion variable-cost regression
  `build/validation-mame-25110-variable-timing-current-f369-v2.json` is also
  green: all 830 retained MOVEMs match their extension-word register-list cost,
  and all 452 retained data-register shifts/rotates match their immediate or
  pre-instruction Dn count. The exception/arithmetic sentinel
  `build/validation-mame-25110-exception-arithmetic-timing-current-f369-v1.json`
  covers 44 `TRAP #n` entries at the CPU-000 34-cycle vector cost and the six
  observed multiply/divide operand rows. It deliberately does not claim a
  general multiply/divide formula; that and unobserved dynamic forms remain
  required before a source timer can claim complete cycle coverage.
  The companion MAME-driver clock reduction
  `build/validation-mame-superman-vblank-clock-current-f369-v1.json` is green:
  the verified 8 MHz CPU and 57.43 Hz screen give a nominal level-6 deadline
  of `800000000/5743` cycles = `139300 + 100/5743`, or `69650 + 50/5743`
  two-cycle units. Therefore a fixed `$7000`, `$2328`, or even fixed 139300-
  cycle reload cannot be the final model; it also needs fractional phase and
  instruction-boundary pending delivery. The unimplemented repair contract is
  recorded in [VIRTUAL_IRQ_TIMING.md](VIRTUAL_IRQ_TIMING.md). Its pure-math
  pre-implementation regression is green at
  `build/validation-virtual-irq-timer-math-current-f369-v1.json`; this is not
  a ROM or fresh-boot result.
  The physical native-on delivery capture
  `build/capture-stage3-irq-delivery-current-f369-v3/summary.json` independently
  stops at the third `$025110` entry and then at `$00:B404`, with no
  architectural writes. It shows zero explicit mid-call yield hits and task 15
  still saved at `$02429C` when the virtual IRQ begins at logical `$0818`.
  This corroborates the red three-way gate but is a checkpoint forensic, not
  fresh-boot or native-off proof.
  Thus current Stage 3 traversal and usable rate remain open; no fresh Stage 3
  completion claim is made.
- The completed bounded campaign
  `build/fresh-campaign-current-4359-to10000-exact-v1/summary.json` is
  predecessor-hash evidence, not current-ROM proof. It covers walking, Button 1
  punch/charge, Button 2 kick, Up flight, Down movement, crate pickup/carry/throw,
  hurt, death/respawn, and five retained deaths, but no boss or Stage 3.
- The post-fix fresh current-hash replay
  `build/fresh-campaign-current-f369-to10158-v2/summary.json` is green through
  MAME tick 10,158 with 1,068 controller transitions, five deaths, zero oracle
  divergences, and zero SA-1 halts. It reaches the repaired `$025110` boundary,
  but no boss or Stage 3 transition occurs; this remains bounded organic coverage,
  not a completed playthrough.
- The retained `94158832…` fresh controller campaign and its paired
  `campaign-stall-threeway-rom9415-v1` remain historical-hash forensic evidence of
  the old `$001000B0/$F800` interpreter/unimplemented-opcode path. The current
  10,158-tick replay does not hit that terminal, but the root path remains unclosed
  for a full-length campaign.
- The retained exact-boundary forensic trace identified the organic stack leak at
  native logical PC `$13BE`: its native entry sees a `$00FD` sentinel frame
  rather than a 68000 return PC, and task 5 lost four bytes per native update.
  The CE58 bridge now enters a no-push D18A body while generic D18A callers keep
  their normal re-simulated push. The repaired regression
  `build/validation-13be-sentinel-route-current-v4.json` is green for 44/44
  exact entries, preserving `$F00DB8` and avoiding the terminal margin failure.
  This focused repair does not fix the separate fresh-route `$001000B0/$F800`
  interpreter halt.
- The exact MAME 0.287 payload is durably staged from snap revision 4339 under
  `build/toolchain/mame-4339-recovery/root/mame` (SHA-256
  `297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f`).
  `bash tools/stage_mame_0287.sh` downloads and extracts that revision without
  replacing the installed snap, then rejects the wrong payload hash or version.
  `tools/mame_0287.py` and `tools/mame_0287_exec.sh` discover the durable path;
  their explicit `SUPERMN_MAME_EXE`/`SUPERMN_MAME_LD_LIBRARY_PATH` overrides
  remain available for another authenticated extracted layout. The host's mutable
  MAME 0.289 snap is not accepted as the arcade oracle.

## Historical v135 evidence

- It repairs the reproduced v134 SA-1 IRAM erasure. A generated `$023342` path had
  been assembled with an 8-bit immediate while live execution was M=16, turning the
  following `$54` operand into accidental `MVN $A9,$FB`.
- An exact-Mesen 2.1.1 regression advanced from frame 11,588 to 13,988 and game tick
  2,107 to 2,519 across the old terminal, with halt zero and live IRAM/task state.
- A separate checkpointed renderer test restored the cropped top HUD: its 88-record
  packed OBJ manifest and screenshot contain `1UP`, `HIGH SCORE`, `2UP`, all score
  rows, and the full credit label. All 14 initialized stacks remained valid with a
  138-byte minimum margin. That test disclosed a 12 KiB same-ROM video-mirror refresh;
  it is not an organic fresh-boot result.

Those are bounded cause-and-regression results. They do not prove a fresh cold boot,
an organic Stage 2 run, a complete stage, general crash freedom, renderer
conservation, or a full playthrough.

## Evidence audit used for this status

The July 24 documentation audit checked the claims above against the retained raw
artifacts, not only prior prose:

| Claim | Raw evidence checked |
|---|---|
| current candidate size/hash | `build/interp.sfc`: 4,194,304 bytes and exact SHA-256 above; the preserved v135 playtest copy is an older hash and is excluded |
| v135 old-terminal liveness | `build/user-playtest-v105-investigation/v135-final-idle-iram-wipe-regression-mesen211-v2/terminal-events.json`: frame 11,588→13,988, tick 2,107→2,519, halt zero, no terminal event |
| v135 HUD | `build/user-playtest-v105-investigation/v135-hud-full-top-band-mesen211-v3/results.json` plus final screenshot: tick 1,258→1,335, render 1,183→1,259, 88 records, 14 valid stacks, 138-byte minimum, disclosed mirror refresh |
| v124 production | exact local v124 ROM hash plus `build/user-playtest-v105-investigation/production-v124-26a0-ordered-coldboot-uninterrupted-3600f-v1/baseline.jsonl` and its hashed hook/debt streams |
| Interpreter counts | retained `optest-final.log` SHA-256 `93470844…` and `opsweep-final.log` SHA-256 `f0e935df…`, reconciled in Recovery R6/R7 |

Those `build/` paths are private local evidence and are not required to exist in a
fresh clone. The committed recovery/handoff documents below retain their hashes and
scope.

## Latest formal performance evidence

No v135 formal performance run exists. The latest end-to-end measurement satisfying
the evidence protocol is exact v124, SHA-256
`777507c9ecba8b7911dae882ea266cca7d173d918dde65b73f880acdb0451352`.
It began at power-on with `TESTFLAG=0`, armed production organically, used the real
controller mailbox, validated the real `$00:F5A3` tick boundary, included waits,
IRQs, rendering, input, sound supervision, and state transitions, and crossed the
known scheduler-ordering region.

| Metric | Formal v124 result |
|---|---:|
| Emulated SNES video frames | 3,602 |
| Game ticks | 1,783 |
| Game rate | **29.700167 game-fps** |
| SA-1 cycles | 643,645,462 |
| Mean SA-1 cycles/tick | **360,990.164** |
| Requests / unit ACKs / true draws | 1,783 / 1,782 / 1,782 |
| Final tick / halt / task mask | 2,210 / `$0000` / `$FFF1` |
| Initialized task stacks / minimum margin | 14 / 138 bytes |

It failed both formal gates: `29.700167 < 30` and `360,990.164 > 358,000`.
The one-request endpoint lag was an in-flight transaction, not a skipped ACK.
This remains useful near-30 Hz scheduler/performance evidence, not a playable
verdict for v124 or v135.

## Subsystem status

| Area | Current truth |
|---|---|
| MC68000 interpreter | Implements the legal MC68000 instruction set and runs on SA-1. Latest retained semantic gates are optest 160/160 and opsweep 782/782 cells (1,564/1,564 vectors), plus focused lockstep evidence. This is not proof of every unvisited whole-program address path. |
| Native escapes/HLE | Many focused and live differentials are green. Repeated human failures show that a correct local differential does not prove whole-game control flow, layout, or stability. |
| Combat | Active `a976…` has a fresh replay through tick 10,000 that observes Button 1 punch/charge, Button 2 kick, Up flight, and crate pickup/carry/throw with 2,062 green comparisons. Its ordinary-enemy 4/4 and boss 118/118 three-way matrices are green, and its same-hash organic crate carry/throw and Up+Right flight-contact branches are green: carried contact does no damage; Button 1 throw damage matches MAME. These bounded tests do not prove a continuous organic battle or full playthrough. |
| Stability | Active `a976…` passes the fresh one-credit renderer/HUD regression and the bounded fresh campaign through tick 10,000 with five matched deaths, no MAME/SNES oracle divergence, and no halt. Its same fresh native-on root reaches tick 14,746, where the exact MAME/native-off/native-on task frame is red on the shared virtual-IRQ timing boundary; bosses, complete stages, and full-playthrough stability remain unproven. |
| Rendering | Active `a976…` fresh one-credit artwork/HUD checks are green. Its organically generated fresh campaign endpoint at the Stage-3 timing boundary has the retained `campaign-end.png` city artwork with no visible vertical blue bar; `tools/test_stage3_irq_order_current_a976_evidence.py` pins that Nexen baseline. It is not an aligned MAME-pixel or renderer-conservation proof; the supplied old `stage3.mss` blue strip remains stale-save-state evidence and exact pixel conservation remains open. |
| Stage 2/3 scrolling | The active fresh lineage reaches the Stage-3 timing boundary and its retained Nexen endpoint has no visible blue bar, but the exact task-frame gate diverges at tick 14,746 and its checkpoint-local rate is far over budget. Current organic Stage-2/3 fidelity, usable rate, completion, and renderer conservation remain unproven. |
| Audio | Organic command transport and TAD loading work. The VGM-derived five-octave-anchor pass was genuinely regenerated, compiled, and packed, but the human verdict was “no noticeable improvement.” Music/SFX remain musically incomplete. |
| Private-input preparation | `tools/prepare_roms.py` authenticates the World ROM set and exactly derives the 68K image, graphics image, C-Chip response, and 12 drums. The 45 FM authoring WAVs still require the external VGM/ymfm pipeline or the preserved private set. |
| Hardware | Emulator evidence exists for Nexen and exact Mesen 2.1.1. No real-cartridge/FXPak SA-1 acceptance result is recorded. |

## Current release blockers

The concise prioritized list is in [RELEASE_BLOCKERS.md](RELEASE_BLOCKERS.md). The
highest-risk items are:

1. validate the corrected boss-fixture boundary across later hits, then obtain
   fresh-boot and farther boss validation before any diagnostic or ordinary
   promotion decision;
2. integration of the remaining common-clock/native-owner work and a qualifying
   30 Hz / 358K-cycle result on the eventual ordinary candidate;
3. renderer conservation, wrong attack-animation tiles, and organic Stage 2
   scrolling;
4. by-ear VGM-to-TAD transcription/timbre and real SFX;
5. a complete playthrough and aligned MAME graphics comparison; and
6. real release-hardware acceptance and scope.

## Evidence sources

- [Current gameplay campaign (2026-08-01)](GAMEPLAY_CAMPAIGN_20260801.md)
- [Engineering checkpoint (2026-08-11)](ENGINEERING_CHECKPOINT_20260811.md)
- [R15 freeze/HUD/audio handoff](../history/handoffs/V135_IRAM_FREEZE_HUD_AUDIO_20260724.md)
- [Recovery ledger R0-R15](../history/recovery/RECOVERY.md)
- [Confession/correction ledger](../history/recovery/CONFESSION.md)
- [Performance campaign](../history/performance/PROFILE_CAMPAIGN.md)
- [v124 formal baseline entry](../history/recovery/RECOVERY.md#formal-v124-production-result)

When new evidence changes a statement above, update this file and the focused evidence
report in the same change. Preserve the old report as dated evidence.
