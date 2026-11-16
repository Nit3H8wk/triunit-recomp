#include "mk3_program.hpp"
#include "mk5_program.hpp"
#include <fstream>
#include <stdexcept>

namespace mk3 {
uint16_t Program::Word(uint32_t bit_address) const {
    if (bit_address < kProgramBaseBit || (bit_address & 15))
        throw std::runtime_error("MK3 program word outside the aligned ROM window");
    const size_t offset = (bit_address - kProgramBaseBit) / 8;
    return uint16_t(bytes.at(offset) | bytes.at(offset + 1) << 8);
}

Program VerifyProgramLanes(const std::vector<uint8_t>& even, const std::vector<uint8_t>& odd) {
    if (even.size() != 0x80000 || odd.size() != 0x80000)
        throw std::runtime_error("MK3 rev 2.1 requires two 512 KiB program lanes");
    Program program;
    program.bytes.resize(0x100000);
    for (size_t i = 0; i < even.size(); ++i) {
        program.bytes[i * 2] = even[i];
        program.bytes[i * 2 + 1] = odd[i];
    }
    program.sha256 = Sha256(program.bytes);
    if (program.sha256 != kProgramSha256)
        throw std::runtime_error("MK3 rev 2.1 interleaved program SHA-256 mismatch");
    return program;
}

Program LoadProgram(const std::filesystem::path& directory) {
    auto read = [&](const char* name) {
        const auto path = directory / name;
        std::error_code error;
        if (std::filesystem::file_size(path, error) != 0x80000 || error)
            throw std::runtime_error("MK3 rev 2.1 program ROM missing or wrong size");
        std::ifstream input(path, std::ios::binary);
        std::vector<uint8_t> bytes(0x80000);
        if (!input.read(reinterpret_cast<char*>(bytes.data()), bytes.size()) ||
            input.peek() != std::char_traits<char>::eof())
            throw std::runtime_error("MK3 rev 2.1 program ROM read failed or changed");
        return bytes;
    };
    return VerifyProgramLanes(read("mk321u54.bin"), read("mk321u63.bin"));
}
}
