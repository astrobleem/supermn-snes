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

| cmd | type    | cue (evidence)                              | → TAD track            | confidence |
|----:|---------|---------------------------------------------|------------------------|------------|
| `$00` | control | stop/silence — precedes coin & new SFX; fires at attract-end | (Tad stop / none) | high |
| `$05` | music   | **attract music** (fires as attract music starts, frame 29017; re-fires each attract loop) | 01 Attract | high |
| `$06` | control | fires ×3 at round start (init/fade-in?)     | (control)              | med |
| `$07` | sfx     | **punch** (P1 Button 1, no enemy)           | — (SFX)                | med |
| `$19` | sfx/mus | **coin insert** (after a `$00` stop)        | 02 Coin                | high |
| `$32` | music   | **Round 1 music** (screenshot-confirmed: Superman city street, right after Start) | 03 Main BGM 1 | high |
| `$62` | sfx     | **jump/kick** (P1 Button 2 while walking)   | — (SFX)                | low |

### Full observed vocabulary (attract demo + driven events), by frequency
`$4E`(144) `$2E`(141) `$23`(37) `$5B`(30) `$43`(26) `$1F`(12) `$59`(12) `$24`(10) `$1D`(9)
`$1C`(8) `$3F`(6) `$44`(5) `$3C`(4) `$3D`(4) `$64`(4) `$06`(3) `$62`(3) `$00`(3) `$1B`(2)
`$3B`(2) `$05`(2) `$30`(1) `$31`(1) `$32`(1) `$47`(1) `$51`(1) `$61`(1) `$63`(1) `$71`(1)
`$07`(1) `$19`(1)

`$4E`/`$2E` dominate the attract stream = the demo's recurring action SFX (punch/hit/step).
The `$1X`-`$7X` bytes appear to be SFX ids grouped by high nibble; `$0X` bytes are control verbs.
These are **not** a simple "song N = byte N" scheme — the Z80 has an arbitrary id→handler table
(attract=`$05`, round1=`$32`), so each cue's byte must be observed, not computed.

## UNKNOWN / to backfill (music triggers not yet reached)

Tracks **04-21** (Boss 1-7, Main BGM 2/3, Round Clear, Continue, Round5 variants, Ending, Name
Entry, Game Over) — not reached in the driven session (require deeper play). Not needed for the
P2 mechanism proof; backfill during P3 when the real songs exist.

**Backfill method (reliable):** the enqueue helper runs RAM-resident (`$f01b54`) so static-disasm
caller labeling is noisy; instead re-run the live trace with the `$800003` write-tap (records
frame + full command byte in D1) and reach each event (boss, round-clear, death, ending) by play
or state-poke, noting the byte at the moment the music changes. Harness lives in this session's
MAME logs: `.mame_mcp/snd_full.log` (send-side), `.mame_mcp/enq.log` (ring enqueues).
