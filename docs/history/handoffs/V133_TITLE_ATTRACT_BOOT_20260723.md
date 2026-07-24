# v133 title, attract, credit, and boot response — July 23, 2026

> **Superseded July 24:** the first long v133 gameplay run cleared the first boss, then found that
> the following vertical section did not scroll. Exact v134 bridges X1-001 scrolly into SNES BG1.
> Preserve the bounded v133 title/attract/credit/zoom evidence below, but use
> [V134_STAGE2_VERTICAL_SCROLL_20260724.md](V134_STAGE2_VERTICAL_SCROLL_20260724.md) and
> `RECOVERY.md` R14 for the current response candidate.

## Verdict

The first human v132 run supersedes R12's response-candidate verdict. The title text was readable
but briefly became pixelated about once per second, the no-input attract sequence stopped at
`INSERT COIN`, and only `CRE` of the bottom-right credit label was visible. The tester also asked
for the temporary SA-1 boot logo to begin extremely large and shrink to its fitted size without
rotation.

Exact v133 production ROM SHA-256:

`15465fe67b458eee08eeb2fe235362e5986378f22f60bf96b1d22e662a53cac5`

Packaged local ROM:

`build/playtest/superman-snes-v133-15465fe6.sfc`

v133 reproduces and repairs the three reported visual/liveness defects and implements the requested
one-shot Mode 7 zoom. It has a stock-Mesen-2.1.1 fresh-power lineage through frame 9,000, but it has
not passed a new human gameplay run, full stage/playthrough, audio listening comparison, renderer
conservation gate, or formal performance gate. It remains an **interactive technical demo, not
playable or shippable**.

## Brief title-text corruption

### Exact failure and root cause

The v132 corruption is visible at
`build/user-playtest-v105-investigation/v132-human-reject-title-framewise-v1/frame-005756.png`.
The title BG2 font tiles, tilemap, source palette, staging palette, and live CGRAM remain byte-stable
at that frame, ruling out a damaged font or palette upload.

The ordinary BG1 uploader was changing `BG12NBA` from `$61` to `$01` at the beginning of every
multi-video-frame render. The previous completed title image remained visible while that work was
in progress, so BG2 temporarily selected character base word `$0000` instead of the title font at
word `$6000`. The title overlay restored `$61` only after the render completed. That transient
register ownership error made valid BG2 map entries display unrelated tiles.

### Repair and evidence

`bg_upload` now keeps `BG12NBA=$61`: BG1 remains at character base `$1000`, while the otherwise
disabled BG2 harmlessly remains at `$6000` until the title overlay uses it. ROM packing asserts the
instruction bytes inside the uploader.

`build/user-playtest-v105-investigation/v133-final-fresh-title-mesen211-v1/` starts the exact v133
ROM from power-on in stock Mesen 2.1.1 with no state load or runtime memory write. It captures every
video frame from 5,700 through 5,900:

- all 201 frames remain Mode 1, brightness 15, forced blank clear, and halt `$0000`;
- game tick advances 285→385 and completed render advances 264→349;
- the exact formerly corrupt frame 5,756 is readable;
- the legal-text region and the `CREDIT 0` region each have one identical nonblack-pixel mask across
  all 201/201 frames; and
- three whole-screen one-pixel variants are the title artwork's sparkle, not glyph substitution.

This is a fresh-power exact-emulator repair of the demonstrated title corruption. A human v133
viewing pass is still required.

## No-input attract freeze at `INSERT COIN`

### Exact failure and root cause

The rejected v132 idle run is retained at
`build/user-playtest-v105-investigation/v132-human-reject-idle-attract-coarse-v1/`. It stops making
game or render progress around video frame 7,910 at tick 1,389 / completed render 1,170, with halt
still zero and task mask `$4003`. The physical SA-1 PC is trapped in
`$9E:DF9F`, inside `rpb_sort_shift`.

The prepared-background insertion sort initializes Y to two bytes, then used `BEQ` to stop when Y
equaled the list length at `$0146`. An empty list has length zero, so Y had already passed the
terminal before the first comparison. The loop then walked and shifted around the 16-bit address
space instead of returning. MAME 0.287 continued changing the corresponding arcade state through
the same no-input interval, confirming that the terminal was port-specific.

### Repair and evidence

The sort now exits on `BCS`, implementing the actual unsigned condition `Y >= length`; zero- and
one-entry lists are already sorted. ROM packing asserts the resulting
`CPY $0146 / BCS` bytes.

The exact-v133 fresh-power title run above continues, without any memory intervention, from its
frame-5,900 checkpoint in
`build/user-playtest-v105-investigation/v133-final-fresh-lineage-attract-mesen211-v1/`.
At the old terminal:

| Video frame | Game tick | Completed render | Halt | Task mask |
|---:|---:|---:|---:|---:|
| 7,910 | 1,389 | 1,171 | `$0000` | `$4003` |
| 7,940 | 1,405 | 1,187 | `$0000` | `$4003` |
| 9,000 | 1,726 | 1,493 | `$0000` | `$FDFF` |

Screenshots change from `INSERT COIN` to the running demo and then `GAME OVER`; PCs and task masks
also continue changing. This passes the exact old freeze in a single fresh-power ROM lineage. It
is a bounded no-input attract run, not proof of a full playthrough.

## Clipped `CREDIT 0`

### Root cause and repair

The centered 256-pixel window deliberately retains ordinary raw X1-001 objects in
`$031-$13F`. The title's bottom credit records are an exceptional wrapped layout: their logical X
coordinates run from `$120` through `$160`, so the ordinary crop retained only the first part and
discarded the rest.

The producer now recognizes only the bottom row at raw Y `$0A`, only glyph codes
`$007D-$0080/$008B`, and only raw X `$120-$16F`. Those five records move left by 48 pixels before
packing. Adjacent solid-border records and every other title/gameplay object keep the established
crop. This places the first `C` immediately after the border and the final digit at screen
X 249..254.

The exact fresh title and attract captures visibly show the complete `CREDIT 0`. The three Python
renderer oracles pass 6/6 synthetic cases each for shifted credit glyphs, untouched adjacent
records/gameplay lookalikes, and the ordinary `$140` right-edge rejection.

## One-shot non-rotating Mode 7 zoom

`tools/gen_boot_screen.py` now emits 64 strictly increasing identity matrices. A and D move from
`$0020` (0.125 scale, extreme close-up) to `$00C0` (the established fitted 0.75 scale); B and C
remain zero in every entry, so rotation and shear are impossible. NMI applies one matrix entry per
frame, latches completion, and never restarts the zoom. After settling, only the small activity
diamond continues its palette pulse.

The final packed 32 KiB boot asset SHA-256 is
`e8d6b5f6c3d77d646eaa695c47d1e74c2c040a56e24d359fa067c3d749ea8734`.
The packer asserts both endpoints, every zero off-diagonal coefficient, strict monotonicity, helper
layout, and asset seams.

`build/user-playtest-v105-investigation/v133-final-boot-zoom-mesen211-fresh-v1/` is a fresh-power
stock-Mesen-2.1.1 capture of the exact v133 ROM:

- frame 17 is an extreme logo close-up;
- frame 50 is mid-zoom;
- frame 86 is fitted and remains geometrically static afterward; and
- Mode 7 remains visible at brightness 15 with forced blank clear.

The status strings remain high-level liveness indicators. They do not claim that a particular
arcade RAM/ROM test has been identified.

## Build and validation summary

- `bash tools/build_interp.sh`: green; 4 MiB production ROM and all pack/layout assertions pass.
- Exact stock-Mesen-2.1.1 fresh power-on title capture: 201/201 legal/credit masks stable.
- Same fresh-power ROM lineage: frame 5,900→9,000, tick 385→1,726, render 349→1,493, halt zero.
- Exact stock-Mesen-2.1.1 fresh Mode 7 capture: huge→mid→fitted, no rotation.
- Credit/crop predicate checks: 6/6 green in each of three independent validator modules.
- Modified Python tools compile; `git diff --check` is clean.

None of these is FPS evidence. v124's 29.700167 game-fps / 360,990.164 cycles-per-tick run remains
the latest formal performance result. The no-input run does not validate the uncertain attract
music by ear, and this change does not alter the inherited v130 audio data.

## Required human retest

Power on the exact v133 ROM and check:

1. the huge-to-fitted SA-1 zoom is comfortable and never rotates;
2. all title legal text remains coherent over several seconds;
3. the full `CREDIT 0` label is visible;
4. idle attract mode passes `INSERT COIN` and continues into/demo out of gameplay;
5. coin/Start and first-stage play still work;
6. crate throw, the charged shot that kills a silver enemy, and the first breakable wall; and
7. first-stage music continuity and instrument timbre.

Only the first four have new v133 repairs/evidence. Wrong Superman attack tiles, the exact
silver-enemy charged kill, first wall on this hash, musical fidelity, renderer conservation,
aligned MAME pixels, full stage/playthrough, and formal 30 Hz gates remain open.
