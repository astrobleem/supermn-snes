# Superman Arcade → SNES Port Plan

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        SNES Hardware                         │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────┐    Mailbox     ┌──────────┐                    │
│  │  5A22     │◄─────────────►│  SA-1     │                    │
│  │  Main CPU │   I-RAM       │  Co-proc  │                    │
│  │           │   $3000-$300F  │           │                    │
│  └─────┬─────┘               └─────┬─────┘                    │
│        │                           │                          │
│        │ PPU registers             │ C-Chip emulation         │
│        │ $2100-$213F              │ Sprite compositing        │
│        │                           │ (CC Type 2)              │
│        ▼                           ▼                          │
│  ┌──────────┐               ┌──────────┐                    │
│  │  PPU      │               │  SPC700   │                    │
│  │  BG/SPR   │               │  Audio    │                    │
│  │  $2100+   │               │  TAD      │                    │
│  └──────────┘               └──────────┘                    │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## CPU Responsibilities

### 5A22 (Main CPU)
- Game logic (ported from 68K)
- Input processing (SNES controllers → C-Chip mailbox)
- Sound commands (TAD via $2140-$2143)
- Frame timing (VBlank interrupt)
- PPU register updates (scroll, mode, etc.)

### SA-1 (Co-processor)
- C-Chip emulation (command-response protocol)
- Sprite compositing (CC Type 2 character conversion)
- DMA management (VRAM uploads)
- Math assistance (collision detection)

### SPC700 (Audio)
- Terrific Audio Driver (TAD)
- Music playback (MML songs)
- Sound effects (BRR samples)

## Memory Map

### 5A22 Address Space
| Address | Usage |
|---|---|
| $0000-$1FFF | WRAM (mirrored) |
| $2100-$213F | PPU registers |
| $2140-$2143 | APU IO |
| $2180-$2183 | WRAM access |
| $4000-$401F | CPU registers |
| $4200-$421F | PPU/CPU registers |
| $6000-$7FFF | SRAM (save data) |
| $8000-$FFFF | ROM (LoROM) |

### SA-1 I-RAM (Shared)
| Address | Usage |
|---|---|
| $3000-$3005 | C-Chip mailbox |
| $3010-$301F | C-Chip scratch |
| $3100-$31FF | Sprite compositing buffer |
| $3200-$37FF | General scratch |

### SA-1 BW-RAM
| Address | Usage |
|---|---|
| $400000-$407FFF | Tile data (converted from arcade) |
| $408000-$40FFFF | Sprite data |
| $410000-$417FFF | Level data |
| $418000-$41FFFF | Game state |

## Game Logic Porting Strategy

### Phase 1: Core Loop
1. Port MAIN_LOOP ($0008FA) to 5A22 ASM
2. Port INPUT_READ to read SNES controllers
3. Port C-CHIP_CMD to use SA-1 mailbox
4. Set up VBlank interrupt for frame timing

### Phase 2: Player & Enemies
1. Port PLAYER_CTRL ($004A9E)
2. Port ENEMY_AI ($024AA8)
3. Port PHYSICS ($024588)
4. Port COLLISION ($028F92)

### Phase 3: Graphics
1. Port SPRITE_DRAW ($005BE4) → SA-1 CC Type 2
2. Port SCROLL ($005C5E) → PPU scroll registers
3. Port GFX_RENDER ($0571EE) → SA-1 compositing
4. Convert tile data from arcade format to SNES format

### Phase 4: Audio
1. Port SOUND_DRIVER ($002D8A) → TAD
2. Convert YM2610 patches → BRR samples
3. Transcribe music → MML
4. Map sound effects → TAD SFX

### Phase 5: Game State
1. Port LEVEL_LOAD ($00C9F8)
2. Port SCORE ($00DE82)
3. Port WEAPON ($024920)
4. Port POWERUP ($02498C)
5. Port DEATH ($01242E)
6. Port GAME_OVER ($000CC0)

## Key Differences: Arcade → SNES

### Graphics
- **Arcade:** 384×240, 4096 colors, hardware sprites
- **SNES:** 256×224, 256 colors (8bpp), 128 sprites
- **Solution:** Use Mode 1 (4bpp BG1/BG2, 2bpp BG3), SA-1 CC Type 2 for sprite scaling

### Audio
- **Arcade:** YM2610 (FM + ADPCM), Z80 driver
- **SNES:** SPC700 (8ch ADPCM), TAD driver
- **Solution:** Convert FM patches to BRR, transcribe music to MML

### Input
- **Arcade:** 8-way joystick + 2 buttons, coin slots, DIP switches
- **SNES:** D-pad + 6 buttons (A/B/X/Y/L/R), Start/Select
- **Solution:** Map SNES buttons to arcade inputs, use Select for coin

### C-Chip
- **Arcade:** External MCU with encrypted firmware
- **SNES:** SA-1 emulation state machine
- **Solution:** Table-driven command-response, track game state in SA-1 I-RAM

## Frame Timing

### Arcade (60Hz)
1. IRQ2 fires (VBlank)
2. GAME_TICK runs
3. MAIN_LOOP processes all subsystems
4. Frame registers updated ($300000, $400000, $600000)
5. C-Chip polled for input

### SNES (60Hz)
1. VBlank NMI fires
2. SA-1 processes C-Chip mailbox
3. 5A22 runs MAIN_LOOP
4. SA-1 composites sprites during active display
5. DMA transfers to VRAM during VBlank

## Data Conversion

### Tile Data
- Arcade: 4bpp planar format (32 bytes per 8×8 tile)
- SNES: 4bpp packed format (32 bytes per 8×8 tile, different bitplane order)
- Tool: `tools/extract_tiles.py` (already written)

### Sprite Data
- Arcade: Variable size, hardware scaling
- SNES: Fixed sizes (8×8 to 64×64), no hardware scaling
- Tool: SA-1 CC Type 2 character conversion

### Palette
- Arcade: 12-bit (4096 colors), 256 entries
- SNES: 15-bit (32768 colors), 256 entries (16 per palette)
- Conversion: Direct mapping (12-bit → 15-bit)

### Sound
- Arcade: YM2610 FM + ADPCM-A (4ch) + ADPCM-B (1ch)
- SNES: SPC700 8ch ADPCM
- Conversion: FM patches → BRR samples, ADPCM → BRR
