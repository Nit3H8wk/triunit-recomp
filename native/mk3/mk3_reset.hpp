#pragma once
#include "mk3_program.hpp"
#include "mk3_pic.hpp"
#include <array>
#include <cstdint>
#include <map>
#include <vector>

namespace mk3 {
struct BusWrite {
    uint32_t pc, address_bit; // pc: source instruction (not the watchpoint's post-fetch PC).
    uint16_t value;
    uint64_t cycle;            // Reference-model cycles before the writing instruction.
};
struct ResetTrace {
    std::array<uint32_t, 16> a{};
    std::array<uint32_t, 15> b{}; // B15 shares SP with A15.
    uint32_t status = 0x10, pc = kResetPc;
    uint64_t cycles = 0, instructions = 0;
    std::vector<BusWrite> writes;
    std::map<uint32_t, uint16_t> ram;   // Main RAM words Ops preloads (none after PowerOn: the code writes Ops::ram).
    uint16_t video_control = 0;         // midwunit_control_w latch (01B00000).
    std::array<uint16_t, 8> io{};       // midwunit io_w m_iodata after identity shuffle (MK3 has no shuffle).
    std::vector<BusWrite> reads;        // Device reads (value = data returned).
    // running_machine::rand and the serial PIC simulation; device_reset (power-on) draws m_data first.
    MameRand rand;
    SerialPic pic;
    // dcs_audio_device REV_DCS1 m_latch_control: both latches empty. Proven for TMS cycles 0..545050 by the native
    // ADSP run (tools/mk3/test_adsp.py): the boot pages never write the output latch; the first change is the host
    // sound-port write at TMS 545051. Later DCS state needs the ADSP co-simulation.
    uint16_t dcs_control = 0x0c00;
};
}
