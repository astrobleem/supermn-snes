# Historical evidence and forensics

This archive preserves the failures, measurements, design arguments, and debugging
lessons that produced the current port. It is intentionally not the onboarding path.

For current truth, use [the authoritative status](../current/STATUS.md). A dated
document's words such as “current,” “green,” “playable,” “next,” or “blocked” apply to
the evidence available when it was written. They do not override the current status
unless that status explicitly adopts the result.

## Recovery and correction ledgers

- [CONFESSION.md](recovery/CONFESSION.md) — July 12 correction of optimistic
  performance and completeness claims.
- [RECOVERY.md](recovery/RECOVERY.md) — R0-R15 canonicalization, reproduction, and
  response-candidate evidence.

These remain the provenance spine for current claims, but
[`docs/current/STATUS.md`](../current/STATUS.md) is now the sole status authority.

## Dated implementation handoffs

[handoffs/](handoffs/) records each playtest report, diagnosis, exact ROM candidate,
bounded validation, and remaining uncertainty from charged-shot through v135 work.
Use these when a new failure resembles a prior human report.

## Performance and scheduling

- [PROFILE_CAMPAIGN.md](performance/PROFILE_CAMPAIGN.md) preserves native/render
  performance iterations and the formal v124 result.
- [R5_SCHEDULER_EXPERIMENTS.md](performance/R5_SCHEDULER_EXPERIMENTS.md) preserves the
  two rejected pacing architectures and their ordering failures.

Old projected fps and isolated-cycle goals are evidence of their experiments, not
current production rate claims.

## Designs, experiments, and risks

- [designs/](designs/) — call bridge, run collapse, and transpiler decisions.
- [experiments/](experiments/) — early interpreter and transpiler spikes.
- [risks/](risks/) — C-Chip, sprite, and transpiler hazard studies.
- [plans/](plans/) — original roadmaps, project plans, and reusable playbook.

These documents explain why an approach was selected or rejected. Current
implementation contracts live under [the reusable toolchain path](../toolchain/).

## Forensics and audio history

- [forensics/](forensics/) — early blocker snapshots, game-logic analysis, sound
  hardware survey, and recovered advice.
- [audio/](audio/) — sound package integration and bootstrap handoff.
- [campaigns/](campaigns/) — broad planning handoff from the pre-recovery campaign.
- [status/](status/) — superseded status summaries plus the complete pre-reorganization
  root README and agent guide.

## Finding a former path

Use [DOCUMENT_MAP.md](DOCUMENT_MAP.md) for every moved top-level document and focused
handoff. Git history is retained through file moves where practical; no historical
report was discarded to create the new hierarchy.

Some campaign reports originally used `[[name]]` references to Claude memory entries
that were never repository files. Their labels are preserved inline as
`legacy memory: name` rather than pretending they are resolvable document links.
