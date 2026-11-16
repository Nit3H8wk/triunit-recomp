// MK3 DMA blitter model: self-checks, then replay of an event file built from Original observations, with the
// done timer and INT1 line of VideoTiming exactly as the CPU executor is to drive them.
// Usage: mk3-dma [graphics events [bias]]
//   graphics: lines "region_offset size path" (ROM_LOAD32_BYTE, stride 4), authenticated by the caller.
//   events (hex unless noted):
//     P n idx:val ...   video RAM words set before the next DMA_COMMAND write (declared stimulus)
//     R off data mask   DMA register write other than DMA_COMMAND (off = word offset 0..15)
//     C c e off data mask   DMA_COMMAND write; c = instruction-start cycle, e = cycles already counted (decimal)
//     E c               advance to cycle c (decimal)
//   bias: whole cycles added to every done time (negative controls).
// Output: G graphics_hash; per trigger "T pixels done_cycle r0..r17" (registers before the write), "V n idx:val ...",
// "H vram_hash"; per change of (DMA_COMMAND & 0x8000) | (INTPEND & INT1): "S W c state" after a DMA_COMMAND write,
// "S T c state" when the done timer fires. A rejection prints "REJECT what" and stops.
// Hashes: the little-endian integer of the bytes modulo 2^61 - 1.
#include "mk3_dma.hpp"
#include "mk3_video.hpp"
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>

namespace {
int failures = 0;
void Check(bool ok, const char* what) { if (!ok) { std::fprintf(stderr, "FAIL %s\n", what); ++failures; } }
template <class F> std::string Rejection(F f) { try { f(); } catch (const std::runtime_error& e) { return e.what(); } return ""; }

constexpr uint64_t kP = (uint64_t(1) << 61) - 1;
uint64_t Hash(const uint8_t* bytes, size_t n) {  // Horner from the most significant end, Mersenne reduction
    uint64_t h = 0;
    const auto step = [&h](unsigned bits, uint32_t digit) {
        const unsigned __int128 x = (unsigned __int128)h << bits | digit;  // < 2^93
        const uint64_t r = uint64_t(x & kP) + uint64_t(x >> 61);
        h = r >= kP ? r - kP : r;
    };
    size_t i = n;
    for (; i % 4; --i) step(8, bytes[i - 1]);
    for (; i; i -= 4) step(32, uint32_t(bytes[i - 4]) | uint32_t(bytes[i - 3]) << 8 | uint32_t(bytes[i - 2]) << 16 | uint32_t(bytes[i - 1]) << 24);
    return h;
}

void SelfChecks() {
    using D = mk3::Dma;
    using V = mk3::VideoTiming;
    std::vector<uint8_t> gfx(64);
    for (size_t i = 0; i < gfx.size(); ++i) gfx[i] = uint8_t(i * 37 + 11);
    D d(gfx);
    d.Write(15, 0x10);  // bank 0: offsets 12/13 are the left/right clip pseudo-registers
    d.Write(12, 3); d.Write(13, 6);
    d.Write(15, 0x30);
    d.Write(12, 1); d.Write(13, 2);
    Check(d.reg[D::LEFTCLIP] == 3 && d.reg[D::RIGHTCLIP] == 6 && d.reg[D::TOPCLIP] == 1 && d.reg[D::BOTCLIP] == 2, "register_map banks");
    d.Write(4, 2); d.Write(5, 0); d.Write(6, 8); d.Write(7, 4); d.Write(8, 0x1234); d.Write(9, 0x56);
    Check(d.Write(1, 0x000c) == 0 && d.vram[512 + 3] == 0, "DMA_COMMAND without bit 15 draws nothing");
    Check(d.Write(1, 0x800c) == 32 && V::DmaPixels(8, 4, 0, 0, true) == 32, "fill pixels = width * height, as the done timer");
    Check(d.vram[512 + 3] == 0x1256 && d.vram[2 * 512 + 6] == 0x1256 && d.vram[512 + 2] == 0 && d.vram[512 + 7] == 0 &&
          d.vram[3] == 0 && d.vram[3 * 512 + 3] == 0, "fill: palette | color inside the clip window only");
    Check(d.Read(0) == 0x800c && d.Read(1) == 0x800c, "dma_r maps register 0 to the command");
    d.Done();
    Check(d.Read(1) == 0x000c, "dma_done clears bit 15");
    Check(Rejection([&] { d.Write(1, 0xc012); }).find("0xc012") != std::string::npos, "unmeasured command rejects with its value");
    d.Write(10, 0x80);
    Check(Rejection([&] { d.Write(1, 0x800c); }).find("scale 0x80") != std::string::npos, "scaling rejects");
    {   // Game profile: unverified paths run, each recorded once (DmaPath id = command | scaled << 16 | skipdma << 17)
        D g(gfx);
        mk3::FirstExecution log;
        g.profile = mk3::Profile::Game; g.first = &log;
        g.Write(6, 2); g.Write(7, 2); g.Write(9, 5); g.Write(13, 0x3ff);   // bank 0: offset 13 = right clip
        g.Write(15, 0x30); g.Write(13, 0x1ff); g.Write(15, 0);               // bank 1: offset 13 = bottom clip
        Check(g.Write(1, 0x800d, 0xffff, 77) == 4 && g.vram[0] == 5 && g.vram[513] == 5, "game: unverified fill 0x800d runs");
        g.Write(1, 0x800d);
        g.Write(10, 0x80);
        Check(g.Write(1, 0x800d, 0xffff, 78) == 8, "game: scaled fill, pixels ((w << 8) / xstep) * ((h << 8) / ystep)");
        g.Write(10, 0); g.Write(3, 0x1000);
        Check(g.Write(1, 0xc002, 0xffff, 79) == 0, "game: skipdma arms the done timer with 0 pixels");
        Check(log.order.size() == 3 && log.order[0].id == 0x800d && log.order[0].cycle == 77 && log.order[1].id == 0x1800d &&
              log.order[2].id == 0x2c002 && log.order[0].kind == mk3::Unverified::DmaPath, "game: one first-execution entry per path");
        // Observer: same video RAM with and without it; every stored word owned by its draw, with the trigger state.
        D plain(gfx), seen(gfx);
        mk3::DmaOwners owners;
        seen.observer = &owners;
        plain.profile = seen.profile = mk3::Profile::Game;
        for (D* x : {&plain, &seen}) {
            x->Write(4, 3); x->Write(5, 2); x->Write(6, 4); x->Write(7, 3); x->Write(8, 0x0300); x->Write(13, 0x3ff);
            x->Write(15, 0x30); x->Write(13, 0x1ff); x->Write(15, 0);
            x->Write(1, 0xc002, 0xffff, 90);
            x->Write(1, 0x8013, 0xffff, 91);   // 8 bpp copy of zero pixels, xflip: overwrites part of the first draw
        }
        size_t owned = 0;
        for (size_t i = 0; i < plain.vram.size(); ++i) owned += owners.owner[i] != 0;
        const mk3::DmaDraw* last = owners.Owner(2 * 512 + 3);
        Check(plain.vram == seen.vram && owners.draws.size() == 2 && owned > 0 && last && last->serial == 2 && last->cycle == 91 &&
              last->command == 0x8013 && last->palette == 0x0300 && last->width == 4 && last->right == 0x3ff,
              "observer: read-only, last writer per video RAM word");
        D strict(gfx);
        strict.Write(3, 0x1000);
        Check(Rejection([&] { strict.Write(1, 0xc002); }).find("outside the graphics region") != std::string::npos, "strict: skipdma rejects");
    }
    d.Write(10, 0); d.Write(15, 0x10); d.Write(12, 0); d.Write(13, 0x3ff); d.Write(15, 0x30); d.Write(12, 0); d.Write(13, 0x1ff);
    // 0xc002: 4 bpp copy of nonzero pixels from bit 0: byte 0x0b -> pixels 0xb, 0x0, byte 0x30 -> 0x0, 0x3
    std::fill(d.vram.begin(), d.vram.end(), uint16_t(0x7777));
    d.Write(2, 0); d.Write(3, 0); d.Write(4, 0); d.Write(5, 9); d.Write(6, 4); d.Write(7, 1);
    Check(d.Write(1, 0xc002) == 4, "copy pixels");
    Check(d.vram[9 * 512] == (0x1200 | 0xb) && d.vram[9 * 512 + 1] == 0x7777 && d.vram[9 * 512 + 2] == 0x7777 &&
          d.vram[9 * 512 + 3] == (0x1200 | 0x3), "copy: nonzero pixels | palette, zero pixels skipped");
    // 0xc082: row header byte 0x0b = preskip 11, postskip 0; width 12 leaves one pixel (bits 8..11 of byte 1 = 0x0)
    d.Write(6, 12);
    std::fill(d.vram.begin(), d.vram.end(), uint16_t(0x7777));
    d.Write(1, 0xc082);
    Check(d.vram[9 * 512 + 11] == 0x7777 && d.vram[9 * 512 + 10] == 0x7777, "skip: preskip moves the start, zero pixel skipped");
    gfx[1] = 0x0e;  // pixel 0xe after the header
    d.Write(1, 0xc082);
    Check(d.vram[9 * 512 + 11] == (0x1200 | 0xe), "skip: pixel after an 11-pixel preskip");
    d.Write(2, uint16_t(gfx.size() * 8 - 16));  // first pixel inside, second one reads past the end
    const auto kept = d.vram;
    Check(Rejection([&] { d.Write(1, 0xc002); }).find("past the loaded") != std::string::npos && d.vram == kept,
          "read past the loaded ROM rejects before any video RAM write");
    // Done timer: 41 ns per pixel after the write, through VideoTiming.
    V v;
    v.DmaCommand(1000, 0x8000, 39, 2);
    Check(v.dma_armed && v.dma_expire == V::At(1002) + V::Atto(41 * 39) * 1000000000, "done 41 ns per pixel after the write");
    v.Advance(1010);
    Check(v.int1_count == 0, "done not before floor(T / cycle)");
    v.Advance(1011);
    Check(v.int1_count == 1 && v.last_int1_cycle == 1011 && (v.io[V::INTPEND] & V::INT1), "done at floor(T / cycle) raises INT1");
}

int Replay(const char* list, const char* events, int bias) {
    std::vector<uint8_t> gfx;
    std::ifstream graphics(list);
    std::string path;
    for (size_t offset, size; graphics >> offset >> size && std::getline(graphics >> std::ws, path);) {
        std::ifstream rom(path, std::ios::binary);
        std::vector<char> data(size);
        if (!rom.read(data.data(), std::streamsize(size)) || rom.peek() != EOF) { std::fprintf(stderr, "bad ROM %s\n", path.c_str()); return 2; }
        if (gfx.size() < (offset & ~size_t(3)) + 4 * size) gfx.resize((offset & ~size_t(3)) + 4 * size);
        for (size_t i = 0; i < size; ++i) gfx[offset + 4 * i] = uint8_t(data[i]);
    }
    std::printf("G %" PRIu64 "\n", Hash(gfx.data(), gfx.size()));
    mk3::Dma dma(gfx);
    mk3::VideoTiming video;
    uint64_t done_seen = 0;
    const auto state = [&] { return unsigned(dma.reg[mk3::Dma::COMMAND] & 0x8000) | (video.io[mk3::VideoTiming::INTPEND] & 2u); };
    unsigned last_state = 0;
    const auto advance = [&](uint64_t cycle) {
        video.Advance(cycle);
        if (video.int1_count != done_seen) {
            done_seen = video.int1_count;
            dma.Done();
            if (state() != last_state) std::printf("S T %" PRIu64 " %u\n", video.last_int1_cycle, last_state = state());
        }
    };
    std::ifstream in(events);
    std::string line;
    try {
        while (std::getline(in, line)) {
            std::istringstream f(line);
            char kind;
            f >> kind;
            if (kind == 'P') {
                std::string pair;
                size_t n;
                f >> n;
                while (f >> pair) dma.vram.at(std::stoul(pair, nullptr, 16)) = uint16_t(std::stoul(pair.substr(pair.find(':') + 1), nullptr, 16));
            } else if (kind == 'R') {
                unsigned off, data, mask;
                f >> std::hex >> off >> data >> mask;
                if (dma.Write(off, uint16_t(data), uint16_t(mask)) != -1) throw std::runtime_error("R event wrote DMA_COMMAND");
            } else if (kind == 'C') {
                uint64_t c;
                unsigned e, off, data, mask;
                f >> c >> e >> std::hex >> off >> data >> mask;
                advance(c);
                const auto before = dma.reg;
                const auto vram = dma.vram;
                const int pixels = dma.Write(off, uint16_t(data), uint16_t(mask));
                if (pixels < 0) throw std::runtime_error("C event is not a DMA_COMMAND write");
                video.DmaCommand(c, dma.reg[mk3::Dma::COMMAND], pixels, e);
                if (dma.reg[mk3::Dma::COMMAND] & 0x8000) {
                    video.dma_expire += mk3::VideoTiming::Atto(bias) * mk3::VideoTiming::kCycle;
                    std::printf("T %d %" PRIu64, pixels, uint64_t(video.dma_expire / mk3::VideoTiming::kCycle));
                    for (uint16_t r : before) std::printf(" %X", r);
                    std::string delta;
                    size_t n = 0;
                    char buffer[24];
                    for (size_t i = 0; i < vram.size(); ++i)
                        if (vram[i] != dma.vram[i]) { std::snprintf(buffer, sizeof buffer, " %zX:%X", i, dma.vram[i]); delta += buffer; ++n; }
                    std::printf("\nV %zu%s\nH %" PRIu64 "\n", n, delta.c_str(),
                                Hash(reinterpret_cast<const uint8_t*>(dma.vram.data()), dma.vram.size() * 2));
                }
                if (state() != last_state) std::printf("S W %" PRIu64 " %u\n", c, last_state = state());
            } else if (kind == 'E') {
                uint64_t c;
                f >> c;
                advance(c);
            } else throw std::runtime_error("bad event: " + line.substr(0, 40));
        }
    } catch (const std::runtime_error& e) {
        std::printf("REJECT %s\n", e.what());
    }
    return 0;
}
} // namespace

// Per-mode cases for tools/mk3/test_dma_modes.py: gfx = raw region bytes; each case line "K r0 .. r17" (hex) loads the
// 18 registers into a fresh Dma (Game profile) over the video RAM pattern (i * 7) & 0x7fff and writes DMA_COMMAND = r1.
// Output per case: "T pixels n idx:val ..." (changed words) or "REJECT what"; then "N paths" (first-execution entries).
int Modes(const char* gfx_path, const char* cases_path) {
    std::ifstream g(gfx_path, std::ios::binary);
    const std::vector<uint8_t> gfx((std::istreambuf_iterator<char>(g)), std::istreambuf_iterator<char>());
    std::ifstream in(cases_path);
    mk3::FirstExecution log;
    std::string line;
    while (std::getline(in, line)) {
        std::istringstream f(line);
        char kind;
        f >> kind;
        mk3::Dma dma(gfx);
        dma.profile = mk3::Profile::Game; dma.first = &log;
        for (auto& r : dma.reg) { unsigned v; f >> std::hex >> v; r = uint16_t(v); }
        for (size_t i = 0; i < dma.vram.size(); ++i) dma.vram[i] = uint16_t((i * 7) & 0x7fff);
        try {
            const int pixels = dma.Write(1, dma.reg[mk3::Dma::COMMAND]);
            size_t n = 0;
            std::string delta;
            char buffer[24];
            for (size_t i = 0; i < dma.vram.size(); ++i)
                if (dma.vram[i] != uint16_t((i * 7) & 0x7fff)) { std::snprintf(buffer, sizeof buffer, " %zX:%X", i, dma.vram[i]); delta += buffer; ++n; }
            std::printf("T %d %zu%s\n", pixels, n, delta.c_str());
        } catch (const std::runtime_error& e) { std::printf("REJECT %s\n", e.what()); }
    }
    std::printf("N %zu\n", log.order.size());
    return 0;
}

int main(int argc, char** argv) {
    SelfChecks();
    if (failures) return 1;
    if (argc == 4 && std::string(argv[1]) == "modes") return Modes(argv[2], argv[3]);
    if (argc >= 3) return Replay(argv[1], argv[2], argc > 3 ? std::atoi(argv[3]) : 0);
    std::puts("mk3 dma self-checks passed");
    return 0;
}
