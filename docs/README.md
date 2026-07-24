# Documentation index

This repository has four documentation paths. Start with the path that matches the
work you are doing; the dated recovery reports are supporting evidence, not required
onboarding.

## 1. Current Superman project

Use this path to build, test, play, or continue the present port.

1. [Current status](current/STATUS.md) — the only authoritative project-status summary.
2. [Release blockers](current/RELEASE_BLOCKERS.md) — known defects, missing gates, and
   decisions still needed.
3. [Build instructions](current/BUILDING.md) — dependencies, private inputs, build command,
   and migration notes.
4. [Controls and playtesting](current/CONTROLS.md).
5. [Validation matrix](current/VALIDATION.md) — commands and the scope of each result.
6. [Current architecture](current/ARCHITECTURE.md).

The [current-project index](current/README.md) links the deeper Superman-specific
renderer, C-Chip, object-processing, sound-command, and ROM-input documents.

## 2. Reusable arcade-to-SNES toolchain

Use this path when modifying the interpreter/transpiler or adapting the machinery to
another game.

- [Toolchain overview](toolchain/README.md)
- [MC68000 interpreter](toolchain/MC68000_INTERPRETER.md)
- [Transpiler workflow](toolchain/TRANSPILER_WORKFLOW.md)
- [Address-map adaptation](toolchain/ADDRESS_MAP_ADAPTATION.md)
- [Graphics conversion](toolchain/GRAPHICS_CONVERSION.md)
- [VGM and sound conversion](toolchain/SOUND_PIPELINE.md)
- [MAME/Nexen differential validation](toolchain/DIFFERENTIAL_VALIDATION.md)
- [Scheduler and timing model](toolchain/SCHEDULER_TIMING.md)
- [Debugging, Poppy, and harness gotchas](toolchain/DEBUGGING.md)
- [Per-tool reuse index](../tools/README.md)

## 3. Gigandes onboarding

Use this path to begin the next Taito X / MC68000 port.

- [What transfers and what changes](gigandes/README.md)
- [Concrete bring-up sequence and gates](gigandes/BRINGUP.md)

## 4. Historical evidence and forensics

Use this path when a current claim needs provenance, a failure resembles an old one,
or a rejected approach is being reconsidered.

- [Historical archive index](history/README.md)
- [Old-to-new document map](history/DOCUMENT_MAP.md)
- [Recovery evidence ledger](history/recovery/RECOVERY.md)
- [Confession/correction ledger](history/recovery/CONFESSION.md)
- [Performance campaigns](history/performance/)
- [Dated playtest handoffs](history/handoffs/)
- [Failed designs and risk studies](history/designs/)
- [Forensic reports](history/forensics/)

Everything under `docs/history/` retains its original dated scope. It does not override
[current status](current/STATUS.md), even if an old heading says “current,” “playable,”
or “next.”

## Documentation rules

- Update `docs/current/STATUS.md` when project truth changes.
- Add focused evidence without rewriting old evidence out of existence.
- Put transferable technique in `docs/toolchain/`; keep game constants in
  `docs/current/` or `docs/gigandes/`.
- Run `python3 tools/check_doc_links.py` after moving or renaming Markdown files.
- Do not link a local lab result to a project-level performance or playability claim
  unless it satisfies the validation contract.

The July 24 hierarchy, authority, archive, contradiction, and verification summary is
in the [documentation reorganization report](DOCUMENTATION_REORGANIZATION_REPORT.md).
