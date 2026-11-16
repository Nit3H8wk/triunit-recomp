#include "../mk2/mk2_program.hpp"
#include "../mk2/mk2_reset.hpp"
#include "../mk2/mk2_task_batch.hpp"
#include "../mk2/mk2_executor.hpp"
#include "../mk2/mk2_protection.hpp"
#include "../mk2/mk2_dcs.hpp"
#include "../mk2/mk2_adsp.hpp"
#include "mk5_program.hpp"
#include <algorithm>
#include <memory>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
int ParsePreStartWindowArg(const std::string& argument) {
    const std::string prefix="--prestart-window=";
    if(argument.rfind("--prestart-window",0)!=0) return -1;
    if(argument.rfind(prefix,0)!=0) throw std::runtime_error("Malformed pre-Start window argument");
    const auto value=argument.substr(prefix.size());
    if(value.empty() || value.size()>2 || !std::all_of(value.begin(),value.end(),[](char c){return c>='0' && c<='9';}))
        throw std::runtime_error("Malformed pre-Start window number");
    const auto index=unsigned(std::stoul(value));
    if(index>=mk2::kPreStartWindowCount) throw std::runtime_error("Pre-Start window out of scope");
    return int(index);
}

int ParseSelectionWindowArg(const std::string& argument) {
    const std::string prefix="--selection-window=";
    if(argument.rfind("--selection-window",0)!=0) return -1;
    if(argument.rfind(prefix,0)!=0) throw std::runtime_error("Malformed selection window argument");
    const auto value=argument.substr(prefix.size());
    if(value.empty() || value.size()>2 || !std::all_of(value.begin(),value.end(),[](char c){return c>='0' && c<='9';}))
        throw std::runtime_error("Malformed selection window number");
    const auto index=unsigned(std::stoul(value));
    if(index>=mk2::kSelectionWindowCount) throw std::runtime_error("Selection window out of scope");
    return int(index);
}

int ParseFirstFightWindowArg(const std::string& argument) {
    const std::string prefix="--first-fight-window=";
    if(argument.rfind("--first-fight-window",0)!=0) return -1;
    if(argument.rfind(prefix,0)!=0) throw std::runtime_error("Malformed first-fight window argument");
    const auto value=argument.substr(prefix.size());
    if(value.empty() || value.size()>2 || !std::all_of(value.begin(),value.end(),[](char c){return c>='0' && c<='9';}))
        throw std::runtime_error("Malformed first-fight window number");
    const auto index=unsigned(std::stoul(value));
    if(index>=mk2::kFirstFightWindowCount) throw std::runtime_error("First-fight window out of scope");
    return int(index);
}

template<class F> void rejects_at(unsigned line,F action, const char* expected_message = nullptr) {
    bool rejected = false;
    try { action(); } catch (const std::runtime_error& error) {
        if (expected_message && std::string(error.what()) != expected_message)
            throw std::runtime_error(std::string("unexpected rejection reason: expected ") +
                                     expected_message + "; observed " + error.what());
        rejected = true;
    }
    if(!rejected)throw std::runtime_error("expected rejection absent at test line "+std::to_string(line));
}
#define rejects(...) rejects_at(__LINE__,__VA_ARGS__)
}

int main(int argc, char** argv) {
    try {
        const int prestart_window=ParsePreStartWindowArg(argc==3 ? argv[2] : "");
        const int selection_window=ParseSelectionWindowArg(argc==3 ? argv[2] : "");
        const bool first_fight_high_punch=argc==3 && std::string(argv[2])=="--first-fight-high-punch";
        const int first_fight_window=first_fight_high_punch ? 86 : ParseFirstFightWindowArg(argc==3 ? argv[2] : "");
        const bool start_input=argc==3 && std::string(argv[2])=="--start-input";
        const bool start_release=argc==3 && std::string(argv[2])=="--start-release";
        require(ParsePreStartWindowArg("--prestart-window=0")==0 && ParsePreStartWindowArg("--prestart-window=15")==15 &&
                ParsePreStartWindowArg("--next-wait")==-1,"pre-Start argument boundaries");
        for(const auto* value:{"--prestart-window","--prestart-window=","--prestart-window=-1","--prestart-window=16","--prestart-window=1x"})
            rejects([&]{ParsePreStartWindowArg(value);});

        require(ParseSelectionWindowArg("--selection-window=0")==0 && ParseSelectionWindowArg("--selection-window=5")==5 &&
                ParseSelectionWindowArg("--next-wait")==-1,"selection argument boundaries");
        for(const auto* value:{"--selection-window","--selection-window=","--selection-window=-1","--selection-window=6","--selection-window=1x"})
            rejects([&]{ParseSelectionWindowArg(value);});

        require(ParseFirstFightWindowArg("--first-fight-window=0")==0 && ParseFirstFightWindowArg("--first-fight-window=69")==69 &&
                unsigned(ParseFirstFightWindowArg("--first-fight-window="+std::to_string(mk2::kFirstFightWindowCount-1)))==mk2::kFirstFightWindowCount-1 &&
                ParseFirstFightWindowArg("--next-wait")==-1,"first-fight argument boundaries");
        for(const auto* value:{"--first-fight-window","--first-fight-window=","--first-fight-window=-1","--first-fight-window=1x"})
            rejects([&]{ParseFirstFightWindowArg(value);});
        rejects([&]{ParseFirstFightWindowArg("--first-fight-window="+std::to_string(mk2::kFirstFightWindowCount));});

        {
            // The pinned MK2 map leaves 1D01070h unmapped: every write keeps its bus lane without a DCS effect.
            mk2::Program helper_program; helper_program.bytes.resize(0x100000);
            const auto helper_machine_owner = std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
            auto& helper_machine = *helper_machine_owner;
            mk2::BootContinuation helper_result; helper_result.main_ram.resize(65536);
            auto& state = helper_result.ready;
            mk2::BootOps helper(helper_program, helper_machine, helper_result);
            for (const uint64_t cycle : {1273431u,1273432u,1843965u,2415197u,2986433u}) {
                state.next_pc = 0xff811ee0; state.cycles = cycle;
                const auto bus_before = helper_result.bus.size();
                helper.Write16(0x01d01070, uint16_t(cycle));
                require(helper_result.bus.size() == bus_before + 1 &&
                        helper_result.bus.back().address_bit == 0x01d01070 &&
                        helper_result.bus.back().value == uint16_t(cycle) && helper_result.bus.back().cycle == cycle &&
                        helper_machine.link.Control() == 0xc00,
                        "unmapped write remains observable without becoming a sound command");
            }
            rejects([&] { helper.Write16(0x01d01060, 0); });
        }
        mk2::BoardBootControls inputs;
        require(inputs.ReadBootInput(0x01600030) == 0xfc7d && inputs.ReadBootInput(0x01600040) == 0xffff,
                "MK2 default DSW and adjacent unmapped word are distinct");
        inputs.dip_switches ^= 0x200;
        require(inputs.ReadBootInput(0x01600030) == 0xfe7d && inputs.ReadBootInput(0x01600040) == 0xffff,
                "DIP selection cannot change the unmapped high word");
        require(inputs.ReadBootInput(0x01600020) == 0xffff,
                "unpressed IN2 occupies its own word before DSW");
        inputs.io[8] = 0xf010; inputs.io[5] = 20; inputs.io[6] = 274; inputs.io[7] = 288;
        inputs.io[9] = 0xfffc; inputs.io[10] = 274;
        inputs.AdvanceScanlines(240);
        require(inputs.vcount == 239 && inputs.display_address == 0xf240 && inputs.active_updates == 220 &&
                inputs.io[18] == 0, "cold scanlines update display address without reaching display IRQ");
        rejects([&] { inputs.AdvanceScanlines(9240); });
        rejects([&] { inputs.AdvanceScanlines(239); });
        mk2::BoardBootControls frame_inputs;
        frame_inputs.io[8] = 0xf010; frame_inputs.io[7] = 288;
        frame_inputs.input0 &= uint16_t(~1);
        frame_inputs.AdvanceScanlines(1266);
        frame_inputs.SetP1HighPunch(true, 8096368);
        frame_inputs.AdvanceScanlines(1430);
        require(frame_inputs.input0 == 0xfffe && frame_inputs.input_events.size() == 1,
                "legal button setter stays pending until the original vblank input frame");
        frame_inputs.AdvanceScanlines(1431);
        require(frame_inputs.input0 == 0xffee && frame_inputs.input_events.back() ==
                    std::array<uint64_t,4>{9139625,1,0xffee,1},
                "input frame latches active-low P1 high punch without changing other bits");
        frame_inputs.SetP1HighPunch(false, 9140064);
        frame_inputs.AdvanceScanlines(1719);
        require(frame_inputs.input0 == 0xffee && frame_inputs.input_events.size() == 3,
                "release stays pending through the preceding physical scanline");
        frame_inputs.AdvanceScanlines(1720);
        frame_inputs.AdvanceScanlines(1720);
        require(frame_inputs.input0 == 0xfffe && frame_inputs.input_events.size() == 4 &&
                frame_inputs.input_events.back() == std::array<uint64_t,4>{10967550,0,0xfffe,1},
                "next input frame releases only the requested button without duplicate events");
        rejects([&] { frame_inputs.SetP1HighPunch(true, 9140064); });
        require(!frame_inputs.requested_p1_high_punch && frame_inputs.input_events.size() == 4 &&
                frame_inputs.input0 == 0xfffe, "past button request rejects before physical or pending input mutation");
        mk2::BoardBootControls controls;
        controls.io[18] = 0x0e06;
        controls.WriteIo(18, 0x0400);
        require(controls.io[18] == 0x0606, "INTPEND preserves external/host bits and selectively clears WV/DI");
        controls.WriteDmaCommand(0);
        require(controls.io[18] == 0x0604 && controls.dma_command == 0,
                "non-starting DMA clears only INT1 pending");
        controls.WriteDmaCommand(0x1200, 0xff00);
        controls.WriteDmaCommand(0x0034, 0x00ff);
        require(controls.dma_command == 0x1234, "DMA command masked lanes");
        rejects([&] { controls.WriteDmaCommand(0x8000); });
        require(controls.dma_command == 0x1234, "untranslated DMA rejected before mutation");
        for (unsigned reg : {15u, 16u, 17u}) {
            rejects([&] { controls.WriteIo(reg, reg == 15 ? 0x88 : (reg == 16 ? 0x8100 : 1)); });
            require(controls.io[reg] == 0, "untranslated host IRQ/halt rejected before mutation");
        }
        controls.WriteIo(17, 0x0404);
        controls.WriteIo(17, 0x0004);
        require(controls.io[17] == 4, "qualified video IRQ mask clears DI without enabling DMA INT1");
        controls.WriteIo(17, 6);
        require(controls.io[17] == 6, "loaded drawing enables DMA INT1 alongside INT2 while DI remains masked");
        controls.WriteIo(17, 4);
        for (uint16_t invalid : {uint16_t(2), uint16_t(0x0406), uint16_t(0xffff)}) {
            rejects([&] { controls.WriteIo(17, invalid); });
            require(controls.io[17] == 4, "unqualified IRQ masks reject before latch mutation");
        }
        controls.WriteIo(30, 0xeffc);
        require(controls.display_address == 0xeffc, "DI handler writes the original display address latch");
        controls.io[15] = 0xff8f;
        controls.WriteIo(15, 0x70);
        require(controls.io[15] == 0xfff7, "TMS host low-control writable and preserved bits");
        controls.WriteVideoControl(0x7c);
        require(controls.VideoBank() == 1 && controls.GfxBank0() == 0, "MK2 video and large-GFX bank selection");
        controls.WriteVideoControl(0x80, 0x00ff);
        controls.WriteVideoControl(0xab00, 0xff00);
        require(controls.video_control == 0xab80 && controls.VideoBank() == 0 && controls.GfxBank0() == 0x800000,
                "video masked lanes preserve the other byte");
        controls.WriteIo(11, 0x2c); controls.WriteIo(21, 8);
        require(controls.RasterOperation() == 0 && controls.TransparentPixels() && controls.PixelShift() == 3 &&
                controls.SourcePitch() == 0x80000000u && controls.DestinationPitch() == 0x80000000u,
                "boot raster configuration derives from original TMS latches");
        mk2::ResetTrace cmos_state;
        cmos_state.cmos[0] = 0xa55a;
        cmos_state.EnableCmos();
        require(cmos_state.cmos_write_enabled, "CMOS enable latch");
        cmos_state.WriteCmos(0, 0x1234, 0x00ff);
        require(cmos_state.cmos[0] == 0xa534 && !cmos_state.cmos_write_enabled,
                "CMOS low lane preserves high byte and clears enable");
        cmos_state.WriteCmos(0, 0x1200, 0xff00);
        require(cmos_state.cmos[0] == 0x1234, "pinned MAME accepts CMOS write without enable");
        cmos_state.WriteCmos(0, 0xffff, 0);
        require(cmos_state.cmos[0] == 0x1234, "CMOS zero mask preserves word");
        cmos_state.WriteCmos(8191, 0xabcd, 0xffff);
        require(cmos_state.cmos.back() == 0xabcd, "CMOS final mapped word");
        mk2::Protection protection;
        std::vector<uint32_t> synthetic_boot(376);
        synthetic_boot[0] = 0x18022f;
        synthetic_boot[0x22] = 0x400108;
        synthetic_boot[0x23] = 0x93fff8;
        {
            mk2::Program missing_vector;
            const auto irq_machine_owner = std::make_unique<mk2::DcsBootMachine>(synthetic_boot);
            auto& irq_machine = *irq_machine_owner;
            const auto irq_state_owner = std::make_unique<mk2::BootContinuation>();
            auto& irq_state = *irq_state_owner;
            irq_state.main_ram.resize(262144);
            auto& state = irq_state.ready;
            // Synthetic ST/SP at an Original DI (PC, cycle): outside the qualified set. The qualified contexts and
            // their changed-field rejections run on the executor's own states (mk2_executor_tests display-irq).
            state.next_pc = 0xff807e60; state.cycles = 1256726;
            state.status = 0x5a2000f5; state.a[15] = 0x01234560;
            state.board.io[17] = 0x0404; state.board.io[18] = 0x0400;
            mk2::BootOps ops(missing_vector, irq_machine, irq_state);
            rejects([&] { ops.DisplayInterrupt(); }, "MK2 asynchronous DI outside qualified polling contexts");
            require(irq_state.bus.empty() && irq_machine.LastMainCycles() == 0 && state.a[15] == 0x01234560 &&
                    state.status == 0x5a2000f5 && state.next_pc == 0xff807e60 && state.cycles == 1256726,
                    "palette IRQ context rejects before stack, bus or clock mutation");
        }
        {
            mk2::Program unused_program;
            unused_program.bytes.resize(0x100000);
            const size_t di_vector = (0xfffffea0u - 0xff800000u) / 8;
            const uint32_t handler = 0xff816370;
            for (unsigned byte = 0; byte < 4; ++byte)
                unused_program.bytes[di_vector + byte] = uint8_t(handler >> (8 * byte));
            const auto bank_machine_owner = std::make_unique<mk2::DcsBootMachine>(synthetic_boot);
            auto& bank_machine = *bank_machine_owner;
            const auto bank_state_owner = std::make_unique<mk2::BootContinuation>();
            auto& bank_state = *bank_state_owner;
            bank_state.main_ram.resize(262144);
            auto& state = bank_state.ready;
            state.a[15] = 0x01001000;
            state.board.io[8] = 0x2000;
            state.a[0] = 0xaabbccdd; state.a[2] = 0x11223344; state.a[10] = 0x55667788;
            state.b[0] = 0x12345678; state.b[2] = 0x89abcdef; state.b[10] = 0xfedcba98;
            state.status = 0x87654321;
            mk2::BootOps ops(unused_program, bank_machine, bank_state);
            ops.Mmtm(0xa020, 0x100, true);
            require(state.a[15] == 0x01000fa0 && state.cycles == 14 && state.status == 0x87654321 &&
                    bank_state.main_ram[0xfe] == 0x5678 && bank_state.main_ram[0xff] == 0x1234 &&
                    bank_state.main_ram[0xfc] == 0xcdef && bank_state.main_ram[0xfd] == 0x89ab &&
                    bank_state.main_ram[0xfa] == 0xba98 && bank_state.main_ram[0xfb] == 0xfedc,
                    "B-bank MMTM preserves word order, shared SP, instruction cycles and status");
            state.b[0] = state.b[2] = state.b[10] = 0;
            ops.Mmfm(0xa020, 0x200, true);
            require(state.a[15] == 0x01001000 && state.cycles == 29 && state.instructions == 2 &&
                    state.b[0] == 0x12345678 && state.b[2] == 0x89abcdef && state.b[10] == 0xfedcba98 &&
                    state.a[0] == 0xaabbccdd && state.a[2] == 0x11223344 && state.a[10] == 0x55667788 &&
                    state.status == 0x87654321 && bank_state.bus.size() == 12 &&
                    bank_state.bus[6].address_bit == 0x01000fa0 && bank_state.bus[10].address_bit == 0x01000fe0,
                    "B-bank MMFM restores distinct registers in reverse stack order without touching A bank");
            {
                auto alias_machine=std::make_unique<mk2::DcsBootMachine>(synthetic_boot);
                auto alias_state=std::make_unique<mk2::BootContinuation>();alias_state->main_ram.resize(262144);
                auto& cpu=alias_state->ready;cpu.a[15]=0x01001000;cpu.status=0x87654321;
                cpu.board.io[8]=0x2000;
                mk2::BootOps alias(unused_program,*alias_machine,*alias_state);
                alias.Mmtm(1,0x300,true);
                require(cpu.a[15]==0x01000fe0 && cpu.cycles==6 && cpu.status==0x87654321 &&
                        alias_state->bus.size()==2 && alias_state->bus[0].address_bit==0x01000fe0 &&
                        alias_state->bus[0].value==0x0fe0 && alias_state->bus[1].value==0x0100,
                        "B-bank MMTM SP alias stores the predecremented shared A15 with exact lanes/cycles/flags");
                alias.Mmfm(1,0x310,true);
                require(cpu.a[15]==0x01001000 && cpu.cycles==13 && cpu.status==0x87654321 &&
                        cpu.instructions==2 && alias_state->bus.size()==4 &&
                        alias_state->bus[2].address_bit==0x01000fe0 && alias_state->bus[2].value==0x0fe0,
                        "B-bank MMFM SP alias loads then increments shared A15 with exact lanes/cycles/flags");
            }
            require(state.cycles == 29 && bank_state.bus.size() == 12 && state.a[15] == 0x01001000,
                    "isolated alias fixture preserves the main B-bank transfer fixture");
            state.board.io[17] = 0x0404; state.board.io[18] = 0x0400;
            state.status = 1;
            ops.WriteField(0xc000012a, 0, 0);
            ops.WriteField(0xc000011a, 0, 0);
            require(state.board.io[18] == 0 && state.board.io[17] == 4 &&
                    bank_state.bus[12].kind == 'r' && bank_state.bus[12].value == 0x400 &&
                    bank_state.bus[13].kind == 'w' && bank_state.bus[13].value == 0 &&
                    bank_state.bus[15].value == 4,
                    "one-bit DI acknowledgement uses physical word RMW and preserves INT2 enable");
            state.status = 0x30; state.next_pc = 0xff8114c0;
            state.board.io[17] = 0x0404; state.board.io[18] = 0x0400;
            const auto irq_bus = bank_state.bus.size();
            const auto irq_instructions = state.instructions;
            state.a[15] = 0x01000020;
            rejects([&] { ops.InterruptEnable(true, 0xff8114d0); },
                    "MK2 IRQ stack outside translated memory");
            require(state.a[15] == 0x01000020 && state.status == 0x30 &&
                    bank_state.bus.size() == irq_bus && state.cycles == 29,
                    "short IRQ stack rejects before first PC push or IE mutation");
            state.a[15] = 0x01001000;
            ops.InterruptEnable(true, 0xff8114d0);
            require(state.next_pc == 0xff816370 && state.status == 0x10 && state.cycles == 48 &&
                    state.instructions == irq_instructions + 1 && state.a[15] == 0x01000fc0 &&
                    bank_state.bus[irq_bus].address_bit == 0x01000fe0 &&
                    bank_state.bus[irq_bus].value == 0x14d0 &&
                    bank_state.bus[irq_bus + 2].address_bit == 0x01000fc0 &&
                    bank_state.bus[irq_bus + 2].value == 0x30 &&
                    bank_state.bus[irq_bus + 4].address_bit == 0xfffffea0,
                    "EINT enters DI atomically with original PC/status stack order and 3+16 cycles");
            state.next_pc = 0xff816e90; state.board.io[18] = 0;
            ops.ReturnInterrupt();
            require(state.next_pc == 0xff8114d0 && state.status == 0x00200030 &&
                    state.a[15] == 0x01001000 && state.cycles == 59,
                    "RETI pops status then PC and restores original interrupted context in 11 cycles");
            const auto safe_cpu = state.a;
            const auto safe_bus = bank_state.bus.size();
            state.board.io[18] = 4;
            rejects([&] { ops.InterruptEnable(true, 0xff8114d0); });
            rejects([&] { ops.ReturnInterrupt(); });
            rejects([&] { ops.RetsAllowed({0xff811360}); });
            require(state.a == safe_cpu && state.cycles == 59 && bank_state.bus.size() == safe_bus &&
                    state.status == 0x00200030 && bank_machine.LastMainCycles() == 59,
                    "unknown IRQ/RETI/return contexts reject before stack, bus, status or DSP mutation");
            state.board.io[18] = 0;
            state.a[0] = 0x7fff7fff; state.status = 0x00200030;
            ops.AddXY(state.a[0], 0x00010001, 0x400);
            require(state.a[0] == 0x80008000 && state.status == 0x50200030,
                    "ADDXY wraps signed lanes independently and uses coordinate N/C/Z/V rather than integer flags");
            state.a[0] = 0xffffffff;
            ops.AddXY(state.a[0], 0x00010001, 0x410);
            require(state.a[0] == 0 && state.status == 0xa0200030,
                    "ADDXY zero lanes set N/Z and clear sign flags without cross-lane carry");
            state.a[0] = 0xaabbccdd; state.status = 0x12345678;
            ops.MoveX(0x55667788, state.a[0], 0x420);
            require(state.a[0] == 0xaabb7788 && state.status == 0x12345678,
                    "MOVX copies low coordinate only and preserves status");
            const auto primitive_cycles = state.cycles;
            rejects([&] { bank_machine.ScheduleDma(4864); },
                    "MK2 DMA timer outside qualified loaded sprite");
            require(!bank_machine.DmaDeadlineSubticks() && !bank_machine.DmaCompletions() &&
                    bank_machine.LastMainCycles() == primitive_cycles,
                    "unknown DMA timer context rejects before clock or timer mutation");
            const auto primitive_bus = bank_state.bus.size();
            // Synthetic ST/SP at the Original TRAP (PC, cycle): rejects before pushes and status mutation. The
            // qualified context, its changed fields and the vector check run on the executor (trap-vector).
            state.next_pc = 0xff8044f0; state.cycles = 1259215; state.status = 0x5a2000f5;
            state.a[15] = 0x01234560; state.board.io[17] = 6;
            rejects([&] { ops.TrapOne(0xff8045d0, 0xff804500); },
                    "MK2 TRAP outside qualified drawing context");
            require(bank_state.bus.size() == primitive_bus && state.a[15] == 0x01234560 &&
                        state.status == 0x5a2000f5 && bank_machine.LastMainCycles() == primitive_cycles,
                    "unknown software trap contexts reject before pushes and status mutation");
            state.cycles = primitive_cycles; state.board.io[17] = 0x0404;
            state.a[15] = 0x01001000;
            state.board.io[18] = 0;
            state.a[1] = 0x80000001; state.status = 0xb0000030;
            ops.Rotate(state.a[1], 0, 0x400);
            require(state.a[1] == 0x80000001 && state.status == 0x90000030,
                    "zero rotation clears carry/zero and preserves N/V without undefined shifts");
            ops.Rotate(state.a[1], 1, 0x410);
            require(state.a[1] == 3 && state.status == 0xd0000030,
                    "rotation wraps the original high bit and emits original carry");
            ops.LeadingOne(0, state.a[0], 0x420);
            require(state.a[0] == 0 && (state.status & 0x20000000),
                    "LMO zero input yields zero count and tests source for zero");
            ops.LeadingOne(0x10, state.a[0], 0x430);
            require(state.a[0] == 27 && !(state.status & 0x20000000),
                    "LMO counts leading zeros in original input queue bits");
            state.a[7] = 0xffffffff;
            ops.MultiplyUnsigned(2, 7, false, 0x440);
            require(state.a[7] == 0xfffffffe,
                    "odd destination multiply stores low product after aliased high result");
            const auto safe_product = state.a;
            const auto safe_cycles = state.cycles;
            rejects([&] { ops.MultiplyUnsigned(2, 14, false, 0); });
            rejects([&] { ops.MultiplyUnsigned(2, 15, false, 0); });
            require(state.a == safe_product && state.cycles == safe_cycles,
                    "multiply shared SP alias rejects before mutation");
            state.status = 0xd0000030; state.a[4] = 0xffffffff;
            ops.MultiplyUnsigned(2, 4, false, 0x450);
            require(state.a[4] == 1 && state.a[5] == 0xfffffffe && state.status == 0xd0000030 &&
                    state.cycles == safe_cycles + 21,
                    "unsigned multiply preserves N/C/V, emits high/low pair and consumes 21 cycles");
            state.status = 0xd0000430; state.a[7] = 0xffffffff; state.a[6] = 0x12345678;
            ops.MultiplyUnsigned(0x10000, 7, false, 0x460);
            require(state.a[7] == 0 && state.a[6] == 0x12345678 && state.status == 0xf0000430 &&
                    state.cycles == safe_cycles + 42,
                    "FW1 zero extension precedes multiply and odd destination aliases only itself");
            state.status = 0x30;
            bank_state.main_ram[0] = 0x80ff; bank_state.main_ram[1] = 0x7654;
            require(ops.ReadField(0x01000000, 0) == 0xffff80ff &&
                    ops.ReadField(0x01000000, 1) == 0x765480ff,
                    "field reads sign extend FW0 while preserving both physical FW1 word lanes");
            state.status = 8;
            require(ops.ReadField(0x01000008, 0) == 0x80,
                    "unsigned byte field reads the selected physical high lane");
            ops.WriteField(0x01000008, 0x1234, 0);
            require(bank_state.main_ram[0] == 0x34ff,
                    "byte field writes truncate and preserve the physical neighboring byte");
            state.status = 16;
            ops.WriteField(0x01000008,0xaabb,0);
            require(ops.ReadField(0x01000008,0)==0xaabb && bank_state.main_ram[0]==0xbbff,
                    "cross-word field preserves neighboring bits through the original two-word RMW");
            const auto fields_bus = bank_state.bus.size();
            rejects([&] { ops.ReadField(0x01000000, 2); });
            state.status = 7;
            rejects([&] { ops.WriteField(0x01000000, 0, 0); });
            require(bank_state.bus.size() == fields_bus && bank_state.main_ram[0] == 0xbbff,
                    "untranslated field widths and selectors reject before physical bus effects");
        }
        mk2::DcsLink synthetic_link;
        const auto dsp_owner = std::make_unique<mk2::AdspBoot>(synthetic_boot, synthetic_link);
        auto& dsp = *dsp_owner;
        dsp.Step(); dsp.Step(); dsp.Step();
        require(dsp.pc == 0x24 && dsp.cycles == 3 && dsp.si == 0x10 &&
                dsp.control[31] == 0x10, "ADSP native jump/immediate/control write");
        rejects([&] { dsp.Step(); });
        require(dsp.pc == 0x24 && dsp.cycles == 3, "ADSP guard before state mutation");
        dsp.ResetCore();
        require(dsp.pc == 0 && dsp.cycles == 0 && dsp.si == 0x10,
                "ADSP warm reset must preserve data registers");
        require(dsp.ReadControl(0x3fe0) == 0xffff, "DCS1 IDMA control is undriven");
        const auto bounded_machine_owner = std::make_unique<mk2::DcsBootMachine>(synthetic_boot);
        auto& bounded_machine = *bounded_machine_owner;
        rejects([&] { bounded_machine.MainInstruction(3658092); },
                "MK2 scheduler outside qualified loaded drawing frontier");
        require(bounded_machine.LastMainCycles() == 0 && bounded_machine.dsp.trace.empty() &&
                bounded_machine.dsp.accesses.empty() && bounded_machine.ScanlineEvents() == 0,
                "scheduler bound rejects before main, DSP, bus or timer mutation");
        rejects([&] { bounded_machine.MainInstruction(0); });
        protection.Write(0xabcd, 0xffff);
        require(protection.Read() == 0xabcd && protection.Shifted() == 0x55e6,
                "MK2 protection latch/shift");
        protection.Write(0x0012, 0x00ff);
        require(protection.Read() == 0xab12, "MK2 low-byte mask");
        protection.Write(0x3400, 0xff00);
        require(protection.Read() == 0x3412 && protection.Constant() == 2,
                "MK2 high-byte mask/constant");
        protection.Write(0xffff, 0);
        require(protection.Read() == 0x3412, "MK2 disabled write");
        mk2::DcsLink link;
        require(link.Control() == 0xc00 && link.MainStatus() == 0xc0, "DCS empty latches");
        link.HostWrite(0x01d01020, 0xfe00);
        link.HostWrite(0x01d01030, 0xfe00, 0x00ff);
        link.Synchronize();
        require(!link.ResetAsserted() && link.Control() == 0xc00, "DCS ignored lane writes");
        link.HostWrite(0x01d01030, 0xfe00);
        require(link.ResetAsserted() && link.Control() == 0xc00, "DCS deferred reset/data");
        link.Synchronize();
        require(link.Control() == 0x400 && link.Irq2Asserted(), "DCS reset then input write");
        link.HostWrite(0x01d01030, 0xffff);
        link.Synchronize();
        require(!link.ResetAsserted() && link.DspReadInput(false) == 0xff &&
                link.Control() == 0x400 && link.Irq2Asserted() && !link.RetireDspInstruction(),
                "DCS release and side-effect-free peek");
        require(link.DspReadInput() == 0xff && link.Control() == 0xc00 &&
                link.Irq2Asserted(), "DCS input becomes empty before synchronized IRQ2 clear");
        require(link.RetireDspInstruction() && !link.Irq2Asserted(), "DCS IRQ2 clears at DSP instruction retirement");
        require(link.DspReadInput() == 0xff && link.RetireDspInstruction() && !link.Irq2Asserted(),
                "DCS redundant input acknowledge still delivers a clear event");
        link.DspWriteOutput(0x1234);
        require(link.Control() == 0xc00, "DCS deferred output");
        link.Synchronize();
        auto peek = link.HostReadOutput(false);
        require(peek.value == 0x34 && peek.polling_cycles == 0 && link.Control() == 0x800,
                "DCS output byte lane/peek");
        require(link.HostReadOutput().value == 0x34 && link.Control() == 0xc00,
                "DCS host output auto-ack");
        require(link.HostReadOutput().polling_cycles == 4444 &&
                link.HostReadOutput(false).polling_cycles == 0, "DCS empty output polling cost");
        link.DspWriteOutput(0x1111);
        link.DspWriteOutput(0x2222);
        link.Synchronize();
        require(link.HostReadOutput().value == 0x22, "DCS pending output latch overwrite");
        link.HostWrite(0x01d01030, 0x01a5, 0x0101);
        link.Synchronize();
        require(link.DspReadInput() == 0xa5 && !link.ResetAsserted(),
                "DCS write accepts access to bits in both byte lanes");
        link.Synchronize();
        link.DspWriteOutput(0x55);
        link.HostWrite(0x01d01030, 0xfe00);
        link.DspReadInput();
        require(!link.RetireDspInstruction() && link.Control() == 0x800 && link.HostReadOutput(false).value == 0x55,
                "DCS instruction retirement publishes output without overtaking a queued host reset");
        link.Synchronize();
        require(link.Control() == 0x400 && !link.Irq2Asserted() && link.DspReadInput(false) == 0,
                "DCS host synchronization preserves reset, command and subsequent clear order");
        std::vector<uint8_t> boot_page(0x1000);
        boot_page[0] = 0x18; boot_page[1] = 0x02; boot_page[2] = 0x2f;
        auto decoded = mk2::DecodeDcsBoot(boot_page);
        require(decoded.size() == 8 && decoded[0] == 0x18022f, "ADSP 24-bit boot byte order");
        boot_page[3] = 0xff;
        rejects([&] { mk2::DecodeDcsBoot(boot_page); });
        rejects([&] { mk2::DecodeDcsBoot({}); });
        mk2::Program invalid;
        mk2::DcsBootMachine invalid_machine(std::vector<uint32_t>(376));
        rejects([&] { mk2::GeneratedBoot generated(invalid, invalid_machine, nullptr, 0xfc7d); });
        invalid.bytes.resize(0x100000);
        invalid.sha256 = mk2::kProgramSha256;
        rejects([&] { mk2::GeneratedBoot generated(invalid, invalid_machine, nullptr, 0xfc7d); });
        // Powerup Test and other non-operator DIP bits are outside the qualified routes.
        rejects([&] { mk2::GeneratedBoot generated(invalid, invalid_machine, nullptr, 0xfc7d | 0x200); });
        rejects([&] { mk2::VerifyProgramLanes({}, {}); });
        rejects([&] { mk2::LoadProgram("missing-mk2-directory"); });
        if (argc == 2 || (argc == 3 && (std::string(argv[2]) == "--batch" || std::string(argv[2]) == "--batch-extended" || std::string(argv[2]) == "--batch-next" || std::string(argv[2]) == "--batch-larger" || std::string(argv[2]) == "--coin-queue" || std::string(argv[2]) == "--coin-accounting" || std::string(argv[2]) == "--coin-pair" || std::string(argv[2]) == "--start-wait" || std::string(argv[2]) == "--next-wait" || prestart_window>=0 || start_input || start_release || selection_window>=0 || first_fight_window>=0))) {
            auto program = mk2::LoadProgram(argv[1]);
            require(program.sha256 == mk2::kProgramSha256, "MK2 program identity");
            require(program.bytes[0x21f0] == 0x60 && program.bytes[0x21f1] == 0x03,
                    "MK2 reset instruction byte order");
            const auto dcs_rom = mk2::LoadDcsDataRoms(argv[1]);
            const auto boot = mk2::DecodeDcsBoot({dcs_rom.begin(), dcs_rom.begin() + 0x1000});
            mk2::DcsLink invalid_link;
            auto changed_boot = boot; changed_boot[0x38] ^= 1;
            rejects([&] { mk2::AdspBoot changed(changed_boot, invalid_link, dcs_rom); },
                    "ADSP initial boot does not match authenticated U2 ROM");
            auto changed_rom = dcs_rom; changed_rom[0x1000] ^= 1;
            rejects([&] { mk2::AdspBoot changed(boot, invalid_link, changed_rom); },
                    "ADSP banked boot requires authenticated U2 ROM");
            const auto machine_owner = std::make_unique<mk2::DcsBootMachine>(boot, dcs_rom);
            auto& machine = *machine_owner;
            // Generated closure from reset to the first cooperative draw (mk2_executor.hpp). Each former manual-stage
            // boundary is compared as full machine state by tools/mk2/test_executor.py (executor_boundaries.json).
            mk2::GeneratedBoot generated(program, machine, nullptr, 0xfc7d);
            const auto& task_draw = generated.Deliver();
            if (argc == 3 && (std::string(argv[2]) == "--coin-pair" || std::string(argv[2]) == "--start-wait" || std::string(argv[2]) == "--next-wait" || prestart_window>=0 || start_input || start_release || selection_window>=0 || first_fight_window>=0)) {
                const bool start_wait=std::string(argv[2]) == "--start-wait";
                const bool next_wait=std::string(argv[2]) == "--next-wait";
                std::cout << "{\"scope\":\"" << (first_fight_high_punch ? "mk2-first-fight-high-punch-suffix" : first_fight_window>=0 ? "mk2-first-fight-suffix" : selection_window>=0 ? "mk2-selection-suffix" : start_release ? "mk2-start-release-suffix" : start_input ? "mk2-start-input-suffix" : prestart_window>=0 ? "mk2-prestart-wait-suffix" : next_wait ? "mk2-next-wait-suffix" : start_wait ? "mk2-start-wait-suffix" : "mk2-coin-pair-suffix") << "\"";
                mk2::WriteTaskBatchObservations(program,task_draw,machine,false,false,false,false,false,!start_release&&!start_input&&!start_wait&&!next_wait&&prestart_window<0&&selection_window<0&&first_fight_window<0,start_wait,next_wait,prestart_window,start_input,start_release,selection_window,first_fight_window,first_fight_high_punch);
                std::cout << "}\n";
                return 0;
            }
            std::cout << "{\"scope\":\"mk2-generated-first-draw\",\"cpu34\":[" << task_draw.ready.next_pc << ',' << task_draw.ready.status << ',' << task_draw.ready.cycles;
            for (auto value : task_draw.ready.a) std::cout << ',' << value;
            for (auto value : task_draw.ready.b) std::cout << ',' << value;
            std::cout << ']';
            if (argc == 3) {
                mk2::WriteTaskBatchObservations(program, task_draw, machine, std::string(argv[2]) == "--batch-extended", std::string(argv[2]) == "--batch-next", std::string(argv[2]) == "--batch-larger", std::string(argv[2]) == "--coin-queue", std::string(argv[2]) == "--coin-accounting");
            }
            std::cout << "}\n";
        } else {
            require(argc == 1, "expected optional MK2 ROM directory");
            std::cout << "MK2 foundation contracts passed (no ROMs)\n";
        }
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
