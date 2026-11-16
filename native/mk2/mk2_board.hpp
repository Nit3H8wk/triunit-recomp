#pragma once
#include "mk2_protection.hpp"
#include <array>
#include <cstdint>
#include <functional>
#include <limits>
#include <stdexcept>
#include <vector>

namespace mk2 {
// Finite cold boot latches, through the original palette queue drain.
struct BoardBootControls {
    friend class DcsBootMachine;
private:
    uint64_t main_horizon_ = 3658091;
    bool host_inputs_ = false;
    bool live_host_domain_=false;
    uint64_t live_discarded_input_events_=0,live_last_input_tick_=0;
    void RecordLiveInput(std::array<uint64_t,4> event) {
        if(event[0]<live_last_input_tick_ || input_events.size()>=128 ||
           live_discarded_input_events_>std::numeric_limits<uint64_t>::max()-input_events.size()-1)
            throw std::runtime_error("MK2 live input observation window or absolute counter exceeded");
        live_last_input_tick_=event[0];input_events.push_back(event);
    }
    std::function<uint32_t(uint64_t)> host_input_provider_;
    std::array<uint16_t,3> requested_ports_{0xffff,0xffff,0xffff};
    uint64_t PackedInputs() const {
        return uint64_t(input0) | (uint64_t(input1)<<16) | (uint64_t(input2)<<32);
    }
public:
    bool CoinPairAdmitted() const { return live_host_domain_ || main_horizon_ == 5077311 || main_horizon_ == 6087360 || main_horizon_ == 7005800 || main_horizon_ == 22081952 || main_horizon_ == 23108559 || main_horizon_ == 24004881 || main_horizon_ == 30060282 || main_horizon_ == 100091930 || main_horizon_ == 101005964 || main_horizon_ == 104090574 || main_horizon_ == 110030700 || main_horizon_ == 118028828 || main_horizon_ == 126026668 || main_horizon_ == 134024907 || main_horizon_ == 150023965; }
    std::array<uint16_t, 28> io{}; // Through DPYTAP; excludes dynamic counters/display address.
    uint16_t dma_command = 0, video_control = 0;
    uint16_t dip_switches = 0xfc7d; // Fixed driver defaults, including Powerup Test off.
    uint16_t input0 = 0xffff, input1 = 0xffff, input2 = 0xffff; // Active-low, unpressed cold inputs.
    uint16_t vcount = 274, display_address = 0; // Initial cold screen callback.
    unsigned scanline_events = 0, active_updates = 0;
    bool requested_p1_high_punch = false;
    bool requested_coin1 = false;
    bool requested_start1 = false;
    Protection protection;
    // Tags 0..5: scripted press/port; 6/7: host request/frame, three ports packed into 48 bits.
    std::vector<std::array<uint64_t, 4>> input_events;

    std::array<uint64_t,4> HostLatchState() const { return {requested_ports_[0],requested_ports_[1],requested_ports_[2],uint64_t(host_inputs_)}; }
    uint64_t LiveInputEventCount() const { return live_discarded_input_events_+input_events.size(); }
    uint64_t LiveLastInputTick() const { return live_last_input_tick_; }
    void DiscardLiveInputEvents() {
        if(!live_host_domain_ || !HostInputProviderActive())throw std::runtime_error("MK2 live input drain requires its own domain");
        live_discarded_input_events_+=input_events.size();
        std::vector<std::array<uint64_t,4>>().swap(input_events);
    }
    bool HostInputProviderActive() const { return bool(host_input_provider_); }
    void ReleaseHostInputProvider() { host_input_provider_={}; }
    void SetHostInputProvider(std::function<uint32_t(uint64_t)> provider, uint64_t tick) {
        if (!provider || host_inputs_ || input0!=0xffff || input1!=0xffff || input2!=0xffff ||
            requested_p1_high_punch || requested_coin1 || requested_start1 ||
            (!input_events.empty() && tick<input_events.back()[0]))
            throw std::runtime_error("MK2 host handoff requires released inputs and monotonic clock");
        host_input_provider_=std::move(provider);
        host_inputs_=true;
    }

    void SetHostInputs(uint32_t shared_in01, uint64_t tick) {
        if ((!host_inputs_ && !input_events.empty()) ||
            (!input_events.empty() && tick < input_events.back()[0]))
            throw std::runtime_error("MK2 host input clock or scripted mode differs");
        // Shared keyboard/XInput layout; bit28 is P1LP, not MK2 volume up.
        requested_ports_ = {uint16_t((shared_in01 & 0x7f7f) | 0x8080),
                            uint16_t(((shared_in01>>16) & 0x27) | 0xffd8),
                            uint16_t(((shared_in01>>28) & 3) | ((shared_in01>>21) & 0x30) | 0xffcc)};
        host_inputs_ = true;
        const uint64_t requested = uint64_t(requested_ports_[0]) |
            (uint64_t(requested_ports_[1])<<16) | (uint64_t(requested_ports_[2])<<32);
        if(live_host_domain_)RecordLiveInput({tick,requested,PackedInputs(),6});
        else input_events.push_back({tick,requested,PackedInputs(),6});
    }

    void SetP1HighPunch(bool pressed, uint64_t tick) {
        if (host_inputs_) throw std::runtime_error("MK2 scripted input during host control");
        if (!input_events.empty() && tick < input_events.back()[0])
            throw std::runtime_error("MK2 requested input clock moved backwards");
        requested_p1_high_punch = pressed;
        input_events.push_back({tick, uint64_t(pressed), input0, 0});
    }

    void SetCoin1(bool pressed, uint64_t tick) {
        if (host_inputs_) throw std::runtime_error("MK2 scripted input during host control");
        if (!input_events.empty() && tick < input_events.back()[0])
            throw std::runtime_error("MK2 requested input clock moved backwards");
        requested_coin1 = pressed;
        input_events.push_back({tick, uint64_t(pressed), input1, 2});
    }

    void SetStart1(bool pressed, uint64_t tick) {
        if (host_inputs_) throw std::runtime_error("MK2 scripted input during host control");
        if (!input_events.empty() && tick < input_events.back()[0])
            throw std::runtime_error("MK2 requested input clock moved backwards");
        requested_start1 = pressed;
        input_events.push_back({tick, uint64_t(pressed), input1, 4});
    }

    uint16_t ReadBootInput(uint32_t address) const {
        if (address == 0x01600000) return input0;
        if (address == 0x01600010) return input1;
        if (address == 0x01600020) return input2;
        if (address == 0x01600030) return dip_switches;
        if (address == 0x01600040) return 0xffff; // Unmapped high word, not a DSW alias.
        throw std::runtime_error("MK2 input read outside boot DIP scope");
    }
    uint16_t HorizontalCount(uint64_t main_cycles) const {
        // Finite cooperative batch; the original 8 MHz beam rounding is unchanged.
        if (main_cycles > main_horizon_ || io[3] != 252)
            throw std::runtime_error("MK2 horizontal count outside qualified 506-pixel cooperative batch horizon");
        // screen::hpos rounds to the nearest 8 MHz pixel; each main cycle is 1.28 pixels.
        const unsigned pixel = unsigned(((main_cycles * 64 + 25) / 50) % 506);
        const unsigned total = unsigned(io[3]) + 1;
        unsigned count = pixel * total / 506 + io[1];
        if (count > total) count -= total;
        return uint16_t(count);
    }
    void AdvanceScanlines(unsigned events) {
        AdvanceScanlines(events, [](const BoardBootControls&) {});
    }
    template<class Observe> void AdvanceScanlines(unsigned events, Observe&& observe) {
        const auto limit64=(main_horizon_*16 + 15 - 94875)/6325 + 1;
        if(live_host_domain_ && limit64>std::numeric_limits<unsigned>::max())throw std::overflow_error("MK2 live scanline counter overflow");
        const auto limit=unsigned(limit64);
        if (events < scanline_events || events > limit || (events != scanline_events && !(io[8] & 0x2000)))
            throw std::runtime_error("MK2 scanline outside qualified loaded drawing scope");
        while (scanline_events < events) {
            vcount = uint16_t(scanline_events++ % (unsigned(io[7]) + 1));
            if (vcount == 274) {
                if (host_inputs_) {
                    const auto previous = PackedInputs();
                    input0=requested_ports_[0];input1=requested_ports_[1];input2=requested_ports_[2];
                    const auto physical = PackedInputs();
                    if (physical != previous) {
                        const std::array<uint64_t,4> event{94875 + uint64_t(scanline_events - 1) * 6325,physical,physical,7};
                        if(live_host_domain_)RecordLiveInput(event);else input_events.push_back(event);
                    }
                } else {
                    const uint16_t next = uint16_t((input0 & ~uint16_t(0x10)) |
                                                 (requested_p1_high_punch ? 0 : 0x10));
                    if (next != input0) {
                        input0 = next;
                        input_events.push_back({94875 + uint64_t(scanline_events - 1) * 6325,
                                                uint64_t(requested_p1_high_punch), input0, 1});
                    }
                    const uint16_t coin = uint16_t((input1 & ~uint16_t(1)) | (requested_coin1 ? 0 : 1));
                    if (coin != input1) {
                        input1 = coin;
                        input_events.push_back({94875 + uint64_t(scanline_events - 1) * 6325,
                                                uint64_t(requested_coin1), input1, 3});
                    }
                    const uint16_t start = uint16_t((input1 & ~uint16_t(4)) | (requested_start1 ? 0 : 4));
                    if (start != input1) {
                        input1 = start;
                        input_events.push_back({94875 + uint64_t(scanline_events - 1) * 6325,
                                                uint64_t(requested_start1), input1, 5});
                    }
                }
                // Frame callbacks request fields after this frame's physical input latch.
                if (host_input_provider_)
                    SetHostInputs(host_input_provider_(94875+uint64_t(scanline_events-1)*6325),
                                  94875+uint64_t(scanline_events-1)*6325);
            }
            if ((io[8] & 0x8000) && vcount == io[10]) io[18] |= 0x0400;
            if (vcount == io[6]) display_address = io[9];
            observe(*this);
            if (vcount >= io[5] && vcount < io[6]) {
                display_address = (display_address & 3)
                    ? uint16_t((display_address & 0xfffc) | ((display_address - 1) & 3))
                    : uint16_t(((display_address & 0xfffc) - (io[8] & 0x03fc)) | (io[9] & 3));
                if(live_host_domain_ && active_updates==std::numeric_limits<unsigned>::max())throw std::overflow_error("MK2 live active-update counter overflow");
                ++active_updates;
            }
        }
    }

    void WriteIo(unsigned offset, uint16_t data) {
        if (offset == 30) { display_address = data; return; }
        auto& word = io.at(offset);
        if ((offset == 16 && (data & 0x8100)) ||
            (offset == 17 && data != 0 && data != 4 && data != 6 && data != 0x0404 &&
                !(CoinPairAdmitted() && data == 0x0406)) ||
            (offset == 15 && (data & 0x0088)))
            throw std::runtime_error("MK2 host interrupt/halt outside boot control scope");
        if (offset == 18) {
            // External/host pending bits are read-only; WV/DI can only be cleared.
            word &= uint16_t(~(uint16_t(~data) & 0x0c00));
        } else if (offset == 15) {
            word = uint16_t(((word & 0xff8f) | (data & 0x0070) | (data & 0x0080)) &
                            (data | uint16_t(~0x0008)));
        } else word = data; // Pinned io_register_w assigns data, not COMBINE_DATA.
    }
    void WriteDmaCommand(uint16_t data, uint16_t mask = 0xffff) {
        const uint16_t next = uint16_t((dma_command & uint16_t(~mask)) | (data & mask));
        if (next & 0x8000) throw std::runtime_error("MK2 DMA drawing outside boot control scope");
        dma_command = next;
        io[18] &= uint16_t(~0x0002); // Every command write clears INT1, even without starting DMA.
    }
    void WriteVideoControl(uint16_t data, uint16_t mask = 0xffff) {
        video_control = uint16_t((video_control & uint16_t(~mask)) | (data & mask));
    }
    unsigned VideoBank() const { return (video_control >> 5) & 1; }
    uint32_t GfxBank0() const { return (video_control & 0x80) ? 0x800000 : 0; } // MK2 large GFX ROM.
    unsigned RasterOperation() const { return (io[11] >> 10) & 31; }
    bool TransparentPixels() const { return (io[11] & 0x20) != 0; }
    unsigned PixelShift() const {
        switch (io[21]) {
        case 2: return 1;
        case 4: return 2;
        case 8: return 3;
        case 16: return 4;
        default: return 0;
        }
    }
    uint32_t SourcePitch() const { return uint32_t(1) << (~io[19] & 31); }
    uint32_t DestinationPitch() const { return uint32_t(1) << (~io[20] & 31); }
};
}
