#include "../mk2/mk2_scanout.hpp"
#include "../mk2/mk2_program.hpp"
#include "mk5_program.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void need(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
constexpr uint32_t xy(unsigned x, unsigned y) { return x | (y << 16); }

void check(mk2::BootVideo& video, mk2::Scanout& scanout, const mk2::Program& program) {
    video.EnableBlood(program);
    const auto original = video.vram;
    constexpr unsigned x = 120, y = 216;
    // RGB555 words used by the original physical DMA of this frame.
    constexpr const char* expected[] = {
        "0ec7800f5fa9a40269e183aeaa1fd29dab148d41c3d47628f0cb093201ffd43f",
        "e6b81ba0704d98a34e864d90cbc51c52a373ee4a51b16d949023ea0b61d88984"
    };
    constexpr uint16_t slot = 0x0400;
    for (unsigned flip = 0; flip < 2; ++flip) {
        video.ClearBlood();
        video.palette_ram[slot+4] = 0x7c00;
        video.palette_ram[slot+6] = 0x7083;
        video.palette_ram[slot+11] = 0x4400;
        video.KeepBlood(x, y, flip, 0x0404);
        video.palette_ram[slot+4] = video.palette_ram[slot+6] = video.palette_ram[slot+11] = 0x03e0;
        video.DrawBlood(0, 0, 0, xy(400, 254));
        std::vector<uint8_t> rgb;
        for (unsigned dy = 0; dy < 11; ++dy) {
            for (unsigned dx = 0; dx < 35; ++dx) {
                const auto pixel = video.BloodPixel((y + dy) * 512 + x + dx);
                for (unsigned shift : {16u, 8u, 0u}) rgb.push_back(uint8_t(pixel >> shift));
            }
        }
        need(Sha256(rgb) == expected[flip], "the splash retains live colors, shape and orientation after palette reuse");
    }
    constexpr auto page = xy(56, 256);
    video.QueueBloodDraw(0x0101d540, page, xy(10, 8), 0, xy(400, 254), true);
    constexpr auto index = (256 + y - 8) * 512 + 56 + x - 10 + 4;
    video.DrawQueuedBlood(0x0101d600);
    need(video.BloodPixel(index) == 0, "the queued splash waits for the last terrain draw");
    video.DrawQueuedBlood(0x0101d540);
    need(video.BloodPixel(index) == 0xff8c0000, "the mirrored splash follows the camera onto the back page");
    need(video.vram == original, "composition leaves arcade video memory intact");

    mk2::BoardBootControls board;
    board.io[1] = 50; board.io[2] = 250; board.io[3] = 252;
    board.io[5] = 20; board.io[6] = 21; board.io[7] = 288; board.io[8] = 0xe410;
    board.io[27] = 28;
    board.vcount = 20; board.display_address = 0x1d00;
    scanout.Line(board, video);
    board.vcount = 21;
    scanout.Line(board, video);
    need(scanout.pixels()[x - 10 + 4] == 0xff000000 &&
         scanout.presentation()[x - 10 + 4] == 0xff8c0000, "presentation preserves a separate arcade raster");

    video.WriteVram(index * 8, 0, board, 0x00ff);
    need(video.BloodPixel(index) == 0, "a later foreground write occludes the splash");
    video.DrawBlood(page, xy(10, 8), 0, xy(400, 254));
    need(video.BloodPixel(index) == 0xff8c0000, "occlusion does not delete the ground stain");
    auto& r = video.dma_registers;
    r[4] = r[17] = index % 512;
    r[5] = r[13] = index / 512;
    r[6] = r[7] = 1;
    video.StartDma(0x800c, board, program.graphics);
    need(video.BloodPixel(index) == 0, "a later foreground DMA occludes the splash");
    video.ClearBlood();
    video.DrawBlood(page, xy(10, 8), 0, xy(400, 254));
    need(video.BloodPixel(index) == 0, "new combat clears both draw pages");
}

// The program's palette fades (mk5_blood_shade.hpp): with the floor under the stain dimmed from 93 to 45 (Sum of its
// RGB555), to black and back, with no draw in between, the presented stain dims with it (rounded per channel), shows
// its kept colours again, exactly, and never brightens; the arcade raster stays canonical.
unsigned checks = 0, negatives = 0;
void check_fade(bool condition, const char* message) { need(condition, message); ++checks; }
void negative(bool rejected, const char* message) { need(rejected, message); ++negatives; }

void fades(const mk2::Program& program) {
    constexpr unsigned x = 120, y = 216, floor_pen = 0x0010;
    constexpr uint16_t bright = 0x7fff, half = 0x3def;   // Sum 93 and 45
    const auto dim = [](uint32_t rgb, unsigned now, unsigned then) {
        const auto ch = [&](unsigned shift) {
            const unsigned v = ((rgb >> shift & 255) >> 3) * now;
            const unsigned d = (v + then / 2) / then;
            return ((d << 3) | (d >> 2)) << shift;
        };
        return 0xff000000u | ch(16) | ch(8) | ch(0);
    };
    struct Rig {
        mk2::BootVideo video;
        mk2::BoardBootControls board;
        mk2::Scanout scanout{true};
    };
    // One frame of the 11 stain rows (page 0, column 0, 400 wide).
    const auto present = [](Rig& r) {
        auto& io = r.board.io;
        io[1] = 50; io[2] = 250; io[3] = 252; io[5] = 20; io[6] = 31; io[7] = 288; io[8] = 0xe410; io[27] = 0;
        for (unsigned v = 20; v <= 31; ++v) {
            r.board.vcount = v;
            r.board.display_address = uint16_t((y + v - 20) << 4);
            r.scanout.Line(r.board, r.video);
        }
    };
    const auto make = [&](Rig& r, uint16_t floor) {
        r.video.EnableBlood(program);
        r.video.EnableFighters();
        std::fill(r.video.vram.begin(), r.video.vram.end(), uint16_t(floor_pen));
        for (unsigned s = 0; s < 12; ++s) r.video.palette_ram[0x0400 + s] = uint16_t(0x0421 * s + 0x1000);
        r.video.KeepBlood(x, y, false, 0x0404);
        r.video.palette_ram[floor_pen] = floor;
        r.video.DrawBlood(0, 0, 0, xy(400, 254));
    };
    // Every stain pixel of the frame against `want(kept colour)`; the raster keeps the floor colour.
    const auto all = [&](const Rig& r, auto want) {
        unsigned stains = 0;
        for (unsigned dy = 0; dy < 11; ++dy)
            for (unsigned dx = 0; dx < 35; ++dx) {
                const auto kept = r.video.BloodPixel((y + dy) * 512 + x + dx);
                const size_t p = size_t(dy) * 400 + x + dx;
                if (!kept) continue;
                ++stains;
                if (r.scanout.presentation()[p] != want(kept) ||
                    r.scanout.pixels()[p] != mk2::ExpandRgb555(r.video.palette_ram[floor_pen])) return false;
            }
        return stains > 0;
    };
    const auto exact = [](uint32_t kept) { return kept; };
    const auto halved = [&](uint32_t kept) { return dim(kept, 45, 93); };

    Rig f; make(f, bright);
    present(f);
    check_fade(all(f, exact) && f.scanout.blood_shade().now == f.scanout.blood_shade().then,
               "floor blood: without a fade the stain keeps its colours exactly (ratio 1)");
    // A shadow drawn under half of the stain before the next pass, no palette change: the kept colours stay exact.
    {
        Rig s; make(s, bright);
        for (size_t i = y * 512; i < (y + 6) * 512; ++i) s.video.vram[i] = 0x0020;
        s.video.palette_ram[0x0020] = 0;
        s.video.DrawBlood(0, 0, 0, xy(400, 254)); present(s);
        bool kept = true;
        for (unsigned dy = 0; dy < 11; ++dy)
            for (unsigned dx = 0; dx < 35; ++dx)
                if (const auto c = s.video.BloodPixel((y + dy) * 512 + x + dx))
                    kept &= s.scanout.presentation()[size_t(dy) * 400 + x + dx] == c;
        check_fade(kept && s.scanout.blood_shade().now == s.scanout.blood_shade().then,
                   "floor blood: a shadow under the stain without a fade leaves its colours");
    }
    f.video.palette_ram[floor_pen] = half; present(f);
    check_fade(all(f, halved), "floor blood: the stain dims with the floor it covers (45/93, per channel)");
    negative(!all(f, exact), "stain kept bright through a fade");
    negative(f.scanout.pixels() != f.scanout.presentation(), "the arcade raster carries the stain");
    f.video.palette_ram[floor_pen] = 0; present(f);
    check_fade(all(f, [](uint32_t) { return 0xff000000u; }), "floor blood: a fade to black takes the stain along");
    // A draw during the fade keeps the references of the first cover.
    f.video.palette_ram[floor_pen] = half; f.video.DrawBlood(0, 0, 0, xy(400, 254)); present(f);
    check_fade(all(f, halved), "floor blood: a draw during the fade keeps the first references");
    negative(!all(f, exact), "references retaken during the fade");
    f.video.palette_ram[floor_pen] = bright; present(f);
    check_fade(all(f, exact), "floor blood: the kept colours come back exactly with the floor");

    // First covered over a dim floor, then the floor brightens: never above the kept colours.
    Rig g; make(g, half);
    g.video.palette_ram[floor_pen] = bright; present(g);
    check_fade(all(g, exact), "floor blood: a brighter floor leaves the kept colours");
    negative(!all(g, [&](uint32_t kept) { return dim(kept, 93, 46); }), "stain brightened above its kept colours");

    // A fighter drawn over a stain pixel: its covered underlay dims with the frame's stains.
    Rig h; make(h, bright);
    constexpr size_t at = size_t(y + 5) * 512 + x + 17;
    const auto kept = h.video.BloodPixel(at);
    need(kept != 0, "the fighter rig covers a stain pixel");
    auto& r = h.video.dma_registers;
    r[4] = r[17] = at % 512; r[5] = r[13] = uint16_t(at / 512); r[6] = r[7] = 1; r[9] = 1;
    h.video.StartDma(0x800c, h.board, program.graphics, false, 1);
    need(h.video.BloodPixel(at) == 0 && h.video.FighterVideo().Blood(at) == kept, "the fighter covers the stain pixel");
    h.video.palette_ram[floor_pen] = half; present(h);
    const auto& fighter = h.scanout.fighter_frame();
    const size_t p = 5 * 400 + x + 17;
    check_fade(fighter.serial && fighter.covered[p] && fighter.underlay[p] == (halved(kept) & 0xffffff),
               "floor blood: the fighter's covered underlay dims with the stains");
    negative(fighter.underlay[p] != (kept & 0xffffff), "fighter underlay kept bright through a fade");
}

}

int main(int argc, char** argv) try {
    need(argc == 2, "pass the MK2 L3.1 ROM directory");
    const auto program = mk2::LoadProgram(argv[1]);
    mk2::BootVideo video;
    mk2::Scanout scanout(true);
    check(video, scanout, program);
    fades(program);
    std::cout << "PASS MK2 Remastered floor splash; fades " << checks << " checks, " << negatives << " negatives\n";
    return 0;
} catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
}
