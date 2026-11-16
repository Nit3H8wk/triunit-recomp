#pragma once
#include "mk2_reset.hpp"
#include <algorithm>

namespace mk2 {
struct PixbltAccess {
    uint32_t pc, address_bit;
    uint16_t value;
    uint64_t cycle;
    char kind;
};
struct PixbltStep {
    unsigned cycles = 0;
    bool completed = false;
    std::vector<PixbltAccess> accesses;
};
class BitmapTextBlit {
    unsigned remaining_ = 0;
    std::array<uint32_t, 10> start_b_{};
public:
    PixbltStep Step(const Program& program, BootVideo& video, ResetTrace& state, unsigned budget) {
        constexpr uint32_t pc = 0xffa592b0, progress = 1u << 25;
        const auto& board = state.board;
        if (!budget || state.next_pc != pc || program.bytes.size() != 0x100000 ||
            program.bytes[(pc - 0xff800000) / 8] != 0xa0 ||
            program.bytes[(pc - 0xff800000) / 8 + 1] != 0x0f ||
            board.io[21] != 8 || board.io[11] != 0x2c || board.io[22] ||
            (board.io[8] & 0x0800) || board.io[20] != 19 || board.VideoBank() != 1 ||
            state.b[3] != 4096 || state.b[4] || bool(state.status & progress) != bool(remaining_))
            throw std::runtime_error("MK2 PIXBLT outside qualified bitmap text mode");
        if (remaining_ && !std::equal(start_b_.begin(), start_b_.end(), state.b.begin()))
            throw std::runtime_error("MK2 PIXBLT registers changed during restart");
        PixbltStep result;
        if (!remaining_) {
            const int width = int16_t(state.b[7]), height = int16_t(state.b[7] >> 16);
            const int x = int16_t(state.b[2]), y = int16_t(state.b[2] >> 16);
            if (width < 1 || (width > 8 && width != 10) || height != 8 ||
                state.b[1] != unsigned((width + 7) & ~7))
                throw std::runtime_error("MK2 PIXBLT outside qualified eight-row font geometry");
            const int64_t destination = int64_t(y) * 4096 + int64_t(x) * 8;
            // Include terminal source prefetch and both bytes of partial destination words.
            for (int row = 0; row < height; ++row) {
                const uint64_t source = uint64_t(state.b[0]) + uint64_t(row) * state.b[1];
                const uint64_t last_source = (source & ~uint64_t(15)) + ((source % 16 + width) / 16) * 16;
                const int64_t dest = destination + int64_t(row) * state.b[3];
                if (source < 0xff800000 || last_source > 0xfffffff0 ||
                    dest < 0 || dest + width * 8 > 0x00400000)
                    throw std::runtime_error("MK2 PIXBLT source or destination outside mapped memory");
            }
            int left = (destination & 15) / 8, right = ((destination + width * 8) & 15) / 8;
            int full = width - left - right;
            if (full < 0) { left = width; right = full = 0; }
            else full /= 2;
            const unsigned words = unsigned(full + (left != 0) + (right != 0));
            result.accesses.reserve(unsigned(height) * (words * 2 + 2));
            remaining_ = 8 + (words * 4 + (words / 2) * 2) * unsigned(height);
            std::copy_n(state.b.begin(), start_b_.size(), start_b_.begin());
            state.status |= progress;
            auto read_source = [&](uint32_t address) {
                const size_t offset = (address - 0xff800000) / 8;
                const uint16_t value = uint16_t(program.bytes[offset] | (uint16_t(program.bytes[offset + 1]) << 8));
                result.accesses.push_back({pc, address, value, state.cycles, 'r'});
                return value;
            };
            for (int row = 0; row < height; ++row) {
                const uint32_t source = state.b[0] + unsigned(row) * state.b[1];
                uint32_t source_word = source & ~uint32_t(15);
                uint16_t source_bits = read_source(source_word);
                uint16_t source_mask = uint16_t(1u << (source & 15));
                const uint32_t dest = uint32_t(destination + int64_t(row) * state.b[3]);
                uint32_t dest_word = dest & ~uint32_t(15);
                auto write_word = [&](unsigned pixels, unsigned shift) {
                    uint16_t data = video.ReadVram(dest_word, board);
                    result.accesses.push_back({pc, dest_word, data, state.cycles, 'r'});
                    for (unsigned pixel = 0; pixel < pixels; ++pixel) {
                        const uint16_t mask = uint16_t(0xffu << shift);
                        const uint16_t color = uint16_t((source_bits & source_mask ? state.b[9] : state.b[8]) & mask);
                        if (color) data = uint16_t((data & uint16_t(~mask)) | color);
                        source_mask = uint16_t(source_mask << 1);
                        if (!source_mask) {
                            source_word += 16; source_bits = read_source(source_word); source_mask = 1;
                        }
                        shift += 8;
                    }
                    video.WriteVram(dest_word, data, board);
                    result.accesses.push_back({pc, dest_word, data, state.cycles, 'w'});
                    dest_word += 16;
                };
                if (left) write_word(unsigned(left), unsigned(dest & 15));
                for (int word = 0; word < full; ++word) write_word(2, 0);
                if (right) write_word(unsigned(right), 0);
            }
        }
        result.cycles = std::min(remaining_, budget);
        remaining_ -= result.cycles;
        result.completed = remaining_ == 0;
        if (result.completed) {
            state.status &= ~progress;
            state.b[0] += 8 * state.b[1];
            state.b[2] = (state.b[2] & 0xffff) | (uint32_t(uint16_t((state.b[2] >> 16) + 8)) << 16);
            state.next_pc = pc + 16;
        }
        return result;
    }
};
}
