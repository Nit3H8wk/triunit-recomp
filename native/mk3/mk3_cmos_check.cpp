#include "mk3_cpu.hpp"
#include "mk5_program.hpp"

namespace mk3 {
std::vector<uint16_t> CmosWords(const std::vector<uint8_t>& cmos_image) {
    if (cmos_image.size() != 0xc000) throw std::runtime_error("MK3 CMOS image must be 49152 bytes");
    std::vector<uint16_t> words(0x6000);
    for (size_t i = 0; i < words.size(); ++i) words[i] = uint16_t(cmos_image[2 * i] | cmos_image[2 * i + 1] << 8); // MAME nvram: LE words.
    return words;
}
// One instruction at s.pc: the boot-text PIXBLT helper or the generated whole-image units (tools/mk3/generate.py);
// a PC outside the static candidate rejects in both profiles.
void StepGenerated(Ops& o) {
    auto& s = o.s;
    o.Begin();
    if (s.pc == 0xffae8690u) {  // PIXBLT B,XY (boot text). With interrupts disabled the scheduler timeslice (restarts with
                                // ST.P) changes neither state nor bus effects: run it to completion.
        // With ST.IE set (operator switch/DIP tests) a timeslice end matters: 34010gfx.hxx eats m_gfxcycles against
        // m_icount, keeps ST.P and m_pc at the PIXBLT, and execute_run's check_interrupt may take an interrupt there (ST
        // with P pushed; RETI resumes the PIXBLT). Budget = m_icount as in Ops::GfxEat. A DevicePath {id = this PC}:
        // Strict rejects it unless route-verified, Game notes it.
        int32_t budget = INT32_MAX;
        if (s.status & VideoTiming::kStatusIE) {
            if (o.profile == Profile::Strict && !Accepted(o.routes, Unverified::DevicePath, 0xffae8690u))
                o.Reject("PIXBLT B,XY with interrupts enabled is not translated", s.pc);
            if (o.first) o.first->Note(Unverified::DevicePath, 0xffae8690u, s.cycles);
            budget = int32_t(std::min<uint64_t>(o.slice_end > s.cycles ? o.slice_end - s.cycles : 1, INT32_MAX));
        }
        const auto step = PixbltBinaryXY(o, o.tms_io, s, o.pixblt, budget);
        o.Finish(step.completed ? 0xffae86a0u : 0xffae8690u, step.cycles);
        return;
    }
    if (!StepTranslated(o)) o.Reject("PC outside the authenticated fixed translation", s.pc);
}
// Machine reset of the verified rev 2.1 program: the TMS34010 at the reset vector (ST 0x10, registers clear) and
// the serial PIC device_reset of midwayic.cpp (generate_serial_data draws from running_machine::rand). Every instruction
// from here on is generated code (tools/mk3/generate.py).
ResetTrace PowerOn(const Program& program) {
    if (program.bytes.size() != 0x100000 || program.sha256 != kProgramSha256 || Sha256(program.bytes) != kProgramSha256)
        throw std::runtime_error("MK3 reset requires the verified rev 2.1 program");
    ResetTrace s;
    s.pic.Reset(s.rand);
    return s;
}
// Runs the generated code from the machine reset until `stop`, without the DCS co-simulation.
ResetTrace RunGenerated(const Program& program, const std::vector<uint8_t>& cmos_image, uint32_t stop) {
    auto s = PowerOn(program);
    Ops o(program, s, CmosWords(cmos_image));
    // Each measured block must be reached from the reset; the bound only guards against a broken path.
    for (unsigned guard = 0; s.pc != stop; ++guard) {
        if (guard > 1000000) o.Reject("generated slice exceeded the translated bound", s.pc);
        StepGenerated(o);
    }
    return s;
}
ResetTrace RunCmosCheck(const Program& program, const std::vector<uint8_t>& cmos) { return RunGenerated(program, cmos, 0xff814b40u); }
ResetTrace RunPicCheck(const Program& program, const std::vector<uint8_t>& cmos) { return RunGenerated(program, cmos, 0xffaeff00u); }
ResetTrace RunInitToText(const Program& program, const std::vector<uint8_t>& cmos) { return RunGenerated(program, cmos, 0xffae8690u); }
ResetTrace RunToSerial(const Program& program, const std::vector<uint8_t>& cmos) { return RunGenerated(program, cmos, 0xffb096a0u); }
ResetTrace RunToSoundWait(const Program& program, const std::vector<uint8_t>& cmos) { return RunGenerated(program, cmos, 0xffaa8990u); }
}
