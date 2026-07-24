# ROM preparation tool — implementation and evidence report

Date: July 24, 2026

## Result

`python3 tools/prepare_roms.py SOURCE` is now the single supported entry point for
the private inputs that can be reproduced deterministically from a legally obtained
MAME `superman` (World) set.

It accepts a directory or ZIP, authenticates all 12 required files by name, size,
SHA-1, and SHA-256, diagnoses renamed files and rejects ambiguity/clones/bad dumps,
then derives and verifies:

- the exact 512 KiB 68000 image;
- the exact 2 MiB MAME-layout graphics image;
- the exact 256-byte organic C-Chip command-1 response through MAME 0.287; and
- all 12 exact ARAM-budgeted ADPCM-A drum WAVs from `b61-01.e18`.

The historical extraction and sound tools were retained. No arcade or derived binary
was added to Git.

## Tested inputs

- Local loose MAME `superman` World set: 12/12 files authenticated.
- Gitignored `tools/mame-trace/roms/superman.zip`: 12/12 files authenticated.
- MAME `0.287 (mame0287)` with Lua enabled.
- Synthetic directory/ZIP entries covering correct, renamed, missing, wrong-hash,
  duplicate-name, duplicate-content, interleave, word-swap, ADPCM decode, resample,
  WAV, C-Chip-script, and help-interface behavior.

Known `supermanu` and `supermanj` program ROM identities are recognized only to give
an actionable unsupported-clone error. Neither clone was locally available for a
whole-set integration run.

## Exact generated-output evidence

All 15 newly generated outputs were compared byte-for-byte with the pre-existing
private inputs: **15/15 identical**.

| Output | Size | SHA-256 |
|---|---:|---|
| `data/superman_m68k.bin` | 524,288 | `6aa9c5b5b55e1545b4da7c2c8610ea01addb096101a667db3f86441d454d197e` |
| `tools/mame-trace/gfx1.bin` | 2,097,152 | `6527c0ddcee69affb98ad75cd50791eadbe5d5dfeb2c6b303b0508638eda90af` |
| `data/cchip_boot_response.bin` | 256 | `75058de1067ddab83ff6b6577be4052b611680c1a344a090bd861d615398f864` |
| `sm_drum_060000.wav` | 7,372 | `7b27258f3fae57e35fc8dabfb1b3042c8c348abeca862304703e25aa6bf5b625` |
| `sm_drum_062a00.wav` | 7,372 | `fb24209cacc249e62b73b86d320628a7955ebf9ec2cff4dad13e49c59a65b65f` |
| `sm_drum_065200.wav` | 7,372 | `040fb5b439b155de05b6df74b7ba7feaa3a777b8641b83fde5fe068d26a433ac` |
| `sm_drum_067800.wav` | 7,372 | `1205e876fec697656da1b2b49f8bc71d55a403976cbc772fb253d957a6d088d5` |
| `sm_drum_069f00.wav` | 7,372 | `020a70d193aa13458a9a2f95bf91f21d5f9f9eb31e2a2dc0d197fe75d53423a2` |
| `sm_drum_06c500.wav` | 7,596 | `4443a7ee0ff184f010041b4cc8c8a35abee3869a08f94eee870dfd1698a33c53` |
| `sm_drum_06f900.wav` | 7,596 | `f0572bb0045e82fcfd279bb191e48425412d0efb95966f6ef42c7eed59aeb470` |
| `sm_drum_072800.wav` | 7,372 | `cd20d0c231da2ed2ab5460c1c0eba119da027bf6ca28d5c64a47c00115ac9486` |
| `sm_drum_075800.wav` | 7,372 | `61f64ef3c152c0d469cab5077a67af53b48bffc2410b41a2f2cfa0651c1ee830` |
| `sm_drum_077900.wav` | 7,372 | `65b6dc165d994adc86397f71ec83093143eb01e8b8e5a23fd606542f1454a899` |
| `sm_drum_079a00.wav` | 7,372 | `76214125518068e6f9d3f1a1b57abd8214c17dd11b30cf4c50345d174047924a` |
| `sm_drum_07b500.wav` | 9,036 | `0132b46bfc19ae08745a2c1f412d736e7b6027b7ca888365dfce21dad5092837` |

All drum paths are below
`soundwork/tad/mml_drafts/instruments/`.

## Fresh-tree build gate

A disposable tree was populated with the current tracked files and only the 45
project-referenced preserved FM authoring WAVs. It contained no prior
`build/interp.sfc`, audio blob, direct private binary, or drum WAV. The preparer
generated all 15 ROM-derived inputs, `soundwork/tad/build_blob.sh` regenerated the
audio blob, and `bash tools/build_interp.sh` completed:

- `soundwork/tad/build/audio-data.bin`: 96,065 bytes,
  SHA-256 `64f58ef6086d690428dc67805e1fe74ecfdc7118bfb8f1a0a2edf7885054eb1a`
- `build/interp.sfc`: 4,194,304 bytes,
  SHA-256 `5aac64b67cfc04caf88b44198b762ddbf283ac38dfc831956290db7a99dd025a`

The first disposable build exposed a circular bootstrap dependency:
`tools/transpile.py` unconditionally opened a previous `build/interp.sfc` while the
build was generating bank-7 bodies. It now uses the prepared
`data/superman_m68k.bin`, validates any coexisting packed-ROM copy, retains a packed
ROM fallback, and supports `SUPERMN_TRANSPILE_ROM` for an explicit lab override. The
second genuinely fresh build passed.

## Commands and gates run

```sh
python3 -m py_compile tools/prepare_roms.py tools/transpile.py tests/test_prepare_roms.py
python3 -m unittest discover -v
python3 -m unittest -v tests/test_prepare_roms.py
python3 tools/prepare_roms.py "$LEGAL_ROM_DIR" --dry-run
python3 tools/prepare_roms.py tools/mame-trace/roms/superman.zip --dry-run
python3 tools/prepare_roms.py "$LEGAL_ROM_DIR" --validate-only
python3 tools/transpile.py 000ce4
```

The disposable-tree harness then ran the equivalent of:

```sh
python3 tools/prepare_roms.py /private/path/to/superman.zip
bash tools/build_interp.sh
```

It also regenerated into a separate empty output root, ran `--validate-only` there,
and performed a direct byte comparison against every existing output.

## Remaining non-derivable input

The current consolidated TAD project references 45 private `fm_p*.wav` files. Their
exact bytes came from the external VGM patch-capture and ymfm rendering workflow,
including selected patches, pitches, loop points, envelopes, normalization, and
octave anchors. The tracked final binding JSON is insufficient to reconstruct every
exact render input from the arcade ROM set alone.

Those FM WAVs remain the one private authoring-input gap. The tool reports this
boundary and never substitutes placeholder audio. With the FM set preserved, the
fresh-tree build above proves that every other required private input and both final
build artifacts regenerate exactly.

Full usage, input identities, overwrite behavior, and legal boundaries are in
`docs/current/ROM_INPUTS.md`.
