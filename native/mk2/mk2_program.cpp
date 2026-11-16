#include "mk2_program.hpp"
#include "mk5_program.hpp"
#include <fstream>
#include <stdexcept>

namespace mk2 {
Program VerifyProgramLanes(const std::vector<uint8_t>& even, const std::vector<uint8_t>& odd) {
    if (even.size() != 0x80000 || odd.size() != 0x80000)
        throw std::runtime_error("MK2 L3.1 requires two 512 KiB program lanes");
    Program program;
    program.bytes.resize(0x100000);
    for (size_t i = 0; i < even.size(); ++i) {
        program.bytes[i * 2] = even[i];
        program.bytes[i * 2 + 1] = odd[i];
    }
    program.sha256 = Sha256(program.bytes);
    if (program.sha256 != kProgramSha256)
        throw std::runtime_error("MK2 L3.1 interleaved program SHA-256 mismatch");
    return program;
}

Program LoadProgram(const std::filesystem::path& directory) {
    auto read = [&](const char* name, size_t expected = 0x80000) {
        const auto path = directory / name;
        std::error_code error;
        const auto size = std::filesystem::file_size(path, error);
        if (error || size != expected)
            throw std::runtime_error("MK2 L3.1 program ROM missing or wrong size");
        std::ifstream input(path, std::ios::binary);
        std::vector<uint8_t> bytes(expected);
        if (!input.read(reinterpret_cast<char*>(bytes.data()), bytes.size()) ||
            input.peek() != std::char_traits<char>::eof())
            throw std::runtime_error("MK2 L3.1 program ROM read failed or changed");
        return bytes;
    };
    auto program = VerifyProgramLanes(read("uj12.l31"), read("ug12.l31"));
    const char* graphics[] = {"ug14-vid", "uj14-vid", "ug19-vid", "uj19-vid",
                             "ug16-vid", "uj16-vid", "ug20-vid", "uj20-vid",
                             "ug17-vid", "uj17-vid", "ug22-vid", "uj22-vid"};
    program.graphics.resize(0xc00000);
    for (unsigned lane = 0; lane < 12; ++lane) {
        const auto bytes = read(graphics[lane], 0x100000);
        for (size_t i = 0; i < bytes.size(); ++i)
            program.graphics[(lane / 4) * 0x400000 + (lane % 4) + i * 4] = bytes[i];
    }
    if (Sha256(program.graphics) != kGraphicsSha256)
        throw std::runtime_error("MK2 interleaved graphics ROM SHA-256 mismatch");
    return program;
}
}
