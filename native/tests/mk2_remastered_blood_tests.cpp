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

}

int main(int argc, char** argv) try {
    need(argc == 2, "pass the MK2 L3.1 ROM directory");
    const auto program = mk2::LoadProgram(argv[1]);
    mk2::BootVideo video;
    mk2::Scanout scanout(true);
    check(video, scanout, program);
    std::cout << "PASS MK2 Remastered floor splash\n";
    return 0;
} catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
}
