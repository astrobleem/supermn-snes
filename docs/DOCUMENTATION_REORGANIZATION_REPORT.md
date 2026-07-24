# Documentation reorganization report

Date: July 24, 2026.

## Outcome

The repository now has four explicit reading paths:

1. [`current/`](current/README.md) — build, playtest, validate, and continue Superman;
2. [`toolchain/`](toolchain/README.md) — reusable MC68000/SA-1 porting machinery;
3. [`gigandes/`](gigandes/README.md) — second-game inventory and concrete bring-up;
4. [`history/`](history/README.md) — evidence, failed experiments, plans, and forensics.

The root [`README.md`](../README.md) is the short project/build entry point.

## Authorities

| Subject | Authority |
|---|---|
| Present Superman verdict, candidate, performance, and subsystem truth | [`current/STATUS.md`](current/STATUS.md) |
| Required release work and unresolved policy choices | [`current/RELEASE_BLOCKERS.md`](current/RELEASE_BLOCKERS.md) |
| Build and private-input procedure | [`current/BUILDING.md`](current/BUILDING.md) and [`current/ROM_INPUTS.md`](current/ROM_INPUTS.md) |
| Validation commands and claim scope | [`current/VALIDATION.md`](current/VALIDATION.md) |
| Reusable integration contracts | [`toolchain/README.md`](toolchain/README.md) and its focused guides |
| Gigandes initial plan | [`gigandes/BRINGUP.md`](gigandes/BRINGUP.md) |
| Provenance for a dated claim | The focused report under [`history/`](history/README.md) |

Historical evidence can support or falsify a current statement, but a historical
document's old “current,” “playable,” or “next” wording is not authoritative.

## Old-to-new mapping and archive

The exhaustive per-file table is
[`history/DOCUMENT_MAP.md`](history/DOCUMENT_MAP.md). Documents were moved with Git
history intact where practical. The previous root README and agent guide were archived
whole before concise replacements were added.

Archive groups:

- `history/recovery/` — Confession and R0-R15 recovery ledgers;
- `history/handoffs/` — each user playtest response and ROM-candidate handoff;
- `history/performance/` — injected, checkpointed, scheduler, and formal production
  measurements;
- `history/designs/` and `history/experiments/` — transpiler, bridge, object-processor,
  interpreter, and rejected design work;
- `history/forensics/` and `history/risks/` — failure analysis and hazard studies;
- `history/audio/` — original sound integration;
- `history/plans/` and `history/campaigns/` — superseded roadmaps and work queues;
- `history/status/` — superseded status layers plus the pre-reorganization root docs.

## Contradictions reconciled

- The port is not called playable. v105's formal cadence result remains historical;
  human combat/audio testing falsified its playable label.
- v135 is the current response candidate, while v124 remains the latest end-to-end
  performance measurement satisfying the evidence protocol.
- 29.700167 game-fps and 360,990.164 cycles/tick are retained with both 30 Hz/358K
  gates explicitly red.
- Old 60 Hz, 150K, 178K, projected-fps, and isolated-span targets are labeled
  historical.
- The original ≥85% disassembly-coverage proposal is no longer presented as a hybrid
  prerequisite; trace/CDL remains a discovery and validation tool.
- Audio byte identity, ARAM fit, and digital continuity are separated from human
  musical acceptance. The octave-anchor pass remains mechanically real and audibly
  rejected.
- Checkpoint, injected, mirror-refreshed, emulator-specific, and fresh-power evidence
  are now labeled separately.

## Decisions still requiring Chad

1. Accept the Stage 2 center-column vertical-scroll approximation or require exact
   per-column presentation.
2. Keep boot-time `Tad_LoadSong(1)` or match the arcade's delayed organic attract
   command.
3. Require real SA-1/FXPak hardware validation for the first release or explicitly
   scope it to emulators.

Release rights scope, including treatment of recognizable music cues, also needs a
decision before public distribution. Gigandes' MAME cave-demo rendering warning is an
oracle risk to investigate during bring-up, not a settled implementation choice.

## Verification performed

```sh
python3 -m py_compile tools/check_doc_links.py tools/prepare_roms.py tests/test_prepare_roms.py
python3 -m unittest discover -v
python3 tools/check_doc_links.py
python3 tools/prepare_roms.py /path/to/legal-superman-set --validate-only
git diff --check
/snap/bin/mame -listxml gigandes
/snap/bin/mame -listxml gigandesa
sha256sum build/interp.sfc build/playtest/superman-snes-v135-5aac64b6.sfc
```

Results:

- 17/17 synthetic ROM-preparation tests passed;
- 357 relative links across 100 Markdown files resolved;
- the authenticated World set passed 12/12 input checks and all 15 generated private
  outputs matched their documented sizes and SHA-256 values in validation-only mode;
- both private v135 ROM copies were 4,194,304 bytes and matched
  `5aac64b67cfc04caf88b44198b762ddbf283ac38dfc831956290db7a99dd025a`;
- the v124 raw production JSON, v135 terminal JSON, v135 HUD JSON/screenshot, and
  retained opcode-log hashes were checked against the current summary; and
- no build was run for this documentation/path-reference-only change, so no
  private/generated ROM input was rewritten.

No copyrighted or derived binary data was added.
