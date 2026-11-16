#include "mk3_pic.hpp"

namespace mk3 {
std::array<uint8_t, 16> SerialPicData(MameRand& rand, int upper, unsigned serial_digit, int year) {
    std::array<uint8_t, 16> d{};
    const uint32_t serial = 123450u + uint32_t(upper) * 1000000u + (serial_digit & 0x0f);
    uint8_t digit[9];
    for (uint32_t i = 0, scale = 100000000; i < 9; ++i, scale /= 10) digit[i] = uint8_t(serial / scale % 10);
    const auto bytes = [&](unsigned first, unsigned count, uint32_t value) {
        for (unsigned i = 0; i < count; ++i) d[first + i] = uint8_t(value >> (8 * i));
    };
    d[12] = uint8_t(rand());
    d[13] = uint8_t(rand());
    const uint32_t date = 0x174u * uint32_t(year - 1980) + 0x1fu * (12 - 1) + 11; // month 12, day 11
    d[10] = uint8_t(date >> 8); d[11] = uint8_t(date);
    bytes(7, 3, (digit[4] + digit[7] * 10u + digit[1] * 100u + 5u * d[13]) * 0x1bcdu + 0x1f3f0u);
    bytes(3, 4, (digit[6] + digit[8] * 10u + digit[0] * 100u + digit[2] * 10000u + 2u * d[13] + d[12]) * 0x107fu + 0x71e259u);
    bytes(0, 3, (digit[5] * 10u + digit[3] * 100u + d[12]) * 0x245u + 0x3d74u);
    return d;
}
} // namespace mk3
