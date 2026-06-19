# Risk Mitigation: Arcade Graphics → SNES PPU + SA-1

Advisor note. Companion to PROJECT_PLAN.md §2 and PORT_PLAN.md "Data Conversion".
Goal: avoid building an SA-1 character-conversion runtime you may not need, and
de-risk the parts that are genuinely hard (palette reduction, sprite limits).

## Correct a load-bearing misconception first

The plan repeatedly says: **"Use SA-1 CC Type 2 to scale sprites."** Two problems:

1. **SA-1 Character Conversion does not scale.** CC converts *linear bitmap*
   pixel data into the SNES planar tile (character) format. It is a
   format-conversion accelerator, not a scaler/rotator. Scaling sprites is a
   separate software problem (the SNES has no sprite scaling hardware; only
   Mode 7 scales, and that's a background, not OBJ sprites).
2. **You may not need CC at all.** The arcade sprites are *already tile data*
   (4bpp planar, per TECHNICAL_REFERENCE.md). If a sprite is a fixed-size tile
   that just needs its bitplanes reordered to SNES layout, that conversion is a
   **build-time offline step** — convert once with a Python tool, ship the
   result. No SA-1 runtime cost, no CC, much less risk.

CC1/CC2 on the SA-1 only earn their keep when you are generating bitmaps *at
runtime* — software-rendered/scaled/rotated frames (this is what
SuperMonkeyIsland does, because SCUMM composites bitmaps). So the first task is
not "port CC code," it's **determine whether Superman needs runtime conversion
at all.**

## Decision gate 0 — RESOLVED (2026-06-16)

**Trace Superman in MAME and answer: does the arcade actually scale sprites
during gameplay, and is it gameplay-critical?**

**Answer: NO.** See `SPRITE_SCALING_VERDICT.md` for full trace data.

9000 frames traced (~150s, coin+start injected). Sprite control registers
($D00600-$D00607) were written only 49 times total — all during the first
frame (power-on init: $00FF→$0000). **Zero writes during actual gameplay.**
The control registers are one-shot init, not live zoom/scale values.

**Decision: offline planar→packed conversion. SA-1 CC Type 2 NOT needed for
sprites. SA-1 is free for game logic, C-Chip emulation, sound driver.**

One open data question remains: the arcade ROM may contain pre-rendered zoom
frames (different tile sets for zoomed sprites, not scaled versions of the
same tiles). This is a data extraction question, not a rendering question.
Check sprite ROM b61-17.k1 for duplicate tile sequences at different sizes.

## The specific hazards (ranked)

### H1 — Palette reduction: 4096 → 256, 16 per palette (CRITICAL, art quality)
Arcade: 12-bit color, up to 256 on-screen, flexible. SNES OBJ: 8 palettes of 15
colors (+transparent) = sprites must be grouped into 16-color sets. This is the
hardest *quality* risk and it's not automatable away cleanly:
- Per-sprite/per-object palette assignment must be planned (which sprites share
  a 16-color palette).
- 12-bit→15-bit is a clean left-shift per channel (RGB444→RGB555); the *hard*
  part is the count reduction to 16/palette, not the bit depth.
- Mitigation: build a palette-analysis tool that clusters the arcade art into
  ≤8 palettes of 15 colors and reports error. Decide acceptable error before
  committing the whole asset set.

### H2 — Per-scanline sprite limits (HIGH, gameplay visible)
SNES OAM: 128 sprites total, but only **32 sprites and 34 8×8 tiles per
scanline**. Arcade hardware has far higher limits. Bullet-hell / boss scenes
will drop sprites (flicker/vanish) if not managed. Mitigations:
- Audit busiest scenes in MAME (boss $00C9A6, projectiles $024956) for max
  concurrent on-screen objects per scanline.
- Plan sprite priority/cycling (the classic flicker trick) and/or move some
  objects to BG layers.

### H3 — Planar format reverse-engineering (HIGH, blocks the pipeline)
The 4 graphics ROMs are interleaved in a specific way (per TECHNICAL_REFERENCE:
b61-16/17 = planes 2,3; b61-14/15 = planes 0,1; even/odd byte offsets). Getting
the plane order / interleave wrong yields garbled-but-plausible tiles — easy to
waste days. Mitigation: validate against MAME's tile viewer (known-good
reference) on a handful of tiles before bulk-converting. `tools/extract_tiles.py`
exists; verify its output pixel-for-pixel against MAME first.

### H4 — Resolution & coordinate mismatch (MEDIUM)
Arcade 384×240 → SNES 256×224. Horizontal playfield is ~33% narrower. This is a
*design* problem, not just scaling: camera/scroll logic, HUD layout, and object
spawn bounds all assume 384 wide. Decide the strategy (crop, squash, or
redesign camera) and feed it back into the transpiler's SCROLL ($005C5E) port.

### H5 — VRAM bandwidth / DMA timing (MEDIUM)
All VRAM writes happen in VBlank (~ limited bytes/frame). If runtime conversion
(H1 path) is needed, the converted tiles must DMA within the VBlank budget.
Mitigation: budget bytes/frame early; if over, convert fewer tiles/frame or
pre-convert offline.

## De-risking strategy: smallest visible win first
1. **One tile, end to end.** Convert a single known arcade tile offline, load it
   into a minimal SNES test ROM (you already boot one), display it, and compare
   to MAME's tile viewer pixel-for-pixel. This validates plane order *and* the
   display path before any bulk work.
2. **One sprite object** with its real palette, on screen, matching MAME.
3. **One busy scene** (a boss) to stress sprite-per-line limits *before*
   committing the rendering approach.
4. Only then bulk-convert assets.

## Validation harness
- **Reference:** MAME tile/sprite/palette viewers are ground truth. Capture
  reference PNGs of tiles, sprites, and palettes from MAME.
- **Automated diff:** your conversion tool should emit a PNG of each converted
  tile; diff against the MAME reference PNG (exact match for non-scaled tiles).
- **In-emulator check:** Mesen2 (+MCP, already working) to view VRAM/OAM/CGRAM
  of the built ROM and confirm it matches the converter's intent.

## Acceptance gates
- **G0 — Scaling decision made** ✅ RESOLVED 2026-06-16. No runtime scaling.
  Offline planar→packed. See SPRITE_SCALING_VERDICT.md.
- **G1 — One tile** matches MAME pixel-for-pixel through the full pipeline.
- **G2 — Palette plan** ≤8×15 colors with measured, accepted color error.
- **G3 — Worst-case scene** sprite-per-scanline count known and a flicker/BG
  mitigation chosen.
- **G4 — VBlank DMA budget** measured for the chosen approach.

## Fallbacks
- If runtime CC scaling proves too expensive: pre-render the needed scale steps
  offline as discrete sprite sets (trade ROM space for SA-1 cycles). ROM is
  cheap (you're planning 2MB+); SA-1 cycles in-frame are not.
- If palette reduction quality is unacceptable: split objects across more BG/OBJ
  palettes, or accept per-zone palette swaps (load different palettes per level
  section).
- If sprite limits are hit: promote large/background objects to BG layers and
  reserve OAM for gameplay-critical sprites.
