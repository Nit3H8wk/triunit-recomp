#include "mk2_executor.hpp"
#include "mk2_cmos_image.hpp"
#include "mk2_operator_boundaries.hpp"
#include "mk2_valid_cmos_startup.hpp"
#include "mk5_program.hpp"
#include <stdexcept>
#include <string>

namespace mk2 {
namespace {
// Original route facts (PC, main cycle). Cold boot: the qualified P1 High Punch press that leaves the factory
// message and its release when the firmware latches it, then the first cooperative draw yield.
constexpr uint32_t kTextEntryPc=0xffa5a190, kButtonPollPc=0xffa5aef0, kButtonReleasePc=0xffa5b130;
constexpr uint64_t kButtonPressCycle=506023, kButtonReleaseCycle=571254;
constexpr uint32_t kYieldPc=0xff80dd30, kCleanDelayPc=0xffa5b090, kStartupEntryPc=0xff811340, kServicePc=0xffa38c10;
constexpr uint64_t kFirstDrawCycle=1261260;
}

GeneratedBoot::GeneratedBoot(const Program& program, DcsBootMachine& machine, const std::vector<uint8_t>* cmos,
                             uint16_t dsw)
    : program_(program), machine_(machine),
      route_(!cmos ? BootRoute::factory : dsw==kTestSwitchDsw ? BootRoute::test_switch : BootRoute::valid_cmos) {
    if (program.bytes.size()!=0x100000 || program.sha256!=kProgramSha256 || Sha256(program.bytes)!=kProgramSha256)
        throw std::runtime_error("MK2 generated boot requires verified L3.1 program bytes");
    if (dsw==kTestSwitchDsw) {
        if (!machine.HasFullDcsRoms() || !cmos || cmos->size()!=16384 || Sha256(*cmos)!=kTestSwitchFactorySha256 ||
            Sha256(program.graphics)!=kGraphicsSha256)
            throw std::runtime_error("MK2 Test Switch requires the authenticated factory CMOS and complete L3.1 ROMs");
    } else if (!OperatorDswSupported(dsw)) {
        throw std::runtime_error("MK2 operator DIP changes are limited to blood and violence");
    }
    auto& s=state_.ready;
    s.board.dip_switches=dsw;
    if (cmos) s.cmos=DecodeCmosImage(*cmos);
    state_.main_ram.assign(262144,0); // 512 KiB main RAM, cold (pinned MAME zero fill).
    state_.observe_history=false;
    const size_t vector=(0xffffffe0u-0xff800000u)/8; // TMS34010 reset vector.
    if ((uint32_t(program.bytes[vector])|(uint32_t(program.bytes[vector+1])<<8)|(uint32_t(program.bytes[vector+2])<<16)|
         (uint32_t(program.bytes[vector+3])<<24))!=s.next_pc)
        throw std::runtime_error("MK2 generated boot requires the ROM reset vector");
    boundaries_.push_back({BootEvent::video_ready,kTextEntryPc,0});
    switch (route_) {
    case BootRoute::factory:
        boundaries_.push_back({BootEvent::press_p1_high_punch,kButtonPollPc,kButtonPressCycle});
        boundaries_.push_back({BootEvent::release_p1_high_punch,kButtonReleasePc,kButtonReleaseCycle});
        boundaries_.push_back({BootEvent::deliver,kYieldPc,kFirstDrawCycle});
        break;
    case BootRoute::valid_cmos:
        boundaries_.push_back({BootEvent::admit_delay,kCleanDelayPc,OperatorCycle(dsw,OperatorBoundary::Post)});
        boundaries_.push_back({BootEvent::admit_startup,kStartupEntryPc,OperatorCycle(dsw,OperatorBoundary::Reset)});
        // The setup and draw cycles depend on the startup profile, read from CMOS at the startup admission.
        boundaries_.push_back({BootEvent::admit_draw,kYieldPc,0});
        boundaries_.push_back({BootEvent::deliver,kYieldPc,0});
        break;
    case BootRoute::test_switch:
        boundaries_.push_back({BootEvent::admit_delay,kCleanDelayPc,kTestSwitchPostCycle});
        boundaries_.push_back({BootEvent::admit_startup,kStartupEntryPc,kTestSwitchResetCycle});
        boundaries_.push_back({BootEvent::deliver,kServicePc,0});
        break;
    }
}

void GeneratedBoot::Apply(const BootBoundary& boundary) {
    auto& s=state_.ready;
    switch (boundary.event) {
    case BootEvent::video_ready: if (video_ready_) video_ready_(state_.video); break;
    case BootEvent::press_p1_high_punch: s.board.SetP1HighPunch(true,s.cycles*16); break;
    case BootEvent::release_p1_high_punch: s.board.SetP1HighPunch(false,s.cycles*16); break;
    case BootEvent::admit_delay: machine_.AdmitValidCmosDelay(s.board); break;
    case BootEvent::admit_startup: {
        const auto profile=OperatorStartupProfile(s);
        machine_.AdmitValidCmosStartup(s.board,profile);
        if (route_==BootRoute::valid_cmos) {
            boundaries_.at(next_+1).cycle=OperatorCycle(s.board.dip_switches,OperatorBoundary::Setup,profile);
            boundaries_.at(next_+2).cycle=OperatorCycle(s.board.dip_switches,OperatorBoundary::Draw,profile);
        }
        break;
    }
    case BootEvent::admit_draw:
        if (OperatorCycle(s.board.dip_switches,OperatorBoundary::Setup,OperatorStartupProfile(s))!=boundary.cycle)
            throw std::runtime_error("MK2 startup profile changed before the first draw");
        machine_.AdmitValidCmosDraw(s.board);
        break;
    case BootEvent::deliver: break;
    }
}

void GeneratedBoot::Step(BootOps& o) {
    auto& s=o.s;
    const auto pc=s.next_pc;
    const auto cycle=s.cycles;
    try {
        if ((s.status&0x00200000) && (s.board.io[17]&s.board.io[18])) o.PendingInterrupt();
        if (!ExecuteGeneratedInstruction(o)) throw std::runtime_error("MK2 PC outside the generated closure");
    } catch (const std::exception& error) {
        throw std::runtime_error(std::string(error.what())+"; TMS PC "+std::to_string(pc)+"; cycle "+
            std::to_string(cycle)+"; DSP PC "+std::to_string(machine_.dsp.pc));
    }
}

void GeneratedBoot::RunTo(uint32_t pc, uint64_t cycle) {
    BootOps o(program_,machine_,state_);
    auto& s=o.s;
    while (true) {
        if (s.next_pc==pc && s.cycles==cycle) return;
        if (s.cycles>cycle) throw std::runtime_error("MK2 generated boot passed the requested boundary");
        while (next_<boundaries_.size()) {
            const auto& b=boundaries_[next_];
            if (b.cycle && s.cycles>b.cycle) throw std::runtime_error("MK2 generated boot missed a route boundary");
            if (s.next_pc!=b.pc || (b.cycle && s.cycles!=b.cycle)) break;
            if (b.event==BootEvent::deliver) throw std::runtime_error("MK2 generated boot requested past delivery");
            Apply(b); ++next_;
        }
        Step(o);
    }
}

void GeneratedBoot::RunToPc(uint32_t pc) {
    BootOps o(program_,machine_,state_);
    auto& s=o.s;
    while (s.next_pc!=pc) {
        while (next_<boundaries_.size()) {
            const auto& b=boundaries_[next_];
            if (b.cycle && s.cycles>b.cycle) throw std::runtime_error("MK2 generated boot missed a route boundary");
            if (s.next_pc!=b.pc || (b.cycle && s.cycles!=b.cycle)) break;
            if (b.event==BootEvent::deliver) throw std::runtime_error("MK2 generated boot requested past delivery");
            Apply(b); ++next_;
        }
        Step(o);
    }
}

BootContinuation& GeneratedBoot::RunToBoundary(BootEvent event) {
    BootOps o(program_,machine_,state_);
    auto& s=o.s;
    while (next_<boundaries_.size()) {
        const auto& b=boundaries_[next_];
        if (b.cycle && s.cycles>b.cycle) throw std::runtime_error("MK2 generated boot missed a route boundary");
        if (s.next_pc==b.pc && (!b.cycle || s.cycles==b.cycle)) {
            if (b.event==event) return state_;
            Apply(b); ++next_; continue;
        }
        Step(o);
    }
    throw std::runtime_error("MK2 generated boot route has no such remaining boundary");
}

BootContinuation& GeneratedBoot::Deliver() {
    if (Delivered()) return state_;
    RunToBoundary(BootEvent::deliver);
    ++next_;
    return state_;
}
}
