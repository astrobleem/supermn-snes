#!/usr/bin/env python3
"""Attribute renderer throughput with same-state, single-phase bypasses.

This is an intervened checkpoint diagnostic, never acceptance evidence.  Each
variant reloads the same legacy-Mesen state, verifies its initial renderer
counters, optionally finishes old-hash in-flight work before logging a complete
WRAM-code refresh, replaces at most one renderer entry with ``RTS``, and records
compact per-video-frame counters.  Raw rows stay on disk so the main thread
needs only the summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_EMULATOR = ROOT / "tools" / "mesen211_mcp_controller.sh"
VIDEO_FILE_BASE = 0x298000
WRAM_BANK7F_BASE = 0x10000
# (label, byte offset from label, replacement).  ``jmp:LABEL`` builds a
# same-bank absolute JMP from the selected symbol table.
VARIANTS: dict[str, tuple[tuple[str, int, str], ...]] = {
    "baseline": (),
    "no_palette": (("ppu_build_cached", 0, "60"),),
    "no_bg": (("vid_bg", 0, "60"),),
    "no_obj": (("vid_obj_cached", 0, "60"),),
    "no_bg_obj": (("vid_bg", 0, "60"), ("vid_obj_cached", 0, "60")),
    # Preserve bg_scroll's register publication while removing only the
    # Mode-2 offset-table build/DMA.
    "no_bg_opt": (("bg_scroll_with_opt", 0, "eaeaeaea"),),
    # Keep bg_dispatch's PHP/REP and continuation, but skip only the dynamic
    # physical-column-map comparison JSL at byte +3.
    "no_bg_column_map": (("bg_dispatch_dynamic", 3, "eaeaeaea"),),
    # Enter the normal OBJ tail (hide/upload/PLP/RTS) without transforming the
    # packed records themselves.
    "no_obj_record_loop": (("vid_obj_packed", 0, "jmp:vof_done"),),
    # Preserve record transformation and cache work, but omit tile/OAM DMA.
    "no_obj_upload": (("obj_upload_title_dispatch", 0, "60"),),
    # Preserve queue reset and normal lookup, but omit proactive cache scanning.
    "no_obj_preflight": (("obj_cache_preflight", 0, "60"),),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--symbols", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--port-base", type=int, default=43840)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--warmup-ceiling", type=int, default=120)
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help=(
            "diagnostic only: finish the checkpoint's in-flight render, then "
            "replace $7F:8000-$AFFF with the selected ROM before measurement"
        ),
    )
    parser.add_argument(
        "--variants",
        default=",".join(VARIANTS),
        help="comma-separated variant names (default: all)",
    )
    parser.add_argument("--expect-tick", type=lambda value: int(value, 0), required=True)
    parser.add_argument(
        "--expect-render-complete", type=lambda value: int(value, 0), required=True
    )
    parser.add_argument("--expect-drops", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--expect-primary", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--expect-secondary", type=lambda value: int(value, 0), required=True)
    return parser.parse_args()


def configure_runtime() -> None:
    dotnet8 = "/home/chad/.dotnet8"
    os.environ["DOTNET_ROOT"] = dotnet8
    os.environ["PATH"] = dotnet8 + os.pathsep + os.environ.get("PATH", "")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_symbols(path: Path) -> dict[str, int]:
    pattern = re.compile(r"^[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)$")
    labels: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line.strip())
        if match:
            labels[match.group(2)] = int(match.group(1), 16)
    needed: set[str] = set()
    for patches in VARIANTS.values():
        for label, _offset, replacement in patches:
            needed.add(label)
            if replacement.startswith("jmp:"):
                needed.add(replacement.removeprefix("jmp:"))
    missing = sorted(needed - labels.keys())
    if missing:
        raise SystemExit(f"missing symbols: {', '.join(missing)}")
    return labels


def le16(data: bytes | bytearray) -> int:
    return int.from_bytes(data, "little")


def read16(m: McpSession, memory_type: str, address: int) -> int:
    return le16(m.read_memory(memory_type, address, 2))


def sample(m: McpSession) -> dict[str, int]:
    state = m.get_state()
    tick = read16(m, "Sa1Memory", 0x0760)
    published = read16(m, "snesWorkRam", 0x7190)
    return {
        "frame": int(state.get("frameCount", 0)),
        "tick": tick,
        "render_complete": read16(m, "snesWorkRam", 0x89A2),
        "rendered_generation": read16(m, "snesWorkRam", 0x89A4),
        "obj_published_sequence": published,
        "obj_age_ticks": (tick - published) & 0xFFFF,
        "primary": read16(m, "snesWorkRam", 0x89D2),
        "drops": read16(m, "snesWorkRam", 0x89D4),
        "secondary": read16(m, "snesWorkRam", 0x89D6),
        "renderer_busy": read16(m, "snesWorkRam", 0x899C),
    }


def advance_one(m: McpSession) -> None:
    response = m.run_frames(1)
    m.pause()
    if int(response.get("framesAdvanced", 0)) != 1:
        raise RuntimeError(f"one-frame advance failed: {response!r}")


def modular_delta(final: int, initial: int) -> int:
    return (final - initial) & 0xFFFF


def summarize(rows: list[dict[str, int]]) -> dict[str, Any]:
    completion_frames = [
        row["frame"]
        for previous, row in zip(rows, rows[1:])
        if row["render_complete"] != previous["render_complete"]
    ]
    intervals = [
        final - initial
        for initial, final in zip(completion_frames, completion_frames[1:])
    ]
    ages = [row["obj_age_ticks"] for row in rows]
    first = rows[0]
    last = rows[-1]
    tick_delta = modular_delta(last["tick"], first["tick"])
    render_delta = modular_delta(
        last["render_complete"], first["render_complete"]
    )
    return {
        "coverage": {
            "complete": len(rows) >= 2,
            "frames": len(rows) - 1,
            "frame_start": first["frame"],
            "frame_end": last["frame"],
        },
        "first": first,
        "last": last,
        "tick_delta": tick_delta,
        "render_complete_delta": render_delta,
        "renders_per_tick": (render_delta / tick_delta) if tick_delta else None,
        "queue_drop_delta": modular_delta(last["drops"], first["drops"]),
        "obj_age_ticks": {
            "minimum": min(ages),
            "median": statistics.median(ages),
            "maximum": max(ages),
        },
        "completion_intervals_video_frames": {
            "count": len(intervals),
            "minimum": min(intervals, default=None),
            "median": statistics.median(intervals) if intervals else None,
            "maximum": max(intervals, default=None),
        },
    }


def run_variant(
    args: argparse.Namespace,
    labels: dict[str, int],
    rom: bytes,
    name: str,
    patches: tuple[tuple[str, int, str], ...],
    port: int,
) -> dict[str, Any]:
    variant_dir = args.output / name
    variant_dir.mkdir()
    interventions: list[dict[str, Any]] = []
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=variant_dir / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        initial = sample(m)
        expected = {
            "tick": args.expect_tick,
            "render_complete": args.expect_render_complete,
            "drops": args.expect_drops,
            "primary": args.expect_primary,
            "secondary": args.expect_secondary,
        }
        observed = {key: initial[key] for key in expected}
        if observed != expected:
            raise RuntimeError(
                f"{name}: checkpoint counters mismatch: {observed!r} != {expected!r}"
            )

        if args.refresh_video_mirror:
            old_complete = initial["render_complete"]
            finish_frames = 0
            while sample(m)["render_complete"] == old_complete:
                if finish_frames >= args.warmup_ceiling:
                    raise RuntimeError(
                        f"{name}: old-hash in-flight render did not complete before refresh"
                    )
                advance_one(m)
                finish_frames += 1
            mirror = rom[VIDEO_FILE_BASE : VIDEO_FILE_BASE + 0x3000]
            for offset in range(0, len(mirror), 0x1000):
                m.write_memory(
                    "snesWorkRam",
                    WRAM_BANK7F_BASE + 0x8000 + offset,
                    mirror[offset : offset + 0x1000].hex(),
                )
            observed_mirror = bytes(
                m.read_memory(
                    "snesWorkRam", WRAM_BANK7F_BASE + 0x8000, len(mirror)
                )
            )
            if observed_mirror != mirror:
                raise RuntimeError(f"{name}: refreshed WRAM video mirror did not verify")
            interventions.append(
                {
                    "kind": "checkpoint_video_wram_code_refresh",
                    "range": "$7F:8000-$AFFF",
                    "bytes": len(mirror),
                    "old_hash_frames_to_safe_boundary": finish_frames,
                    "meaning": "cross-ROM diagnostic intervention; never acceptance evidence",
                }
            )

        for label, offset, replacement_spec in patches:
            if replacement_spec.startswith("jmp:"):
                target_label = replacement_spec.removeprefix("jmp:")
                target_address = labels[target_label]
                replacement = bytes(
                    (0x4C, target_address & 0xFF, (target_address >> 8) & 0xFF)
                )
            else:
                replacement = bytes.fromhex(replacement_spec)
            address = WRAM_BANK7F_BASE + labels[label] + offset
            original = bytes(
                m.read_memory("snesWorkRam", address, len(replacement))
            )
            file_offset = VIDEO_FILE_BASE + labels[label] + offset - 0x8000
            expected_bytes = rom[file_offset : file_offset + len(replacement)]
            if original != expected_bytes:
                raise RuntimeError(
                    f"{name}: {label}+{offset} WRAM bytes {original.hex()} "
                    f"!= ROM {expected_bytes.hex()}"
                )
            m.write_memory("snesWorkRam", address, replacement.hex())
            if bytes(
                m.read_memory("snesWorkRam", address, len(replacement))
            ) != replacement:
                raise RuntimeError(f"{name}: {label} bypass did not verify")
            interventions.append(
                {
                    "label": label,
                    "offset": offset,
                    "wram_address": f"$7F:{labels[label] + offset:04X}",
                    "original": original.hex(),
                    "replacement": replacement.hex(),
                    "meaning": "diagnostic phase bypass; not ROM or acceptance evidence",
                }
            )

        # Finish the scene that was already executing when the state was saved;
        # begin measurement on a common completed-render boundary.
        initial_complete = sample(m)["render_complete"]
        warmup = 0
        while sample(m)["render_complete"] == initial_complete:
            if warmup >= args.warmup_ceiling:
                raise RuntimeError(f"{name}: no completed render during warmup")
            advance_one(m)
            warmup += 1

        rows = [sample(m)]
        for _ in range(args.frames):
            advance_one(m)
            rows.append(sample(m))
        final_state = variant_dir / "final.mss"
        m.save_state(final_state)

    rows_path = variant_dir / "rows.jsonl"
    rows_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    result = {
        "variant": name,
        "scope": "same-state intervened renderer throughput attribution only; never acceptance",
        "warmup_frames_to_completion_boundary": warmup,
        "interventions": interventions,
        "summary": summarize(rows),
        "artifacts": {
            "rows": str(rows_path),
            "final_state": str(final_state),
        },
    }
    (variant_dir / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


def main() -> int:
    args = parse_args()
    if args.frames <= 0 or args.warmup_ceiling <= 0:
        raise SystemExit("frame counts must be positive")
    for path in (args.rom, args.state, args.symbols, args.emulator):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    args.output.mkdir(parents=True)
    configure_runtime()
    labels = load_symbols(args.symbols)
    rom = args.rom.read_bytes()
    selected = [value.strip() for value in args.variants.split(",") if value.strip()]
    unknown = sorted(set(selected) - VARIANTS.keys())
    if not selected or unknown:
        raise SystemExit(
            "invalid --variants: "
            + (", ".join(unknown) if unknown else "selection is empty")
        )
    results = [
        run_variant(args, labels, rom, name, VARIANTS[name], args.port_base + index)
        for index, name in enumerate(selected)
    ]
    report = {
        "schema": 1,
        "kind": "renderer_phase_bypass_diagnostic",
        "scope": (
            "same-emulator legacy-Mesen checkpoint intervention; a requested code "
            "refresh is cross-ROM diagnostic evidence, and bypassed phases make all "
            "variants except baseline invalid as visual/gameplay evidence"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "frames_per_variant": args.frames,
        "refresh_video_mirror": args.refresh_video_mirror,
        "results": results,
    }
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "report": str(report_path),
                "variants": {
                    item["variant"]: item["summary"] for item in results
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
