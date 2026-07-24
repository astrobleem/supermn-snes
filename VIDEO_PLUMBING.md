# Video Plumbing — wiring the live 68K interpreter to the SNES PPU

Created June 19, 2026, right after the interpreter reached Superman's **live
per-frame game loop** (see `STATUS.md`, `INTERPRETER_SPIKE.md`). The game is
running *blind*: every 68K write to a video/sprite hardware bank is currently a
**no-op**, so no pixels reach the SNES PPU. This doc captures exactly what the boot
does with the video hardware, what I learned getting it alive, and the concrete
plan + traps for the next phase.

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

See `docs/handoff/V133_TITLE_ATTRACT_BOOT_20260723.md`. The status strings describe
high-level liveness (`ROM LOADED`, `SA-1 68000 CORE ACTIVE`, `ARCADE BOOT IN PROGRESS`); they are
not claims that a particular internal RAM/ROM test is active.

## The one hard-won rule: dispatch every memory store by destination bank

The interpreter models 68K work RAM `$F0xxxx → SNES $7F`. Many store handlers in
`src/interp.pasm` **hardcode the `$7F` bank** (they were written when only work RAM
mattered). That is a latent corruption bug the moment a handler is asked to write a
*hardware* bank, because `$B00000 & 0xFFFF = $0000 → $7F:0000 = $F00000`:

- This is exactly the bug that set `tmask $0003 → $7BDE` this session: the sprite
  copy `move.l (A0)+,(A1)+` at 68K `$08DE` with `A1=$B00000` was writing the task
  table. Fix was to gate `op_movl_anp_anp`'s dest write on `dst An high16 == $00F0`.

**Before adding any real hardware-write path, audit EVERY store handler.** The
correct architecture is a single dispatch on the destination's 68K high byte:

| 68K addr (high) | Region (arcade)            | Action |
|---|---|---|
| `$F0xxxx` | 68K work RAM               | write `$7F:(addr&0xFFFF)` (as today) |
| `$B0xxxx` | **palette RAM (xRGB555, 4KB / 2048 colors)** | → SNES CGRAM path |
| `$D0xxxx` | **sprite Y-low / scroll RAM / ctrl regs (`$D00600`)** | → SNES OAM-Y + BG scroll |
| `$E0xxxx` | **sprite code + X + color (16KB)** | → SNES OAM + BG tilemap |
| `$30/$40/$60 xxxx` | **video control/strobe regs (constant `$0010`/frame)** | enable/ack — not pixel data |
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

Address map authority: `TRANSPILER_DESIGN.md` §D4 and memory `arcade-address-map`
(`$B00000/$D00000/$E00000/$F00000` — the *corrected* map; old docs had a
digit-dropped version). Cross-check every bank against MAME's `taito_x.cpp` mapping
before trusting it.

Recommendation: write `store8/store16/store32(addr_hi16, addr_lo16, value)` helpers
that do the bank dispatch **once**, and route every store handler through them
(`writebyte/writeword/writelong` already do the `$F0`-only check — generalize those
and make the predecrement/postincrement/movem/clr handlers call them instead of
inlining `sta $7F0000,x`). Handlers currently inlining `$7F`: `op_movl_anp_anp`
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
  frame. Display-enable / IRQ-ack strobes — they do NOT carry pixel data, so the
  translator only needs to shadow them (and can ignore them for rendering v1).
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
`CCHIP_BOOT_HANDSHAKE.md`).

## How to develop/verify the plumbing

1. **Capture the oracle.** In MAME, `install_write_tap` over `$300000-$6FFFFF` and
   `$B00000-$Bxxxxx` (and `$E0xxxx`); log `(PC, addr, value)` per frame for a few
   boot frames. That is the exact target write stream. (Same tap infra as
   `tools/mame-trace/trace_io_diff.lua`.)
2. **Decode the formats.** Sprite struct at `$F01712` → X1-001 OBJ attributes →
   SNES OAM. The graphics *decode* is already validated end-to-end
   (`PALETTE_VERDICT.md`, memory `sprite-palette-bank-model`,
   `superscaler-snes-technique`); this phase is *transport*, hooking those writes to
   the proven PPU path, not re-deriving formats.
3. **Liveness/sync probes** (proven this session):
   - `$F01C56` (work RAM `$11C56`) = per-frame counter, increments every frame —
     heartbeat to confirm frame timing.
   - iloop ring index `$48` and the VBLANK countdown `$8A` — "is the interpreter
     loop even running" (both froze on the `idone` infinite loop).
   - `tmask` at `$F00002` should hold `$0003` (matches MAME); any drift means a
     store handler is clobbering the task table (bank-dispatch bug).
4. **Compare** a rendered frame to MAME via the Mesen real-PPU path (memory
   `mesen-mcp-validation`).

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
  cleared $7E (hash uncleared → hang; OAM/tilemap garbage). See [[poppy-asm-gotchas]].
- **Stage 5 ✓** BG tile cache: open-addressing **hash dedup** (O(1)) + **per-tile VRAM
  DMA** (no staging cap, up to 192 codes = VRAM budget). The live game now runs ~180x
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
