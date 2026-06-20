# Video Plumbing — wiring the live 68K interpreter to the SNES PPU

Created June 19, 2026, right after the interpreter reached Superman's **live
per-frame game loop** (see `STATUS.md`, `INTERPRETER_SPIKE.md`). The game is
running *blind*: every 68K write to a video/sprite hardware bank is currently a
**no-op**, so no pixels reach the SNES PPU. This doc captures exactly what the boot
does with the video hardware, what I learned getting it alive, and the concrete
plan + traps for the next phase.

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
| `$B0xxxx` | **sprites / objects (X1-001 OBJ)** | → SNES OAM / OBJ path |
| `$D0xxxx` | (per D4 map)               | video |
| `$E0xxxx` | (per D4 map; cleared at boot, `clr.w (A0)+` loop @ `$2692`, `A0=$E00800`) | video |
| `$30/$40/$60 xxxx` | **video regs / tilemaps (X1-001 BG/scroll)** | → SNES BG path |
| else | I/O (`$50` DIP, `$80` sound, `$90` C-Chip) | existing readbyte stubs / no-op |

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

- **Per-frame video register writes** — frame-work `$3A92`:
  - `$3A96 move.w D0,($00600000)`
  - `$3A9C move.w D0,($00300000)`
  - `$3AAA move.w D0,($00400000)` (gated by `tst.b ($F00000)` at `$3AA2`)
  These go through `op_movw_dn_abs`, which today no-ops any non-`$F0` dest. They are
  almost certainly VDP/X1 control-register pokes (display enable / layer setup).
- **Video RAM clear** — `$2692 clr.w (A0)+` loop, `A0=$E00800` (32-bit clear of a
  video region at boot). Handler `op_clrw_anp` already no-ops non-`$F0`.
- **Sprite/OBJ upload** — `$08DE move.l (A0)+,(A1)+`, `A1=$B00000`, inside a
  bit-masked loop (`$08C2`–`$08F2`) driven by `D6=($F01B12)`: per set bit it copies
  8 longs (32 bytes) from a work-RAM sprite struct (`A0=$F01712+`) to `$B00000+`,
  else skips `$20`. **This is the OBJ DMA** — the per-frame sprite list. The source
  layout in work RAM (`$F01712`...) is the thing to decode into SNES OAM.

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
