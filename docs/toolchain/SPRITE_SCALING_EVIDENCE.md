# Sprite Scaling Verdict — MAME Trace Results

## Trace setup
- MAME headless, Superman (b61), 9000 frames (~150s)
- Coin1 + Start1 injected at frames 240/460 to reach gameplay
- Write taps on $D00000-$D005FF (sprite Y), $D00600-$D00607 (control), $E00000-$E03FFF (code/X/attr)

## Results

### Sprite activity (confirms gameplay reached)
| Metric | Value |
|---|---|
| Frames traced | 9000 |
| Sprite Y writes | 11,924 |
| Sprite code/X/attr writes | 22,952 |
| Sprite control reg writes | 49 |

### Control register breakdown ($D00600-$D00607)

| Reg | Address | Writes | Values | Behavior |
|---|---|---|---|---|
| 0 | $D00600 | 1 | $0010 | Constant (init only) |
| 1 | $D00601 | 0 | — | Unused |
| 2 | $D00602 | 1 | $0021 | Constant (init only) |
| 3 | $D00603 | 0 | — | Unused |
| 4 | $D00604 | 24 | $00FF×1, $0000×23 | Init sequence ($00FF→$0000), then static |
| 5 | $D00605 | 0 | — | Unused |
| 6 | $D00606 | 23 | $00FF×1, $0000×22 | Init sequence ($00FF→$0000), then static |
| 7 | $D00607 | 0 | — | Unused |

### Verdict: NO runtime sprite scaling

The control registers ($D00604, $D00606) change value during the **first frame only**
(power-on init: $00FF → $0000). They are never written again during 9000 frames of
gameplay. The "runtime scaling" detected by the raw trace is a false positive from
initialization.

**Conclusion: Superman's arcade hardware does NOT scale sprites at runtime.**
All sprites use fixed sizes. The sprite control registers are one-shot init, not
live zoom/scale values.

## Implications for the SNES port

1. **SA-1 CC Type 2 is NOT needed for sprites.** The original assumption that
   runtime scaling hardware would need to be emulated is wrong.
2. **Offline planar→packed conversion is sufficient.** All sprite tiles can be
   converted at build time with `tools/extract_tiles.py`.
3. **SA-1 is free for other work** — game logic, C-Chip emulation, sound driver.
4. **ROM space is the only tradeoff** — if the arcade has multiple zoom levels
   pre-rendered as separate sprite frames, we just include them all. ROM is cheap.

## Open question: pre-rendered zoom frames?

The trace proves the hardware doesn't scale. But the arcade ROM may still contain
**pre-rendered zoomed sprite frames** (e.g., Superman zooming in = a different,
larger sprite tile set, not a scaled version of the same tiles). This is a data
question, not a rendering question:

- If zoom = different tile sets → just convert and include all sets offline
- If zoom = same tiles at different sizes → need to check if the arcade swaps
  to entirely different sprite tiles for "zoomed" frames

To answer: examine the sprite ROM (b61-17.k1) for duplicate tile sequences at
different sizes, or check the sprite code/X writes for patterns that suggest
frame-swapping during zoom animations.
