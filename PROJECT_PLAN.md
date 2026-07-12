# Superman Arcade → SNES Port
## Project Plan: Porting Taito's Superman (1996) to Super Nintendo

> **RECOVERY OVERRIDE — July 12, 2026:** this is the original project-plan snapshot, not current
> status. Start at [`RECOVERY.md`](RECOVERY.md). The canonical build runs at 1.3237 game-fps
> post-arm; performance architecture is the active gate.

> **Current status: see [`STATUS.md`](STATUS.md).** Snapshot (June 17, 2026):
> graphics path validated on real SNES PPU (`PALETTE_VERDICT.md`); transpiler
> design settled (`TRANSPILER_DESIGN.md`) and gate **G2 green** — two 68K leaves
> differentially verified vs MAME (`SPIKE_RESULT.md`); disassembly coverage (gate
> **G1**) has a reliable trace-driven pipeline at 10.2% confirmed / 779 jump tables
> resolved, climbing via a full playthrough trace (`COVERAGE_G1.md`). Bulk
> transpilation, C-Chip, and audio not yet started.

---

## Source Hardware: Taito X System

| Component | Taito X Spec | Notes |
|---|---|---|
| **Main CPU** | Motorola 68000 @ 8MHz | 16-bit CISC, big-endian |
| **Sound CPU** | Z80 @ 4MHz | Shares RAM with 68K |
| **Sound Chip** | YM2610 (OPNB) | FM synthesis + ADPCM-A (4ch) + ADPCM-B (1ch) |
| **Resolution** | 384×240 @ 60Hz | Interlaced capable |
| **Tilemap** | Custom (X1-001A, X1-002A) | 2-3 scrolling layers, 8×8 tiles |
| **Sprites** | Custom (X1-006) | Variable size, flipping, priorities |
| **I/O** | X1-004 | Coin, controls, DIP switches |
| **Protection** | C-Chip (68705 MCU) | Encrypted Z80, game logic |
| **Colors** | 12-bit (4096 palette) | 256 on-screen typical |
| **ROM Total** | 3.2MB across 10 chips | |

---

## Target Hardware: SNES + SA-1

| Component | SNES/SA-1 Spec | Advantage |
|---|---|---|
| **Main CPU** | Ricoh 5A22 (65816) @ 3.58MHz | 16-bit, fast page 0 |
| **Coprocessor** | SA-1 @ 10.74MHz | 3× speed of 5A22, same 65816 ISA |
| **Sound CPU** | SPC700 @ 2.048MHz | With Terrific Audio Driver |
| **Resolution** | 256×224 (typical) or 512×448 | Mode 7 for pseudo-3D |
| **Tilemap** | PPU BG1-BG4, Mode 0-7 | Hardware scrolling, flipping |
| **Sprites** | OAM: 128 sprites, 4 sizes | 32×32 to 64×64 |
| **Colors** | 15-bit (32768 palette) | 256 on-screen (8bpp) |
| **Audio** | 8 channels ADPCM | TAD: MML, envelopes, effects |
| **Extra** | MSU-1 for streaming audio/data | PCM music, large assets |

---

## Critical Architecture Decisions

### 1. 68000 → SA-1 Code Port

The main game logic is 68000 assembly (big-endian CISC). The SA-1 is also a 65816
(little-endian CISC-like). Strategy:

- **Automated translation**: Write a 68000→PASM transpiler for the bulk of game logic
  - Map 68K registers to SA-1 direct page
  - Translate addressing modes (68K has more flexible modes)
  - Handle big-endian→little-endian data access
  - Map 68K exception vectors to SA-1 vectors
- **Hand-optimize critical paths**: VBlank, sprite DMA, collision detection

**Key insight from SuperMonkeyIsland**: The SMI project already proved you can run a
complex game engine (SCUMM) on the SA-1. Superman's game loop should be simpler.

### 2. Graphics: Arcade Tile/Sprite → SNES PPU

**Tilemaps**: Taito X uses 8×8 tiles in planar format (likely 4bpp).
SNES uses 8×8 tiles in packed format (2bpp, 4bpp, or 8bpp).

- Convert tile data from planar to packed format
- Use SNES BG layers: BG1 (main), BG2 (alt), HUD on BG3
- Scroll registers map directly to Taito's scroll hardware

**Sprites**: Taito X sprites are variable size with hardware scaling.
SNES sprites are fixed sizes (8×8 to 64×64) with no hardware scaling.

**SA-1 CC Type 2 is CRITICAL here**:
1. Extract sprite data from arcade ROM (already in bitplane format)
2. Use SA-1 CC Type 2 (Character Conversion) to convert bitmap → tile format
3. SA-1 can composite scaled sprites into tile data, then DMA to VRAM
4. This is EXACTLY what SuperMonkeyIsland does for sprite rendering

### 3. Sound: YM2610 → Terrific Audio Driver

The YM2610 provides:
- 4 FM channels (OPNB, same as OPN2)
- 4 ADPCM-A channels (voice)
- 1 ADPCM-B channel (waveform)

TAD provides:
- 8 software-mixed channels on SPC700
- MML (Music Macro Language) song format
- Software ADSR/GAIN envelopes
- Vibrato, portamento, volume slides

Strategy:
1. Extract YM2610 FM patches from sound ROM (b61_09.a10)
2. Transcribe songs to MML by analyzing the Z80 sound driver
3. Convert ADPCM samples → BRR (SNES native format)
4. Use tad-compiler to generate SNES-ready audio data

### 4. C-Chip: The Protection Problem

Superman uses a C-Chip (68705 MCU) for:
- Protection/encryption
- Possibly game state verification
- Input processing

Strategy:
1. **Analyze the C-Chip communication protocol** from MAME source (cchip.c)
2. **Patch out protection checks** in the main 68K code
3. **Emulate C-Chip inputs** via a lookup table or simple state machine on SA-1

---

## ROM Breakdown & Asset Extraction Plan

| ROM File | Content | Extraction Method |
|---|---|---|
| b61-01.e18 | 68K code (lo) | Disassemble with Ghidra/IDA → PASM |
| b61-14.f1 | 68K code (hi) | Merge with lo, then disassemble |
| b61-15.h1 | Tile gfx 0 (512KB) | Parse planar 4bpp → SNES packed |
| b61-16.j1 | Tile gfx 1 (512KB) | Parse planar 4bpp → SNES packed |
| b61-17.k1 | Sprite gfx (512KB) | Parse planar 4bpp → SA-1 CC Type 2 |
| b61_07.a5 | C-Chip code (128KB) | Analyze for protocol emulation |
| b61_08.a8 | Z80 sound code (128KB) | Disassemble for song data format |
| b61_09.a10 | YM2610 samples (128KB) | Extract ADPCM → convert to BRR |
| b61_10.d18 | C-Chip data (64KB) | Analyze for lookup tables |
| b61_13.a3 | Tile gfx 2 (128KB) | Parse planar 4bpp → SNES packed |

---

## Project Milestones

### Phase 1: Foundation (Week 1-2)
- [x] Set up project structure
- [x] Analyze ROM layout
- [x] Write tile extraction tool (planar → packed)
- [x] Set up Poppy build pipeline
- [x] Get booting ROM with valid header + vectors
- [ ] Port SMI's SA-1 CC Type 2 code as starting point
- [ ] Write sprite extraction tool

### Phase 2: Graphics Pipeline (Week 3-4)
- [ ] Convert all tile data to SNES format
- [ ] Convert sprite data for SA-1 CC Type 2
- [ ] Implement tilemap rendering (BG layers)
- [ ] Implement sprite rendering (SA-1 compositing)
- [ ] Test in Mesen-MCP with SA-1 core

### Phase 3: Game Logic (Week 5-8)
- [~] Disassemble 68K game code — trace-driven CDL pipeline (gate G1); 10.2%
      confirmed code, 779 jump tables resolved, climbing (`COVERAGE_G1.md`)
- [~] Write 68K→PASM transpiler — design settled (D1–D4, `TRANSPILER_DESIGN.md`);
      hand-transpile + differential harness proven (gate G2, `SPIKE_RESULT.md`);
      tool-generation not started
- [ ] Decide transpile-all vs interpret-cold/transpile-hot hybrid (risk-doc fork)
- [ ] Port game loop, input, collision
- [ ] Emulate C-Chip protocol
- [ ] Port level data structures

### Phase 4: Audio (Week 9-10)
- [ ] Extract YM2610 FM patches
- [ ] Transcribe songs to MML
- [ ] Convert ADPCM samples to BRR
- [ ] Integrate TAD into build pipeline
- [ ] Test audio in emulator

### Phase 5: Integration & Polish (Week 11-12)
- [ ] Full game boot and playability
- [ ] Performance optimization (SA-1 usage)
- [ ] Bug fixing via Mesen-MCP debugging
- [ ] Final ROM build and testing

---

## Key Technical References

- SuperMonkeyIsland SA-1 code: `/home/chad/SNES-SuperMonkeyIsland/src/core/sa1_boot.65816`
- TAD audio driver: `/home/chad/terrific-audio-driver/`
- Poppy assembler: `/home/chad/poppy/`
- Mesen-MCP: `/home/chad/Mesen2/`
- MAME Taito X driver: `mame/src/mame/taito/taito_x.cpp`
- MAME C-Chip driver: `mame/src/mame/machine/cchip.c`
