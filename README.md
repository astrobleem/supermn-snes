# Superman (Taito X System) → SNES / SA-1

A port of the 1988 Taito arcade game **Superman** (Motorola 68000 CPU, X1-001/X1-002
video, YM2610 + C-Chip) to the **Super Nintendo with the SA-1** coprocessor.

The strategy is a **interpret-cold / transpile-hot hybrid**: a hand-written 68000
interpreter (in 65816 assembly) boots and runs the original game logic on real SNES
hardware, while hot paths are migrated to native 65816 over time. Every component is
validated **differentially against ground truth** — MAME for the arcade side, a real
SNES PPU (via Mesen) for the target side.

> ⚠️ **No copyrighted ROM data is included.** This repository contains only original
> source, tooling, and documentation. You must supply your own legally-obtained
> Superman arcade ROM set to build or run anything. See [Building](#building).

## Where things stand

| Area | State |
|---|---|
| **68000 interpreter** | ✅ **Complete legal MC68000 instruction set** — 47/47 op groups, 154/154 differential tests green vs MAME, boots Superman on real SNES |
| Graphics pipeline | ✅ validated on real SNES PPU vs MAME (palette + both X1-001 draw paths) |
| Transpiler (design + spike) | ✅ design settled; 2 functions differentially verified (gate G2) |
| C-Chip boot handshake | ✅ solved via patch + input mailbox + 256-byte download replay (no MCU emulation) |
| Disassembly coverage (G1) | ⬆ trace-driven CDL pipeline; full playthrough trace |
| Audio (YM2610 → SNES TAD) | 🔬 analyzed; `vgm-to-tad-mml` skill exists |
| Bulk game-logic port | ⬜ not started |

See **[STATUS.md](STATUS.md)** for the authoritative, detailed state and
**[ROADMAP.md](ROADMAP.md)** for where we're heading next.

## The 68000 interpreter

`src/interp.pasm` is a hand-written 65816 interpreter that executes real 68000
opcodes on a real SNES (validated in Mesen against MAME as the arcade oracle).
It now implements the **complete legal MC68000 instruction set** — not just the
subset Superman happens to use — so it is reusable for future arcade→SNES ports.

- 68000 registers live in the 65816 direct page; work RAM (`$F0xxxx`) maps to SNES
  bank `$7F`; opcodes are fetched big-endian from the ROM image at `$C10000+PC`.
- New/generic ops route through a shared effective-address (EA) engine; the
  original ~142 game-path handlers are left untouched.
- Exceptions (TRAP, divide-by-zero → vec 5, CHK → vec 6, TRAPV → vec 7,
  ILLEGAL → vec 4) push correct stack frames and vector through the ROM table.

**Every operation was implemented and validated one at a time** against MAME via
the single-instruction differential harness `tools/optest.py`, with a full-boot
regression after each batch. See **[INTERPRETER_SPIKE.md](INTERPRETER_SPIKE.md)**.

## Key documents

- **[STATUS.md](STATUS.md)** — single source of "where we're at"
- **[ROADMAP.md](ROADMAP.md)** — next steps and milestones
- **[METHODOLOGY.md](METHODOLOGY.md)** — the reusable arcade→SNES recipe
- **[TRANSPILER_DESIGN.md](TRANSPILER_DESIGN.md)** — 68K→SA-1 lowering decisions
- **[INTERPRETER_SPIKE.md](INTERPRETER_SPIKE.md)** — interpreter design & validation
- **[PALETTE_VERDICT.md](PALETTE_VERDICT.md)** — graphics path validation
- **[CCHIP_BOOT_HANDSHAKE.md](CCHIP_BOOT_HANDSHAKE.md)** / **[CCHIP_FIRMWARE.md](CCHIP_FIRMWARE.md)** — C-Chip resolution
- **[tools/README.md](tools/README.md)** — tool reuse guide

## Building

> Requires a legally-obtained Superman arcade ROM set (not distributed here).

1. Place the ROM set where the tools expect it (extract the 68K image to
   `data/superman_m68k.bin`; see `tools/build_interp_rom.py`).
2. Toolchain: the [Poppy](https://example.invalid) 65816 assembler, Python 3, MAME
   0.287 (arcade oracle), and Mesen with its Python MCP (SNES PPU validation).
3. Build the interpreter ROM:
   ```sh
   bash tools/build_interp.sh      # assembles src/interp.pasm -> build/interp.sfc
   ```
4. Run the differential test suite (needs MAME + Mesen MCP running):
   ```sh
   python3 tools/optest.py         # 154 single-instruction tests vs MAME
   ```

## Repository layout

```
src/        65816 source (interp.pasm = the 68000 interpreter; main, spikes)
tools/      build scripts, the optest harness, trace/CDL pipeline, analysis
tools/sound/  YM2610 VGM -> SNES (TAD/MML) conversion
data/       extracted assets (gitignored — derived from the arcade ROM)
build/      build outputs (gitignored)
*.md        design notes, risk docs, verdicts, status
```

## License / legal

Original source and documentation in this repository are the author's own work.
The Superman arcade game and its ROM/graphics/audio data are property of their
respective rights holders and are **not** included or distributed here. This is a
preservation / reverse-engineering project for interoperability and education.
