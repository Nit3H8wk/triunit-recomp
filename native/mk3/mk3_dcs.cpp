#include "mk3_dcs.hpp"
#include "mk2_dcs.hpp"
#include "mk5_program.hpp"
#include <fstream>
#include <stdexcept>

namespace mk3 {
std::vector<uint8_t> LoadDcsU2(const std::filesystem::path& directory) {
    const auto path = directory / "l1_mortal_kombat_3_u2_music_spch.u2";
    std::error_code error;
    if (std::filesystem::file_size(path, error) != 0x100000 || error)
        throw std::runtime_error("MK3 DCS U2 ROM missing or wrong size");
    std::ifstream input(path, std::ios::binary);
    std::vector<uint8_t> bytes(0x100000);
    if (!input.read(reinterpret_cast<char*>(bytes.data()), bytes.size()) || input.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("MK3 DCS U2 ROM read failed or changed");
    if (Sha256(bytes) != kDcsU2Sha256) throw std::runtime_error("MK3 DCS U2 ROM SHA-256 mismatch");
    return bytes;
}

std::vector<uint32_t> LoadDcsBoot(const std::filesystem::path& directory) {
    const auto bytes = LoadDcsU2(directory);
    // Same adsp21xx boot format as MK2's DCS1 board (tools: mk2::DecodeDcsBoot).
    return mk2::DecodeDcsBoot({bytes.begin(), bytes.begin() + 0x1000});
}
}
