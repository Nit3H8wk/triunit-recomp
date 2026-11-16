#pragma once
#include <array>
#include <cstdint>

namespace mk3 {
// running_machine::rand (src/emu/machine.cpp, mame0280): fixed constructor seed, never reseeded except by a
// state load (m_rand_seed is a saved item). In MK3 2.1 the serial PIC's device_reset is the only consumer
// observed, so power-on draws 1-2 and each later soft reset draws the next two.
struct MameRand {
    uint32_t seed = 0x9d14abd7;
    uint32_t operator()() { seed = 1664525u * seed + 1013904223u; return seed >> 16 | seed << 16; }
};

// midwunit.cpp wunit_picsim: set_upper(528); GAME year "1994"; SERIAL_DIGIT DIP default 6.
constexpr int kMk3PicUpper = 528, kMk3PicYear = 1994;
constexpr unsigned kMk3SerialDigit = 6;

// generate_serial_data of the serial PIC device (midwayic.cpp): consumes two draws (m_data[12], m_data[13]).
std::array<uint8_t, 16> SerialPicData(MameRand& rand, int upper = kMk3PicUpper, unsigned serial_digit = kMk3SerialDigit,
                                      int year = kMk3PicYear);

// The serial PIC device of midwayic.cpp (simulation): status_r, read, write and reset_w; Reset() is device_reset.
struct SerialPic {
    std::array<uint8_t, 16> data{};
    uint8_t buff = 0, idx = 0, status = 0; // m_idx is uint8_t in midwayic.h: the % 16 index survives its wrap.

    void Reset(MameRand& rand) { data = SerialPicData(rand); }
    void ResetLine(bool state) { if (state) idx = status = buff = 0; }
    uint8_t Status() const { return status; }
    uint8_t Read() { status = 1; return buff; }       // side_effects_disabled() reads belong to debuggers only.
    void Write(uint8_t value) {
        status = (value >> 4) & 1;                     // status follows the clock bit
        if (!status) buff = (value & 0x0f) ? value & 0x0f : data[idx++ % data.size()]; // self-test nibble or next byte
    }
};
} // namespace mk3
