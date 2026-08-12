# Engineering checkpoint — August 11, 2026; updated August 12

This is a concise handoff for the multi-week gameplay-validation campaign. It
does not replace [STATUS.md](STATUS.md), which remains the sole authority for
project status and acceptance claims.

## Exact ROM identities

| Role | SHA-256 | Scope |
|---|---|---|
| Best evidence-backed ordinary candidate | `a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60` | Preserved 66-byte terminal-CCR repair with fresh ordinary coverage through tick 10,000. |
| Red renderer parent | `11aefd2c…` | Preserved step-cap source line; deterministic repeated-tile flashes under live Mesen scrolling. |
| Current-source ordinary build | `5f5dc9d7…` | Renderer-red. Exact Mesen state is corrupt at tick 2,465; all 228 retained continuation frames trigger the repetition diagnostic. No corrected ROM exists. |
| Long checkpointed VTIME lineage | `14e920eb84a5ab44bff902b941f8926c42cab11f39e4537a88d2c4ad0e608750` | Oracle-green through tick 14,000; post-divergence coverage through tick 20,000. |
| IRQ/VPA/input-diagnosis predecessor v4 | `4a3555fd3d8d9dec589ee27531ec23e7ad7bd5f52c86e983dd1872677049cfb9` | Retained tick-14,745 checkpoint and first input/Y mismatch at 14,748. |
| Delayed-input diagnostic v7 | `45c9096dfda3d4203878c18954725ff4814f23f4e28a1e623f3cf07b647e6c72` | Player/input/death oracle is green through 16,000; corrected first boss observations are green at 15,908/15,990. No fresh boot. |
| Exact-v7 cap checkpoint | `45c9096d…` | No oracle divergence through completed tick 21,200; terminal tick 21,203 intentionally reaches the interpreter lifetime guard (`$CAFE`, SA-1 `$00D15A`, virtual PC `$000D42`). |
| Unpromoted v8 successor | `162b757c…` | Four threshold-byte successor; repeat-validated same-ROM continuation reaches MAME 31,000 / SNES 30,994 with no divergence or mismatch and halt 0; liveness metrics were not sampled at the intentional stop. |

Never report one identity's evidence as proof for another. Diagnostic checkpoint
migration is explicitly unable to prove boot, renderer continuity, performance,
production, or release acceptance.

## What the campaign accomplished

- Built a disk-first MAME-versus-Nexen campaign runner with authenticated ROM,
  oracle, emulator, bridge, timeline, exact-boundary, and checkpoint identities.
- Added atomic post-entry safe checkpoints, repeat-save hashing, recovery of a
  checkpoint from a harness-red run, and a machine-readable evidence ledger.
  This eliminated repeated 10,000-tick prefix replays.
- Added diagnostic-only cross-ROM migration that refreshes executable 5A22 WRAM
  from the selected ROM while proving every other serialized domain unchanged.
- Moved long playback to the Luna `playback_watcher`. Raw logs, states, frames,
  and screenshots stay on disk; the main reasoning thread receives only first
  divergence, mismatch ranges, concrete symptoms, and artifact filenames.
- Fixed real 5A22 liveness defects: nested NMI status corruption, DMA descriptor
  replay ordering, and NMI scroll-keepalive clobber of renderer scratch `$D0`.
- Expanded VTIME coverage through the `$02429C` root/children, Stage-3 player
  blocks, MOVE-collapse fallback, absolute choke gate, four-byte DBcc register
  indexing, paced `$0818`, IRQ-entry accounting, and fractional interval phase.
- Preserved negative results. Credit-gate failures, the pure-interpreter `$0818`
  bypass, nonresumable exact-entry states, the v5 `.org` overlap, and the v6
  one-tick-early input response remain documented rather than being rewritten as
  successes.

The retained `14e920eb…` campaign is exact through tick 14,000. It continues
safely through tick 20,000 for coverage, but the first inherited comparison
divergence is tick 14,748. Later boss rows used the rejected frame-minus-75
mapping and are neither timing evidence nor green boss acceptance.

Exact-v7 continuation is oracle-green through completed tick 21,200. Safe state
is `6c3eaab1…` (IRAM `0d4f91e8…`), pre-counter `$07FEF8A5`; terminal tick
21,203 reaches `$08000000`, writes `$CAFE`, and spins at SA-1 `$00D15A` /
virtual PC `$000D42`. ROM disassembly identifies valid `MOVE.W (A1)+,D4` at
`$0D40` followed by `BEQ` at `$0D42`; no exact MAME state is needed for this
cap arithmetic. The v8 migration and continuation reports
(`build/playback-watcher-20260812/v8-stepcap-migrated21200-to21300-v1/watcher-report.json`,
which crosses the old cap to counter `$0809A799`,
`build/playback-watcher-20260812/v8-stepcap-resume21301-to21500-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume21501-to22000-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume22001-to22500-v1/watcher-report.json`, and
`build/playback-watcher-20260812/v8-stepcap-resume22501-to23000-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume23001-to25000-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume25001-to27000-v1/watcher-report.json`,
`build/playback-watcher-20260812/v8-stepcap-resume27001-to30000-v1/watcher-report.json`,
and `build/playback-watcher-20260812/v8-stepcap-resume30001-to33000-v1/watcher-report.json`)
have first divergence NONE and no mismatch ranges through MAME 31,000 / SNES
30,994; endpoint halt is 0. Minimum stack and renderer drops were not sampled
at the intentional stop. The endpoint is state
`613c6566788e4b81408b87efbd278d35fa9f75c6ca762eb14a17b65f1ff4f32c`, IRAM
`7ab15b2dad152aa2d3b37401c6534e0ae4c4a42dc3a44beef6c21c5c9988ef4c`, resume
31,001. The retained movie ends at game tick 139,925 / frame 140,000, leaving
108,925 game ticks (22.15% covered). The campaign is intentionally paused for
human screenshot review. These are checkpoint-only diagnostics, not fresh boot,
full-playthrough, or production acceptance.

## Human visual checkpoint

Update, August 12: the still-image review did not survive live gameplay. Chad ran
then-current ordinary `build/interp.sfc` (`11aefd2c…`) in Mesen and observed a repeated,
corrupt gameplay background immediately after coin/start plus flashing while
scrolling. The supplied capture is retained at
`docs/assets/evidence/current-11ae-user-mesen-background-red-20260812.png`. This is
parent-hash negative evidence and invalidates the earlier run recommendation. The
montage below remains scoped to its preserved `4eb9a408…` and v7 source images;
it does not establish live current-ROM renderer correctness. The `11ae…` hash is
preserved for exact Mesen reproduction and consecutive framebuffer analysis. Its
analysis is deterministically
red at extracted frames 165–174 and 225–232. The first bad frames change 98.93%
and 60.34% of the playfield. Focused no-write hooks identify heavy-path uploads at
emulator frames 6,915 and 6,988 whose staged maps are 96.88% and 94.63% zero words;
the fuller uploads at 6,927 and 6,997 restore the storefront. Physical BG tile
slot zero contains live art, so zero staging entries display as the repeated
pattern. Raw frames/hooks stay in the parent-hash playback-watcher directories;
the compact causal report is
`build/playback-watcher-20260812/current-11ae-mesen211-right-bg-map-values-from6891-v5/watcher-report.json`.

The first queue-wide repair `10dc1a0b…` was rejected because repeated-tile ranges
persisted. The narrower map-content heuristic delays a map below 256 nonzero
words only when a complete successor is queued and continues publishing live
scroll. `9ab9a1db…` was superseded on static audit because its scan changed X/Y;
`5f5dc9d7…` restores those registers. Its retained ticks 881→1,020 run suppresses
one 35-cell map and sees no dominant-tile collapse across 231 lossless frames.
That result is now explicitly diagnostic-only: it was not aligned to exact MAME
pixels and did not prove temporal conservation.

Chad's exact Mesen 2.1.1 state `interp_1.mss` (SHA-256 `63606d27…`) opens
`5f5dc9d7…` already corrupt at frame 10,118 / game tick 2,465. Displayed VRAM
and `$7E:9000` staging maps are byte-identical with 1,589/2,048 zero words. A
real-Right continuation reaches tick 2,578 with halt zero; all 228 retained
frames trigger the repetition diagnostic. Fifteen map attempts produce eight
commits, and the heuristic admits the 459-nonzero-word map. The source-level root
is the use of physical BG slot zero for live artwork even though empty map words
select slot zero; authenticated arcade graphics code zero is blank. Slot zero
must be reserved as blank. No corrected ROM has been built.

Tooling now enforces three independent gates over one authenticated ROM and exact
tick range: state oracle, aligned exact-MAME pixels at every game tick, and every
intervening SNES video frame matching the preceding or succeeding accepted MAME
image. `tools/validate_gameplay_acceptance.py` alone may issue a bounded aggregate
green. Missing evidence is `unknown`; repetition, capture, trace, cross-emulator,
and isolated single-frame results cannot authorize “fixed” or “no divergence.”

The committed README montage at `docs/assets/readme/showcase-20260812.png`
(SHA-256 `afa28ba5…`) supersedes the stale August 11 montage. Its first four
panes come from the preserved fresh `4eb9a408…`
visual line and show the clean SA-1 boot, centered HUD/prompt, restored storefront
combat background, and crate carry without the bogus tile chunk. Its last two
panes come from the checkpointed v7 Stage-1 boss continuation and are labeled as
checkpoint evidence. The montage intentionally combines two evidence scopes; it
does not establish fresh-boot or full-playthrough acceptance for v7/v8.
Chad's concept cover is retained at repository root as `superman.png` (SHA-256
`633b9e7a…`); it is presentation artwork, not emulator evidence.
On August 12 Chad reviewed the corrected montage and reported no visible defect.
That is human acceptance of these six still images only, not a live gameplay,
audio, aligned-pixel, or hardware playtest.

## The tick-14,748 repair

The earlier IRQ-accounting reduction found a real VTIME defect, but focused
counterfactuals showed it did not move the Y mismatch. The decisive ordering
evidence was:

1. candidate `$003AD8` reads P1 before the next `$0818` re-arm;
2. NMI has completed the B+Up `$0088` sample;
3. arm remains 2, so the ordered `$410000` publisher does not run;
4. candidate P1 remains `$FF`, while MAME consumes `$EE` and moves Y 139→136.

V5 attempted a staged reader at `$F2:B500`, overlapping the live dynamic-cost
decoder and stalling before gameplay. V6 relocated it to `$B740` but consumed
the newest NMI sample immediately, shifting the mismatch one tick early. V7
patches only the five-byte `input_p1` prefix, leaves generic `joy_read` intact,
honors genuine `$0818` mailbox publications via `$41012B`, and otherwise commits
the preceding staged sample before capturing the next.

Luna's ROM-only continuation from the authenticated v4 tick-14,745 checkpoint
has no divergence through 14,750: Y is 139 at 14,747 and 136 at 14,748,
2,746/2,746 player rows and 12/12 death rows are green, and all three terminal
states are byte-identical at SHA `9fde6a6b…` with IRAM `c98e718e…`. The compact
report is
`build/playback-watcher-20260811/v7-input-delayed-migrated14745-to14750-v2/watcher-report.json`.

The exact-v7 same-ROM suffix then resumes at 14,751 and remains partial-green
through 15,000: 2,772/2,772 cumulative player rows, 12/12 death rows, 1,386
input transitions, zero divergence, halt zero, live rendering, and 15 valid
initialized task stacks at minimum margin 138. Its repeat-identical tick-15,000
state is `918098c4…`, IRAM `43c45f3c…`, and resumes at 15,001. The compact
report is
`build/playback-watcher-20260811/v7-input-delayed-resume14751-to15000-v3/watcher-report.json`.
This remains migrated-lineage evidence: it does not prove fresh boot, bosses,
rate, production, or playthrough acceptance.

Further exact-v7 same-ROM suffixes keep all player/input/death rows green
through 16,000. The original boss rows at 15,906/15,988 were two observation
boundaries early: every retained timeline tick row has `frame - tick == 74`,
and campaign stops are pre-body. Focused writes store and commit `$0028` and
`$0024` during SNES ticks 15,901/15,983; the following campaign stops at
MAME/SNES 15,908/15,902 and 15,990/15,984 observe both values and are green.
This excludes a separate boss initializer/subtractor defect for those writes
and removes the claimed organic scheduler split. The final compact report is
`build/playback-watcher-20260812/v7-boss-observation-resume15901-to16000-v1/watcher-report.json`.
The repeat-identical tick-16,000 state is `06da361f…`,
IRAM `3a672763…`, and resumes at 16,001. Compact evidence is under
`build/playback-watcher-20260811/v7-input-delayed-resume{15001-to15500-v1,15501-to16000-v1}/`
and `build/playback-watcher-20260811/v7-boss-health-write-window-v2/`.

The corrected v7 suffix continues through tick 16,500 with six cumulative
Stage-1 boss observations green. New green rows are MAME ticks
16,102/16,201/16,285/16,403 with health 34/31/29/25. Player, input, and death
references remain green; there is no oracle divergence, halt is zero, renderer
queue drops are zero, and the minimum initialized-stack margin is 138. The
repeat-identical tick-16,500 state is `f6c5b389…`, IRAM `5de396c8…`, and resumes
at 16,501. The compact report is
`build/playback-watcher-20260812/v7-boss-observation-resume16001-to16500-v1/watcher-report.json`.
This validates only the first six Stage-1 fixtures, not full-boss behavior,
fresh boot, production, performance, or playthrough acceptance. The historical
frame-minus-75 rows remain invalid comparisons, not accepted red boss evidence.

The corrected v7 suffix then reaches tick 17,000 with 11 cumulative Stage-1
boss observations green. New rows are MAME ticks 16,519/16,624/16,750/16,837/
16,921 with expected and observed health 21/18/14/11/9. Player, input, and
death references remain green with no oracle divergence, halt zero, renderer
queue drops zero, and minimum initialized-stack margin 138. The
repeat-identical tick-17,000 state is `1bab53c8…`, IRAM `bf80c888…`, and resumes
at 17,001. The compact report is
`build/playback-watcher-20260812/v7-boss-observation-resume16501-to17000-v1/watcher-report.json`.
This validates the retained first 11 Stage-1 fixtures only, not complete
Stage-1 boss behavior, full-boss, fresh boot, production, performance, or
playthrough acceptance.

The corrected v7 suffix reaches tick 17,500 with 12 cumulative Stage-1 boss
observations green. The new row is MAME tick 17,020 with expected and observed
health 6. Player, input, and death references remain green with no oracle
divergence, halt zero, renderer queue drops zero, and minimum initialized-stack
margin 138. The repeat-identical tick-17,500 state is `9f785e78…`, IRAM
`b1a53fde…`, and resumes at 17,501. The compact report is
`build/playback-watcher-20260812/v7-boss-observation-resume17001-to17500-v1/watcher-report.json`.
The last two Stage-1 fixtures remain pending; this is not complete Stage-1 boss
behavior, fresh boot, full-boss, production, performance, or playthrough
acceptance.

The corrected v7 suffix reaches tick 18,000 with all 14 retained Stage-1 boss
fixtures green. New rows are MAME ticks 17,562 and 17,656 with expected and
observed health 2 and `$FFFF`. Player, input, and death references remain
green with no oracle divergence, halt zero, renderer queue drops zero, and
minimum initialized-stack margin 138. The repeat-identical tick-18,000 state
is `d06e3fb9…`, IRAM `fdfe1d7d…`, and resumes at 18,001. The compact report is
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
renderer drops zero. This remains checkpointed-v7 evidence; the next boss
fixture is Stage 2 at MAME tick 36,227, and fresh boot, full playthrough, and
production acceptance remain unproven.

## Screenshots retained locally

Screenshots are ROM-derived evidence and remain gitignored. The curated local
contact sheet is `build/showcase-20260811.png`. Its six source captures show:

- cold boot / SA-1 ROM activity and the credited start prompt;
- Button 1 combat;
- organic crate pickup/carry;
- Stage-1 boss-region coverage (not green boss acceptance); and
- the v7 tick-14,750 terminal frame.

Additional retained action captures cover Button 2 kick, hurt, death/respawn,
crate pickup phases, carry, and throw under the checkpointed campaign directories.

The contact sheet is now negative evidence, not a showcase acceptance artifact:
manual review found corrupt/orange cold boot, wrong combat background, a bogus
crate-area tile chunk, and clipped P2 HUD placement. Superseded `2f590fb1…` now
has a fresh run through tick 3,300: boot, centered P2 HUD, and crate-area pixels
are repaired, but combat remains the red-brick failure. Forensics proved that
C0BC followed an existing title baseline; its expected 784-byte transition was
mistaken for a later mutation and cleared the valid token. Superseded `6f7b1084…`
retained the token only when the live 2 KiB planes equal their publication-time
snapshot, and its fresh tick-1,280 plus same-lineage resume through 3,300 stayed
oracle/liveness/HUD/crate green, but combat remained red brick. Forensics then
found the accepted token changed without a geometry or dirty-generation change,
so the 5A22 never uploaded the canonical prepared map. Current `4eb9a408…`
caches the applied token, restores the immutable map, sorted-code list, and
palette map, and publishes one prepared dirty event. Its three-case 5A22 fixture
is green, and a migrated tick-1,280-to-1,300 continuation restores the storefront
after the first render without oracle/liveness failure. Its authorized exact-hash
fresh prefix then repeat-hashed a safe tick-1,280 checkpoint; the same-lineage
suffix resumed at 1,281 and completed tick 3,300 with no observed oracle/liveness
divergence across 118 input transitions and one death. Retained frames show clean
SA-1 boot, the restored storefront at Button-1 tick 1,278, no bogus crate-area
tile chunk at carry tick 3,214, and the full centered P2 HUD. The compact report
is
`build/playback-watcher-20260811/visual-eightfix-4eb-fresh-to3300-v1/watcher-report.json`.

## What remains open

1. Treat the exact-hash tick-3,300 result as bounded partial-green evidence only;
   it does not close renderer conservation, aligned MAME pixels, performance, or
   full-playthrough acceptance.
2. If extending this campaign, use Luna and resume the retained exact-hash
   tick-1,280 checkpoint; do not replay the accepted prefix or stream transcripts
   into the main thread.
3. Close remaining common-clock/native-owner coverage and obtain a qualifying
   power-on 30 Hz / 358K-cycles-per-tick result on the eventual ordinary image.
4. Complete renderer conservation, attack-tile, organic Stage-2, aligned-pixel,
   audio-listening, full-playthrough, and real-hardware acceptance.

The ordinary build now reproduces exact SHA `4eb9a408…`. Its fresh prefix plus
same-lineage suffix is partial-green through tick 3,300; broader acceptance and
release blockers remain open.
