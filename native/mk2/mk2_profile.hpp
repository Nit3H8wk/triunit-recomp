#pragma once
#include <cstdint>
#include <filesystem>
#include <functional>
#include <string>
#include <vector>

namespace mk2 {
struct CmosProfileSnapshot { std::vector<uint8_t> image; std::string sha256; };
enum class CmosLock { Mk1Session, Mk2Profile };
// Operator edits preserve opaque bytes; the target must be an existing cmos.bin.
CmosProfileSnapshot LoadCmosFile(const std::filesystem::path& file);
// Commit runs under the game lock; failure restores the previous CMOS before unlock.
std::string CompareAndSwapCmosFile(const std::filesystem::path& file,
    const std::vector<uint8_t>& image,const std::string& expected_sha256,CmosLock lock,
    const std::function<void()>& commit={});
// Storage preserves all 16384 bytes; arcade CMOS validation belongs to reset.
CmosProfileSnapshot LoadCmosProfile(const std::filesystem::path& directory);
CmosProfileSnapshot PrepareCmosProfile(const std::filesystem::path& directory,const std::filesystem::path& authenticated_seed);
std::string CompareAndSwapCmosProfile(const std::filesystem::path& directory,
    const std::vector<uint8_t>& image,const std::string& expected_sha256);
}
