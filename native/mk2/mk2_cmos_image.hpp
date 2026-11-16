#pragma once
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace mk2 {
inline std::vector<uint16_t> DecodeCmosImage(const std::vector<uint8_t>& image) {
    if (image.size() != 16384)
        throw std::runtime_error("MK2 CMOS image requires exactly 16384 bytes");
    std::vector<uint16_t> words(8192);
    for (unsigned n = 0; n < words.size(); ++n)
        words[n] = uint16_t(image[2*n] | (uint16_t(image[2*n+1]) << 8));
    return words;
}

inline std::vector<uint8_t> EncodeCmosImage(const std::vector<uint16_t>& words) {
    if (words.size() != 8192)
        throw std::runtime_error("MK2 CMOS state requires exactly 8192 words");
    std::vector<uint8_t> image(16384);
    for (unsigned n = 0; n < words.size(); ++n) {
        image[2*n] = uint8_t(words[n]);
        image[2*n+1] = uint8_t(words[n] >> 8);
    }
    return image;
}
}
