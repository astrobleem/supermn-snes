# Scheduler and timing model

The arcade program contains a cooperative task scheduler whose IRQ cadence is part of
game behavior. The SNES port also has an asynchronous producer/consumer boundary:
SA-1 game logic publishes render work while the 5A22 owns VBlank, PPU DMA, input, and
audio supervision.

## Current production model

- SNES video runs at approximately 60 frames per second.
- Superman game logic targets 30 complete game ticks per second.
- The `$0818` boundary and `$AC` pacing retain the observed coroutine/IRQ ordering.
- SA-1 publishes a bounded render candidate; 5A22 acknowledges and renders it during
  its supervised PPU schedule.
- Input and sound rings cross the same ownership boundary.

Changing cadence, wait behavior, wake order, or DMA order can move an IRQ between two
producer operations. Earlier NMI/WAI and supervisor-wake experiments passed short
windows, then failed the known ordering event around ticks 765-767.

## Invariants

A scheduler or renderer change must preserve:

- real game-tick hook/counter agreement;
- recent tick and render progress;
- halt zero and expected task mask;
- every initialized task's saved stack above its real floor;
- input and sound-ring integrity;
- request, ACK, and true-render accounting;
- no unreported queue overflow or coalescing;
- coherent 5A22/SA-1 supervisor ownership; and
- the organic gate-off fallback.

## Performance vocabulary

Use **game-fps** only for an end-to-end production measurement that starts at power-on
with `TESTFLAG=0`, arms naturally, uses the real input mailbox, validates the actual
tick boundary, includes waits/IRQs/rendering/transitions, and identifies the exact
source and ROM.

The current Superman release gate is:

- at least 30 game ticks per emulated second; and
- no more than 358,000 SA-1 cycles per representative whole gameplay tick, including
  pacing and rendering.

The latest formal result is v124 at 29.700167 game-fps and 360,990.164 cycles/tick, so
both gates remain red. Older 60 Hz, 150K, 178K, projected-fps, and injected-span goals
are historical campaign targets, not the current acceptance contract.

## Tools

- `tools/recovery_baseline.py` — qualifying power-on production run.
- `tools/profile_continuous.py` — non-pausing phase attribution.
- `tools/soak_gameplay_ordering.py` — checkpointed ordering/conservation soak.
- `tools/profile_tick_ring.py` — diagnostic-build PC attribution only.
- `tools/build_idle_vsync_lab.py` and `tools/soak_idle_vsync_lab.py` — rejected pacing
  laboratories, retained for evidence and future hypotheses.

Read the [current validation contract](../current/VALIDATION.md) before reporting a
number. Historical negative results and raw campaign interpretation are preserved in
[R5 scheduler experiments](../history/performance/R5_SCHEDULER_EXPERIMENTS.md) and
[the profile campaign](../history/performance/PROFILE_CAMPAIGN.md).
