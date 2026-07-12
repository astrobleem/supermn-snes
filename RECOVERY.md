# Project recovery — canonicalization and evidence baseline

Started July 12, 2026. This is the active project-control document. It converts the repository
from overlapping optimistic handoffs into one evidence-backed engineering line.

## Canonical repository state

- Canonical upstream base: `origin/main` at PR #15 merge `73f1839`.
- Active recovery branch: `recovery/canonicalize-20260712`.
- Recovered truth documents: root `CONFESSION.md` and `AGENTS.md`.
- Old local tips and the unique stash are preserved as local `archive/*-pre-recovery-20260712`
  refs. Nothing has been deleted.
- The old `sound-p3` worktree remains locked and untouched until all unique content is proven
  preserved. Its tracked tip is already an ancestor of `origin/main`; its only unique untracked
  file was `CONFESSION.md`, now copied byte-for-byte to the root.

## Evidence grades

### Strong evidence

- MC68000 instruction semantics: MAME differential gates, including the recorded 782/782 sweep.
- Per-function native escapes that individually passed firing plus lockstep/full-diff gates.
- C-Chip observed boot response and input-mailbox contract.
- TAD blob construction, ARAM fit, and byte-level transport/oracle checks.
- Specific Poppy `.org` overlap and stale-cross-bank-address bugs already reproduced and fixed.

### Partial evidence, not a project-level verdict

- Injected GAME_TICK cycle spans: valid for local comparisons, incomplete for end-to-end fps.
- Isolated palette/sprite/background render tests: validate conversion paths, not a settled cold boot.
- Sound trigger injection and byte matches: validate transport/data, not musical fidelity.
- `$0818` `$AC=$2000` soak samples: useful mitigation evidence, not a proof of crash freedom.

### Unproven or contradicted

- Playability or a credible 30/60 fps landing point.
- Correct level-background rendering in current production cold boot.
- Complete/faithful sound by ear.
- Organic firing of every mapped music/SFX trigger.

## Canonical tools

- Arcade oracle: MAME 0.287 at `/snap/bin/mame`.
- SNES/SA-1/PPU oracle: MCP-enabled Nexen at
  `/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen`.
- Shared Python transport/client: `/home/chad/Mesen2/python`.
- Agent stdio shim: `tools/nexen_mcp_bridge.py`.
- Global MCP registrations: `mame` and `nexen-inproc`.

The older `/home/chad/Mesen2` emulator remains available for compatibility with historical scripts,
but new baseline evidence uses Nexen unless a documented emulator comparison is the purpose.

## Recovery gates

### R0 — Source and artifact provenance

- [x] Base recovery work on `origin/main`.
- [x] Preserve prior refs and unique stash.
- [x] Recover `CONFESSION.md` and add `AGENTS.md`.
- [x] Identify Nexen as the current project oracle and validate its MCP handshake/SA-1 cycle state.
- [ ] Back up stale generated artifacts before regeneration.
- [ ] Rebuild the merged 21-song TAD blob and ROM from the canonical source.
- [ ] Record hashes, sizes, tool versions, source commit, and build log.

### R1 — Static and interpreter correctness

- [ ] Run bank/layout assertions during the canonical build.
- [ ] Run opsweep and optest against MAME 0.287.
- [ ] Run the production gameplay smoke on the freshly built ROM.

### R2 — Honest cold-boot performance

- [ ] Start from power-on with production `TESTFLAG=0`; do not load a save state or force gates.
- [ ] Log when `$072E/$071A/$073A` arm and record the sound-ring signature that caused it.
- [ ] Drive coin and Start through the real input mailbox.
- [ ] Measure emulator video frames, wall time, SA-1 cycles, `$0760` game-tick count, instruction
  counter, task mask, halt state, and final PC in the same continuous run.
- [ ] Cross-check that `$0760` is monotonic and corresponds to the `$0818` game-frame boundary.
- [ ] Publish raw logs and separate emulated-game rate from host throughput.

### R3 — Gameplay rendering truth

- [ ] Reach a settled gameplay state from the same cold boot.
- [ ] Capture `$41:4800` tile codes, `$41:4C00` colors, CGRAM, VRAM, OAM, PPU layer enables,
  and screenshot together.
- [ ] Compare with a same-state MAME reference or state why exact state alignment is unavailable.
- [ ] Decide whether the missing background is state progression, shadow generation, transfer,
  PPU configuration, or renderer logic.

### R4 — Sound truth

- [ ] Record audio from organic attract and gameplay triggers.
- [ ] Verify which commands fired without injection.
- [ ] Listen to all 21 tracks against arcade references and log musical defects.
- [ ] Reclassify sound as data-correct, transport-correct, or musically accepted per track.

## Decision rule after the baseline

Performance is the project gate. If a faithful, accelerators-armed cold boot is still orders of
magnitude below a usable game rate, do not spend the next campaign polishing sound or adding more
isolated escapes. Profile the true end-to-end run and choose explicitly among:

1. a larger semantic/HLE rewrite with a measured path to the target rate;
2. a reduced-scope technical demo with honest acceptance criteria; or
3. stopping the port while preserving the reusable interpreter/toolchain work.

No option will be framed as success until its observable user experience meets its stated target.
