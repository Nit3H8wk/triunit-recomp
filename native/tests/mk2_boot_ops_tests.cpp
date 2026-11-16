#include "../mk2/mk2_boot_ops.hpp"
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
template<class F> void rejects(F action) {
    bool failed = false;
    try { action(); } catch (const std::runtime_error&) { failed = true; }
    require(failed, "unknown boot access accepted");
}
}
std::vector<uint32_t> IrqBootFixture(const std::vector<uint32_t>& u2) {
    // Cold instruction 0 and PM words 0x1c..0x48 of the user's U2 boot page (the six IRQ vector sources and their
    // loader loop); the rest of the page is cleared so only these instructions are reachable.
    std::vector<uint32_t> boot(376); boot[0]=u2.at(0);
    std::copy(u2.begin()+0x1c,u2.begin()+0x49,boot.begin()+0x1c);
    return boot;
}
int ImmediateIrqContracts(const std::vector<uint32_t>& boot) { try {
 {
  mk2::Program program;
  auto machine=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
  auto out=std::make_unique<mk2::BootContinuation>();out->main_ram.resize(262144);
  out->ready.a[15]=0x01500000;
  mk2::BootOps ops(program,*machine,*out);
  rejects([&] { ops.ReturnInterrupt(); });
  require(out->ready.a[15]==0x01500000 && out->bus.empty() && !machine->LastMainCycles(),
          "unmapped RETI stack rejects before stack or scheduler mutation");
 }
 {
  auto combined=std::make_unique<mk2::DcsBootMachine>(boot);
  auto split=std::make_unique<mk2::DcsBootMachine>(boot);
  combined->MainInstruction(5,true,0x100);split->MainInstruction(5,true,0x100);
  combined->link.DspReadInput();split->link.DspReadInput();
  combined->link.Synchronize();split->link.Synchronize();
  combined->MainInstruction(24);split->MainInstruction(8);split->MainInstruction(24);
  require(combined->dsp.InstructionCount()==38 && split->dsp.InstructionCount()==37,
          "combined19 versus split3+16 retains the original38/37 instruction witness");
 }
 for(unsigned operation=0;operation<3;++operation) {
  for(unsigned pending : {0u,2u,0x402u}) {
   mk2::Program p;p.bytes.resize(0x100000);
   for(auto vector : {std::pair<uint32_t,uint32_t>{0xffffffc0,0xff8045d0},{0xfffffea0,0xff816370}}) {
    const auto n=(vector.first-0xff800000)/8;
    for(unsigned k=0;k<4;++k)p.bytes[n+k]=uint8_t(vector.second>>(k*8));
   }
   auto machine=std::make_unique<mk2::DcsBootMachine>(boot);
   auto expected=std::make_unique<mk2::DcsBootMachine>(boot);
   machine->MainInstruction(5,true,0x100);expected->MainInstruction(5,true,0x100);
   machine->link.DspReadInput();expected->link.DspReadInput();
   machine->link.Synchronize();expected->link.Synchronize();
   auto out=std::make_unique<mk2::BootContinuation>();out->main_ram.resize(262144);
   // Synthetic ST and SP at the Original PCs: IE comes from the instruction under test (EINT) or the saved status.
   auto& s=out->ready;s.cycles=5;s.next_pc=0xff804110;s.status=0x50000015;
   s.board.io[8]=0x2000;s.board.io[17]=0x406;s.board.io[18]=uint16_t(pending);
   s.a[15]=0x01234560;mk2::BootOps o(p,*machine,*out);
   const uint32_t next=operation==2?0xff80413fu:0xff804130u;
   const unsigned cost=operation==0?3:operation==1?8:11;
   if(operation==2)o.Push(next);
   if(operation)o.Push(0x50200015);
   const auto original_sp=s.a[15];out->bus.clear();
   const uint32_t final_sp=original_sp+(operation==0?0:operation==1?32:64)-(pending?64:0);
   if(operation==0)o.InterruptEnable(true,next);
   else if(operation==1)o.PopStatus(next);
   else o.ReturnInterrupt();
   expected->MainInstruction(5+cost+(pending?16:0));
   const uint32_t handler=pending&0x400?0xff816370u:0xff8045d0u;
   if(s.next_pc!=(pending?handler:(next&~15u)) || s.cycles!=5+cost+(pending?16:0) ||
      s.status!=(pending?0x10u:0x50200015u) || s.a[15]!=final_sp || s.instructions!=1)
    return 1+int(operation);
   if(machine->dsp.Registers()!=expected->dsp.Registers() || machine->dsp.trace!=expected->dsp.trace)
    return 11+int(operation);
   const unsigned reads=operation==0?0:operation==1?2:4;
   if(out->bus.size()!=reads+(pending?6:0))return 21+int(operation);
   for(const auto& lane:out->bus)if(lane.pc!=0xff804110 || lane.cycle!=5)return 31+int(operation);
   if(pending) {
    const auto& low=out->bus[reads];
    const auto& high=out->bus[reads+1];
    if(low.value!=(next&0xfff0) || high.value!=0xff80 || out->bus[reads+2].value!=0x15 ||
       out->bus[reads+3].value!=0x5020 || out->bus[reads+4].address_bit!=(pending&0x400?0xfffffea0u:0xffffffc0u))
     return 41+int(operation);
   }
  }
 }
 {
  auto combined=std::make_unique<mk2::DcsBootMachine>(boot);
  auto split=std::make_unique<mk2::DcsBootMachine>(boot);
  combined->MainInstruction(5,true,0x100);split->MainInstruction(5,true,0x100);
  combined->link.DspReadInput();split->link.DspReadInput();
  combined->link.Synchronize();split->link.Synchronize();
  combined->MainInstruction(24);split->MainInstruction(8);split->MainInstruction(24);
  require(combined->dsp.InstructionCount()==38 && split->dsp.InstructionCount()==37,
          "combined19 versus split3+16 retains the original38/37 instruction witness");
 }
 for(unsigned operation=0;operation<3;++operation) {
  mk2::Program p;p.bytes.resize(0x100000); // Invalid fixed vector must reject before any mutation.
  auto machine=std::make_unique<mk2::DcsBootMachine>(boot);
  auto out=std::make_unique<mk2::BootContinuation>();out->main_ram.resize(262144);
  auto& s=out->ready;s.next_pc=0xff804110;s.status=0x50000015;s.a[15]=0x01234560;
  s.board.io[17]=6;s.board.io[18]=2;
  mk2::BootOps o(p,*machine,*out);
  if(operation==2)o.Push(0xff80413f);
  if(operation)o.Push(0x50200015);
  const auto sp=s.a[15];const auto ram=out->main_ram;out->bus.clear();bool rejected=false;
  try {
   if(operation==0)o.InterruptEnable(true,0xff804130);
   else if(operation==1)o.PopStatus(0xff804130);
   else o.ReturnInterrupt();
  }catch(const std::runtime_error&){rejected=true;}
  if(!rejected || s.status!=0x50000015 || s.next_pc!=0xff804110 || s.a[15]!=sp || s.cycles ||
     s.instructions || out->main_ram!=ram || !out->bus.empty() || machine->LastMainCycles())return 51+int(operation);
 }

 {
  mk2::Program p;
  auto m=std::make_unique<mk2::DcsBootMachine>(boot), expected=std::make_unique<mk2::DcsBootMachine>(boot);
  m->MainInstruction(5,true,0x100);expected->MainInstruction(5,true,0x100);
  m->link.DspReadInput();expected->link.DspReadInput();
  m->link.Synchronize();expected->link.Synchronize();
  auto out=std::make_unique<mk2::BootContinuation>();out->main_ram.resize(262144);
  auto& state=out->ready;state.cycles=5;state.next_pc=0xff804110;state.board.io[8]=0x2000;
  mk2::BootOps op(p,*m,*out);
  op.Write16(0x01d01020,1);op.Finish(0xff804140,3);expected->MainInstruction(8);
  if(m->dsp.Registers()!=expected->dsp.Registers() || m->dsp.trace!=expected->dsp.trace ||
     m->link.Control()!=expected->link.Control() || m->link.ResetAsserted()!=expected->link.ResetAsserted() ||
     m->link.Irq2Asserted()!=expected->link.Irq2Asserted() || out->bus.size()!=1 ||
     out->bus[0].address_bit!=0x01d01020 || out->bus[0].value!=1 || out->bus[0].cycle!=5 ||
     out->bus[0].pc!=0xff804110 || out->bus[0].kind!='w')return 61;
 }
 std::cout<<"9 immediate IRQ contexts and 3 invalid vectors; combined scheduler state/trace, physical lanes and rejection atomicity checked\n";
 return 0;
 }catch(const std::exception& e){std::cout<<e.what();return 99;}
}

int main(int argc,char** argv) {
    try {
        mk2::Program program; program.bytes.resize(0x100000);
        program.bytes[0] = 0x12; program.bytes[1] = 0x34;
        mk2::DcsBootMachine machine(std::vector<uint32_t>(376));
        mk2::BootContinuation result; result.main_ram.resize(65536);
        result.ready.board.io[8] = 0x2000; result.ready.board.io[7] = 288;
        mk2::BootOps op(program, machine, result);
        op.s.next_pc = 0xffa5a2e0;
        require(op.Read8(0xff800008) == 0x34 && result.bus.size() == 1 &&
                result.bus[0].value == 0x3412 && result.bus[0].address_bit == 0xff800000,
                "byte extraction retains the physical neighboring ROM byte");
        op.Write32(0x01000000, 0x89abcdef);
        require(op.Read32(0x01000000) == 0x89abcdef && result.main_ram[0] == 0xcdef &&
                result.main_ram[1] == 0x89ab, "main RAM DWORD lanes");
        op.s.cmos[0] = 0xa55a;
        const auto before = result.bus.size();
        op.WriteByte(0x01400000, 0x34);
        require(op.s.cmos[0] == 0xa534 && result.bus.size() == before + 2 &&
                result.bus[before].kind == 'r' && result.bus[before].value == 0xa55a &&
                result.bus.back().kind == 'w' && result.bus.back().value == 0xa534,
                "CMOS byte store is a physical word RMW preserving the other byte");
        op.WriteByte(0x01480000, 0x34);
        require(op.s.cmos_write_enabled && result.bus[result.bus.size()-2].value == 0xffff &&
                result.bus.back().value == 0xff34, "enable gate RMW reads the unmapped pull-up word");
        require(op.Read32(0x01600000) == 0xffffffff, "unpressed input words are active-low");
        uint32_t value = 0x7fffffff;
        op.Arithmetic(value, 1, false, 0xffa5a2f0, 1);
        require(value == 0x80000000 && op.s.status == 0x90000010,
                "addition preserves field bits and sets signed overflow");
        op.s.a[15] = 0x010ffff0; op.s.a[0] = 0x12345678; op.s.a[1] = 0x89abcdef;
        op.Mmtm(0xc000, 0xffa5a300);
        op.s.a[0] = op.s.a[1] = 0;
        op.Mmfm(0xc000, 0xffa5a310);
        require(op.s.a[0] == 0x12345678 && op.s.a[1] == 0x89abcdef &&
                op.s.a[15] == 0x010ffff0 && op.s.status == 0x90000010,
                "multi-register stack transfer restores values and preserves flags");
        op.s.next_pc = 0xff80e3d0; op.s.status = 0xf0200030;
        op.s.a[2] = 0x01002000;
        for (unsigned reg = 7; reg <= 12; ++reg) op.s.a[reg] = 0x12345600 + reg * 0x10203;
        const auto task_registers = op.s.a;
        const auto task_cycle = op.s.cycles;
        const auto task_bus = result.bus.size();
        op.Mmtm(0x01f8, 0xff80e3f0, false, 2);
        require(op.s.a[2] == task_registers[2] - 6 * 32 && op.s.a[15] == task_registers[15] &&
                op.s.status == 0xf0200030 && op.s.cycles == task_cycle + 26 &&
                result.bus.size() == task_bus + 12,
                "task MMTM predecrements A2, preserves SP/flags and charges all six register writes");
        for (unsigned reg = 7; reg <= 12; ++reg) {
            const auto address = task_registers[2] - (reg - 6) * 32;
            const auto lane = task_bus + (reg - 7) * 2;
            require(result.bus[lane].kind == 'w' && result.bus[lane].pc == 0xff80e3d0 &&
                    result.bus[lane].address_bit == address && result.bus[lane].cycle == task_cycle &&
                    result.bus[lane].value == uint16_t(task_registers[reg]) &&
                    result.bus[lane + 1].address_bit == address + 16 &&
                    result.bus[lane + 1].value == uint16_t(task_registers[reg] >> 16),
                    "task MMTM keeps ascending register order and low/high physical lanes at descending addresses");
        }
        const auto before_base_alias = op.s.a;
        const auto before_base_bus = result.bus.size();
        const auto before_base_cycle=op.s.cycles;
        op.Mmtm(0x2000, 0xff80e3f0, false, 2);
        require(op.s.a[2]==before_base_alias[2]-32 && op.Read32(op.s.a[2])==op.s.a[2] &&
                result.bus.size()==before_base_bus+4 && op.s.cycles==before_base_cycle+6 &&
                op.s.status==0xf0200030 && op.s.a[15]==before_base_alias[15],
                "MMTM base alias writes its predecremented value in six cycles with flags preserved");
        op.s.a[2]=before_base_alias[2];
        op.s.a[1] = op.s.a[2];
        for (unsigned reg = 7; reg <= 12; ++reg) op.s.a[reg] = 0;
        const auto restore_cycle = op.s.cycles;
        const auto restore_bus = result.bus.size();
        op.Mmfm(0x01f8, 0xff80de00, false, 1);
        require(op.s.a[1] == task_registers[2] && op.s.a[15] == task_registers[15] &&
                op.s.status == 0xf0200030 && op.s.cycles == restore_cycle + 27,
                "dispatcher context restore advances A1 without changing SP or saved flags");
        for (unsigned reg = 7; reg <= 12; ++reg) {
            const auto lane = restore_bus + (12 - reg) * 2;
            require(op.s.a[reg] == task_registers[reg] &&
                    result.bus[lane].address_bit == task_registers[2] - (reg - 6) * 32 &&
                    result.bus[lane].pc == 0xff80e3f0 && result.bus[lane].cycle == restore_cycle,
                    "dispatcher restore uses descending register order from ascending physical words");
        }
        op.Write32(op.s.a[1],0x01003000);
        const auto before_restore_alias = op.s.a;
        const auto before_restore_bus = result.bus.size();
        const auto before_restore_cycle=op.s.cycles;
        op.Mmfm(0x4000, 0xff80de00, false, 1);
        require(op.s.a[1]==0x01003020 && op.s.a[15]==before_restore_alias[15] &&
                result.bus.size()==before_restore_bus+2 && op.s.cycles==before_restore_cycle+7 &&
                op.s.status==0xf0200030 && result.bus[before_restore_bus].address_bit==before_restore_alias[1],
                "MMFM base alias increments the loaded value in seven cycles with flags preserved");
        op.s.a[1] = task_registers[2];
        const auto saved_sp = op.s.a[15];
        const auto save_cycle = op.s.cycles;
        op.Mmtm(0x01f8, 0xff80dd20, false, 1);
        require(op.s.a[1] == task_registers[2] - 192 && op.s.a[15] == saved_sp &&
                op.s.cycles == save_cycle + 26 && op.s.status == 0xf0200030,
                "cooperative yield saves through A1 without changing SP or flags");
        op.s.a[12] = op.s.a[1];
        op.s.a[7] = 0;
        op.Mmfm(0x0100, 0xff847860, false, 12);
        require(op.s.a[7] == task_registers[12] && op.s.a[12] == task_registers[2] - 160 &&
                op.s.a[15] == saved_sp && op.s.status == 0xf0200030,
                "task stack restore advances A12 while retaining CPU stack and flags");
        op.s.status = 0x90200030;
        op.PushStatus(0xffa4cae0);
        op.s.status = 0x30; op.s.board.io[17] = op.s.board.io[18] = 0x0400;
        const auto before_pop_sp = op.s.a[15];
        const auto before_pop_bus = result.bus.size();
        const auto before_pop_cycles = op.s.cycles;
        rejects([&] { op.PopStatus(0xffa4cb80); });
        require(op.s.a[15] == before_pop_sp && op.s.status == 0x30 &&
                result.bus.size() == before_pop_bus && op.s.cycles == before_pop_cycles,
                "POPST with IE and enabled pending IRQ rejects before stack, bus, flags or clock mutation");
        op.s.board.io[18] = 0;
        op.PopStatus(0xffa4cb80);
        require(op.s.a[15] == before_pop_sp + 32 && op.s.status == 0x90200030 &&
                op.s.cycles == before_pop_cycles + 8,
                "POPST preserves IE and all saved flags when no enabled IRQ is pending");
        const auto registers = op.s.a;
        const auto bus_count = result.bus.size();
        const auto alias_cycles=op.s.cycles;
        op.Mmtm(1, 0xffa5a320);
        require(op.s.a[15]==registers[15]-32 && result.bus.size()==bus_count+2 &&
                result.bus[bus_count].value==uint16_t(registers[15]-32) &&
                result.bus[bus_count+1].value==uint16_t((registers[15]-32)>>16) &&
                op.s.cycles==alias_cycles+6 && op.s.status==0x90200030,
                "MMTM SP alias stores the decremented shared stack pointer with exact lanes and cycles");
        op.Mmfm(1, 0xffa5a320);
        require(op.s.a == registers && result.bus.size() == bus_count+4 &&
                op.s.cycles==alias_cycles+13 && op.s.status==0x90200030,
                "MMFM SP alias restores then increments the shared pointer with exact lanes and cycles");
        rejects([&] { op.Read16(0x02000000); });
        rejects([&] { op.Write16(0x02000000, 1); });
        value = 0x89abcdef; op.s.status = 0xf0000030;
        op.Shift(value, 0, true, 0);
        require(value == 0x89abcdef && op.s.status == 0x90000030,
                "zero shift preserves data/N/V while clearing carry and recalculating zero");
        rejects([&] { op.Shift(value, 32, true, 0); });
        value = 0; op.s.status = 0x40200030;
        op.AddCarry(value, 0xffffffff, 0);
        require(value == 0 && op.s.status == 0x20200030,
                "ADDC retains original core carry rule excluding carry-in from carry comparison");
        value = 0x80008000; op.s.status = 0x10200030;
        op.ShiftArithmetic(value, 16, true, 0);
        require(value == 0xffff8000 && op.s.status == 0xd0200030,
                "SRA retains overflow and sign fills independently of host signed shifts");
        value = 0x80000000; op.s.status = 0x00200030;
        op.ShiftArithmetic(value, 1, false, 0);
        require(value == 0 && op.s.status == 0x70200030,
                "SLA computes discarded sign overflow, carry and zero");
        value = 0x00010000; op.s.status = 0xf0200030;
        op.SubtractXY(value, 0x00020001, 0);
        require(value == 0xffffffff && op.s.status == 0x50200030,
                "SUBXY subtracts signed coordinate lanes independently and sets coordinate flags");
        value = 0x80; op.s.status = 0x50200028;
        op.SignExtend(value, 0, 0);
        require(value == 0xffffff80 && op.s.status == 0xd0200028,
                "SEXT clears NZ only and preserves carry/overflow/IE/field bits");
        for (const auto context : {std::array<uint32_t, 2>{0xff807d50, 0x50200015},
                                   std::array<uint32_t, 2>{0xff807ea0, 0xa02000e9}}) {
            op.s.board.io[18] = 0;
            op.Push(context[0]); op.Push(context[1]);
            op.s.next_pc = 0xff816e90;
            const auto return_cycle = op.s.cycles;
            op.ReturnInterrupt();
            require(op.s.next_pc == context[0] && op.s.status == context[1] &&
                    op.s.cycles == return_cycle + 11 && op.s.a[15] == saved_sp,
                    "RETI restores each dispatcher polling PC and all saved synthetic flags in eleven cycles");
        }
        // Asynchronous DI: entry in qualified contexts (push order, vector, sixteen cycles, preceding-instruction
        // lanes) runs on the executor's own states (mk2_executor_tests display-irq). Synthetic flags at a dispatcher
        // polling PC are outside the qualified set and reject before any mutation.
        const size_t vector_offset = (0xfffffea0u - 0xff800000u) / 8;
        for (unsigned byte = 0; byte < 4; ++byte)
            program.bytes[vector_offset + byte] = uint8_t(0xff816370u >> (byte * 8));
        op.s.next_pc = 0xff807d30; op.s.status = 0x50200015;
        op.Mmtm(0xed80, 0xff807d50);
        const auto interrupted_sp = op.s.a[15];
        op.s.board.io[17] = 0x404; op.s.board.io[18] = 0x400;
        const auto rejected_irq_bus = result.bus.size();
        const auto rejected_irq_cycle = op.s.cycles;
        rejects([&] { op.DisplayInterrupt(); });
        require(op.s.a[15] == interrupted_sp && result.bus.size() == rejected_irq_bus &&
                op.s.cycles == rejected_irq_cycle && op.s.next_pc == 0xff807d50 && op.s.status == 0x50200015,
                "unobserved asynchronous DI flags reject before stack, vector, clock or instruction changes");
        op.s.board.io[18] = 0;
        {
            mk2::DcsBootMachine graphics_machine(std::vector<uint32_t>(376));
            graphics_machine.link.HostWrite(0x01d01030, 0);
            graphics_machine.link.Synchronize();
            mk2::BootContinuation graphics;
            auto& state = graphics.ready;
            state.board.io[8] = 0x6810; state.board.io[7] = 288;
            state.board.io[11] = 0x2c; state.board.io[20] = 18; state.board.io[21] = 8;
            state.board.video_control = 0x20;
            std::fill(graphics.video.vram.begin(), graphics.video.vram.end(), uint16_t(0x5aa5));
            std::array<uint16_t, 1024> pixels{};
            for (unsigned n = 0; n < pixels.size(); ++n) pixels[n] = uint16_t(0xa500 + n * 0x13);
            graphics.video.shift_register.fill(0xcafe);
            std::copy(pixels.begin(), pixels.end(), graphics.video.vram.begin() + 0x3fc00);
            mk2::BootOps graphics_op(program, graphics_machine, graphics);
            state.next_pc = 0xff817080; state.b[2] = 0x1fe000; state.status = 0xf0200030;
            graphics_op.PixelRead(state.b[2], state.b[2], 0xff817090);
            require(state.b[2] == 0xa500 && state.status == 0xf0200030 && state.cycles == 4 && graphics.bus.empty() &&
                    std::equal(pixels.begin(), pixels.end(), graphics.video.shift_register.begin()) &&
                    std::all_of(graphics.video.shift_register.begin() + 1024, graphics.video.shift_register.end(),
                                [](uint16_t value) { return value == 0xcafe; }),
                    "PIXT loads all raw shift-register words and returns full first word without ordinary CPU bus lanes");
            std::fill_n(graphics.video.vram.begin() + 0x3fc00, 1024, uint16_t(0x7777));
            graphics_machine.MainInstruction(5800); state.cycles = 5800;
            state.next_pc = 0xff817130; state.status = 0x30;
            state.b[2] = 0; state.b[3] = 0x2000; state.b[4] = 3;
            state.b[7] = 0x007f0001; state.b[9] = 0x12;
            state.board.io[11] |= 0x40;
            rejects([&] { graphics_op.FillXY(0xff817140); });
            require(state.cycles == 5800 && graphics.bus.empty() && state.status == 0x30 &&
                    graphics.video.vram[0] == 0x5aa5,
                    "unqualified clipping mode rejects before any FILL memory, progress or timing mutation");
            state.board.io[11] = 0x2c;
            graphics_op.FillXY(0xff817140);
            require(state.cycles == 5929 && state.next_pc == 0xff817130 && state.status == 0x02000030 &&
                    state.b[2] == 0 && graphics.bus.empty() && graphics.video.vram[127 * 1024] == 0x5aa5,
                    "FILL writes whole shift-register blocks once before timer restart without ordinary CPU bus lanes");
            for (unsigned row = 0; row < 127; ++row)
                require(std::equal(pixels.begin(), pixels.end(), graphics.video.vram.begin() + row * 1024),
                        "each shift-register callback copies all 1024 physical words including palette bits");
            auto resumed_graphics=graphics;
            {
                mk2::BootOps resumed(program,graphics_machine,resumed_graphics);
                resumed.FillXY(0xff817140);
            }
            graphics=std::move(resumed_graphics);
            require(state.cycles == 6316 && state.next_pc == 0xff817140 && state.status == 0x30 &&
                    state.b[2] == 0x007f0000 && graphics.bus.empty(),
                    "FILL consumes all 516 original cycles and advances destination Y only on final restart");
            state.next_pc = 0xff817130; state.status = 0x30; state.b[2] = 0; state.b[4] = 0x100003;
            const auto second_fill_cycle = state.cycles;
            do { graphics_op.FillXY(0xff817140); } while (state.next_pc == 0xff817130);
            require(state.cycles == second_fill_cycle + 516 && state.b[2] == 0x007f0000,
                    "second display page retains original FILL timing and register update");
            for (unsigned row = 0; row < 127; ++row)
                require(std::equal(pixels.begin(), pixels.end(), graphics.video.vram.begin() + 0x20000 + row * 1024),
                        "second display page preserves shift-register contents rather than replacing them with COLOR1");
            graphics.video.vram[0x3fc00] = 0;
            state.next_pc = 0xff817080; state.status = 0xf0200030;
            graphics_op.PixelRead(0x1fe000, state.b[2], 0xff817090);
            require(state.b[2] == 0 && state.status == 0xe0200030 && graphics.bus.empty(),
                    "zero shift-register first word clears only V and preserves NZC and field bits");
        }
        require(argc==2,"expected the authenticated U2 ROM path");
        const auto boot=IrqBootFixture(mk2::LoadDcsBoot(argv[1]));
        require(ImmediateIrqContracts(boot) == 0, "immediate IRQ contracts failed");
        std::cout << "MK2 boot primitives passed\n";
    } catch (const std::exception& error) { std::cerr << error.what(); return 1; }
}
