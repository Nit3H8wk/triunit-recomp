#pragma once
#include "mk2_program.hpp"
#include "mk2_board.hpp"
#include "mk2_video.hpp"
#include <array>
#include <map>

namespace mk2 {
struct ResetAccess {
    uint32_t pc, address_bit;
    uint16_t value;
    uint64_t cycle;
};
struct ResetTrace {
    std::array<uint32_t, 16> a{};
    std::array<uint32_t, 15> b{}; // B15 shares SP with A15.
    uint32_t status = 0x10, next_pc = kResetPc;
    uint64_t cycles = 0, instructions = 0;
    uint32_t delay_iterations = 0;
    std::vector<ResetAccess> writes, cmos_reads, cmos_writes;
    BoardBootControls board;
    std::vector<ResetAccess> board_writes; // Aligned full-word accesses, 16 bits each.
    bool cmos_write_enabled = false;
    // Pinned MAME accepts masked writes even without a preceding enable.
    void EnableCmos() { cmos_write_enabled = true; }
    void WriteCmos(unsigned offset, uint16_t data, uint16_t mask) {
        auto& word = cmos.at(offset);
        word = uint16_t((word & uint16_t(~mask)) | (data & mask));
        cmos_write_enabled = false;
    }
    // Heap snapshots avoid exhausting the instrumented test stack; cold DEFAULT_ALL_0, no NVRAM.
    std::vector<uint16_t> cmos = std::vector<uint16_t>(8192);
    std::map<uint32_t, uint32_t> ram;
};
struct BootAccess {
    uint32_t pc, address_bit, value;
    uint64_t cycle;
    unsigned size_bits;
};
}
