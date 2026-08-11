#!/usr/bin/env python3
"""Guard diagnostic cross-ROM checkpoint migration and its write boundary."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tools" / "replay_mame_controller_campaign.py"
SPEC = importlib.util.spec_from_file_location("campaign_rom_migration", CAMPAIGN)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {CAMPAIGN}")
campaign = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = campaign
SPEC.loader.exec_module(campaign)


class FakeSession:
    def __init__(self, wram: bytes, work: bytes | None = None) -> None:
        self.wram = bytearray(wram)
        self.work = bytearray(work if work is not None else bytes(0x10000))
        self.architectural_mutations: list[dict[str, object]] = []
        self.snes_cpu = {"k": 0x80, "pc": 0x8000}

    def read_memory(self, memory_type: str, address: int, length: int) -> bytes:
        if memory_type == "snesWorkRam":
            return bytes(self.wram[address : address + length])
        if memory_type == "snesMemory" and 0x400000 <= address < 0x410000:
            offset = address - 0x400000
            return bytes(self.work[offset : offset + length])
        raise AssertionError(f"unexpected memory read: {memory_type} {address:#x}")

    def write_memory(
        self, memory_type: str, address: int, hex_bytes: str
    ) -> dict[str, object]:
        raw = bytes.fromhex(hex_bytes)
        self.architectural_mutations.append(
            {
                "tool": "write_memory",
                "arguments": {
                    "memoryType": memory_type,
                    "address": address,
                    "hex": hex_bytes,
                },
            }
        )
        if memory_type == "snesWorkRam":
            self.wram[address : address + len(raw)] = raw
        elif memory_type == "snesMemory" and 0x400000 <= address < 0x410000:
            offset = address - 0x400000
            self.work[offset : offset + len(raw)] = raw
        else:
            raise AssertionError(
                f"unexpected memory write: {memory_type} {address:#x}"
            )
        return {"ok": True}

    def get_cpu_state(self, cpu_type: str) -> dict[str, int]:
        if cpu_type != "Snes":
            raise AssertionError(f"unexpected CPU type: {cpu_type}")
        return dict(self.snes_cpu)


def public_snapshot(wram: bytes, work: bytes = b"game-work") -> dict[str, object]:
    return {
        "sa1": {"pc": 0x1234, "k": 0x92},
        "snes": {"pc": 0x8000, "k": 0x80},
        "frame_count": 123,
        "ppu": {"bgMode": 1},
        "sa1_iram_sha256": campaign.digest(b"i"),
        "work_64k_sha256": campaign.digest(work),
        "wram_128k_sha256": campaign.digest(wram),
        "vram_64k_sha256": campaign.digest(b"v"),
        "cgram_512_sha256": campaign.digest(b"c"),
        "oam_544_sha256": campaign.digest(b"o"),
        "spc_ram_64k_sha256": campaign.digest(b"s"),
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="campaign-rom-migration-") as temp:
        directory = Path(temp)
        rom = directory / "candidate.sfc"
        rom_data = bytearray(0x400000)
        source = bytes(
            (index * 17 + 3) & 0xFF
            for index in range(campaign.VIDEO_WRAM_LENGTH)
        )
        start = campaign.VIDEO_WRAM_ROM_OFFSET
        rom_data[start : start + len(source)] = source
        rom.write_bytes(rom_data)

        before_wram = bytes([0xA5]) * 0x20000
        before_work_data = bytearray(0x10000)
        state = campaign.VTIME_STATE_CPU_ADDRESS - 0x400000
        before_work_data[state + 0x00 : state + 0x02] = (0xC71E).to_bytes(
            2, "little"
        )
        before_work_data[state + 0x02 : state + 0x04] = (1).to_bytes(
            2, "little"
        )
        before_work_data[state + 0x06 : state + 0x08] = (4067).to_bytes(
            2, "little"
        )
        before_work_data[state + 0x08 : state + 0x0A] = (1).to_bytes(
            2, "little"
        )
        before_work_data[state + 0x0A : state + 0x0C] = (1282).to_bytes(
            2, "little"
        )
        before_work = bytes(before_work_data)
        fake = FakeSession(before_wram, before_work)
        before_raw = (
            b"iram",
            before_work,
            before_wram,
            b"vram",
            b"cgram",
            b"oam",
            b"spc",
        )
        before_public = public_snapshot(before_wram, before_work)

        refresh = campaign.refresh_video_wram(fake, rom)
        clock = campaign.migrate_vtime_irq_clock(fake)
        after_wram = bytes(fake.wram)
        after_work = bytes(fake.work)
        after_raw = (before_raw[0], after_work, after_wram, *before_raw[3:])
        after_public = public_snapshot(after_wram, after_work)
        report = campaign.validate_video_wram_migration(
            before_public=before_public,
            before_raw=before_raw,
            after_public=after_public,
            after_raw=after_raw,
            selected_rom=rom,
            refresh=refresh,
            mutations=fake.architectural_mutations,
            vtime_clock_migration=clock,
        )
        if report["diagnostic_only"] is not True:
            raise AssertionError("migration lost diagnostic-only classification")
        if report["game_state_write"] is not False:
            raise AssertionError("code refresh was classified as a game write")
        if len(report["architectural_mutations"]) != 4:
            raise AssertionError("expected three code writes plus one clock write")
        if clock["derived"]["interval_start_bucket"] != 2:
            raise AssertionError("tick-14500 interval-start bucket changed")
        if clock["derived"]["completed_phase_bucket"] != 4:
            raise AssertionError("tick-14500 completed phase bucket changed")

        tampered_raw = (*after_raw[:3], b"changed-vram", *after_raw[4:])
        try:
            campaign.validate_video_wram_migration(
                before_public=before_public,
                before_raw=before_raw,
                after_public=after_public,
                after_raw=tampered_raw,
                selected_rom=rom,
                refresh=refresh,
                mutations=fake.architectural_mutations,
                vtime_clock_migration=clock,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("migration accepted an unrelated VRAM change")

        collision = FakeSession(before_wram)
        collision.snes_cpu = {"k": 0x7F, "pc": 0x9000}
        try:
            campaign.refresh_video_wram(collision, rom)
        except RuntimeError as exc:
            if "paused 5A22 instruction" not in str(exc):
                raise
        else:
            raise AssertionError("migration overwrote the paused 5A22 PC")

    print("campaign diagnostic ROM-migration regression: green")


if __name__ == "__main__":
    main()
