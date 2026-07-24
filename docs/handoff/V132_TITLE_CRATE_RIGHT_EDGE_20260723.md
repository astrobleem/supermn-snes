# v132 title, crate, and right-edge response — July 23, 2026

## Verdict

The next human run supersedes v131's response-candidate label. The supplied v131 ROM still froze
when the tester threw the crate, Superman disappeared at the visible right side of the newly
centered window, and the title words were incoherent.

Exact v132 production ROM SHA-256:

`48d7c4d6c6a431e8c2066410e325888d70aec9d15b7261903ddc4f8effd476a2`

Packaged local ROM:

`build/playtest/superman-snes-v132-48d7c4d6.sfc`

v132 has focused evidence for all three newly reported failures. It has not completed a fresh
cold-boot stage run, a full playthrough, a musical listening pass, renderer conservation, or a
formal performance gate. It remains an **interactive technical demo, not playable or shippable**.

## Incoherent title text

### Root cause

The arcade title composes its six legal-text rows as 149 overlapping 16x16 OBJ records. That is
already beyond the SNES limit of 128 OBJs per frame, and each dense row also exceeds the SNES
34-OBJ-tile scanline limit. Preserving the arcade OBJ representation therefore could not produce a
complete title even when the renderer and cache were otherwise correct.

### Repair

The SA-1 snapshot producer now recognizes the exact post-TAITO title composition using three
distant code/Y signatures. Only for that composition, it removes the six legal-text Y rows from
the packed OBJ manifest, leaving 97 title-artwork objects. The 5A22 renders those six text rows on
BG2 while retaining the Superman logo, TAITO logo, globe, copyright art, and every non-title frame
as OBJs.

The BG2 helper copies the same private glyph graphics already packed in the ROM; no arcade graphic
bytes were added to source. BG2 uses map word address `$7000`, character word address `$6000`, and
palette 7. The two arcade lines wider than the 32-column SNES window are meaning-preserving
32-character adaptations:

- `SUPERMAN, ALL RELATED CHARACTERS`
- `SLOGANS & INDICIA ARE TRADEMARKS`

This omits one trailing comma and substitutes `&` for `AND`; it avoids clipping the first or last
letter of either line.

The first font build exposed another Poppy bank hazard: a same-bank long indexed load encoded bank
zero. The retained load explicitly ORs the physical `$E9` bank into `title_font_codes`; the bad
build is not retained.

### Exact-Mesen evidence

`build/user-playtest-v105-investigation/v132-title-fontdma-final-mesen211-fresh-v1/` starts the
final production hash from power-on in stock Mesen 2.1.1 with no runtime memory pokes. Frames
5,680, 5,700, 5,720, and 5,740 remain Mode 1, brightness 15, forced blank clear, halt zero, and use
main-screen layers BG1+BG2+OBJ. Tick advances 275→305 and completed renders advance 254→281.
Frames 5,720 and 5,740 are pixel-identical; visual inspection confirms all six legal lines are
coherent. The final screenshot SHA-256 is
`6b7df613ae6021db9c7ddff91a7cb61cae4f484b3465e6b0b625ea208b45843b`.

A separate exact-ROM continuation,
`build/user-playtest-v105-investigation/v132-final-title-coin-start-handoff-mesen211-v2/`, reloads
that fresh-power title state and holds the real Select/Start inputs long enough to cross the
30 Hz mailbox cadence. It reaches the pre-round Superman sequence at video frame 6,491 / tick 681 /
completed render 649 with halt zero, eight valid initialized task stacks, and a 168-byte minimum
margin. The screenshot confirms the title-only overlay is absent after the transition; its
SHA-256 is `80db7d702add34b656e529f87f732afb1bb00e0a6f29b0e1d908ef170d32d1bb`.

This closes the reproduced title-capacity defect in a clean automated power-on capture. The tester
still needs to confirm it in the normal interactive run.

## Crate-throw freeze

### Exact failure and root cause

The exact-v131 failure is retained in
`build/user-playtest-v105-investigation/v131-fresh-crate-throw-crash-v1/`. It freezes at tick
1,288 with virtual PC `$FA:85F8`; the SA-1 is executing the `$00:0000/$0004/$0006/$D16E` loop while
halt remains zero.

Execution-range hooks narrowed the first bad transfer to `entry_23342`: it reached `$98:80C9` and
then executed `RTI` into zero. At generated continuation label `br23342_1`, Poppy had forgotten
the incoming accumulator/index mode. The intended 16-bit sequence

`LDA #br23342_2; STA $40`

was emitted as `A9 D1 85 40 ...`. With M=16, `$85` became the high immediate byte and `$40` then
executed as `RTI`, popping an unrelated frame and jumping to `$00:0000`.

The continuation now declares `.a16` and `.i16`. The corrected bytes are
`A9 D3 80 85 40 A9 FB 00 85 42 4C 00 84`, and the ROM pack asserts both continuation addresses
and the complete byte sequence so this exact silent assembler failure cannot return.

### Differential and replay evidence

A `PC_RING=1` diagnostic build of the same source has SHA-256
`d81872eae8b08b52bfc3564f49d6fead4ee32b6fec14d17c9f7223422535499b`. In
`build/user-playtest-v105-investigation/v132-final-2429c-mode-fix-differential-v4.json`, six retained
organic `$02429C` fixtures each run under three native-gate variants. MAME 0.287 and Nexen match
exactly in all 18/18 cases across every D/A register, CCR, interrupt mask, mapped 16 KiB work-RAM
window, and value-checked native-return residue.

The first attempt used the production-packed ROM, where the documented PC-freeze fetch calls are
NOPed, so the harness ran past its terminal and reported `maxFrames`. That was a harness-mode
mistake, not a green result. After the diagnostic run, a normal production rebuild reproduced the
preserved v132 ROM byte-for-byte.

`build/user-playtest-v105-investigation/v132-final-crate-mode-fix-mesen211-v2/` then replays the exact
pre-freeze Mesen 2.1.1 state with the selected v132 ROM and refreshed renderer mirror. It advances
from tick 1,265 / render 1,164 through tick 1,480 / render 1,370, where v131 stopped at tick 1,288.
Halt remains zero, all 13 initialized task stacks are valid, and the minimum margin is 138 bytes.
The crate action and scene continue visually.

Two speculative interpreter-return guards failed the exact replay before this cause was found.
They were removed completely; v132 contains only the mode-correct continuation repair.

This closes the reproduced crate failure and the bounded function semantics. It is a checkpointed
replay, not a fresh organic stage or crash-freedom proof.

## Superman disappearing on the right

R11's statement that X1-001 bit 8 made raw `$100-$1FF` entirely offscreen was incomplete. The
coordinate is signed, but the device draws the sprite in both 512-pixel buckets. For the centered
arcade-X `64..319` crop, raw X `$100-$13F` is the wrapped copy at arcade X `256..319` and must be
retained.

The producer and all three validator predicates now use the exact raw overlap interval
`$031-$13F`. Both legacy and packed consumers stop sign-extending raw `$100-$13F` before
subtracting the 64-pixel crop origin.

In `build/user-playtest-v105-investigation/v132-final-right-edge-mesen211-v2/`, exact Mesen 2.1.1
drives the player right from the current crate replay state. Tick advances 1,480→1,572, completed
renders 1,370→1,411, halt remains zero, all initialized stacks remain valid with a 138-byte
minimum margin, and the player coordinate advances 208→336. The `action-0001-none.png` capture
visibly retains Superman at the far-right boundary behind the copper pipe; later X=336 is
legitimately outside the 256-pixel crop. A synthetic boundary check also retains
`$031/$0FF/$100/$13F` and rejects `$030/$140`.

The final-hash packed-snapshot mirror-refresh diagnostic at
`build/user-playtest-v105-investigation/v132-final-packed-obj-right-edge-nexen-v2/` recorded one
stale first consumer image followed by seven consecutive exact samples. Its aggregate is correctly
red at 7/8; do not cite it as a green renderer gate. The inherited burst-render conservation
failure also remains open.

## Build and validation summary

- `bash tools/build_interp.sh`: green; all ROM-pack/layout assertions pass.
- Production rebuild after `PC_RING=1`: byte-identical to the preserved candidate.
- `$02429C` focused MAME/Nexen differential: 18/18 green on the diagnostic build.
- Exact Mesen 2.1.1 crate failure replay: green past the old terminal.
- Exact Mesen 2.1.1 right-edge drive: live, with the visible boundary sprite retained.
- Exact Mesen 2.1.1 fresh power-on: coherent BG2+OBJ title composition.
- Same-ROM title-state continuation: real coin/Start reaches the pre-round sequence with the
  title overlay absent.
- Modified Python build/validator tools compile; the centered-X synthetic boundary check passes.
- Packed-snapshot mirror-refresh diagnostic: red 7/8 because sample zero is stale; retained as
  negative evidence.

None of these is FPS evidence. v124's 29.700167 game-fps / 360,990.164 cycles-per-tick run remains
the latest formal performance result.

## Required human retest

Power on the exact v132 ROM and check, in order:

1. all title words after TAITO fades;
2. crate pickup and throw;
3. Superman at the visible right edge;
4. the charged shot that kills a silver enemy;
5. the first breakable wall and continued first-stage play; and
6. first-stage instrument timbre and music continuity.

Only the first three have new focused v132 repairs. The silver-enemy outcome, wall on this exact
hash, musical quality, renderer conservation, full-stage/playthrough stability, and formal 30 Hz
gate remain open.
