#!/usr/bin/env python3
"""Live-fixture MAME/Nexen differential for native collision root $025110.

Organic inputs are captured at the production bank-$97 entry before its
skipped-JSR adapter pushes a return.  The MAME oracle receives the equivalent
real 68000 stack frame and returns to the original-ROM self-loop at $002B16;
the repeating fetch makes MAME's prefetch-skewed PC tap settle at the correct
post-RTS SP.  Nexen runs the same fixture twice: once through the interpreter
from logical PC $025110 with all escapes disabled, and once through the
bank-$97 native root with escapes enabled.  Every D/A register, CCR/mask, and
mapped 16 KiB work-RAM byte is compared.

This is bounded function-semantic and local-cycle evidence, not FPS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import validate_175a0_native as shared
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


base = shared.base
ROOT = shared.ROOT
DEFAULT_ROM = shared.DEFAULT_ROM
DEFAULT_STATE = shared.DEFAULT_STATE
ENTRY_PC = 0x025110
ENTRY_NATIVE = 0x978000
INEXT = 0x00D128
RETURN_PC = 0x002B16
OP_ILLEGAL = 0x00CDED
MAPPED_WORK_SIZE = shared.MAPPED_WORK_SIZE
FULL_WORK_SIZE = shared.FULL_WORK_SIZE
COLLISION_TABLE_OFFSET = 0x3A74
COLLISION_RECORD_SIZE = 0x10
COLLISION_RECORD_COUNT = 31
GUARD_ACTIVE_COUNTS = (0, 1, 16, 17)
SEMANTIC_GUARD_SHAPES = (
    "stage1-spanning-response-clear",
    "stage2-overlap",
    "stage2-word-positive-low-byte-negative",
    "stage2-overlap-before-17th-fallback",
    "stage2-contained-nonzero-response",
    "stage2-second-outer-active",
    "stage2-negative-edge",
    "stage5-positive-outer",
    "stage5-negative-final-slot",
    "stage5-word-positive-low-byte-negative",
    "stage5-byte-positive-high-poison",
    "stage5-byte-negative-clean-high",
    "stage5-byte-carry-high-poison",
    "stage5-final-active-d0-ccr",
    "stage5-final-active-d1-ccr",
)


def ensure_paused(m: base.McpSession) -> None:
    """Pause only when running; a redundant Nexen pause can step the SA-1."""
    if not bool(m.get_state().get("isPaused")):
        m.pause()


def case_work(case: shared.LiveCase) -> bytes:
    """Install the real JSR return at the stack position native will push."""

    pre_push_sp = case.regs["A7"] & 0xFFFFFF
    if (pre_push_sp >> 16) != 0xF0 or (pre_push_sp & 0xFFFF) < 4:
        raise RuntimeError(
            f"{case.name}: unsupported pre-push A7 ${pre_push_sp:06X}"
        )
    work = bytearray(case.work)
    offset = (pre_push_sp - 4) & 0xFFFF
    work[offset : offset + 4] = base.be32(RETURN_PC)
    return bytes(work)


def capture_live_cases(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
    input_buttons: int | None,
    input_frames: int | None,
    stabilize_entry: bool,
) -> list[shared.LiveCase]:
    cases: list[shared.LiveCase] = []
    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as m:
        ensure_paused(m)
        m.load_state(str(state))
        ensure_paused(m)
        entry_original: bytes | None = None
        if stabilize_entry:
            if count != 1:
                raise RuntimeError(
                    "stabilized entry capture currently requires --cases 1"
                )
            # Nexen execution hooks notify before the instruction but may not
            # pause the emulation thread immediately.  $025110 mutates its
            # collision-table input, so a late pause is not a valid entry
            # fixture.  Temporarily replace the first instruction with a
            # side-effect-free BRA -2; the hook can then notify repeatedly
            # while every emulated 68000 register and work-RAM byte remains
            # exactly at the entry seam.
            entry_bank = (ENTRY_NATIVE >> 16) & 0xFF
            entry_offset = ENTRY_NATIVE & 0xFFFF
            rom_offset = (
                (entry_bank - 0x40) * 0x8000
                + (entry_offset & 0x7FFF)
            )
            entry_original = bytes(
                m.read_memory("snesPrgRom", rom_offset, 2)
            )
            m.write_memory("snesPrgRom", rom_offset, "80fe")
        hook = m.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        if input_buttons is not None:
            if input_frames is None:
                m.tool(
                    "set_input",
                    {"port": 0, "buttons": input_buttons, "hold": True},
                )
            else:
                # Legacy Mesen checkpoints must be continued in their owning
                # emulator.  Its controller primitive advances immediately
                # for an explicit frame count and then releases the override,
                # so install the entry hook/stabilizer before driving it.
                m.tool(
                    "set_input",
                    {
                        "port": 0,
                        "buttons": input_buttons,
                        "frames": input_frames,
                    },
                )
        previous_cycles = -1
        try:
            for index in range(count):
                hit = m.run_until(max_frames=180, hook_handle=hook)
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(
                        f"production capture {index} did not reach native entry: "
                        f"{hit!r}"
                    )
                ensure_paused(m)
                cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                if cycles <= previous_cycles:
                    raise RuntimeError("native-entry capture did not advance")
                previous_cycles = cycles
                regs = shared.captured_regs(m)
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
                )
                if (regs["A5"] & 0xFFFFFF) != 0xF00000:
                    raise RuntimeError(
                        f"capture {index}: noncanonical A5 "
                        f"${regs['A5'] & 0xFFFFFF:06X}"
                    )
                tick = shared.be16(work, 0x1C56)
                cases.append(
                    shared.LiveCase(
                        name=f"live-{index:02d}-tick-{tick}",
                        regs=regs,
                        sr=shared.captured_sr(m),
                        work=work,
                        tick=tick,
                        exit_pc=RETURN_PC,
                    )
                )
        finally:
            m.remove_hook(hook)
            if entry_original is not None:
                m.write_memory(
                    "snesPrgRom",
                    rom_offset,
                    entry_original.hex(),
                )
    return cases


def load_cases(fixture_dir: Path, count: int) -> list[shared.LiveCase]:
    cases: list[shared.LiveCase] = []
    metadata_paths = sorted(fixture_dir.glob("case-*.json"))
    if len(metadata_paths) < count:
        raise RuntimeError(
            f"fixture directory has {len(metadata_paths)} cases, need {count}: "
            f"{fixture_dir}"
        )
    for metadata_path in metadata_paths[:count]:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        work = metadata_path.with_suffix(".work.bin").read_bytes()
        if len(work) != FULL_WORK_SIZE:
            raise RuntimeError(
                f"fixture for {metadata_path} is {len(work)} bytes, expected "
                f"{FULL_WORK_SIZE}"
            )
        cases.append(
            shared.LiveCase(
                name=metadata["name"],
                regs={name: int(value) for name, value in metadata["regs"].items()},
                sr=int(metadata["sr"]),
                work=work,
                tick=int(metadata["tick"]),
                exit_pc=RETURN_PC,
            )
        )
    return cases


def derive_guard_cases(seed: shared.LiveCase) -> list[shared.LiveCase]:
    """Create boundary shapes for the guarded collision shortcuts.

    The count cases exercise stage-1 compact-list limits.  Additional cases
    force stage-2 overlap/shape/sign misses and stage-5 active/final-negative
    behavior so both fast exits and pre-write fallbacks are compared to MAME.
    """

    if (seed.regs["A5"] & 0xFFFFFF) != 0xF00000:
        raise RuntimeError(
            f"{seed.name}: guard fixture requires canonical A5=$F00000"
        )
    derived: list[shared.LiveCase] = []
    for active_count in GUARD_ACTIVE_COUNTS:
        work = bytearray(seed.work)
        for slot in range(COLLISION_RECORD_COUNT):
            offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
            work[offset : offset + 2] = b"\x00\x00"
        for slot in range(active_count):
            offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
            work[offset : offset + 2] = b"\x00\x01"
            work[offset + 0x0A : offset + 0x0C] = b"\x00\x00"
        derived.append(
            shared.LiveCase(
                name=f"guard-active-{active_count:02d}-from-{seed.name}",
                regs=dict(seed.regs),
                sr=seed.sr,
                work=bytes(work),
                tick=seed.tick,
                exit_pc=RETURN_PC,
            )
        )

    def add_shape(
        name: str,
        work: bytearray,
        regs: dict[str, int] | None = None,
        sr: int | None = None,
    ) -> None:
        derived.append(
            shared.LiveCase(
                name=f"guard-{name}-from-{seed.name}",
                regs=dict(seed.regs) if regs is None else regs,
                sr=seed.sr if sr is None else sr,
                work=bytes(work),
                tick=seed.tick,
                exit_pc=RETURN_PC,
            )
        )

    # Two ordinary Stage-1 records overlap on both axes, but the inner
    # rectangle spans beyond both vertical edges of the outer.  The original
    # response topology must take its Y-clear branch and clear both stale D
    # bytes.  This is the focused form of the organic tick-9897 fixture that
    # exposed stale collision response bytes surviving the compact pass.
    work = bytearray(seed.work)
    work[0x3734:0x3CC4] = bytes(0x3CC4 - 0x3734)
    outer = COLLISION_TABLE_OFFSET
    inner = outer + COLLISION_RECORD_SIZE
    work[outer : outer + COLLISION_RECORD_SIZE] = bytes.fromhex(
        "000100790086008500A20061F9D60000"
    )
    work[inner : inner + COLLISION_RECORD_SIZE] = bytes.fromhex(
        "00010081008A007A00AB0060072A0000"
    )
    add_shape("stage1-spanning-response-clear", work)

    # Isolate one stage-1 record so that stage 1 itself cannot write it, then
    # force a stage-2 rectangle overlap.  The new stage-2 shortcut must detect
    # the overlap and delegate before the first game-state write.
    work = bytearray(seed.work)
    for slot in range(32):
        offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
        work[offset : offset + 2] = b"\x00\x00"
    inner = COLLISION_TABLE_OFFSET
    outer = 0x3A54
    work[inner : inner + 2] = b"\x00\x01"
    work[inner + 0x0A : inner + 0x0C] = b"\x00\x00"
    work[inner + 0x0E : inner + 0x10] = b"\x00\x00"
    work[inner + 2 : inner + 10] = work[outer + 2 : outer + 10]
    add_shape("stage2-overlap", work)

    # The Stage-2 E filter is a signed word test.  $009E is positive even
    # though its low byte has bit 7 set; XBA alone leaves the 65816 N flag
    # describing that low byte and used to skip this legitimate overlap.
    work = bytearray(seed.work)
    for slot in range(32):
        offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
        work[offset : offset + COLLISION_RECORD_SIZE] = bytes(
            COLLISION_RECORD_SIZE
        )
    inner = COLLISION_TABLE_OFFSET
    outer = 0x3A54
    work[outer : outer + COLLISION_RECORD_SIZE] = bytes.fromhex(
        "000100B200C7006B00A7002300000000"
    )
    work[inner : inner + COLLISION_RECORD_SIZE] = bytes.fromhex(
        "000100C600DE00540084009E0000009E"
    )
    add_shape("stage2-word-positive-low-byte-negative", work)

    # The guarded Stage-2 scan permits at most sixteen qualifying inners.  An
    # overlap before a seventeenth qualifier exercises the dangerous late
    # fallback boundary: the overlap continuation has already written C/D/E,
    # so restarting the generated pass is valid only if the final state still
    # exactly matches one uninterrupted arcade pass.
    work = bytearray(seed.work)
    for slot in range(32):
        offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
        work[offset : offset + COLLISION_RECORD_SIZE] = bytes(
            COLLISION_RECORD_SIZE
        )
    outer = 0x3A54
    work[outer : outer + COLLISION_RECORD_SIZE] = bytes.fromhex(
        "0001006400c8006400c8000101020000"
    )
    for slot in range(17):
        offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
        if slot == 0:
            rectangle = bytes.fromhex("007800b4007800b4")
        else:
            x1 = 0x1000 + slot * 0x20
            x2 = x1 + 0x10
            rectangle = (
                x1.to_bytes(2, "big")
                + x2.to_bytes(2, "big")
                + b"\x10\x00\x10\x10"
            )
        work[offset : offset + COLLISION_RECORD_SIZE] = (
            b"\x00\x01"
            + rectangle
            + b"\x00\xBD"
            + bytes((0x40 + slot, 0x60 + slot))
            + b"\x00\x00"
        )
    add_shape("stage2-overlap-before-17th-fallback", work)

    # A rectangle strictly contained by the outer takes both response-clear
    # branches.  Seed nonzero C/D bytes and a nonzero inner E word: the arcade
    # routine conditions the *outer* clear on outer.E, but always clears the
    # inner response.  This catches both a mistaken inner-E guard and the
    # 65816's lack of a long-addressing STZ instruction.
    work = bytearray(seed.work)
    for slot in range(32):
        offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
        work[offset : offset + 2] = b"\x00\x00"
    work[outer : outer + 2] = b"\x00\x01"
    work[outer + 2 : outer + 10] = bytes.fromhex("006400c8006400c8")
    work[outer + 0x0A : outer + 0x0C] = b"\x00\x23"
    work[outer + 0x0C : outer + 0x0E] = b"\x33\x44"
    work[outer + 0x0E : outer + 0x10] = b"\x00\x60"
    work[inner : inner + 2] = b"\x00\x01"
    work[inner + 2 : inner + 10] = bytes.fromhex("007800b4007800b4")
    work[inner + 0x0A : inner + 0x0C] = b"\x00\x60"
    work[inner + 0x0C : inner + 0x0E] = b"\x55\xAA"
    work[inner + 0x0E : inner + 0x10] = b"\x00\x01"
    add_shape("stage2-contained-nonzero-response", work)

    # A positive second stage-2 outer is outside the specialized one-outer
    # shape and must run the complete generated pass.
    work = bytearray(seed.work)
    work[0x3A64 : 0x3A66] = b"\x00\x01"
    add_shape("stage2-second-outer-active", work)

    # Signed coordinate domains are retained by the generated path.
    work = bytearray(seed.work)
    for slot in range(32):
        offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
        work[offset : offset + 2] = b"\x00\x00"
    work[inner : inner + 2] = b"\x00\x01"
    work[inner + 2 : inner + 4] = b"\xFF\xFF"
    work[inner + 0x0A : inner + 0x0C] = b"\x00\x00"
    work[inner + 0x0E : inner + 0x10] = b"\x00\x00"
    add_shape("stage2-negative-edge", work)

    # Any positive stage-5 outer must reject the all-inactive proof and retain
    # the original inner-loop/call behavior.
    work = bytearray(seed.work)
    work[0x37F4 : 0x37F6] = b"\x00\x01"
    add_shape("stage5-positive-outer", work)

    # The inactive shortcut still has to publish the final TST.W negative CCR
    # when the last narrow slot is negative rather than zero.
    work = bytearray(seed.work)
    work[0x37E4 : 0x37E6] = b"\xFF\xFF"
    add_shape("stage5-negative-final-slot", work)

    # TST.W $E(A2) must use the word sign, not XBA's exchanged-byte sign.
    # $009E is positive as a 68000 word even though its low byte has bit 7
    # set.  One narrow Stage-5 overlap must therefore propagate outer type
    # $8030 into inner.E and inner type $009E into outer.E.
    work = bytearray(seed.work)
    for table, count in (
        (0x3734, 12),
        (0x37F4, 32),
        (0x39F4, 6),
        (0x3A54, 33),
        (0x3C74, 4),
    ):
        for slot in range(count):
            offset = table + slot * COLLISION_RECORD_SIZE
            work[offset : offset + COLLISION_RECORD_SIZE] = bytes(
                COLLISION_RECORD_SIZE
            )
    outer = 0x3734
    inner = 0x3A74
    work[outer : outer + COLLISION_RECORD_SIZE] = bytes.fromhex(
        "000100BF00F7007A0082803000010000"
    )
    work[inner : inner + COLLISION_RECORD_SIZE] = bytes.fromhex(
        "000100D300DC00570088009E0001009E"
    )
    work[0x3CB4 : 0x3CB6] = b"\x00\x00"
    add_shape("stage5-word-positive-low-byte-negative", work)

    def stage5_byte_case(
        name: str,
        *,
        response_c: int,
        d2_word: int,
    ) -> None:
        work = bytearray(seed.work)
        # Make every earlier collision table inactive, then admit exactly one
        # wide Stage-5 outer/inner pair.  Their overlap reaches $025956 but
        # uses outer type $8034 and exchanged E=$0067, so the later call paths
        # are skipped and the byte-sign coordinate decision remains isolated.
        for table, count in (
            (0x3734, 12),
            (0x37F4, 32),
            (0x39F4, 6),
            (0x3A54, 33),
            (0x3C74, 4),
        ):
            for slot in range(count):
                offset = table + slot * COLLISION_RECORD_SIZE
                work[offset : offset + 2] = b"\x00\x00"
        work[0x1CCC : 0x1CCE] = b"\x00\x00"
        work[0x3CB4 : 0x3CB6] = b"\x00\x00"

        outer = 0x37F4
        inner = 0x39F4
        work[outer : outer + 0x10] = bytes.fromhex(
            "000101000120008000a08034"
        ) + bytes((response_c & 0xFF, 0x01, 0x00, 0x00))
        work[inner : inner + 0x10] = bytes.fromhex(
            "000101000120008000a0006700000000"
        )
        regs = dict(seed.regs)
        regs["D2"] = (regs["D2"] & 0xFFFF0000) | (d2_word & 0xFFFF)
        add_shape(name, work, regs)

    # $3F+$40=$7F is positive as a byte even though the preserved D2 high byte
    # is negative.  $40+$40=$80 is negative as a byte even though a widened
    # word result is positive.  Together they force both sides of TST.B.
    stage5_byte_case(
        "stage5-byte-positive-high-poison",
        response_c=0x3F,
        d2_word=0x8000,
    )
    stage5_byte_case(
        "stage5-byte-negative-clean-high",
        response_c=0x40,
        d2_word=0x0000,
    )
    # $C0+$40 wraps to zero and sets X while preserving D2's high byte.  The
    # following TST.B clears NZVC but must retain that X; the old word-width
    # lowering instead produced $8000, took the negative branch, and lost X.
    stage5_byte_case(
        "stage5-byte-carry-high-poison",
        response_c=0xC0,
        d2_word=0x7F00,
    )

    def stage5_final_outer_case(name: str, *, response_d: int) -> None:
        work = bytearray(seed.work)
        for table, count in (
            (0x3734, 12),
            (0x37F4, 32),
            (0x39F4, 6),
            (0x3A54, 33),
            (0x3C74, 4),
        ):
            for slot in range(count):
                offset = table + slot * COLLISION_RECORD_SIZE
                work[offset : offset + COLLISION_RECORD_SIZE] = bytes(
                    COLLISION_RECORD_SIZE
                )
        work[0x1CCC : 0x1CCE] = b"\x00\x00"
        work[0x3CB4 : 0x3CB6] = b"\x00\x00"

        # The final narrow outer is the last record whose initial TST.W can
        # remain architecturally visible at RTS.  Make it overlap the first
        # narrow inner and poison incoming NZVC so stale publication cannot
        # accidentally agree with MAME.
        outer = 0x37E4
        inner = 0x3A74
        work[outer : outer + COLLISION_RECORD_SIZE] = (
            bytes.fromhex("000101000120008000a08034")
            + bytes((0x3F, response_d & 0xFF, 0x00, 0x00))
        )
        work[inner : inner + COLLISION_RECORD_SIZE] = bytes.fromhex(
            "000101000120008000a0006700000000"
        )
        poisoned_sr = (seed.sr & ~0x0F) | 0x0F
        add_shape(name, work, sr=poisoned_sr)

    # D=0 exits after TST.B $D(A0); D=1 reaches the $25956 adjustment and
    # exits after the equal CMP.W #$8034.  Both are positive-final-slot paths
    # that bypass the nonpositive final-TST repair.
    stage5_final_outer_case("stage5-final-active-d0-ccr", response_d=0)
    stage5_final_outer_case("stage5-final-active-d1-ccr", response_d=1)
    return derived


def derive_x_variants(cases: list[shared.LiveCase]) -> list[shared.LiveCase]:
    """Replay every semantic shape with incoming MC68000 X clear and set."""

    variants: list[shared.LiveCase] = []
    for case in cases:
        for x in (0, 1):
            variants.append(
                shared.LiveCase(
                    name=f"{case.name}-x{x}",
                    regs=dict(case.regs),
                    sr=(case.sr & ~0x10) | (x << 4),
                    work=case.work,
                    tick=case.tick,
                    exit_pc=case.exit_pc,
                )
            )
    return variants


def mame_result(session: base.MameSession, case: shared.LiveCase) -> base.Result:
    work = case_work(case)
    pre_push_sp = case.regs["A7"] & 0xFFFFFF
    entry_sp = (pre_push_sp - 4) & 0xFFFFFF

    session.pause()
    session.write_block(0xF00000, work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    # $025110 contains no SR-mask writer.  Mask unrelated real IRQ6 delivery
    # during the injected span, then restore the organic mask on readback.
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", entry_sp)
    session.set_reg("SP", entry_sp)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=RETURN_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=pre_push_sp,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach settled return loop ${RETURN_PC:06X} "
            f"for {case.name}: {captured!r}"
        )
    raw = captured["registers"]
    regs = {name: raw[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    regs["A7"] = raw["SP"] & 0xFFFFFFFF
    sr = ((raw["SR"] & 0xFFFF) & ~0x0700) | (case.sr & 0x0700)
    return base.Result(regs, sr, bytes.fromhex(captured["hex"]))


def wait_for_file(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise RuntimeError(f"save state was not flushed: {path}")


def seed_vtime_active_state(m: base.McpSession) -> None:
    """Seed the opt-in VTIME clock for a no-deadline local fixture replay.

    The normal harness deliberately starts direct at either ``inext`` or the
    bank-$97 native entry, so it bypasses the ordinary fetch gateway that owns
    VTIME initialization.  This synthetic state is deliberately farther than
    one vblank from expiry: it proves the active native ledger's stack/CCR/RAM
    path without pretending to be a hardware-phase timing run.
    """

    payload = bytearray(0x1A)
    payload[0x00:0x02] = (0xC71E).to_bytes(2, "little")
    payload[0x02:0x04] = (1).to_bytes(2, "little")
    payload[0x04:0x06] = (5).to_bytes(2, "little")
    payload[0x06:0x08] = (0x1012).to_bytes(2, "little")
    payload[0x08:0x0A] = (1).to_bytes(2, "little")
    m.write_memory(base.SNES_SPACE, 0x404000, payload.hex())


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: shared.LiveCase,
    *,
    native: bool,
    pre_state: Path | None,
    choke_gate: int = 0,
    boundary_tool: str | None = None,
    vtime_active: bool = False,
) -> tuple[base.Result, dict | None]:
    work = case_work(case)
    m.load_state(str(nat))
    ensure_paused(m)

    pre_push_sp = case.regs["A7"] & 0xFFFFFF
    launch_regs = dict(case.regs)
    if not native:
        launch_regs["A7"] = (pre_push_sp - 4) & 0xFFFFFFFF
    reg_blob = b"".join(
        base.le32(launch_regs[name]) for name in base.REG_NAMES
    )
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(work), 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            work[offset : offset + 0x4000].hex(),
        )
    shared.park_snes_cpu(m)

    flags = case.sr & base.CCR_MASK
    shared.write_u16(m, 0x6E, flags & 1)
    shared.write_u16(m, 0x72, (flags >> 1) & 1)
    shared.write_u16(m, 0x60, (flags >> 2) & 1)
    shared.write_u16(m, 0x70, (flags >> 3) & 1)
    shared.write_u16(m, 0xA2, (flags >> 4) & 1)
    shared.write_u16(m, 0x7C, (case.sr >> 8) & 7)
    logical_pc = RETURN_PC if native else ENTRY_PC
    shared.write_u16(m, 0x40, logical_pc & 0xFFFF)
    shared.write_u16(m, 0x42, (logical_pc >> 16) & 0xFF)
    shared.write_u16(m, 0x4A, 0)
    shared.write_u16(m, 0x4C, 0)
    shared.write_u16(m, 0xA4, launch_regs["A7"] & 0xFFFF)
    shared.write_u16(m, 0xA6, (launch_regs["A7"] >> 16) & 0xFFFF)
    shared.write_u16(m, 0xA8, 1)
    shared.write_u16(m, 0xAA, 0)
    shared.write_u16(m, 0xAC, 0xFFFF)
    shared.write_u16(m, 0x0702, 0)
    shared.write_u16(m, 0x0704, 1)
    # Production NOPs the per-fetch dbg_fetch call, so use a temporary
    # ILLEGAL opcode at the retained return seam and stop at op_illegal before
    # it mutates the architectural state.
    shared.write_u16(m, 0x0710, 0)
    shared.write_u16(m, 0x0712, 0)
    shared.write_u16(m, 0x0714, 0)
    shared.write_u16(m, 0x0716, (RETURN_PC >> 16) & 0xFF)
    shared.write_u16(m, 0x0718, 0xFFF8)
    shared.write_u16(m, 0x071A, 1 if native else 0)
    shared.write_u16(m, 0x072E, 0)
    shared.write_u16(m, 0x0730, 0)
    # Keep the historical unpaced fixture default, but allow a focused
    # production-pacing differential to exercise the charged generated path.
    shared.write_u16(
        m,
        0x0734,
        1 if os.environ.get("SUPERMN_VALIDATE_PACED") == "1" else 0,
    )
    shared.write_u16(m, 0x0736, 0)
    shared.write_u16(m, 0x0738, 0)
    shared.write_u16(m, 0x073A, choke_gate)
    shared.write_u16(m, 0x073C, 0)
    if vtime_active:
        seed_vtime_active_state(m)

    base.set_sa1_pc(m, ENTRY_NATIVE if native else INEXT)
    state_info = None
    if pre_state is not None:
        pre_state.parent.mkdir(parents=True, exist_ok=True)
        response = m.save_state(pre_state.resolve())
        wait_for_file(pre_state)
        state_info = {
            "path": str(pre_state.resolve()),
            "sha256": shared.sha256(pre_state),
            "size": pre_state.stat().st_size,
            "response": response,
        }

    return_offset = 0x10000 + RETURN_PC
    illegal_offset = OP_ILLEGAL - 0x8000
    return_original = bytes(m.read_memory("snesPrgRom", return_offset, 2))
    illegal_original = bytes(m.read_memory("snesPrgRom", illegal_offset, 2))
    m.write_memory("snesPrgRom", return_offset, "4afc")
    m.write_memory("snesPrgRom", illegal_offset, "80fe")
    seam_hook = (
        None
        if boundary_tool is not None
        else m.add_exec_hook(OP_ILLEGAL, cpu_type="Sa1")
    )
    if seam_hook is not None:
        m.drain_notifications(timeout=0.05)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        # The interpreter-only high-density collision shapes can legitimately
        # consume tens of millions of SA-1 cycles.  Keep the local IRQ mask
        # isolated and allow enough emulated frames to finish those exact
        # fallback paths; the native cases still return almost immediately.
        if boundary_tool is None:
            hit = m.run_until(max_frames=240, hook_handle=seam_hook)
        else:
            hit = m.tool(
                boundary_tool,
                {
                    "address": OP_ILLEGAL,
                    "cpuType": "Sa1",
                    "maxFrames": 240,
                    "occurrences": 1,
                },
            )
        ensure_paused(m)
    finally:
        if seam_hook is not None:
            m.remove_hook(seam_hook)
        m.write_memory("snesPrgRom", return_offset, return_original.hex())
        m.write_memory("snesPrgRom", illegal_offset, illegal_original.hex())
    expected_reason = "hookFired" if boundary_tool is None else "breakpoint"
    exact_stop_ok = True
    if boundary_tool is not None:
        exact_address = (
            ((int((hit or {}).get("k", 0)) & 0xFF) << 16)
            | (int((hit or {}).get("pc", 0)) & 0xFFFF)
        )
        exact_stop_ok = (
            exact_address == OP_ILLEGAL
            and int((hit or {}).get("observedOccurrences", -1)) == 1
            and (hit or {}).get("isPaused") is True
            and (hit or {}).get("scopedBreakpointRemoved") is True
        )
        if boundary_tool == "run_to_exact_exec_stop":
            exact_stop_ok = (
                exact_stop_ok
                and (hit or {}).get("exactStopTriggered") is True
                and (hit or {}).get("exactStopBreakDelivered") is True
            )
    if (
        (hit or {}).get("reason") != expected_reason
        or (
            boundary_tool is not None
            and (hit or {}).get("hit") is not True
        )
        or not exact_stop_ok
    ):
        sa1_state = m.get_cpu_state("Sa1")
        observed_pc = shared.read_u16(m, 0x40) | (
            (shared.read_u16(m, 0x42) & 0xFF) << 16
        )
        raise RuntimeError(
            f"Nexen did not freeze at return ${RETURN_PC:06X} "
            f"for {case.name}, native={native}: {hit!r}; "
            f"SA1={sa1_state!r}, 68K_PC=${observed_pc:06X}, "
            f"halt=${shared.read_u16(m, 0x4E):04X}, "
            f"compact_count=${shared.read_u16(m, 0x50):04X}, "
            f"outer=${shared.read_u16(m, 0x52):04X}, "
            f"inner=${shared.read_u16(m, 0x56):04X}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    observed_pc = shared.read_u16(m, 0x40) | (
        (shared.read_u16(m, 0x42) & 0xFF) << 16
    )
    if observed_pc != RETURN_PC:
        raise RuntimeError(
            f"Nexen froze at ${observed_pc:06X}, expected ${RETURN_PC:06X}"
        )
    sr = 0x2000 | ((shared.read_u16(m, 0x7C) & 7) << 8) | shared.captured_ccr(m)
    return (
        base.Result(
            shared.captured_regs(m),
            sr,
            bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
            end_cycles - start_cycles,
        ),
        state_info,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument(
        "--capture-emulator",
        type=Path,
        help=(
            "emulator that owns --state and is used only to capture portable "
            "entry fixtures; the three-way replay still uses --nexen"
        ),
    )
    parser.add_argument(
        "--vtime-active",
        action="store_true",
        help=(
            "seed a no-deadline virtual-cycle state for both SNES fixture "
            "runs; diagnostic-only, not hardware-phase evidence"
        ),
    )
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7720)
    parser.add_argument("--cases", type=int, default=12)
    parser.add_argument(
        "--input-buttons",
        type=lambda value: int(value, 0),
        help="hold this Nexen port-0 button mask while capturing fresh fixtures",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="replay retained case-*.json/.work.bin fixtures instead of recapturing",
    )
    parser.add_argument(
        "--guard-shapes",
        action="store_true",
        help=(
            "derive 0/1/16/17-active boundary cases from the first fixture "
            "to exercise both compact and fallback paths"
        ),
    )
    parser.add_argument(
        "--both-x",
        action="store_true",
        help="replay every organic/guard shape with incoming X clear and set",
    )
    parser.add_argument(
        "--only-shape",
        action="append",
        default=[],
        help=(
            "after deriving guard shapes, retain only case names containing "
            "this token; repeat for multiple focused shapes"
        ),
    )
    parser.add_argument(
        "--retain-prestates",
        action="store_true",
        help=(
            "save each fully configured native-off/on Nexen state before "
            "execution; intended for focused discrepancy regressions"
        ),
    )
    parser.add_argument(
        "--stabilize-entry-capture",
        action="store_true",
        help=(
            "capture one exact mutable $025110 entry by temporarily replacing "
            "its first native instruction with side-effect-free BRA -2; "
            "requires --cases 1"
        ),
    )
    parser.add_argument(
        "--capture-input-frames",
        type=int,
        help=(
            "use the legacy capture emulator's advance-and-release input "
            "primitive for this many frames instead of Nexen hold mode"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    mame_oracle = mame_identity()
    os.environ.update(mame_environment(os.environ))
    for path in (
        args.rom,
        args.state,
        args.nexen,
        args.capture_emulator or args.nexen,
        args.nat,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.cases < 1:
        parser.error("--cases must be positive")
    if args.capture_input_frames is not None and args.capture_input_frames < 1:
        parser.error("--capture-input-frames must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.input_buttons is not None and not 0 <= args.input_buttons <= 0xFFF:
        parser.error("--input-buttons must be a 12-bit mask")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.fixture_dir is not None:
        fixture_dir = args.fixture_dir
        if not fixture_dir.is_dir():
            parser.error(f"fixture directory does not exist: {fixture_dir}")
    else:
        fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
        if fixture_dir.exists():
            parser.error(f"fixture directory already exists: {fixture_dir}")
        fixture_dir.mkdir()
    artifact_dir = args.output.parent / f"{args.output.stem}-artifacts"
    if artifact_dir.exists():
        parser.error(f"artifact directory already exists: {artifact_dir}")
    artifact_dir.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $025110 three-way differential; "
            "MAME arcade, Nexen interpreter with all escapes disabled, and "
            "Nexen native root with escapes enabled; all D/A registers, "
            "CCR/X/mask, mapped 16 KiB work RAM; not fps"
        ),
        "mame": mame_oracle,
        "mame_return_seam": {
            "pc": f"{RETURN_PC:06X}",
            "instruction": "BRA.B self",
            "reason": "repeat fetch until post-RTS SP is settled",
            "rom_file_modified": False,
        },
        "mame_irq_isolation": {
            "reason": "prevent unrelated held VBLANK IRQ6 during local injection",
            "entry_mask": 7,
            "reported_mask": "organic entry mask; function has no SR-mask writer",
            "rom_file_modified": False,
        },
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": shared.sha256(args.nexen),
        "capture_emulator": str(
            (args.capture_emulator or args.nexen).resolve()
        ),
        "capture_emulator_sha256": shared.sha256(
            args.capture_emulator or args.nexen
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": shared.sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": shared.sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": shared.sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "interpreter_entry": f"{INEXT:06X}",
        "fixtures": args.cases,
        "input_buttons": args.input_buttons,
        "capture_input_frames": args.capture_input_frames,
        "synthetic_guard_active_counts": (
            list(GUARD_ACTIVE_COUNTS) if args.guard_shapes else []
        ),
        "synthetic_guard_shapes": (
            list(SEMANTIC_GUARD_SHAPES) if args.guard_shapes else []
        ),
        "incoming_x_variants": [0, 1] if args.both_x else "organic",
        "only_shape_filters": args.only_shape,
        "fixture_source": (
            str(fixture_dir.resolve())
            if args.fixture_dir is not None
            else "fresh production capture"
        ),
        "artifact_directory": str(artifact_dir.resolve()),
        "snes_configurations": ["native-off", "native-on"],
        "nested_xlat_gate": {"native-off": 0, "native-on": 1},
        "retain_prestates": args.retain_prestates,
        "vtime_active_synthetic_no_deadline": args.vtime_active,
        "stabilized_entry_capture": args.stabilize_entry_capture,
        "variants_per_fixture": 2,
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    if args.fixture_dir is not None:
        cases = load_cases(fixture_dir, args.cases)
    else:
        capture_emulator = args.capture_emulator or args.nexen
        old_dotnet_root = os.environ.get("DOTNET_ROOT")
        old_path = os.environ.get("PATH", "")
        if args.capture_emulator is not None:
            # The retained organic crate states are owned by legacy Mesen
            # 2.1.1, which requires the host's .NET 8 runtime.
            os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
            os.environ["PATH"] = "/home/chad/.dotnet8:" + old_path
        try:
            cases = capture_live_cases(
                args.rom,
                args.state,
                capture_emulator,
                args.port,
                args.cases,
                fixture_dir / "capture.nexen.stderr.log",
                args.input_buttons,
                args.capture_input_frames,
                args.stabilize_entry_capture,
            )
        finally:
            if old_dotnet_root is None:
                os.environ.pop("DOTNET_ROOT", None)
            else:
                os.environ["DOTNET_ROOT"] = old_dotnet_root
            os.environ["PATH"] = old_path
    if args.guard_shapes:
        cases.extend(derive_guard_cases(cases[0]))
    if args.only_shape:
        cases = [
            case
            for case in cases
            if any(token in case.name for token in args.only_shape)
        ]
        if not cases:
            parser.error("--only-shape filters selected no cases")
    if args.both_x:
        cases = derive_x_variants(cases)
    for index, case in enumerate(cases):
        fixture = {
            "name": case.name,
            "tick": case.tick,
            "terminal_pc": f"{RETURN_PC:06X}",
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        if args.fixture_dir is None:
            (fixture_dir / f"case-{index:02d}.work.bin").write_bytes(case.work)
            (fixture_dir / f"case-{index:02d}.json").write_text(
                json.dumps(fixture, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        event = {"event": "fixture", **fixture}
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    arcade: dict[str, base.Result] = {}
    mame = base.MameSession(
        mame=str(MAME),
        system="superman",
        rompath=str(base.MAME_TRACE / "roms"),
        workdir=str(base.MAME_TRACE),
        state_directory=str(base.MAME_TRACE / "sta"),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        for case in cases:
            arcade[case.name] = mame_result(mame, case)
            event = {
                "event": "mame_case",
                "case": case.name,
                "oracle_terminal_pc": f"{RETURN_PC:06X}",
            }
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
    finally:
        mame.stop()

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=180.0,
        # A retained fixture directory is immutable evidence.  Keep replay
        # process logs beside the new result instead of overwriting the log
        # that accompanied the original capture.
        stderr_log=artifact_dir / "differential.nexen.stderr.log",
    ) as nexen:
        for case in cases:
            for native in (False, True):
                configuration = "native-on" if native else "native-off"
                console, pre_state = nexen_result(
                    nexen,
                    args.nat,
                    case,
                    native=native,
                    pre_state=(
                        artifact_dir
                        / "states"
                        / configuration
                        / f"{case.name}.mss"
                        if args.retain_prestates
                        else None
                    ),
                    vtime_active=args.vtime_active,
                )
                event = shared.compare(
                    case,
                    arcade[case.name],
                    console,
                    1 if native else 0,
                    0,
                )
                event["configuration"] = configuration
                event["root_native"] = native
                if pre_state is not None:
                    event["pre_state"] = pre_state
                events.append(event)
                print(json.dumps(event, sort_keys=True), flush=True)

    case_events = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in case_events)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(case_events) - green,
        "total": len(case_events),
        "result": "green" if green == len(case_events) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
