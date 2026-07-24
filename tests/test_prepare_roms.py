#!/usr/bin/env python3
"""Synthetic tests for tools/prepare_roms.py.

No arcade ROM bytes or derived game data are present in this test module.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import prepare_roms  # noqa: E402


def synthetic_spec(name: str, data: bytes) -> object:
    return prepare_roms.RomSpec(
        name=name,
        size=len(data),
        sha1=hashlib.sha1(data).hexdigest(),
        sha256=hashlib.sha256(data).hexdigest(),
        purpose="synthetic test ROM",
    )


def synthetic_entry(display: str, basename: str, data: bytes) -> object:
    return prepare_roms.SourceEntry(
        display_name=display,
        basename=basename,
        size=len(data),
        read_bytes=lambda: data,
    )


class LayoutTests(unittest.TestCase):
    def test_interleave_byte_lanes(self) -> None:
        actual = prepare_roms.interleave_byte_lanes(
            bytes((0x10, 0x20, 0x30)),
            bytes((0x11, 0x21, 0x31)),
        )
        self.assertEqual(actual, bytes((0x10, 0x11, 0x20, 0x21, 0x30, 0x31)))

    def test_interleave_rejects_unequal_lanes(self) -> None:
        with self.assertRaisesRegex(
            prepare_roms.RomPreparationError, "unequal byte lanes"
        ):
            prepare_roms.interleave_byte_lanes(b"\x00", b"\x00\x01")

    def test_load32_word_swap_two_lanes(self) -> None:
        output = bytearray(8)
        prepare_roms.load32_word_swap(output, bytes((0, 1, 2, 3)), 0)
        prepare_roms.load32_word_swap(output, bytes((4, 5, 6, 7)), 2)
        self.assertEqual(output, bytearray((1, 0, 5, 4, 3, 2, 7, 6)))

    def test_load32_word_swap_rejects_overflow(self) -> None:
        with self.assertRaisesRegex(
            prepare_roms.RomPreparationError, "does not fit"
        ):
            prepare_roms.load32_word_swap(bytearray(7), bytes((0, 1, 2, 3)), 2)

    def test_adpcm_a_decoder_uses_high_nibble_first(self) -> None:
        self.assertEqual(
            prepare_roms.decode_adpcm_a(bytes((0x01, 0x8F))),
            [2, 8, 6, -24],
        )

    def test_drum_resampler_matches_linear_integer_policy(self) -> None:
        self.assertEqual(
            prepare_roms.resample_linear([0, 100, 200, 300], 4, 8),
            [0, 50, 100, 150, 200, 250, 300, 300],
        )

    def test_wav_writer_is_mono_pcm16(self) -> None:
        output = prepare_roms.mono_pcm16_wav([0, 1, -1], 8_000)
        self.assertEqual(output[:4], b"RIFF")
        self.assertEqual(output[8:12], b"WAVE")
        self.assertEqual(len(output), 44 + 3 * 2)


class SourceValidationTests(unittest.TestCase):
    def test_exact_named_synthetic_rom(self) -> None:
        data = b"synthetic-rom"
        spec = synthetic_spec("test.rom", data)
        entry = synthetic_entry("test.rom", "test.rom", data)
        resolved, notes = prepare_roms.resolve_rom_set([entry], [spec])
        self.assertEqual(resolved, {"test.rom": data})
        self.assertEqual(notes, [])

    def test_unique_renamed_rom_is_identified_by_checksums(self) -> None:
        data = b"renamed-synthetic-rom"
        spec = synthetic_spec("expected.rom", data)
        entry = synthetic_entry("renamed.bin", "renamed.bin", data)
        resolved, notes = prepare_roms.resolve_rom_set([entry], [spec])
        self.assertEqual(resolved["expected.rom"], data)
        self.assertIn("recognized by checksum", notes[0])

    def test_duplicate_filename_fails_loudly(self) -> None:
        data = b"duplicate-synthetic-rom"
        spec = synthetic_spec("expected.rom", data)
        entries = [
            synthetic_entry("one/expected.rom", "expected.rom", data),
            synthetic_entry("two/expected.rom", "expected.rom", data),
        ]
        with self.assertRaisesRegex(
            prepare_roms.RomPreparationError, "duplicate required ROM filenames"
        ):
            prepare_roms.resolve_rom_set(entries, [spec])

    def test_duplicate_contents_under_different_names_fails(self) -> None:
        data = b"duplicate-content"
        spec = synthetic_spec("expected.rom", data)
        entries = [
            synthetic_entry("expected.rom", "expected.rom", data),
            synthetic_entry("copy.bin", "copy.bin", data),
        ]
        with self.assertRaisesRegex(
            prepare_roms.RomPreparationError, "duplicated ROM contents"
        ):
            prepare_roms.resolve_rom_set(entries, [spec])

    def test_wrong_checksum_reports_hashes_not_contents(self) -> None:
        expected = b"expected-private-placeholder"
        wrong = b"X" * len(expected)
        spec = synthetic_spec("expected.rom", expected)
        entry = synthetic_entry("expected.rom", "expected.rom", wrong)
        with self.assertRaises(prepare_roms.RomPreparationError) as caught:
            prepare_roms.resolve_rom_set([entry], [spec])
        message = str(caught.exception)
        self.assertIn("checksum mismatch", message)
        self.assertIn(hashlib.sha256(wrong).hexdigest(), message)
        self.assertNotIn(repr(wrong), message)

    def test_missing_rom_names_its_purpose(self) -> None:
        data = b"expected"
        spec = synthetic_spec("missing.rom", data)
        unrelated = synthetic_entry("other.bin", "other.bin", b"other")
        with self.assertRaises(prepare_roms.RomPreparationError) as caught:
            prepare_roms.resolve_rom_set([unrelated], [spec])
        self.assertIn("missing (synthetic test ROM)", str(caught.exception))

    def test_collects_nested_member_from_zip(self) -> None:
        # Use a canonical-size dummy so the production collector admits it,
        # then authenticate it with a synthetic manifest.
        data = bytes(131_072)
        spec = synthetic_spec("b61_09.a10", data)
        with tempfile.TemporaryDirectory() as tmp_name:
            archive_path = Path(tmp_name) / "synthetic.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("nested/b61_09.a10", data)
            entries = prepare_roms.collect_source_entries(archive_path)
            resolved, _ = prepare_roms.resolve_rom_set(entries, [spec])
        self.assertEqual(resolved["b61_09.a10"], data)

    def test_world_archive_wins_over_clone_archives_in_rompath(self) -> None:
        data = bytes(131_072)
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            for archive_name in ("superman.zip", "supermanu.zip"):
                with zipfile.ZipFile(root / archive_name, "w") as archive:
                    archive.writestr("b61_09.a10", data)
            entries = prepare_roms.collect_source_entries(root)
        self.assertEqual(
            [entry.display_name for entry in entries],
            ["superman.zip!b61_09.a10"],
        )


class InterfaceTests(unittest.TestCase):
    def test_help_lists_required_modes(self) -> None:
        help_text = prepare_roms.build_argument_parser().format_help()
        self.assertIn("--dry-run", help_text)
        self.assertIn("--validate-only", help_text)
        self.assertIn("--output-root", help_text)
        self.assertIn("--mame", help_text)

    def test_cchip_lua_reads_only_the_expected_window(self) -> None:
        script = prepare_roms.build_cchip_capture_lua(Path("/synthetic/out"), 7)
        self.assertIn("0xF01B20 + i", script)
        self.assertIn("for i = 0, 255", script)
        self.assertIn("frame >= 7", script)


if __name__ == "__main__":
    unittest.main()
