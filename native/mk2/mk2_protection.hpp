#pragma once
#include <cstdint>

namespace mk2 {
// midtunit_m.cpp: MK2's latch, shifted read and constant are distinct devices from MK1.
class Protection {
    uint16_t data_ = 0;
public:
    void Write(uint16_t data, uint16_t mask) {
        data_ = uint16_t((data_ & uint16_t(~mask)) | (data & mask));
    }
    uint16_t Read() const { return data_; }
    uint16_t Shifted() const { return data_ >> 1; }
    uint16_t Constant() const { return 2; }
};
}
