# Charged-shot release freeze — July 23, 2026

## Verdict

The reported freeze was reproduced on exact v124 and was a port defect, not a controller or
charging mistake. Holding arcade Button 1 (SNES B/Y) and releasing a charged shot reached a
silently overwritten native `$00D3B0` state handler. The repaired v127 candidate does not stall in
the retained 96-, 120-, or 180-video-frame hold cases.

Candidate ROM SHA-256:
`1a8a5742536b6142a42387546524bb0e785fac508a01e6ff5e5c53027b06db35`.

This is focused checkpoint and layout evidence. It is not a new cold-boot performance result, does
not supersede v124's 29.700167 game-fps measurement, and does not restore the word playable.

## Reproduction

`tools/validate_charged_shot.py` loads the organically armed production gameplay checkpoint, uses
Nexen port 0 and the ROM's real `$4016` input path, holds B, releases it, and records tick/render
progress plus both CPU states.

On v124 SHA-256 `777507c9ecba8b7911dae882ea266cca7d173d918dde65b73f880acdb0451352`,
the 96-frame hold:

- reached the charged-shot animation and projectile path;
- advanced only 50 game ticks and 50 renders after release;
- accumulated a sustained stall by relative frame 130; and
- ended with the SA-1 PC at zero while halt remained `$0000`.

The retained trace alternates a physical `BRK` at address zero with `RTI` from the SA-1 exception
path. Evidence:
`build/user-playtest-v105-investigation/charged-shot-v124-96hold-trace-v1/`.

An organic MAME 0.287 hold/release remained live, so the freeze was SNES-port behavior rather than
the arcade game's charged-shot contract.

## Root cause

`entry_d3b0` was symbolized at `$92:EFFB`, but its generated body extended through `$92:F18E`.
`jah2_ext` was later pinned with `.org $F000`. Poppy permits overlap and gives the later section
the final bytes, so `$92:F000-$92:F0C8` replaced 201 bytes in the middle of `$D3B0`. The historical
campaign ledger had already warned that this bank seam was unsafe, but no pack assertion closed
it.

The charged-shot release path selects case `$000C` in `$00D226`, jumps to the corrupted `$D3B0`
body, and eventually consumes invalid native instructions and physical-stack state. That is why
ordinary short attacks worked after the v124 combat-return repair while the charged release still
froze.

## Repair

- `$92:EFFB` remains the established translation-table target but is now a four-byte
  `JML $94:B400` trampoline.
- The complete original `$D3B0` body lives in the audited bank-$94 gap at `$B400`.
- Its indirect-call continuation is fixed at `$94:B580` and uses the bank-$94 `$00FD` return
  sentinel before crossing to the existing bridge at `$92:F828`.
- `$92:F18F` explicitly pins the following `$D226` handler.
- The ROM packer now verifies the trampoline, `$F000` island, `$D226` prologue, relocated body,
  cross-bank bridge, continuation, and every surrounding zero seam.
- `python3 tools/audit_banks.py` is green across all escape banks after the relocation.

## Focused results

| B hold | Frames observed after release | Game ticks after release | Renders after release | `$D3B0` / continuation hits | Result |
|---:|---:|---:|---:|---:|---|
| 96 | 600 | 300 | 300 | 2 / 2 | green |
| 120 | 600 | 300 | 300 | 2 / 2 | green |
| 180 | 1,200 | 600 | 600 | 2 / 2 | green |

The 180-frame case ended at tick 1,718 with halt zero, production gates intact, 138 bytes of
minimum saved-stack margin, and player health reduced from 20 to 16 by live enemy offense.
Independent regressions on the same ROM also show visible normal punch/jump output and an
800-video-frame idle-combat window with an activated enemy attack and health 20 to 18.

A fresh `TESTFLAG=0` power-on smoke organically armed the production gates at frame 5,242, drove
coin and Start through the real controller mailbox, detected gameplay, and ended at frame 5,711 /
tick 291 with halt zero. Tick/render progress, the sound ring, supervisor ROM/WRAM mirror, renderer
queue state, and all initialized stack floors were healthy. This shortened, sampled smoke proves
the candidate still cold-boots into gameplay; it is not an uninterrupted FPS measurement.

Focused evidence:

- `build/user-playtest-v105-investigation/charged-shot-v127-relocated-96hold-v1/`
- `build/user-playtest-v105-investigation/charged-shot-v127-relocated-120hold-v1/`
- `build/user-playtest-v105-investigation/charged-shot-v127-relocated-180hold-v1/`
- `build/user-playtest-v105-investigation/visible-actions-v127-charged-shot-fix-v2/`
- `build/user-playtest-v105-investigation/idle-combat-v127-charged-shot-fix-v1/`
- `build/user-playtest-v105-investigation/production-v127-charged-shot-coldboot-smoke-v1/`

## Remaining acceptance gates

The candidate still needs a formal uninterrupted production rate/budget run and a human playtest
of the exact ROM. Audio fidelity and the missed 30 Hz/cycle thresholds remain open independently
of this freeze repair.
