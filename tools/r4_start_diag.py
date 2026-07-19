#!/usr/bin/env python3
"""R4 follow-up: why does the round-start $32 send not fire on the port?

Arcade truth (MAME): the sender at $8e18 (`move.w #$32,-(sp); jsr $2d8a`) is
guarded at $8e0a by `move.w $1cca(a5),d2 / cmpi.w #4 / bne skip`.  $1cca is a
sound-state cell: boot writes 4 ($41c4) then 3 ($44ee); the coin handler
($4540) restores 4, which arms the round-start send.

This script cold-boots the fixed ROM, drives the fast coin@40/start@73 path,
logs every change of the $f01cc0-$f01cd0 region, and once gameplay begins arms
a PC-freeze at $8e0a (the guard read) to capture d-regs + $1cca at decision
time if the guard code is ever reached.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

RING_WPTR = 0x401C40
SND_STATE = 0x401CC0  # 68K $f01cc0 (watch 16 bytes; $1cca is +0x0a)
CIN_STATE = 0x401C48  # 68K $f01c48-$f01c6f C-Chip input/status block ($1c4e = start, active-low bit7)
REQ_STATE = 0x402920  # 68K $f02920-$f0293f music-engine state cells ($2936 = request bits)
COIN = 0x2000
START = 0x1000


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    p.add_argument("--mesen", type=Path,
                   default=Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen"))
    p.add_argument("--port", type=int, default=7475)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--gameplay-ticks", type=int, default=200)
    p.add_argument("--freeze-pc", type=lambda v: int(v, 16), default=0x8E0A)
    p.add_argument("--disarm", action="store_true",
                   help="Zero the accelerator gates ($072E/$071A/$073A) just "
                        "before the start press (pure interpretation).")
    p.add_argument("--disarm-gates", type=str, default="",
                   help="Comma-separated IRAM gate addresses (hex) to zero "
                        "pre-start instead of all three, e.g. '071A'.")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
    os.environ["PATH"] = "/home/chad/.dotnet8:" + os.environ.get("PATH", "")

    out = (args.output / "start_diag.jsonl").open("w")

    def emit(event: str, **fields):
        out.write(json.dumps({"event": event, "wall": time.time(), **fields}) + "\n")
        out.flush()

    def le16(b: bytes) -> int:
        return b[0] | (b[1] << 8)

    with McpSession(rom=args.rom.resolve(), mesen=args.mesen, cwd=ROOT,
                    port=args.port, boot_wait=6.0, socket_timeout=300.0,
                    stderr_log=args.output / "emulator.stderr.log") as m:
        stage = "boot"
        stage_mark = 0
        total = 0
        frozen_seen = False
        last16 = le16(m.read_memory("Sa1Memory", 0x0760, 2))
        snd_prev = b""
        cin_prev = b""
        req_prev = b""
        wptr_prev = 0

        def poll():
            nonlocal last16, total, snd_prev, cin_prev, req_prev, wptr_prev
            m.pause()
            state = m.get_state()
            t16 = le16(m.read_memory("Sa1Memory", 0x0760, 2))
            total_now = (t16 - last16) & 0xFFFF
            last16 = t16
            nonlocal_total(total_now)
            snd = m.read_memory("snesMemory", SND_STATE, 16)
            wptr = int.from_bytes(m.read_memory("snesMemory", RING_WPTR, 4), "big")
            if snd != snd_prev:
                emit("snd_state", tick=total, stage=stage,
                     frame=state.get("frameCount"), hex=snd.hex(),
                     v1cca=(snd[0x0A] << 8) | snd[0x0B])
            if wptr != wptr_prev:
                emit("wptr", tick=total, stage=stage, wptr=f"{wptr:08x}")
            cin = m.read_memory("snesMemory", CIN_STATE, 0x28)
            # Mask the free-running per-frame counter/rotator cells ($1c56-$1c5f)
            cin_key = cin[:0x0E] + b"\0" * 10 + cin[0x18:]
            if cin_key != cin_prev:
                emit("cin_state", tick=total, stage=stage, hex=cin.hex(),
                     v1c4e=cin[0x06], v1c4f=cin[0x07], v1c53=cin[0x0B])
                cin_prev = cin_key
            req = m.read_memory("snesMemory", REQ_STATE, 0x20)
            if req != req_prev:
                emit("req_state", tick=total, stage=stage, hex=req.hex(),
                     v2936=(req[0x16] << 8) | req[0x17])
                req_prev = req
            snd_prev, wptr_prev = snd, wptr
            frozen = le16(m.read_memory("Sa1Memory", 0x0712, 2))
            sample = {"tick": total, "stage": stage,
                      "frame": state.get("frameCount"), "frozen": frozen,
                      "task_mask": le16(m.read_memory("snesMemory", 0x400002, 2))}
            emit("sample", **sample)
            m.resume()
            return sample

        def nonlocal_total(delta):
            nonlocal total
            total += delta

        def set_input(v: int):
            m.write_memory("snesMemory", 0x410002, v.to_bytes(2, "little").hex())
            emit("input", stage=stage, value=v, tick=total)

        s = poll()
        while True:
            if stage == "boot":
                latch = le16(m.read_memory("Sa1Memory", 0x0768, 2))
                if latch != 0:
                    emit("armed", tick=total, frame=s["frame"])
                    stage = "attract"; stage_mark = total
            elif stage == "attract" and total - stage_mark >= 40:
                stage = "coin1_hold"; stage_mark = total; set_input(COIN)
            elif stage == "coin1_hold" and total - stage_mark >= 8:
                stage = "coin1_gap"; stage_mark = total; set_input(0)
            elif stage == "coin1_gap" and total - stage_mark >= 7:
                stage = "coin2_hold"; stage_mark = total; set_input(COIN)
            elif stage == "coin2_hold" and total - stage_mark >= 8:
                stage = "coin2_gap"; stage_mark = total; set_input(0)
            elif stage == "coin2_gap" and total - stage_mark >= 7:
                # Arm the PC-freeze BEFORE the start press: the requester fires
                # during the hold (arcade: start-down + 1 frame).
                m.pause()
                m.write_memory("Sa1Memory", 0x0710,
                               args.freeze_pc.to_bytes(2, "little").hex())
                m.write_memory("Sa1Memory", 0x0716, "0000")
                gate_addrs = [0x072E, 0x071A, 0x073A] if args.disarm else [
                    int(g, 16) for g in args.disarm_gates.split(",") if g]
                if gate_addrs:
                    for addr in gate_addrs:
                        m.write_memory("Sa1Memory", addr, "0000")
                    emit("gates_disarmed", tick=total,
                         gates=[f"{a:04x}" for a in gate_addrs])
                m.resume()
                emit("freeze_armed", pc=f"{args.freeze_pc:04x}", tick=total)
                stage = "start_hold"; stage_mark = total; set_input(START)
            elif stage == "start_hold" and total - stage_mark >= 10:
                stage = "gameplay"; stage_mark = total; set_input(0)
            elif stage == "gameplay":
                if total - stage_mark >= args.gameplay_ticks:
                    break
            # Freeze can hit in any stage; while frozen the tick counter is
            # parked, so handle it before stage-tick arithmetic can stall.
            if s["frozen"] == 1 and not frozen_seen:
                frozen_seen = True
                m.pause()
                dp = m.read_memory("Sa1Memory", 0x0000, 0xB0)
                ring = m.read_memory("Sa1Memory", 0x0400, 0x200)
                ring_ptr = le16(dp[0x48:0x4A])
                snd = m.read_memory("snesMemory", SND_STATE, 16)
                cin = m.read_memory("snesMemory", CIN_STATE, 0x28)
                a6 = int.from_bytes(dp[0x38:0x3C], "little")
                frame_local = b""
                if 0xF00000 <= a6 <= 0xF03FF6:
                    frame_local = m.read_memory(
                        "snesMemory", 0x400000 + (a6 - 0xF00000) - 8, 16)
                regs = {f"d{i}": int.from_bytes(dp[i*4:i*4+4], "little")
                        for i in range(8)}
                regs.update({f"a{i}": int.from_bytes(dp[0x20+i*4:0x20+i*4+4],
                                                     "little") for i in range(8)})
                ccr = {"Z": le16(dp[0x60:0x62]), "C": le16(dp[0x6E:0x70]),
                       "N": le16(dp[0x70:0x72]), "V": le16(dp[0x72:0x74]),
                       "X": le16(dp[0xA2:0xA4])}
                # last 16 interpreted PCs, newest last
                trail = []
                for i in range(16, 0, -1):
                    off = (ring_ptr - 4 * i) & 0x1FF
                    trail.append(f"{le16(ring[off+2:off+4]):02x}"
                                 f"{le16(ring[off:off+2]):04x}")
                emit("frozen", tick=total, pc_lo=le16(dp[0x40:0x42]),
                     pc_bank=le16(dp[0x42:0x44]), regs=regs, ccr=ccr,
                     pc_trail=trail, dp_hex=dp.hex(),
                     rom_6abc=m.read_memory("snesMemory", 0xC16ABC, 2).hex(),
                     snd_hex=snd.hex(), cin_hex=cin.hex(),
                     frame_local_hex=frame_local.hex(),
                     v1cca=(snd[0x0A] << 8) | snd[0x0B])
                m.write_memory("Sa1Memory", 0x0714, "0100")  # release
                m.resume()
            time.sleep(3.0)
            s = poll()

        emit("final", tick=total, stage=stage, frozen_seen=frozen_seen)
        print(json.dumps({"frozen_seen": frozen_seen, "tick": total}))
    out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
