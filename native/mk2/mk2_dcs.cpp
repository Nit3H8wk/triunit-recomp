#include "mk2_dcs.hpp"
#include "mk5_program.hpp"
#include <fstream>
#include <stdexcept>

namespace mk2 {
void DcsLink::HostWrite(uint32_t address, uint16_t value, uint16_t mask) {
    if (address == 0x01d01020) return;
    if (address != 0x01d01030) throw std::runtime_error("DCS host write outside data port");
    if (!(mask & 0xff) || !(mask & 0xff00)) return;
    reset_ = !(value & 0x100);
    if (reset_) pending_.push_back({Kind::Reset, 0});
    pending_.push_back({Kind::Input, uint16_t(value & 0xff)});
}

void DcsLink::Synchronize() {
    SynchronizeEvents(Boundary::Host);
}

bool DcsLink::SynchronizeEvents(Boundary boundary) {
    bool irq2_clear_delivered = false;
    while (!pending_.empty()) {
        const auto event = pending_.front();
        if (boundary != Boundary::Host && (event.kind == Kind::Reset || event.kind == Kind::Input)) break;
        if (boundary == Boundary::IsolatedDsp && event.kind == Kind::Output) break;
        pending_.pop_front();
        switch (event.kind) {
        case Kind::Reset: control_ |= 0xc00; irq2_ = false; break;
        case Kind::Input: input_ = event.value; control_ &= ~uint16_t(0x800); irq2_ = true; break;
        // The source has one pre-output latch, not a FIFO of output values.
        case Kind::Output: output_ = pending_output_; control_ &= ~uint16_t(0x400); break;
        case Kind::ClearIrq2: irq2_ = false; irq2_clear_delivered = true; break;
        }
    }
    return irq2_clear_delivered;
}

uint16_t DcsLink::DspReadInput(bool side_effects) {
    if (side_effects) {
        control_ |= 0x800;
        // MAME's input auto-ack empties the latch before the synchronized line event.
        pending_.push_back({Kind::ClearIrq2, 0});
    }
    return input_;
}

void DcsLink::DspWriteOutput(uint16_t value) {
    pending_output_ = value;
    pending_.push_back({Kind::Output, 0});
}

DcsLink::HostRead DcsLink::HostReadOutput(bool side_effects) {
    const bool empty = (control_ & 0x400) != 0;
    if (side_effects) control_ |= 0x400;
    return {uint8_t(output_), side_effects && empty ? 4444u : 0u};
}

std::vector<uint32_t> DecodeDcsBoot(const std::vector<uint8_t>& page) {
    if (page.size() != 0x1000) throw std::runtime_error("DCS boot requires one 4096-byte page");
    const size_t count = (size_t(page[3]) + 1) * 8;
    if (count > 0x400) throw std::runtime_error("DCS boot exceeds internal program RAM");
    std::vector<uint32_t> words(count);
    for (size_t i = 0; i < count; ++i)
        words[i] = (uint32_t(page[4*i]) << 16) | (uint32_t(page[4*i+1]) << 8) | page[4*i+2];
    return words;
}

std::vector<uint8_t> LoadDcsDataRoms(const std::filesystem::path& directory) {
    std::vector<uint8_t> bytes(6 * 0x80000);
    for (unsigned socket = 0; socket < 6; ++socket) {
        const auto path = directory / ("su" + std::to_string(socket + 2) + ".l1");
        std::error_code error;
        if (std::filesystem::file_size(path, error) != 0x80000 || error)
            throw std::runtime_error("MK2 DCS data ROM missing or wrong size");
        std::ifstream input(path, std::ios::binary);
        if (!input.read(reinterpret_cast<char*>(bytes.data() + socket * 0x80000), 0x80000) ||
            input.peek() != std::char_traits<char>::eof())
            throw std::runtime_error("MK2 DCS data ROM read failed or changed");
    }
    if (Sha256(bytes) != kDcsDataSha256)
        throw std::runtime_error("MK2 DCS six-socket data ROM SHA-256 mismatch");
    return bytes;
}

std::vector<uint8_t> LoadDcsRom(const std::filesystem::path& u2) {
    std::error_code error;
    if (std::filesystem::file_size(u2, error) != 0x80000 || error)
        throw std::runtime_error("MK2 DCS U2 ROM missing or wrong size");
    std::ifstream input(u2, std::ios::binary);
    std::vector<uint8_t> bytes(0x80000);
    if (!input.read(reinterpret_cast<char*>(bytes.data()), bytes.size()) ||
        input.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("MK2 DCS U2 ROM read failed or changed");
    if (Sha256(bytes) != "82bdcbbd9413071f20a52cf7fd0fcf094fa474a08938b4f8c1d617d1490a137c")
        throw std::runtime_error("MK2 DCS U2 ROM SHA-256 mismatch");
    return bytes;
}

std::vector<uint32_t> LoadDcsBoot(const std::filesystem::path& u2) {
    const auto bytes = LoadDcsRom(u2);
    return DecodeDcsBoot({bytes.begin(), bytes.begin() + 0x1000});
}
}
