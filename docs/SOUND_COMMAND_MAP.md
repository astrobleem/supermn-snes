# Sound-command RE — arcade → TAD map (P2 STEP 1)

Reverse-engineered 2026-07-07 via live MAME trace of `superman` (Taito X). This is the
command-id → musical-cue → TAD-track table that P2 wiring routes through. See
[[sound-port-scope]] / [[sound-p1-progress]] for the surrounding plan.

## Model (CONFIRMED, not inferred)

The arcade sound is a **single-byte trigger** interface, NOT streamed music:
- The 68K sends compact command bytes through the TC0140SYT latch; the **Z80 owns a full
  music/SFX engine + song data** (in `b61_10.d18` + sample ROM `b61-01.e18`) and sequences
  everything autonomously.
- **Decisive test:** with a Z80-side tap on the YM2610 ports (`$E000-$E003`), over 120 frames
  of steady round-1 gameplay the **Z80 wrote the YM2610 5116 times while the 68K sent 0 sound
  commands.** Music plays entirely Z80-driven; the 68K is silent between triggers. (This ruled
  out the "68K streams music" alternative — the earlier "idle gameplay is quiet" observation was
  confounded and did NOT by itself prove triggers; the YM-write tap does.)

**Consequence for the port:** we do NOT replicate arcade note data. We detect *which cue* each
trigger byte selects (by game event) and route it to the matching **TAD song** (our MML drafts).
The Z80's internal song data is irrelevant to us — TAD is our sequencer.

## Send path (68K side)

- Command bytes are enqueued into a 32-byte ring buffer at **`$f01c20`-`$f01c3f`**
  (write ptr `$1c40(a5)`, read ptr `$1c44(a5)`, both init to `$f01c20`; wrap at `$f01c40`).
  `a5 = $00f00000`.
- A per-frame drain (`$2db0`) sends **one** queued byte per frame (when the TC0140SYT reports
  ready) via the send helper **`$2df0`**:
  ```
  $2df0: move.b d0,$800001   ; d0 = port-select = 0
  $2df6: move.b d1,$800003   ; FIRST write: bus byte = FULL command byte (e.g. $4E)
  $2dfc: lsr.w #4,d1
  $2dfe: move.b d1,$800003   ; SECOND write: bus byte = command>>4 (e.g. $04)
  $2e04: rts
  ```
  The TC0140SYT takes the low nibble of each write; the Z80 reassembles `cmd = lo | (hi<<4)`.
- `$2e06` is a **separate status-poll** helper (writes `$800001`, reads `$800003` twice); it is
  the game's sound-ready handshake and does NOT write `$800003`. So every `$800003` **write**
  belongs to a `$2df0` send pair.

### Interp-side capture (how P2 STEP 2 grabs the byte)
The **first** `$800003` write of each pair already carries the FULL command byte on the bus
(verified in MAME: `move.b d1,...` puts d1's whole low byte on the bus, `$4E` not the masked
`$0E`). So the supervisor needs only:
- on a write to **`$800001`** (hi16 `$0080`, lo16 `$0001`): **arm**.
- on the next write to **`$800003`** (hi16 `$0080`, lo16 `$0003`) while armed: **command = that
  byte**; disarm.
No nibble reassembly needed. (Status polls re-arm harmlessly — they never write `$800003`.)

## Command → cue → TAD-track table

Event correlations are from driving the live machine (coin/start edges, button inputs) and a
screenshot confirmation for round-1. TAD track numbers refer to `soundwork/tad/mml_drafts/NN_*`.

**GROUND TRUTH (P3 backfill, 2026-07-09) — the full music map.** Method: every byte
`$01-$7F` was stimulated DIRECTLY on the arcade machine in MAME (Lua writes to the
TC0140SYT latch replicating the `$2df0` sequence, with the 68K halted so the attract demo
couldn't contaminate), and the Z80's resulting YM2610 register stream was reduced to a
key-on fingerprint and matched against all 21 VGM rips (same engine + data → exact-prefix
matches). The music ids are the **contiguous block `$05-$19`** — a perfect bijection onto
the 21 tracks; every weak first-pass match was re-captured at 32 events and confirmed
exact. The two knowns anchor it ($05 attract, $19 coin).

| cmd | → track (VGM #) | TAD song id | | cmd | → track (VGM #) | TAD song id |
|----:|------------------|----:|-|----:|------------------|----:|
| `$00` | stop/silence   |  0 | | `$10` | 15 Round 5-3   | 15 |
| `$05` | 01 Attract     |  1 | | `$11` | 16 Round 5-4   | 16 |
| `$06` | 03 Main BGM 1  |  3 | | `$12` | 17 Boss BGM 6  | 17 |
| `$07` | 08 Main BGM 3  |  8 | | `$13` | 18 Boss BGM 7  | 18 |
| `$08` | 04 Boss BGM 1  |  4 | | `$14` | 07 Round Clear |  7 |
| `$09` | 05 Main BGM 2  |  5 | | `$15` | 12 Continue    | 12 |
| `$0A` | 06 Boss BGM 2  |  6 | | `$16` | 19 Ending      | 19 |
| `$0B` | 09 Boss BGM 3  |  9 | | `$17` | 20 Name Entry  | 20 |
| `$0C` | 10 Boss BGM 4  | 10 | | `$18` | 21 Game Over   | 21 |
| `$0D` | 11 Boss BGM 5  | 11 | | `$19` | 02 Coin        |  2 |
| `$0E` | 13 Round 5-1   | 13 | | `$2E`/`$4E` | action SFX (demo-dominant) | sfx 1/0 |
| `$0F` | 14 Round 5-2   | 14 | | `$62` | two-drum thud SFX | sfx 1 |

**CORRECTIONS to the earlier event-correlation guesses** (this is why direct stimulation
beats correlation): `$32` is NOT round-1 music — it is a rising-scale SFX (likely the
"Superman flies up" jingle); the round-start burst that was screenshot-correlated
contained both `$06` (the REAL Main BGM 1 trigger, previously misread as "control ×3")
and `$32`. And `$07` is Main BGM 3, NOT punch — the demo's dominant action SFX are
`$4E`/`$2E`. Bytes `$1A-$7F` (minus the SFX rows above) are SFX/jingles — unmapped until
real SFX are authored. Curiosity: a few ids ($1D/$2C/$3A/$52/$60/$6F) restart the attract
music; harmless, left unmapped.

All rows are wired in `snd_map` (src/video.pasm) as a 128-entry table (`snd_tbl`); music
routes through `Tad_LoadSongIfChanged` so repeated sends (e.g. `$06` ×3 at round start)
don't restart the song, while an intervening `$00` still forces a real restart.

### Full observed vocabulary (attract demo + driven events), by frequency
`$4E`(144) `$2E`(141) `$23`(37) `$5B`(30) `$43`(26) `$1F`(12) `$59`(12) `$24`(10) `$1D`(9)
`$1C`(8) `$3F`(6) `$44`(5) `$3C`(4) `$3D`(4) `$64`(4) `$06`(3) `$62`(3) `$00`(3) `$1B`(2)
`$3B`(2) `$05`(2) `$30`(1) `$31`(1) `$32`(1) `$47`(1) `$51`(1) `$61`(1) `$63`(1) `$71`(1)
`$07`(1) `$19`(1)

`$4E`/`$2E` dominate the attract stream = the demo's recurring action SFX (punch/hit/step).
The `$1X`-`$7X` bytes appear to be SFX ids grouped by high nibble; `$0X` bytes are control verbs.
These are **not** a simple "song N = byte N" scheme — the Z80 has an arbitrary id→handler table
(attract=`$05`, round1=`$32`), so each cue's byte must be observed, not computed.

## Backfill method (used for the ground-truth table above)

Playing to each event was never needed. Instead, with a live MAME session:
1. Halt the 68K (SR=$2700 + PC parked on a `bra.s *` in work RAM) so the attract demo
   can't send contaminating commands.
2. Install a Z80-side write tap on the YM2610 ports (`$E000-$E003`), reduced online to a
   key-on fingerprint: `("F", fm_ch, block, fnum)` for FM key-ons (reg $28, using shadowed
   $A0/$A4 pitch), `("A", mask)` for ADPCM-A key-ons (port-1 reg $00, bit7==0).
3. Per candidate byte: send `$00` (stop), settle ~50 frames, then write the byte to the
   TC0140SYT latch exactly as `$2df0` does (`$800001`=0, `$800003`=b, `$800003`=b>>4) and
   capture 16-32 events.
4. Match against the same fingerprint reduction of the 21 VGM rips (exact-prefix scoring;
   the rip is the same Z80 engine + data, so real matches are event-for-event exact).

Sweep of all of `$01-$7F`: ~35k emulated frames, one session.
