# Superman Arcade → SNES Port
## Technical Reference & Progress

### Source Hardware: Taito X System (1988)

**Complete Memory Map (from MAME taito_x.cpp):**
```
0x000000-0x07FFFF  : 68000 Program ROM (512KB)
0x900000-0x900FFF  : C-Chip shared RAM (1KB window into 8KB SRAM)
0x0B0000-0x0B0FFF  : Palette RAM (4KB, xRRRRRGGGGGBBBBB format)
0x0D0000-0x0D07FF  : Video attribute RAM (2KB)
  0x000-0x3FF : Sprite Y coordinate
  0x400-0x7FF : Tile X & Y scroll
0x0E0000-0x0E0FFF  : Object RAM bank 1 (4KB)
  0x000-0x3FF : Sprite number (0x3FFF) + Y flip (0x4000) + X flip (0x8000)
  0x400-0x7FF : Sprite X (0x1FF) + Sprite color (0xF800)
  0x800-0xBFF : Tile number (0x3FFF) + Y flip (0x4000) + X flip (0x8000)
  0xC00-0xFFF : Tile color (0xF800)
0x0E2000-0x0E2FFF  : Object RAM bank 2 (4KB)
0x0F0000-0x0FFFFF  : Work RAM (64KB)
```

**C-Chip Communication (from MAME taitocchip.cpp):**
- 68K accesses C-Chip shared RAM at $900000-$900FFF (mem68_r/mem68_w)
- ASIC registers at $900800-$900FFF (asic_r/asic68_w)
- C-Chip contains: uPD78C11 MCU + 8KB external EPROM + 8KB SRAM + ASIC
- 1KB window into 8KB SRAM, banked via register at $900600
- Used for: input processing, protection, game state verification

**ROM Layout (from MAME):**
```
68K Code (512KB):
  b61_09.a10  128KB  even bytes, 0x00000-0x0FFFF
  b61_07.a5   128KB  odd bytes,  0x00000-0x0FFFF
  b61_08.a8   128KB  even bytes, 0x40000-0x4FFFF
  b61_13.a3   128KB  odd bytes,  0x40000-0x4FFFF

Graphics (2MB, 4bpp planar):
  b61-16.j1   512KB  Plane 2,3 at gfx offset 0x000000
  b61-17.k1   512KB  Plane 2,3 at gfx offset 0x100000
  b61-14.f1   512KB  Plane 0,1 at gfx offset 0x000002
  b61-15.h1   512KB  Plane 0,1 at gfx offset 0x100002

Sound:
  b61_10.d18   64KB  Z80 program
  b61-01.e18  512KB  YM2610 ADPCM samples

|C-Chip:
  b61_11.m11   8KB  C-Chip external EPROM (hash-verified, on disk)
  cchip_upd78c11.bin  4KB  uPD78C11 internal mask ROM (hash-verified, on disk)
```

**Key 68K Addresses (from MAME source analysis):**
- Reset vector: SP=0x00F03FFE, PC=0x00003EF0
- C-Chip shared RAM: $900000-$900FFF
- Sound command: 0x800001 (TC0140SYT master_port_w)
- Sound status: 0x800003 (TC0140SYT master_comm_r)
- DIP switches: 0x500000-0x500007
- Work RAM: 0x0F0000-0x0FFFFF
- Palette: 0x0B0000-0x0B0FFF
- Sprite/tile RAM: 0x0E0000-0x0E3FFF
- Video regs: 0x0D0000-0x0D07FF

**Input Ports:**
- IN0: Player 1 (Up/Down/Left/Right + 2 buttons)
- IN1: Player 2 (Up/Down/Left/Right + 2 buttons)
- IN2: Coin1, Coin2, Service1, Tilt
- DSWA: Coinage (world: 1C/1C, 2C/1C, etc.)
- DSWB: Difficulty (Easy/Medium/Hard/Hardest), Lives (3-6), Demo Sounds, Flip Screen

### Disassembly Status (updated June 17, 2026 — see `COVERAGE_G1.md`)

- ✅ ROM image built: data/superman_m68k.bin (512KB)
- ✅ **Trace-driven CDL pipeline** (`tools/build_cdl.py`): the MAME execution trace
  IS the code/data log — confirmed code only, exact lengths, resolves indirect
  jumps (H6). The old "14%" was an unreliable linear sweep (data mis-decoded as
  code); reliable baseline was ~3.4%.
- ✅ **10.2% of ROM confirmed-executed code** (15,148 instr, zero false positives)
  and **779 indirect jump-table targets resolved**, driven by scripted states + a
  full beat-the-game playthrough (`inp/superman_play.inp`) + service menu.
- ✅ Peony recursive descent from these seeds: **35,047 blocks** (vs 483);
  ≥43.6% code / ≥67.5% ROM classified (`data/merged.cdl` → `tools/measure_coverage.py`).
- 📋 Next (G1→85%): land full descent %; more playthroughs for missed paths;
  endianness manifest (G4).

### SNES Mapping Plan

**CPU:**
- 68K game logic → SA-1 (same 65816 ISA, 3× clock speed)
- Main 5A22 → I/O, sound, VBlank processing

**Graphics:**
- Arcade sprites → SA-1 CC Type 2 (like SuperMonkeyIsland)
- Tilemaps → SNES BG layers (Mode 0 or Mode 1)
- Palette → SNES CGRAM (4096 colors → 256 colors, 16 per palette)

**Sound:**
- YM2610 FM → render to BRR samples (TAD is sample-based, no FM synthesis)
- YM2610 ADPCM → BRR samples
- Z80 sound driver → TAD MML songs

**C-Chip:**
- Emulate on SA-1 or main CPU
- Map communication to $900000 equivalent in SNES address space
- May need to patch out protection checks

### Build Tools
- Peony (M68K disassembly): ✅ Built and working
- Poppy (SNES assembly): ✅ Built and working — primary assembler for code + vectors
- WLA-DX 10.7a: ✅ Built from source — NOT used for final build (see BLOCKERS.md)
- WLA-DX 9.5: Available from SMI project — NOT used (older, same bugs)
- Mesen-MCP (debugging): ✅ Working with SA-1
- TAD (audio): ✅ Built and working
- Tile converter: ✅ Planar → packed conversion done
- build_rom.py: ✅ Creates final ROM with LoROM header + checksum from Poppy binary

### Current Build Pipeline
1. `make` → Poppy assembles src/main.pasm → src/main.bin (32KB, code + vectors)
2. `build_rom.py` → Creates 64KB LoROM image with header at $7FC0, copies code,
   injects vectors, computes checksum
3. Output: distribution/superman.sfc (64KB, valid checksum, boots in emulator)

### Known Issues
See BLOCKERS.md for resolved findings and notes.
All previous blockers (map mode byte, vector addresses, fix_header.py, WLA-DX quirks) are resolved.
