# Engineering checkpoint — August 11, 2026

This is a concise handoff for the multi-week gameplay-validation campaign. It
does not replace [STATUS.md](STATUS.md), which remains the sole authority for
project status and acceptance claims.

## Exact ROM identities

| Role | SHA-256 | Scope |
|---|---|---|
| Best evidence-backed ordinary candidate | `a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60` | Preserved 66-byte terminal-CCR repair with fresh ordinary coverage through tick 10,000. |
| Current-source ordinary build | `4eb9a4082dac83233304b318cd2d7729923767106e640360988937089a762963` | Reproducible `build/interp.sfc`; unpromoted complete C0BC consumer/visual-repair candidate, not acceptance-equivalent to `a976…` or predecessor hashes. |
| Long checkpointed VTIME lineage | `14e920eb84a5ab44bff902b941f8926c42cab11f39e4537a88d2c4ad0e608750` | Oracle-green through tick 14,000; post-divergence coverage through tick 20,000. |
| IRQ/VPA/input-diagnosis predecessor v4 | `4a3555fd3d8d9dec589ee27531ec23e7ad7bd5f52c86e983dd1872677049cfb9` | Retained tick-14,745 checkpoint and first input/Y mismatch at 14,748. |
| Delayed-input diagnostic v7 | `45c9096dfda3d4203878c18954725ff4814f23f4e28a1e623f3cf07b647e6c72` | Migrated five-tick seam is green through 14,750; no fresh boot yet. |

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
divergence is tick 14,748 and later boss rows are downstream timing evidence,
not green boss acceptance.

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
after the first render without oracle/liveness failure. It has not been
fresh-booted.

## What remains open

1. Decide whether to authorize a focused fresh-boot `4eb9a408…` visual campaign.
   Until then, its combat-background repair is unaccepted. The predecessor's
   green boot/HUD/crate evidence does not transfer across the ROM hash.
2. If authorized, use Luna and the retained checkpoints; do not replay accepted
   prefixes or stream transcripts into the main thread.
3. Close remaining common-clock/native-owner coverage and obtain a qualifying
   power-on 30 Hz / 358K-cycles-per-tick result on the eventual ordinary image.
4. Complete renderer conservation, attack-tile, organic Stage-2, aligned-pixel,
   audio-listening, full-playthrough, and real-hardware acceptance.

The ordinary build now reproduces exact SHA `4eb9a408…`. The latest fresh visual
campaign in this repair phase used superseded `6f7b1084…`; `4eb9a408…` has not
been fresh-booted.
