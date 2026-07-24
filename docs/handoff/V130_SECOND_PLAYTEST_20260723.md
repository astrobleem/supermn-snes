# v130 second human playtest — July 23, 2026

> **Superseded later on July 23:** the next human runs rejected the supplied v131 and v132
> responses. Exact v133 is the current title/attract/credit/boot response while preserving the
> bounded v132 crate/right-edge/title-capacity work. See
> [V133_TITLE_ATTRACT_BOOT_20260723.md](V133_TITLE_ATTRACT_BOOT_20260723.md).

## Verdict

Exact v130
`1ec22cbc92ad7beef0e20d8af6ff12f57023b7c437311f4bc6be56ce37cdd928`
is human-rejected as a playtest candidate.

The tester did not reach the first breakable wall, so v130's controlled wall repair remains
human-unconfirmed. Two earlier first-stage actions crashed the game:

1. picking up a box and throwing it;
2. killing a silver enemy with a held charged punch/energy shot.

The same run reported:

- wrong tiles in Superman's punch/kick animation frames;
- a gameplay viewport showing the upper-left portion of the arcade playfield instead of a centered
  crop, requiring a shift right and down; and
- rotating Mode 7 boot presentation that caused dizziness and must be replaced with non-rotating
  activity.

These are direct human observations in Mesen 2.1.1. They supersede any wording that promotes v130
as the current playtest candidate.

## v131 response candidate

Exact v131 response-candidate ROM SHA-256:

`be0ed971b90ce4ce48e0c6b1ad3356eba41c5b12484c11506154ce40dbe8c1aa`

Packaged local ROM:

`build/playtest/superman-snes-v131-mesen211-be0ed971.sfc`

This candidate changes the boot presentation, viewport transform, and OBJ-cache reclamation. It
does not change the TAD music data, so the earlier by-ear sample/timbre question remains open.
It is an **interactive technical demo, not playable or shippable**.

### Static SA-1 logo

The tester-supplied `/home/chad/data/sa1-logo.png` is usable. It is a 1536×1024 RGB image with
SHA-256
`091e5831c949a8c686e35ff8ba1e77fccd4bbbf0b6ed173c821bd9494516b3c6`. The generator embeds a
reproducible 120×80, 92-color indexed derivative, not the source file. The decoded derivative's
palette-plus-pixels SHA-256 is
`c85b266b610ff7dd08ad860369d17170c891ead78f37aff4322836a5ad7c2d09`; the complete 32 KiB boot
asset is
`fc39ed2f9176dc55fa7c1bc40c4ae716f3151a005f166f7d2c7cfc85bc08f616`.

All 64 retained Mode 7 table entries are the same identity-scale matrix, and NMI never changes
M7A-D. The only motion is a palette pulse on one 8×8 amber OBJ diamond. In
`build/user-playtest-v105-investigation/v131-final-static-logo-mesen211-v1/`, exact-Mesen frames
200 and 300 differ only in bounding box `(228,192)-(236,200)`; the logo itself has no changed
pixels. Both remain Mode 7 at brightness 15, forced blank clear, and halt zero. This explicitly
supersedes v130's rotating shield.

### Centered 384×240 to 256×224 crop

The live MAME oracle reports a 384×240 arcade screen. A centered SNES crop therefore begins at
arcade `(64, 8)`. The retained transform is now:

- BG1 horizontal scroll: existing arcade scroll plus 64;
- BG1 vertical scroll: zero instead of `$3F8`, advancing the old image by eight lines;
- OBJ X: signed X1-001 X minus 64;
- OBJ Y: `232 - ((sy + 14) & 255)`, modulo 256; and
- producer visibility: only signed non-negative X values whose 16-pixel sprite can overlap the
  centered window (`49..255`).

MAME source/live-register inspection confirmed that X1-001 bit 8 is a sign bit, not a right-side
extension. The legacy and packed renderers and the SA-1 producer use the same transform.

The matching-state `--packed-obj-manifest --manifest-only` check in
`build/user-playtest-v105-investigation/v131-centered-obj-manifest-nexen-v3/` is green across
20/20 boundaries: packed length, every six-byte record, visibility, and source order have zero
manifest mismatch. The tool still reports one unrelated raw work-plane handoff transient
(16 bytes at one sample) outside the manifest-only gate. This is checkpointed predicate evidence,
not a formal rate or complete renderer result.

### Wrong-tile root cause and reclamation quarantine

The exact-v130 bad-animation checkpoint is
`build/user-playtest-v105-investigation/v130-box-b-b-mesen211-v1/action-0003.mss`. Its
code-to-VRAM cache was internally exact, but the next heavy frame had reclaimed and remapped
physical OBJ slots while the PPU still displayed the preceding OAM generation. Rewriting those
VRAM slots before the replacement OAM DMA explains the transient Superman/enemy tiles.

The high-water reclaimer now decodes every physical slot named by the currently displayed OAM and
marks it unavailable before rebuilding the hash/free stack. The first implementation exposed
another Poppy/65816 trap: `$7E8602,Y` silently assembled as bank-local absolute-Y because the CPU
has no absolute-long,Y mode. The focused validator caught every displayed slot entering the free
list. The final implementation walks OAM with absolute-long,X and retains the cursor in direct
page.

Current-ROM evidence in
`build/user-playtest-v105-investigation/v131-obj-displayed-slot-quarantine-nexen-v10/` is green in
both independent runs:

- all 12 physical slots named by the displayed 20-entry OAM prefix were marked;
- displayed/free intersection: empty across a 104-slot free stack;
- displayed/upload-queue intersection: empty across a 12-slot upload queue; and
- all gating renderer outputs were byte-identical.

This is a forced-full-cache checkpoint test, not a cold-boot or full-playthrough result.

### Exact emulator and liveness evidence

Fresh `TESTFLAG=0` Nexen evidence for the exact hash is in
`build/user-playtest-v105-investigation/v131-final-coldboot-settle-v2/`. It organically arms the
production gates, accepts coin/Start through the real controller mailbox, validates 150/150
counter/hook ticks, and ends at frame 5,982 / tick 426 with halt zero, continuing rendering, and a
154-byte minimum observed saved-stack margin. PPU state reports BG1 H/V scroll `64/0`.

A separate fresh stock-Mesen-2.1.1 boot is in
`build/user-playtest-v105-investigation/v131-final-title-mesen211-v1/`. Frames 5,650–5,800 retain
brightness 15, forced blank clear, halt zero, and advancing ticks/renders. From its exact same-hash
frame-5,800 state,
`build/user-playtest-v105-investigation/v131-final-mesen211-full-sequence-v1/` accepts real
coin/Start, completes the 450-frame transition, fires two charged-shot entries and two relocated
continuations, then advances 437 tick hooks and 600 post-release frames with no failed check or
stagnant frame. It ends at frame 8,177 / tick 1,524 / render 1,472 / halt zero; health changing
20→18 also reconfirms enemy offense in that encounter.

### Crate/throw and enemy-charge scope

The v130 crate operation is reproducible: at X=93, crouch then stand lifts the wooden crate
(`action_state=10`), and Button 1 throws it (`action_state=7`). A current-ROM checkpoint replay
refreshes the state-restored `$7F:8000-$AFFF` renderer mirror from the selected v131 ROM before
running that exact real-controller sequence:

`build/user-playtest-v105-investigation/v131-box-regression-mesen211-v1/`

It visibly holds and throws the crate, reaches tick 1,483 with halt zero, keeps all initialized
task stacks valid at a 138-byte minimum margin, and continues both game ticks and completed
renders. Because its gameplay checkpoint originated on v130 and only the selected-ROM renderer
mirror is explicitly refreshed, this is focused cross-version checkpoint evidence, not an organic
v131 full-stage proof.

The user's silver-enemy charged-kill freeze remains state/target-specific. The fresh same-hash
charged-shot sequence above is green, but a generic charged shot is not proof of that exact kill
event. Do not call that human report closed until the exact enemy outcome is reproduced or the
tester clears it on v131.

## Build and gate summary

- `bash tools/build_interp.sh`: green, including ROM pack/layout assertions.
- `python3 tools/audit_banks.py`: all banks green.
- Static logo: exact stock Mesen 2.1.1, fresh power-on, frames 200/300.
- Production reachability: fresh `TESTFLAG=0` Nexen, organic gates and real coin/Start.
- Title/transition/charge: fresh exact stock Mesen 2.1.1, real controller mailbox.
- Centered OBJ producer predicate: 20/20 exact packed-manifest boundaries.
- Displayed-slot quarantine: two forced-full-cache variants, all gated outputs equal.
- Crate hold/throw: focused compatible checkpoint with the exact selected-ROM renderer mirror
  explicitly refreshed.

None of these is a formal FPS result or a full-stage/playthrough soak. v124's
29.700167 game-fps / 360,990.164 cycles-per-tick run remains the latest formal performance
evidence. Human v131 confirmation is still required for the viewport, static boot presentation,
crate path, first wall, exact silver-enemy charged kill, animation tiles, and first-stage timbre.
