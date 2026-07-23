#!/usr/bin/env python3
"""Attribute complete checkpoint ticks through the diagnostic 68K PC ring.

With ``PC_RING=1``, the interpreter writes every emulated MC68000 PC to the 128-entry
flight-recorder ring at SA-1 IRAM $0400-$05ff.  Nexen's non-pausing memory hooks attach the source
SA-1 cycle count to each byte write.  Reassembling those writes gives a chronological
68K fetch stream with exact cycle timestamps while the emulator runs uninterrupted.

This is deliberately a checkpoint profiler, not an FPS harness.  It neither changes
the ROM nor pokes the running game.  Its cycle deltas include the selected pacing
path, virtual IRQ, native escapes, interpreted instructions, renderer contention,
and the return to the real $0818/$00:F5A3 tick boundary.  Marked pacing-lab ROMs
must be opted into explicitly.  Use recovery_baseline.py for an end-to-end
production performance claim.  The normal production ROM NOPs both per-fetch calls,
and this profiler rejects that ROM explicitly.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_OUTPUT = ROOT / "build/tick-ring-profile"
IDLE_VSYNC_LAB_MARKER_OFFSET = 0x2CFF00
IDLE_VSYNC_LAB_MARKERS = {b"R5VSYNC1", b"R5VNMI01", b"R5VNMI02", b"R5VNMI03"}

CLAMP = 0x00F5A3
TAKE_IRQ = 0x00B404
# Keep this synchronized with src/escbank.sym.  The earlier $92:DC3B value
# became an interior instruction after the direct render-helper rewrites
# shortened the code before entry_3a92 by 185 bytes.
ENTRY_3A92 = 0x92DB82
SCHEDULER_HOOKS = {
    "entry_swo": 0x92FA00,
    "lh_sched": 0x00F9B2,
    "lhs_sel": 0x92FD00,
    "irq_none": 0x0080CB,
    "entry_swin": 0x92FB00,
    "op_rte": 0x00B3B8,
    "fast_rte": 0x9D8400,
}
SCHEDULER_SPANS = {
    "switch_out": ("entry_swo", "lh_sched"),
    "select": ("lhs_sel", "irq_none"),
    "switch_in": ("entry_swin", "fast_rte"),
}
TASK_HOOKS = {
    "task_c2f8": 0x92E2C7,
    "task_2658e": 0x92E566,
    "task_4542": 0x92E70E,
    "task_ce58": 0x92E787,
    "task_c172": 0x949D7E,
    "task_1d5f0": 0x97EC00,
    "task_1e7c0": 0x98AE00,
    "task_24bc2": 0x998000,
    "task_2429c": 0x9985D3,
    "task_c78e": 0x99A27D,
    "task_c7dc": 0x98FA80,
    "task_c846": 0x99AF6A,
    "task_c892": 0x98FD70,
    "task_11752": 0x99B539,
    "task_1177c": 0x99B68A,
    "task_46de": 0x99B74F,
    "task_75c": 0x99BF3D,
    "task_77a": 0x99C0BC,
    # Production round-start initial roots (packed from $99:C900).
    "task_c262": 0x99C900,
    "task_8d72": 0x99CC04,
    "task_c3f6": 0x99D254,
    "task_7c22": 0x99DCE0,
    "task_ce48": 0x99DDAE,
    "task_74b8": 0x9593CA,
    "task_74d4": 0x95948A,
    "task_74ec": 0x959537,
    # Sustained-gameplay object-update root, routed through xlat at $02A190.
    "task_2a190": 0x95B660,
    # Eight-slot callback/update coroutine resumed at $0175A0.
    "task_175a0": 0x95C103,
    # Completion of the nested object callback; deterministic state update.
    "task_1770e": 0x95C69D,
    # Object-state coroutine resumed after the $01C118 yield.
    "task_1c11a": 0x95D041,
}
BODY_HOOKS = {
    # Production renderer manifest at the real $0818 boundary.  These hooks
    # split producer work from the pacing handler's remaining boundary cost;
    # the compact-list scans are now large enough to affect the 30 Hz budget.
    "render_manifest_build": 0x9EDC00,
    "rmb_no_promote": 0x9EDC3B,
    "rmb_bg_select": 0x9EDC55,
    "render_bg_dirty_sparse": 0x9EE280,
    "rbds_fast": 0x9EE2A0,
    "rbds_done": 0x9EE300,
    "rmb_obj_begin": 0x9EDCDE,
    "rmb_obj_done": 0x9EDDF6,
    "render_manifest_build_end": 0x9EDE03,
    # Indexed-JSR table adapter for $00111A.  Keep this separate from the
    # native body span so the evidence proves that the newly routed callsite
    # actually reaches the adapter instead of merely observing some other
    # direct entry into the already-existing hand-native body.
    "entry_111at": 0x95A700,
    "e111at_return": 0x95AA0A,
    # Guarded late-combat island.  Separate adapter-state hooks prove whether
    # organic calls used the specialized state-zero path or interpreter
    # fallback; leaf hooks expose actual same-bank execution, not xlat intent.
    "entry_2a1b2": 0x95B600,
    "h2a1b2_fallback": 0x95B61E,
    "h2a1b2_state0": 0x95B62C,
    "h2a190_after_bsr": 0x95B68A,
    "entry_2a1d8t": 0x95B70A,
    "entry_2a53a": 0x95BB57,
    "entry_29128": 0x95BC71,
    "entry_29144": 0x95BD54,
    "entry_2a61e": 0x95BF80,
    # Genuine-return continuations inside the $0175A0 coroutine.  These prove
    # whether production returns dispatch through xlat or resume interpreted;
    # the latter is materially different when choosing the next native seam.
    "entry_175e8": 0x95C328,
    "entry_17612": 0x95C4CB,
    # Whole-call cost of the hot native two-stream sprite builder.  The
    # emulated-PC ring otherwise charges this body to its $0011xx return sites,
    # obscuring its aggregate cost.
    "entry_111a": 0x00EA79,
    "e11a_return": 0x00EBDF,
    # Guarded live $0020E8 tile-strip helper.  The old bank-$00 lowering owns
    # the real LINK/MOVEM frame; bank $9D replaces only its fully proved write
    # body and returns to the retained epilogue.
    "h20e8_fast": 0x9DA003,
    "h20e8_fallback": 0x9DA08D,
    "h20e8_hot": 0x9DA098,
    "producer_bg_append_range": 0x9DA540,
    "pbar_done": 0x9DA580,
    "h20e8_epilogue": 0x00F423,
    # Scheduler context-copy loop boundaries.  These isolate the mechanical
    # 15-register MOVEM save/restore cost from the surrounding scheduler work.
    "swo_movem_begin": 0x92FA12,
    "swo_movem_end": 0x92FA32,
    "swin_movem_begin": 0x92FBC4,
    # The fixed-offset restore finishes its final register store at $FC98;
    # ending there matches the old span's exclusion of the A7 update/JML tail.
    "swin_movem_end": 0x92FC98,
    "swin_diag_counter_begin": 0x92FB4F,
    "swin_diag_counter_end": 0x92FB58,
    "sels_diag_counter_begin": 0x92FD1A,
    "sels_diag_counter_end": 0x92FD23,
    # Table-dispatched object leaf added during the NMI-snapshot cadence pass.
    "entry_1f1c0t": 0x97FC60,
    # Callable palette-transition stepper.  Its direct jsr.l hook lives in
    # bank $92, but the body executes in bank $99; hook the real execution bank.
    "entry_96a": 0x99C200,
    "hle_96a": 0x95A000,
    "h96a_fast": 0x95A0F9,
    "h96a_generated_fallback": 0x95A1D6,
    # Guarded whole-root round-start tilemap initializer.  Hook the execution
    # bank as well as the bank-$99 wrapper so the organic fast/fallback choice
    # is explicit in retained transition evidence.
    "hle_c262": 0x95A300,
    "hc262_fast": 0x95A32F,
    "hc262_after_2742": 0x95A489,
    "hc262_generated_fallback": 0x95A4DF,
    "hc262_generated_finish": 0x95AF00,
    "entry_9ea": 0x99C500,
    "hle_9ea": 0x95A600,
    "h9ea_fast": 0x95A62C,
    "h9ea_done": 0x95A6F0,
    "h9ea_generated_fallback": 0x95A6F4,
    # Native $003A92 game-tick return boundaries (src/escbank.sym).  These
    # split the old catch-all $0708 attribution into the real helper/caller
    # spans without pausing or perturbing the running emulator.
    "br3a92_1": 0x92DC38,
    "br3a92_2": 0x92DC6A,
    "br3a92_3": 0x92DDB3,
    "br3a92_4": 0x92DDC0,
    "br3a92_5": 0x92DE13,
    "br3a92_6": 0x92DE2F,
    "br3a92_7": 0x92DE62,
    "br3a92_8": 0x92DF55,
    "br3a92_9": 0x92DF62,
    "br3a92_10": 0x92DF87,
    "br3a92_11": 0x92DF97,
    "br3a92_12": 0x92DFA4,
    "br3a92_13": 0x92DFB1,
    "gt_restore_begin": 0x92DFE9,
    "gt_restore_done": 0x92E00B,
    "entry_295at": 0x94A523,
    "entry_29b6t": 0x94A64B,
    "brc172_1": 0x94A31A,
    "brc172_2": 0x94A486,
    "entry_23864": 0x989800,
    "entry_23a0c": 0x98A200,
    "entry_ce4t": 0x948F7C,
    "hle_12b6c": 0x94E000,
    "hce4_entry": 0x94FA00,
    "hce4_guards_done": 0x94FB21,
    "hce4_outer_loop": 0x94FC13,
    "hce4_rows_done": 0x94FCDB,
    "hce4_exit_exhausted": 0x94FD04,
    "hce4_hot_done": 0x94FD11,
    "hce4_cold": 0x94FD71,
    # Fixed immutable-shape island in bank $95.  Per-shape entry hooks make
    # the CE4 aggregate actionable: the bank-$94 hot span alone cannot tell
    # whether a tick is paying for a small 4x4 sprite or a 6x6 shape.
    "hce4_shape_try": 0x95F400,
    "hce4_shape_3762e": 0x95F55D,
    "hce4_shape_341c2": 0x95F5CB,
    "hce4_shape_337f0": 0x95F675,
    "hce4_shape_33c0a": 0x95F743,
    "hce4_shape_428d6": 0x95F7E1,
    "hce4_shape_4288a": 0x95F8BB,
    "hce4_shape_finish": 0x95F992,
    "hce4_shape_end": 0x95F9C4,
    "hce4_shape_try_ext": 0x9DE400,
    "hce4_ext_guard_42a52": 0x9DE443,
    "hce4_ext_guard_42a9e": 0x9DE465,
    "hce4_ext_guard_33f6e": 0x9DE48A,
    "hce4_ext_guard_3762e_hidden": 0x9DE4AA,
    "hce4_ext_guard_ca8e": 0x9DE4C3,
    "hce4_ext_shape_33f6e": 0x9DE541,
    "hce4_ext_shape_ca8e": 0x9DE57F,
    "hce4_ext_shape_3762e_hidden": 0x9DE5A9,
    "hce4_ext_shape_42a": 0x9DE608,
    "hce4_ext_exhausted": 0x9DE710,
    "hce4_ext_fill": 0x9DE724,
    "hle_ce4_cont": 0x94FD7A,
    "br23a0c_1": 0x98A36D,
    "entry_23ae2": 0x98A900,
    "br23a0c_3": 0x98A6D3,
    "entry_23b52": 0x98AB00,
    "br23864_2": 0x989CF5,
    "br23864_3": 0x989D02,
    "br24bc2_1": 0x998036,
    "entry_28ddc": 0x99989B,
    "br24bc2_2": 0x99804F,
    "entry_24d98": 0x999D3B,
    "h24d98_hot_done": 0x999EF2,
    "h24d98_cold": 0x999F29,
    "br24bc2_3": 0x9980D3,
    "entry_23342": 0x988000,
    "br2429c_1": 0x9985F8,
    "entry_23e34": 0x998B59,
    "br2429c_2": 0x998605,
    "entry_235e0": 0x989200,
    "br2429c_3": 0x998613,
    "entry_25110": 0x978000,
    # The compact active-record pass lives in bank $95 even though the
    # retained generated continuation remains in bank $97.
    "25110_compact_entry": 0x95F000,
    "25110_compact_pairs": 0x95F064,
    "25110_compact_inner": 0x95F07D,
    "25110_overlap_x1": 0x95F0A6,
    "25110_overlap_x_done": 0x95F0C1,
    "25110_overlap_y1": 0x95F0DA,
    "25110_overlap_done": 0x95F0F5,
    "25110_x_right_overlap": 0x95F130,
    "25110_x_left": 0x95F16C,
    "25110_x_clear": 0x95F1CA,
    "25110_y_begin": 0x95F1EA,
    "25110_y_lower_overlap": 0x95F225,
    "25110_y_above": 0x95F261,
    "25110_y_clear": 0x95F2BF,
    "25110_meta": 0x95F2DF,
    "25110_meta_special": 0x95F301,
    "25110_meta_normal": 0x95F321,
    "25110_meta_second": 0x95F34A,
    "25110_pair_next": 0x95F373,
    "25110_compact_done": 0x95F38A,
    "25110_compact_fallback": 0x95F3A5,
    "25110_sgt": 0x95F3BA,
    "25110_slt": 0x95F3C6,
    "25110_sge": 0x95F3D0,
    "25110_stage2_fast_entry": 0x9D8000,
    "25110_stage2_fast_scan": 0x9D8065,
    "25110_stage2_fast_done": 0x9D8107,
    "25110_stage2_fast_fallback": 0x9D8120,
    "25110_stage2_fast_next": 0x9D80E7,
    "25110_stage2_overlap_entry": 0x9DE800,
    "25110_stage5_inactive_entry": 0x9D8200,
    "25110_stage5_inactive_scan": 0x9D8219,
    "25110_stage5_inactive_done": 0x9D822F,
    "25110_stage1_outer": 0x97804F,
    "25110_stage1_inner": 0x9780A9,
    "25110_stage1_inner_next": 0x978503,
    "25110_stage1_outer_next": 0x978518,
    "25110_stage2_outer": 0x978541,
    "25110_stage2_next": 0x9788FE,
    "25110_stage3_outer": 0x978C84,
    "25110_stage4_setup": 0x97903F,
    "25110_stage4_outer": 0x97905C,
    "25110_stage4_next": 0x97917D,
    "25110_stage5_select": 0x979197,
    "25110_stage5_wide": 0x9791BE,
    "25110_stage5_outer": 0x9791EB,
    "25110_stage5_inner_next": 0x979539,
    "25110_stage5_outer_next": 0x97954E,
    "br2429c_4": 0x998621,
    "entry_259ca": 0x9996AE,
    "br2429c_5": 0x99862E,
    # Current src/escbank4.sym after the guarded A0/A1/A2/A3/A5 work-RAM
    # specialization and corrected register-form BTST #11 masks.
    "br1e7c0_1": 0x98B9F6,
    "br1e7c0_2": 0x98BEE0,
    "br1e7c0_3": 0x98C0CA,
    "br1e7c0_4": 0x98D316,
    "br1e7c0_5": 0x98D45A,
    "br1e7c0_6": 0x98D4AD,
    "entry_1f1fe": 0x98F4FA,
    "br1e7c0_7": 0x98D4F4,
    "br1e7c0_8": 0x98D6DC,
    "entry_d96t": 0x98E348,
    "d96_hot_done": 0x98E660,
    "d96_cold": 0x98E8BC,
    "d96_main": 0x98E55D,
    "d96_after_outer": 0x98E62B,
    "d96_restore": 0x98E660,
    "br1e7c0_10": 0x98DDE7,
    "br1e7c0_11": 0x98E285,
    "br11752_5": 0x99B5B9,
    "br1177c_1": 0x99B69A,
    "br1177c_2": 0x99B6A8,
    "br1177c_3": 0x99B6B6,
    "br1177c_4": 0x99B6C4,
    "br1177c_5": 0x99B6D2,
    "br1177c_6": 0x99B714,
    "br1177c_7": 0x99B741,
    "entry_caf6": 0x97D800,
    "caf6_loop1": 0x97D9D1,
    "brcaf6_1": 0x97DB16,
    "caf6_loop2": 0x97DBB2,
    "brcaf6_2": 0x97DC30,
    "hcaf6_fast": 0x97DD03,
    "hcaf6_guard_done": 0x97DE2F,
    "hcaf6_loop": 0x97DE8D,
    "hcaf6_before_core": 0x97DF05,
    "hcaf6_after_core": 0x97DF08,
    "hcaf6_loop_check": 0x97DF0E,
    "hcaf6_fallback": 0x97DF2A,
    "hcaf6_32fca": 0x9DA200,
    "entry_cb9e_bank97": 0x97E800,
    "entry_2742t": 0x99DE0E,
    "entry_24a60t": 0x99E2C5,
    "entry_24a84t": 0x99E3B6,
    "entry_24920t": 0x99E4A7,
    "entry_24956t": 0x99E5CB,
    "brc262_1": 0x99CB29,
    "brc3f6_1": 0x99D3B4,
    "brc3f6_2": 0x99D409,
    "brc3f6_3": 0x99D45E,
    "brc3f6_4": 0x99D4A4,
    "brc3f6_5": 0x99D4EA,
    "brc3f6_6": 0x99D5E2,
    "brc3f6_7": 0x99D824,
    "brc3f6_8": 0x99D8FE,
    "brc3f6_9": 0x99DA66,
    "brc3f6_10": 0x99DABE,
    "brc3f6_11": 0x99DAF6,
    "entry_c8e0t": 0x958000,
    "brc8e0_1": 0x958127,
    "brc8e0_2": 0x958239,
    "brc8e0_3": 0x958379,
    "entry_c9a6t": 0x958444,
    "entry_c722t": 0x958673,
    "brc722_1": 0x958936,
    "entry_bba4t": 0x958958,
    "entry_c60et": 0x958AF8,
    "brc60e_1": 0x958DE9,
    "entry_c6bct": 0x958F54,
    "brc6bc_1": 0x9591DD,
    "entry_8d56t": 0x95931F,
    "entry_2d8at": 0x9599F0,
    "entry_f01b20t": 0x9597BD,
    # Guarded short OBJ transfer. These execution-bank hooks prove whether the
    # canonical DMA path or the interpreter fallback actually fired; the outer
    # br3a92_9->br3a92_11 span remains the whole-call cycle attribution.
    "hle_17b4": 0x959B00,
    "h17_fast": 0x959B46,
    "h17_interp_fallback": 0x959BE6,
    # Guarded descriptor copier.  The PC-ring attribution at emulated $0008FA
    # remains the whole-call cost; these execution-bank hooks prove whether the
    # organic calls used DMA or retained the pre-HLE generated body.
    "entry_8fat": 0x94AD98,
    "hle_8fa": 0x959D00,
    "h8fa_fast": 0x959DFE,
    "h8fa_cold_fallback": 0x959E6A,
    "br8d72_1": 0x99CF97,
    "br8d72_2": 0x99D03A,
    "br8d72_3": 0x99D0DD,
    "br8d72_4": 0x99D180,
}
BODY_SPANS = {
    "render_manifest_total": (
        "render_manifest_build",
        "rmb_obj_done",
    ),
    "render_manifest_promote": ("render_manifest_build", "rmb_no_promote"),
    "render_manifest_bg": ("rmb_bg_select", "rmb_obj_begin"),
    "render_manifest_obj": ("rmb_obj_begin", "rmb_obj_done"),
    "render_manifest_bg_scan": ("rmb_bg_select", "rmb_prepare_bg"),
    "render_manifest_bg_exact": ("rbds_fast", "rbds_done"),
    "render_prepare_total": ("rmb_prepare_bg", "rpb_success"),
    "render_prepare_c0bc": ("rpb_c0bc_prepared", "rpb_success"),
    "render_prepare_c0bc_dma": ("rpb_c0bc_rom_dma", "rpb_c0bc_rom_dma_end"),
    "render_prepare_collect": ("rmb_prepare_bg", "rpb_collect_done"),
    "render_prepare_sort": ("rpb_collect_done", "rpb_sort_done"),
    "render_prepare_slot_translate": ("rpb_sort_done", "rpb_hash_built"),
    "render_prepare_clear_map": ("rpb_hash_built", "rpb_clear_palette_map"),
    "render_prepare_clear_palette": ("rpb_clear_palette_map", "rpb_map_cell"),
    "render_prepare_map": ("rpb_map_cell", "rpb_success"),
    "render_map_code_load": ("rpb_map_cell", "rpb_map_nonempty"),
    "render_map_slot_translate": ("rpb_map_nonempty", "rpb_slot_ready"),
    "render_map_palette": ("rpb_slot_ready", "rpb_palette_ready"),
    "render_map_attributes": ("rpb_palette_ready", "rpb_flips_ready"),
    "render_map_coordinates": ("rpb_flips_ready", "rpb_left_nt"),
    "render_map_store": ("rpb_left_nt", "rpb_map_next"),
    "entry_111at_whole_call": ("entry_111at", "e111at_return"),
    "entry_111a_whole_call": ("entry_111a", "e11a_return"),
    "20e8_guarded_body": ("h20e8_fast", "h20e8_epilogue"),
    "producer_bg_append": ("producer_bg_append_range", "pbar_done"),
    "scheduler_switch_out_movem": ("swo_movem_begin", "swo_movem_end"),
    "scheduler_switch_in_movem": ("swin_movem_begin", "swin_movem_end"),
    "scheduler_switch_in_diag_counter": (
        "swin_diag_counter_begin",
        "swin_diag_counter_end",
    ),
    "scheduler_select_diag_counter": (
        "sels_diag_counter_begin",
        "sels_diag_counter_end",
    ),
    "game_tick_prologue_2bda": ("entry_3a92", "br3a92_1"),
    "game_tick_2bc2": ("br3a92_1", "br3a92_2"),
    "game_tick_input_2be2": ("br3a92_2", "br3a92_3"),
    "game_tick_3c36": ("br3a92_3", "br3a92_4"),
    "game_tick_branch_to_4178": ("br3a92_4", "br3a92_7"),
    "game_tick_scalar_8c2": ("br3a92_7", "br3a92_8"),
    "game_tick_26a0": ("br3a92_8", "br3a92_9"),
    "game_tick_158e": ("br3a92_9", "br3a92_10"),
    "game_tick_17b4": ("br3a92_9", "br3a92_11"),
    "game_tick_after_158e_2d8e": ("br3a92_10", "br3a92_12"),
    "game_tick_after_17b4_2d8e": ("br3a92_11", "br3a92_12"),
    "game_tick_5c32": ("br3a92_12", "br3a92_13"),
    "game_tick_to_restore": ("br3a92_13", "gt_restore_begin"),
    "game_tick_restore": ("gt_restore_begin", "gt_restore_done"),
    "c172_draw_29b6": ("entry_29b6t", "brc172_1"),
    "c172_draw_295a": ("entry_295at", "brc172_2"),
    "c262_call_2742t": ("entry_2742t", "brc262_1"),
    "c262_hle_final_2742t": ("entry_2742t", "hc262_after_2742"),
    "c0bc_hle_total": ("hc0bc_hle_fast", "hc0bc_hle_done"),
    "c0bc_hle_final_29b6": ("entry_29b6_fast", "hc0bc_hle_after_29b6"),
    "9ea_compact_hot_path": ("h9ea_fast", "h9ea_done"),
    "c3f6_call_24a60t": ("entry_24a60t", "brc3f6_1"),
    "c3f6_call_24a84t": ("entry_24a84t", "brc3f6_1"),
    "c3f6_call_24920t": ("entry_24920t", "brc3f6_2"),
    "c3f6_call_24956t_1": ("entry_24956t", "brc3f6_3"),
    "c3f6_call_24956t_2": ("entry_24956t", "brc3f6_4"),
    "c3f6_call_24956t_3": ("entry_24956t", "brc3f6_5"),
    "c3f6_call_c8e0t_first": ("entry_c8e0t", "brc3f6_6"),
    "c3f6_call_c722t": ("entry_c722t", "brc3f6_7"),
    "c3f6_call_bba4t": ("entry_bba4t", "brc3f6_8"),
    "c3f6_call_c8e0t_second": ("entry_c8e0t", "brc3f6_9"),
    "c3f6_call_c60et": ("entry_c60et", "brc3f6_10"),
    "c3f6_call_c6bct": ("entry_c6bct", "brc3f6_11"),
    "c8e0_call_c9a6t": ("entry_c9a6t", "brc8e0_1"),
    "8d72_sound_enqueue_1": ("entry_2d8at", "br8d72_1"),
    "8d72_sound_enqueue_2": ("entry_2d8at", "br8d72_2"),
    "8d72_sound_enqueue_3": ("entry_2d8at", "br8d72_3"),
    "8d72_sound_enqueue_4": ("entry_2d8at", "br8d72_4"),
    "task24bc2_call_23864": ("entry_23864", "br24bc2_1"),
    "task23864_call_23a0c": ("entry_23a0c", "br23864_2"),
    "task23a0c_call_ce4": ("entry_ce4t", "br23a0c_1"),
    "ce4_hot_path": ("hce4_entry", "hce4_hot_done"),
    "ce4_guards": ("hce4_entry", "hce4_guards_done"),
    "ce4_stack_and_setup": ("hce4_guards_done", "hce4_outer_loop"),
    "ce4_fill_and_flags": ("hce4_rows_done", "hce4_hot_done"),
    "ce4_exhaustion_flags": ("hce4_exit_exhausted", "hce4_hot_done"),
    "ce4_shape_3762e_body": ("hce4_shape_3762e", "hce4_shape_finish"),
    "ce4_shape_341c2_body": ("hce4_shape_341c2", "hce4_shape_finish"),
    "ce4_shape_337f0_body": ("hce4_shape_337f0", "hce4_shape_finish"),
    "ce4_shape_33c0a_body": ("hce4_shape_33c0a", "hce4_shape_finish"),
    "ce4_shape_428d6_body": ("hce4_shape_428d6", "hce4_shape_finish"),
    "ce4_shape_4288a_body": ("hce4_shape_4288a", "hce4_shape_finish"),
    "ce4_shape_finish": ("hce4_shape_finish", "hce4_hot_done"),
    "ce4_ext_33f6e_body": ("hce4_ext_shape_33f6e", "hce4_ext_exhausted"),
    "ce4_ext_ca8e_body": ("hce4_ext_shape_ca8e", "hce4_ext_exhausted"),
    "ce4_ext_3762e_body": ("hce4_ext_shape_3762e_hidden", "hce4_ext_fill"),
    "ce4_ext_42a_body": ("hce4_ext_shape_42a", "hce4_ext_exhausted"),
    "ce4_ext_exhausted_finish": ("hce4_ext_exhausted", "hce4_hot_done"),
    "ce4_ext_fill_finish": ("hce4_ext_fill", "hce4_hot_done"),
    "hle12b6c_ce4_tree": ("hle_12b6c", "hle_ce4_cont"),
    "task23a0c_call_23ae2": ("entry_23ae2", "br23a0c_3"),
    "task23864_call_23b52": ("entry_23b52", "br23864_3"),
    "task24bc2_call_28ddc": ("entry_28ddc", "br24bc2_2"),
    "task24bc2_call_24d98": ("entry_24d98", "br24bc2_3"),
    "task2429c_call_23342": ("entry_23342", "br2429c_1"),
    "task2429c_call_23e34": ("entry_23e34", "br2429c_2"),
    "task2429c_call_235e0": ("entry_235e0", "br2429c_3"),
    "task2429c_call_25110": ("entry_25110", "br2429c_4"),
    "25110_compact_scan": ("25110_compact_entry", "25110_compact_pairs"),
    "25110_compact_pairs_total": ("25110_compact_pairs", "25110_compact_done"),
    "25110_compact_total": ("25110_compact_entry", "25110_compact_done"),
    "25110_stage2_fast_total": ("25110_stage2_fast_entry", "25110_stage2_fast_done"),
    "25110_stage2_fast_scan_total": ("25110_stage2_fast_scan", "25110_stage2_fast_done"),
    "25110_stage2_overlap_body": ("25110_stage2_overlap_entry", "25110_stage2_fast_next"),
    "25110_stage5_inactive_total": ("25110_stage5_inactive_entry", "25110_stage5_inactive_done"),
    "25110_stage3_total": ("25110_stage3_outer", "25110_stage4_setup"),
    # Aggregate the expensive nested passes inside $25110.  The outer-loop
    # spans include their respective inner loops; the inner span is retained
    # separately to show how much of pass 1 is collision-pair work.
    "25110_stage1_outer_total": ("25110_stage1_outer", "25110_stage1_outer_next"),
    "25110_stage1_inner_total": ("25110_stage1_inner", "25110_stage1_inner_next"),
    "25110_stage2_outer_total": ("25110_stage2_outer", "25110_stage2_next"),
    "25110_stage4_outer_total": ("25110_stage4_outer", "25110_stage4_next"),
    "25110_stage5_outer_total": ("25110_stage5_outer", "25110_stage5_outer_next"),
    "task2429c_call_259ca": ("entry_259ca", "br2429c_5"),
    # Split the large generated $01E7C0 object/render task at its existing
    # native continuations.  These spans are measurement-only: they do not
    # alter the ROM, and the nested helper-call spans below remain available
    # to explain expensive segments.
    "task1e7c0_entry_to_br1": ("task_1e7c0", "br1e7c0_1"),
    "task1e7c0_br1_to_br2": ("br1e7c0_1", "br1e7c0_2"),
    "task1e7c0_br2_to_br3": ("br1e7c0_2", "br1e7c0_3"),
    "task1e7c0_br3_to_br4": ("br1e7c0_3", "br1e7c0_4"),
    "task1e7c0_br4_to_br5": ("br1e7c0_4", "br1e7c0_5"),
    "task1e7c0_br5_to_br6": ("br1e7c0_5", "br1e7c0_6"),
    "task1e7c0_br6_to_br7": ("br1e7c0_6", "br1e7c0_7"),
    "task1e7c0_br7_to_br8": ("br1e7c0_7", "br1e7c0_8"),
    "task1e7c0_br8_to_br10": ("br1e7c0_8", "br1e7c0_10"),
    "task1e7c0_br10_to_br11": ("br1e7c0_10", "br1e7c0_11"),
    "task1e7c0_call_1f1fe": ("entry_1f1fe", "br1e7c0_7"),
    "task1e7c0_call_d96_first": ("entry_d96t", "br1e7c0_10"),
    "task1e7c0_call_d96_second": ("entry_d96t", "br1e7c0_11"),
    # The guarded bank-$97 common-iteration helper can complete several
    # records, then hand the first unsupported record back to the generated
    # bank-$98 body.  Count complete hot records and bracket each callback so
    # the remaining $01E7C0 residency is not guessed from overlapping legacy
    # continuation spans.
    "h1e7c0_hot_record": ("h1e7c0_hot_loop", "h1e7c0_hot_decrement"),
    "h1e7c0_hot_callback": ("h1e7c0_hot_cb_ok", "h1e7c0_hot_return"),
    "h1e7c0_hot_post": ("h1e7c0_hot_post", "h1e7c0_hot_decrement"),
    "d96_prologue": ("entry_d96t", "d96_main"),
    "d96_main_loop": ("d96_main", "d96_after_outer"),
    "d96_post_loop": ("d96_after_outer", "d96_restore"),
    "d96_restore_return": ("d96_restore", "br1e7c0_10"),
    "11752_dispatch_12b6c": ("br11752_5", "task_1177c"),
    "1177c_call_12a92": ("task_1177c", "br1177c_1"),
    "1177c_call_cc44": ("br1177c_1", "br1177c_2"),
    "1177c_call_cc80": ("br1177c_2", "br1177c_3"),
    "1177c_call_12af6": ("br1177c_3", "br1177c_4"),
    "1177c_call_117b4": ("br1177c_4", "br1177c_5"),
    "1177c_tail_to_ccd8": ("br1177c_5", "br1177c_6"),
    "1177c_tail_to_caf6": ("br1177c_6", "br1177c_7"),
    "caf6_first_draw_loop": ("caf6_loop1", "brcaf6_1"),
    "caf6_second_draw_loop": ("caf6_loop2", "brcaf6_2"),
    "hcaf6_record": ("hcaf6_loop", "hcaf6_loop_check"),
    "hcaf6_cb9e_core": ("hcaf6_before_core", "hcaf6_after_core"),
    "hcaf6_whole_call": ("hcaf6_fast", "br1177c_7"),
    "hcaf6_const_body": ("hcaf6_const_list", "hcaf6_const_done"),
    "hcaf6_32fca_body": ("hcaf6_32fca", "hcaf6_32fca_done"),
}
RING_START = 0x000400
RING_END = 0x0005FF
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
EXPECTED_CLAMP_BYTES = bytes.fromhex("ee6007")
PC_RING_CALL_OFFSETS = (0x00EB, 0x80EB)
EXPECTED_PC_RING_CALL = bytes.fromhex("2081e2")
EXPECTED_GATES = {
    "loop": 1,
    "escape": 1,
    "choke": 1,
    "swin": 0xA55A,
    "select": 0x5EEC,
    "latch": 1,
}
GATE_ADDRS = {
    "loop": 0x072E,
    "escape": 0x071A,
    "choke": 0x073A,
    "swin": 0x073C,
    "select": 0x0736,
    "latch": 0x0768,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=7478)
    parser.add_argument("--intervals", type=int, default=4)
    parser.add_argument(
        "--warmup-ticks",
        type=int,
        default=0,
        help=(
            "Advance this many real $00:F5A3 tick boundaries after loading the "
            "checkpoint, before installing the high-volume attribution hooks."
        ),
    )
    parser.add_argument("--profile-timeout", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=0.05)
    parser.add_argument(
        "--input-buttons",
        type=lambda value: int(value, 0),
        help=(
            "Hold this Nexen port-0 button mask during attribution (for "
            "example 0x82 for Right+B)."
        ),
    )
    parser.add_argument(
        "--idle-vsync-lab",
        action="store_true",
        help="Explicitly allow a marked R5 pacing-lab ROM.",
    )
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help=(
            "Lab only: replace the checkpoint's $7F:8000-$AFFF video mirror "
            "with the selected ROM and initialize newly owned renderer metadata."
        ),
    )
    parser.add_argument(
        "--expected-task-mask",
        type=lambda value: int(value, 0),
        help=(
            "Require this exact raw little-endian task-mask value.  Without an "
            "override, require the established early-game $3Bxx class."
        ),
    )
    parser.add_argument(
        "--allow-gameplay-mask-evolution",
        action="store_true",
        help=(
            "Allow a nonzero gameplay task mask to change during attribution; "
            "the exact start/end values are still retained."
        ),
    )
    parser.add_argument(
        "--round-start-transition",
        action="store_true",
        help=(
            "Profile an organic post-Start checkpoint: require the attract "
            "$0300 task mask at entry and a $3Bxx gameplay mask at exit."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=80,
        help="Number of aggregate 68K PCs retained in the human-facing summary.",
    )
    parser.add_argument(
        "--deep-1e7c0",
        action="store_true",
        help=(
            "Hook every original-PC basic-block label in the generated $01E7C0 "
            "body. This is a high-volume diagnostic and does not alter the ROM."
        ),
    )
    parser.add_argument(
        "--deep-2429c",
        action="store_true",
        help=(
            "Hook every unique generated basic-block label in the native $02429C "
            "coroutine and its always-called $23342/$23E34/$235E0 helpers. This is "
            "a high-volume diagnostic and does not alter the ROM."
        ),
    )
    return parser.parse_args()


def add_deep_1e7c0_hooks() -> None:
    """Load generated $01E7C0 block addresses from the current bank-$98 symbols."""
    symbols = ROOT / "src/escbank4.sym"
    if not symbols.is_file():
        raise SystemExit(f"--deep-1e7c0 requires current symbols: {symbols}")
    found = 0
    for raw in symbols.read_text().splitlines():
        fields = raw.split()
        if len(fields) != 2 or not fields[1].startswith("L1e7c0_"):
            continue
        bank_text, offset_text = fields[0].split(":", 1)
        if bank_text != "00":
            raise SystemExit(f"unexpected escbank4 symbol bank in {raw!r}")
        BODY_HOOKS[fields[1]] = 0x980000 | int(offset_text, 16)
        found += 1
    if found < 100:
        raise SystemExit(
            f"--deep-1e7c0 found only {found} block labels; symbols are stale"
        )


def add_deep_2429c_hooks() -> None:
    """Load unique $02429C and always-called helper blocks from banks $98/$99."""
    occupied = set(BODY_HOOKS.values())
    found = 0
    sources = (
        (
            ROOT / "src/escbank4.sym",
            0x980000,
            ("L23342_", "Lf23342_", "br23342_", "L2335e_", "Lf2335e_", "br2335e_", "L235e0_", "Lf235e0_"),
        ),
        (
            ROOT / "src/escbank5.sym",
            0x990000,
            ("L2429c_", "Lf2429c_", "L23e34_", "Lf23e34_", "br23e34_", "L23e42_", "Lf23e42_", "br23e42_"),
        ),
    )
    for symbols, bank, prefixes in sources:
        if not symbols.is_file():
            raise SystemExit(f"--deep-2429c requires current symbols: {symbols}")
        for raw in symbols.read_text().splitlines():
            fields = raw.split()
            if len(fields) != 2 or not fields[1].startswith(prefixes):
                continue
            bank_text, offset_text = fields[0].split(":", 1)
            if bank_text != "00":
                raise SystemExit(f"unexpected escape-bank symbol bank in {raw!r}")
            address = bank | int(offset_text, 16)
            # Generated labels sometimes alias each other or an existing
            # call-return hook. One execution hook is sufficient and keeps the
            # timestamped path unambiguous.
            if address in occupied:
                continue
            BODY_HOOKS[fields[1]] = address
            occupied.add(address)
            found += 1
    if found < 100:
        raise SystemExit(
            f"--deep-2429c found only {found} unique block labels; symbols are stale"
        )


def load_symbol_offsets(path: Path) -> dict[str, int]:
    if not path.is_file():
        raise SystemExit(f"current layout symbols are required: {path}")
    offsets: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) != 2 or ":" not in fields[0]:
            continue
        bank_text, offset_text = fields[0].split(":", 1)
        if bank_text != "00":
            continue
        offsets[fields[1]] = int(offset_text, 16)
    return offsets


def refresh_current_layout_hooks() -> None:
    """Resolve optimization-sensitive hooks from current assembled symbols.

    X-aware $25110 regeneration changes generated instruction sizes. Original
    address labels remain semantically stable, but their SA-1 offsets do not.
    Resolve those hooks at startup so stale addresses cannot silently turn a
    performance gate into unrelated interior hooks.
    """

    sources = {
        "interp": (0x000000, load_symbol_offsets(ROOT / "src/interp.sym")),
        "esc2": (0x940000, load_symbol_offsets(ROOT / "src/escbank2.sym")),
        "esc4": (0x980000, load_symbol_offsets(ROOT / "src/escbank4.sym")),
        "esc3": (0x970000, load_symbol_offsets(ROOT / "src/escbank3.sym")),
        "esc5": (0x990000, load_symbol_offsets(ROOT / "src/escbank5.sym")),
        "esc6": (0x950000, load_symbol_offsets(ROOT / "src/escbank6.sym")),
        "esc7": (0x9D0000, load_symbol_offsets(ROOT / "src/escbank7.sym")),
        "esc8": (0x9E0000, load_symbol_offsets(ROOT / "src/escbank8.sym")),
    }

    def resolve(source: str, symbol: str) -> int:
        bank, offsets = sources[source]
        try:
            return bank | offsets[symbol]
        except KeyError as exc:
            raise SystemExit(
                f"current layout symbol {symbol} is missing from {source}"
            ) from exc

    dynamic = {
        # The producer-side render manifest is still evolving while the 30 Hz
        # transition spikes are being removed.  Resolve every phase boundary
        # from the current bank-$9E symbols: stale interior addresses can fire
        # once per scan iteration and turn a real one-shot span into nonsense.
        "render_manifest_build": ("esc8", "render_manifest_build"),
        "rmb_no_promote": ("esc8", "rmb_no_promote"),
        "rmb_bg_select": ("esc8", "rmb_bg_select"),
        "render_bg_dirty_sparse": ("esc8", "render_bg_dirty_sparse"),
        "rbds_fast": ("esc8", "rbds_fast"),
        "rbds_done": ("esc8", "rbds_done"),
        "rmb_obj_begin": ("esc8", "rmb_obj_begin"),
        "rmb_obj_done": ("esc8", "rmb_obj_done"),
        "render_manifest_build_end": ("esc8", "render_manifest_build_end"),
        "rmb_prepare_bg": ("esc8", "rmb_prepare_bg"),
        "rpb_prepare_dynamic": ("esc8", "rpb_prepare_dynamic"),
        "rpb_c0bc_prepared": ("esc8", "rpb_c0bc_prepared"),
        "rpb_c0bc_rom_dma": ("esc8", "rpb_c0bc_rom_dma"),
        "rpb_c0bc_rom_dma_end": ("esc8", "rpb_c0bc_rom_dma_end"),
        "rpb_collect_done": ("esc8", "rpb_collect_done"),
        "rpb_sort_done": ("esc8", "rpb_sort_done"),
        "rpb_hash_built": ("esc8", "rpb_hash_built"),
        "rpb_clear_palette_map": ("esc8", "rpb_clear_palette_map"),
        "rpb_map_cell": ("esc8", "rpb_map_cell"),
        "rpb_map_nonempty": ("esc8", "rpb_map_nonempty"),
        "rpb_slot_ready": ("esc8", "rpb_slot_ready"),
        "rpb_palette_ready": ("esc8", "rpb_palette_ready"),
        "rpb_flips_ready": ("esc8", "rpb_flips_ready"),
        "rpb_left_nt": ("esc8", "rpb_left_nt"),
        "rpb_map_next": ("esc8", "rpb_map_next"),
        "rpb_success": ("esc8", "rpb_success"),
        "hc0bc_hle_probe_gap": ("esc8", "hc0bc_hle_probe_gap"),
        "hc0bc_hle_probe_tail": ("esc8", "hc0bc_hle_probe_tail"),
        # Remaining occasional spawn-spike chain.  These hooks prove the
        # actual execution bank for every bank-$9E body and distinguish a
        # guarded fallback from a native hit in the same organic tick.
        "trap1_dispatch": ("interp", "trap1_dispatch"),
        "entry_466": ("esc8", "entry_466"),
        "h466_cold": ("esc8", "h466_cold"),
        "h466_hot": ("esc8", "h466_hot"),
        "entry_1d51a": ("esc8", "entry_1d51a"),
        "h1d51a_cold": ("esc8", "h1d51a_cold"),
        "h1d51a_hot": ("esc8", "h1d51a_hot"),
        "entry_1d53a": ("esc8", "entry_1d53a"),
        "h1d53a_cold": ("esc8", "h1d53a_cold"),
        "h1d53a_hot": ("esc8", "h1d53a_hot"),
        "entry_1d54c": ("esc8", "entry_1d54c"),
        "entry_24d28": ("esc8", "entry_24d28"),
        "h24d28_cold": ("esc8", "h24d28_cold"),
        "h24d28_hot": ("esc8", "h24d28_hot"),
        "entry_24d64": ("esc8", "entry_24d64"),
        "h24d64_cold": ("esc8", "h24d64_cold"),
        "h24d64_hot": ("esc8", "h24d64_hot"),
        "entry_1f4b0t": ("esc8", "entry_1f4b0t"),
        "h1f4b0t_cold": ("esc8", "h1f4b0t_cold"),
        "h1f4b0t_hot": ("esc8", "h1f4b0t_hot"),
        # Guarded collapse of the sixteen inactive $01C9AE object records.
        # The entry proves the fetch choke routed bank $01 correctly; the
        # hot/cold split distinguishes a semantic hit from an exact restart.
        "entry_1c9ae_empty": ("esc8", "entry_1c9ae_empty"),
        "h1c9ae_empty_hot": ("esc8", "h1c9ae_empty_hot"),
        "h1c9ae_empty_cold": ("esc8", "h1c9ae_empty_cold"),
        # Bounded one-shot round-transition initializer prefix.
        "entry_d7be": ("esc8", "entry_d7be"),
        "hd7be_hot": ("esc8", "hd7be_hot"),
        "hd7be_cold": ("esc8", "hd7be_cold"),
        "hd7be_cold_a5_low": ("esc8", "hd7be_cold_a5_low"),
        "hd7be_cold_a5_bank": ("esc8", "hd7be_cold_a5_bank"),
        "hd7be_cold_a7_bank": ("esc8", "hd7be_cold_a7_bank"),
        "hd7be_cold_a7_cross": ("esc8", "hd7be_cold_a7_cross"),
        "hd7be_cold_count": ("esc8", "hd7be_cold_count"),
        "hd7be_cold_ac": ("esc8", "hd7be_cold_ac"),
        "hd7be_cold_ac_lt16": ("esc8", "hd7be_cold_ac_lt16"),
        "hd7be_cold_ac_16_31": ("esc8", "hd7be_cold_ac_16_31"),
        "hd7be_cold_ac_32_47": ("esc8", "hd7be_cold_ac_32_47"),
        "hd7be_cold_ac_48_63": ("esc8", "hd7be_cold_ac_48_63"),
        "hd7be_cold_ac_64_83": ("esc8", "hd7be_cold_ac_64_83"),
        "entry_24cb6": ("esc5", "entry_24cb6"),
        # Rare $C172 signed-boundary callback path.  These distinguish the
        # new bounded helper from its generated fallback and prove whether the
        # organic spike actually reaches the direct $29B6 wrapper.
        "hc172_optional_hot": ("esc2", "hc172_optional_hot"),
        "hcx_after_29b6": ("esc2", "hcx_after_29b6"),
        "hcx_table_zero_abort": ("esc2", "hcx_table_zero_abort"),
        "hcx_table_zero_done": ("esc2", "hcx_table_zero_done"),
        "hc172_hot_finish": ("esc2", "hc172_hot_finish"),
        "hc172_cold": ("esc2", "hc172_cold"),
        # Actual execution-bank shortcuts and their guarded miss seams.
        "h23342_empty": ("esc4", "h23342_empty"),
        "h23342_empty_miss": ("esc4", "h23342_empty_miss"),
        "h23e34_empty": ("esc4", "h23e34_empty"),
        "h23e34_empty_miss": ("esc4", "h23e34_empty_miss"),
        "h235e0_empty": ("esc4", "h235e0_empty"),
        "h235e0_empty_miss": ("esc4", "h235e0_empty_miss"),
        "h2429c_empty_helpers": ("esc4", "h2429c_empty_helpers"),
        "h2429c_empty_helpers_hit": ("esc4", "h2429c_empty_helpers_hit"),
        "h2429c_empty_helpers_miss": ("esc4", "h2429c_empty_helpers_miss"),
        # Generated-record DBRA trampoline back into the common $01E7C0
        # helper.  Unlike h1e7c0_hot_reentry itself, this counts only actual
        # cold-record recoveries, not the helper's initial per-tick entry.
        "h1e7c0_generated_reentry": ("esc4", "h1e7c0_generated_reentry"),
        # Guarded compact collision pass and its X-aware alternate adapter.
        "25110_compact_entry": ("esc6", "h25110_stage1"),
        "25110_compact_pairs": ("esc6", "h25_pairs_begin"),
        "25110_compact_inner": ("esc6", "h25_inner"),
        "25110_overlap_x1": ("esc6", "h25_overlap_x1"),
        "25110_overlap_x_done": ("esc6", "h25_overlap_x_done"),
        "25110_overlap_y1": ("esc6", "h25_overlap_y1"),
        "25110_overlap_done": ("esc6", "h25_overlap_done"),
        "25110_x_right_overlap": ("esc6", "h25_x_right_overlap"),
        "25110_x_left": ("esc6", "h25_x_left"),
        "25110_x_clear": ("esc6", "h25_x_clear"),
        "25110_y_begin": ("esc6", "h25_y_begin"),
        "25110_y_lower_overlap": ("esc6", "h25_y_lower_overlap"),
        "25110_y_above": ("esc6", "h25_y_above"),
        "25110_y_clear": ("esc6", "h25_y_clear"),
        "25110_meta": ("esc6", "h25_meta"),
        "25110_meta_special": ("esc6", "h25_meta_special"),
        "25110_meta_normal": ("esc6", "h25_meta_normal"),
        "25110_meta_second": ("esc6", "h25_meta_second"),
        "25110_pair_next": ("esc6", "h25_pair_next"),
        "25110_compact_done": ("esc6", "h25_fast_done"),
        "25110_compact_fallback": ("esc6", "h25_fallback"),
        "25110_sgt": ("esc6", "h25_sgt"),
        "25110_slt": ("esc6", "h25_slt"),
        "25110_sge": ("esc6", "h25_sge"),
        "25110_xflag_stage1": ("esc6", "h25110_xflag_stage1"),
        # Stage-2 no-collision proof in the first full bank after the TAD blob.
        "25110_stage2_fast_entry": ("esc7", "h25110_stage2_try"),
        "25110_stage2_fast_scan": ("esc7", "h25s2_scan"),
        "25110_stage2_fast_done": ("esc7", "h25s2_fast_done"),
        "25110_stage2_fast_fallback": ("esc7", "h25s2_fallback"),
        "25110_stage2_fast_next": ("esc7", "h25s2_next"),
        "25110_stage2_overlap_entry": ("esc7", "h25110_stage2_overlap"),
        "25110_stage5_inactive_entry": ("esc7", "h25110_stage5_inactive_try"),
        "25110_stage5_inactive_scan": ("esc7", "h25s5_scan"),
        "25110_stage5_inactive_done": ("esc7", "h25s5_fast_done"),
        "h20e8_fast": ("esc7", "h20e8_fast"),
        "h20e8_fallback": ("esc7", "h20e8_fallback"),
        "h20e8_hot": ("esc7", "h20e8_hot"),
        "producer_bg_append_range": ("esc7", "producer_bg_append_range"),
        "pbar_done": ("esc7", "pbar_done"),
        # Yield-safe $00DA72/$00D8AC coroutine path.  The public DA72 root is
        # registered separately as a task hook below; these continuation,
        # callee, and sparse-router hooks prove that the organic resume stays
        # on the intended native path across the real $00D8B4 return.
        "xlat_da_dispatch": ("esc7", "xlat_da_dispatch"),
        "entry_d8b4": ("esc7", "entry_d8b4"),
        "entry_d9cct": ("esc7", "entry_d9cct"),
        "entry_dc44t": ("esc7", "entry_dc44t"),
        "entry_da44t": ("esc7", "entry_da44t"),
        "entry_da9et": ("esc7", "entry_da9et"),
        "entry_daf4t": ("esc7", "entry_daf4t"),
        "entry_dc2et": ("esc7", "entry_dc2et"),
        "hda72_hot": ("esc7", "hda72_hot"),
        "hda72_cold": ("esc7", "hda72_cold"),
        "hd8b4_hot": ("esc7", "hd8b4_hot"),
        "hd8b4_cold": ("esc7", "hd8b4_cold"),
        # One-shot attract-to-gameplay initializers in bank $9D's tail.
        "entry_24aa8t": ("esc7", "entry_24aa8t"),
        "h24aa8t_hot": ("esc7", "h24aa8t_hot"),
        "h24aa8t_cold": ("esc7", "h24aa8t_cold"),
        "entry_28f92t": ("esc7", "entry_28f92t"),
        "h28f92_hot": ("esc7", "h28f92_hot"),
        "h28f92_cold": ("esc7", "h28f92_cold"),
        "entry_91et": ("esc7", "entry_91et"),
        "h91et_hot": ("esc7", "h91et_hot"),
        "h91et_cold": ("esc7", "h91et_cold"),
        "entry_c0bc_generated": ("esc7", "entry_c0bc_generated"),
        "hc0bc_hot": ("esc7", "hc0bc_hot"),
        "hc0bc_cold": ("esc7", "hc0bc_cold"),
        "brc0bc_1": ("esc7", "brc0bc_1"),
        "entry_29b6_fast": ("esc7", "entry_29b6_fast"),
        "h29b6_fast": ("esc7", "h29b6_fast"),
        "h29b6_reject": ("esc7", "h29b6_reject"),
        "hle_c0bc": ("esc8", "hle_c0bc"),
        "hc0bc_hle_fast": ("esc8", "hc0bc_hle_fast"),
        "hc0bc_hle_reject": ("esc8", "hc0bc_hle_reject"),
        "hc0bc_hle_after_29b6": ("esc8", "hc0bc_hle_after_29b6"),
        "hc0bc_hle_done": ("esc8", "hc0bc_hle_done"),
        # Guarded whole-chain $CE58->$CD1A->four $0FB8 sprite clears.
        "hcd1a_fb8": ("esc7", "hcd1a_fb8"),
        "hcd1a_hot": ("esc7", "hcd1a_hot"),
        "hcd1a_cold": ("esc7", "hcd1a_cold"),
        "hcd1a_fb8_end": ("esc7", "hcd1a_fb8_end"),
        # Late-combat direct xlat arms.  The generated $02A86E return seams
        # expose every nested call without pausing the emulator, while the
        # $02AD4C hot/cold split proves its address guard decision.
        "entry_2ad4ct": ("esc7", "entry_2ad4ct"),
        "h2ad4c_hot": ("esc7", "h2ad4c_hot"),
        "h2ad4c_cold": ("esc7", "h2ad4c_cold"),
        "entry_2a86et": ("esc7", "entry_2a86et"),
        "br2a86e_1": ("esc7", "br2a86e_1"),
        "br2a86e_2": ("esc7", "br2a86e_2"),
        "br2a86e_3": ("esc7", "br2a86e_3"),
        "br2a86e_4": ("esc7", "br2a86e_4"),
        "br2a86e_5": ("esc7", "br2a86e_5"),
        "br2a86e_6": ("esc7", "br2a86e_6"),
        "br2a86e_7": ("esc7", "br2a86e_7"),
        "br2a86e_8": ("esc7", "br2a86e_8"),
        "br2a86e_9": ("esc7", "br2a86e_9"),
        # Guarded immutable-list CAF6 specialization.  Resolve both the old
        # bank-$97 guard seams and the new bank-$95 body after every build.
        "hcaf6_fast": ("esc3", "hcaf6_fast"),
        "hcaf6_guard_done": ("esc3", "hcaf6_guard_done"),
        "hcaf6_loop": ("esc3", "hcaf6_loop"),
        "hcaf6_before_core": ("esc3", "hcaf6_before_core"),
        "hcaf6_after_core": ("esc3", "hcaf6_after_core"),
        "hcaf6_loop_check": ("esc3", "hcaf6_loop_check"),
        "hcaf6_fallback": ("esc3", "hcaf6_fallback"),
        "hcaf6_const_list": ("esc6", "hcaf6_const_list"),
        "hcaf6_const_record": ("esc6", "hcaf6_const_record"),
        "hcaf6_const_done": ("esc6", "hcaf6_const_done"),
        "hcaf6_32fca": ("esc7", "hcaf6_32fca"),
        "hcaf6_32fca_record": ("esc7", "hcaf6_32fca_record"),
        "hcaf6_32fca_done": ("esc7", "hcaf6_32fca_done"),
        # Named semantic seams survive regenerated-label renumbering.
        "25110_stage1_outer": ("esc3", "h25110_stage1_outer"),
        "25110_stage1_inner": ("esc3", "h25110_stage1_inner"),
        "25110_stage1_inner_next": ("esc3", "h25110_stage1_inner_next"),
        "25110_stage1_outer_next": ("esc3", "h25110_stage1_outer_next"),
        "25110_stage2_outer": ("esc3", "h25110_stage2_outer"),
        "25110_stage2_next": ("esc3", "h25110_stage2_next"),
        "25110_stage3_outer": ("esc3", "h25110_stage3_outer"),
        "25110_stage4_setup": ("esc3", "h25110_stage4_setup"),
        "25110_stage4_outer": ("esc3", "h25110_stage4_outer"),
        "25110_stage4_next": ("esc3", "h25110_stage4_next"),
        "25110_stage5_select": ("esc3", "h25110_stage5_select"),
        "25110_stage5_wide": ("esc3", "h25110_stage5_wide"),
        "25110_stage5_outer": ("esc3", "h25110_stage5_outer"),
        "25110_stage5_inner_next": ("esc3", "h25110_stage5_inner_next"),
        "25110_stage5_outer_next": ("esc3", "h25110_stage5_outer_next"),
        # Current $01E7C0 common-record helper.  These names are hand-written
        # semantic seams and therefore safe to resolve from the assembled
        # symbols instead of pinning optimization-sensitive offsets here.
        "h1e7c0_hot": ("esc3", "h1e7c0_hot"),
        "h1e7c0_hot_cold": ("esc3", "h1e7c0_hot_cold"),
        "h1e7c0_hot_done": ("esc3", "h1e7c0_hot_done"),
        "h1e7c0_hot_loop": ("esc3", "h1e7c0_hot_loop"),
        "h1e7c0_hot_cb_ok": ("esc3", "h1e7c0_hot_cb_ok"),
        "h1e7c0_hot_return": ("esc3", "h1e7c0_hot_return"),
        "h1e7c0_hot_post": ("esc3", "h1e7c0_hot_post"),
        "h1e7c0_hot_decrement": ("esc3", "h1e7c0_hot_decrement"),
        "h1e7c0_hot_all_done": ("esc3", "h1e7c0_hot_all_done"),
    }
    BODY_HOOKS.update(
        {name: resolve(source, symbol) for name, (source, symbol) in dynamic.items()}
    )
    TASK_HOOKS["task_da72"] = resolve("esc7", "entry_da72")
    TASK_HOOKS["task_c0bc"] = resolve("esc7", "entry_c0bc")
    SCHEDULER_HOOKS["fast_rte"] = resolve("esc7", "hfast_rte_entry")
    # The guarded $01E7C0 helper has only a few dozen semantic labels.  Hook
    # all of them so a cold handoff records the last passed guard, making the
    # unsupported organic record shape directly actionable.  These are
    # non-pausing execution hooks and remain checkpoint attribution only.
    esc3_bank, esc3_offsets = sources["esc3"]
    occupied = set(BODY_HOOKS.values())
    for symbol, offset in esc3_offsets.items():
        if not symbol.startswith("h1e7c0_hot_"):
            continue
        address = esc3_bank | offset
        if address in occupied:
            continue
        BODY_HOOKS[symbol] = address
        occupied.add(address)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def le32(data: bytes) -> int:
    return le16(data) | (le16(data[2:]) << 16)


def configure_dotnet(executable: Path) -> None:
    root = "/home/chad/.dotnet10" if executable.name == "Nexen" else "/home/chad/.dotnet8"
    other = "/home/chad/.dotnet8" if executable.name == "Nexen" else "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = root
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (root, other)
    ]
    os.environ["PATH"] = ":".join([root, other, *current])


class Recorder:
    def __init__(self, output: Path) -> None:
        output.mkdir(parents=True, exist_ok=False)
        self._summary = (output / "profile.jsonl").open("x", encoding="utf-8")
        self._raw = (output / "hooks.jsonl").open("x", encoding="utf-8")

    def emit(self, event: str, **fields: Any) -> None:
        row = {"event": event, "time": time.time(), **fields}
        line = json.dumps(row, sort_keys=True)
        print(line, flush=True)
        self._summary.write(line + "\n")
        self._summary.flush()

    def raw(self, params: dict[str, Any], label: str) -> None:
        self._raw.write(json.dumps({"label": label, **params}, sort_keys=True) + "\n")

    def close(self) -> None:
        self._summary.close()
        self._raw.close()


def snapshot(m: McpSession) -> dict[str, Any]:
    def r16(address: int, memory_type: str = "Sa1Memory") -> int:
        return le16(m.read_memory(memory_type, address, 2))

    def r32(address: int, memory_type: str = "Sa1Memory") -> int:
        return le32(m.read_memory(memory_type, address, 4))

    def stack_state() -> dict[str, Any]:
        a5 = r32(0x0034) & 0xFFFFFF
        if not 0xF00000 <= a5 <= 0xF0FFFF:
            return {
                "a5": a5,
                "initialized": 0,
                "minimum_margin": None,
                "below_floor": [],
                "tasks": [],
            }
        base = a5 - 0xF00000
        floor_bytes = m.read_memory("snesMemory", 0xC10882, 16 * 4)
        tasks = []
        below_floor = []
        for index in range(16):
            floor = int.from_bytes(
                floor_bytes[index * 4 : index * 4 + 4], "big"
            )
            saved_sp = int.from_bytes(
                m.read_memory(
                    "snesMemory", 0x400000 + base + 0x0A + index * 4, 4
                ),
                "big",
            )
            if saved_sp == 0:
                continue
            descriptor = int.from_bytes(
                m.read_memory(
                    "snesMemory", 0x400000 + base + 0x4E + index * 4, 4
                ),
                "big",
            )
            task = {
                "index": index,
                "descriptor": descriptor,
                "saved_sp": saved_sp,
                "floor": floor,
                "margin": saved_sp - floor,
            }
            tasks.append(task)
            if task["margin"] < 0:
                below_floor.append(task)
        return {
            "a5": a5,
            "initialized": len(tasks),
            "minimum_margin": min(
                (task["margin"] for task in tasks), default=None
            ),
            "below_floor": below_floor,
            "tasks": tasks,
        }

    state = m.get_state()
    cpu = m.get_cpu_state("Sa1")
    return {
        "frame": int(state.get("frameCount", 0)),
        "tick": r16(0x0760),
        "pc68k": r32(0x0040) & 0xFFFFFF,
        "steps": r32(0x004A),
        "opcode": r16(0x0044),
        "halt": r16(0x004E),
        "ac": r16(0x00AC),
        "task_mask": r16(0x400002, "snesMemory"),
        "stack": stack_state(),
        "sound_ring_ptr": m.read_memory("snesMemory", 0x401C40, 4).hex(),
        "gates": {name: r16(address) for name, address in GATE_ADDRS.items()},
        "sa1_cycles": int(cpu.get("cycleCount", 0)),
        "sa1_pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
        "emulator_running": bool(state.get("isRunning", False)),
        "emulator_paused": bool(state.get("isPaused", False)),
    }


def require_production_state(
    label: str,
    state: dict[str, Any],
    expected_task_mask: int | None,
    transition_role: str | None = None,
    allow_gameplay_mask_evolution: bool = False,
) -> None:
    if state["gates"] != EXPECTED_GATES:
        raise RuntimeError(
            f"{label} gate mismatch: expected {EXPECTED_GATES}, got {state['gates']}"
        )
    if state["halt"] != 0:
        raise RuntimeError(f"{label} interpreter halted: $4E={state['halt']:#06x}")
    ring_pointer = int(state["sound_ring_ptr"], 16)
    if not 0x00F01C20 <= ring_pointer <= 0x00F01C40:
        raise RuntimeError(
            f"{label} sound ring pointer outside $F01C20-$F01C40: "
            f"{state['sound_ring_ptr']}"
        )
    if transition_role == "start" and state["task_mask"] != 0x0300:
        raise RuntimeError(
            f"{label} is not the post-Start attract task state: "
            f"task mask={state['task_mask']:#06x}"
        )
    if transition_role == "end" and state["task_mask"] >> 8 != 0x3B:
        raise RuntimeError(
            f"{label} did not reach the expected gameplay task class: "
            f"task mask={state['task_mask']:#06x}"
        )
    if (
        transition_role is None
        and expected_task_mask is None
        and not allow_gameplay_mask_evolution
        and state["task_mask"] >> 8 != 0x3B
    ):
        raise RuntimeError(
            f"{label} is not the expected gameplay task class: "
            f"task mask={state['task_mask']:#06x}"
        )
    if (
        transition_role is None
        and expected_task_mask is not None
        and state["task_mask"] != expected_task_mask
    ):
        raise RuntimeError(
            f"{label} task mask mismatch: expected {expected_task_mask:#06x}, "
            f"got {state['task_mask']:#06x}"
        )
    if (
        transition_role is None
        and allow_gameplay_mask_evolution
        and state["task_mask"] == 0
    ):
        raise RuntimeError(f"{label} has an empty gameplay task mask")
    stack = state["stack"]
    if stack["initialized"] == 0:
        raise RuntimeError(f"{label} has no initialized task stacks")
    if stack["below_floor"]:
        raise RuntimeError(
            f"{label} has saved task stacks below their floors: "
            f"{stack['below_floor']}"
        )


def hook_notifications(rows: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for row in rows:
        if row.get("method") == "notifications/mesen/hookFired":
            yield row.get("params", {})


def parse_ring_writes(
    writes: list[dict[str, Any]],
) -> tuple[list[dict[str, int]], int, int]:
    """Reassemble the four byte hooks emitted by each pair of 16-bit STAs.

    The SA-1 native stack can descend into the same $0400-$05FF IRAM range.
    Complete ring writes are four address-consecutive bytes emitted within a
    few cycles; an isolated write outside such a burst is unrelated hook noise,
    not a malformed ring record.  Nearby partial/interleaved bursts remain a
    hard integrity signal for the caller.
    """
    ordered = sorted(writes, key=lambda event: int(event["cycleCount"]))
    records: list[dict[str, int]] = []
    malformed = 0
    unrelated = 0
    index = 0
    while index + 3 < len(ordered):
        group = ordered[index : index + 4]
        address = int(group[0]["address"])
        expected = [address + offset for offset in range(4)]
        actual = [int(event["address"]) for event in group]
        if address % 4 == 0 and actual == expected:
            values = [int(event["value"]) & 0xFF for event in group]
            low = values[0] | (values[1] << 8)
            bank_word = values[2] | (values[3] << 8)
            records.append(
                {
                    "cycle": int(group[0]["cycleCount"]),
                    "frame": int(group[0].get("frame", 0)),
                    "ring_address": address,
                    "pc": ((bank_word & 0xFF) << 16) | low,
                    "bank_word": bank_word,
                }
            )
            index += 4
            continue
        cycle = int(ordered[index]["cycleCount"])
        near_previous = (
            index > 0
            and cycle - int(ordered[index - 1]["cycleCount"]) <= 64
        )
        near_next = (
            index + 1 < len(ordered)
            and int(ordered[index + 1]["cycleCount"]) - cycle <= 64
        )
        if near_previous or near_next:
            malformed += 1
        else:
            unrelated += 1
        index += 1
    while index < len(ordered):
        cycle = int(ordered[index]["cycleCount"])
        near_previous = (
            index > 0
            and cycle - int(ordered[index - 1]["cycleCount"]) <= 64
        )
        near_next = (
            index + 1 < len(ordered)
            and int(ordered[index + 1]["cycleCount"]) - cycle <= 64
        )
        if near_previous or near_next:
            malformed += 1
        else:
            unrelated += 1
        index += 1
    return records, malformed, unrelated


def stats(values: list[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def interval_rows(
    clamps: list[dict[str, Any]],
    phases: list[dict[str, Any]],
    pcs: list[dict[str, int]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(clamps, clamps[1:])):
        start = int(left["cycleCount"])
        end = int(right["cycleCount"])
        stream = [record for record in pcs if start < record["cycle"] < end]
        inside_phases = [
            event for event in phases if start < int(event["cycleCount"]) < end
        ]
        irqs = [event for event in inside_phases if event["label"] == "take_irq"]
        entries = [event for event in inside_phases if event["label"] == "entry_3a92"]
        irq = irqs[0] if irqs else None
        entry = entries[0] if entries else None

        def paired_spans(start_label: str, end_label: str) -> dict[str, Any]:
            durations: list[int] = []
            pending: int | None = None
            unmatched_starts = 0
            unmatched_ends = 0
            for event in sorted(inside_phases, key=lambda row: int(row["cycleCount"])):
                label = event["label"]
                cycle = int(event["cycleCount"])
                if label == start_label:
                    if pending is not None:
                        unmatched_starts += 1
                    pending = cycle
                elif label == end_label:
                    if pending is None:
                        unmatched_ends += 1
                    else:
                        durations.append(cycle - pending)
                        pending = None
            if pending is not None:
                unmatched_starts += 1
            return {
                "start": start_label,
                "end": end_label,
                "durations": durations,
                "stats": stats(durations),
                "unmatched_starts": unmatched_starts,
                "unmatched_ends": unmatched_ends,
            }

        scheduler_spans = {
            name: paired_spans(start_label, end_label)
            for name, (start_label, end_label) in SCHEDULER_SPANS.items()
        }
        body_spans = {
            name: paired_spans(start_label, end_label)
            for name, (start_label, end_label) in BODY_SPANS.items()
        }
        body_hook_fires = collections.Counter(
            event["label"]
            for event in inside_phases
            if event["label"] in BODY_HOOKS
        )

        # Each switch-in ends at the guarded fast-RTE helper, which either
        # dispatches a known native root or delegates to op_rte. Attribute the
        # native root only until
        # the next emulated-PC ring write; nested native helper hooks therefore
        # do not double-count the residency charged to the preceding $0796.
        task_dispatches: list[dict[str, Any]] = []
        task_labels = set(TASK_HOOKS)
        ordered_phases = sorted(inside_phases, key=lambda row: int(row["cycleCount"]))
        dispatch_origins = [
            event for event in ordered_phases if event["label"] == "fast_rte"
        ]
        for position, op_event in enumerate(dispatch_origins):
            op_cycle = int(op_event["cycleCount"])
            next_op_cycle = (
                int(dispatch_origins[position + 1]["cycleCount"])
                if position + 1 < len(dispatch_origins)
                else end
            )
            next_pc = next((record for record in stream if record["cycle"] > op_cycle), None)
            boundary = min(next_op_cycle, next_pc["cycle"] if next_pc else end)
            root = next(
                (
                    event
                    for event in ordered_phases
                    if op_cycle < int(event["cycleCount"]) < boundary
                    and event["label"] in task_labels
                ),
                None,
            )
            task_dispatches.append(
                {
                    "op_rte_cycle": op_cycle,
                    "task": root["label"] if root else "interpreted",
                    "task_entry_cycle": int(root["cycleCount"]) if root else None,
                    "dispatch_cycles": (
                        int(root["cycleCount"]) - op_cycle if root else None
                    ),
                    "next_pc": f"{next_pc['pc']:06X}" if next_pc else None,
                    "next_pc_cycle": next_pc["cycle"] if next_pc else None,
                    "native_to_next_pc_cycles": (
                        next_pc["cycle"] - int(root["cycleCount"])
                        if root and next_pc
                        else None
                    ),
                }
            )

        # ``--deep-1e7c0`` installs hooks for every generated original-PC
        # basic-block label.  Preserve their exact timestamped path from the
        # native task entry to the next emulated-PC fetch so a large native
        # residency can be decomposed without guessing from block hit counts.
        # Keep this absent in ordinary profiles: the trace is intentionally
        # verbose and exists for attribution only.
        deep_1e7c0_trace: list[dict[str, int | str]] = []
        if any(label.startswith("L1e7c0_") for label in BODY_HOOKS):
            dispatch = next(
                (
                    row
                    for row in task_dispatches
                    if row["task"] == "task_1e7c0"
                    and row["task_entry_cycle"] is not None
                    and row["next_pc_cycle"] is not None
                ),
                None,
            )
            if dispatch is not None:
                task_start = int(dispatch["task_entry_cycle"])
                task_end = int(dispatch["next_pc_cycle"])
                previous = task_start
                for event in ordered_phases:
                    cycle = int(event["cycleCount"])
                    if task_start <= cycle < task_end:
                        deep_1e7c0_trace.append(
                            {
                                "label": str(event["label"]),
                                "cycle_from_task": cycle - task_start,
                                "cycles_from_previous_hook": cycle - previous,
                            }
                        )
                        previous = cycle
                deep_1e7c0_trace.append(
                    {
                        "label": "next_pc",
                        "cycle_from_task": task_end - task_start,
                        "cycles_from_previous_hook": task_end - previous,
                    }
                )

        deep_2429c_trace: list[dict[str, int | str]] = []
        if any(
            label.startswith(("L2429c_", "Lf2429c_")) for label in BODY_HOOKS
        ):
            dispatch = next(
                (
                    row
                    for row in task_dispatches
                    if row["task"] == "task_2429c"
                    and row["task_entry_cycle"] is not None
                    and row["next_pc_cycle"] is not None
                ),
                None,
            )
            if dispatch is not None:
                task_start = int(dispatch["task_entry_cycle"])
                task_end = int(dispatch["next_pc_cycle"])
                previous = task_start
                for event in ordered_phases:
                    cycle = int(event["cycleCount"])
                    if task_start <= cycle < task_end:
                        deep_2429c_trace.append(
                            {
                                "label": str(event["label"]),
                                "cycle_from_task": cycle - task_start,
                                "cycles_from_previous_hook": cycle - previous,
                            }
                        )
                        previous = cycle
                deep_2429c_trace.append(
                    {
                        "label": "next_pc",
                        "cycle_from_task": task_end - task_start,
                        "cycles_from_previous_hook": task_end - previous,
                    }
                )

        attributed: list[dict[str, int]] = []
        for position, record in enumerate(stream):
            next_cycle = stream[position + 1]["cycle"] if position + 1 < len(stream) else end
            attributed.append({**record, "cycles_to_next_pc_or_clamp": next_cycle - record["cycle"]})

        by_pc_cycles: collections.Counter[int] = collections.Counter()
        by_pc_fires: collections.Counter[int] = collections.Counter()
        active_by_pc_cycles: collections.Counter[int] = collections.Counter()
        active_by_pc_fires: collections.Counter[int] = collections.Counter()
        for record in attributed:
            pc = record["pc"]
            cost = record["cycles_to_next_pc_or_clamp"]
            by_pc_cycles[pc] += cost
            by_pc_fires[pc] += 1
            if entry is not None:
                entry_cycle = int(entry["cycleCount"])
                next_cycle = record["cycle"] + cost
                active_cost = max(0, next_cycle - max(record["cycle"], entry_cycle))
            else:
                active_cost = 0
            if active_cost:
                # A native escape can begin after the triggering 68K PC was logged.
                # Charge only the overlap with entry_3a92..clamp, rather than dropping
                # that entire (often dominant) bridge span from the active ranking.
                active_by_pc_cycles[pc] += active_cost
                active_by_pc_fires[pc] += 1

        def ranked(
            cycles: collections.Counter[int], fires: collections.Counter[int]
        ) -> list[dict[str, int | str]]:
            return [
                {
                    "pc": f"{pc:06X}",
                    "cycles": cost,
                    "fires": fires[pc],
                    "mean_cycles_per_fire": cost // max(1, fires[pc]),
                }
                for pc, cost in cycles.most_common()
            ]

        rows.append(
            {
                "index": index,
                "start_cycle": start,
                "end_cycle": end,
                "total_cycles": end - start,
                "start_frame": int(left.get("frame", 0)),
                "end_frame": int(right.get("frame", 0)),
                "frame_delta": int(right.get("frame", 0)) - int(left.get("frame", 0)),
                "pc_fetches": len(stream),
                "unique_pcs": len(by_pc_cycles),
                "prefix_before_first_pc_cycles": stream[0]["cycle"] - start if stream else None,
                "irq_count": len(irqs),
                "entry_count": len(entries),
                "clamp_to_irq_cycles": int(irq["cycleCount"]) - start if irq else None,
                "irq_to_entry_cycles": (
                    int(entry["cycleCount"]) - int(irq["cycleCount"])
                    if irq and entry
                    else None
                ),
                "entry_to_clamp_cycles": end - int(entry["cycleCount"]) if entry else None,
                "scheduler_spans": scheduler_spans,
                "body_spans": body_spans,
                "body_hook_fires": dict(sorted(body_hook_fires.items())),
                **(
                    {"deep_1e7c0_trace": deep_1e7c0_trace}
                    if deep_1e7c0_trace
                    else {}
                ),
                **(
                    {"deep_2429c_trace": deep_2429c_trace}
                    if deep_2429c_trace
                    else {}
                ),
                "task_dispatches": task_dispatches,
                "all_pc_costs": ranked(by_pc_cycles, by_pc_fires),
                "active_pc_costs": ranked(active_by_pc_cycles, active_by_pc_fires),
            }
        )
    return rows


def aggregate(intervals: list[dict[str, Any]], top: int) -> dict[str, Any]:
    total_cycles: collections.Counter[str] = collections.Counter()
    total_fires: collections.Counter[str] = collections.Counter()
    active_cycles: collections.Counter[str] = collections.Counter()
    active_fires: collections.Counter[str] = collections.Counter()
    for interval in intervals:
        for row in interval["all_pc_costs"]:
            total_cycles[row["pc"]] += int(row["cycles"])
            total_fires[row["pc"]] += int(row["fires"])
        for row in interval["active_pc_costs"]:
            active_cycles[row["pc"]] += int(row["cycles"])
            active_fires[row["pc"]] += int(row["fires"])

    count = max(1, len(intervals))

    def ranked(
        cycles: collections.Counter[str], fires: collections.Counter[str]
    ) -> list[dict[str, float | int | str]]:
        return [
            {
                "pc": pc,
                "cycles_total": cost,
                "cycles_per_interval": cost / count,
                "fires_total": fires[pc],
                "fires_per_interval": fires[pc] / count,
                "mean_cycles_per_fire": cost / max(1, fires[pc]),
            }
            for pc, cost in cycles.most_common(top)
        ]

    def present(field: str) -> list[int]:
        return [int(row[field]) for row in intervals if row.get(field) is not None]

    scheduler_spans: dict[str, Any] = {}
    for name in SCHEDULER_SPANS:
        durations = [
            int(duration)
            for interval in intervals
            for duration in interval["scheduler_spans"][name]["durations"]
        ]
        scheduler_spans[name] = {
            "stats": stats(durations),
            "cycles_per_interval": sum(durations) / max(1, len(intervals)),
            "fires_per_interval": len(durations) / max(1, len(intervals)),
            "unmatched_starts": sum(
                int(interval["scheduler_spans"][name]["unmatched_starts"])
                for interval in intervals
            ),
            "unmatched_ends": sum(
                int(interval["scheduler_spans"][name]["unmatched_ends"])
                for interval in intervals
            ),
        }

    task_totals: dict[str, dict[str, Any]] = {}
    for task in sorted(
        {dispatch["task"] for interval in intervals for dispatch in interval["task_dispatches"]}
    ):
        rows = [
            dispatch
            for interval in intervals
            for dispatch in interval["task_dispatches"]
            if dispatch["task"] == task
        ]
        residencies = [
            int(row["native_to_next_pc_cycles"])
            for row in rows
            if row["native_to_next_pc_cycles"] is not None
        ]
        dispatch_costs = [
            int(row["dispatch_cycles"])
            for row in rows
            if row["dispatch_cycles"] is not None
        ]
        task_totals[task] = {
            "fires": len(rows),
            "fires_per_interval": len(rows) / max(1, len(intervals)),
            "native_to_next_pc": stats(residencies),
            "native_cycles_per_interval": sum(residencies) / max(1, len(intervals)),
            "dispatch": stats(dispatch_costs),
        }

    body_spans: dict[str, Any] = {}
    for name in BODY_SPANS:
        durations = [
            int(duration)
            for interval in intervals
            for duration in interval["body_spans"][name]["durations"]
        ]
        body_spans[name] = {
            "stats": stats(durations),
            "cycles_per_interval": sum(durations) / max(1, len(intervals)),
            "fires_per_interval": len(durations) / max(1, len(intervals)),
            "unmatched_starts": sum(
                int(interval["body_spans"][name]["unmatched_starts"])
                for interval in intervals
            ),
            "unmatched_ends": sum(
                int(interval["body_spans"][name]["unmatched_ends"])
                for interval in intervals
            ),
        }

    body_hook_fires = {
        label: {
            "total": sum(
                int(interval["body_hook_fires"].get(label, 0))
                for interval in intervals
            ),
            "per_interval": sum(
                int(interval["body_hook_fires"].get(label, 0))
                for interval in intervals
            )
            / max(1, len(intervals)),
        }
        for label in BODY_HOOKS
    }

    return {
        "scope": "checkpointed uninterrupted cycle attribution; not end-to-end fps",
        "intervals": len(intervals),
        "complete_phase_intervals": sum(
            1 for row in intervals if row["irq_count"] == 1 and row["entry_count"] == 1
        ),
        "total_cycles": stats(present("total_cycles")),
        "clamp_to_irq_cycles": stats(present("clamp_to_irq_cycles")),
        "irq_to_entry_cycles": stats(present("irq_to_entry_cycles")),
        "entry_to_clamp_cycles": stats(present("entry_to_clamp_cycles")),
        "pc_fetches": stats(present("pc_fetches")),
        "scheduler_spans": scheduler_spans,
        "task_dispatches": task_totals,
        "body_spans": body_spans,
        "body_hook_fires": body_hook_fires,
        "top_all_pc_costs": ranked(total_cycles, total_fires),
        "top_active_pc_costs": ranked(active_cycles, active_fires),
    }


def main() -> int:
    args = parse_args()
    refresh_current_layout_hooks()
    if args.deep_1e7c0:
        add_deep_1e7c0_hooks()
    if args.deep_2429c:
        add_deep_2429c_hooks()
    if args.intervals < 1:
        raise SystemExit("--intervals must be positive")
    if args.warmup_ticks < 0:
        raise SystemExit("--warmup-ticks cannot be negative")
    if args.profile_timeout <= 0:
        raise SystemExit("--profile-timeout must be positive")
    if args.poll_seconds <= 0 or args.poll_seconds > 1:
        raise SystemExit("--poll-seconds must be in (0, 1]")
    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.input_buttons is not None and not 0 <= args.input_buttons <= 0x0FFF:
        raise SystemExit("--input-buttons must be a 12-bit Nexen controller mask")
    if args.round_start_transition and args.expected_task_mask is not None:
        raise SystemExit(
            "--round-start-transition and --expected-task-mask are mutually exclusive"
        )
    if args.allow_gameplay_mask_evolution and args.expected_task_mask is not None:
        raise SystemExit(
            "--allow-gameplay-mask-evolution and --expected-task-mask are "
            "mutually exclusive"
        )

    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()
    for label, path in (("ROM", args.rom), ("state", args.state), ("Nexen", args.nexen)):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    rom = args.rom.read_bytes()
    if len(rom) != 4 * 1024 * 1024:
        raise SystemExit(f"expected a 4 MiB production ROM, got {len(rom)} bytes")
    testflag = int.from_bytes(rom[0x77E0:0x77E2], "little")
    if testflag != 0:
        raise SystemExit(f"TESTFLAG must be zero, got {testflag:#06x}")
    marker = rom[
        IDLE_VSYNC_LAB_MARKER_OFFSET : IDLE_VSYNC_LAB_MARKER_OFFSET + 8
    ]
    if args.idle_vsync_lab:
        if marker not in IDLE_VSYNC_LAB_MARKERS:
            raise SystemExit(
                "--idle-vsync-lab requires a marked R5VSYNC1/R5VNMI01/R5VNMI02/R5VNMI03 lab ROM"
            )
    elif marker in IDLE_VSYNC_LAB_MARKERS:
        raise SystemExit(
            "marked pacing-lab ROM requires the explicit --idle-vsync-lab flag"
        )
    if rom[0x75A3 : 0x75A6] != EXPECTED_CLAMP_BYTES:
        raise SystemExit(
            "real tick hook bytes mismatch at ROM $75A3: "
            f"{rom[0x75A3:0x75A6].hex()} != {EXPECTED_CLAMP_BYTES.hex()}"
        )
    for offset in PC_RING_CALL_OFFSETS:
        actual = rom[offset : offset + len(EXPECTED_PC_RING_CALL)]
        if actual != EXPECTED_PC_RING_CALL:
            raise SystemExit(
                "PC-ring attribution requires a diagnostic ROM built with "
                f"`PC_RING=1 bash tools/build_interp.sh`; file ${offset:06X} "
                f"is {actual.hex()}, expected {EXPECTED_PC_RING_CALL.hex()}"
            )

    configure_dotnet(args.nexen)
    log = Recorder(args.output)
    try:
        log.emit(
            "provenance",
            project_commit=git_value("rev-parse", "HEAD"),
            project_status=git_value("status", "--short").splitlines(),
            rom=str(args.rom),
            rom_sha256=sha256(args.rom),
            rom_size=args.rom.stat().st_size,
            state=str(args.state),
            state_sha256=sha256(args.state),
            nexen=str(args.nexen),
            nexen_sha256=sha256(args.nexen),
            testflag=testflag,
            idle_vsync_lab=args.idle_vsync_lab,
            idle_vsync_lab_marker=(
                marker.decode() if marker in IDLE_VSYNC_LAB_MARKERS else None
            ),
            expected_task_mask=(
                f"{args.expected_task_mask:#06x}"
                if args.expected_task_mask is not None
                else None
            ),
            allow_gameplay_mask_evolution=args.allow_gameplay_mask_evolution,
            round_start_transition=args.round_start_transition,
            input_buttons=args.input_buttons,
            input_transport=(
                "nexen_port0_manual_4016"
                if args.input_buttons is not None
                else None
            ),
            intervals_requested=args.intervals,
            warmup_ticks=args.warmup_ticks,
            hook_addresses={
                "clamp": f"{CLAMP:06X}",
                "take_irq": f"{TAKE_IRQ:06X}",
                "entry_3a92": f"{ENTRY_3A92:06X}",
                **{name: f"{address:06X}" for name, address in SCHEDULER_HOOKS.items()},
                **{name: f"{address:06X}" for name, address in TASK_HOOKS.items()},
                **{name: f"{address:06X}" for name, address in BODY_HOOKS.items()},
                "pc_ring": f"{RING_START:06X}-{RING_END:06X}",
            },
            runtime_pokes=(
                [
                    {
                        "kind": "checkpoint_lab_wram_video_mirror_refresh",
                        "address": "7F:8000-7F:AFFF",
                        "length": VIDEO_WRAM_LENGTH,
                        "sha256": hashlib.sha256(
                            rom[
                                VIDEO_FILE_BASE:
                                VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
                            ]
                        ).hexdigest(),
                    },
                    {
                        "kind": "checkpoint_lab_exact_bg_metadata_migration",
                        "addresses": ["41:014C", "41:014E", "7E:1F1E"],
                    },
                ]
                if args.refresh_video_mirror
                else []
            ),
            hooks_pause_cpu=False,
            evidence_scope=(
                "checkpointed mirror-refreshed renderer cycle attribution; not fps"
                if args.refresh_video_mirror
                else "checkpointed marked pacing-lab cycle attribution; not fps"
                if args.idle_vsync_lab
                else "checkpointed production round-start transition attribution; not fps"
                if args.round_start_transition
                else "checkpointed production cycle attribution; not fps"
            ),
        )
        with McpSession(
            rom=args.rom,
            mesen=args.nexen,
            cwd=ROOT,
            port=args.port,
            boot_wait=8.0,
            socket_timeout=max(120.0, args.profile_timeout),
            stderr_log=args.output / "nexen.stderr.log",
        ) as m:
            m.pause()
            m.load_state(args.state)
            m.pause()
            if args.refresh_video_mirror:
                rom_mirror = rom[
                    VIDEO_FILE_BASE:VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
                ]
                for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
                    chunk = rom_mirror[offset:offset + 0x1000]
                    m.write_memory(
                        "snesWorkRam", VIDEO_WRAM_OFFSET + offset, chunk.hex()
                    )
                observed_mirror = bytes(
                    m.read_memory(
                        "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
                    )
                )
                if observed_mirror != rom_mirror:
                    raise RuntimeError("production WRAM video mirror did not verify")
                frame_ack = le16(m.read_memory("Sa1Memory", 0x3302, 2))
                m.write_memory(
                    "snesWorkRam", 0x1F1E, frame_ack.to_bytes(2, "little").hex()
                )
                bg_dirty = le16(m.read_memory("snesMemory", 0x410140, 2))
                producer_status = 0xFFFF if bg_dirty else 0
                m.write_memory(
                    "snesMemory",
                    0x41014C,
                    producer_status.to_bytes(2, "little").hex(),
                )
                m.write_memory("snesMemory", 0x41014E, "0000")
            if args.input_buttons is not None:
                m.tool(
                    "set_input",
                    {"port": 0, "buttons": args.input_buttons, "hold": True},
                )
            if args.warmup_ticks:
                warmup_handle = m.add_exec_hook(CLAMP, cpu_type="Sa1")
                m.drain_notifications(timeout=0.05)
                warmup_started = time.monotonic()
                warmup_events = 0
                m.resume()
                while time.monotonic() - warmup_started < args.profile_timeout:
                    for params in hook_notifications(
                        m.drain_notifications(timeout=args.poll_seconds)
                    ):
                        if int(params.get("handle", -1)) == warmup_handle:
                            warmup_events += 1
                    if warmup_events >= args.warmup_ticks:
                        m.pause()
                        break
                    time.sleep(min(0.01, args.poll_seconds))
                else:
                    m.pause()
                    raise TimeoutError(
                        "tick-ring warmup timed out after "
                        f"{args.profile_timeout:.1f} seconds after "
                        f"{warmup_events}/{args.warmup_ticks} tick hooks"
                    )
                warmup_removed = m.remove_hook(warmup_handle)
                if not warmup_removed:
                    raise RuntimeError("failed to remove the warmup clamp hook")
                log.emit(
                    "warmup_finished",
                    requested_ticks=args.warmup_ticks,
                    observed_tick_hooks=warmup_events,
                    wall_seconds=time.monotonic() - warmup_started,
                )
            start_state = snapshot(m)
            require_production_state(
                "profile start",
                start_state,
                args.expected_task_mask,
                "start" if args.round_start_transition else None,
                args.allow_gameplay_mask_evolution,
            )
            log.emit("profile_start", **start_state)

            handles = {
                "pc_ring_write": m.add_write_hook(RING_START, RING_END, cpu_type="Sa1"),
                "clamp": m.add_exec_hook(CLAMP, cpu_type="Sa1"),
                "take_irq": m.add_exec_hook(TAKE_IRQ, cpu_type="Sa1"),
                "entry_3a92": m.add_exec_hook(ENTRY_3A92, cpu_type="Sa1"),
                **{
                    name: m.add_exec_hook(address, cpu_type="Sa1")
                    for name, address in SCHEDULER_HOOKS.items()
                },
                **{
                    name: m.add_exec_hook(address, cpu_type="Sa1")
                    for name, address in TASK_HOOKS.items()
                },
                **{
                    name: m.add_exec_hook(address, cpu_type="Sa1")
                    for name, address in BODY_HOOKS.items()
                },
            }
            by_handle = {handle: label for label, handle in handles.items()}
            m.drain_notifications(timeout=0.05)

            writes: list[dict[str, Any]] = []
            phases: list[dict[str, Any]] = []
            clamps: list[dict[str, Any]] = []
            target_clamps = args.intervals + 1
            started = time.monotonic()
            last_heartbeat = started
            m.resume()
            while time.monotonic() - started < args.profile_timeout:
                rows = m.drain_notifications(timeout=args.poll_seconds)
                for params in hook_notifications(rows):
                    handle = int(params.get("handle", -1))
                    label = by_handle.get(handle)
                    if label is None:
                        continue
                    if "cycleCount" not in params:
                        raise RuntimeError(
                            "hook notification lacks cycleCount; use the R5 cycle-stamped Nexen"
                        )
                    log.raw(params, label)
                    if label == "pc_ring_write":
                        writes.append(params)
                    else:
                        event = {**params, "label": label}
                        phases.append(event)
                        if label == "clamp":
                            clamps.append(event)
                if len(clamps) >= target_clamps:
                    m.pause()
                    break
                now = time.monotonic()
                if now - last_heartbeat >= 15.0:
                    log.emit(
                        "heartbeat",
                        wall_seconds=now - started,
                        clamps=len(clamps),
                        ring_write_events=len(writes),
                    )
                    last_heartbeat = now
                time.sleep(min(0.01, args.poll_seconds))
            else:
                m.pause()
                raise TimeoutError(
                    f"tick-ring profile timed out after {args.profile_timeout:.1f} seconds"
                )

            for params in hook_notifications(m.drain_notifications(timeout=0.3)):
                handle = int(params.get("handle", -1))
                label = by_handle.get(handle)
                if label is None or "cycleCount" not in params:
                    continue
                log.raw(params, label)
                if label == "pc_ring_write":
                    writes.append(params)
                else:
                    event = {**params, "label": label}
                    phases.append(event)
                    if label == "clamp":
                        clamps.append(event)
            for handle in handles.values():
                m.remove_hook(handle)
            end_state = snapshot(m)
            require_production_state(
                "profile end",
                end_state,
                args.expected_task_mask,
                "end" if args.round_start_transition else None,
                args.allow_gameplay_mask_evolution,
            )

        clamps = sorted(clamps, key=lambda event: int(event["cycleCount"]))
        phases = sorted(phases, key=lambda event: int(event["cycleCount"]))
        pcs, malformed, unrelated = parse_ring_writes(writes)
        intervals = interval_rows(clamps[:target_clamps], phases, pcs)
        if len(intervals) != args.intervals:
            raise RuntimeError(
                f"expected {args.intervals} intervals, reconstructed {len(intervals)}"
            )
        # Hook installation/removal can bisect the first or last pair of 16-bit
        # stores.  Up to three discarded bytes at each edge are therefore normal;
        # anything larger indicates loss or interleaving inside the capture.
        if malformed > 6:
            raise RuntimeError(f"malformed/interleaved PC-ring byte events: {malformed}")
        for interval in intervals:
            log.emit("interval", **interval)
        summary = aggregate(intervals, args.top)
        log.emit(
            "profile_summary",
            hook_counts={
                "pc_ring_write": len(writes),
                **{
                    label: sum(1 for event in phases if event["label"] == label)
                    for label in (
                        "clamp",
                        "take_irq",
                        "entry_3a92",
                        *SCHEDULER_HOOKS,
                        *TASK_HOOKS,
                        *BODY_HOOKS,
                    )
                },
            },
            ring_records=len(pcs),
            discarded_ring_edge_events=malformed,
            discarded_unrelated_ring_range_writes=unrelated,
            start_state=start_state,
            end_state=end_state,
            **summary,
        )
        return 0
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
