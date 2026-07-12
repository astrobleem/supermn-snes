# R5 continuous profile and idle-vblank architecture

Date: July 12, 2026. This is the focused evidence record for recovery gate R5. It does not change
the production ROM and does not supersede the canonical cold-boot rate in `RECOVERY.md` R2.

## Verdict

The apparent 4-6x disagreement between the canonical 8.10M-cycle tick and the old injected
1.3-2.0M-cycle windows is resolved. The old windows ended before the next `$0818` wait completed.
In an uninterrupted production attract interval, the shipped `$AC=$2000` clamp spends about
6.47M of 7.26M cycles waiting for the virtual IRQ. A mailbox-driven, 60-tick-settled gameplay
checkpoint independently measures 6.46M wait cycles in a 7.36M tick, or 87.73%. The missing factor
is present in representative gameplay, not just attract mode.

Two isolated lab ROMs then tested real-vblank waiting. A 5A22-supervisor wake reduced a short light
attract interval to 2.17M cycles. A more aggressive WRAM-resident NMI wake reduced it to 0.927M
cycles, an 87.23% short-window reduction. Both failed the behavioral gate after entering gameplay:
the poll wake halted `$DEAD` at tick 765 and the NMI wake halted `$DEAD` at tick 767; both had PC
`$080100`, corrupt task mask `$FFC1`, and a still-positive 150-byte minimum sampled stack margin.
Waiting until the SA-1 reaches the main `$0818` context is insufficient, and waiting for the 5A22
supervisor/renderer to return is insufficient. The `$2000` delay is part of the game coroutine's
effective timing contract, not disposable spin.

The 0.927M number is therefore a failed architecture's diagnostic result, not a speed result that
can be promoted. Even before the failure, its active work alone averaged 818K cycles and the full
tick was respectively 2.29x and 2.59x the 358K-cycle 30 Hz budget. The conservative supervisor wake
is also about 6.05x over that budget and behaviorally red. R5 explains the missing cost and retires
two unsafe shortcuts, but it does not produce a measured path to 30 Hz.

| Like-for-like light attract variant | Mean cycles/tick | Steady video frames/tick | Behavioral gate |
|---|---:|---:|---|
| Production `$2000` clamp | 7,256,419 | 40-41 | canonical |
| 5A22 supervisor-poll wake | 2,166,590 | 13 | `$080100` / `$DEAD`, tick 765 |
| WRAM NMI wake | 926,918 | 5 | `$080100` / `$DEAD`, tick 767 |

## Measurement repair

`tools/profile_continuous.py` installs all phase hooks simultaneously and never pauses at a phase
boundary. Recovery Nexen commit `6365acc39` adds the source CPU's exact 64-bit `cycleCount` to each
hook notification. Host delivery latency therefore cannot change the deltas. The measured points
are:

- `$00:F5A3`: exact retained `INC $0760` clamp/tick boundary;
- `$00:B404`: interpreter virtual-IRQ path;
- `$92:DC3B`: native `$3A92` game-tick entry;
- `$00:F597`: lab-only entry into the `$0818` decision body.

The harness cold-boots to the real production gates, saves a checkpoint before installing hooks,
then profiles that same-ROM checkpoint with one continuous run. All intervals contain exactly one
IRQ and one `$3A92` entry. The production run also preserved all six gate values, sound-ring pointer
`$00F01C20`, and halt word zero. A legacy-Mesen-to-Nexen checkpoint attempt zeroed the SA-1 IRAM gate
block and was rejected; it is retained only as negative cross-emulator evidence.

Raw production evidence:
`build/recovery-20260712/r5-continuous-profile-verified/profile.jsonl`, SHA-256
`ea5db36f25d9ed9a03e164f7802fd0c92eb4015320419abf03ea9dfd9abe8f85`.

`--drive-gameplay` then used the ordinary mailbox to enter gameplay at tick 195, settled to tick
258/task mask `$3B60`, saved a pre-hook checkpoint, and produced a byte-repeated final profile from
that state. Raw verified gameplay evidence is
`build/recovery-20260712/r5-continuous-profile-gameplay-verified/profile.jsonl`, SHA-256
`83125a216f6cfb3d5ab9dd7fd1078e183eecefc09466fd6cdd7b97380f7b285f`; its checkpoint hashes to
`0076df64b7902eb05ca6a29c1e38742a0cb4e3fb76722153e779cf3cbec08247`.

| Continuous phase, 16 intervals | Attract mean | Settled gameplay mean | Gameplay share |
|---|---:|---:|---:|
| `$00:F5A3` clamp -> virtual IRQ | 6,467,122 | 6,456,498 | 87.73% |
| virtual IRQ -> native `$3A92` entry | 7,156 | 7,163 | 0.10% |
| `$3A92` entry -> next clamp | 782,140 | 896,057 | 12.18% |
| **Clamp -> clamp total** | **7,256,419** | **7,359,718** | **100%** |

The gameplay intervals are exceptionally stable: 7,359,190-7,360,482 cycles and 41-42 SNES video
frames per tick, about 1.457 game ticks/s. The canonical cold-boot post-arm average remains 8,099,238
cycles/tick and 1.3237 fps because it includes initial post-arm and state-transition cost. It is
still the end-to-end user-facing baseline; the settled profile is the correct phase attribution.
Both independently show why the older partial injected windows were misleading.

## Isolated prototypes

`tools/build_idle_vsync_lab.py --nmi-wake` generates the experiment under
`build/r5-idle-vsync-nmi-lab/` without editing canonical assembly, objects, or `build/interp.sfc`.
The lab ROM is marked `R5VNMI01`; IRAM `$0734` is an explicit runtime experiment gate. Its SHA-256
is `982131563e4d6fafc07d726adc0205d7293f6bdc6e188e190602910e54354e33`. The supervisor-poll ROM is
marked `R5VSYNC1` and hashes to
`671c710da3daf24a1362f9a46de1bac7adf0ad6b56c07d9da96e113681261538`.

The change has three parts:

1. A size-neutral bank-$00 patch replaces only the `$7597-$75A2` clamp decision and retains the
   exact `INC $0760` bytes `EE 60 07` at `$75A3`.
2. With `$0734=1`, a bank-$99 handler clears stale inter-CPU IRQ state, masks SA-1 IRQ vectoring,
   enables the 5A22 IRQ source, executes `WAI`, disables/clears the source after wake, and sets
   `$AC=1` so the interpreter delivers its ordinary virtual IRQ at the next boundary.
3. A native 5A22 NMI trampoline enters a full-state-preserving handler copied to WRAM `$7F:8F00`.
   It requests the SA-1 wake and leaves the Bus-A latch on IRAM before returning entirely through
   WRAM. This keeps the NMI independent of renderer duration and avoids persistent ROM contention.

The intended safety contract was: active task work completes before `WAI`; the SA-1 is in the main
idle context when vblank arrives; the hardware IRQ only wakes and cannot vector while masked; and
the existing virtual-IRQ path runs after wake. The long gate falsified the conclusion drawn from
that contract. It prevents stack interruption, but it does not preserve timing between
cooperatively scheduled producer and consumer work. The supervisor-poll failure proves the issue is
broader than an NMI interrupting renderer work.

Raw final short-profile evidence:
`build/recovery-20260712/r5-idle-vsync-nmi-wram-cold/profile.jsonl`, SHA-256
`571dbc9fe8274b78b75fa924382cd5fe625ae9bcb0cd8e1f81a7d628ebf56d0c`.

| Lab phase, 16 intervals | Mean SA-1 cycles |
|---|---:|
| previous clamp -> virtual IRQ | 1,120 |
| virtual IRQ -> native `$3A92` entry | 7,193 |
| `$3A92` entry -> main idle entry | 818,248 |
| main idle entry -> next clamp, including real vblank wait | 100,358 |
| **Clamp -> clamp total** | **926,918** |

In this short profile, the NMI lab eliminates 98.45% of the wait and reduces the like-for-like
interval 87.23%. Active work is 4.62% higher than the production trace, so it was not silently
skipped. Every interval contains exactly one IRQ, one `$3A92` entry, and one idle entry; steady
video-frame deltas are five. Those local accounting facts remain valid, but the later derail makes
the architecture unusable.

## Negative iterations retained

- The first 5A22 supervisor-poll wake reduced the tick to 2.17M cycles but woke only after the long
  renderer returned. That serialization is expensive and did not restore correctness: its separate
  soak reached the same `$080100` failure at tick 765. Its short profile is
  `build/recovery-20260712/r5-idle-vsync-prototype/profile.jsonl`, SHA-256
  `54da654ce0f226826e4d831bd97815fc7b507e7dbccc4c94009ca6f26f43abe8`.
- A ROM-hosted 5A22 NMI handler left the hardware-shaped Bus-A latch on program ROM and created
  full-time contention, making the result about 3.3x slower.
- An early handler failed to force DBR zero before touching hardware/IRAM.
- Reusing a checkpoint made before the final WRAM-copy layout left stale handler bytes and hung in
  `WAI`. A fresh same-ROM cold boot removed the false failure.

Those runs remain under the other `r5-idle-vsync-*` evidence directories and must not be averaged
with the final cold-boot prototype.

## Behavioral gate

`tools/soak_idle_vsync_lab.py` drives the documented virtual-controller mailbox from the same-ROM
pre-hook checkpoint and samples the real scheduler state without debugger hooks. It requires:

- production gates and the explicit lab gate to remain exact;
- sound-ring pointer `$00F01C20` and interpreter halt word zero;
- continued `$00:F5A3` tick progress;
- gameplay task-mask entry after real coin/start pulses; and
- every initialized task's saved SP to remain at or above its true floor at 68K ROM `$0882`.

A 600-tick NMI dress rehearsal entered gameplay at tick 195, initialized seven task contexts, and
kept a minimum sampled stack margin of 154 bytes. The decisive run disproved that short green: it
entered gameplay, remained apparently healthy at tick 693, and halted `$DEAD` by tick 767 with 68K
PC `$080100` and corrupt task mask `$FFC1`. Twelve contexts were initialized and the minimum sampled
stack margin was still 150 bytes. Raw evidence is
`build/recovery-20260712/r5-idle-vsync-nmi-soak/soak.jsonl`, SHA-256
`536764a9696b9631e7bd987eafef86dad4c0188979c3786b4d43de9e6658a626`; the final-state SHA-256 is
`e637f85f5860b8565ba1bb6dc784db098e2f1ac2d63f53da3c74b9207ca7a32a`.

The supervisor-poll run independently entered gameplay and failed at tick 765 with the same halt,
PC, corrupt task mask, twelve initialized contexts, and 150-byte minimum sampled margin. Raw
evidence is `build/recovery-20260712/r5-idle-vsync-poll-soak-1200/soak.jsonl`; its final-state
SHA-256 is `cd087a106e00eb939ba143ca15a234a3e9788cd60e9645acafe710768ac97019`, and the JSONL hashes to
`986a40921361007116e70fbad85e6f22e032e5de0f1e6b173e6ff754c20ac288`.

The near-identical game-tick failure point across five-frame NMI cadence and roughly thirteen-frame
supervisor cadence is evidence that the dense virtual-IRQ cadence itself exposes the ordering bug.
It does not isolate the exact producer, so do not narrow the root cause further without a direct
trace. It does rule out stack-floor exhaustion and the simple “wait for renderer completion” fix.

## Campaign decision

R5 chooses the honestly scoped technical-demo path unless a future architecture first clears two
hard gates: it must preserve producer completion through the failing gameplay event, and a
representative whole gameplay tick must measure at or below 358K cycles with renderer/pacing cost
included. The current production clamp is slow but remains canonical; both fast-wake shortcuts are
retired. Even a hypothetical safe zero-cost wait would leave the measured 896K active gameplay
path at 2.50x the entire 30 Hz budget.

A semantic/full-AOT effort may still be valuable for the reusable interpreter/toolchain, but there
is no measured composable path from either lab to 30 Hz today. No more per-function sprint or
partial-window projection should be described as progress toward a playable port until a
whole-system prototype clears those gates.
