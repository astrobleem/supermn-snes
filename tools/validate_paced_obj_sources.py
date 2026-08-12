#!/usr/bin/env python3
"""Check paced OBJ work planes against the final live video shadow.

The production pacing hook stops the SA-1 at ``lhp_wai`` only after the game
has finished the tick and published stable-shadow ownership.  Sampling there
tests whether the three work planes consumed by $00158E are still byte-exact
with the renderer-visible shadow at the actual handoff boundary.  This is a
checkpointed architecture check, not an end-to-end FPS measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/111a-table-active-cold-boot-v1/final.mss"
)
WAI_HOOK = 0x99FB51
PLANES = (
    ("y", 0x401CF6, 0x413002),
    ("x_palette", 0x4020F2, 0x414402),
    ("code", 0x4024EE, 0x414002),
)
PLANE_BYTES = 0x03FC


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--boundaries", type=int, default=20)
    parser.add_argument("--port", type=int, default=7661)
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="gate only the independent manifest predicate check",
    )
    parser.add_argument(
        "--y-qualified-manifest",
        action="store_true",
        help=(
            "Validate the delegated $41:1600 Y-qualified list (up to 512 "
            "offsets) and prove that applying the remaining code/X filters "
            "reconstructs the exact capped visible manifest."
        ),
    )
    parser.add_argument(
        "--yx-qualified-manifest",
        action="store_true",
        help=(
            "Validate the delegated $41:1600 Y/X-qualified list (up to 512 "
            "offsets) and prove that applying the remaining code filter "
            "reconstructs the exact capped visible manifest."
        ),
    )
    parser.add_argument(
        "--packed-obj-manifest",
        action="store_true",
        help=(
            "Validate bit-15-tagged $41:1600 visible OBJ records packed as "
            "Y/code/X words, and reconstruct their ordered source slots."
        ),
    )
    return parser.parse_args()


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
    return int.from_bytes(data, "little")


def mismatch_summary(source: bytes, shadow: bytes) -> dict[str, object]:
    mismatches = [
        index for index, (left, right) in enumerate(zip(source, shadow)) if left != right
    ]
    return {
        "mismatch_count": len(mismatches),
        "first_mismatches": [
            {
                "offset": index,
                "source": source[index],
                "shadow": shadow[index],
            }
            for index in mismatches[:16]
        ],
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "shadow_sha256": hashlib.sha256(shadow).hexdigest(),
    }


def packed_x_word(
    sy: int,
    x_color: int,
    code_word: int,
    source_offset: int | None = None,
) -> int | None:
    """Apply the production crop and its exact HUD-only translations."""
    sx = x_color & 0x01FF
    code = code_word & 0x3FFF
    if source_offset is not None:
        if sy == 0x0A and (
            source_offset == 0x0004
            or 0x0048 <= source_offset < 0x0072
        ):
            return None
        if sy == 0x1A and 0x006A <= source_offset < 0x0072:
            return None
    if sy in (0xE2, 0xF2) and code == 0x0020:
        return None
    if sy in (0xE2, 0xF2):
        if sx < 0x0040:
            return (x_color + 0x0030) & 0xFFFF
        if 0x0120 <= sx < 0x0170:
            return (x_color - 0x0030) & 0xFFFF
    credit_glyph = 0x007D <= code <= 0x0080 or code == 0x008B
    if sy == 0x0A and credit_glyph and 0x0120 <= sx < 0x0170:
        return (x_color - 0x0030) & 0xFFFF
    if 0x0031 <= sx < 0x0140:
        return x_color
    return None


def expected_obj_manifest(
    y_plane: bytes,
    code_plane: bytes,
    x_plane: bytes,
    *,
    title_overlay: bool = False,
) -> bytes:
    """Reproduce vid_obj_fast's exact source-order visibility selection."""
    offsets: list[int] = []
    for offset in range(0, 0x0400, 2):
        code = int.from_bytes(code_plane[offset : offset + 2], "big")
        if code == 0xFFFF or code & 0x3FFF == 0:
            continue
        sy = y_plane[offset + 1]
        if sy == 0 or sy >= 0xF3:
            continue
        if title_overlay and 0x1A <= sy < 0x70 and sy & 0x0F == 0x0A:
            continue
        x_color = int.from_bytes(x_plane[offset : offset + 2], "big")
        if packed_x_word(sy, x_color, code, source_offset=offset) is None:
            continue
        offsets.append(offset)
        if len(offsets) == 128:
            break
    return b"".join(offset.to_bytes(2, "little") for offset in offsets)


def expected_y_manifest(y_plane: bytes) -> bytes:
    offsets = [
        offset
        for offset in range(0, 0x0400, 2)
        if 0 < y_plane[offset + 1] < 0xF3
    ]
    return b"".join(offset.to_bytes(2, "little") for offset in offsets)


def expected_yx_manifest(
    y_plane: bytes, code_plane: bytes, x_plane: bytes
) -> bytes:
    offsets: list[int] = []
    for offset in range(0, 0x0400, 2):
        if not 0 < y_plane[offset + 1] < 0xF3:
            continue
        x_color = int.from_bytes(x_plane[offset : offset + 2], "big")
        code = int.from_bytes(code_plane[offset : offset + 2], "big")
        if packed_x_word(
            y_plane[offset + 1], x_color, code, source_offset=offset
        ) is None:
            continue
        offsets.append(offset)
    return b"".join(offset.to_bytes(2, "little") for offset in offsets)


def expected_packed_manifest(
    y_plane: bytes,
    code_plane: bytes,
    x_plane: bytes,
    *,
    title_overlay: bool = False,
) -> bytes:
    records = bytearray()
    visible = expected_obj_manifest(
        y_plane,
        code_plane,
        x_plane,
        title_overlay=title_overlay,
    )
    for cursor in range(0, len(visible), 2):
        offset = int.from_bytes(visible[cursor : cursor + 2], "little")
        code = int.from_bytes(code_plane[offset : offset + 2], "big")
        x_color = int.from_bytes(x_plane[offset : offset + 2], "big")
        packed_x = packed_x_word(
            y_plane[offset + 1], x_color, code, source_offset=offset
        )
        assert packed_x is not None
        records.extend(y_plane[offset : offset + 2])
        records.extend(code_plane[offset : offset + 2])
        records.extend(packed_x.to_bytes(2, "big"))
    return bytes(records)


def visible_from_packed_manifest(
    manifest: bytes,
    y_plane: bytes,
    code_plane: bytes,
    x_plane: bytes,
    *,
    title_overlay: bool = False,
) -> bytes:
    """Recover the packed records' monotonically ordered source slots.

    Production records intentionally omit their source offset.  Match each
    six-byte record to the first identical, independently visible source slot
    after the previous match.  The full packed-byte comparison remains the
    authoritative completeness check; this reconstruction separately checks
    source ordering and the visibility predicate.
    """
    expected_visible = expected_obj_manifest(
        y_plane,
        code_plane,
        x_plane,
        title_overlay=title_overlay,
    )
    candidates = [
        int.from_bytes(expected_visible[cursor : cursor + 2], "little")
        for cursor in range(0, len(expected_visible), 2)
    ]
    accepted: list[int] = []
    candidate_cursor = 0
    for cursor in range(0, len(manifest), 6):
        record = manifest[cursor : cursor + 6]
        if len(record) != 6:
            break
        while candidate_cursor < len(candidates):
            offset = candidates[candidate_cursor]
            candidate_cursor += 1
            source_record = (
                y_plane[offset : offset + 2]
                + code_plane[offset : offset + 2]
            )
            code = int.from_bytes(code_plane[offset : offset + 2], "big")
            x_color = int.from_bytes(x_plane[offset : offset + 2], "big")
            packed_x = packed_x_word(
                y_plane[offset + 1], x_color, code, source_offset=offset
            )
            assert packed_x is not None
            source_record += packed_x.to_bytes(2, "big")
            if source_record == record:
                accepted.append(offset)
                break
        else:
            break
    return b"".join(offset.to_bytes(2, "little") for offset in accepted)


def visible_from_y_manifest(
    manifest: bytes, y_plane: bytes, code_plane: bytes, x_plane: bytes
) -> bytes:
    accepted: list[int] = []
    for cursor in range(0, len(manifest), 2):
        offset = int.from_bytes(manifest[cursor : cursor + 2], "little")
        if offset > 0x03FE or offset & 1:
            continue
        code = int.from_bytes(code_plane[offset : offset + 2], "big")
        if code == 0xFFFF or code & 0x3FFF == 0:
            continue
        x_color = int.from_bytes(x_plane[offset : offset + 2], "big")
        if packed_x_word(
            y_plane[offset + 1], x_color, code, source_offset=offset
        ) is None:
            continue
        accepted.append(offset)
        if len(accepted) == 128:
            break
    return b"".join(offset.to_bytes(2, "little") for offset in accepted)


def visible_from_yx_manifest(manifest: bytes, code_plane: bytes) -> bytes:
    accepted: list[int] = []
    for cursor in range(0, len(manifest), 2):
        offset = int.from_bytes(manifest[cursor : cursor + 2], "little")
        if offset > 0x03FE or offset & 1:
            continue
        code = int.from_bytes(code_plane[offset : offset + 2], "big")
        if code == 0xFFFF or code & 0x3FFF == 0:
            continue
        accepted.append(offset)
        if len(accepted) == 128:
            break
    return b"".join(offset.to_bytes(2, "little") for offset in accepted)


def main() -> int:
    args = parse_args()
    if args.boundaries <= 0:
        raise SystemExit("--boundaries must be positive")
    selected_formats = sum(
        (
            args.y_qualified_manifest,
            args.yx_qualified_manifest,
            args.packed_obj_manifest,
        )
    )
    if selected_formats > 1:
        raise SystemExit(
            "manifest format options are mutually exclusive"
        )
    rom = args.rom.resolve()
    state = args.state.resolve()
    nexen = args.nexen.resolve()
    output = args.output.resolve()
    for label, path in (("ROM", rom), ("state", state), ("Nexen", nexen)):
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"{label} missing or empty: {path}")
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

    samples: list[dict[str, object]] = []
    with McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=output / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(state)
        m.pause()
        for index in range(args.boundaries):
            hook = m.add_exec_hook(WAI_HOOK, cpu_type="Sa1")
            m.drain_notifications(timeout=0.05)
            hit = m.run_until(max_frames=30, hook_handle=hook)
            m.pause()
            m.remove_hook(hook)
            if (hit or {}).get("reason") != "hookFired":
                raise RuntimeError(f"boundary {index}: lhp_wai did not fire: {hit!r}")

            plane_results: dict[str, dict[str, object]] = {}
            for name, source_address, shadow_address in PLANES:
                source = bytes(m.read_memory("snesMemory", source_address, PLANE_BYTES))
                shadow = bytes(m.read_memory("snesMemory", shadow_address, PLANE_BYTES))
                plane_results[name] = mismatch_summary(source, shadow)
            full_y = bytes(m.read_memory("snesMemory", 0x413000, 0x0400))
            full_code = bytes(m.read_memory("snesMemory", 0x414000, 0x0400))
            full_x = bytes(m.read_memory("snesMemory", 0x414400, 0x0400))
            title_overlay = bool(
                le16(m.read_memory("snesMemory", 0x410150, 2))
            )
            expected_visible = expected_obj_manifest(
                full_y,
                full_code,
                full_x,
                title_overlay=title_overlay if args.packed_obj_manifest else False,
            )
            if args.packed_obj_manifest:
                expected_manifest = expected_packed_manifest(
                    full_y,
                    full_code,
                    full_x,
                    title_overlay=title_overlay,
                )
            elif args.yx_qualified_manifest:
                expected_manifest = expected_yx_manifest(
                    full_y, full_code, full_x
                )
            elif args.y_qualified_manifest:
                expected_manifest = expected_y_manifest(full_y)
            else:
                expected_manifest = expected_visible
            encoded_manifest_length = le16(
                m.read_memory("snesMemory", 0x410138, 2)
            )
            packed_flag_match = bool(encoded_manifest_length & 0x8000) == bool(
                args.packed_obj_manifest
            )
            manifest_length = encoded_manifest_length & (
                0x7FFF if args.packed_obj_manifest else 0xFFFF
            )
            delegated_manifest = (
                args.y_qualified_manifest
                or args.yx_qualified_manifest
                or args.packed_obj_manifest
            )
            maximum_length = (
                0x0300
                if args.packed_obj_manifest
                else (0x0400 if delegated_manifest else 0x0100)
            )
            alignment = 6 if args.packed_obj_manifest else 2
            if manifest_length > maximum_length or manifest_length % alignment:
                observed_manifest = b""
            else:
                observed_manifest = bytes(
                    m.read_memory(
                        "snesMemory",
                        0x411600 if delegated_manifest else 0x411E00,
                        manifest_length,
                    )
                )
            manifest_result = mismatch_summary(expected_manifest, observed_manifest)
            manifest_result.update(
                {
                    "expected_length": len(expected_manifest),
                    "observed_length": manifest_length,
                    "encoded_length": encoded_manifest_length,
                    "format_flag_match": packed_flag_match,
                    "length_match": manifest_length == len(expected_manifest),
                }
            )
            if args.packed_obj_manifest:
                delegated_visible = visible_from_packed_manifest(
                    observed_manifest,
                    full_y,
                    full_code,
                    full_x,
                    title_overlay=title_overlay,
                )
            elif args.yx_qualified_manifest:
                delegated_visible = visible_from_yx_manifest(
                    observed_manifest, full_code
                )
            elif args.y_qualified_manifest:
                delegated_visible = visible_from_y_manifest(
                    observed_manifest, full_y, full_code, full_x
                )
            else:
                delegated_visible = observed_manifest
            visible_result = mismatch_summary(expected_visible, delegated_visible)
            visible_result.update(
                {
                    "expected_length": len(expected_visible),
                    "observed_length": len(delegated_visible),
                    "length_match": len(expected_visible) == len(delegated_visible),
                }
            )
            sample = {
                "index": index,
                "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
                "sa1_cycles": int(m.get_cpu_state("Sa1")["cycleCount"]),
                "arm": le16(m.read_memory("snesMemory", 0x410122, 2)),
                "renderer_busy": le16(
                    m.read_memory("snesMemory", 0x7E899C, 2)
                ),
                "title_overlay": title_overlay,
                "plane_prefix_words": {
                    "y": m.read_memory("snesMemory", 0x413000, 2).hex(),
                    "code": m.read_memory("snesMemory", 0x414000, 2).hex(),
                    "x_palette": m.read_memory("snesMemory", 0x414400, 2).hex(),
                },
                "control_words": {
                    "scroll": m.read_memory("snesMemory", 0x413408, 2).hex(),
                    "sprite": m.read_memory("snesMemory", 0x413604, 2).hex(),
                },
                "planes": plane_results,
                "manifest": manifest_result,
                "visible_manifest": visible_result,
            }
            samples.append(sample)
            print(json.dumps({"event": "boundary", **sample}, sort_keys=True), flush=True)

    mismatch_count = sum(
        int(result["mismatch_count"])
        for sample in samples
        for result in sample["planes"].values()  # type: ignore[union-attr]
    )
    manifest_mismatch_count = sum(
        int(sample["manifest"]["mismatch_count"])  # type: ignore[index]
        + int(not sample["manifest"]["length_match"])  # type: ignore[index]
        + int(not sample["manifest"]["format_flag_match"])  # type: ignore[index]
        + int(sample["visible_manifest"]["mismatch_count"])  # type: ignore[index]
        + int(not sample["visible_manifest"]["length_match"])  # type: ignore[index]
        for sample in samples
    )
    gated_mismatch_count = (
        manifest_mismatch_count
        if args.manifest_only
        else mismatch_count + manifest_mismatch_count
    )
    summary = {
        "scope": (
            "checkpointed independent OBJ-manifest predicate equivalence; not fps"
            if args.manifest_only
            else "checkpointed paced-boundary OBJ source/shadow equivalence; not fps"
        ),
        "result": "green" if gated_mismatch_count == 0 else "red",
        "manifest_only": args.manifest_only,
        "y_qualified_manifest": args.y_qualified_manifest,
        "yx_qualified_manifest": args.yx_qualified_manifest,
        "packed_obj_manifest": args.packed_obj_manifest,
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--porcelain=v1").splitlines(),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(state),
        "state_sha256": sha256(state),
        "nexen": str(nexen),
        "nexen_sha256": sha256(nexen),
        "hook": f"{WAI_HOOK:06X}",
        "boundaries": len(samples),
        "compared_bytes": len(samples) * len(PLANES) * PLANE_BYTES,
        "mismatch_count": mismatch_count,
        "manifest_mismatch_count": manifest_mismatch_count,
        "samples": samples,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "summary",
                "result": summary["result"],
                "boundaries": summary["boundaries"],
                "compared_bytes": summary["compared_bytes"],
                "mismatch_count": mismatch_count,
                "manifest_mismatch_count": manifest_mismatch_count,
                "summary": str(output / "summary.json"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if gated_mismatch_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
