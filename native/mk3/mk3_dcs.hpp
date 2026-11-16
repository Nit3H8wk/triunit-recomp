#pragma once
#include <cstdint>
#include <filesystem>
#include <vector>

namespace mk3 {
// DCS Audio 8K (REV_DCS1): U2 is ROM_LOAD16_BYTE at dcs offset 0; the ADSP-2105 boots from its first page.
inline constexpr const char* kDcsU2Sha256 = "eeffa20b1b436860682874464cc17efee597fdaa96c0bda34bd7e949072ffda6";
std::vector<uint8_t> LoadDcsU2(const std::filesystem::path& rom_directory);
std::vector<uint32_t> LoadDcsBoot(const std::filesystem::path& rom_directory); // 24-bit PM words.
}
