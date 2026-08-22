# Superman video renderer

This is the implementation record for wiring live MC68000 video state to the SNES
PPU. Its stage-by-stage sections preserve the June bring-up, including claims that
were true only before pixels first rendered. For current acceptance state, use
[the authoritative status](STATUS.md); for the reusable method, use
[graphics conversion](../toolchain/GRAPHICS_CONVERSION.md).

> **Historical opening:** when this record began on June 19, every non-work-RAM video
> write was a no-op and the game ran blind. Production now renders recognizable
> title/gameplay/HUD output, but renderer conservation, attack-animation tiles,
> organic Stage 2 behavior, and aligned MAME pixels remain open.

## August 13–14 focused correction: every-frame BG/OBJ integration

Preserved `50bbed41…` produces the right Stage-1 wall/floor but does not move it
at source cadence. In the retained exact-hash frame-5,871 suffix, live X1 column
zero advances by exactly -3 pixels on all 50 game ticks. The PPU changes BG1HOFS
only 17 times because a physical-column change forces a heavy tilemap remap,
both immutable-image queues remain full, and 33 later candidates are dropped.
The resulting accepted controls contain accumulated 6-15-pixel motion.

Rejected `3a5f3694…` first decoupled latest coherent X1 scroll from immutable
image ownership. Its validator nevertheless sampled only frames on which the
30 Hz source changed. It reported 49 correct three-pixel registrations while
silently skipping the intervening held frames. Reanalysis over every consecutive
video frame exposes the user-visible `hold, +3` cadence: 48 holds and 49
three-pixel jumps.

Preserved `21abe04c…` retains the 60 Hz presentation cursor at `$72B4` but makes
the camera and displayed-map authorities explicit. `$72B2` is now the common
modulo-32 camera phase: a raw source-column jump across the X1 two-slot gap is
reduced to the real -3-pixel motion. Before each exact tilemap DMA, the foreground
compares all sixteen new/applied physical-column mappings with the displayed map
at `$72F0-$72FF`. A modal delta is accepted only with at least 9/16 agreement;
sparse/unrelated transitions instead seed source column 4 in the unwrapped phase
domain. NMI installs only that prepared basis after the paired map is visible.

The path took several deliberately rejected builds. `b1e57e0e…` achieved the
1/2-pixel cadence but flashed at map publication. `d43c8bb4…` committed the
coarse rebase one video frame late. `562928a5…` moved it into the correct NMI but
still had nine discontinuities because Poppy accepted `stz $7E72B9` even though
65816 has no long `STZ`, emitting bank-relative `9C B9 72`; the commit marker
never cleared and later unrelated DMAs repeated the rebase. The final source uses
`LDA #0 / STA long` for both marker clears. Packer guards pin the legal bytes,
same-NMI call count, and one-shot marker protocol.

Fresh post-Start evidence rejected three later anchor policies. `b5ce230b…`
trusted source column 0 and injected a 64-pixel rebase when that column crossed
the X1 gap. `686bc109…` moved the anchor to column 4, but the gap migrates and
that column later detached by two slots while the other thirteen did not move.
`4279fb5b…` used the modal 16-column delta and fixed those gameplay rotations,
but accepted a weak 3/16 relationship between the sparse title map and the first
full gameplay map, producing a persistent 64-pixel black band after Start. Those
negative runs are retained under their hash-prefixed directories in
`/home/chad/supermn-snes-artifacts/active/`; none is a handoff ROM.

Its focused real-65816/PPU bridge is green 16/16, including the exact
sparse title-to-gameplay map, an isolated column crossing the gap, a real
thirteen-column rotation, and a raw -67 jump unwrapped to -3. The exact-hash
fresh-power gate retains 601 consecutive post-Start frames 5,512–6,112 / ticks
190–490 and is framebuffer-clear. Its every-frame temporal report has 152 exact
-3 source changes, 151 one-pixel and 152 two-pixel visible registrations, no
holds/reversals/oversized steps, and zero mismatch at all 15 displayed-map
changes. Sol manually reviewed the full contact sheet and former rebase points.
Evidence is under
`/home/chad/supermn-snes-artifacts/active/21abe04c-fresh-neutral-poststart600-v1/`.

Preserved `382b76a4…` extends the same cursor to world-space OAM. X1's foreground
plane mixes fixed top/bottom HUD records with player, crate, pillar, enemy, and
other world records. A renderer-only OAM upload therefore made those objects
hold and jump against the integrated BG. Foreground commit now copies one
immutable 544-byte OAM image, records only playfield-world X fields, and retains
the union of old/new active spans. NMI applies the cursor delta and publishes a
compact active low-table span plus the complete high table; fixed HUD records do
not move. A base-delta pending state is never downgraded by camera alignment, so
a shrinking list cannot leave stale objects visible.

The wake deadline is evaluated before tile-queue priority. Every due wake samples
the quiescent X1 camera before presentation; the rejected tile-first ordering
alternated between early and late source publication and produced a measurable
2/2/hold cadence. The current exact-hash fresh temporal gate measures 153 exact
-3 source changes as 152 one-pixel and 153 two-pixel moves with no holds,
reversals, oversized steps, or BG discontinuities. Its OBJ gate is green across
599 post-warmup frames and 358 same-base transitions with zero violations. The
focused real-65816/PPU bridge is green 21/21. Evidence is under
`/home/chad/supermn-snes-artifacts/active/382b76a4-build-diagnostics-v1/` and
`/home/chad/supermn-snes-artifacts/active/382b76a4-fresh-poststart600-v1/`.

Rejected `60481722…` attempted to correct the later human-reported
fence/black-column failure by removing the exact-layout `+64` crop. That
diagnosis used a resized 384-pixel X1 image rather than the canonical
`(64,1)-(320,225)` crop. Correct registration shows the predecessor background
was aligned and `60481722…` moved it 64 pixels in the opposite direction.

The actual failure was a stale modal displayed-map basis. Chad's checkpoint
serialized `$A0`, but the immutable image's source-column-4 slot, paired raw X,
and unwrapped phase prove absolute basis `$60`. Exact HScroll therefore remains
`64 + signed8($60-$66) = $3A` (58). Current source prepares
`slot4*32 + phase - raw4 (mod 256)` for every exact image and installs it only
after the paired map DMA. The bridge is green 22/22, including absolute zero,
isolated gap crossings, whole rotations, and the `$A0->$60/$66/$3A` fence case.

Rejected `36d664e6…` first carried this math but exposed an independent NMI
deadlock. ACK `$0100` was read in A8 as low byte zero, so the presentation gate
mistook a live renderer for boot, skipped BG/OAM forever, and left foreground
waiting on OAM due `3`. Its fresh 601-frame temporal gate is red: 303 held
moving-camera transitions and no PPU motion for 456 pixels of source motion.

Rejected `893d467b…` tests the complete request/ACK readiness state. In the exact
red checkpoint, the first NMI clears due `3`; ACK, render generations, and OAM
publication resume. The supplied fence state requires two explicitly logged
old-hash provenance bytes, then eight attack/right phases keep Superman at world
X 224 and HScroll 58 with no halt or invalid task context. Sol manually reviewed
the canonical X1/SNES side-by-side: fence, wall, windows, doorway, and floor are
aligned and the gross vertical black band is absent. Evidence is under
`/home/chad/supermn-snes-artifacts/active/893d467b-frame-counter-fix-v1/`.
The checkpoint is not an aligned MAME oracle: its tick-3718 work image differs
from canonical MAME in 2,291 bytes, including player health and position.

The fresh `893d467b…` gate exposed a persistent native-record failure after that
recovery. Slot 2 published code `$19AE` but kept 127 bytes of Mode-7 data. A
passive two-frame trace proves the exact sequence was owner publication, tile
DMA helper, direct path, `MDMAEN=$01`, and return with the destination unchanged.
For that transfer `HVBJOY=$C2` still reported VBlank while `OPVCT=$0000`: the
status and counter straddled the line-0 boundary. The low-page path lacked a
minimum-line check and mistook line 0 for lines 225-255. Rejected `b92ac14f…`
retired the line-256+ tiers but did not address this low-page race.

Historical `f25a0e68…` permits low-page direct DMA only at `OPVCT >= $E1`; lower
lines and every high-page descriptor publish for the next NMI. Packer guards
pin the helper seams, the low-page floor, the high-page publish branch, and its
inert retired tier. At exact fresh frame 5,250, slot 2 matches its ROM record
128/128 bytes. The current organic coin/Start movie then retains 601 consecutive
clear post-Start frames 5,704-6,304; its every-frame temporal gate is green with
302 PPU steps, 151 source steps, and no wrong registration or discontinuity.
Sol reviewed the contact sheet and representative frames 100/300/600.

This does not make the renderer fast or prove later stages. Aligned MAME pixels,
formal MAME-frame conservation, organic Stage 2 and later coverage, performance,
hardware, and human combat/audio acceptance remain open.

## Current bounded clear: prepared raw BG baseline (August 13, 2026)

Exact ROM `c6ec69a1…` organically consumes a credit and starts Stage 1. Corrected
movie replay proves 457 consecutive actual video frames (5,634–6,090), all with
HUD/OBJ over an absent BG. The older 601-sample controller capture is negative
evidence but is not consecutive-frame coverage. VRAM map
and native tile bytes are present and the live X1 shadow contains the complete
392-cell scene. The failure is consumer state: primary prepared (`$FFFE`)
promotion copies `$D8A0`'s exact logical map, `$E8A0`'s sorted codes, and
`$EA20`'s palette map, but leaves canonical raw planes `$2000/$2400` holding
the preceding 35-cell title image. Later sparse/clean candidates are defined
relative to those planes, so they erase or retain the wrong scene even though
the prepared transition itself was exact.

In rejected `d4873020…`, `prepared_bg_cache_reconstruct` ran only during queued
primary prepared promotion, before dynamic column remapping. It uses the immutable logical offset table at
5A22 `$EF:6800` to invert each prepared TL map word, recover the sorted arcade
code and arcade palette bank, reverse the single-axis flip mapping, and publish
big-endian canonical code/color words. The lazy WRAM promoter grows from `$026A`
to `$026E`; the packer checks both the new span and its `$E9:C400` call.

The initial cache-only proof restored the scene but exposed black tile chunks.
Its prepared graphics list contains 178 consecutive 128-byte records; the old
`$1700` chunk size consumed the VBlank window and corrupted record tails at
physical slots 46 and 138. Preserved `50bbed41…` reduced that to `$1600`, and
both DMA wait paths reset the OPVCT phase with `STAT78`. A phase reset alone was
tested and rejected as insufficient.

The later every-frame OBJ publisher added bounded NMI work before the tile DMA.
Rejected `dde99419…` proved that `$1600` no longer retained its two-record margin:
fresh checkpoints found corrupt records 43/44, 87/88, 131/132, and 175/176 at
every 44-record boundary. Preserved `382b76a4…` introduced `$1500`, exactly 42
complete records, and current `f25a0e68…` retains it. All former boundary records
are exact in the predecessor's fresh 601-frame gate, and
the manually reviewed contact sheet contains no missing/partial tiles or vertical
bands.

Actual assembled-helper execution also caught and rejected an initial
`$EF:E800` table reference: the table is SA-1 `$9E:E800` at file `$2F6800`, so
the 5A22 address is `$EF:6800`. With that corrected, the actual helper and
promoter produce raw code/color planes byte-identical to live X1. The 500-frame
intervened continuation has 178/178 exact graphics records and no structural,
palette, or stale-target mismatch; manually inspected frames 50, 200, and 500
and the full 50-frame checkpoint contact sheet show the complete scrolling
background without black chunks. The corresponding X1 source sheet confirms the
early gray-green palette transition is not SNES-only. Evidence is
`build/playback-watcher-20260813/c6ec-assembled-prepared-dma1600-proof-v3/`
and `c6ec-assembled-prepared-dma1600-proof-v3-final-cache-v1/`; the corrupted
expected/observed records remain in `c6ec-prepared-cache-proof-v4-final-cache-v3/`.

Rejected ROM `d4873020…` contains the queued-path bytes, but its fresh gate is
still red. `snapshot_acquire_paced` takes the direct prepared path through
`psd_prepared_dma`; that path copies BGMAP, sorted codes, and palette map without
calling the reconstructor. A same-hash `$E9:C400` execution hook remains silent
while live X1 changes to 392 Stage-1 cells and the raw cache remains the exact
35-cell title image. The queue-only intervention therefore proved its named
branch but did not cover organic fresh execution.

Its fresh evidence and reviewed contact sheet are in
`d487-fresh-poststart-framebuffers-v2`; helper-flow evidence is
`d487-organic-helper-poststart0-v1`.

Historical `50bbed41…` places the same `$E9:C400` reconstruction call after the
direct prepared map/list/palette snapshot. Pack-time guards require exactly one
call in both direct and queued consumers. Its organic fresh movie retains 602
consecutive post-Start frames. The old 50-frame grace flags only the real
Stage-1 fade (black 50–65, dark/gray through 89); manual review shows geometry
from frame 66 and the complete wall/floor/palette by frame 90. Authenticated
offline reanalysis verifies every PNG and is clear from frame 100 through 601.
At frame 100 the raw code/color planes match live X1 byte-for-byte, structural
ownership is 392/392, and all 178 native BG graphics records match. Evidence is
under `50bbed41-fresh-poststart-framebuffers-v1`,
`50bbed41-fresh-poststart-x1-100-v2`, and
`50bbed41-fresh-poststart-inspect-100-v1`. This closes the reproduced missing-BG
regression, not aligned-MAME pixels, temporal conservation, later-stage coverage,
performance, hardware, or gameplay acceptance.

## Current correction: bank-safe per-column vertical scroll (August 12, 2026)

Preserved unaccepted candidate `c6ec69a1…` added the per-column vertical-scroll
capture and Mode-2 window path on top of the blank-slot/map-authority repair.
Rejected predecessor `95b44eb7…` used `sta $7E74C0,y`; that addressing mode does
not exist on 65816, and the then-used compiler emitted DB-relative absolute,Y bytes
`99 C0 74`. Those stores corrupted the arcade boot RAM test, which is why the ROM
stayed on the loading screen despite passing the focused renderer fixture. The
latest `astrobleem/poppy` fork now rejects this invalid-operand class; the packer
guard remains to pin the project's intended legal byte sequence.

The repaired capture preserves X, transfers Y to X, and uses legal long,X:
`DA BB 9F C0 74 7E FA`. `tools/build_interp_rom.py` rejects the bad encoding and
requires this sequence. A bounded exact-hash cold-boot smoke reaches tick 185,
render 89, PC `$0818`, Mode 2, halt zero; the focused real-5A22/PPU bridge gate is
green 10/10.

Both supplied old Mesen states now rebuild to complete, settled Mode-2 frames
under an explicit checkpoint migration. State one proves 384/384 final target
owners from 442 occupied source cells and 58 intentional X1 draw-order overlaps;
state two proves 392/392 without overlap. Both have zero unclaimed stale cells,
palette mismatches, or native-graphics mismatches, and their dynamic offset
tables match their live/applied column maps. A first-idle black half-screen was
Mesen screenshot latency: the identical coherent state shows the complete frame
after two parked PPU frames. These remain intervened structural/pixel-availability
diagnostics. Exact aligned-MAME pixels and formal temporal conservation remain
open.

## Preserved correction: blank BG slot and one map authority (August 12, 2026)

Preserved predecessor `6413924c…` repairs the live scrolling
corruption reproduced from Chad's Mesen state. Empty heavy-render cells are map
word zero, and authenticated arcade graphics record zero is 128 blank bytes.
Physical SNES BG slot zero is therefore permanently reserved and uploaded as
blank; nonempty dynamic and immutable C0BC records use slots 1–191. The C0BC
packer asserts record zero is blank, and `tools/test_bg_blank_slot_invariant.py`
audits source plus the built ROM.

This was necessary but not sufficient. Commit `6aef22a` had introduced a sparse
map gate that could suppress a PPU tilemap upload while leaving the newer staging
map and cache state live. Subsequent incremental work then used a map the PPU had
never displayed as its authority and could eventually publish missing columns.
That path removes the split: every completed staging map reaches
`bg_upload_commit`; there is no sparse suppression helper. A controlled
tick-2,437 cross-ROM migration is clear for 273 consecutive post-vblank frames
while scrolling Right, but that is diagnostic-only. Fresh boot, aligned MAME
pixels, and formal every-video-frame conservation for this exact hash remain
open; see [STATUS.md](STATUS.md) and [VALIDATION.md](VALIDATION.md).

## Current correction: one-shot scale-only SA-1 boot ownership (July 23, 2026)

The opening statement above describes the June bring-up and is historical: production now renders
the game. Exact v130 replaced the long black SA-1/interpreter initialization interval with a
temporary 5A22-owned Mode 7 activity screen, but its rotating shield made the tester dizzy.
v131 made the logo static. At the tester's request, v133 retains the no-rotation rule while adding
one huge-to-fitted scale animation that never repeats.

`tools/gen_boot_screen.py` deterministically creates a 32 KiB asset:

| Asset region | Offset | Size | Purpose |
|---|---:|---:|---|
| Mode 7 map low bytes | `$0000` | `$4000` | 128×128 low-byte tilemap |
| Mode 7 tile high bytes | `$4000` | `$2800` | blank tile + 150 indexed logo tiles |
| OBJ font tiles | `$6800` | `$1000` | static status text + heartbeat diamond |
| OAM | `$7800` | `$0220` | 56 text sprites + one 8×8 activity sprite |
| CGRAM | `$7C00` | `$0200` | boot palette |
| Mode 7 A/B/C/D table | `$7E00` | `$0200` | 64 monotonic scale-only identity matrices |

The packer regenerates and places that asset at file `$300000-$307FFF` (5A22
`$F0:0000-$7FFF`) and asserts every DMA seam plus SHA-256
`e8d6b5f6c3d77d646eaa695c47d1e74c2c040a56e24d359fa067c3d749ea8734`.
The 120×80, 92-color logo is a compact indexed derivative of the user-supplied
`/home/chad/data/sa1-logo.png` (source SHA-256
`091e5831c949a8c686e35ff8ba1e77fccd4bbbf0b6ed173c821bd9494516b3c6`; decoded
palette-plus-pixels SHA-256
`c85b266b610ff7dd08ad860369d17170c891ead78f37aff4322836a5ad7c2d09`).
It contains no arcade graphics.

`boot_screen_init` is fixed at `$E9:F000`. It forces blank only during one-time setup, DMAs the
map/tiles/font/OAM/CGRAM, copies the matrix table to private WRAM `$7E:F100`, selects Mode 7 BG1 +
OBJ, starts A=D at `$0020`, centers the matrix, and restores brightness 15. `$7E:1F1B` bit 7 owns
the screen, bit 6 latches completion, and its low six bits are the table/heartbeat phase. The
WRAM-mirrored `boot_mode7_tick` runs once per NMI. During its first pass it increases A and D
strictly to `$00C0`; B and C are zero in all 64 table entries, so the logo cannot rotate or shear.
After entry 63, matrix updates stop permanently and only CGRAM color 131 alternates between two
amber values for the small activity diamond. It does not touch the SA-1 scheduler or pretend to
measure boot percentage.

The first real game renderer clears `$1F1B` before claiming the display. In the fresh exact-Mesen
2.1.1 capture
`build/user-playtest-v105-investigation/v133-final-boot-zoom-mesen211-fresh-v1/`, exact-v133 frame
17 is an extreme close-up, frame 50 is intermediate, and frame 86 is fitted and geometrically
static afterward. All remain Mode 7 at brightness 15 with forced blank clear. The packer asserts
the `$0020/$00C0` endpoints, A=D, B=C=0, and strict monotonicity. A same-ROM continuation from an
exact-v133 fresh-power title checkpoint remains live through frame 9,000 / tick 1,726 /
render 1,493. After game ownership clears bit 7, NMI overhead is only the call and inactive-flag
branch/return.

See the
[v133 title/attract/boot handoff](../history/handoffs/V133_TITLE_ATTRACT_BOOT_20260723.md).
The status strings describe
high-level liveness (`ROM LOADED`, `SA-1 68000 CORE ACTIVE`, `ARCADE BOOT IN PROGRESS`); they are
not claims that a particular internal RAM/ROM test is active.

## The one hard-won rule: dispatch every memory store by destination bank

Production maps MC68000 work RAM `$F0xxxx` to SA-1 BW-RAM `$40:xxxx` and video
shadow to `$41`. The chronological stage notes below sometimes retain their early
5A22 `$7E/$7F` naming; do not copy those bank literals into new code.

Many early store handlers hardcoded the work-RAM path because no device stores had
landed yet. That becomes corruption as soon as an instruction targets a hardware
bank: `$B00000 & $FFFF = $0000`, so a work-RAM-only fast path writes the emulated
`$F00000` bytes instead of palette state.

- This is exactly the bug that set `tmask $0003 → $7BDE` this session: the sprite
  copy `move.l (A0)+,(A1)+` at 68K `$08DE` with `A1=$B00000` was writing the task
  table. Fix was to gate `op_movl_anp_anp`'s dest write on `dst An high16 == $00F0`.

**Before adding any real hardware-write path, audit EVERY store handler.** The
correct architecture is a single dispatch on the destination's 68K high byte:

| 68K addr (high) | Region (arcade)            | Action |
|---|---|---|
| `$F0xxxx` | 68K work RAM               | write BW-RAM `$40:(addr&$FFFF)` |
| `$B0xxxx` | **palette RAM (xRGB555, 4KB / 2048 colors)** | → SNES CGRAM path |
| `$D0xxxx` | **sprite Y-low / scroll RAM / ctrl regs (`$D00600`)** | → SNES OAM-Y + BG scroll |
| `$E0xxxx` | **sprite code + X + color (16KB)** | → SNES OAM + BG tilemap |
| `$30/$40/$60 xxxx` | observed per-frame ignored/control writes | no-op or diagnostic shadow; not pixel data |
| else | I/O (`$50` DIP, `$80` sound, `$90` C-Chip) | existing readbyte stubs / no-op |

> **CORRECTION (Stage 0, June 2026, data-verified).** An earlier version of this
> table called `$B00000` the OBJ/sprite bank and the `$08DE`/`$08E2` loop "the OBJ
> DMA." That was WRONG. A live MAME write-stream capture
> (`tools/mame-trace/capture_video_stream.lua` → `video_writes.log`) shows the
> `$08E2` loop writes **palette** to `$B00000`, and the live `$B00000` contents are
> **byte-identical to the validated `c_palette.bin`**. The bank roles above match the
> validated decode (`tools/build_snes_full_scene.py`, `dump_frame_clean.lua`):
> `$B0`=palette, `$E0`=sprite code/X, `$D0`=sprite Y/scroll. The 32-bytes-per-iteration
> the `$08E2` loop copies from work RAM (`$F01712`...) is **16 colors × 2 bytes = one
> palette bank**, not a sprite struct. Verified write PCs (live, gameplay frame 3000):
> `$08E2`→`$B0` palette; `$15B8`/`$17AA-$17B4`→`$E0` sprite code/X; `$26F0`/`$26F2`→`$D0`
> Y/scroll, `$26CC`/`$26D2`→`$D00604/$D00606` ctrl; `$3A9C`→`$600000`, `$3AA2`→`$300000`,
> `$3AB0`→`$400000` (all constant `$0010`). All writes are word-size to even addresses.

Address-map authority is now the
[address-map adaptation guide](../toolchain/ADDRESS_MAP_ADAPTATION.md); the original
lowering decision remains in
[the historical transpiler design](../history/designs/TRANSPILER_DESIGN.md).
Use `$B00000/$D00000/$E00000/$F00000`; older digit-dropped spellings are wrong.
Cross-check every bank against MAME's `taito_x.cpp` mapping before trusting it.

Recommendation: write `store8/store16/store32(addr_hi16, addr_lo16, value)` helpers
that do the bank dispatch **once**, and route every store handler through them
(`writebyte/writeword/writelong` already do the `$F0`-only check — generalize those
and make the predecrement/postincrement/movem/clr handlers call them instead of
inlining the BW-RAM bank). Historical work-RAM-only handlers included
`op_movl_anp_anp`
(now gated), `op_clrw_pre`, `op_movw_imm_pre`, `op_movw_dn_predec`,
`op_movw_d16_predec`, `op_pea*` (stack pushes — always `$F0`, fine), the `movem`
family, and the `op_*_predec/_anp/_d16` stores I added this session (most already
gained an explicit `cmp #$00F0` gate — grep for `cmp #$00F0`).

## Where the boot actually touches video (observed, live)

These are real PCs hit by the running game loop — good breakpoints/taps for
capturing the write streams MAME produces vs what we emit:

- **Per-frame video control-reg writes** (Stage-0 verified PCs, may differ from the
  interpreter's PCs above; these are MAME ground truth): `$3A9C`→`$600000`,
  `$3AA2`→`$300000`, `$3AB0`→`$400000`, each a word write of constant `$0010` once per
  frame. MAME maps them as ignored writes. They do not carry pixel data; preserve
  observed cadence/side effects rather than assigning an unproved enable/ACK meaning.
- **Video RAM clear** — `$2692 clr.w (A0)+` loop, `A0=$E00800` (clears the sprite
  region at boot). Handler `op_clrw_anp` already no-ops non-`$F0`.
- **PALETTE upload** — `$08E2 move.l (A0)+,(A1)+`, `A1=$B00000`, inside a bit-masked
  loop (`~$08C2`–`$08F2`) driven by `D6=($F01B12)`: per set bit it copies 8 longs
  (32 bytes = **16 colors**) from a work-RAM palette buffer (`A0=$F01712+`) to
  `$B00000+` (one palette bank), else skips `$20`. **This is the per-frame palette
  upload** (NOT the OBJ DMA — see CORRECTION above). Shadow `$B00000` → convert
  xRGB555→xBGR555 → CGRAM.
- **Sprite attributes** — sprite code/X/color written to `$E00000` (PCs `$15B8`,
  `$17AA`–`$17B4`) and sprite Y/scroll/ctrl to `$D00000`/`$D00600` (PCs `$26CC`,
  `$26D2`, `$26F0`, `$26F2`). These (+ palette) are the full per-frame video state;
  shadow them and run the validated decode (`build_snes_full_scene.py`) at runtime.

## Inputs (needed for an interactive frame)

C-Chip data port `$900001/3/5` is read by the frame-work as the **input mailbox**
(P1/P2/coins, active-low, idle `$FF`). In `readbyte`, phase-1 (`$A8=1`, last cmd
`$62 != $01`) returns `$FF`. To make the game respond, map SNES controller state →
those reads (invert: active-low). The C-Chip **GWK download** path (`$62==$01`)
must keep replaying `cchip_boot_response.bin` — don't break it (see
[the C-Chip boot contract](CCHIP_BOOT_HANDSHAKE.md)).

## How to develop/verify the plumbing

1. **Capture the oracle.** In MAME, `install_write_tap` over `$300000-$6FFFFF` and
   `$B00000-$Bxxxxx` (and `$E0xxxx`); log `(PC, addr, value)` per frame for a few
   boot frames. That is the exact target write stream. (Same tap infra as
   `tools/mame-trace/trace_io_diff.lua`.)
2. **Decode the formats.** Sprite struct at `$F01712` → X1-001 OBJ attributes →
   SNES OAM. The graphics *decode* is already validated end-to-end
   in the [palette evidence](../toolchain/GRAPHICS_PALETTE_EVIDENCE.md); this phase is
   *transport*, hooking those writes to the proven PPU path, not re-deriving formats.
3. **Liveness/sync probes** (proven this session):
   - `$F01C56` (work RAM `$11C56`) = per-frame counter, increments every frame —
     heartbeat to confirm frame timing.
   - iloop ring index `$48` and the VBLANK countdown `$8A` — "is the interpreter
     loop even running" (both froze on the `idone` infinite loop).
   - `tmask` at `$F00002` should hold `$0003` (matches MAME); any drift means a
     store handler is clobbering the task table (bank-dispatch bug).
4. **Compare** a rendered frame to MAME through the
   [MAME/Nexen differential path](../toolchain/DIFFERENTIAL_VALIDATION.md).

## Progress (June 2026)

- **Stage 0 ✓** capture+reconcile ($B00000 = palette, confirmed byte-identical).
- **Stage 1 ✓** store dispatch + `$7E` shadow (optest 154/154; boot intact; shadow populated).
- **Stage 2 ✓** palette → CGRAM, byte-exact 100% on real PPU (`tools/check_cgram.py`).
- **Stage 3 ✓ (substantially)** OBJ sprites render on the real PPU from the live game:
  `gfx1` embedded (4MB ROM); `decode_tile` validated 128/128 vs Python
  (`tools/check_decode.py`); `vid_obj` builds OAM + decodes tiles to VRAM + assigns
  OBJ palette banks dynamically; recognizable arcade sprites display. Two known
  limits: no tile dedup (per-sprite tiles, 64-sprite cap) and 8 OBJ palettes (excess
  banks fall back to palette 0 → some sprites show wrong colors). `vid_obj` is gated on
  liveness (`tmask==$0003`) so it never runs on garbage shadow during boot.
- **Stage 4 ✓** BG playfield (`vid_bg`: tilemap + tiles + scroll). An injected MAME
  gameplay frame renders the **actual scene** (church / GAME-OVER / steps / railings) —
  BG + OBJ + palette all correct (`tools/check_render.py`). Bugs fixed along the way:
  `copy128`'s nonexistent `lda long,Y`; and four `STZ long,X` clears that the assembler
  truncated to `STZ abs,X` (DBR=$7F) → they wrote $7F (corrupting work RAM) and never
  cleared $7E (hash uncleared → hang; OAM/tilemap garbage). See
  [the Poppy assembler gotchas](../toolchain/DEBUGGING.md#2-poppy-assembler-gotchas-65816-pasm).
- **Stage 5 ✓** BG tile cache: open-addressing **hash dedup** (O(1)) + **per-tile VRAM
  DMA** (no staging cap, 191 artwork codes plus reserved blank slot zero = VRAM budget).
  The live game now runs ~180x
  faster than the old O(n^2) linear scan (~18 vs ~0.1 interp-steps/frame).

## Polish status (the four follow-ups)

- **Vblank-timed DMA ✓ (implementation superseded by R9).** The June path made `vid_frame`
  force blank around each foreground upload. A real Mesen 2.1.1 playtest later exposed those pulses
  as horizontal bars and showed that large transfers could outlive VBlank. Production now
  publishes descriptors through `$7E:1F11`; NMI services them after the established scheduler wake,
  splits large background uploads, and permits small VBlank-tail batches only under size-aware
  scanline limits. Preserve the old wording as history, not current architecture.
- **Pixel-diff vs MAME ✓ (integration validated)** `tools/render_arcade_ref.py` is a
  pure-Python (no numpy/PIL) port of the validated `render_full_frame.py` decode; it
  renders the same `c_*.bin` to `/tmp/arcade_ref.png` (47 colors, matching MAME). The
  interp's `check_render.py` output is a 256-wide SNES crop of that exact scene (church
  doors / arched window / brick wall / GAME-OVER / steps / status bar) with matching
  colors. NB: MAME can't be screenshotted through the headless MCP (`-video none`), so a
  per-pixel MAME diff isn't available here; palette→CGRAM (byte-exact) and decode_tile
  (128/128) are the quantitative checks, plus this visual integration match.
- **OBJ tile dedup ✓** `obj_slot` (own hash $7E:A800, 16-wide tile grid) lets multiple
  sprites share one decoded tile, so up to 128 sprites (OAM limit) need <=64 distinct
  tiles. Injected MAME frame renders 98 sprites (was 52), incl. the flying Superman.
- **Cross-frame BG tile cache ✓** The BG hash ($7E:A000) + its decoded VRAM tiles persist
  across game-frames; `bg_slot` hits skip decode+DMA, so a static playfield is nearly
  free to re-render. Eviction = full-clear when >=160/192 slots used; one-time clear at
  `vid_init`. The tilemap and palettes are still rebuilt every frame (cheap).

**Both required a one-time enabler: the render subsystem was relocated to ROM bank $E9**
(`src/video.pasm`, assembled @ $8000 -> placed @ $E9:8000 = file $298000) because the
interp bank was full. The interp keeps hot-path `map_snes` + a `test_or_vid` stub and
reaches the moved code via 3 `jsl`/`jml` wrappers (VID_FRAME=$E98000 / VID_INIT=$E98004 /
VIDTEST=$E98008) that bridge `rts`<->`rtl`. Interp bank free: 126 B -> 1930 B.
- **Stage 5 ◐** BG has a sequential decode-once-per-frame tile cache (64 slots). Remaining:
  OBJ dedup, cross-frame LRU, larger BG cache (one frame has ~120 distinct BG codes > 64),
  per-frame decode cap.

## Render validation (`tools/check_render.py`)

Built a **TESTFLAG=2 ROM mode** (`vidtest`): skips the 68K interpreter and renders whatever
is in the `$7E` shadow, on a go-flag, **once then halts** (stable VRAM/OAM/screen to read).
`check_render.py` injects MAME's captured gameplay-frame state (`c_palette` / `c_spritecode_full`
/ `c_spriteylow`, byte-swapped to the arcade big-endian shadow layout) and screenshots. This
**pixel-validates the render pipeline on real data without the interpreter reaching gameplay**.
Findings: palette/CGRAM byte-exact; OBJ sprites render; it **caught the `bg_ent` 16-bit-immediate
width bug** (fixed) and the open BG-tile-staging bug above. NB: the render loop must DMA only
once and halt — a continuous loop DMAs mid-display (garbage frames) and makes VRAM reads
unreliable (they catch mid-DMA).

Lesson added Stage 3: **every counted loop's terminal value must be reachable by the
step.** A `cpx #$0200` with X stepping by 4 from 1 (1,5,9,…) never equals 512 → the
loop ran away writing across `$7E` into `$7F` work RAM and hung the game (F01C56 froze).
Use a reachable bound (`cpx #$0201`).

## Implementation lessons (Stages 1–2, June 2026 — these cost hours, heed them)

- **NEVER insert interp code mid-file. Add it in the `$F800` free block.** The
  interpreter bank ($8000–$FFFF) is dense with `bra`/`bcc` short branches (±127).
  Inserting a routine mid-file shifts subsequent code and silently pushes some
  branch out of range — **Poppy does NOT error, it wraps the offset**, corrupting a
  handler far from the edit. Symptom: the boot reaches a *different* PC and hard-hangs
  on a perfectly-valid opcode (we hit `move.w D7,D1` at `$04A2` via trap#1). Fix:
  there is ~2KB free at `$F800–$FFDF`; put all new routines there under `.org $F800`
  and `jsr` to them (position-independent within the bank). `vid_init`/`vid_frame`
  are called from reset/iloop via a single `jsr` each (≈3-byte shift, safe).
- **Poppy tracks the M/X width linearly from `rep`/`sep`; a routine reached only by
  `jsr` inherits the PRECEDING routine's width, not its caller's.** A 16-bit routine
  placed right after a `sep #$20`-ending routine gets its `and #$....` immediates
  emitted as **8-bit (2-byte)** operands; at runtime (16-bit M) the CPU reads a 3-byte
  immediate and the whole routine desyncs. Symptom: a math routine returns
  plausible-but-wrong values (our `snes_color($7BDE)` gave `$051D`). Fix: start every
  16-bit routine in the `$F800` block with an explicit `rep #$30` (no-op at runtime,
  corrects the assembler). Verify with `xxd` that `and #$001F` is `29 1F 00`, not `29 1F`.
- **Flush cadence: build+DMA once per *simulated* game-frame (at the `$8A` reload),
  not per real vblank.** The interpreter is ~100× slower than realtime, so the game
  emits a new frame only every few hundred real frames; flushing 60×/s cripples it.
  A per-instruction vblank poll is also too costly — drop it. DMA at the game-frame
  boundary; the image is static between game-frames so a mid-frame DMA glitch is
  invisible. (Validated via `tools/check_cgram.py`: CGRAM == `snes_color(shadow)` 100%.)

## Gotchas learned this session (saves time later)

- **Decode the FULL `mmmrrr`.** I froze the boot for a long while because I read
  `$309A` as `move.w (A2)+,D0` when it is `move.w (A2)+,(A0)` (mem→mem). Always
  decode dest mode (bits 8-6) *and* source mode (bits 5-3), not just "Dn dest".
- **Unimplemented opcode = hard hang, not a clean error.** `src/interp.pasm`'s
  `idone` is `bra ispin` (spin forever). A frozen iloop ring index `$48` is the
  signal. A small Python simulator of the `kNN` dispatch chain (parse
  `lda $44/and/cmp/bne/beq/bra/jmp` + a `pha/pla` stack) tells you which handler an
  opcode *actually* routes to — invaluable for "this should be handled but isn't".
- **Dispatch masks must match the field you compare.** Found a real bug: addq/subq
  `(d16,An)` were masked `$F1C8` but compared to `$5068` — impossible to match, so
  the handlers were dead. The mask must keep every bit present in the compare value.
- **MAME's main PC parks at `$081A` forever**; the game runs entirely inside the
  VBLANK ISR + cooperative tasks. Don't expect the "main" PC to move — sample the
  scheduler/task state and per-frame side effects instead.
