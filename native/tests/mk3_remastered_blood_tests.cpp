// MK3 Remastered floor blood (native/mk3/mk3_blood.hpp) on the user's ROM: the splash frame decoded by the board's DMA
// and its composition, plain and mirrored, with the colours kept at the delete. Only the SHA-256 of the results is
// stored here; the pens of the program's own last splash draws were compared against the same composition on routes
// (plan 2026-11-19, stage C).
#include "../mk3/mk3_dma.hpp"
#include "mk5_program.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace {
void need(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
std::vector<uint8_t> LoadGraphics(const char* list) {   // rows "offset size path", ROM_LOAD32_BYTE (mk3_preview_main.cpp)
    std::vector<uint8_t> gfx;
    std::ifstream rows(list);
    std::string path;
    for (size_t offset, size; rows >> offset >> size && std::getline(rows >> std::ws, path);) {
        std::ifstream rom(path, std::ios::binary);
        std::vector<char> data(size);
        need(bool(rom.read(data.data(), std::streamsize(size))), "bad MK3 graphics ROM");
        if (gfx.size() < (offset & ~size_t(3)) + 4 * size) gfx.resize((offset & ~size_t(3)) + 4 * size);
        for (size_t i = 0; i < size; ++i) gfx[offset + 4 * i] = uint8_t(data[i]);
    }
    need(!gfx.empty(), "no MK3 graphics ROMs");
    return gfx;
}
}

int main(int argc, char** argv) try {
    need(argc == 3, "pass the MK3 rev 2.1 ROM directory and its graphics list");
    const auto program = mk3::LoadProgram(argv[1]);
    mk3::FloorBlood blood;
    mk3::EnableFloorBlood(blood, program, LoadGraphics(argv[2]));
    constexpr const char* kShape = "7156262383b104725d02b7ce141437caa72d3ca546cb84df5be9bb61644e0410";
    constexpr const char* kComposed[] = {"51e87113dd8fe0fc88d9d681841ea9892425dec5d78c668ad9cc43c3b88ea064",
                                            "143e83025c2eac98e4fef4cba0a733405630b34b89351426d9be06ac61606f7a"};
    need(Sha256(blood.shape) == kShape, "the splash pixels are the original frame decoded by the board's DMA");
    mk3::FloorBlood::Colors colors{};
    for (size_t k = 0; k < colors.size(); ++k) colors[k] = uint16_t(k << 10 | (15 - k) << 5 | 3);
    constexpr int x = 120, y = 200, page_x = 56, w = mk3::FloorBlood::kWidth, h = mk3::FloorBlood::kHeight;
    std::vector<uint16_t> plain;
    for (const bool flip : {false, true}) {
        blood.Clear();
        blood.stains[{int16_t(x), int16_t(y), flip}].colors = colors;
        blood.Draw({1, uint32_t(page_x), 0, 0, 0x00fe0190, true}, blood.layer, nullptr);   // page 0 at x 56, camera 0, clip 400 x 254
        std::vector<uint8_t> bytes;
        std::vector<uint16_t> box;
        for (int dy = 0; dy < h; ++dy)
            for (int dx = 0; dx < w; ++dx) {
                const uint16_t v = blood.At(size_t(y + dy) * 512 + size_t(page_x + x + dx));
                box.push_back(v); bytes.push_back(uint8_t(v >> 8)); bytes.push_back(uint8_t(v));
            }
        need(Sha256(bytes) == kComposed[flip], "the kept splash composes the original shape with its kept colours");
        if (!flip) { plain = box; continue; }
        for (int dy = 0; dy < h; ++dy)
            for (int dx = 0; dx < w; ++dx) need(box[size_t(dy * w + dx)] == plain[size_t(dy * w + w - 1 - dx)], "the mirrored splash is the plain one reversed");
    }
    std::cout << "PASS MK3 Remastered floor splash\n";
    return 0;
} catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
}
