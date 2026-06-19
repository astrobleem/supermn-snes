# Superman Arcade -> SNES Port — Known Issues & Notes
# Last updated: June 16, 2026

This document describes technical findings from the initial ROM bring-up.
Most "blockers" turned out to be misunderstandings — see ADVICE.md for the
full analysis. What remains are genuine notes for future work.

---

## RESOLVED: Map Mode Byte

**Finding:** $30 is the correct map mode byte for LoROM + FastROM.
WLA-DX writes $30 correctly. The 12 reference ROMs in /home/chad/ROMS/ all
have $20 because they are slow-ROM games.

**Decision:** Use $30 (LoROM + FastROM). Our code sets MEMSEL=$01 at runtime.

**Files updated:** build_rom.py, main.65816

---

## RESOLVED: Interrupt Vector Addresses

**Finding:** Poppy resolves LoROM label addresses correctly. The previous
hardcoded addresses ($8033/$8034/$8032) were off by 1 byte each — they
"worked" only because all three handlers were contiguous `rti` bytes.

**Decision:** Reverted to label-based vectors. Verified correct in output.

**Files updated:** src/main.pasm

---

## RESOLVED: fix_header.py

**Finding:** Dead code (not in makefile), wrong checksum field order,
writes invalid $02 map mode byte.

**Decision:** Deleted.

---

## NOTE: WLA-DX SNES Header Directives

WLA-DX's `.SNESHEADER`, `.SNESNATIVEVECTOR`, and `.SNESEMUVECTOR` directives
have quirks that make them difficult to use for manual header placement:

1. `.SNESHEADER` auto-computes checksum, which conflicts with manual checksum
   bytes written via `.org $FFC0` + `.db` directives
2. `.SNESNATIVEVECTOR` creates a section that overlaps with manually-placed
   header bytes at $7FE0+
3. `.org $7FC0` in the header section causes "origin overflow" because the
   MEMORYMAP maps bank 0 at $8000-$FFFF, and $7FC0 is below that range

**Current approach:** Use Poppy for code + vectors, build_rom.py for header.
This works well and is the recommended path. WLA-DX is not needed for the
current build.

**If WLA-DX is needed later** (e.g., for SA-1 banking/sections), the fix is:
- Use `.org $FFC0` (CPU address, not file offset) for the header
- Use `.org $FFE0` / `.org $FFF0` for vectors
- Don't mix `.SNESHEADER` with manual header bytes

---

## NOTE: SNES Checksum Algorithm

The correct algorithm (verified against 12 commercial ROMs):

1. Zero the 4 checksum-field bytes ($FFDC-$FFDF)
2. S = (sum of all ROM bytes) mod 0x10000
3. Write **complement** = S XOR 0xFFFF at $FFDC (little-endian)
4. Write **checksum** = S at $FFDE (little-endian)

The only invariant that matters: checksum + complement = 0xFFFF (as 16-bit words).

No emulator refuses to boot on a bad checksum — bsnes/higan/Mesen report
mismatches in the ROM info panel but boot regardless. The field matters for
ROM databases, flash-cart menus, and good hygiene.

Reference: /home/chad/snesmanual/fullsnes.txt — "SNES Cartridge ROM Header"

---

## NOTE: Build Pipeline

Current: `make` → Poppy assemble → build_rom.py → distribution/superman.sfc

- src/main.pasm: 65816 assembly (Poppy format) — code + vectors
- src/main.bin: 32KB Poppy output (code + vectors, no header)
- build_rom.py: Creates 64KB LoROM image with header + checksum
- Output: distribution/superman.sfc (64KB, valid checksum)

---

## Open Questions for Future Work

1. **ROM size:** Header says 256KB ($08) but file is 64KB. Harmless for
   emulators, but should be corrected when the ROM grows.
2. **SA-1 support:** poppy.json declares SA-1, but the header writes cart
   type $00 (ROM only). Update when SA-1 is wired up.
3. **SRAM:** Header writes $00 SRAM. Update if save data is needed.
