#pragma once
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace mk3 {
// MK3 rev 2.1 (MAME `mk3`): ROM_LOAD16_BYTE mk321u54.bin (even) / mk321u63.bin (odd); tools/mk3/roms-21.json.
inline constexpr const char* kProgramSha256 = "1bc7a53a023f15b20f01398f87e38478a27c670df27ea320e36125d0957ee651";
inline constexpr uint32_t kProgramBaseBit = 0xff800000; // TMS34010 bit address of program byte 0.
inline constexpr uint32_t kResetPc = 0xff8148b0;
struct Program {
    std::vector<uint8_t> bytes;
    std::string sha256;
    uint16_t Word(uint32_t bit_address) const;
};
Program VerifyProgramLanes(const std::vector<uint8_t>& even, const std::vector<uint8_t>& odd);
Program LoadProgram(const std::filesystem::path& rom_directory);
}
