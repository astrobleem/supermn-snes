#!/usr/bin/env python3
"""Regression checks for fail-closed direct-controller capture claims."""

from capture_snes_direct_framebuffers import (
    CAMERA_MAILBOX_BATCH_HELPER_LAB,
    CAMERA_MAILBOX_NMI_HELPER_LAB,
    CAMERA_MAILBOX_SA1_HELPER_LAB,
    CAMERA_MAILBOX_VALID_BATCH_HELPER_LAB,
    CAMERA_MAILBOX_VALID_NMI_HELPER_LAB,
    CAMERA_MAILBOX_VALID_SA1_HELPER_LAB,
    EARLY_CAMERA_BATCH_ENTRY_LAB,
    EARLY_CAMERA_BATCH_ENTRY_OLD,
    EARLY_CAMERA_BATCH_HELPER_LAB,
    EARLY_CAMERA_MANIFEST_CALL_LAB,
    EARLY_CAMERA_MANIFEST_CALL_OLD,
    EARLY_CAMERA_NMI_ENTRY_LAB,
    EARLY_CAMERA_NMI_ENTRY_OLD,
    EARLY_CAMERA_NMI_HELPER_LAB,
    EARLY_CAMERA_SA1_HELPER_LAB,
    EARLY_CAMERA_SA1_HELPER_OFFSET,
    SA1_DEADLINE_IRQ_DISABLED_LAB,
    SA1_DEADLINE_IRQ_FILE_OFFSET,
    SA1_DEADLINE_IRQ_OLD,
    controller_input_failure,
)
from capture_snes_input_framebuffers import (
    CAMERA_MAILBOX_VALID_BATCH_HELPER_LAB as INPUT_VALID_BATCH_HELPER,
    CAMERA_MAILBOX_VALID_NMI_HELPER_LAB as INPUT_VALID_NMI_HELPER,
    CAMERA_MAILBOX_VALID_SA1_HELPER_LAB as INPUT_VALID_SA1_HELPER,
    DMA0_MAP_VMADDR_ZERO_LAB,
    DMA0_SERVICE_TAIL,
    DMA0_SERVICE_TAIL_OLD,
    OBJ_BATCH_DISPATCH_OLD,
    OBJ_BATCH_YIELD_DMA0_LAB,
    advance_recording_with_input,
    obj_staging_dma4_bytes,
)


class PartialTimedInput:
    def __init__(self, frame: int, advances: list[int]) -> None:
        self.frame = frame
        self.advances = iter(advances)

    def get_state(self) -> dict[str, int]:
        return {"frameCount": self.frame}

    def set_input(self, buttons: int, frames: int) -> dict[str, int]:
        advanced = next(self.advances)
        self.frame += advanced
        return {"buttons": buttons, "frames": frames}

    def pause(self) -> None:
        return None


def main() -> int:
    neutral = [{"input_mailbox": "00000000"} for _ in range(5)]
    observed = neutral + [{"input_mailbox": "00200000"}]

    assert controller_input_failure(neutral, 0) is None
    assert controller_input_failure(observed, 4) is None
    failure = controller_input_failure(neutral, 4)
    assert failure is not None
    assert failure["kind"] == "controller_input_not_observed"

    partial = PartialTimedInput(100, [5, 3])
    response = advance_recording_with_input(partial, 4, 8)
    assert partial.frame == 108
    assert [row["advanced"] for row in response["responses"]] == [5, 3]
    assert response["overshoot_frames"] == 0

    one_frame_overshoot = PartialTimedInput(100, [5, 4])
    response = advance_recording_with_input(one_frame_overshoot, 4, 8)
    assert one_frame_overshoot.frame == 109
    assert response["overshoot_frames"] == 1

    staging = b"".join(
        bytes(
            (
                0x9C if register in (0, 6) else 0x8D,
                0x50 + register,
                0x43,
            )
        )
        for register in range(7)
    ) + bytes.fromhex("a9208d0b42")
    isolated = obj_staging_dma4_bytes(staging)
    for register in range(7):
        opcode = 0x9C if register in (0, 6) else 0x8D
        assert bytes((opcode, 0x40 + register, 0x43)) in isolated
        assert bytes((opcode, 0x50 + register, 0x43)) not in isolated
    assert bytes.fromhex("a9108d0b42") in isolated
    assert obj_staging_dma4_bytes(isolated) == isolated
    assert OBJ_BATCH_YIELD_DMA0_LAB.startswith(bytes.fromhex("08e220ad111ff002286b"))
    # The lab keeps the authenticated dispatch body, replacing only its
    # initial PHP/REP prologue with the pending-DMA0 yield gate.
    assert OBJ_BATCH_DISPATCH_OLD[3:] in OBJ_BATCH_YIELD_DMA0_LAB
    assert bytes.fromhex("9c16219c1721") in DMA0_MAP_VMADDR_ZERO_LAB
    assert DMA0_SERVICE_TAIL == 0x7F8A61
    assert DMA0_SERVICE_TAIL_OLD[:4] == DMA0_MAP_VMADDR_ZERO_LAB[:4]
    assert DMA0_SERVICE_TAIL_OLD[4:] in DMA0_MAP_VMADDR_ZERO_LAB
    assert SA1_DEADLINE_IRQ_FILE_OFFSET == 0x2CFB4E
    assert SA1_DEADLINE_IRQ_OLD == bytes.fromhex("8d0922")
    assert SA1_DEADLINE_IRQ_DISABLED_LAB == bytes.fromhex("eaeaea")
    assert EARLY_CAMERA_MANIFEST_CALL_OLD == bytes.fromhex("2200dc9e")
    assert EARLY_CAMERA_MANIFEST_CALL_LAB == bytes.fromhex("22c5fb99")
    assert EARLY_CAMERA_SA1_HELPER_OFFSET == 0x2CFBC5
    assert bytes.fromhex("8f2201412200dc9e6b") in EARLY_CAMERA_SA1_HELPER_LAB
    assert EARLY_CAMERA_NMI_ENTRY_OLD == bytes.fromhex("af220141")
    assert EARLY_CAMERA_NMI_ENTRY_LAB == bytes.fromhex("5c20dae9")
    assert bytes.fromhex("c904d010") in EARLY_CAMERA_NMI_HELPER_LAB
    assert EARLY_CAMERA_NMI_HELPER_LAB.endswith(bytes.fromhex("5c04cfe9"))
    assert EARLY_CAMERA_BATCH_ENTRY_OLD == bytes.fromhex("af220141")
    assert EARLY_CAMERA_BATCH_ENTRY_LAB == bytes.fromhex("5c80dae9")
    assert EARLY_CAMERA_BATCH_HELPER_LAB.endswith(bytes.fromhex("5c44dae9"))
    assert len(CAMERA_MAILBOX_SA1_HELPER_LAB) == 26
    assert bytes.fromhex("af8934418f620141") in CAMERA_MAILBOX_SA1_HELPER_LAB
    assert CAMERA_MAILBOX_SA1_HELPER_LAB.endswith(bytes.fromhex("2200dc9e6b"))
    assert len(CAMERA_MAILBOX_NMI_HELPER_LAB) == 30
    assert bytes.fromhex("af630141cfb2717e") in CAMERA_MAILBOX_NMI_HELPER_LAB
    assert CAMERA_MAILBOX_NMI_HELPER_LAB.endswith(bytes.fromhex("5c04cfe9"))
    assert len(CAMERA_MAILBOX_BATCH_HELPER_LAB) == 30
    assert CAMERA_MAILBOX_BATCH_HELPER_LAB.endswith(bytes.fromhex("5c44dae9"))
    assert CAMERA_MAILBOX_VALID_SA1_HELPER_LAB == INPUT_VALID_SA1_HELPER
    assert CAMERA_MAILBOX_VALID_NMI_HELPER_LAB == INPUT_VALID_NMI_HELPER
    assert CAMERA_MAILBOX_VALID_BATCH_HELPER_LAB == INPUT_VALID_BATCH_HELPER
    assert bytes.fromhex("a9a58f630141") in INPUT_VALID_SA1_HELPER
    assert INPUT_VALID_SA1_HELPER.endswith(bytes.fromhex("5c00dc9e"))
    assert bytes.fromhex("2200dc9e6b") not in INPUT_VALID_SA1_HELPER
    assert bytes.fromhex("c9a5d00e") in INPUT_VALID_NMI_HELPER
    assert INPUT_VALID_NMI_HELPER.endswith(bytes.fromhex("5c04cfe9"))
    assert INPUT_VALID_BATCH_HELPER.endswith(bytes.fromhex("5c44dae9"))
    print("direct framebuffer input contract: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
