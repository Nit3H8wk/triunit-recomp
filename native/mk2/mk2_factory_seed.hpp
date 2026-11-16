#pragma once
#include "mk2_program.hpp"
#include <filesystem>

namespace mk2 {
// The factory CMOS seed is not versioned: the local setup (tools/setup/mk2.py, factory_seed()) writes it next to the
// generated includes of the authenticated program, from the game's own factory boot.
inline std::filesystem::path FactorySeedPath(const std::filesystem::path& root = {}) {
    return root / "generated" / "mk2" / kProgramSha256 / "mk2-factory-default-cmos.bin";
}
}
