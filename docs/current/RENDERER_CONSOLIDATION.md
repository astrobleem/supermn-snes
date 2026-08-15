# Renderer consolidation contract

This document defines the renderer work required after the rejected
`f25a0e684180cd0d1998f85569deae05cef0e8e89ab0f0188134f32f388ab835`
ROM. Current response candidate
`d01db972b1c764a5969d40bb84649d2db7df7c92a03c3b3eb5407f0ad9f73b28`
is still governed by this contract. It is a design and validation contract, not
a playable-ROM claim.

## August 15 stop checkpoint

The fixed-Poppy `d01db972…` fresh run retained 602 consecutive post-Start
framebuffers. Sol's review and the machine reports found two independent
renderer failures. Prepared BG graphics use `$1500`-byte chunks; the final
128-byte record at every boundary is truncated, producing persistent fragments
in slots 42/84/126/168. An intervened frame-41 lab reduced the chunk to `$1400`
and made all four records exact with halt zero. Current source carries that
change, but no successor ROM has been built.

The OAM failure is structural: `obj_present_commit` invalidates and overwrites
the sole presentation buffer across an NMI. That NMI advances BG first, sees OBJ
pending `$80`, and retains prior-camera hardware OAM for one frame. The next
candidate must retain an immutable last-published OAM/list path during candidate
construction. The broader complete-scene contract below remains open; no full
gameplay replay has been started.

## August 14 response-candidate result

The reproduced progressive black vertical void had a concrete tilemap-lifetime
cause. During a one-column canonical-layout rotation, the incremental path
cleared the old physical slot and the new physical slot, published the new lookup,
then appended the source column as dirty. The source-code cache correctly treated
unchanged cells as hits, but that meant it emitted no map words for the cleared
destination. Each transition therefore removed another complete physical slot:
four SNES tile columns across 32 tilemap rows, or 112 nonzero Stage-1 words.

Predecessor `72838eca…` moves that complete 4-by-32 slot first, clears only the old
slot, then publishes the new lookup. Pack guards pin that order and the complete
helper bytes. The real-65816/PPU bridge is green 30/30, including an independently
seeded 4 KiB map proving that the source is retained, the destination is exact,
and unrelated bytes are unchanged. The row-offset fixture covers all 32 X1 cells;
each 16-pixel X1 row spans two SNES tilemap rows, so the six-shift
`(cell & ~1) * 64` stride is intentional. The rejected five-shift experiment
`d2864e99…` was based on the wrong row-height model and is not part of current
source.

Bounded continuation from an inspector-proven clean predecessor frame keeps
1,568/2,048 physical tilemap words nonzero at relative frames
0/100/140/150/180/200/240/260. Sol opened the former failure interval and the
same-ROM tail; the growing black void is absent. The fresh-post-Start gate now
measures vertical black runs only in the upper BG field, so a real missing BG
slot cannot be diluted by the independently drawn floor. Its limit is 16 pixels:
the legitimate gold-column interior is nine pixels, while a missing physical
slot is 32 pixels.

This closes only the slot-loss cause under bounded checkpoint coverage. The old
261-frame pause/step report remains red, but the acquisition can stop before the
current PPU frame's NMI completes and then cross two presentations before the next
state. It is therefore not a natural-cadence oracle.

An uninterrupted hook trace exposed two concrete presentation-ownership failures.
The old common NMI path treated a pending DMA0 descriptor as if it had consumed the
current VBlank, suppressing BG/OBJ presentation. The OBJ-pattern batch separately
marked a VBlank presented before its time checks and reserved the frame for patterns.
Rejected `f8ab5339…` removed the pending-descriptor proxy but retained missing
frames. Rejected `ebdd33c5…` called the presenter from inside the late batch path;
it eliminated missing frames but duplicated both BG and OBJ publication on 15
complete frames.

Predecessor `927a2879…` routes a batch-due NMI through a leading-edge helper that
presents exactly once, sets the existing marker, and tail-calls the historical wake.
The real-65816/PPU bridge is green 30/30. A hash-authenticated uninterrupted reducer
is component-green for exact consecutive PPU frames 6,012-6,088: one
`bg_scroll_present_step` and one `obj_present_nmi` on every one of 77 frames, no
missing or duplicate ranges, 54 cursor writes, and maximum successive cursor delta
two pixels. Sol coalesced the lossless animated capture before inspection and
reviewed all 65 retained framebuffer records; none shows the progressive black bar,
missing wall/floor, or palette corruption. Evidence is under
`/home/chad/supermn-snes-artifacts/active/927a2879-leading-batch-presentation-v1/`.

That is migrated cross-ROM checkpoint evidence and a component result only. Current
`c14c0184…` has since supplied exact-hash fresh-power coverage through 601
consecutive post-Start frames. Its wall/floor/map remains structurally whole after
the entry fade, but the broader contract correctly rejects it: the temporal reducer
records 77 held PPU transitions during source motion and scene coherence records
OAM age 16. The first main hold is tied to a 16-record OBJ-pattern dependency that
drains 7+7+2 before the moving OAM base can publish, holding the displayed scene for
seven frames. The next renderer work is eliminating that dependency latency and
rerunning the bounded exact-hash gates, not promotion or a long campaign.

## Why the current renderer is rejected

The current renderer can produce a correct background in a narrow capture while
still presenting a wrong complete frame. Its state is split across independent
authorities:

| Domain | Producer or owner | Consumer or publication token |
| --- | --- | --- |
| raw palette/BG/OBJ | SA-1 `$41` shadow and manifest | producer sequence/ack at `$41:0132+` |
| direct snapshot | `pacing_snapshot_direct` | canonical WRAM generation `$7E:899A` |
| queued snapshots | primary and secondary `render_queue_capture*` formats | queue storage, then the same canonical WRAM generation |
| heavy worker | palette, BG map/tile cache, and OAM builders | worker claim/busy fields `$7E:89A0/$899C` |
| BG presentation | map basis, camera phase, due/valid bytes `$7E:72B*` | BG map/scroll PPU writes |
| OBJ presentation | immutable OAM image, world list, due/valid bytes `$7E:718*` | channel-6 OAM publication |
| graphics patterns | BG/OBJ tile descriptors and pending flags | independent VRAM DMA completion |
| display phase | boot marker `$7E:1F1B` | boot Mode 7 or gameplay Mode 2 hardware ownership |

Those tokens do not establish one atomic displayed scene. A BG image, scroll,
palette, OBJ image, and tile set may therefore come from different logical
generations. The current NMI helper also uses nonzero `FRAME_REQ/FRAME_ACK` as a
proxy for gameplay readiness even though those counters do not transfer display
ownership.

The rejected ROM demonstrates the consequence at cold boot. The generated boot
assets and `boot_screen_init` bytes are identical to the previously centered
`4eb9a408...` ROM, but the Mode-7 logo shifts from approximately x=59..188 to
x=0..125 while the OBJ status text remains centered. `nmi_gameplay_present`
calls the gameplay BG scroll writer after the request/ack counters become nonzero,
even while `$7E:1F1B` still marks boot ownership. Writing `BG1HOFS` moves the
Mode-7 logo and does not move the boot OBJ text. Exact first-frame/register trace
evidence is retained with the current-hash campaign before this cause is closed.

The reported walking failure is separately renderer-red. The first focused replay
did not establish a MAME-aligned player state, but the retained exact-hash
601-frame capture proves an internal cross-generation presentation error. At game
tick 476, BG presentation follows live camera 103 while hardware OAM still owns
candidate sequence 457 with base camera 160; NMI translates that old OAM image by
57 pixels. Translation cannot update the old Superman tile codes, pose, or
animation. A newer moving BG plus an older translated character therefore creates
the observed glide/moonwalk regardless of eventual MAME alignment.

The immediate fail-safe repair makes the camera owned by the last complete
hardware-OAM base the sole BG presentation target. That removes cross-generation
motion, but it does not prove low latency or correct MAME facing. Queue
normalization/latest-ready work and the aligned motion oracle remain required.

## Required display-owner state machine

Only one owner may write presentation registers in an NMI:

1. `BOOT`: Mode 7 owns BG1, its matrix/offsets, boot CGRAM, and boot OAM.
2. `GAME_PREPARE`: a complete first gameplay scene is being built offscreen;
   boot remains displayed and gameplay presentation writes are prohibited.
3. `GAME`: a completed gameplay scene has been published; only gameplay NMI
   presentation may touch the gameplay registers.

`FRAME_REQ`, `FRAME_ACK`, renderer-busy, and queue occupancy are not display-owner
signals. The transition from `GAME_PREPARE` to `GAME` occurs only after a coherent
gameplay PPU flush completes. The transition is one-way until reset.

## One scene-generation contract

Every accepted producer image is normalized into one canonical scene packet,
regardless of whether it arrived through the direct, primary-queue, or
secondary-queue path. A packet contains:

- immutable producer generation and request sequence;
- raw palette, BG code/color planes, packed OBJ records, and controls;
- resolved BG physical-column ownership and map basis;
- the complete next BG tilemap and palette image;
- the complete next OAM image and its world/fixed classification;
- source camera and object coordinates needed for presentation; and
- the complete tile-pattern upload plan and cache ownership on which that
  tilemap/OAM image depends.

The worker builds the packet in non-displayed memory. Tile patterns must reach
VRAM before a published map or OAM entry can reference them, and cache slots
referenced by the currently displayed scene may not be evicted. A packet becomes
`ready` only when all of its dependencies are complete.

NMI is the sole hardware publisher. It may either retain the current complete
scene or commit one complete ready scene. It must not combine a new BG map with
old OBJ, a new scroll with a stale world-object transform, or new map/OAM
references with incomplete tile DMA.

## Motion presentation contract

The arcade produces approximately 30 game scenes per second and SNES presents
approximately 60 video frames per second. Intervening presentation frames may be
derived only from one adjacent pair of complete scenes. One shared world-space
transform must drive BG scroll and every world OBJ; HUD/status OBJ remain fixed.

For every accepted adjacent pair `(G, G+1)`:

- source object positions, animation code, flip flags, and camera are preserved;
- each 60 Hz presentation is either exact `G`, exact `G+1`, or an explicitly
  validated shared interpolation of their world transform;
- facing comes from the arcade OBJ/code semantics, never from the input button;
- no object may disappear because BG and OBJ selected different generations; and
- transition order cannot reverse, duplicate, or skip an arcade animation frame
  without a named conservation allowance.

Until aligned MAME data validates interpolation, the fail-safe policy is to hold
one complete scene and then commit the next. Smooth interpolation is a later
optimization, not permission to synthesize unverified motion.

## Implementation phases

1. Prove the rejected-hash boot and walking failures and retain their exact
   first-divergence artifacts.
2. Enforce the display-owner state machine before changing the wider data path.
3. Normalize the direct and both queued acquisitions into one canonical packet
   schema with one generation token.
4. Make BG map, palette, OAM, scroll, and tile dependencies one ready/commit unit.
5. Replace independent BG/OBJ 60 Hz adjustment with the shared motion contract.
6. Retire superseded due/valid paths only after exact-path fixtures prove that no
   producer or NMI entry can bypass the canonical commit.

New work should live behind an isolated renderer build flag until the old and new
paths can be compared. An experimental ROM is diagnostic output, not a human-test
candidate.

## Fail-closed acceptance

The same exact ROM hash and fresh-power movie lineage must supply all required
reports. Missing or unknown coverage is red, not neutral.

- Boot geometry: compare every visible boot phase with approved bounds; any
  clipped or shifted logo, text, or diamond fails.
- Title/credit/Start: preserve complete composite frames through the organic
  transition.
- Walk right and left: MAME-aligned player world X, screen X, code, flip,
  animation order, and consecutive SNES framebuffers must agree.
- Attack: stationary and moving attacks must preserve code/flip/order and full
  composite pixels.
- Scroll: every intervening SNES framebuffer must satisfy the temporal
  conservation rule; seams, black bars, hard jumps, and mismatched world-OBJ
  motion fail.
- Fence: collision before break, break animation/composite, passage afterward,
  doorway/background, and the brief right-edge region are all mandatory.
- Full composite: aligned MAME/SNES comparison includes BG, OBJ, HUD, palette,
  geometry, and every intervening video frame. A background-only match cannot
  pass.
- Human review: Sol must open the named boot, transition, right/left walk,
  attack, scroll, and fence artifacts and record exactly what was inspected.

Only `tools/promote_human_test_rom.py` may create a human-test ROM, and it remains
the final fail-closed enforcement layer after these renderer-specific gates.
