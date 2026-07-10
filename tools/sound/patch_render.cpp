// patch_render — render one captured YM2610(B) FM patch to a mono s16 WAV via ymfm.
// Usage: patch_render <patch_hex_31B> <block> <fnum> <hold_s> <tail_s> <out.wav>
// Patch byte layout (see tools/sound/vgm_fm_patches.py):
//   28 op bytes: 7 reg groups (0x30,0x40,0x50,0x60,0x70,0x80,0x90) x slot offsets {0,4,8,12}
//   + B0 (FB/ALG) + B4 (AMS/PMS, pan stripped) + LFO (reg 0x22 low nibble)
// Renders on part-0 channel offset 1 (key-on selector 1) at 8 MHz, chip native rate.
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include "ymfm_opn.h"

class DummyIface : public ymfm::ymfm_interface {
public:
    uint8_t ymfm_external_read(ymfm::access_class, uint32_t) override { return 0; }
};

static void wr(ymfm::ym2610b &chip, int port, uint8_t reg, uint8_t val) {
    if (port == 0) { chip.write_address(reg); chip.write_data(val); }
    else { chip.write_address_hi(reg); chip.write_data_hi(val); }
}

int main(int argc, char **argv) {
    if (argc != 7) { fprintf(stderr, "args\n"); return 2; }
    std::string hex = argv[1];
    int block = atoi(argv[2]), fnum = atoi(argv[3]);
    double hold_s = atof(argv[4]), tail_s = atof(argv[5]);
    const char *outp = argv[6];
    std::vector<uint8_t> pb;
    for (size_t i = 0; i + 1 < hex.size(); i += 2)
        pb.push_back((uint8_t)strtol(hex.substr(i, 2).c_str(), nullptr, 16));
    if (pb.size() != 31) { fprintf(stderr, "want 31 patch bytes, got %zu\n", pb.size()); return 2; }

    DummyIface iface;
    ymfm::ym2610b chip(iface);
    chip.reset();
    uint32_t rate = chip.sample_rate(8000000);

    const int choff = 1;                               // part 0, channel offset 1, keyon sel 1
    static const int slotoff[4] = {0, 4, 8, 12};
    static const int bases[7] = {0x30, 0x40, 0x50, 0x60, 0x70, 0x80, 0x90};
    int k = 0;
    wr(chip, 0, 0x22, pb[30] & 0x0f);                  // LFO
    for (int b = 0; b < 7; b++)
        for (int s = 0; s < 4; s++)
            wr(chip, 0, bases[b] + slotoff[s] + choff, pb[k++]);
    wr(chip, 0, 0xB0 + choff, pb[28]);                 // FB/ALG
    wr(chip, 0, 0xB4 + choff, 0xC0 | (pb[29] & 0x37)); // pan both + AMS/PMS
    wr(chip, 0, 0xA4 + choff, ((block & 7) << 3) | ((fnum >> 8) & 7));
    wr(chip, 0, 0xA0 + choff, fnum & 0xff);
    wr(chip, 0, 0x28, 0xF0 | 0x01);                    // key on, all slots, sel 1

    uint32_t nhold = (uint32_t)(hold_s * rate), ntail = (uint32_t)(tail_s * rate);
    std::vector<int16_t> out;
    out.reserve(nhold + ntail);
    ymfm::ym2610b::output_data od;
    for (uint32_t i = 0; i < nhold + ntail; i++) {
        if (i == nhold) wr(chip, 0, 0x28, 0x01);       // key off
        chip.generate(&od, 1);
        int32_t v = (od.data[0] + od.data[1]) / 2;     // FM stereo mix (ADPCM on ch2 unused)
        if (v > 32767) v = 32767; if (v < -32768) v = -32768;
        out.push_back((int16_t)v);
    }
    // minimal WAV writer
    FILE *f = fopen(outp, "wb");
    if (!f) { perror("open"); return 1; }
    uint32_t dlen = out.size() * 2, riff = 36 + dlen, fmt = 16;
    uint16_t pcm = 1, ch = 1, bps = 16, ba = 2;
    uint32_t br = rate * 2;
    fwrite("RIFF", 1, 4, f); fwrite(&riff, 4, 1, f); fwrite("WAVE", 1, 4, f);
    fwrite("fmt ", 1, 4, f); fwrite(&fmt, 4, 1, f); fwrite(&pcm, 2, 1, f); fwrite(&ch, 2, 1, f);
    fwrite(&rate, 4, 1, f); fwrite(&br, 4, 1, f); fwrite(&ba, 2, 1, f); fwrite(&bps, 2, 1, f);
    fwrite("data", 1, 4, f); fwrite(&dlen, 4, 1, f);
    fwrite(out.data(), 2, out.size(), f);
    fclose(f);
    printf("rate=%u samples=%zu\n", rate, out.size());
    return 0;
}
