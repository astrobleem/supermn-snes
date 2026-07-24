# Old-to-new documentation map

This map is the authoritative relocation record for the July 24, 2026 documentation
reorganization.

## Current Superman documents

| Former path | Current path |
|---|---|
| `README.md` | [`docs/history/status/README_PRE_REORG_20260724.md`](status/README_PRE_REORG_20260724.md) preserves the old contents; a short [`README.md`](../../README.md) now occupies the root |
| `AGENTS.md` | [`docs/history/status/AGENTS_GUIDE_PRE_REORG_20260724.md`](status/AGENTS_GUIDE_PRE_REORG_20260724.md) preserves the old contents; a concise authoritative [`AGENTS.md`](../../AGENTS.md) now occupies the root |
| `BUILD.md` | [`docs/current/BUILDING.md`](../current/BUILDING.md) |
| `CCHIP_BOOT_HANDSHAKE.md` | [`docs/current/CCHIP_BOOT_HANDSHAKE.md`](../current/CCHIP_BOOT_HANDSHAKE.md) |
| `CCHIP_FIRMWARE.md` | [`docs/current/CCHIP_FIRMWARE.md`](../current/CCHIP_FIRMWARE.md) |
| `VIDEO_PLUMBING.md` | [`docs/current/VIDEO_RENDERER.md`](../current/VIDEO_RENDERER.md) |
| `docs/PREPARE_ROMS.md` | [`docs/current/ROM_INPUTS.md`](../current/ROM_INPUTS.md) |
| `docs/SOUND_COMMAND_MAP.md` | [`docs/current/SOUND_COMMAND_MAP.md`](../current/SOUND_COMMAND_MAP.md) |

New current summaries are
[`docs/current/STATUS.md`](../current/STATUS.md),
[`RELEASE_BLOCKERS.md`](../current/RELEASE_BLOCKERS.md),
[`CONTROLS.md`](../current/CONTROLS.md),
[`VALIDATION.md`](../current/VALIDATION.md), and
[`ARCHITECTURE.md`](../current/ARCHITECTURE.md).

## Reusable toolchain documents

| Former path | Current path |
|---|---|
| `docs/INTERP_DEBUG_AND_GOTCHAS.md` | [`docs/toolchain/DEBUGGING.md`](../toolchain/DEBUGGING.md) |
| `PALETTE_VERDICT.md` | [`docs/toolchain/GRAPHICS_PALETTE_EVIDENCE.md`](../toolchain/GRAPHICS_PALETTE_EVIDENCE.md) |
| `SPRITE_SCALING_VERDICT.md` | [`docs/toolchain/SPRITE_SCALING_EVIDENCE.md`](../toolchain/SPRITE_SCALING_EVIDENCE.md) |
| `CONVERTSOUND.md` | [`docs/toolchain/SOUND_CONVERSION_REFERENCE.md`](../toolchain/SOUND_CONVERSION_REFERENCE.md) |
| `COVERAGE_G1.md` | [`docs/toolchain/TRACE_COVERAGE.md`](../toolchain/TRACE_COVERAGE.md) |

The concise interpreter, transpiler, address-map, graphics, sound, differential, and
scheduler guides under [`docs/toolchain/`](../toolchain/) are new synthesis documents.
They link back to the evidence rather than replacing it.

## Historical plans and campaign records

| Former path | Archived path |
|---|---|
| `CONFESSION.md` | [`docs/history/recovery/CONFESSION.md`](recovery/CONFESSION.md) |
| `RECOVERY.md` | [`docs/history/recovery/RECOVERY.md`](recovery/RECOVERY.md) |
| `STATUS.md` | [`docs/history/status/STATUS_THROUGH_20260724.md`](status/STATUS_THROUGH_20260724.md) |
| `TECHNICAL_REFERENCE.md` | [`docs/history/status/TECHNICAL_REFERENCE_EARLY.md`](status/TECHNICAL_REFERENCE_EARLY.md) |
| `MAIN_PLANNING_HANDOFF.md` | [`docs/history/campaigns/MAIN_PLANNING_HANDOFF.md`](campaigns/MAIN_PLANNING_HANDOFF.md) |
| `docs/PROFILE_CAMPAIGN.md` | [`docs/history/performance/PROFILE_CAMPAIGN.md`](performance/PROFILE_CAMPAIGN.md) |
| `docs/R5_PERFORMANCE_ARCHITECTURE.md` | [`docs/history/performance/R5_SCHEDULER_EXPERIMENTS.md`](performance/R5_SCHEDULER_EXPERIMENTS.md) |
| `METHODOLOGY.md` | [`docs/history/plans/PORTING_PLAYBOOK_20260625.md`](plans/PORTING_PLAYBOOK_20260625.md) |
| `PORT_PLAN.md` | [`docs/history/plans/PORT_PLAN.md`](plans/PORT_PLAN.md) |
| `PROJECT_PLAN.md` | [`docs/history/plans/PROJECT_PLAN.md`](plans/PROJECT_PLAN.md) |
| `ROADMAP.md` | [`docs/history/plans/ROADMAP.md`](plans/ROADMAP.md) |
| `TRANSPILER_TOOL_SCOPE.md` | [`docs/history/plans/TRANSPILER_TOOL_SCOPE.md`](plans/TRANSPILER_TOOL_SCOPE.md) |

## Historical designs, experiments, risks, and forensics

| Former path | Archived path |
|---|---|
| `CALL_BRIDGE_DESIGN.md` | [`docs/history/designs/CALL_BRIDGE_DESIGN.md`](designs/CALL_BRIDGE_DESIGN.md) |
| `RUN_COLLAPSE_DESIGN.md` | [`docs/history/designs/RUN_COLLAPSE_DESIGN.md`](designs/RUN_COLLAPSE_DESIGN.md) |
| `TRANSPILER_DESIGN.md` | [`docs/history/designs/TRANSPILER_DESIGN.md`](designs/TRANSPILER_DESIGN.md) |
| `docs/OBJPROC_SPEC.md` | [`docs/history/designs/OBJECT_PROCESSOR_CAMPAIGN_20260703.md`](designs/OBJECT_PROCESSOR_CAMPAIGN_20260703.md) |
| `INTERPRETER_SPIKE.md` | [`docs/history/experiments/INTERPRETER_BRINGUP.md`](experiments/INTERPRETER_BRINGUP.md) |
| `SPIKE_RESULT.md` | [`docs/history/experiments/TRANSPILER_SPIKE.md`](experiments/TRANSPILER_SPIKE.md) |
| `RISK_CCHIP.md` | [`docs/history/risks/CCHIP.md`](risks/CCHIP.md) |
| `RISK_SPRITES.md` | [`docs/history/risks/SPRITES.md`](risks/SPRITES.md) |
| `RISK_TRANSPILER.md` | [`docs/history/risks/TRANSPILER.md`](risks/TRANSPILER.md) |
| `ADVICE.md` | [`docs/history/forensics/ADVICE_20260616.md`](forensics/ADVICE_20260616.md) |
| `BLOCKERS.md` | [`docs/history/forensics/BUILD_BLOCKERS_20260616.md`](forensics/BUILD_BLOCKERS_20260616.md) |
| `GAME_LOGIC_ANALYSIS.md` | [`docs/history/forensics/GAME_LOGIC_ANALYSIS.md`](forensics/GAME_LOGIC_ANALYSIS.md) |
| `SOUNDHARDWARE.md` | [`docs/history/forensics/SOUND_HARDWARE_SURVEY.md`](forensics/SOUND_HARDWARE_SURVEY.md) |
| `INTEGRATION.md` | [`docs/history/audio/SOUND_PACKAGE_INTEGRATION.md`](audio/SOUND_PACKAGE_INTEGRATION.md) |
| `supersoundhandoff.md` | [`docs/history/audio/SOUND_BOOTSTRAP_HANDOFF.md`](audio/SOUND_BOOTSTRAP_HANDOFF.md) |

## Focused handoffs

Every former `docs/handoff/` file moved to `docs/history/handoffs/`:

| Former filename | Archived document |
|---|---|
| `CHARGED_SHOT_FREEZE_20260723.md` | [charged-shot freeze](handoffs/CHARGED_SHOT_FREEZE_20260723.md) |
| `FIRST_WALL_OCTAVE_AUDIO_AND_BOOT_20260723.md` | [wall/audio/boot](handoffs/FIRST_WALL_OCTAVE_AUDIO_AND_BOOT_20260723.md) |
| `MESEN211_PLAYTEST_REGRESSIONS_20260723.md` | [Mesen regressions](handoffs/MESEN211_PLAYTEST_REGRESSIONS_20260723.md) |
| `ROM_PREPARATION_TOOL_20260724.md` | [ROM preparation](handoffs/ROM_PREPARATION_TOOL_20260724.md) |
| `V130_SECOND_PLAYTEST_20260723.md` | [v130 playtest](handoffs/V130_SECOND_PLAYTEST_20260723.md) |
| `V132_TITLE_CRATE_RIGHT_EDGE_20260723.md` | [v132 title/crate/right edge](handoffs/V132_TITLE_CRATE_RIGHT_EDGE_20260723.md) |
| `V133_TITLE_ATTRACT_BOOT_20260723.md` | [v133 title/attract/boot](handoffs/V133_TITLE_ATTRACT_BOOT_20260723.md) |
| `V134_STAGE2_VERTICAL_SCROLL_20260724.md` | [v134 Stage 2](handoffs/V134_STAGE2_VERTICAL_SCROLL_20260724.md) |
| `V135_IRAM_FREEZE_HUD_AUDIO_20260724.md` | [v135 freeze/HUD/audio](handoffs/V135_IRAM_FREEZE_HUD_AUDIO_20260724.md) |
| `scheduler_inplace_diff_session.md` | [scheduler in-place differential](handoffs/scheduler_inplace_diff_session.md) |
| `scheduler_switchout_wip.md` | [scheduler switch-out WIP](handoffs/scheduler_switchout_wip.md) |
