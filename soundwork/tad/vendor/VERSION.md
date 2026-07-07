# TAD vendor pin (sound port P1)

Reproducibility pins for the Terrific Audio Driver integration. Regenerate the blob with
`soundwork/tad/build_blob.sh`.

## Versions
- **TAD source**: `/home/chad/terrific-audio-driver` @ commit `822164b` ("Fix wrong instrument pitch table offset")
- **tad-compiler**: `0.3.0` (prebuilt release binary `target/release/tad-compiler`)
- **cc65 (ca65/ld65)**: `V2.18` (for the byte-verify reference build of `tad-audio.s`)
- **.NET for Mesen**: `/home/chad/.dotnet8` (8.0.28) — NOT `.dotnet10` (that is Nexen's). Mesen fails to launch without it.

## Vendored files (this dir)
- `tad-audio.s` (1519 lines / ~347 instr) — the ca65 host API being PORTED to Poppy (`.org $9000` in `src/video.pasm`).
- `tad-audio.inc` — the public header (equates, enums, macros) the port needs.
- `audio-driver.bin` (3218B), `loader.bin` (116B) — SPC700 blobs (turnkey; also baked into the generated blob).

## Generated blob (`soundwork/tad/build/audio-data.bin`, 4143B for the 02_coin placeholder)
Self-contained, one `.incbin`-able file. Layout (from `ca65-export --output-bin`):
```
off 0      loader.bin       (116)      -> Tad_Loader_Bin,      Tad_Loader_SIZE = 116
off 116    audio-driver.bin (3218)     -> Tad_AudioDriver_Bin, Tad_AudioDriver_SIZE = 3218
off 3334   Tad_DataTable    (8)        -> [u24 ; N_DATA_ITEMS=2] PRG offsets + u16 footer
off 3342+  common + song data
```
DataTable (offsets from blob base): item0 common=`0x000D39`, item1 song=`0x000F1A`, footer=`0x105A`.
`AUDIO_DATA_BANK = .bankbyte(blob base)`. HIROM assert: blob MUST start at a HiRom bank boundary (`$XX:0000`).

## LoadAudioData contract (HIROM, 43 bytes — port verbatim to Poppy)
`jsl`-called (rtl). IN: A=0 → common (return carry SET); A>=1 → song. OUT: carry set if valid; A:X = far
address; Y = size. Computes size = `DataTable[i+1] - DataTable[i]`; address from `DataTable` + `AUDIO_DATA_BANK`.

## Song/SFX enums (`build/audio.inc`)
`Song.BLANK=0`, `Song.s02_coin=1` (Tad_LoadSong arg); `SFX.sfx_stub=0`.
