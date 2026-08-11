# Virtual IRQ timing repair design

Last reviewed: August 11, 2026.

This is a design and evidence-routing document for the Stage 3 virtual
level-6 IRQ defect. It is not an implementation acceptance report. The active
`a976…` ROM is a 66-byte terminal-CCR repair based on `5c7e…`. Its fresh
native-on root reaches tick 14,746 and retains a safe tick-14,743 state, but
the exact current three-way gate remains green at ticks 14,744--14,745 and red
at tick 14,746 in `build/validate-stage3-irq-order-current-a976-v1.json`:
MAME task 15 saves `$0259B0`/`$0242BE`, SR `$2400`; native-off and native-on
both save `$02429C`/`$00044E`, SR `$2404`, then diverge in collision/RNG. Its
checkpoint-local rate is 2,471,287.70 native-on and 11,320,496.0 all-native-off
SA-1 cycles/tick, not the required 358K
(`build/measure-stage3-current-a976-safe14743-v1/summary.json`). The active
hash now also has an authenticated native-on continuation from that exact
fresh-lineage safe state through tick 15,050 at
`build/continue-stage3-current-a976-safe14743-native-on-v1`: it remains live
but records 15 downstream player differences after the already-established
tick-14,746 split. The focused rerun
`build/continue-stage3-current-a976-safe14743-native-on-prefailure-v2` stays
exact through its tick-14,839 input boundary and deterministically turns red
at tick 14,841, retaining an immutable nonresumable pre-input forensic state.
Those are propagation/liveness records, not a recovery, a new root, a
native-off continuation, Stage-3 completion, or rate proof.
See [STATUS.md](STATUS.md) and [RELEASE_BLOCKERS.md](RELEASE_BLOCKERS.md).

The opt-in VTIME diagnostic now closes the smaller `$02429C` source seam. Its
bank-$F3 copy owns all 35 original blocks, flushes before all eleven genuine
return child transfers, runs every child under the interpreter per-fetch
clock, and resumes the exact F3 continuation. The ordinary bank-$99 route and
`op_rts_sentinel` bytes remain unchanged when `VTIME=0`. Source closure is
green at `build/audit-stage3-2429c-common-clock-closure-b758-v3.json`; exact
runtime evidence is green 8/8 at
`build/validate-vtime-2429c-root-b758-v3.jsonl`, with exact handoff and
synthetic first-deadline checks at
`build/validate-vtime-esc5-root-handoff-b758-v3.json` and
`build/validate-vtime-esc5-root-due-b758-v3.json`. This diagnostic is built
from the unaccepted ordinary `b758…` source state, not the active `a976…` ROM.
Follow-on diagnostic `efeb08e8…` makes the `$074C` collapsed scheduler scan
decline to the exact interpreter clock whenever VTIME is valid. Both its active
and invalid-clock routes are green in exact Nexen at
`build/validate-vtime-scheduler-scan-fallback-b758-v4.json`. The global
boundary remains explicit: 11 of 26 legacy `$AC` writers and 12
accelerated interpreter/scheduler/native/HLE/renderer/idle seams remain
unmigrated at `build/audit-vtime-legacy-ac-writers-b758-v3.json` and
`build/audit-vtime-accelerated-boundaries-b758-v3.json`. Therefore the result
does not repair fresh VTIME gameplay: the v3 and v4 controller controls stop at
the credit gate before any gameplay transition, observing 7 and 5 credits
respectively instead of 8. Their compact reports are under
`build/playback-watcher-20260808/vtime-2429c-root-3dc-fresh-to3000-native-on-v1/`
and
`build/playback-watcher-20260808/vtime-2429c-root-schedfallback-efeb-fresh-to3000-native-on-v1/`.
The matching v4 gameplay-native-off control is identically red at 5/8 credits
with zero gameplay transitions under
`build/playback-watcher-20260808/vtime-2429c-root-schedfallback-efeb-fresh-to3000-native-off-v1/`.
The fallback is locally exact but campaign-rejected, and its credit-gate miss
is shared VTIME/scheduler timing rather than gameplay-native dispatch.
Focused pulse probes show the direct throughput mechanism: v3 advances 69
game ticks over the fixed 215-frame credit window and recognizes 7 pulses; v4
advances only 44 and recognizes 5. The reports are
`build/probe-vtime-credit-pulses-3dc-v3/summary.json` and
`build/probe-vtime-credit-pulses-efeb-v4/summary.json`. The fallback has been
removed from current source and remains only as a retained negative artifact.
Two VTIME micro-optimizations are also retained negative: checked-call fast
path `9aa32c55…` advances 71 ticks and dynamic-class prefilter `9ae08316…`
advances 72, but both preserve the same 7/8 credit result. The exact-MAME root
remains green 8/8 for the former, so the rejection is throughput/bootstrap,
not a newly observed root semantic failure. A one-word Select latch
`2567dd89…` worsens the result to 6/8 by delaying neutral releases. All three
source changes were reverted. The bounded samples identify pulse 2 as the
lost edge: its frame-5256--5260 hold is entirely inside game tick 82. The
unchanged v3 ROM recognizes all eight edges when only the pre-game harness
bootstrap uses eight-frame holds and gaps
(`build/probe-vtime-credit-pulses-3dc-v3-long8-v1/summary.json`). Fresh Luna
controls then separate bootstrap phase from gameplay readiness: settle 155
reaches origin RNG 22,330, one recurrence before 200; settle 95 reaches 28,686,
20 recurrences before; settle 158 passes the origin-RNG gate but observes only
6 of 29 requested gameplay `$92:DB82` entries across frames 5,650--8,106. No
gameplay input transition or oracle divergence is reached. The compact reports
are the three `watcher-report.json` files under
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8*-fresh-to3000-native-on-v1/`.
That is a diagnostic bootstrap allowance, not VTIME, input, gameplay, or rate
acceptance. The later apparent gameplay-phase throughput/exact-entry blocker
was a 5A22 control-flow failure, not insufficient SA-1 entry cadence. Terminal
capture found two interrupt faults: NMI modified a saved status byte instead
of preserving the interrupted mask state, and the pending-DMA flag remained
published across `MDMAEN`, allowing an NMI at DMA completion to replay the
same descriptor recursively. After preserving both status bytes and clearing
the flag before DMA, the remaining renderer stall was traced to asynchronous
`bg_scroll` clobbering direct-page `$D0`; the NMI keepalive now preserves it.
The combined opt-in image is `e00fb0cb…`. Fresh native-on and matching
diagnostic-tool native-off controls reach tick 250 without divergence or stack
corruption, and fresh native-on reaches tick 1,100 with 98/98 retained exact
entries, six green input transitions, 12 green player references, valid task
floors, and continued rendering. The compact reports are under
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-*`.
An authenticated continuation from `resume_mame_tick` 1,098 reaches tick 3,000
with no mismatch, 168/168 green player references, 2/2 green death/respawn
references, valid floors, and live rendering. That extends the liveness and
gameplay bound but remains checkpointed sampled/transition evidence.
The next continuation from `resume_mame_tick` 2,998 reaches tick 6,000 with no
mismatch, 1,134/1,134 green player references, 4/4 green death/respawn
references, all listed action/button gaps closed, valid floors, and live
rendering. Boss coverage remains absent.
The following continuation from `resume_mame_tick` 5,998 reaches tick 10,000
with no mismatch, 2,062/2,062 green player references, 10/10 green
death/respawn references, valid floors, and live rendering. After the
resume-at-input-edge harness fix is proven, the next continuation from
`resume_mame_tick` 10,008 reaches tick 14,750 with no sampled player mismatch
and retains all tick-14,743--14,747 boundaries. It ends with 2,745/2,745 green player
references, 12/12 green death/respawn references, valid floors, and live CPUs
and rendering. Exact work-RAM attribution shows those sampled fields hid the
same historical seam: `e00f…` first differs at tick 14,746 in task 15,
RNG, and collision state, then at the tick-14,839 false-hit marker and
tick-14,840 player state. The report is
`build/playback-watcher-20260809/vtime-2429c-root-b758-nmi-dma-d0-native-on-attribution-v1/watcher-report.json`.
The exact phase reduction `build/validate-vtime-stage3-phase-e00f-v3.json`
measures the cause boundary. Original MAME consumes 131,286 cycles between the
tick-14,745 game boundary and task-15 `$02429C`; VTIME charges 16,308, leaving
a 114,978-cycle deficit before the root starts. The candidate then enters the
root with 61,448 two-cycle units remaining, while MAME takes level 6 only
7,692 cycles later inside `$025110`. Route hooks show zero `$97:8000` and
ESC3-ledger hits, so the child is genuinely interpreted and the local root
handoff is not the missing span. The retained pre-root trace observes 192
known entry hits; 185 hits across 52 labels are not admitted to a selected
ledger. The complete unadmitted+selected phase split is 16+0
control/scheduler, 35+2 scroll/player prepass, 48+4 player/renderer fanout,
8+0 selector/resume tail, and 78+1 task-15 pre-root. The validator records
`safe_narrow_fix_available=false`. This removes the campaign-control ambiguity
but leaves broad upstream/global common-clock coverage and Stage-3 rate open.
The corresponding opt-in interpreter-only image is
`build/interp-vtime-interpreter-only-e00f-v1.sfc`, SHA-256
`0bfae7d05a152441f9df4d028677641420a6053ce4148711668a1c5c6b48456f`.
After an exact fresh-bootstrap calibration, its retained v6 controller run at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-fresh-to250-v6/watcher-report.json`
matches the MAME tick-221/RNG-200 origin and remains partial-green through tick
250 over 29/29 interpreted game-update entries. Its safe rendezvous advances
the SA-1 exact-stop PC `$008F56->$008F58`, observes zero additional entries,
and produces three byte-identical resumable saves. This is the first clean
fresh prefix for the ROM-selected fallback. After the mode-aware child-return
gate repair, authenticated Luna-owned continuations extend that same fresh
lineage to a repeated-safe tick-14,743 boundary without an oracle mismatch.
The next request stops at its first player discrepancy at tick 14,841 in
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume14001-to15000-v1/watcher-report.json`:
MAME action 0 / health 4 / `(52,112)` versus SNES action 9 / health 20 /
`(68,96)`, after 14,611/14,611 cumulative exact entries. `$071A/$073A` remain
zero throughout. That is the same downstream false-respawn signature already
shared by ordinary native-off and native-on after their exact tick-14,746
task-frame split. The interpreter-only result therefore removes the last
campaign-length ambiguity from the broad-clock diagnosis; it does not admit a
narrow collision or gate fix. The repeated tick-14,743 checkpoint is recorded
in `docs/current/CAMPAIGN_EVIDENCE_LEDGER.json`, and
`tools/test_vtime_interpreter_only_stage3_divergence.py` pins the discrepancy.
The focused no-replay attribution at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-stage3-attribution-v1/watcher-report.json`
directly pins the same task-frame split at tick 14,746 and retains the prior
114,978-cycle deficit before `$02429C`; its compact guard is
`tools/test_vtime_interpreter_only_stage3_attribution.py`. This rejects the
root ledger as the next isolated repair target because the clock is already
late on entry.

The next bounded candidate makes all four scheduler shortcuts decline before
mutation under explicit interpreter-only VTIME. The corrected ROM is
`build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-v2.sfc`,
SHA-256 `60087042d9b0ecc48525258033009a634085deb661899724d917b8df78266ae9`.
Its per-fetch prepare path clears `$071A/$073A/$0736/$073C` for both a newly
initialized clock and an already-valid restored state. That restored-state
detail matters: the first migrated v1 seam retained `$0736=$5EEC` and
`$073C=$A55A` and is non-testing. The corrected Luna-owned v2 seam at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-seam-v2/watcher-report.json`
records all four gates zero at ticks 14,744--14,747 but leaves the first
task-frame divergence at tick 14,746 and the raw 21/21/78/81-byte mismatch
counts unchanged. The four-shortcut fallback is therefore not a sufficient
narrow repair. The paths were not directly instrumented in this seam, and the
result is ROM-migrated rather than fresh; it proves no common clock, rate, or
acceptance. `tools/test_vtime_interpreter_only_scheduler_fallback_evidence.py`
guards both the invalid-v1 and valid-v2 scopes. The next timing target remains
the other unmigrated global clock owners, including loop-collapse, `$0818`
idle/pacing, renderer, and retained native/HLE boundaries, not another long
campaign replay from an already-red state.

The next Luna disk reduction,
`build/playback-watcher-20260809/stage3-remaining-loop-idle-owner-scope-v1/watcher-report.json`,
checks 46,900 retained MAME instruction rows. `$0818` retires 1,993 times in
tick 14,744--14,745 but not at all in the failing 14,745--14,746 interval;
the other requested loop owners `$3B84/$3FEA/$ADBE` are absent, while
`$02429C/$025110/$0259B0` retire 1/1/27 times in that failing interval. A
bounded pre-mutation `$0818` fallback candidate then tests the sole preceding
loop owner. Its ROM is
`build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-v1.sfc`,
SHA-256 `7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387`.
The direct-hook seam at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-seam-v1/watcher-report.json`
observes 17,133 `$99:FBB0` gateway executions, zero `$99:FB00` paced-helper
executions, all four fallback gates zero, and halt zero. It nevertheless
leaves the first authoritative task-15 split at tick 14,746 and changes the
four mismatch totals only from the prior 21/21/78/81 to 21/21/78/83. This
rejects `$0818` fallback as a sufficient common-clock repair; it is a
ROM-migrated forensic negative, so no fresh long replay or timing acceptance
follows. `tools/test_stage3_remaining_loop_idle_owner_scope.py` and
`tools/test_vtime_interpreter_only_0818_fallback_evidence.py` pin the result.
The next active ledger scope is the failing-window
`$02429C -> $025110 -> $0259B0` child handoff plus the upstream lateness that
already exists on root entry.

The resulting Luna disk ledger is
`build/playback-watcher-20260809/stage3-2429c-25110-259b0-owner-ledger-v1/watcher-report.json`.
It divides the failing 139,486-cycle MAME interval into 1,554 cycles from
`$02429C` to `$025110`, 1,176 to `$02582E`, 146 to first `$0259B0`, 4,580
across 27 continuation rows, 216 to the IRQ boundary, and a 64-cycle entry
gap. Only 2,876 cycles elapse root-to-first-continuation, versus the retained
114,978-cycle pre-root deficit and 115,204-cycle root-entry lateness. Thus the
root/child/resume/IRQ handoffs are not common-clock-complete but no individual
owner is isolated. `tools/test_stage3_2429c_25110_259b0_owner_ledger.py`
guards this no-oracle reduction. The next bounded seam is read-only,
source-authenticated observation of those transitions; no clock mutation is
yet justified.

The completed seam is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-child-hooks-v1/watcher-report.json`.
All native `$02429C/$025110` branch, Stage-2, return, and resume hooks are
zero; the real IRQ entry hook fires four times, the four fallback gates stay
zero, and first task-frame divergence remains tick 14,746 with 21/21/78/83
differing bytes. Therefore those native handlers do not own the active
interpreter-only failure even though the corresponding MAME path is retired.
`tools/test_vtime_interpreter_only_root_child_hooks_evidence.py` guards this
ROM-migrated exclusion. The next clock attribution must first enumerate the
remaining accelerated owners that actually fire, especially CE4 renderer
and dynamic loop families.

The completed inventory is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-active-owner-inventory-v1/watcher-report.json`.
CE4 and all separately addressable unmigrated native/renderer `$AC` writers
are zero. Scheduler scan/switch entry hooks fire 64/42/42 times but their zero
gates already force fallback. Generic
`gm_memclr/gm_verify_far/gm_memset_far` check labels each fire 19,262 times;
the identical counts show a chained gateway path and do not prove acceptance
or clock mutation. The split stays at tick 14,746. The bounded scope is
guarded by `tools/test_vtime_interpreter_only_active_owner_inventory.py`.
Only an accept-versus-decline entry/exit ledger for that generic loop cluster
can now justify a further fallback experiment.

The completed Luna ledger is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-generic-loop-ledger-v1/watcher-report.json`.
Each generic family is entered 19,262 times, yet accepted memclr, verify, and
memset counts are all zero; 1,594 word-shaped memset checks also decline.
There is no generic collapsed mutation before, between, or after the captured
IRQs, and first task-frame divergence remains tick 14,746.
`tools/test_vtime_interpreter_only_generic_loop_ledger.py` guards the
no-accept exclusion. Further fallback experiments are blocked until the
interpreter/common-clock cycle model is reduced against MAME retired-cycle
truth.

The disk audit is
`build/playback-watcher-20260809/stage3-interpreter-common-clock-model-v1/watcher-report.json`.
It establishes that the retained 16,308-cycle selected charge and
114,978-cycle gap came from the older mixed preserve/native-on ledger, not a
measured SHA `7a22…` interpreter-only phase. That charge is 8,154 two-cycle
units, while the 131,286-cycle MAME span has 11,006 retired intervals (9,193
static-table exact and 1,813 dynamic). Current source already loads the static
CPU-000 table and applies the proven Bcc/DBcc/TRAP/MOVEM/shift corrections at
each interpreted fetch. The old gap cannot support a tuned constant or cycle-
model change. `tools/test_stage3_interpreter_common_clock_model.py` guards the
scope. The filtered read-only Luna measurement is now
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-phase-v1/watcher-report.json`.
The corrected custom-Nexen run exits zero, captures 4/4 boundaries and root
1/1, and retains its earlier wrong-companion-set attempt as invalid at zero
boundaries. Between the tick-14,745 boundary and `$02429C`, SHA `7a22…`
consumes 34,856 two-cycle units = 69,712 MC68000 cycles with no intervening
reload or IRQ, versus MAME's 131,286. It reaches root with 69,494 virtual
cycles remaining while MAME reaches IRQ 7,692 cycles later: a direct
61,802-cycle phase error. All fallback gates and halt remain zero; the first
task split remains tick 14,746. `tools/test_vtime_interpreter_only_root_phase.py`
guards the result. Candidate interpreted-fetch count versus MAME's 11,006
retired intervals is the next bounded discriminator. That Luna result is now
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-fetch-count-v1/watcher-report.json`:
6,471 prepare and 6,471 consume events, only 58.795% of MAME's 11,006 intervals
(deficit 4,535), with zero reloads or IRQs in the exact window. Gates and halt
remain zero and ticks 14,744--14,745 retain their 21-byte mismatch ranges.
`tools/test_vtime_interpreter_only_root_fetch_count.py` guards this rejection
of a cycle-table retune. The disk-only logical-PC alignment at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-pc-sequence-v1/watcher-report.json`
then reconstructs 6,471 valid candidate PCs against 11,006 MAME rows: 4,551
MAME deletions and 13 SNES insertions. The first deleted block, indices
223--234 at `$0008E6…$0008D8`, follows the unconditional `$0008DE` MOVE.L run
collapse at bank-$00 `mvc_check`. That owner explains 759 deleted MOVE rows,
not the entire deficit. A 2,970-row `$024998`-family deletion remains without
proven direct dispatch ownership. The guard is
`tools/test_vtime_interpreter_only_root_pc_sequence.py`.

The accelerated-boundary audit now includes the previously omitted
`mvc_check`. A size-neutral VTIME-only prefix substitution routes it through
`$F2:B4D1`, where bit 1 falls back to `op_move_g` before architectural
mutation. Candidate SHA `a49eedc7…` is guarded by
`tools/test_vtime_interpreter_only_mvc_fallback.py`; the ordinary SHA remains
`2dadd…`. Its bounded Luna result is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-fetch-v1/watcher-report.json`:
prepare/consume rises exactly 759 from 6,471 to 7,230, matching the deleted
MOVE rows; charge rises from 34,856 to 42,446 two-cycle units, and root
remaining falls to 27,157 units. No reload/IRQ or sampled gate/halt/task/player
regression occurs, while the same two 21-byte ranges remain. The candidate is
still 3,776 intervals short of MAME. The evidence guard is
`tools/test_vtime_interpreter_only_mvc_fallback_evidence.py`. The bounded PC
alignment at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-pc-v1/watcher-report.json`
confirms the recovered 759 MVC rows now align and leaves 3,792 MAME deletions
plus 13 SNES insertions. Its first 12-row deletion is unchanged. Its largest
2,970-row deletion contains 2,096 MAME `$0249xx` rows against zero candidate
logical `$0249xx` rows. A real-bank `$9D:C000/$B000/$B800` hook is therefore
the next bounded owner discriminator, not replay. The compact artifact guard
is `tools/test_vtime_interpreter_only_mvc_pc_sequence.py`. The completed owner
probe at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-native-owner-v1/watcher-report.json`
finds zero strict-window hits at `$00:D360/$D36E`, `$9D:C000`, `$9D:B000`, and
`$9D:B800`; prepare/consume remains 7,230/7,230 and reload/IRQ remains zero.
The candidate therefore skips the allocator/pool path itself rather than
executing it invisibly in native code. The exclusion is guarded by
`tools/test_vtime_interpreter_only_root_native_owner.py`; existing alignment
and work-RAM artifacts must be reduced before another run.
The completed disk-only reduction is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-branch-context-v1/watcher-report.json`.
Equal scheduler anchors `$0007E4/$000766` bracket all 2,970 MAME-only rows;
the candidate executes no PC between them. MAME calls `$0249C2` and `$02498C`
from `$02E8B8/$02E8C4`. No captured differing byte is a directly named path
operand, and only eight of the 21 bytes are inside mapped 16-KiB work RAM.
The tracked game-tick low byte `$F01C57` is MAME `$97` versus candidate `$96`,
which establishes a one-count boundary offset but not a causal link to the
skipped path. Zero-advance ROM-migrated reads at retained v6 gameplay-origin
tick 221 and safe tick 250 already show the one-count `$F01C56` offset
(`$00DA/$00DB` and `$00F7/$00F8`). It therefore predates Stage 3 and is not a
new Stage-3 timing loss. Those reads are checkpoint provenance, not fresh-
current-candidate or acceptance evidence. A corrected tick-14,000--14,002
comparison shows `$F01C56` advancing once on both sides; the originally called
stall belongs to the separate IRAM `$0760` exact-entry counter. This does not
identify the responsible scheduler deadline or fix. The artifact guards are
`tools/test_vtime_interpreter_only_root_branch_context.py`,
`tools/test_vtime_interpreter_only_origin_phase_bytes.py`, and
`tools/test_vtime_interpreter_only_phase_counter_scope.py`.
Exact scheduler stops then record task 13 restoring `$02E864` before task 15;
there is no scheduler skip. Its retained VTIME prepare stream has zero interior
events between the task's `$0007E4/$000766` anchors while MAME retires 2,970
rows. The independent IRAM-PC-write stream follows `$0007E8→$02E864`, twelve
ordered `$02E8B8→$0249C2→$02498C` visits, and `$000532→$000766`, matching
MAME's target counts. The pool route therefore executes, but it is invisible
to VTIME prepare: this is a clock-ownership bypass rather than a gameplay-path
skip. Those writes prove ordered PC state changes, not retirement, so the
physical fetch-control owner remains open. The compact guards are
`tools/test_vtime_interpreter_only_root_task_selection.py`,
`tools/test_vtime_interpreter_only_root_task13_pc.py`, and
`tools/test_vtime_interpreter_only_root_task13_pcwrite.py`.
The exact physical control chain then reports 2,971 task-13 fetch/choke paths
but only one VTIME choke/consume/prepare. The packed pre-arm condition was
direct-page `LDA $2E`, which aliases emulated A3.H, rather than absolute
`$072E`. The diagnostic-only repair emits `LDA $072E`; ordinary ROM SHA
`2dadd12c…` is unchanged and fixed candidate SHA is `d91e28e9…`. On that
candidate all 2,971 fetch/choke paths reach consume and prepare, without a
reload/IRQ, frame, gate, halt, or next-scan regression. Boundary-to-root
prepare count becomes 11,010 versus 11,006 MAME rows. The known three-row
capture prefix reduces the raw surplus to one terminal `$0007E8`; the prior
2,970-row task-13 deletion is fully aligned, leaving one twelve-PC
delete/reinsert signature. Disk-only complete-call and producer reductions
resolve it: MAME mask `$00030000` selects palette ordinals 16--17, candidate
`$0000C000` selects 14--15, and both have two active iterations. Task 15 uses
the same `$003B42` load, `$003B46` rotate, `$003B4C` OR, and `$003B50→$0008C2`
chain. Candidate `$F01C56/$F01C58` remains one rolling call behind MAME, exactly
matching the offset already present in retained zero-advance tick-221 and
tick-250 states. This is checkpoint-origin phase, not a new Stage-3 path or
clock loss. The candidate intermediate `$F01B12` value is inferred from PC
sequence and work state; its single bounded hook attempt stopped before the
target. These are bounded diagnostic
facts, not global common-clock, freshness, rate, or acceptance. Guards are
`tools/test_vtime_interpreter_only_root_task13_fetch_control.py`,
`tools/test_vtime_interpreter_only_choke_gate.py`,
`tools/test_vtime_interpreter_only_choke_gate_evidence.py`,
`tools/test_vtime_interpreter_only_choke_gate_root_fetch.py`, and
`tools/test_vtime_interpreter_only_choke_gate_pc_sequence.py`, plus the
`...first12_context.py`, `...first12_mask.py`, and `...mask_writer.py` guards.
The campaign runner rejects an acceptance resume of the fixed ROM from the old
tick-14,743 state because serialized WRAM contains the old video supervisor.
The retained forensic continuation moves the observed task-15 split to tick
14,747 but is neither resumable nor acceptance evidence.

The exact tick-14,746 boundary-to-root ledger on choke-gate SHA `d91e28e9…`
charges 61,277 two-cycle units against MAME's 60,699, an aligned +578-unit /
+1,156-cycle overrun. Both native-parent charge seams are present. The largest
equal-PC charge deltas exposed a four-byte-register indexing defect: both DBcc
dynamic timing helpers used `2*n` to read Dn. The conditional diagnostic fix
uses `4*n`, produces interpreter-only SHA `7583d110…`, and leaves ordinary ROM
SHA `2dadd12c…` byte-identical.

A disk-only counterfactual on the aligned ledger changes 493 DBcc pairs at 22
PCs. It removes 246 units/492 cycles, leaving +332 units/+664 cycles. Deferred
native/RTS representation differences cancel exactly; the honest remainder is
one extra 61-row candidate collision path (+326), the retained checkpoint mask
phase (+5), and +1 unit in common instructions (`DIVU` +2, Bcc -1). This is not
evidence for another DBcc adjustment. Exact MAME 0.287 represents DIVU timing
inside its cycle-core microcode, so a PC-local two-cycle exception is not an
acceptable general timing repair.

The cumulative `7583d110…` interval's -19-unit endpoint is explicitly not an
aligned oracle comparison: task 15 is already `$025856` versus MAME `$0259B0`
at the starting tick-14,746 boundary. Loading the old exact-entry state under
the new ROM was attempted once; it observed zero requested entries over 719
frames and ended at virtual PC `$F01B6C`, halt `$DEAD`. That state is an
ordinary paused boundary with `resumable_checkpoint=false` and must not be
replayed again.

The first fresh `7583d110…` controller attempt accepted 0/8 credit pulses. A
bounded preserved-ROM bisect at
`build/playback-watcher-20260810/fresh-credit-bisect-v1/watcher-report-v2.json`
isolates the loss to the diagnostic `$0818` pre-mutation fallback: `60087042…`
accepts 8/8, while its immediate `7a22b819…` successor accepts 0/8. In the
retained zero-advance state both CPUs run, but pacing arm/last-release/debt are
zero and request/ack is 64/0. The fallback jumped around the paced S-CPU/NMI
rendezvous. MVC, choke, and DBcc changes postdate the bracket.

Default interpreter-only VTIME therefore keeps `$0818` on the paced helper;
the rejected pure-interpreter path is explicit opt-in bit 2. The VTIME packer
retargets the diagnostic gateway mask without changing ordinary ROM SHA
`2dadd12c…`. The resulting paced/DBcc diagnostic is SHA `14e920eb…`. Its
changed phase was calibrated without writes from a same-ROM credited state:
MAME's origin target occurs after a 3,224-frame credited wait at frame 9,432,
tick `$0760` 168, RNG 2,716. This is a controller-bootstrap calibration, not a
common-clock or rate claim.

The one calibrated fresh `14e920eb…` run is partial-green through MAME tick
250 at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-fresh-to250-calibrated-v1/watcher-report.json`:
8/8 credits; interpreted `$003A92` origin at MAME tick 221/RNG 200; 29 neutral
gameplay ticks with zero oracle divergence; halt zero. Three independently
saved copies of the safe tick-250 state have SHA `ba6f0490…`; their SA-1 IRAM
sidecars have SHA `8950c547…`. The report proves a resumable post-entry
`$008F56->$008F58` boundary. It is a short fresh lineage seed only, so continue
from that state in bounded segments and do not replay the bootstrap. One bad
parent-supplied resume argument (`250` instead of the event's `251`) was
rejected before emulator launch and is not playback evidence. The corrected
same-ROM continuations are partial-green through tick 806 (555/555 entries)
and tick 1,100 (293/293 more): cumulative 877/877 interpreted entries, 12/12
player references, six real input transitions, zero oracle divergence, and
halt zero. Tick-806 state SHA is `fe4a5409…`; tick-1,100 state SHA is
`27207e5f…`, with sidecar `5cb96e4f…` and resume tick 1,101. Its same-ROM child
is now partial-green through tick 3,000: 1,899/1,899 segment and 2,776/2,776
cumulative interpreted entries, 168/168 player references, 84 real input
transitions, every gameplay button, actions 0/1/2/8/9, one matched death, zero
oracle divergence, halt zero, valid task stacks, and live rendering. Actions
3/4/5/7/10 and bosses are absent. Repeat-identical resumable states at
1,500/2,000/2,500/3,000 cap replay cost; the last is SHA `47dc58a1…`, IRAM
`4ee69101…`, resume tick 3,001. Two retained launcher-preflight negatives
executed zero gameplay; the exit-0 partial-count-Nexen run is authoritative.
The next same-hash continuation remained green through tick 4,559 and then
lost its Nexen MCP transport mid-call, without an oracle mismatch or gameplay
failure. Its repeat-identical tick-4,500 checkpoint allowed a bounded recovery
that replayed only 59 green ticks and reached tick 5,000 with
`--continue-oracle-divergences`. The authenticated cumulative lineage is now
4,833/4,833 entries with 921/921 player references, every action ID, two
deaths with 4/4 death references, zero divergence, halt zero, live rendering,
and minimum task-stack margin 138. The repeat-identical tick-5,000 state is SHA
`0fd2e312…`, IRAM `9e6e7605…`, resume tick 5,001. Bosses remain absent. This
transport stop invalidates no gameplay evidence and requires no ROM rebuild or
fresh replay.

A subsequent Luna-owned same-hash continuation is partial-green through tick
6,500: 1,499/1,499 segment and 6,332/6,332 cumulative entries, 1,210/1,210
player references, 605 real transitions, every action ID, two deaths with 4/4
green death references, zero divergence, halt zero, live rendering, and
minimum task-stack margin 138. Bosses remain absent. Repeat-identical states at
5,500, 6,000, and 6,500 cap replay cost; tick 6,500 is SHA `fb9644dd…`, IRAM
`26c824b3…`, resume tick 6,501. No rebuild or fresh boot occurred.

The first child at tick 6,501 completed no new entry because that resume tick
is an input edge and the harness indexed an empty zero-entry `spans` list. Its
`OSError(9)` was cleanup fallout, not a transport or gameplay failure. The
guarded harness now processes the same-tick edge without executing or indexing
an entry and advances at 6,502. The failed child invalidates no accepted parent
evidence and does not require a ROM rebuild.
The first corrected retry was rejected before emulator launch because the
harness change altered the runner SHA. The finite resume-compatibility gate now
admits exactly the tick-6,500 parent runner `2030c213…` for this reviewed zero-
entry-only successor; arbitrary drift remains rejected. The preflight-only
negative invalidates no evidence.

The corrected Luna-owned v3 is partial-green through tick 8,000: 1,499/1,499
segment and 7,831/7,831 cumulative interpreted entries, 1,585/1,585 cumulative
player references, 793 cumulative real transitions, every action ID, two
deaths in this segment, 6/6 cumulative death references, zero divergence,
halt zero, live rendering, and all 15 initialized task stacks valid with
minimum margin 130. Bosses remain absent. Repeat-identical states at
7,000/7,500/8,000 cap replay cost; tick 8,000 is SHA `aea7ce50…`, IRAM
`99bab411…`, resume tick 8,001. No rebuild or fresh boot occurred.

The next same-hash segment is partial-green through tick 9,500: 1,499/1,499
segment and 9,330/9,330 cumulative entries, 1,852/1,852 cumulative player
references, 926 cumulative real transitions, every action ID, two deaths in
this segment, 8/8 cumulative death references, zero divergence, halt zero,
live rendering, and all 15 initialized stacks valid with minimum margin 138.
Bosses remain absent. Repeat-identical states at 8,500/9,000/9,500 cap replay
cost; tick 9,500 is SHA `efd193b0…`, IRAM `fabcd919…`, resume tick 9,501. No
prefix replay, rebuild, or fresh boot occurred.

The next same-hash segment is partial-green through tick 11,000: 1,499/1,499
segment and 10,829/10,829 cumulative entries, 2,402/2,402 cumulative player
references, 1,201 cumulative real transitions, every action ID, two deaths in
this segment, 10/10 cumulative death references, zero divergence, halt zero,
live rendering, and all 15 initialized stacks valid with minimum margin 138.
Bosses remain absent. Repeat-identical states at 10,000/10,500/11,000 cap
replay cost; tick 11,000 is SHA `6fd49508…`, IRAM `ef9a8033…`, resume tick
11,001. No prefix replay, rebuild, or fresh boot occurred.

The next same-hash segment is partial-green through tick 12,500: 1,499/1,499
segment and 12,328/12,328 cumulative entries, 2,566/2,566 cumulative player
references, 1,283 cumulative real transitions, every action ID, two deaths in
this segment, 12/12 cumulative death references, zero divergence, halt zero,
live rendering, and all 15 initialized stacks valid. Minimum stack margin fell
from 138 to 92 and remains an explicit safety watch. Bosses remain absent.
Repeat-identical states at 11,500/12,000/12,500 cap replay cost; tick 12,500
is SHA `0ff1242f…`, IRAM `83608462…`, resume tick 12,501. No prefix replay,
rebuild, or fresh boot occurred.

The next same-hash segment is partial-green through tick 14,000: 1,499/1,499
segment and 13,827/13,827 cumulative entries, 2,650/2,650 cumulative player
references, 1,325 cumulative real transitions, every action ID, no new deaths,
12/12 cumulative death references, zero divergence, halt zero, live rendering,
and all 15 initialized stacks valid; minimum margin recovered to 138. Bosses
remain absent. Repeat-identical states at 13,000/13,500/14,000 cap replay cost;
tick 14,000 is SHA `234ef4ad…`, IRAM `a5d1d340…`, resume tick 14,001. No
prefix replay, rebuild, or fresh boot occurred.

The same-hash continuation safely reaches tick 15,500, but the exact green
prefix ends at 14,747. First divergence at 14,748 is player Y only (SNES 139,
MAME 136), followed by 27 Y-only records at 24 sparse ticks through 14,866 and
no later recorded mismatch through 15,500. The segment completes 1,499/1,499
entries and 15,326/15,326 cumulative entries with halt zero, live rendering,
and all 15 initialized stacks valid at minimum margin 138. Its end SNES tick
15,494 versus MAME 15,500 changes the prior two-tick offset. Focused diagnosis
from tick 14,500 is distinguishing timing alignment from semantic player-Y
drift; neither is presumed. No Stage-transition or boss event was emitted.
Repeat-identical states at 14,500/15,000/15,500 cap replay; tick 15,500 is SHA
`43f9c07c…`, IRAM `d5dff99d…`, resume tick 15,501. No rebuild or fresh replay
has occurred.

The nearest-checkpoint reduction initially appeared to confirm a causal
contract, but that attribution is now superseded. A corrected hard-bounded
alignment of the interpreted `$025110` child has 553 common
retirement rows, no PC/opcode mismatches, and zero adjusted-cost delta across
all common rows and each segment. The earlier repeated-loop `+132` delta and
`$02584A` branch mismatch were caused by a wrong repeated MAME interval and are
invalid. At the exact `$0818` IRQ boundary, the candidate's six paired consumes
total 47 units/94 cycles because they begin with stale `$0818/4E75` cost 8 and
end before the final `$000708/4EB9` cost 10; the six prepared ISR instructions
correctly total 49 units/98 cycles. MAME also has a separate 66-cycle IRQ edge.
The aligned first `$003A92->$025110` span is candidate 133,046 versus MAME
133,020 cycles (`+26`). This remains a real VTIME interrupt-entry plus
prepare/consume endpoint-ownership defect, but later counterfactuals prove it
is not sufficient to cause or cure the tick-14,748 Y mismatch.

Source inspection matches that runtime result: `vtime_consume_expired` leaves
the staged pre-IRQ cost, `vtime_reload_virtual` reloads/clears due state without
discarding that cost or staging exception ownership, and `take_irq` builds the
interrupt frame without a VTIME owner. The compact result is
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume14001-to15500-v1/focused-y-write-v1/irq-cost-pipeline-v1/irq-cost-report.json`,
and `tools/test_vtime_interpreter_only_irq_cost_pipeline.py` rejects the
invalidated loop/branch interpretations.

The superseding causal result is the input-publication clock boundary. On v4
`4a3555fd…`, both the `+2` interval-clock seed and a direct -1-unit child-entry
countdown mutation leave the first mismatch at 14,748. Corrected ordering puts
the immediate `$003AD8` read before the next `$0818` re-arm. NMI completes the
`$0088` pad sample after the wake decision, while arm=2 prevents the ordered
mailbox write; candidate P1 therefore remains `$FF` where MAME is `$EE`.
Directly consuming the newest staged sample in v6 shifts the mismatch to
14,747, proving that immediate sampling is one game tick too early.

V7 adds a diagnostic-only delayed P1 commit at `$F2:B740`, outside the repaired
dynamic decoder ending at `$B71E`. It leaves generic `joy_read` unchanged,
honors a real `$0818` publication when `$41012B` advances, and otherwise
returns the preceding staged sample while publishing it to the shared mailbox
for the rest of the input block. ROM `45c9096d…` passes the ROM-only migrated
tick-14,745-to-14,750 comparison with Y 139 at 14,747 and Y 136 at 14,748,
2,746/2,746 green player rows, no divergence, and repeat-identical terminal
states. See
`build/playback-watcher-20260811/v7-input-delayed-migrated14745-to14750-v2/watcher-report.json`.
This is focused checkpoint evidence only; fresh-boot timing authority remains
open.

Post-divergence playback on the same ROM now reaches tick 17,000. The segment
remains live and stack-safe but records 38 divergences: 13 input, 14
input-response, and 11 Stage-1 boss rows. A disk-only reduction finds the boss
fixtures at sparse MAME ticks 15,906--16,919 with a uniform six-game-tick SNES
lag. Initialization is expected health 40 but observed 0, and every later
observed health is the preceding fixture's expected health. This is moderately
confident propagation from the inherited timing drift; it does not isolate a
new boss-health semantic defect. All boss rows are red. Repeat-validated
checkpoints at 16,000/16,500/17,000 preserve forensic continuation; tick
17,000 is state `a9826e63…`, IRAM `cdf1a8c7…`. Compact reports are under
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume15501-to17000-v1/`.

The next same-hash Luna segment reaches tick 18,500. Three later boss fixtures
continue the one-row delay: expected/observed health `6/9`, `2/6`, and
`$FFFF/2` at ticks 17,018, 17,560, and 17,654. Cumulative divergence classes
are 13 input, 14 input-response, and 14 boss rows; every boss fixture is red
and no independent semantic root is localized. Halt remains zero, all task
stacks stay valid at minimum margin 138, and rendering remains live.
Repeat-validated checkpoints at 17,500/18,000/18,500 preserve forensic
continuation; tick 18,500 is state `718d3dd3…`, IRAM `a14d74b7…`.

The same-hash Luna continuation then reaches tick 20,000 without a new
mismatch or boss-fixture row; cumulative classes remain 13 input, 14
input-response, and 14 boss. Halt remains zero, rendering remains live, and
all initialized stacks are valid at minimum margin 136. Repeat-validated
checkpoints at 19,000/19,500/20,000 preserve the endpoint; tick 20,000 is
state `caf9df72…`, IRAM `f06ec2ad…`, resume tick 20,001. This is forensic
continuation only and does not extend accepted truth beyond tick 14,000.

Repair requires changing this packed handoff and therefore producing a new ROM
hash. The precise replacement charge and boundary protocol remain to be
implemented and proven in focused tests; no source timing edit or rebuild has
been made. Acceptance evidence from calibrated tick 221 onward would have to
be replayed for a new hash, while this `14e920eb…` campaign remains preserved
as historical/diagnostic evidence. No fresh boot is authorized or running.

None of this establishes Stage 3, boss behavior, timing acceptance, rate,
promotion, or production fitness. Continue the current hash in bounded Luna-
owned segments and continue post-divergence when state safety permits; focus
diagnosis at the nearest checkpoint and batch nonblocking fixes. Before a new
ROM lineage, disclose the confirmed root cause, rebuild necessity, and fresh
evidence invalidated. A new fresh boot requires explicit approval. The focused
paced-default, DBcc, and current-hash campaign tests guard these limits and
checkpoint transitions.
Stage-3 rate, ordinary three-way recovery, boss gameplay, and global
common-clock promotion remain open.

## Established oracle facts

- The original board's M68000 is 8 MHz, its MAME screen is 57.43 Hz, and its
  vblank uses level 6 `HOLD_LINE`. The nominal deadline is exactly
  `800000000/5743` MC68000 cycles, or `139300 + 100/5743` cycles per frame.
  The read-only reduction is
  `build/validation-mame-superman-vblank-clock-current-f369-v1.json`.
- The fresh original-code MAME controller replay has exact Stage-3 service
  periods of 139,302, 139,296, and 139,342 cycles, with interruption PCs
  `$000818`, `$0259B0`, `$02582E`, and `$000810`. The service variation is
  expected: a held IRQ is taken at a completed-instruction boundary, not at a
  fictional fixed instruction count. The current exact-MAME-0.287 refresh is
  `build/mame-stage3-irq-phase-current-5c7e-v1/summary.json` and its green
  artifact regression is
  `build/validate-mame-stage3-irq-phase-current-5c7e-v1.json`; the prior
  `f369…` report remains provenance only.
- The fresh power-on MAME owner-activity probe
  `build/mame-scheduler-cycle-phase-current-a976-14743-14747-v3` adds 5,055
  timestamped program-space observations across ticks 14,743--14,747. It
  sees scheduler scan/select/switch seams, `$0818`, task 15, and the collision
  route. A MAME program-read tap can also see data reads and prefetches, so its
  labels are owner-activity observations only—not retired instruction or
  basic-block timing. The qualified reduction
  `build/validate-mame-scheduler-cycle-phase-current-a976-v2.json`, guarded
  by `tools/test_mame_scheduler_cycle_phase.py`, joins it to the
  instruction-only debugger trace and re-proves the four IRQ PCs `$000818`,
  `$0259B0`, `$02582E`, `$000810` and periods
  139,300/139,302/139,296/139,342. This
  refines the ledger boundary without admitting any scheduler/root owner to
  VTIME or changing the Stage-3 repair/rate block.
- The native-entry address trace used while scoping that root is now qualified
  against active `a976…` by
  `build/validate-active-native-entry-alignment-current-a976-safe14743-v2.json`
  and `tools/test_active_native_entry_alignment.py`: its 240 source-labelled
  observed hits are 236 exact source-byte matches and four documented
  production counter-strip hits. The correction is material only to address
  provenance: bank `$9F` source begins at `$A100` and is packed at file
  `$2FA100`. It is not a whole-ROM source identity, a timing model, or a
  repair admission.
- The corresponding active-`a976…` one-tick fetch-boundary profile is retained
  at `build/profile-stage3-tick-current-a976-safe14743-v1/profile.json` and
  guarded by `tools/test_stage3_current_a976_profile_evidence.py`. Its
  1,936,861 cycles / 11 video frames / 413 fetches are perturbed diagnostic
  data, not a rate result. `$0242BE` is 5.24% of the total and the top 20
  attributions are 40.35%, so this record rejects a single-bridge or
  renderer-only timing diagnosis; it does not alter the common-clock repair.
- Its guarded region reduction at
  `build/analyze-stage3-current-a976-hot-regions-safe14743-v1.json`
  (`tools/test_stage3_current_a976_hot_regions.py`) selects `$027B` record
  emission (32.52%) and `$02E4-$02E5` draw dispatch/call setup (18.71%) for
  future independent native-span work. Those are fetch-attribution lower
  bounds, not timing ownership or rate-repair admissions.
- The first selected `$027B` route is now classified exactly. Original MAME
  executes `$027B44/$027B7C` 60 times each in the retained Stage-3 trace, but
  active `a976…` reaches native parent `$027952` 12 times from the shared safe
  checkpoint while both child wrappers fire zero times. The bank-$02 compact
  sparse dispatcher had no cases for those targets, so it intentionally
  rejoined interpretation. The unpromoted hash-guarded candidate `387855da…`
  adds only the two dispatcher cases and the already-validated `$027AEA`
  parent edge. It is 14/14 green in exact original-MAME/native-off/native-on
  parent comparisons and fires all three children organically at that
  checkpoint. The fresh Stage-1 rejection makes the candidate non-promotable;
  see `build/validate-stage3-record-emitter-route-coverage-current-a976-v4.json`.
  That v4 reduction also records the next live sparse miss, `$02E524`: 60
  original MAME executions but zero active/candidate wrapper entries. Its
  1,800,936.97-cycle checkpoint result still misses 358K, so this narrows a
  native/HLE throughput loss but does not alter the separate common-clock
  timing root or authorize promotion.
- The ordinary current `5c7eeb37…` ROM has the retained three-way task-frame
  gate at `build/validate-stage3-irq-order-current-5c7e-v1.json`. It uses exact
  original-code MAME plus authenticated gameplay-native-disabled and
  production-native-on continuations. Ticks 14,744--14,745 agree; at 14,746
  MAME saves task 15 at `$0259B0`/`$0242BE`, SR `$2400`, while both SNES modes
  retain `$02429C`/`$00044E`, SR `$2404`. The following tick changes
  collision/RNG state in both SNES modes. This establishes the timing root for
  the active ROM, but does not supply a timer repair or Stage-3 completion.
- The matching current-hash physical-delivery capture is intentionally red at
  `build/capture-stage3-irq-delivery-current-5c7e-v3/summary.json`. Before
  running, it verifies the fresh Nexen restore against the authenticated
  public-state metadata and complete SA-1 IRAM sidecar, with no architectural
  writes, and restores the recorded port-0 input. It reaches the third
  `$025110` entry but no `$02582A/$02582E/$0259B0` yield, then takes the
  virtual IRQ at logical `$000818` with task 15 still
  `$02429C`/`$00044E`/SR `$2404`. This is a native-on checkpoint forensic,
  not a fresh-boot, native-off, rate, or repair claim.
- An authenticated, non-mutating execution-route trace over the three exact
  intervals is green at
  `build/trace-stage3-timing-boundaries-current-5c7e-v1/summary.json`. Each
  interval reaches the scheduler select, scheduler switch-in/out, CE4,
  `$02429C`, `$025110`, and `$0818` pacing boundaries. The first two intervals
  invoke the generic bank-$94 legacy `$AC` helper 140 times each; the failing
  third interval invokes it 176 times. That identifies a live mixed-clock
  route, not merely a static source inventory. A candidate leaving that helper
  or the `$0818` release in instruction-countdown units cannot close this
  failure.
- The follow-up current-ROM caller trace is green as an observation at
  `build/trace-stage3-ac94-callers-current-5c7e-v1/summary.json`. It discovers
  all 82 active-ROM bank-$94 `JSR esc_ac_charge` sites, then authenticates and
  replays the same three intervals. The 140/140/176 helper calls are exact;
  the 36 calls unique to the failing update are 12 visits each to `$94:D548`,
  `$94:D567`, and `$94:D586`: the three 3/2/5-instruction blocks of the
  `$02E40E` address leaf. This identifies the first variable-work trigger for
  the late IRQ. It does not isolate a native-only root (native-off also fails)
  or authorize a one-leaf count adjustment; all three paths still require the
  common cycle clock described below. Its focused retained-artifact regression
  is `build/validate-stage3-ac94-variable-work-current-5c7e-v1.json` and
  `tools/test_stage3_ac94_variable_work.py`; green there means only that this
  failure trigger is reproduced, never that a timer repair was accepted.
- The matching original-MAME cycle reduction is green at
  `build/analyze-stage3-2e40e-cycles-current-5c7e-v1.json`: all 72 retained
  calls cost exactly 80 cycles for `D0.b < 7` or 94 cycles for `D0.b >= 7`.
  The failing MAME update has 21 calls (7 low-path, 14 high-path). This is
  concrete ledger input for `$02E40E`; it does not justify translating its
  3/2/5 instruction charges in isolation while the surrounding route remains
  mixed-clock. The separately authenticated native countdown capture now
  observes the actual stores: each of the 12 red-tick visits subtracts exactly
  3, then 2, then 5 from legacy `$AC`, with the helper reached seven SA-1
  cycles after its call site and its low/high word-store 32/33 cycles after.
  `build/validate-stage3-ac94-countdown-current-5c7e-v1.json` and
  `tools/test_stage3_ac94_countdown.py` join that observation to the exact
  MAME 80/94-cycle ledger. They preserve the instruction-unit/cycle-unit
  mismatch; they do not approve a native-only leaf adjustment.
- The register-qualified trace proves all 10,803 retained conditional Bcc and
  DBcc records against their actual SR/Dn outcomes. Short Bcc is 10/8 cycles,
  word Bcc is 10/12, and the observed DBcc loop-back/expired cases are 10/14.
  See `build/validation-mame-25110-branch-timing-current-f369-v2.json`.
- A development-only static CPU-000 table explains 38,888 of 46,874
  ROM-resident instruction pairs. The remaining 7,986 trace pairs are
  concentrated at path-dependent branch/loop, MOVEM, shift/rotate, and
  arithmetic sites. The comparison is evidence of an insufficient static
  model; it does not attribute every mismatch to a single MAME-core mechanism.
  See `build/audit-m68k-cycle-model-current-f369-v6.json`.
- The register-qualified reducer now proves all 830 retained MOVEM records
  (their extension-word register masks) and all 452 retained data-register
  shift/rotate records (their immediate or Dn counts) against original MAME
  with zero mismatches. See
  `build/validation-mame-25110-variable-timing-current-f369-v2.json`.
- The remaining retained exception/arithmetic sentinel covers all 44 `TRAP #n`
  rows at the CPU-000 vector-32--47 total of 34 cycles, plus the six observed
  multiply/divide operand rows. See
  `build/validation-mame-25110-exception-arithmetic-timing-current-f369-v1.json`.
  The arithmetic rows are deliberately not a general multiply/divide formula;
  that coverage remains required before claiming a complete dynamic model.

## Required behavior

The repair must represent a common virtual MC68000 clock, not a tuned `$AC`
instruction count.

1. Use a 2-cycle-unit countdown. The nominal deadline is
   `69650 + 50/5743` units, so a 16-bit `$AC` alone cannot hold it. Carry the
   high countdown bit and the fractional phase explicitly.
2. Charge one completed interpreted instruction by its actual path cost. In
   particular, branch/DBcc rules must use current CCR/X and register state;
   MOVEM and data-register shift/rotate must consume their decoded/pre-state
   operands; and `TRAP #n` must use its vector cost, not the static opcode
   value. They must not charge the static opcode value after the path has been
   chosen.
3. Charge every native/HLE span through the same API and the same units.
   Generated basic blocks must use their executed path cost, including loop
   iterations and dynamic helpers. A native-only or interpreter-only clock is
   not acceptable.
4. Preserve deadline overshoot. If an instruction or native span crosses a
   deadline, record the excess before requesting the pending IRQ. Schedule the
   next deadline from the prior hardware phase minus that excess, not from the
   late instruction boundary.
5. Set the existing pending state at the first safe completed-instruction
   boundary and retain mask/stack/return semantics. While level 6 is masked,
   continue deadline advancement without inventing a queue of extra IRQ frames.
6. Rescale or replace every legacy direct `$AC` mutation, including idle
   clamps, boot/test setup, native block charges, explicit `$025110` yield
   checks, and pacing paths. A mixed instruction-unit/cycle-unit state is
   invalid.

## Workspace and compatibility constraints

The existing `$0700` block is active harness, gate, counter, scheduler, and
diagnostic state. `$0724` is a transpiler hit counter, and `$0734/$0736/$073A/
$073C/$073E` are live production or diagnostic gates; none may be repurposed.
The PC ring occupies `$0400-$05FF`, and the SA-1 stack descends from `$07FF`.

The staged diagnostic currently uses BW-RAM `$40:4000-$4019`, outside both the
mapped arcade work-RAM window and the SA-1 IRAM/native stacks. It was selected
by static-reference audit, but it is not yet a production allocation: a runtime
canary and sustained fresh-run ownership proof are still required. `$0680+`
remains only a discarded IRAM candidate, not a live workspace.

Old save states contain only the old instruction-unit `$AC` and no high word,
fractional phase, or overshoot. They cannot prove the new timer. Focused old
states may be used for forensic comparisons only after explicitly seeding all
new timer state; fresh power-on is required for acceptance.

Changing native gates after a state load is also invalid when the serialized
SA-1 PC is already executing an escape handler: the gate controls only future
dispatches, not the handler that will resume. The current ordinary tick-14,743
checkpoint resumes at `$92:DB8C` inside the native game-tick handler. The
trace harness now refuses that late mutation and retains the check at
`build/trace-stage3-gameplay-native-off-current-5c7e-safe14743-v2-rejected/rejected-gate-mutation.json`.
This is a harness guard, not a change to the prepared native-off states used
by the existing three-way regressions. New native-off timing captures must set
their gates before the checkpoint boundary is saved.

`build/validation-virtual-irq-timer-math-current-f369-v1.json` is a green
pure-arithmetic regression for this proposed representation. It proves 5,743
reloads contain exactly 50 extra two-cycle units and checks that an instruction
crossing a deadline carries its overshoot into the next hardware-phase reload.
It is intentionally not ROM evidence.

## Staged implementation record — unaccepted

The dirty workspace now contains an opt-in interpreter clock plus one bounded
native `$025110` diagnostic ledger, not a candidate repair.
`tools/gen_m68k_cpu000_static_cycles.py` generated the source-authenticated
64 KiB static CPU-000 table
`src/m68k_cpu000_static_cycles.bin` (SHA-256
`201cf148abf22ef763a55c6c086cc0eade0afb1f7185727d086f7b00a814914b`).
`src/vtime.pasm` uses it only when `VTIME=1`. The normal ROM pack now restores
the legacy per-fetch countdown and debug body in both bank-$00 views, so it
executes no VTIME runtime call; the packer byte-asserts and conditionally
patches the entry, charge, and finish gateways only in the diagnostic image.

The retained current diagnostic is
`build/interp-vtime-native-ledger-diagnostic-v2.sfc`, SHA-256
`590f1dfba2b1969be538439371cccf1556510ba8b24ae443d81c9c3ae8c8aff3`.
Its fresh 12-frame neutral liveness/ownership probe is green at
`build/validate-vtime-native-ledger-liveness-v2/summary.json`, including the
native-ledger workspace fields. The older v4 JSL/RTL fetch-gateway result and
its 115/120-frame timeout remain historical; neither is rate evidence.

That shallow liveness gate is insufficient for boot promotion. The current
player-ledger diagnostic `68c9…`, with gameplay native escapes disabled to
isolate its interpreter clock, fails a fresh one-credit controller sequence
before gameplay at
`build/validate-vtime-esc9-nativeoff-fresh3000-v1/summary.json`: after the
normal 5,248-frame cold-boot wait and eight real Select pulses it remains on
the SA-1 boot screen with `$F01C62=0`, no halt, and a retained failure state.
This is VTIME hardware-boundary/timing-or-boot alignment evidence, not an
arcade/SNES gameplay differential or a single-rule diagnosis, but it rejects
the diagnostic clock before Stage-3 or production promotion.

The matched gameplay-native-on control is independently red at
`build/validate-vtime-esc9-nativeon-fresh3000-v1/summary.json`: it has the
same zero-credit failure at the same 5,248-frame pre-coin boundary and the
same boot-screen PNG SHA-256
`9a4b3a5208749e4ec6e1d969e7bd8fea03b95632988ddae5217b255698ebaf55` as the
native-off run. Both retain their own pre-game failure state. A freshly
launched exact MAME 0.287 session, driven through its boot-aware one-credit
path, reaches gameplay at reported frame 1,952 and retains
`build/mame-vtime-boot-oracle-v1/states/superman/fresh-original-booted-before-vtime-comparison.sta`.
This is a boot/readiness control, not a same-PC MAME/SNES lockstep: the VTIME
images never reach a gameplay PC to compare.

The chunked fresh VTIME timer probe
`build/probe-vtime-esc9-boot-clock-v4/summary.json` distinguishes no timer
progress from an unusably slow virtual clock. With ordinary native gates left
enabled, it advances exactly 5,248 real video frames, retires 862,681
interpreter instructions, and moves phase 50 to 2,700—53 observed virtual
deadlines at 50 two-cycle units each—without a wrap, halt, or deadline-due
flag. It is still in the arcade boot RAM-test path (`$003F7C` to `$003FEE`),
not title. That is about 99 real video frames per observed virtual deadline,
where the original cadence is one deadline per video frame. The paired
one-frame forensic probes from the native-off and native-on failure states,
`build/probe-vtime-esc9-nativeoff-boot-failure-v1.json` and
`build/probe-vtime-esc9-nativeon-boot-failure-v1.json`, agree at virtual
`$003FF6 → $003FEE`, opcode `$66F6`, phase 2,700, remaining 5,177 → 4,499
two-cycle units, `$00AC=$7000`, `$00AA=1`, no game tick, and no active native
ledger block. Thus the rejected design has a functioning interpreter timer but
does not have a hardware-rate/common-clock implementation. The legacy
accelerator/pacing `$AC` domain remains mixed with VTIME, and no isolated `$AC`
or native-escape tweak is a safe repair. These experiments do not alter the
active ordinary `5c7e…` ROM.

The newer explicit interpreter-only pack is also rejected as a boot-rate
diagnostic, not promoted. Its byte-minimal flag image is
`build/interp-vtime-interpreter-only-escapes-off-diagnostic-v1.sfc` (SHA-256
`0ee4e331ce65bc8cbfa999ef75f20f654080a4a2ad063601c60a9b05d0452bd8`). It
does not clear `$071A/$073A` until after the VTIME magic/valid state is live;
the early clear power-on values are therefore not treated as switch evidence.
The fresh neutral framewise run at
`build/validate-vtime-interpreter-only-liveness-5500-framewise-v3/summary.json`
is explicitly **inconclusive** at its 180-second host budget: it advances from
emulator frame 137 to 3,173, reaches interpreter step 785,106, has no halt,
but remains at virtual PC `$003FFA` with game tick zero and VTIME magic/valid
still zero. Its retained PNG is the SA-1 ``ARCADE BOOT IN PROGRESS`` screen,
and its saved state is forensic only. Consequently it proves neither the
post-task native-gate switch nor a common clock, and it is not a gameplay,
MAME differential, rate, Stage-3, or fresh-ROM acceptance result. The
one-frame transport and atomic host-progress changes in
`tools/validate_vtime_liveness.py` prevent a slow experiment from losing its
last completed frame; `tools/test_vtime_liveness_chunking.py` guards that
property. This adds cold-boot hardware-rate evidence but does not change the
active `5c7e…` ROM or the required common-clock design.

The subsequent interpreter-only image which also packs the still-unwired
native-parent/interpreter-child helper is independently rejected by the actual
fresh one-credit controller path. The image is
`build/interp-vtime-interpreter-only-native-handoff-v1.sfc` (SHA-256
`598f0acc255ee703188caab39e44b0475f87f23311fc82a2e0c41128c1af1d91`). Its
fresh power-on report at
`build/validate-vtime-interpreter-only-native-handoff-fresh-prompt-v1/summary.json`
records one real Select edge, no state load, and no runtime game-memory write.
At video frame 5,407 task mask is 3 and halt is zero, but credits remain zero;
the prompt screenshot has 775 black right-wedge pixels, zero artwork-gray
underlay pixels, and 156 lower-right nonblack pixels. The retained
`one-credit-prompt.mss` is nonresumable forensic evidence. The expected-red
result is guarded by
`tools/test_vtime_interpreter_only_native_handoff_prompt.py`. It does not
prove that the deferred native-gate switch ran, nor does it reach a
MAME-comparable gameplay PC; it is not a native-off/native-on comparison,
IRQ/order result, Stage-3 result, or renderer regression in active `5c7e…`.

The live `$02429C` Stage-3 coroutine root now has a source-authenticated
future-ledger inventory at
`build/audit-stage3-2429c-charge-blocks-current-5c7e-v4.json`, guarded by
`tools/test_stage3_2429c_charge_blocks.py`. It reduces the original CPU-000
root to 78 instructions / 35 basic blocks / 520 static two-cycle units when
each block is counted once. All 14 path-sensitive instructions are terminal
Bcc/DBcc, so the existing post-block CCR/Dn rule is applicable. Its eleven
JSR/BSR/indirect child handoff sites are enumerated and still unadmitted. The
eight direct child entries include non-terminal MOVEM work in `$023342`,
`$023E34`, and `$0235E0`, plus immediate shift work in `$02443A`; only
`$025110` already has a compatible deferred block ledger. They must receive
explicit owner/return handoffs and their own exact adjustments before the root
can be charged. The current route classification is five native-entry calls,
five interpreter xlat misses (the three `$0243E8` calls plus `$02443A` and
`$0244D4`), and one dynamic indirect A0 dispatch; only the native-entry edges
can retain a shared native owner. This is a read-only
ledger prerequisite, not an enabled VTIME seam, native-on rate result, or
tick-14,746 repair.

The next cross-bank prerequisite is now present only as an **unwired** opt-in
diagnostic helper at `$F2:FE40`: `vtime_native_handoff_to_interpreter` flushes
the one deferred block owned by either the `$025110` or player ledger before a
native parent exposes an interpreter-child PC. It clears the native owner only
when no virtual deadline crosses; on a deadline it retains the caller-owned
PC/stack policy and clears only the pending block. An unknown owner invalidates
VTIME rather than silently mixing ledgers. The assembled layout and BW-RAM
long stores are pinned by `tools/test_vtime_native_handoff.py`; its first
diagnostic image is
`build/interp-vtime-native-handoff-diagnostic-v1.sfc` (SHA-256
`ace8098e2fd74b739cc735c01e60b0c25c9a05fba9ff1e06e28fe92ab8533792`). No
escape calls the helper yet, so this is a construction/packing regression only:
it has no route reachability, timing, IRQ, rate, Stage-3, or fresh-boot result,
and the active `5c7e…` ROM remains unchanged.

A deliberately too-early 24-frame fresh power-on smoke of that image is red at
`build/validate-vtime-native-handoff-liveness-v1/summary.json`: it advances
frames 138--162 and retires 5,605 interpreter steps without a halt, but VTIME
magic/valid remains zero because the documented post-self-test gate has not
opened. This neither tests the unwired helper nor establishes boot readiness;
it prevents treating a pre-arm observation as VTIME liveness.

The helper itself has now been executed synthetically in Nexen at
`build/validate-vtime-native-handoff-runtime-v1/summary.json` and is guarded
by `tools/test_validate_vtime_native_handoff_runtime.py`. From retained
pre-call states it flushes owner 3 by 14 two-cycle units and owner 9 by 10,
clears the deferred/current/owner fields before the final RTL, and makes an
unknown owner return to the interpreter loop with `VT_VALID=0` while retaining
the bad owner tag for diagnosis. Those states and the temporary unknown-owner
stack return are retained. This proves only the helper's isolated instruction
sequence; no organic escape reaches it, so it is not a native route, MAME,
IRQ, gameplay, Stage-3, rate, or fresh-ROM result.

The emitted-source companion inventory
`build/audit-stage3-2429c-handoff-protocol-current-5c7e-v1.json`, guarded by
`tools/test_stage3_2429c_handoff_protocol.py`, closes a critical ownership
ambiguity before wiring that helper. `$02429C` currently has zero local charge
calls. Its first original child site is a guarded fast arm that represents the
three `$023342/$023E34/$0235E0` callees; after that are four direct-native
transfers and six `ojmp_hook` transfers, each with a distinct existing return
protocol. Every one bypasses a parent-owner flush today. Thus a root ledger
must flush before all ten emitted child transfers, acquire the successor's
owner only after that flush, retain the caller's existing `$00FA`/logical
`$0242BE` return state on a deadline, and either ledger the fused triple or
route it elsewhere. This is a read-only blocker proof, not root ledger wiring,
an IRQ recovery, or a rate result.

`tools/gen_vtime_esc5_charge_table.py` now makes the root's unconsumed
ordinal-indexed metadata concrete at
`build/gen-vtime-esc5-charge-table-current-5c7e-v1.json`: 35 costs, 35 start
PCs, 35 terminal opcodes, and the 14 dynamic-terminal ordinals. The generator
is guarded by `tools/test_vtime_esc5_charge_table.py`. It deliberately has no
native return-address index because `$02429C` has no charge calls yet, and it
is not packed or read by any VTIME helper. The table is a prerequisite for a
future source transformation, not evidence of one.

The guarded three-callee fusion now has a separate exact-MAME span reduction at
`build/validate-mame-2429c-empty-fusion-current-f369-v1.json`, guarded by
`tools/test_mame_2429c_empty_fusion.py`. All four retained canonical empty
paths run from `$023342` to `$0242B2` in exactly 33 instructions / 798 cycles
(399 two-cycle units), with no IRQ inside the span. An opaque future fusion may
bulk-charge that amount only after proving no deadline can cross; otherwise it
must leave the fusion before `$023342` for a boundary-capable path. This is not
coverage of a nonempty arm, a native fusion implementation, or a timer fix.

The exact-MAME component reducer
`build/validate-mame-2429c-native-child-timing-current-f369-v1.json`, guarded
by `tools/test_mame_2429c_native_child_timing.py`, now checks 124 observed
dynamic instructions in the four direct native child bodies. It has zero
mismatches for 24 MOVEM.L records, 56 Bcc outcomes, and 44 DBcc outcomes. The
four dynamic PCs `$02360C/$023618/$023660/$025A0E` are absent from the retained
trace and remain explicit ledger gaps. This is bounded original-MAME input for
the fused/direct-child work, not a proof that the native fusion, its return
protocol, the interpreter children, or a common clock is correct.

A second exact original-MAME 0.287 power-on capture extends the same
controller movie across ticks 14,720--14,860:
`build/mame-2429c-irq-phase-current-f369-wide-v1/summary.json`. It contains
70,436 read-only trace events and 141 root entries. The child reducer finds
4,371 matching dynamic records, and the root reducer finds no timing mismatch,
but the previously unobserved child PCs `$02360C/$023618/$023660/$025A0E` and
ten root dynamic PCs still never execute. The artifact guard is
`tools/test_mame_2429c_wide_coverage.py`. This strengthens the requirement for
targeted distinct-arm oracle fixtures; it neither admits bulk charging nor
proves an SNES handoff, virtual IRQ repair, gameplay, or rate.

The same test also pins the post-divergence MAME-only continuation through
tick 15,000 at
`build/mame-2429c-irq-phase-current-f369-postdivergence-v1/summary.json`.
Despite 140 more root visits, it adds no dynamic root/child arm and preserves
all 14 gaps. The current controller movie therefore cannot replace deliberate
distinct-arm original-MAME fixtures. There is no corresponding SNES claim
after its retained tick-14,841 divergence.

The retained exact MAME 0.287 trace now has a narrowed `$02429C` branch
oracle at `build/validate-mame-2429c-branch-timing-current-f369-v2.json`.
All 48 observed root Bcc/DBcc executions agree with the predicted original
control flow and 10/12/14-cycle outcomes (four root PCs: `$0242A2`, `$0242C8`,
`$0242E6`, `$0243E0`). Ten of the fourteen root dynamic PCs are unobserved in
that trace and remain an explicit coverage gap. This is original-code MAME
evidence for a bounded subset, not an enabled SNES ledger, child-route proof,
or virtual-IRQ repair.

The fixture gap is now closed at the bounded-root level, without changing the
clock acceptance boundary. The fourth controlled arm is deliberately active
but gives `$02360C` its fall-through outcome so `$023618` executes, and gives
the root state byte the value 1 before the later comparison so `$02437E`
falls through and `$024388` executes. All four retained fixtures first pass
the active `a976…` exact MAME/native-off/native-on function differential,
12/12, at `build/validate-2429c-distinct-arm-isolated-a976-pinned-v2.jsonl`.
That comparison includes D/A registers, CCR/X/mask, 16 KiB mapped work RAM,
and the explicit return/stack-residue contract; it masks unrelated IRQ6 only
within this bounded handler.

The one-shot exact-MAME debugger tracer
`tools/trace_2429c_mame_fixture_cycles.py` then records the original body up
to a validation-only terminal Trap-fetch NOP. The four traces under
`build/mame-2429c-fixture-cycles-original-v2` have zero branch/child timing
prediction failures. Their union observes all 14 root dynamic branch/DBcc PCs
and all 19 dynamic PCs in the direct native children. The joined source and
artifact regression is
`build/validate-mame-2429c-fixture-cycle-coverage-a976-v1.json` plus
`tools/test_mame_2429c_fixture_cycle_coverage.py`. Its green result means only
that the bounded path-cost inventory is complete: it does not admit a root
owner, a fused-child policy, a parent flush, a due-IRQ unwind,
interpreter-child ownership, the remaining accelerated boundaries, or an
unmasked IRQ/rate claim.

The current active `5c7e…` root also passes its exact function-local oracle at
`build/validate-2429c-current-5c7e-live-v1.jsonl`: three fresh-lineage organic
entries (ticks 14,741--14,743) × native `(0,0)`, `(1,0)`, and `(1,1)` routes
are all green against original MAME 0.287 for D/A, CCR/mask, mapped work RAM,
and audited return residue. The `$025110` call preserves logical `$0242BE`;
the other calls retain their explicit private-continuation residues. This
deliberately IRQ-masked/no-deadline fixture proves semantic handoff only. It
does not allow a parent clock charge, live IRQ conclusion, rate claim, or
fresh-boot Stage-3 acceptance.

A controlled distinct-arm pass isolated a separate native semantic problem
before any clock work: `$02429C`'s inactive object record and `$0259CA`'s
inactive scan record execute `TST.B` before a terminating DBRA, but their
native byte-read branches had not published NZVC. The byte-minimal `a976…`
active repair fixes those two paths and is green 9/9 against exact
MAME/native-off/native-on at
`build/validate-2429c-distinct-arm-isolated-a976-pinned-v1.jsonl`. Its fresh
power-on replay is green through tick 10,000 and its one-credit HUD/art check
is green. This is a local native/HLE CCR repair, not an all-mode tick-14,746
clock repair: it has not reached the Stage-3 window, the controlled fixtures
mask IRQs, and it does not measure Stage-3 rate. The dirty-source `b758…`
image remains rejected; `tools/test_2429c_tstb_ccr_regression.py` is the
narrow guard for the source seam and isolated evidence.

The source inventory now makes that mixed domain executable rather than
implicit. `build/audit-vtime-legacy-ac-writers-current-5c7e-v5.json` finds 26
direct `$AC` writers in the current diagnostic source: two selected `$025110`
seams, two selected player seams, and one selected diagnostic `$0818` release
seam are intercepted, while 11 remain unmigrated (nine native-charge, one CE4
renderer residue, and one `$0818` idle-scheduler write). Two additional writes
are one-countdown virtual-due delivery bridges, three are diagnostic countdown
quarantines, and three are inactive disabled-mode compatibility writes.
`tools/test_vtime_legacy_ac_writers.py` guards the inventory and is green only
because it confirms promotion is blocked. Every active path must move to a
common, path-sensitive cycle API before a VTIME repair can be considered.

The corresponding accelerated-boundary inventory is
`build/audit-vtime-accelerated-boundaries-current-5c7e-v3.json`. It makes the
other mixed-clock route explicit: the current source still has six loop
collapses, scheduler scan/switch/select shortcuts, `$0818` idle pacing,
`$02429C`, and CE4 outside a common clock. It also records that `$025110` and
the six Stage-3 player entries are only selected diagnostic ledgers. Its 13
uncovered boundaries deliberately keep promotion blocked. Of the retained
Stage-3 trace's 65 entry labels, 58 are unadmitted pending an exact
charge-route proof; continuation/end labels are deliberately not asserted to
be independently uncharged;
`tools/test_vtime_accelerated_boundaries.py` rejects a future silent narrowing
of that boundary set. The inventory additionally binds each family to its
required repair shape: loop collapses must split at a virtual deadline or
fallback before it, scheduler/native/renderer work must use a decoded
path-sensitive block ledger with a pre-next-block unwind, and `$0818` must
advance the common phase from its observed video epoch rather than write the
legacy counter. This is a source/trace inventory, not exhaustive
generated-escape reachability or a timing result.

The native-charge inventory is machine-checked rather than inferred from the
six legacy helper names. Its current artifact,
`build/audit-native-charge-blocks-25110-current-v3.json`, has 226 return sites,
545 original instructions, 3,064 static two-cycle units, and 179 dynamic
terminal branch/loop blocks. The generator rejects any non-terminal or
unsupported dynamic instruction before emitting the sparse table.

`build/validation-mame-25110-deferred-charge-current-v2.json` is green against
the exact retained MAME trace: post-block CCR and post-DBcc Dn state predict
all 4,320 complete block totals, including 4,234 dynamic terminal executions.
The forced one-unit pre-failure state caught a real 65816 JSR `return-PC−1`
table-key error; the corrected native-deadline wiring is green at
`build/validate-vtime-25110-due-path-v7/summary.json`. The active-clock
function-local MAME/native-off/native-on fixture is green 2/2 at tick 10,155
in `build/validate-25110-vtime-native-ledger-exact-v2.json`. It seeds a
synthetic no-deadline timer state, so it proves local registers, CCR/X, stack
return, and mapped RAM only—not hardware IRQ phase.

The current production-window inventory
`build/trace-fresh-14743-one-update-native-paths-current-9dcc-v1/trace.json`
shows why that ledger cannot yet repair the real clock: one exact Stage-3
update enters native `$025110` and the Stage-3 player paths `$013282`,
`$013314`, `$01337E`, `$0133EA`, `$013468`, and `$013538`. The diagnostic
currently charges only `$025110`; its remaining native paths still use the
legacy instruction-unit `$AC` accounting. The source must not enable this
partial clock in production or infer timing from one scalar charge.

That earlier narrow inventory is superseded for the current ROM by the
all-entry trace at
`build/trace-stage3-active-native-current-5c7e-safe14743-v1.json/trace.json`.
It observes 65 entry-labelled native seams and 279 hits in one update,
including callable entries and continuation/end seams for the six player
bodies, `$025110`, CE4, `$02429C`, scheduler switch-in/out, object helpers,
and callback bridges. The promotion guard
`build/audit-stage3-vtime-coverage-current-5c7e-v1.json` is intentionally
green only because it finds the partial ledger incomplete: the `$025110`
ledger does not charge all six player entries, CE4, `$02429C`, or either task
switch. `tools/test_stage3_vtime_coverage.py` makes that exclusion a focused
regression. A player-only table extension would therefore still be an unsafe
partial clock, not the required root repair.

`build/audit-stage3-native-charge-helpers-current-5c7e-v2.json` links that
same active-entry trace to the existing legacy instruction-count helper
families. It finds 100 `$92` entry-labelled seam hits, one `$98` hit, and 13
`$99` hits in banks with no direct per-block helper, while `$94/$97/$9F`
entry-labelled seams use three different helper conventions. The audit is
deliberately weaker than a
reachability proof—having a helper in a source bank does not prove a traced
entry hits it or that its debit is the correct cycle cost—but it proves a
`$025110`-only conversion cannot become a common clock. Its static regression
is `tools/test_native_charge_helpers.py`.

The current-lineage non-pausing CE4 split at
`build/profile-stage3-ce4-current-5c7e-safe14743-v1.json` prevents narrowing
the rate diagnosis to the renderer alone: it records 66,386.5 CE4 SA-1
cycles/update (16 calls, including 12 fast 2×2 calls) across two hooked spans
whose mean is 3,303,291.5 cycles. The trace crosses the known failing window
and is not an fps result, but it is sufficient to leave the shared virtual
clock/scheduler route ahead of a renderer-only change.

A narrower post-entry scheduler measurement keeps the same distinction clear.
`build/profile-stage3-swin-span-current-5c7e-safe14743-v2/results.json`
records 94 complete `$92:FB00-$92:FC9F` switch-in body spans over eight
checkpointed updates: 11.75 calls/update, 715.35 mean SA-1 cycles/call, and
8,405.375 cycles/update for that measured body. It ends after the known bad
boundary and excludes the fast RTE, switch-out, and selector paths, so it is
not a rate or scheduler-correctness result. It merely rules out this one
switch-in body as the dominant raw SA-1 cycle consumer while leaving its
virtual-clock semantics mandatory.

The one-per-update native `$02429C` bridge is now separately bounded at
`build/profile-stage3-2429c-pre25110-span-current-5c7e-safe14743-v1/results.json`.
From the loaded tick-14,741 state through tick 14,749 it records eight complete
`$99:85D3` to `$99:8621` spans, which include the nested `$025110` collision
call and average 97,734.125 SA-1 cycles. The checkpointed span ends before the
`$0242BE` continuation and crosses the known bad boundary, so it is not an
IRQ, MAME, or rate result. It nevertheless prevents treating that one bridge
or `$025110` alone as an explanation for the multi-million-cycle update spans.

A follow-up audit invalidated the timing conclusion that could be drawn from
the first current-source `VTIME=1` checkpoint experiment. In the original
diagnostic source, Poppy encoded `DEC VT_REMAIN_HI` as `CE 08 40` (16-bit
absolute `$4008`) because 65816 has no long `DEC`, so it decremented SA-1 IRAM
rather than the BW-RAM `$40:4008` timer high word. The same hazard applied to
every `STZ`/`INC`/`DEC` VTIME state mutation. Thus
`build/interp-vtime-stage3-9dcc-experiment-v1.sfc` (SHA-256
`2db6773cfbc705cfdff8622cf3891102fa44fc2f85935af9135500bfca1cc163`) and its
856-frame ROM-mismatched checkpoint stall are retained only as a failed,
addressing-broken diagnostic—not evidence that the partial `$025110` ledger
itself has reached a timing conclusion.

The corrected diagnostic uses explicit accumulator read/modify/long-store
sequences for every such field and is guarded by
`tools/test_vtime_long_state_writes.py`, which rejects both source-level
unencodable mutators and assembled IRAM aliases. Its opt-in image is
`build/interp-vtime-stage3-9dcc-experiment-v2.sfc` (SHA-256
`b55274a802ffde5a88e4f3559d05213ab44cf7eab1f07dcc9eaf901aa28ab37e`). A fresh
24-frame neutral liveness run is green at
`build/validate-vtime-stage3-9dcc-experiment-liveness-v3/summary.json`: it
requires an actual virtual-deadline reload, advancing fractional phase from
50 to 100 rather than merely seeing a nonzero timer workspace. The forensic,
all-native-off checkpoint probe
`build/probe-vtime-stage3-9dcc-all-off-long-store-v4` also observes the
initialized high word `$0001` decrement to `$0000` and a subsequent reload to
phase 50. Its ROM and state intentionally differ, so it is bookkeeping proof
only, not a Stage-3 three-way or fresh-lineage result.

The diagnostic build route is guarded separately from the ordinary pack:
`tools/test_vtime_build_mode_guard.py` requires `VTIME=1` to skip only the
normal disabled-pack assertion while `VTIME=0` continues to run it. The
earlier diagnostic image is `build/interp-vtime-current-5c7e-diagnostic-v3.sfc`
(`b55274a8…`). The active ordinary file is a restored preserved `5c7e…`
artifact. A later ordinary build from the dirty player-ledger source is the
unaccepted `18bbee7f…` image, so byte identity with `5c7e…` must not be
claimed. Old ordinary-ROM save states are not valid evidence for either
diagnostic image and must not be migrated for timing conclusions.

Even with that concrete timer-state repair, the production-window inventory
still proves the diagnostic charges only `$025110` while several active player
and renderer HLE paths bypass the common clock. It must not be promoted or
used to infer rate, IRQ recovery, or gameplay correctness until every active
native/HLE span is charged through the same representation.

The first concrete extension audit is retained at
`build/audit-stage3-player-charge-blocks-current-5c7e-v1.json`. It proves the
six active `$9F` player handlers have 83 assembled `esc9_ac_charge` sites that
map one-to-one to 238 decoded original instructions and 83 basic blocks. Four
non-terminal immediate shifts add eight two-cycle units and can be folded into
a generated block baseline; the remaining Bcc/DBcc outcomes require deferred
post-block charging. The audit deliberately classifies BSR/BRA and
BTST/BCLR/BSET as static rather than generic `b*` branches. This is inventory
and regression evidence (`tools/test_stage3_player_charge_blocks.py`), not a
common-clock implementation or a timing fix.

`tools/gen_vtime_esc9_charge_table.py` now turns that verified inventory into
player-ledger metadata, retained at
`build/gen-vtime-esc9-charge-table-current-5c7e-v1.json`: 83 block records,
37 terminal dynamic branch/loop records, and a `$BA00-$FC72` sparse return-PC
map. The ordinary ROM does not pack or execute this data. The later opt-in
player diagnostic does, but only for its six handlers: it is
`build/interp-vtime-current-5c7e-esc9-ledger-v2.sfc`, SHA-256
`68c9bccc94ed79be173bfc342fa4f7b5f6583199e8484997fef620a83ff82175`.
It uses a `$40:401A` owner tag so the player and `$025110` ledgers cannot mix,
routes all 83 checked charge sites and 15 checked OJMP/interpreter-bridge/ORS
tails only with `VTIME=1`, and keeps the normal `esc9_ac_charge` routes in an
ordinary pack. `tools/test_vtime_esc9_charge_table.py` prevents table shape or
range drift. This is explicitly not a partial promotion.

The new diagnostic has three narrow green proofs: fresh 24-frame liveness at
`build/validate-vtime-esc9-ledger-liveness-v2/summary.json`; a real
`$0126EA`-to-`$013282` first-block forced-deadline unwind at
`build/validate-vtime-esc9-ledger-due-v5/summary.json`; and the shared finish
path through the pack-injected OJMP handoff gateway at
`build/validate-vtime-esc9-finish-gateway-v1/summary.json`. The original
version of the first test used the wrong 65816 stack slot for the generated
JSR residue; its retained red v2 report caught that defect before this green
replacement. The forced exit test enters the gateway directly and proves no
organic callout route. Correspondingly, the six retained real `$013282`
fixtures in `build/validate-vtime-esc9-ledger-handoff-due-v1*` did not reach
the OJMP handoff in their bounded window. That is a negative route-selection
result, not evidence that a missing handoff is correct or a timing fix.

Even with this extension, the all-entry trace still contains CE4, `$02429C`,
task-switch, object, callback, and other native/HLE spans outside both ledger
families. The profile-aware audit
`build/audit-stage3-vtime-coverage-player-ledger-current-5c7e-v1.json`
confirms that the seven admitted paths are charged, while required `$02429C`,
CE4, switch-in, and switch-out remain uncovered; its green result means
promotion is blocked. No player diagnostic result establishes a common clock,
task-frame recovery at tick 14,746, a usable Stage-3 rate, fresh gameplay, or
acceptance.

No result here supplies a native/HLE common clock, general multiply/divide
model, exact tick-14,746 three-way recovery, Stage 3 rate, or fresh gameplay
acceptance. The retained `cd4a6a93…` ordinary pack failed to reach its prompt
by video frame 5,407 because it still executed the disabled consumer JSL/RTL
at every interpreted instruction. The byte-asserted packing repair produces
`8b9adc92…`, whose independent fresh one-credit title/HUD check is green at
`build/validate-fresh-one-credit-prompt-vtime-default-8b9a-v1/summary.json`.
That proves only the normal-pack regression is gone; it is not VTIME or
Stage-3 timing acceptance.

The August 2 post-boot VTIME experiment is also rejected before gameplay. It
adds an opt-in-only `$0818` handoff that marks the common timer due after the
real S-CPU/NMI wait (`$99:FBA1 → $F2:B400`), while the restored active
`5c7e…` ROM retains the original `LDA #1 / STA $AC` bytes. The first image,
`build/interp-vtime-postboot-pacing-experiment-v1.sfc` (`9d3e7517…`), armed
when `$0734` became nonzero; that was too early. Its fresh one-credit control
is red at `build/validate-vtime-postboot-pacing-fresh-prompt-v1/summary.json`:
after the 5,248-frame boot window it is still at `$003B88` with no task mask,
despite VTIME magic/valid being set. The refined image,
`build/interp-vtime-taskmask-pacing-experiment-v2.sfc` (`0de24905…`), waits
for both `$0734` and nonzero `$F00002` task mask. Its corresponding fresh
control is also red at
`build/validate-vtime-taskmask-pacing-fresh-prompt-v2/summary.json`; the
retained post-window probe
`build/probe-vtime-taskmask-after5248-v2` proves VTIME never activated
(magic/valid zero) while the boot remains at `$003B88` with task mask zero.
This classifies the v2 failure as per-fetch cross-bank prepare/consume overhead
on its legacy fallback, not as a defect in the new `$0818` helper.
`tools/test_vtime_paced_release_pack.py` guards both
diagnostic bytes and the restored production bytes. Neither image is a
fresh-title, gameplay, timing, rate, or promotion result.

The third, local-prearm image is rejected too. It keeps the normal fetch JSR
and uses bank-$00 gateways until the established `$072E` post-self-test gate
opens, then calls the same `$F2` helpers. That image is
`build/interp-vtime-local-prearm-experiment-v3.sfc` (`1ea6ff85…`). Its fresh
one-credit control remains red at
`build/validate-vtime-local-prearm-fresh-prompt-v3/summary.json`: frame 5,407
has zero task mask and credits, though no interpreter halt. Loading only the
newly retained state for readback shows VTIME magic and valid are both zero at
that boundary (`build/probe-vtime-local-prearm-after5407-v3.json`), so the
post-self-test gate never opened. The top-of-iloop local JSR plus legacy branch
alone still prevents the self-test from reaching its sound-ring arm. This is a
throughput rejection, not early VTIME activation or a `$0818`-handoff defect.
`tools/test_vtime_local_prearm_pack.py` pins both diagnostic seams and the
unchanged active `5c7e…` bytes. It is not title, gameplay, timing, rate, or
promotion evidence.

The subsequent choke-gated experiment removes the pre-self-test helper cost by
reusing the ordinary bank-$00 `choke_tramp` only after `$072E` is armed. Its
first image, `build/interp-vtime-choke-gateway-experiment-v6.sfc`
(`d4bc57e6…`), reached the one-credit checkpoint with VTIME magic/valid set,
but the result was red. The retained
`build/probe-vtime-choke-gateway-after5407-v6.json` shows `VT_DUE=1` while the
emulated PC is the `$0818` self-refetch (`60FE`): native/HLE or hardware-paced
due can tail-enter `inext`, then loop_hook can bypass choke indefinitely. This
is a delivery-boundary defect in the diagnostic, not evidence against the
production HUD repair.

The corrected v7 image, `build/interp-vtime-choke-gateway-experiment-v7.sfc`
(`b28f72c7…`), writes `$AC=1` alongside every virtual native or `$0818` due.
That is a one-shot bridge into the existing iloop IRQ/reload/pending path, not
instruction-unit timing: `vtime_reload` consumes and clears `VT_DUE` before
the next virtual deadline. Its fresh one-credit title/HUD check is green at
`build/validate-vtime-choke-gateway-fresh-prompt-v7/summary.json`; the
following-frame probe at
`build/probe-vtime-choke-gateway-after5407-v7.json` retains magic/valid,
changes the virtual remainder, and has `VT_DUE=0`.
`tools/test_vtime_choke_gateway_pack.py` pins the no-preboot-cost relocation,
and `tools/test_vtime_due_bridge_pack.py` pins both native and `$0818` bridge
writes. The synthetic endpoint fixture
`build/validate-vtime-choke-due-bridge-v7/summary.json` is green: it retains a
forced `VT_DUE=1`/`$AC=1` prestate, reaches retained `$F2:8500`, clears the
due flag, advances phase once, and returns to iloop. This is a narrow
fresh-boot/due-delivery recovery only. The partial
ledgers, generic accelerated boundaries, exact Stage-3 three-way, rate, and
organic gameplay validations remain required before promotion.

A one-update Stage-3 stop-by-stop probe is retained at
`build/profile-stage3-tick-vtime-choke-v7-safe14743-v1/profile.json`. It loads
an ordinary pre-VTIME checkpoint, so it cannot seed or prove a valid fresh
diagnostic clock; it completed tick 14,744 without a halt but took 6,065,981
SA-1 cycles, 34 video frames, and 822 interpreted-fetch stops. This is neither
an uninterrupted rate measurement nor a timing comparison, but it rules out
using the fresh-title recovery as a Stage-3 usability claim.

## Required acceptance sequence

1. Validate the timer arithmetic itself against the retained MAME clock and
   branch/DBcc, MOVEM/shift, and exception reports, including fractional carry
   and overshoot cases. General multiply/divide operand coverage remains an
   explicit pre-acceptance requirement. The staged source has a bounded active
   no-deadline differential; its liveness and synthetic fixture probes are not
   hardware-phase evidence.
2. Run the same retained Stage-3 state in MAME, SNES native-off, and SNES
   native-on. Compare registers, CCR/X, stack/return state, work RAM, object
   and collision records, health/damage writes, task scheduling, and IRQ
   cadence through and past tick 14,746.
3. Re-run focused gameplay regressions: carried versus thrown crates, ordinary
   enemy damage, boss health/hits, title/credit/HUD, scrolling, and Stage-3
   hot/scroll handlers.
4. Run the controller movie organically from a fresh cold boot through the
   repaired point and farther. Do not call this a full playthrough unless it
   actually reaches the ending path.
5. Only after correctness is green, profile real production timing and compare
   against the project’s 30 game-tick/s and 358K SA-1-cycle/tick gates.
