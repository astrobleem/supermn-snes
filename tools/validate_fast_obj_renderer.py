#!/usr/bin/env python3
"""Byte-differential the production fast OBJ transform against its reference.

Two fresh Nexen processes load the same organic production checkpoint.  With
interrupts disabled, each process invokes one WRAM-resident OBJ routine on the
5A22 and returns to the same private spin stub: established vid_obj at $8189 or
vid_obj_fast at $A400.  This is checkpointed renderer/local-cycle evidence, not
FPS or a production cold-boot result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
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
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
RETURN_STUB = 0x7F7F00
RETURN_STACK = 0x1DFE
ENTRIES = {"reference": 0x7F8189, "fast": 0x7FA400}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument(
        "--candidate-rom",
        type=Path,
        help="Compare the fast entry in this ROM against the fast entry in --rom.",
    )
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=7617)
    parser.add_argument(
        "--force-cold-obj-cache",
        action="store_true",
        help="Clear the persistent OBJ hash so every visible code exercises insertion/upload.",
    )
    parser.add_argument(
        "--force-full-obj-cache",
        action="store_true",
        help=(
            "Set the persistent slot count to 128 while retaining the checkpoint hash, "
            "forcing the next missing code through the full-cache recovery path."
        ),
    )
    parser.add_argument(
        "--allow-cache-remap",
        action="store_true",
        help=(
            "Treat physical OBJ cache/hash/slot layout as an internal candidate "
            "detail. Non-OBJ VRAM and the positioned OAM render remain gating."
        ),
    )
    parser.add_argument(
        "--candidate-y-manifest",
        action="store_true",
        help=(
            "For a cross-ROM candidate, derive its $7E:BC00 Y-qualified list "
            "from the checkpoint's coherent raw OBJ-Y cache before calling "
            "the candidate fast renderer."
        ),
    )
    parser.add_argument(
        "--candidate-yx-manifest",
        action="store_true",
        help=(
            "For a cross-ROM candidate, derive its $7E:BC00 Y/X-qualified "
            "list from the checkpoint's coherent raw OBJ caches before "
            "calling the candidate fast renderer."
        ),
    )
    parser.add_argument(
        "--candidate-packed-manifest",
        action="store_true",
        help=(
            "For a cross-ROM candidate, derive its bit-15-tagged $7E:BC00 "
            "visible OBJ records from the checkpoint's coherent raw OBJ "
            "caches before calling the candidate fast renderer."
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def differing_offsets(left: bytes, right: bytes, limit: int = 128) -> list[int]:
    return [
        offset
        for offset, (old, new) in enumerate(zip(left, right))
        if old != new
    ][:limit]


def stable_ppu_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return visible PPU configuration without sampling-position counters."""
    return {
        key: value
        for key, value in state.items()
        if key not in {"frameCount", "scanline"}
    }


def set_snes_entry(m: McpSession, entry: int) -> None:
    # RTS pulls low then high from SP+1/SP+2 and increments the stored address.
    # $7EFF therefore returns to the BRA $FE stub at $7F:7F00.
    m.write_memory("snesWorkRam", 0x17F00, "80fe")
    m.write_memory("snesWorkRam", RETURN_STACK + 1, "ff7e")
    m.tool(
        "set_cpu_state",
        {
            "cpuType": "Snes",
            "pc": entry & 0xFFFF,
            "k": entry >> 16,
            "a": 0,
            "x": 0,
            "y": 0,
            "sp": RETURN_STACK,
            "d": 0,
            "dbr": 0,
            "ps": 0x04,  # native mode, IRQ masked; routine establishes A16/X16
            "emulationMode": False,
        },
    )


def run_variant(
    name: str,
    entry: int,
    args: argparse.Namespace,
    port: int,
    rom: Path | None = None,
) -> dict[str, Any]:
    selected_rom = (rom or args.rom).resolve()
    with McpSession(
        rom=selected_rom,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=180.0,
        stderr_log=args.output / f"{name}.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()

        rom_mirror = selected_rom.read_bytes()[
            VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
        ]
        old_mirror = m.read_memory(
            "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
        )
        for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
            m.write_memory(
                "snesWorkRam",
                VIDEO_WRAM_OFFSET + offset,
                rom_mirror[offset : offset + 0x1000].hex(),
            )
        if m.read_memory(
            "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
        ) != rom_mirror:
            raise RuntimeError(f"{name}: production WRAM code mirror did not verify")

        # Prevent the production NMI/coprocessor handlers from interleaving the
        # synthetic call.  The SA-1 may continue, but it cannot mutate 5A22 WRAM
        # caches/OAM/PPU, and both variants begin from the identical checkpoint.
        m.write_memory("snesMemory", 0x004200, "00")
        m.write_memory("snesMemory", 0x002201, "00")
        m.write_memory("snesMemory", 0x002202, "80")
        m.write_memory("snesWorkRam", 0x899C, "0100")

        # $4200=0 prevents new NMIs, but a save state can already contain a
        # latched NMI.  Let that one retire against the private spin stub while
        # the renderer-busy word suppresses production render work.  Without
        # this drain, the pending handler can interleave one variant at a
        # different instruction and make a synthetic old-vs-fast comparison
        # depend on routine timing rather than renderer semantics.
        set_snes_entry(m, RETURN_STUB)
        interrupt_quiesce = m.run_frames(2)
        m.pause()
        m.write_memory("snesMemory", 0x004200, "00")
        m.write_memory("snesMemory", 0x002201, "00")
        m.write_memory("snesMemory", 0x002202, "80")
        full_cache_intervention = None
        if args.force_cold_obj_cache:
            m.write_memory("snesWorkRam", 0x5000, bytes(0x1000).hex())
            m.write_memory("snesWorkRam", 0x00DE, "0000")
            m.write_memory("snesWorkRam", 0x89CE, "0000")
            m.write_memory("snesWorkRam", 0x8980, "5aa5")
            m.write_memory("snesWorkRam", 0x8988, "ffff")
            m.write_memory("snesWorkRam", 0x89C6, "0000")
        if args.force_full_obj_cache:
            checkpoint_encoded_length = int.from_bytes(
                m.read_memory("snesWorkRam", 0x89BA, 2), "little"
            )
            checkpoint_length = checkpoint_encoded_length & 0x7FFF
            checkpoint_packed8 = None
            if (
                checkpoint_encoded_length & 0x8000
                and checkpoint_length <= 0x0400
                and checkpoint_length % 8 == 0
            ):
                checkpoint_packed8 = m.read_memory(
                    "snesWorkRam", 0xBC00, checkpoint_length
                )
            raw_y = (
                m.read_memory("snesWorkRam", 0x3000, 0x0400)
                if checkpoint_packed8 is None
                else None
            )
            raw_code = (
                m.read_memory("snesWorkRam", 0x4000, 0x0400)
                if checkpoint_packed8 is None
                else None
            )
            raw_x = (
                m.read_memory("snesWorkRam", 0x4400, 0x0400)
                if checkpoint_packed8 is None
                else None
            )
            removed = None
            candidate_codes: list[tuple[int, int]] = []
            if checkpoint_packed8 is not None:
                for cursor in range(0, len(checkpoint_packed8), 8):
                    source_offset = int.from_bytes(
                        checkpoint_packed8[cursor : cursor + 2], "little"
                    )
                    raw_code_word = int.from_bytes(
                        checkpoint_packed8[cursor + 4 : cursor + 6], "big"
                    )
                    code = raw_code_word & 0x3FFF
                    if raw_code_word != 0xFFFF and code:
                        candidate_codes.append((source_offset, code))
            else:
                assert raw_y is not None and raw_code is not None and raw_x is not None
                for source_offset in range(0, 0x0400, 2):
                    if not 0 < raw_y[source_offset + 1] < 0xF0:
                        continue
                    x_color = int.from_bytes(
                        raw_x[source_offset : source_offset + 2], "big"
                    )
                    sx = x_color & 0x01FF
                    if 0x0100 <= sx < 0x01F0:
                        continue
                    raw_code_word = int.from_bytes(
                        raw_code[source_offset : source_offset + 2], "big"
                    )
                    code = raw_code_word & 0x3FFF
                    if raw_code_word != 0xFFFF and code:
                        candidate_codes.append((source_offset, code))
            for source_offset, code in candidate_codes:
                hash_offset = ((code * 3) & 0x03FF) * 2
                for _ in range(1024):
                    cached = int.from_bytes(
                        m.read_memory("snesWorkRam", 0x5000 + hash_offset, 2),
                        "little",
                    )
                    if cached == code:
                        m.write_memory(
                            "snesWorkRam", 0x5000 + hash_offset, "0000"
                        )
                        removed = {
                            "manifest_source_offset": source_offset,
                            "code": code,
                            "hash_offset": hash_offset,
                        }
                        break
                    if cached == 0:
                        break
                    hash_offset = (hash_offset + 2) & 0x07FF
                if removed is not None:
                    break
            if removed is None:
                raise RuntimeError("could not remove a live code for full-cache exercise")
            m.write_memory("snesWorkRam", 0x00DE, "8000")
            m.write_memory("snesWorkRam", 0x89CE, "0000")
            full_cache_intervention = {
                "slot_count": 128,
                "reclaimed_slot_count": 0,
                "removed_live_hash_entry": removed,
            }
        manifest_intervention = None
        if (
            args.candidate_y_manifest
            or args.candidate_yx_manifest
            or args.candidate_packed_manifest
        ) and name == "candidate":
            packed8_source = None
            packed8_offsets: list[int] = []
            if args.candidate_packed_manifest:
                checkpoint_encoded_length = int.from_bytes(
                    m.read_memory("snesWorkRam", 0x89BA, 2), "little"
                )
                checkpoint_length = checkpoint_encoded_length & 0x7FFF
                if (
                    checkpoint_encoded_length & 0x8000
                    and checkpoint_length <= 0x0400
                    and checkpoint_length % 8 == 0
                ):
                    source = m.read_memory(
                        "snesWorkRam", 0xBC00, checkpoint_length
                    )
                    packed8_offsets = [
                        int.from_bytes(source[cursor : cursor + 2], "little")
                        for cursor in range(0, checkpoint_length, 8)
                    ]
                    if all(
                        offset <= 0x03FE and offset & 1 == 0
                        for offset in packed8_offsets
                    ):
                        packed8_source = source
            raw_y = m.read_memory("snesWorkRam", 0x3000, 0x0400)
            raw_code = (
                m.read_memory("snesWorkRam", 0x4000, 0x0400)
                if args.candidate_packed_manifest
                else None
            )
            raw_x = (
                m.read_memory("snesWorkRam", 0x4400, 0x0400)
                if args.candidate_yx_manifest or args.candidate_packed_manifest
                else None
            )
            offsets = list(packed8_offsets) if packed8_source is not None else []
            if packed8_source is None:
                for offset in range(0, 0x0400, 2):
                    if raw_code is not None:
                        code = int.from_bytes(raw_code[offset : offset + 2], "big")
                        if code == 0xFFFF or code & 0x3FFF == 0:
                            continue
                    if not 0 < raw_y[offset + 1] < 0xF0:
                        continue
                    if raw_x is not None:
                        x_color = int.from_bytes(raw_x[offset : offset + 2], "big")
                        sx = x_color & 0x01FF
                        if 0x0100 <= sx < 0x01F0:
                            continue
                    offsets.append(offset)
                    if args.candidate_packed_manifest and len(offsets) == 128:
                        break
            if args.candidate_packed_manifest:
                if packed8_source is not None:
                    manifest = b"".join(
                        packed8_source[cursor + 2 : cursor + 8]
                        for cursor in range(0, len(packed8_source), 8)
                    )
                else:
                    assert raw_code is not None and raw_x is not None
                    records = bytearray()
                    for offset in offsets:
                        records.extend(raw_y[offset : offset + 2])
                        records.extend(raw_code[offset : offset + 2])
                        records.extend(raw_x[offset : offset + 2])
                    manifest = bytes(records)
                encoded_length = 0x8000 | len(manifest)
            else:
                manifest = b"".join(
                    offset.to_bytes(2, "little") for offset in offsets
                )
                encoded_length = len(manifest)
            m.write_memory("snesWorkRam", 0xBC00, manifest.hex())
            m.write_memory(
                "snesWorkRam", 0x89BA, encoded_length.to_bytes(2, "little").hex()
            )
            if m.read_memory("snesWorkRam", 0xBC00, len(manifest)) != manifest:
                raise RuntimeError("candidate: synthesized manifest did not verify")
            manifest_intervention = {
                "source": (
                    "checkpoint packed offset/Y/code/X records with offsets removed"
                    if packed8_source is not None
                    else "coherent $7E:3000/$4000/$4400 OBJ caches"
                    if args.candidate_packed_manifest
                    else "coherent $7E:3000 OBJ-Y and $7E:4400 OBJ-X caches"
                    if args.candidate_yx_manifest
                    else "coherent $7E:3000 OBJ-Y cache"
                ),
                "qualification": (
                    "code/Y/X with 128-object cap"
                    if args.candidate_packed_manifest
                    else "Y/X"
                    if args.candidate_yx_manifest
                    else "Y"
                ),
                "format": "packed-y-code-x" if args.candidate_packed_manifest else "offset-list",
                "destination": "7EBC00",
                "entries": len(offsets),
                "length": len(manifest),
                "encoded_length": encoded_length,
                "sha256": digest(manifest),
            }
        set_snes_entry(m, entry)

        return_hook = m.add_exec_hook(RETURN_STUB, cpu_type="Snes")
        m.drain_notifications(timeout=0.05)
        start_cycles = int(m.get_cpu_state("Snes")["cycleCount"])
        hit = m.run_until(max_frames=20, hook_handle=return_hook)
        m.pause()
        end_cycles = int(m.get_cpu_state("Snes")["cycleCount"])
        cpu = m.get_cpu_state("Snes")
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"{name}: OBJ call did not return: {hit!r}; cpu={cpu!r}"
            )
        pc = (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))
        if pc != RETURN_STUB:
            # The return hook is the completion proof.  A long synthetic draw
            # can reach the stub exactly as an already-latched NMI vectors;
            # normalize both variants back to the private spin PC before the
            # post-call PPU settling comparison instead of making that race a
            # false renderer failure.
            set_snes_entry(m, RETURN_STUB)
            normalized = m.get_cpu_state("Snes")
            normalized_pc = (
                int(normalized.get("k", 0)) << 16
            ) | int(normalized.get("pc", 0))
            if normalized_pc != RETURN_STUB:
                raise RuntimeError(
                    f"{name}: could not normalize post-hook PC "
                    f"{pc:#08x}->{normalized_pc:#08x}"
                )

        region_bytes = {
            "bank_to_palette": m.read_memory("snesWorkRam", 0x8580, 0x0020),
            "oam_staging": m.read_memory("snesWorkRam", 0x8600, 0x0220),
            "ppu_oam": m.read_memory("snesSpriteRam", 0x0000, 0x0220),
            "cgram_staging": m.read_memory("snesWorkRam", 0x8000, 0x0200),
            "ppu_cgram": m.read_memory("snesCgRam", 0x0000, 0x0200),
            "obj_hash": m.read_memory("snesWorkRam", 0x5000, 0x1000),
            "obj_tile_staging": m.read_memory("snesWorkRam", 0xB000, 0x4000),
            "obj_vram": m.read_memory("snesVideoRam", 0x8000, 0x8000),
            "full_vram": m.read_memory("snesVideoRam", 0x0000, 0x10000),
        }
        regions = {}
        for label, data in region_bytes.items():
            target = args.output / f"{name}-{label}.bin"
            target.write_bytes(data)
            regions[label] = {
                "path": str(target),
                "length": len(data),
                "sha256": digest(data),
            }

        # The two routines finish at different scanline positions, and their
        # forced-blank DMA pulses can therefore leave different *current-frame*
        # debugger composites even when every resulting PPU byte is identical.
        # Advance two interrupt-free frames from the common spin PC before the
        # visual comparison; this is outside the local cycle measurement.
        m.remove_hook(return_hook)
        screenshot_settle = m.run_frames(2)
        m.pause()
        ppu_state = m.get_ppu_state()
        dma_state = m.tool("read_dma_state")
        oam_render_response = m.render_oam(mode="positioned", scale=1, format="path")
        oam_render = args.output / f"{name}-oam.png"
        shutil.copy2(Path(oam_render_response["path"]), oam_render)
        screenshot_response = m.take_screenshot(format="path")
        screenshot = args.output / f"{name}.png"
        shutil.copy2(Path(screenshot_response["path"]), screenshot)
        return {
            "rom": str(selected_rom),
            "rom_sha256": sha256(selected_rom),
            "entry": entry,
            "return_pc": pc,
            "cycles": end_cycles - start_cycles,
            "post_hook_pc": pc,
            "hit": hit,
            "mirror_intervention": {
                "length": VIDEO_WRAM_LENGTH,
                "differing_bytes": sum(
                    left != right for left, right in zip(old_mirror, rom_mirror)
                ),
                "sha256": digest(rom_mirror),
            },
            "interrupt_quiesce": interrupt_quiesce,
            "full_cache_intervention": full_cache_intervention,
            "manifest_intervention": manifest_intervention,
            "regions": regions,
            "screenshot_settle": screenshot_settle,
            "ppu_state": ppu_state,
            "dma_state": dma_state,
            "oam_render": {
                "path": str(oam_render),
                "sha256": sha256(oam_render),
                "response": oam_render_response,
            },
            "screenshot": {
                "path": str(screenshot),
                "sha256": sha256(screenshot),
                "response": screenshot_response,
            },
        }


def main() -> int:
    args = parse_args()
    if args.force_cold_obj_cache and args.force_full_obj_cache:
        raise SystemExit(
            "--force-cold-obj-cache and --force-full-obj-cache are mutually exclusive"
        )
    selected_candidate_manifests = sum(
        (
            args.candidate_y_manifest,
            args.candidate_yx_manifest,
            args.candidate_packed_manifest,
        )
    )
    if selected_candidate_manifests > 1:
        raise SystemExit(
            "candidate manifest synthesis options are mutually exclusive"
        )
    if (
        selected_candidate_manifests
    ) and args.candidate_rom is None:
        raise SystemExit("candidate manifest synthesis requires --candidate-rom")
    if args.allow_cache_remap and args.candidate_rom is None:
        raise SystemExit("--allow-cache-remap requires --candidate-rom")
    paths = [args.rom, args.state, args.nexen]
    if args.candidate_rom is not None:
        paths.append(args.candidate_rom)
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.mkdir(parents=True, exist_ok=False)

    if args.candidate_rom is None:
        specs = [
            (name, entry, args.rom)
            for name, entry in ENTRIES.items()
        ]
    else:
        specs = [
            ("baseline", ENTRIES["fast"], args.rom),
            ("candidate", ENTRIES["fast"], args.candidate_rom),
        ]
    variants = {
        name: run_variant(name, entry, args, args.port + index, rom)
        for index, (name, entry, rom) in enumerate(specs)
    }
    left_name, right_name = (specs[0][0], specs[1][0])
    comparisons = {}
    for label in variants[left_name]["regions"]:
        left = Path(variants[left_name]["regions"][label]["path"]).read_bytes()
        right = Path(variants[right_name]["regions"][label]["path"]).read_bytes()
        comparisons[label] = {
            "equal": left == right,
            "differing_bytes": sum(a != b for a, b in zip(left, right)),
            "first_differing_offsets": differing_offsets(left, right),
        }
        if args.candidate_rom is not None and label == "obj_tile_staging":
            comparisons[label]["gating"] = False
            comparisons[label]["reason"] = (
                "candidate uploads native records directly; intermediate WRAM staging "
                "is intentionally no longer an output contract"
            )
        if args.allow_cache_remap and label in {
            "obj_hash",
            "oam_staging",
            "ppu_oam",
            "obj_vram",
            "full_vram",
        }:
            comparisons[label]["gating"] = False
            comparisons[label]["reason"] = (
                "physical OBJ cache slots and the OAM tile numbers that address them "
                "may be remapped; exact non-OBJ VRAM and positioned OAM pixels gate "
                "the resulting visible state"
            )
    if args.allow_cache_remap:
        left_vram = Path(
            variants[left_name]["regions"]["full_vram"]["path"]
        ).read_bytes()
        right_vram = Path(
            variants[right_name]["regions"]["full_vram"]["path"]
        ).read_bytes()
        left_non_obj = left_vram[:0x8000]
        right_non_obj = right_vram[:0x8000]
        comparisons["non_obj_vram"] = {
            "equal": left_non_obj == right_non_obj,
            "differing_bytes": sum(
                old != new for old, new in zip(left_non_obj, right_non_obj)
            ),
            "first_differing_offsets": differing_offsets(
                left_non_obj, right_non_obj
            ),
            "reason": (
                "the BG/non-OBJ half of VRAM remains an exact gate while only the "
                "physical OBJ cache half may be remapped"
            ),
        }
    comparisons["screenshot"] = {
        "equal": (
            variants[left_name]["screenshot"]["sha256"]
            == variants[right_name]["screenshot"]["sha256"]
        ),
        "gating": False,
        "reason": (
            "live composite retains forced-blank scanline history and is sampled at "
            "different cycle positions; exact PPU bytes/state and positioned OAM render gate"
        ),
        f"{left_name}_sha256": variants[left_name]["screenshot"]["sha256"],
        f"{right_name}_sha256": variants[right_name]["screenshot"]["sha256"],
    }
    comparisons["oam_render"] = {
        "equal": (
            variants[left_name]["oam_render"]["sha256"]
            == variants[right_name]["oam_render"]["sha256"]
        ),
        f"{left_name}_sha256": variants[left_name]["oam_render"]["sha256"],
        f"{right_name}_sha256": variants[right_name]["oam_render"]["sha256"],
    }
    comparisons["ppu_state"] = {
        "equal": stable_ppu_state(variants[left_name]["ppu_state"])
        == stable_ppu_state(variants[right_name]["ppu_state"]),
        "ignored_sampling_fields": ["frameCount", "scanline"],
    }
    comparisons["dma_state"] = {
        "equal": variants[left_name]["dma_state"] == variants[right_name]["dma_state"],
    }
    all_equal = all(
        item["equal"]
        for item in comparisons.values()
        if item.get("gating", True)
    )
    result = {
        "scope": (
            "same-checkpoint cross-ROM fast-OBJ differential; not FPS"
            if args.candidate_rom is not None
            else "same-checkpoint direct 5A22 old-vs-fast OBJ differential; not FPS"
        ),
        "force_cold_obj_cache": args.force_cold_obj_cache,
        "force_full_obj_cache": args.force_full_obj_cache,
        "allow_cache_remap": args.allow_cache_remap,
        "candidate_y_manifest": args.candidate_y_manifest,
        "candidate_yx_manifest": args.candidate_yx_manifest,
        "candidate_packed_manifest": args.candidate_packed_manifest,
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "candidate_rom": (
            str(args.candidate_rom.resolve()) if args.candidate_rom is not None else None
        ),
        "candidate_rom_sha256": (
            sha256(args.candidate_rom) if args.candidate_rom is not None else None
        ),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "variants": variants,
        "comparisons": comparisons,
        "all_equal": all_equal,
        "local_cycle_delta": variants[left_name]["cycles"] - variants[right_name]["cycles"],
    }
    result_path = args.output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "all_equal": all_equal,
                f"{left_name}_cycles": variants[left_name]["cycles"],
                f"{right_name}_cycles": variants[right_name]["cycles"],
                "results": str(result_path),
            },
            sort_keys=True,
        )
    )
    return 0 if all_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
