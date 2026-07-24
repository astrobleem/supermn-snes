# Superman Game Logic Analysis

## Entry Points (from vector table)

| Vector | Address | Description |
|---|---|---|
| Reset | $003EF0 | Main entry point |
| IRQ2 | $0006C4 | VBlank interrupt |
| IRQ4 | $00082C | Sprite/tile interrupt |
| IRQ6 | $0006C4 | Same as IRQ2 |

## Key Functions (by JSR frequency)

### $0008FA — MAIN_LOOP (34 references)
The most frequently called function. This is the main game loop that runs every frame. Uses `link`/`movem` prologue, processes player input and updates game state.

### $002D8A — SOUND_DRIVER (29 references)
Sound driver — writes to YM2610 at $800001. Called frequently for music and SFX playback.

### $0571EE — GFX_RENDER (10 references)
Graphics rendering — updates sprite/tile RAM at $0E0000.

### $0249C2 — GAME_UPDATE (7 references)
Core game state update — processes scoring, level progression, difficulty.

### $00C9F8 — LEVEL_LOAD (6 references)
Loads level data — maps, tile data, enemy positions.

### $005BE4 — SPRITE_DRAW (6 references)
Sprite drawing — writes sprite data to $0E0000-$0E2FFF.

### $004A9E — PLAYER_CTRL (6 references)
Player control — reads input, updates player position, handles shooting.

### $024AA8 — ENEMY_AI (5 references)
Enemy AI — updates enemy positions and behavior.

### $028F92 — COLLISION (5 references)
Collision detection — player vs enemies, bullets vs enemies.

### $024588 — PHYSICS (5 references)
Physics update — gravity, movement, boundaries.

### $028D70 — INPUT_READ (5 references)
Input reading — reads C-Chip for coin/button status.

### $005C5E — SCROLL (5 references)
Screen scrolling — updates BG scroll registers.

### $00C8E0 — MUSIC (4 references)
Music control — starts/stops music tracks.

### $00091E — INIT (4 references)
Initialization — sets up game state, clears RAM.

### $000C1C — VBLANK (4 references)
VBlank handler — processes per-frame tasks.

### $024920 — WEAPON (4 references)
Weapon handling — shooting, bullet management.

### $02498C — POWERUP (4 references)
Power-up handling — Super Fireball, power-ups.

### $00DE82 — SCORE (4 references)
Score handling — updates score display.

### $000B40 — TITLE (3 references)
Title screen logic — FBI logo, "START" prompt.

### $000A90 — PAUSE (3 references)
Pause handling — checks START button, pauses game.

### $00C9A6 — BOSS (3 references)
Boss logic — boss movement patterns, bullet patterns.

### $00AE8E — DIALOG (3 references)
Dialog/text handling — level text, story text.

### $024956 — PROJECTILE (3 references)
Projectile handling — bullet movement, collision.

### $003A92 — GAME_TICK (2 references)
Game tick — called from IRQ handler, runs main loop.

### $003E0E — CCHIP_CMD (2 references)
C-Chip command — sends commands to C-Chip.

### $01F67E — ANIMATE (2 references)
Animation — sprite animation, tile animation.

### $01242E — DEATH (2 references)
Player death — explosion animation, life loss.

### $000CC0 — GAME_OVER (2 references)
Game over — "GAME OVER" display, continue prompt.

## Frame Execution Order

Based on IRQ handler and function call graph:

1. **IRQ fires** → $0006C4
   - Sets SR to $0700 (disable interrupts)
   - Checks C-Chip status
   - Calls GAME_TICK ($3A92)

2. **GAME_TICK** → $003A92
   - Saves all registers
   - Calls MAIN_LOOP ($0008FA)
   - Restores registers, RTE

3. **MAIN_LOOP** → $0008FA
   - Calls INPUT_READ ($028D70) — reads C-Chip for input
   - Calls PLAYER_CTRL ($004A9E) — updates player
   - Calls ENEMY_AI ($024AA8) — updates enemies
   - Calls PHYSICS ($024588) — applies physics
   - Calls COLLISION ($028F92) — checks collisions
   - Calls SCROLL ($005C5E) — updates scroll
   - Calls SPRITE_DRAW ($005BE4) — updates sprites
   - Calls SOUND_DRIVER ($002D8A) — updates sound

4. **Frame registers** (at $3F26):
   - $300000 = $0000 (watchdog)
   - $400000 = $0000 (control)
   - $600000 = $0000 (control)

## Reset Handler Flow ($3EF0)

1. C-Chip initialization:
   - Write #$0000 to $700000 (C-Chip command)
   - Write #$0003 to $700000 (C-Chip command)
   - Initialize ASIC RAM

2. Video register setup:
   - $D00600 = $0010 (display control)
   - $D00602 = $0021 (tile/sprite control)
   - $D00604 = $00FF (scroll/priority)
   - $D00606 = $00FF (scroll/priority)

3. Frame register init:
   - $300000 = $0000
   - $400000 = $0000
   - $600000 = $0000

4. Work RAM initialization:
   - Clears $0F0000-$0FFFFF (work RAM)
   - Sets up game state variables

5. Enters main loop

## Memory Map Summary

| Address Range | Usage |
|---|---|
| $000000-$07FFFF | 68K Program ROM |
|| $900000-$900FFF | C-Chip (shared RAM + ASIC registers) |
| $0B0000-$0B0FFF | Palette RAM (12-bit: xRRRRRGGGGGBBBBB) |
| $0D0000-$0D07FF | Video attribute RAM |
| $0E0000-$0E3FFF | Sprite/Tile RAM |
| $0F0000-$0FFFFF | Work RAM (64KB) |
| $300000 | Frame register (watchdog) |
| $400000 | Frame register (control) |
| $600000 | Frame register (control) |
| $800001 | Sound command port (TC0140SYT) |
| $800003 | Sound status port |
| $C00000 | Additional control register |
| $D00600-$D00606 | Video control registers |

## C-Chip Integration Points

The C-Chip is accessed at these key points:

1. **Initialization** ($3EF0): Reset and handshake
2. **Input reading** ($028D70): Read coins, buttons, DIP switches
3. **Game state** ($0249C2): Level, lives, score verification
4. **Protection** ($00C9F8): ROM verification during level load

For the SNES port, the C-Chip emulation needs to:
- Respond to init command with #$4B (OK)
- Return input data (mapped from SNES controllers)
- Track game state (level, lives, score)
- Pass protection checks
