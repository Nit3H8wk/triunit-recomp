#pragma once
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

struct VerifiedMk5Program {
    std::vector<uint8_t> bytes;
    std::string sha256;
    std::filesystem::path even_source,odd_source;
};

inline constexpr const char* kMk5ProgramSha256="ae1e5b310c6e512168b2ab7ff796a7656656898cf82ea98735bed0cd12288a06";
std::string Sha256(const std::vector<uint8_t>& bytes);
VerifiedMk5Program LoadMk5Program(const std::filesystem::path& root);
