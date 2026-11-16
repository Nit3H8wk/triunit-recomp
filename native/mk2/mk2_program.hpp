#pragma once
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace mk2 {
inline constexpr const char* kProgramSha256 =
    "45b3285496db555efaf4a3608a4f59845dd47a82e4a0593607e0592f47b36f23";
inline constexpr uint32_t kResetPc = 0xff810f80;
inline constexpr const char* kGraphicsSha256 = "b42e8b8d0d58a3649bafac26449fd9c4fc7c964a5798b971d15cd689bd62df7f";
struct Program {
    std::vector<uint8_t> bytes;
    std::vector<uint8_t> graphics;
    std::string sha256;
};
Program VerifyProgramLanes(const std::vector<uint8_t>& even, const std::vector<uint8_t>& odd);
Program LoadProgram(const std::filesystem::path& rom_directory);
}
