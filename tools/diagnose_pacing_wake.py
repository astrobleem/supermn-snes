#!/usr/bin/env python3
"""Trace the S-CPU/SA-1 pacing wake handshake from a retained state.

Diagnostic only: load one save state, install a small set of S-CPU exec hooks
and S-CPU/SA-1 write hooks around the $0818 pacing rendezvous, advance a few
frames, and retain only compact hook events plus final scheduler bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from collections import deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_EMULATOR = ROOT / "tools" / "mesen211_mcp_controller.sh"


def load_sa1_symbols(path: Path) -> dict[str, int]:
    """Load Poppy bank-zero symbols and map them into SA-1 bank $99."""
    wanted = {
        "lh_0818_paced",
        "lhp_no_clamp",
        "lhp_wait",
        "lhp_epoch_ready",
        "lhp_wai",
        "lhp_release_store_debt",
        "lhp_release_repay",
        "lhp_release_epoch_done",
        "lhp_vtime_release_seam",
        "lh_0818_paced_end",
    }
    found: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        fields = raw.split()
        if len(fields) != 2 or fields[1] not in wanted:
            continue
        bank_text, offset_text = fields[0].split(":", 1)
        if int(bank_text, 16) != 0:
            raise ValueError(f"unexpected escbank5 symbol bank: {raw}")
        found[fields[1]] = 0x990000 | int(offset_text, 16)
    missing = sorted(wanted - found.keys())
    if missing:
        raise ValueError(f"missing escbank5 pacing symbols: {', '.join(missing)}")
    return found


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument(
        "--escbank5-sym",
        type=Path,
        default=ROOT / "src" / "escbank5.sym",
        help="current exact-ROM symbol map used for SA-1 pacing landmarks",
    )
    parser.add_argument("--port", type=int, default=7705)
    parser.add_argument("--frames", type=int, default=4)
    parser.add_argument(
        "--buttons",
        default="0",
        help=(
            "optional held controller mask while tracing; accepts decimal, "
            "0x-prefixed hex, or labels select/start/right/left/up/down/b/y/a/x"
        ),
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="install only IRQ/guard/queue-capture hooks for low-overhead tracing",
    )
    return parser.parse_args()


def configure_runtime(emulator: Path) -> None:
    dotnet8 = "/home/chad/.dotnet8"
    dotnet10 = "/home/chad/.dotnet10"
    selected = dotnet8 if emulator.name == "mesen211_mcp_controller.sh" else dotnet10
    path = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet8, dotnet10)
    ]
    os.environ["DOTNET_ROOT"] = selected
    os.environ["PATH"] = ":".join([selected, dotnet8, dotnet10, *path])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def parse_buttons(text: str) -> int:
    labels = {
        "select": McpSession.BTN_SELECT,
        "start": McpSession.BTN_START,
        "right": McpSession.BTN_RIGHT,
        "left": McpSession.BTN_LEFT,
        "up": McpSession.BTN_UP,
        "down": McpSession.BTN_DOWN,
        "b": McpSession.BTN_B,
        "y": McpSession.BTN_Y,
        "a": McpSession.BTN_A,
        "x": McpSession.BTN_X,
    }
    value = 0
    for raw in text.replace("+", ",").split(","):
        item = raw.strip().lower()
        if not item or item == "0":
            continue
        if item in labels:
            value |= int(labels[item])
        else:
            value |= int(item, 0)
    return value


def snapshot(m: McpSession) -> dict[str, Any]:
    state = dict(m.get_state())
    snes = dict(m.get_cpu_state("Snes"))
    sa1 = dict(m.get_cpu_state("Sa1"))
    dp = bytes(m.read_memory("Sa1Memory", 0x0000, 0x0100))
    return {
        "frame": int(state.get("frameCount", 0)),
        "snes_pc": ((int(snes.get("k", 0)) & 0xFF) << 16)
        | (int(snes.get("pc", 0)) & 0xFFFF),
        "snes_stop": str(snes.get("stopState", "unknown")),
        "snes_p": int(snes.get("p", -1)),
        "snes_a": int(snes.get("a", -1)),
        "snes_x": int(snes.get("x", -1)),
        "snes_y": int(snes.get("y", -1)),
        "snes_sp": int(snes.get("sp", -1)),
        "snes_d": int(snes.get("d", -1)),
        "snes_dbr": int(snes.get("dbr", -1)),
        "snes_ps": int(snes.get("ps", -1)),
        "sa1_pc": ((int(sa1.get("k", 0)) & 0xFF) << 16)
        | (int(sa1.get("pc", 0)) & 0xFFFF),
        "sa1_stop": str(sa1.get("stopState", "unknown")),
        "pc68k": le16(dp[0x40:0x42]) | ((le16(dp[0x42:0x44]) & 0xFF) << 16),
        "ac": le16(dp[0xAC:0xAE]),
        "aa": le16(dp[0xAA:0xAC]),
        "tick": le16(bytes(m.read_memory("Sa1Memory", 0x0760, 2))),
        "gate_072e": le16(bytes(m.read_memory("Sa1Memory", 0x072E, 2))),
        "gate_0734": le16(bytes(m.read_memory("Sa1Memory", 0x0734, 2))),
        "gate_073a": le16(bytes(m.read_memory("Sa1Memory", 0x073A, 2))),
        "pacing_410120_41013f": bytes(
            m.read_memory("snesMemory", 0x410120, 0x20)
        ).hex(),
        "input_410000_41000f": bytes(
            m.read_memory("snesMemory", 0x410000, 0x10)
        ).hex(),
        "io_4200_421f": bytes(m.read_memory("snesMemory", 0x004200, 0x20)).hex(),
        "nmitimen_4200": int(bytes(m.read_memory("snesMemory", 0x004200, 1))[0]),
        "nmi_busy_7e1f22": int(bytes(m.read_memory("snesMemory", 0x7E1F22, 1))[0]),
        "code_7fa7bc_a7db": bytes(
            m.read_memory("snesMemory", 0x7FA7BC, 0x20)
        ).hex(),
    }


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists: {args.output}")
    args.output.mkdir(parents=True)
    configure_runtime(args.emulator)
    buttons = parse_buttons(args.buttons)
    sa1_exec_hooks = load_sa1_symbols(args.escbank5_sym)
    # These are bank-$00 interpreter/interrupt landmarks, not bank-$99 native
    # helper symbols.  Keep them explicit and label their narrower meaning.
    sa1_exec_hooks.update(
        {
            "sa1_take_irq": 0x00B404,
            "sa1_cop_brk_vector_rti_d13b": 0x00D13B,
        }
    )

    exec_hooks = {
        "pacing_try_wake": 0x7F8E00,
        "pacing_publish_input_scroll": 0x7F8ED0,
        "pacing_after_capture_scroll": 0x7F8ED7,
        "pacing_before_phase_publish": 0x7F8EDA,
        "pacing_after_phase_publish": 0x7F8EDE,
        "pacing_publish_return": 0x7F8EE0,
        "ptw_deadline_due": 0x7F8E2B,
        "ptw_renderer_ownership_guard": 0x7F8E40,
        "ptw_snapshot_queued": 0x7F8E4F,
        "ptw_try_queue2": 0x7F8E5B,
        "ptw_queue_full": 0x7F8E67,
        "ptw_snapshot_direct": 0x7F8E72,
        "ptw_snapshot_busy": 0x7F8E7B,
        "nmi_pacing_wram": 0x7F8F00,
        "nmi_pacing_restore": 0x7F8F31,
        "nmi_pacing_rti": 0x7F8F3F,
        "irq_pacing_wram": 0x7F8F40,
        "nmi_guard_enter": 0x7F8F71,
        "nmi_guard_done": 0x7F8F7B,
        "nmi_guard_exit": 0x7F8F7C,
        "nmi_present_then_wake": 0x7F8FB0,
        "nptw_wake": 0x7F8FCD,
        "rom_pacing_try_wake": 0x008E00,
        "rom_ptw_deadline_due": 0x008E2B,
        "rom_ptw_renderer_ownership_guard": 0x008E40,
        "rom_ptw_snapshot_busy": 0x008E7B,
        "rom_nmi_pacing_wram": 0x008F00,
        "rom_irq_pacing_wram": 0x008F40,
        "rom_nmi_present_then_wake": 0x008FB0,
        "rom_nptw_wake": 0x008FCD,
        "nmi_batch_present_then_wake": 0xE9D160,
        "nmi_batch_present_after_arbitrate": 0xE9D164,
        "nmi_batch_present_after_dispatch": 0xE9D168,
        "nmi_present_arbitrate": 0xE9CF00,
        "nmi_present_arbitrate_after_intake": 0xE9CF04,
        "nmi_present_arbitrate_two_frame": 0xE9CF1D,
        "nmi_present_arbitrate_not_due": 0xE9CF2A,
        "nmi_present_arbitrate_heavy_present": 0xE9CF31,
        "nmi_present_arbitrate_present": 0xE9CF3D,
        "nmi_present_arbitrate_done": 0xE9CF41,
        "bg_scroll_phase_publish": 0xE9C720,
        "bg_scroll_phase_publish_full": 0xE9CF50,
        "bg_scroll_phase_publish_full_return": 0xE9CFC5,
        "bg_scroll_present_init": 0xE9C1A0,
        "nmi_present_before_dma": 0xE9CD20,
        "nmi_gameplay_present": 0xE9CD00,
        "bg_scroll_present_step": 0xE9C200,
        "bg_scroll_present_step_full": 0xE9CD60,
        "bg_scroll_present_early": 0xE9CDB6,
        "bg_scroll_present_negative": 0xE9CDBB,
        "bg_scroll_present_store": 0xE9CDEF,
        "bg_scroll_present_restore": 0xE9CDF6,
        "bg_scroll_present_after_pla": 0xE9CDF7,
        "bg_scroll_present_rtl": 0xE9CDFA,
        "nmi_gameplay_after_scroll_step": 0xE9CD07,
        "nmi_gameplay_after_bg": 0xE9CD0B,
        "nmi_gameplay_after_obj": 0xE9CD0F,
        "nmi_gameplay_return": 0xE9CD10,
        "nmi_bg_reapply": 0xE9CD40,
        "nmi_bg_reapply_after_scroll": 0xE9CD4B,
        "nmi_bg_reapply_return": 0xE9CD51,
        "obj_present_nmi": 0xE9CA80,
        "nmi_obj_tile_batch": 0xE9D000,
        "nmi_obj_tile_batch_end": 0xE9D148,
        "nmi_obj_tile_batch_dispatch": 0xE9D600,
        "nmi_camera_mailbox_intake": 0xE9DA20,
        "nmi_camera_mailbox_resume": 0xE9DA39,
        "nmi_batch_present_arbitrate": 0xE9DA40,
        "nmi_batch_camera_mailbox_intake": 0xE9DA80,
        "render_queue_capture_primary": 0xE9B000,
        "render_queue_capture_primary_rtl": 0xE9B13D,
        "render_queue_capture_secondary": 0xE9B140,
        "render_queue_capture_secondary_rtl": 0xE9B25F,
        "render_queue_replace_latest_clean": 0xE9EA40,
        "render_queue_replace_latest_clean_rtl": 0xE9EA92,
    }
    if args.minimal:
        keep = {
            "irq_pacing_wram",
            "nmi_pacing_wram",
            "nmi_pacing_restore",
            "nmi_pacing_rti",
            "nmi_guard_enter",
            "nmi_guard_done",
            "nmi_guard_exit",
            "pacing_try_wake",
            "pacing_publish_input_scroll",
            "pacing_after_capture_scroll",
            "pacing_before_phase_publish",
            "pacing_after_phase_publish",
            "pacing_publish_return",
            "ptw_deadline_due",
            "ptw_snapshot_queued",
            "ptw_try_queue2",
            "ptw_queue_full",
            "ptw_snapshot_direct",
            "ptw_snapshot_busy",
            "render_queue_capture_primary",
            "render_queue_capture_primary_rtl",
            "render_queue_capture_secondary",
            "render_queue_capture_secondary_rtl",
            "render_queue_replace_latest_clean",
            "render_queue_replace_latest_clean_rtl",
        }
        exec_hooks = {name: address for name, address in exec_hooks.items() if name in keep}
    write_hooks = {
        "write_pacing_arm_410122_snes": ("Snes", 0x410122, 0x410123),
        "write_nmitimen_4200_snes": ("Snes", 0x004200, 0x004200),
        "write_wake_2200_snes": ("Snes", 0x002200, 0x002200),
        "write_sa1_request_2209_sa1": ("Sa1", 0x002209, 0x002209),
        "write_sa1_enable_220a_sa1": ("Sa1", 0x00220A, 0x00220A),
        "write_sa1_ack_220b_sa1": ("Sa1", 0x00220B, 0x00220B),
    }

    result: dict[str, Any] = {
        "scope": "retained-state pacing wake trace; diagnostic only",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "frames": args.frames,
        "buttons": buttons,
        "buttons_arg": args.buttons,
        "hooks": {},
        "events": [],
        "last_events": [],
        "first_event_by_name": {},
        "last_event_by_name": {},
    }
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=0.0,
        socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        result["load_state"] = dict(m.load_state(args.state.resolve()))
        m.pause()
        result["initial"] = snapshot(m)
        handles: dict[int, str] = {}
        for name, address in exec_hooks.items():
            handle = m.add_exec_hook(address, cpu_type="Snes")
            result["hooks"][name] = {"kind": "exec", "handle": handle, "address": f"{address:06X}"}
            handles[handle] = name
        for name, address in sa1_exec_hooks.items():
            handle = m.add_exec_hook(address, cpu_type="Sa1")
            result["hooks"][name] = {
                "kind": "exec",
                "cpu": "Sa1",
                "handle": handle,
                "address": f"{address:06X}",
            }
            handles[handle] = name
        for name, (cpu, start, end) in write_hooks.items():
            handle = m.add_write_hook(start, end_address=end, cpu_type=cpu)
            result["hooks"][name] = {
                "kind": "write",
                "cpu": cpu,
                "handle": handle,
                "start": f"{start:06X}",
                "end": f"{end:06X}",
            }
            handles[handle] = name
        m.drain_notifications(timeout=0.05)
        if buttons:
            result["input_response"] = m.set_input(buttons, args.frames)
        else:
            result["input_response"] = m.run_frames(args.frames)
        m.pause()
        counts: Counter[str] = Counter()
        last_events: deque[dict[str, Any]] = deque(maxlen=512)
        for note in m.drain_notifications(timeout=0.2):
            if note.get("method") != "notifications/mesen/hookFired":
                continue
            params = dict(note.get("params") or {})
            name = handles.get(int(params.get("handle", -1)), "unknown")
            counts[name] += 1
            event = {
                "name": name,
                **{key: params.get(key) for key in sorted(params)},
            }
            if len(result["events"]) < 128:
                result["events"].append(event)
            last_events.append(event)
            result["first_event_by_name"].setdefault(name, event)
            result["last_event_by_name"][name] = event
        result["counts"] = dict(sorted(counts.items()))
        result["last_events"] = list(last_events)
        result["final"] = snapshot(m)
        result["final_state"] = dict(m.save_state(args.output / "final.mss"))
        result["hook_diag"] = m.hook_diag()

    report = args.output / "results.json"
    report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": str(report),
                "counts": result["counts"],
                "initial": result["initial"],
                "final": result["final"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
