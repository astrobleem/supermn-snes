#!/usr/bin/env python3
"""Attribute checkpointed 5A22 renderer time to production phase boundaries.

This is a cycle-stamped checkpoint profiler, not an end-to-end FPS harness.  It
uses the WRAM execution addresses actually reached by the production renderer
and retains the raw hook stream beside its phase summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
RENDER_COMPLETE = 0x7F8924
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
QUEUE_STATE_OFFSET = 0x89D2
QUEUE_CODE_MARK_OFFSET = 0x89D8
PHASE_LABELS = (
    "sound_tick",
    "vf_tick",
    "snapshot_acquire_paced",
    "vid_frame",
    "ppu_build_cached",
    "vid_bg",
    "bg_dispatch",
    "bg_dispatch_incremental",
    "bg_dispatch_full",
    "bg_dispatch_fast",
    "bg_dispatch_prepared",
    "vid_bg_incremental",
    "vid_bg_heavy",
    "vbi_capacity_ready",
    "bg_cache_reclaim",
    "bg_tile_dma_direct",
    "bg_upload",
    "vid_obj_cached",
    "vid_obj_fast",
    "vid_obj_packed",
    "obj_fast_prepare",
    "obj_cache_preflight",
    "obj_cache_reclaim_fast",
    "obj_tile_queue",
    "obj_upload",
    "obj_upload_queued",
    "ppu_dma_flush_acked",
)
OPTIONAL_PHASE_LABELS = (
    "bcr_clear_changed",
    "bcr_changed_done",
    "bcr_clear_used",
    "bcr_scan_tilemap",
    "bcr_collect_hash",
    "bcr_collect_slots",
    "bcr_hash_clear",
    "bcr_rehash_loop",
    "bcr_rehash_done",
    "bcr_delete_loop",
    "bcr_delete_done",
    "obj_palslot",
    "obj_slot_fast",
    "obj_oam_fast",
    "vof_done",
    "obj_hide_tail_fast",
    "obj_upload_oam",
)
SPECIAL_HOOKS = (
    ("pacing_snapshot_direct", 0x7F0000),
    ("ptw_queue_full", 0x7F0000),
    ("render_queue_capture", 0xE90000),
    ("render_queue_capture_secondary", 0xE90000),
    ("render_queue_install", 0xE90000),
    ("rqi_done", 0xE90000),
    ("render_queue_promote", 0x7E0000),
    ("rqp_have_entry", 0x7E0000),
    ("rqp_finish", 0x7E0000),
)
HIGH_LEVEL_PHASES = (
    ("ack_to_sound", "ack", "sound_tick"),
    ("sound", "sound_tick", "vf_tick"),
    ("joy", "vf_tick", "snapshot_acquire_paced"),
    ("snapshot_acquire", "snapshot_acquire_paced", "vid_frame"),
    ("frame_prologue", "vid_frame", "ppu_build_cached"),
    ("palette", "ppu_build_cached", "vid_bg"),
    ("background", "vid_bg", "vid_obj_cached"),
    ("objects", "vid_obj_cached", "ppu_dma_flush_acked"),
    ("ppu_flush", "ppu_dma_flush_acked", "render_complete"),
    ("total", "ack", "render_complete"),
)
BG_RECLAIM_PHASES = (
    ("setup", "bg_cache_reclaim", "bcr_clear_changed"),
    ("clear_changed_union", "bcr_clear_changed", "bcr_changed_done"),
    ("clear_used_bitmap", "bcr_clear_used", "bcr_scan_tilemap"),
    ("scan_live_cells_hash", "bcr_scan_tilemap", "bcr_collect_hash"),
    ("scan_live_cells_slots", "bcr_scan_tilemap", "bcr_collect_slots"),
    ("collect_retained_hash", "bcr_collect_hash", "bcr_hash_clear"),
    ("collect_retained_slots", "bcr_collect_slots", "bcr_hash_clear"),
    ("clear_hash", "bcr_hash_clear", "bcr_rehash_loop"),
    ("rehash_retained", "bcr_rehash_loop", "bcr_rehash_done"),
    ("finish_rebuild", "bcr_rehash_done", "vbi_capacity_ready"),
    ("collect_stale_hash", "bcr_collect_hash", "bcr_delete_loop"),
    ("delete_stale_clusters", "bcr_delete_loop", "bcr_delete_done"),
    ("finish_delete", "bcr_delete_done", "vbi_capacity_ready"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbols", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7971)
    parser.add_argument("--frames", type=int, default=1200)
    parser.add_argument("--chunk-frames", type=int, default=300)
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help="Lab only: replace checkpoint $7F:8000-$AFFF with --rom video bytes.",
    )
    parser.add_argument(
        "--bg-hash-multiplier",
        type=lambda value: int(value, 0),
        default=1,
        help=(
            "Odd 9-bit BG hash multiplier used by --rom (default: legacy 1). "
            "With --refresh-video-mirror, rebuild the checkpoint hash in place."
        ),
    )
    parser.add_argument(
        "--input-buttons",
        type=lambda value: int(value, 0),
        default=McpSession.BTN_RIGHT | McpSession.BTN_B,
        help="Nexen controller-button mask (Right+B is $0082, not mailbox word $8100)",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_symbols(path: Path) -> dict[str, int]:
    labels: dict[str, int] = {}
    pattern = re.compile(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s+(\S+)$")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line.strip())
        if match:
            labels[match.group(3)] = int(match.group(2), 16)
    missing = [label for label in PHASE_LABELS if label not in labels]
    if missing:
        raise SystemExit(f"missing symbols in {path}: {', '.join(missing)}")
    return labels


def summary(values: list[int]) -> dict[str, Any]:
    return {
        "count": len(values),
        "minimum": min(values, default=None),
        "median": statistics.median(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "maximum": max(values, default=None),
    }


def queue_diagnostics(
    m: McpSession,
    rom: bytes,
    promoter_start: int,
    promoter_end: int,
) -> dict[str, Any]:
    control = m.read_memory("snesWorkRam", QUEUE_STATE_OFFSET, 8)
    installed = m.read_memory(
        "snesWorkRam", promoter_start, promoter_end - promoter_start
    )
    file_start = VIDEO_FILE_BASE + promoter_start - 0x8000
    expected = rom[file_start : file_start + len(installed)]
    return {
        "primary_state": int.from_bytes(control[0:2], "little"),
        "drops": int.from_bytes(control[2:4], "little"),
        "secondary_state": int.from_bytes(control[4:6], "little"),
        "code_mark": int.from_bytes(control[6:8], "little"),
        "renderer_busy": int.from_bytes(
            m.read_memory("snesWorkRam", 0x899C, 2), "little"
        ),
        "code_matches_rom": installed == expected,
        "code_sha256": hashlib.sha256(installed).hexdigest(),
        "expected_code_sha256": hashlib.sha256(expected).hexdigest(),
        "promoter_wram": f"$7E:{promoter_start:04X}-${promoter_end - 1:04X}",
    }


def rebuild_bg_hash(m: McpSession, multiplier: int) -> dict[str, Any]:
    raw_codes = m.read_memory("snesWorkRam", 0xA000, 0x0400)
    raw_slots = m.read_memory("snesWorkRam", 0xA400, 0x0400)
    codes = [
        int.from_bytes(raw_codes[index : index + 2], "little")
        for index in range(0, len(raw_codes), 2)
    ]
    slots = [
        int.from_bytes(raw_slots[index : index + 2], "little")
        for index in range(0, len(raw_slots), 2)
    ]
    active = [
        (code, slots[index])
        for index, code in enumerate(codes)
        if code not in (0x0000, 0xFFFF)
    ]
    if len({code for code, _slot in active}) != len(active):
        raise RuntimeError("checkpoint BG hash contains duplicate live codes")

    rebuilt_codes = bytearray(0x0400)
    rebuilt_slots = bytearray(0x0400)
    maximum_probe = 0
    for code, mapped_slot in active:
        probe = (code * multiplier) & 0x01FF
        probe_count = 1
        while int.from_bytes(
            rebuilt_codes[probe * 2 : probe * 2 + 2], "little"
        ):
            probe = (probe + 1) & 0x01FF
            probe_count += 1
            if probe_count > 0x0200:
                raise RuntimeError("checkpoint BG hash rebuild overflowed")
        maximum_probe = max(maximum_probe, probe_count)
        rebuilt_codes[probe * 2 : probe * 2 + 2] = code.to_bytes(2, "little")
        rebuilt_slots[probe * 2 : probe * 2 + 2] = mapped_slot.to_bytes(
            2, "little"
        )

    m.write_memory("snesWorkRam", 0xA000, rebuilt_codes.hex())
    m.write_memory("snesWorkRam", 0xA400, rebuilt_slots.hex())
    if m.read_memory("snesWorkRam", 0xA000, 0x0400) != rebuilt_codes:
        raise RuntimeError("candidate BG code hash did not verify")
    if m.read_memory("snesWorkRam", 0xA400, 0x0400) != rebuilt_slots:
        raise RuntimeError("candidate BG slot hash did not verify")
    return {
        "multiplier": multiplier,
        "entry_count": len(active),
        "removed_tombstones": sum(code == 0xFFFF for code in codes),
        "maximum_probe": maximum_probe,
        "scope": "cross-ROM checkpoint initialization only",
    }


def main() -> int:
    args = parse_args()
    for path in (args.rom, args.state, args.symbols, args.nexen):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    args.output.mkdir(parents=True)

    symbols = load_symbols(args.symbols)
    for label in ("render_queue_promote", "render_queue_promote_end"):
        if label not in symbols:
            raise SystemExit(f"missing symbol in {args.symbols}: {label}")
    promoter_start = symbols["render_queue_promote"]
    promoter_end = symbols["render_queue_promote_end"]
    if not 0xECA0 <= promoter_start < promoter_end <= 0xF000:
        raise SystemExit("queue promoter is outside private $7E:ECA0-$EFFF WRAM")
    rom = args.rom.read_bytes()
    if not 1 <= args.bg_hash_multiplier <= 0x01FF or not (
        args.bg_hash_multiplier & 1
    ):
        raise SystemExit("--bg-hash-multiplier must be odd and in 1..511")
    events: list[dict[str, Any]] = []
    bg_hash_intervention: dict[str, Any] | None = None
    queue_code_reset_intervention = False
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        queue_initial = queue_diagnostics(
            m, rom, promoter_start, promoter_end
        )
        if args.refresh_video_mirror:
            mirror = rom[VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH]
            m.write_memory("snesWorkRam", VIDEO_WRAM_OFFSET, mirror.hex())
            if m.read_memory(
                "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
            ) != mirror:
                raise RuntimeError("candidate video WRAM mirror did not verify")
            # Cross-ROM checkpoints must exercise the production lazy installer,
            # not have this harness pre-install the promoter and hide a bad path.
            m.write_memory("snesWorkRam", QUEUE_CODE_MARK_OFFSET, "0000")
            m.write_memory(
                "snesWorkRam",
                promoter_start,
                bytes(promoter_end - promoter_start).hex(),
            )
            queue_code_reset_intervention = True
            if args.bg_hash_multiplier != 1:
                bg_hash_intervention = rebuild_bg_hash(
                    m, args.bg_hash_multiplier
                )
        queue_before_run = queue_diagnostics(
            m, rom, promoter_start, promoter_end
        )
        hook_labels = PHASE_LABELS + tuple(
            label for label in OPTIONAL_PHASE_LABELS if label in symbols
        )
        handles = {
            m.add_exec_hook(0x7F0000 | symbols[label], cpu_type="Snes"): label
            for label in hook_labels
        }
        for label, bank in SPECIAL_HOOKS:
            if label in symbols:
                handles[m.add_exec_hook(bank | symbols[label], cpu_type="Snes")] = label
        handles[m.add_exec_hook(RENDER_COMPLETE, cpu_type="Snes")] = "render_complete"
        ack_handle = m.add_write_hook(0x3302, 0x3303, cpu_type="Snes")
        handles[ack_handle] = "ack_write"
        queue_control_handle = m.add_write_hook(
            0x7E89D2, 0x7E89D9, cpu_type="Snes"
        )
        handles[queue_control_handle] = "queue_control_write"
        m.drain_notifications(timeout=0.05)
        # Neutral is already the emulator's reset/default controller state.
        # Do not send Nexen's persistent ``hold`` form in that case: legacy
        # Mesen's MCP ``set_input`` contract requires an explicit frame count
        # and otherwise rejects the profile before the checkpoint can run.
        if args.input_buttons:
            m.tool(
                "set_input",
                {"port": 0, "buttons": args.input_buttons, "hold": True},
            )
        remaining = args.frames
        while remaining:
            count = min(args.chunk_frames, remaining)
            run = m.run_frames(count)
            advanced = int(run.get("framesAdvanced", 0))
            if advanced <= 0:
                raise RuntimeError(f"no frame progress: {run!r}")
            remaining -= advanced
            for note in m.drain_notifications(timeout=0.10):
                if note.get("method") != "notifications/mesen/hookFired":
                    continue
                params = dict(note.get("params", {}))
                label = handles.get(int(params.get("handle", -1)))
                if label is None or "cycleCount" not in params:
                    continue
                address = int(params.get("address", 0))
                if label == "ack_write" and address != 0x3303:
                    continue
                events.append(
                    {
                        "label": "ack" if label == "ack_write" else label,
                        "address": address,
                        "cycle": int(params["cycleCount"]),
                        "frame": int(params.get("frame", 0)),
                        "value": params.get("value"),
                    }
                )
        for handle in handles:
            m.remove_hook(handle)
        queue_after_run = queue_diagnostics(
            m, rom, promoter_start, promoter_end
        )
        snes_cpu_after_run = dict(m.get_cpu_state("Snes"))
        sa1_cpu_after_run = dict(m.get_cpu_state("Sa1"))
        queue_metadata_after_run = m.read_memory(
            "snesWorkRam", 0xD180, 0x20
        ).hex()
        final_state_path = args.output / "final.mss"
        m.save_state(final_state_path.resolve())

    raw_path = args.output / "hooks.jsonl"
    raw_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    renders: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for event in events:
        label = event["label"]
        if label == "ack":
            current = {"ack": event, "markers": {"ack": event}}
            continue
        if current is None:
            continue
        current["markers"].setdefault(label, event)
        counts = current.setdefault("marker_counts", {})
        counts[label] = counts.get(label, 0) + 1
        if label != "render_complete":
            continue
        markers = current["markers"]
        phases: dict[str, int] = {}
        for phase, begin, end in HIGH_LEVEL_PHASES:
            if begin in markers and end in markers:
                phases[phase] = markers[end]["cycle"] - markers[begin]["cycle"]
        current["phases"] = phases
        current["start_frame"] = markers["ack"]["frame"]
        current["end_frame"] = event["frame"]
        current["bg_path"] = next(
            (
                label
                for label in (
                    "bg_dispatch_full",
                    "bg_dispatch_prepared",
                    "bg_dispatch_incremental",
                    "bg_dispatch_fast",
                )
                if label in markers
            ),
            "unknown",
        )
        current["obj_path"] = (
            "vid_obj_packed" if "vid_obj_packed" in markers else "vid_obj_fast"
            if "vid_obj_fast" in markers else "unknown"
        )
        current["obj_reclaim"] = "obj_cache_reclaim_fast" in markers
        current["bg_reclaim"] = "bg_cache_reclaim" in markers
        if "bg_cache_reclaim" in markers and "vbi_capacity_ready" in markers:
            current["bg_reclaim_cycles"] = (
                markers["vbi_capacity_ready"]["cycle"]
                - markers["bg_cache_reclaim"]["cycle"]
            )
            current["bg_reclaim_phases"] = {
                phase: markers[end]["cycle"] - markers[begin]["cycle"]
                for phase, begin, end in BG_RECLAIM_PHASES
                if begin in markers and end in markers
            }
        current["bg_tile_uploads"] = counts.get("bg_tile_dma_direct", 0)
        current["obj_tile_uploads"] = counts.get("obj_tile_queue", 0)
        renders.append(current)
        current = None

    phase_summaries = {
        phase: summary(
            [render["phases"][phase] for render in renders if phase in render["phases"]]
        )
        for phase, _begin, _end in HIGH_LEVEL_PHASES
    }
    path_summaries: dict[str, dict[str, Any]] = {}
    for path in sorted({render["bg_path"] for render in renders}):
        selected = [
            render["phases"]["total"]
            for render in renders
            if render["bg_path"] == path and "total" in render["phases"]
        ]
        path_summaries[path] = summary(selected)
    bg_reclaim_phase_summaries = {
        phase: summary(
            [
                render["bg_reclaim_phases"][phase]
                for render in renders
                if phase in render.get("bg_reclaim_phases", {})
            ]
        )
        for phase, _begin, _end in BG_RECLAIM_PHASES
    }
    top = sorted(
        (
            {
                "start_frame": render["start_frame"],
                "end_frame": render["end_frame"],
                "bg_path": render["bg_path"],
                "obj_path": render["obj_path"],
                "obj_reclaim": render["obj_reclaim"],
                "bg_reclaim": render["bg_reclaim"],
                "bg_reclaim_cycles": render.get("bg_reclaim_cycles"),
                "bg_reclaim_phases": render.get("bg_reclaim_phases"),
                "bg_tile_uploads": render["bg_tile_uploads"],
                "obj_tile_uploads": render["obj_tile_uploads"],
                "phases": render["phases"],
            }
            for render in renders
            if "total" in render["phases"]
        ),
        key=lambda item: item["phases"]["total"],
        reverse=True,
    )[:40]
    result = {
        "scope": "checkpointed 5A22 renderer phase attribution; not FPS evidence",
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "symbols": str(args.symbols),
        "symbols_sha256": sha256(args.symbols),
        "nexen_sha256": sha256(args.nexen),
        "frames": args.frames,
        "chunk_frames": args.chunk_frames,
        "input_buttons": args.input_buttons,
        "video_mirror_intervention": args.refresh_video_mirror,
        "queue_code_reset_intervention": queue_code_reset_intervention,
        "queue_initial": queue_initial,
        "queue_before_run": queue_before_run,
        "queue_after_run": queue_after_run,
        "queue_metadata_after_run": queue_metadata_after_run,
        "snes_cpu_after_run": snes_cpu_after_run,
        "sa1_cpu_after_run": sa1_cpu_after_run,
        "final_state": str(final_state_path),
        "bg_hash_multiplier": args.bg_hash_multiplier,
        "bg_hash_intervention": bg_hash_intervention,
        "render_count": len(renders),
        "event_counts": {
            label: sum(event["label"] == label for event in events)
            for label in sorted({event["label"] for event in events})
        },
        "phase_summaries": phase_summaries,
        "bg_path_total_summaries": path_summaries,
        "bg_reclaim_phase_summaries": bg_reclaim_phase_summaries,
        "top_renders": top,
        "renders": renders,
        "hooks": {"path": str(raw_path), "sha256": sha256(raw_path)},
    }
    result_path = args.output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "render_count": len(renders),
                "phase_summaries": phase_summaries,
                "bg_path_total_summaries": path_summaries,
                "bg_reclaim_phase_summaries": bg_reclaim_phase_summaries,
                "queue_after_run": queue_after_run,
                "results": str(result_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
