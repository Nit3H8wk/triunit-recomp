// MK1 Remastered floor blood through the program's palette fades (mk5_blood_shade.hpp): the splash kept and drawn as
// the live path does (Mk5LiveVideo::ObserveBlood), the floor under it dimmed from 93 to 45 (Sum of its RGB555), to
// black and back with no draw in between; the presented stain dims with it (rounded per channel), shows its kept
// colours again, exactly, never brightens, and a fighter's covered underlay dims along. The Original raster stays the
// canonical one. Built with -fno-access-control to drive the scanline observer and the fighter surface directly.
#include "mk5_scanout.hpp"
#include "mk5_live_video.hpp"
#include <iostream>
#include <stdexcept>

namespace {
unsigned checks = 0, negatives = 0;
void need(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void check(bool condition, const char* message) { need(condition, message); ++checks; }
void negative(bool rejected, const char* message) { need(rejected, message); ++negatives; }

constexpr unsigned kX = 100, kY = 220, kLeft = 90, kWidth = 80, kFloorPen = 0x0010;
constexpr uint16_t kBright = 0x7fff, kHalf = 0x3def;   // Sum 93 and 45
constexpr uint32_t kObject = 0x01001000;

uint32_t dim(uint32_t rgb, unsigned now, unsigned then) {
    const auto ch = [&](unsigned shift) {
        const unsigned d = (((rgb >> shift & 255) >> 3) * now + then / 2) / then;
        return ((d << 3) | (d >> 2)) << shift;
    };
    return ch(16) | ch(8) | ch(0);
}
uint32_t expand(uint16_t c) {
    const auto e = [](unsigned v) { return (v << 3) | (v >> 2); };
    return e(c >> 10 & 31) << 16 | e(c >> 5 & 31) << 8 | e(c & 31);
}

struct Rig {
    Mk5MemoryBuffers memory;
    ResetTrace cpu{};
    Mk5IrqEpoch epoch{};
    std::unique_ptr<Mk5IrqController> irq;
    BootDiState di;
    std::unique_ptr<Mk5LiveVideo> video;
    std::unique_ptr<Mk5Scanout> screen;
    unsigned top = 0, rows = 0;
    void set(uint32_t bit, uint16_t value) { memory.ram[(bit - 0x01000000) / 16] = value; }
    Rig(const VerifiedMk5Program& program, const VerifiedMk5GlyphBank& graphics, uint16_t floor, bool remastered = true) {
        cpu.a[15] = 0x01000200;
        auto& io = epoch.io;
        top = kY - 2; rows = 40;
        io[1] = 0; io[2] = io[3] = kWidth / 2; io[5] = 0; io[6] = uint16_t(rows); io[7] = 288; io[8] = 0xe400; io[27] = kLeft / 2;
        epoch.quanta_to_next_scanline = 1;
        std::fill(memory.vram.begin(), memory.vram.end(), uint16_t(kFloorPen));
        memory.palette[kFloorPen] = floor;
        irq = std::make_unique<Mk5IrqController>(program, cpu, memory, epoch);
        video = std::make_unique<Mk5LiveVideo>(graphics, cpu, memory, *irq, di, &program);
        const auto sprite = video->blood_sprite;
        need(sprite.height + 4 <= int(rows) && kX + sprite.width <= kLeft + kWidth, "the splash fits the rig's frame");
        if (!remastered) video.reset();
        screen = std::make_unique<Mk5Scanout>(*irq, memory, video.get());
        if (!video) return;
        // A new bout, then the splash kept at (kX, kY) as its object is removed, then the arena pass draws it.
        set(0x01051190, 2);
        set(kObject + 0x90, kX); set(kObject + 0xb0, kY);
        set(kObject + 0x180, uint16_t(sprite.frame)); set(kObject + 0x190, uint16_t(sprite.frame >> 16));
        cpu.a[8] = kObject; cpu.a[13] = (254u << 16) | 400;
        video->ObserveBlood(0xffc9f010, cpu);
        video->ObserveBlood(0xffde7ad0, cpu);
        need(video->blood_stains.size() == 1, "the splash is kept");
        Draw();
    }
    void Draw() { video->ObserveBlood(0xffc7a700, cpu); }
    // One frame of the stain rows (page 0, columns kLeft..kLeft+kWidth).
    void Present() {
        const auto io = epoch.io;
        for (unsigned v = 0; v <= rows; ++v)
            irq->scanline_observer_(Mk5ScanlineEvent{v, uint16_t(v), uint16_t((top + v) << 4), false}, io);
    }
    size_t Pixel(size_t index) const { return (index / 512 - top) * kWidth + index % 512 - kLeft; }
    // Every stain pixel of the frame against `want(kept colour)`.
    template<class Want> bool All(Want want) const {
        unsigned stains = 0;
        for (size_t i = kY * 512; i < (kY + rows) * 512; ++i) {
            const auto kept = video->BloodPixel(i);
            if (!kept) continue;
            ++stains;
            if (screen->pixels()[Pixel(i)] != want(kept)) return false;
        }
        return stains > 0;
    }
};
}

int main(int argc, char** argv) try {
    need(argc == 2, "pass the MK1 L5.0 ROM directory");
    const auto program = LoadMk5Program(argv[1]);
    const auto graphics = LoadMk5GlyphBank(argv[1]);
    const auto exact = [](uint32_t kept) { return kept; };
    const auto halved = [](uint32_t kept) { return dim(kept, 45, 93); };

    Rig f(program, graphics, kBright);
    f.Present();
    check(f.All(exact) && f.screen->blood_frame_shade().now == f.screen->blood_frame_shade().then,
          "floor blood: without a fade the stain keeps its colours exactly (ratio 1)");
    Rig original(program, graphics, kBright, false);
    original.Present();
    {
        bool canonical = true;
        for (size_t p = 0; p < original.screen->pixels().size(); ++p) canonical &= original.screen->pixels()[p] == expand(kBright);
        check(canonical, "floor blood: the Original raster has no stain");
        negative(original.screen->pixels() != f.screen->pixels(), "the Remastered frame shows no stain");
    }
    // A shadow drawn under half of the stain before the next blood pass (MK1 draws the shadows first), no palette change:
    // the kept colours stay exact.
    {
        Rig s(program, graphics, kBright);
        for (size_t i = kY * 512; i < (kY + 6) * 512; ++i) s.memory.vram[i] = 0x0020;
        s.memory.palette[0x0020] = 0;
        s.Draw(); s.Present();
        check(s.All(exact) && s.screen->blood_frame_shade().now == s.screen->blood_frame_shade().then,
              "floor blood: a shadow under the stain without a fade leaves its colours");
    }
    f.memory.palette[kFloorPen] = kHalf; f.Present();
    check(f.All(halved), "floor blood: the stain dims with the floor it covers (45/93, per channel)");
    negative(!f.All(exact), "stain kept bright through a fade");
    f.memory.palette[kFloorPen] = 0; f.Present();
    check(f.All([](uint32_t) { return 0u; }), "floor blood: a fade to black takes the stain along");
    // A draw during the fade keeps the references of the first cover.
    f.memory.palette[kFloorPen] = kHalf; f.Draw(); f.Present();
    check(f.All(halved), "floor blood: a draw during the fade keeps the first references");
    negative(!f.All(exact), "references retaken during the fade");
    f.memory.palette[kFloorPen] = kBright; f.Present();
    check(f.All(exact), "floor blood: the kept colours come back exactly with the floor");

    // First covered over a dim floor, then the floor brightens: never above the kept colours.
    Rig g(program, graphics, kHalf);
    g.memory.palette[kFloorPen] = kBright; g.Present();
    check(g.All(exact), "floor blood: a brighter floor leaves the kept colours");
    negative(!g.All([](uint32_t kept) { return dim(kept, 93, 46); }), "stain brightened above its kept colours");

    // A fighter drawn over a stain pixel (as Mk5LiveVideo::Write does): its covered underlay dims with the stains.
    Rig h(program, graphics, kBright);
    size_t at = 0;
    for (size_t i = (kY + 3) * 512 + kX; i < (kY + 4) * 512 && !at; ++i) if (h.video->BloodPixel(i)) at = i;
    need(at != 0, "the fighter rig covers a stain pixel");
    const auto kept = h.video->BloodPixel(at);
    auto draw = h.video->fighters.Draw(1);
    h.memory.vram[at] = 0x0123;
    h.video->fighters.Write(draw, at, h.memory.vram[at], kept);
    h.video->blood_layer[at] = 0;
    need(h.video->FighterVideo().Blood(at) == kept, "the fighter covers the stain pixel");
    h.memory.palette[kFloorPen] = kHalf; h.Present();
    const auto& fighter = h.screen->fighter_frame();
    const auto p = h.Pixel(at);
    check(fighter.serial && fighter.covered[p] && fighter.underlay[p] == halved(kept),
          "floor blood: the fighter's covered underlay dims with the stains");
    negative(fighter.underlay[p] != kept, "fighter underlay kept bright through a fade");
    std::cout << "PASS MK1 Remastered floor blood fades: " << checks << " checks, " << negatives << " negatives\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << "FAIL MK1 Remastered floor blood fades: " << e.what() << '\n';
    return 1;
}
