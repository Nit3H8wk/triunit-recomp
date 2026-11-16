"""Generator guards for the finite native ADSP boot translation."""
from pathlib import Path
import importlib.util
import os
import sys
import unittest


class AdspGeneratorTests(unittest.TestCase):
    def generator(self):
        path = Path(__file__).with_name("generate_adsp.py")
        self.assertTrue(path.is_file(), "native ADSP generator is missing")
        spec = importlib.util.spec_from_file_location("generate_adsp", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_neutral_wrap_uses_only_the_six_authenticated_fixed_pcs(self):
        g=self.generator()
        self.assertEqual(g.translate(0x939ffa),"WriteData(0x39ff, ar);")
        rom=g.ROOT/'roms/mk2/su2.l1'
        if not rom.is_file():self.skipTest('requires authenticated U2')
        source=g.generate(rom.read_bytes())
        for pc,word in ((0x358,0x42000a),(0x359,0x939ffa),(0x35a,0x22200f),(0x35b,0x9390fa),(0x35c,0x0d00ae),(0x35d,0x0a000f)):
            self.assertIn(f'case 0x{pc|0x10000:05x}: CheckOpcode(0x{word:06x}); Advance();',source)

    def test_neutral_clear_has_eight_rom_qualified_slots(self):
        g=self.generator()
        rom=g.ROOT/'roms/mk2/su2.l1'
        if not rom.is_file():self.skipTest('requires authenticated U2')
        source=g.generate(rom.read_bytes())
        words=(0x403884,0x26630f,0x22730f,0x0d041a,0x400008,0x680085,0x680085,0x1c332f)
        for n,word in enumerate(words):
            self.assertIn(f'case 0x{0x10246+n:05x}: CheckOpcode(0x{word:06x}); Advance();',source)

    def test_known_instruction_is_fixed_native_code(self):
        generator = self.generator()
        self.assertEqual(generator.translate(0x400108), "si = 0x0010;")
        self.assertEqual(generator.translate(0x18022f), "pc = 0x0022;")
        self.assertEqual(generator.translate(0x5000a5), "ReadProgramAr();")

    def test_unknown_or_different_variant_is_rejected(self):
        generator = self.generator()
        for opcode in (0xffffff, 0x5000a4, 0x0d0c19, 0x14039f, 0x180220):
            with self.subTest(opcode=opcode), self.assertRaises(ValueError):
                generator.translate(opcode)

    def test_original_bank_switch_and_loader_have_fixed_translations(self):
        generator = self.generator()
        expected = {0x930008: "WriteData(0x3000, si);",
                    0x1c3e8f: "PushPc(); pc = 0x03e8;",
                    0x0a000f: "ReturnCall();"}
        for opcode, statement in expected.items():
            with self.subTest(opcode=opcode):
                try:
                    translated = generator.translate(opcode)
                except ValueError as error:
                    self.fail(str(error))
                self.assertEqual(translated, statement)

    def test_idle_firmware_arithmetic_and_shift_have_fixed_translations(self):
        generator = self.generator()
        expected = {0x26e00f: "af = Sub(ax0, ay0, false);",
                    0x180640: "if (astat & 1) pc = 0x0064;",
                    0x0e120f: "ShiftLogical(ar, int8_t(se), false, false);"}
        for opcode, statement in expected.items():
            with self.subTest(opcode=opcode):
                self.assertEqual(generator.translate(opcode), statement)

    def test_wrapped_half_buffer_uses_fixed_original_branch(self):
        generator = self.generator()
        self.assertEqual(generator.translate(0x404f0a), "ar = 0x04f0;")
        self.assertEqual(generator.translate(0x1813bf), "pc = 0x013b;")
        for pc in (0x133, 0x134, 0x135):
            self.assertIn(pc, generator.IDLE_PCS)

    def test_invalid_boot_cannot_generate(self):
        generator = self.generator()
        for data in (b"", bytes(0x80000)):
            with self.assertRaises(ValueError):
                generator.generate(data)

    def test_delay_exit_instructions_have_fixed_translations(self):
        generator = self.generator()
        expected = {0x839fca: "ar = ReadData(0x39fc);",
                    0x267a0f: "CopyArToAf();", 0x180f41: "DelayBranch();"}
        for opcode, statement in expected.items():
            with self.subTest(opcode=opcode):
                try:
                    actual = generator.translate(opcode)
                except ValueError as error:
                    self.fail(str(error))
                self.assertEqual(actual, statement)

    def test_irq_handler_uses_fixed_original_instructions(self):
        generator = self.generator()
        expected = {0x1816ef: "pc = 0x016e;", 0x0c0030: "SelectBank(uint8_t(mstat | 1));",
                    0x83400a: "ar = ReadInput();", 0x979fc5: "WriteData(0x39fc, uint16_t(m[5]));",
                    0x0a001f: "ReturnIrq();"}
        for opcode, statement in expected.items():
            self.assertEqual(generator.translate(opcode), statement)

    def test_pair_firmware_words_use_closed_original_arithmetic_dag_and_control_flow(self):
        generator=self.generator()
        expected={0x1823af:'pc = 0x023a;',0x182461:'if (!(astat & 1)) pc = 0x0246;',
                  0x1824e0:'if (astat & 1) pc = 0x024e;',0x26620f:'af = Add(ar, ay0, false);',
                  0x22720f:'ar = Add(ar, af, true);',0x182641:'if (!(astat & 1)) pc = 0x0264;',
                  0x6000a4:'ar = ReadDag(1, 0);',0x181d6f:'pc = 0x01d6;',0x0d01b6:'mr0 = m[2];'}
        for opcode,want in expected.items():
            with self.subTest(opcode=opcode):self.assertEqual(generator.translate(opcode).strip(),want)

    def test_loaded_irq_parallel_move_uses_old_operand_and_closed_variant(self):
        generator = self.generator()
        self.assertEqual(generator.translate(0x2bc604),
                         "{ const auto moved = ay0; ar = Logic(uint16_t(sr0 ^ ay0)); ax0 = moved; }")
        with self.assertRaises(ValueError):
            generator.translate(0x2bc605)

    def test_palette_wait_parallel_decrement_and_jump_have_closed_translations(self):
        generator = self.generator()
        expected = {
            0x2b004e: "{ const auto moved = sr0; ar = Decrement(ay0, true); ay0 = moved; }",
            0x189a2f: "pc = 0x09a2;",
        }
        for opcode, statement in expected.items():
            with self.subTest(opcode=opcode):
                try:
                    translated = generator.translate(opcode)
                except ValueError as error:
                    self.fail(str(error))
                self.assertEqual(translated, statement)
        for pc in (0x998, 0x999, 0x99a, 0x99b, 0x99c, 0x99d, 0x99e):
            self.assertIn(pc, generator.PALETTE_PCS)
        with self.assertRaises(ValueError):
            generator.translate(0x2b005e)

    def test_native_delay_exit_flags_irq_and_fractional_scanline_boundaries(self):
        # Catches wrong AF flags, mutation before an unsupported branch/IRQ, and
        # rounding a scanline up to the next main cycle instead of its budget.
        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root))
        from tools.quality import run as quality
        source = r'''
#include "mk2_adsp.hpp"
#include "mk2_dcs.hpp"
#include <algorithm>
#include <stdexcept>
#include <iostream>
void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
template<class F> void rejected(F action) {
    try { action(); } catch (const std::runtime_error&) { return; }
    throw std::runtime_error("expected scope rejection");
}
// Fixed DSP words are read from the user's U2 (argv[1]); none is stored here.
std::vector<uint8_t> u2;
uint32_t U2Word(size_t offset) { return uint32_t(u2.at(offset))<<16 | uint32_t(u2.at(offset+1))<<8 | u2.at(offset+2); }
uint32_t BootWord(uint16_t pc) { return U2Word(size_t(pc)*4); }
uint32_t Firmware(uint16_t pc) { return U2Word(pc<0x400 ? 0x1000+size_t(pc)*4 : 0x2000+size_t(pc-0x800)*4); }
int main(int argc,char** argv) {
    try {
        check(argc==2,"expected the MK2 ROM directory");
        const auto dcs=mk2::LoadDcsDataRoms(argv[1]);
        u2.assign(dcs.begin(),dcs.begin()+0x80000);
        const auto real_boot=mk2::DecodeDcsBoot({u2.begin(),u2.begin()+0x1000});
        std::vector<uint32_t> boot(376);
        for (uint16_t pc : {0x40,0x41,0x42,0x43,0x45,0x46,0x47}) boot[pc] = BootWord(pc);
        // Context guards compare PM with the authenticated U2: same PM image, ROM attached.
        auto rom_backed=[&](mk2::DcsLink& link) {
            mk2::AdspBoot dsp(real_boot,link,u2);
            std::copy(boot.begin(),boot.end(),dsp.pm.begin());
            return dsp;
        };
        mk2::DcsLink link;
        mk2::AdspBoot dsp(boot, link);
        mk2::AdspBoot countdown(boot, link);
        countdown.rebooted_ = true;
        countdown.pm[0x2fa] = Firmware(0x2fa); countdown.pm[0x2fb] = Firmware(0x2fb);
        for (uint16_t value : {uint16_t(0), uint16_t(1), uint16_t(2), uint16_t(0x8000)}) {
            countdown.pc = 0x2fa; countdown.ay0 = value; countdown.si = 0x1234;
            countdown.mstat = 0; countdown.astat = 0;
            const auto cycles = countdown.cycles;
            countdown.Step(); countdown.Step();
            check(countdown.pc == 0x2fc && countdown.cycles == cycles + 2 &&
                  countdown.ar == uint16_t(value - 1) && countdown.si == countdown.ar &&
                  countdown.ay0 == value, "original queued-command countdown reaches its existing continuation");
        }
        for (uint16_t pc : {uint16_t(0x2fa), uint16_t(0x2fb)}) {
            countdown.pc = pc; countdown.pm[pc] ^= 1;
            const auto saved = countdown.Registers(); const auto rows = countdown.trace.size();
            rejected([&] { countdown.Step(); });
            check(countdown.Registers() == saved && countdown.trace.size() == rows,
                  "changed countdown opcode rejects before mutation");
            countdown.pm[pc] ^= 1;
        }
        for (uint16_t value : {uint16_t(0), uint16_t(0x1234), uint16_t(0x8000)}) {
            dsp.pc = 0x45; dsp.dm[0x1fc] = value; dsp.astat = 0xff;
            dsp.Step();
            check(dsp.ar == value && dsp.accesses.back().pc == 0x45 &&
                  dsp.accesses.back().address == 0x39fc && dsp.accesses.back().space == 'r', "DM read");
            dsp.Step();
            check(dsp.Registers()[44] == value &&
                  dsp.astat == (value == 0 ? 0xf1 : value == 0x8000 ? 0xf2 : 0xf0), "AF flags");
            auto before = dsp.Registers(); const auto count = dsp.trace.size();
            dsp.Step();
            check(dsp.pc == (value ? 0xf4 : 0x48), "original delay exit branch");
            check(dsp.trace.size() == count + 1 && dsp.cycles == before[1] + 1, "branch executes once");
        }
        dsp.pc = 0x44; dsp.imask = 0x20;
        link.HostWrite(0x01d01030, 0x01ff); link.Synchronize();
        auto before = dsp.Registers(); const auto count = dsp.trace.size();
        rejected([&] { dsp.Step(); });
        check(dsp.Registers() == before && dsp.trace.size() == count, "IRQ rejected before mutation");
        boot[4] = BootWord(0x1c);  // first-boot IRQ2 vector, copied from page word 0x1c
        for (uint16_t n = 0; n < 9; ++n) boot[0x16e + n] = BootWord(uint16_t(0x16e + n));
        mk2::DcsLink irq_link;
        auto irq = rom_backed(irq_link);
        irq.pc = 0x44; irq.imask = 0x20; irq.mstat = 0x10; irq.astat = 0x95;
        irq.ar = 0x1234; irq.si = 0x10; irq.af = 0x6789; irq.px = 0x5a;
        irq.i[4] = 0x123; irq.m[5] = 1;
        irq_link.HostWrite(0x01d01030, 0xff02); irq_link.Synchronize();
        irq.Step();
        check(irq.trace.back()[0] == 4 && irq.pc == 0x16e && irq.pc_sp == 1 && irq.stat_sp == 1 &&
              irq.imask == 0 && irq.sstat == 0x44, "IRQ vector saves status and PC without an extra cycle");
        check(irq.pc_stack_[0] == 0x44, "IRQ physically saves return PC at current stack pointer");
        irq.Step();
        check(irq.mstat == 0x11 && irq.ar == 0 && irq.si == 0 && irq.af == 0 &&
              irq.Registers()[61] == 0x1234 && irq.Registers()[71] == 0x10,
              "secondary-bank entry retains primary registers independently");
        for (unsigned n = 0; n < 8; ++n) irq.Step();
        check(irq.pc == 0x44 && irq.cycles == 10 && irq.pc_sp == 0 && irq.stat_sp == 0 &&
              irq.sstat == 0x55 && irq.imask == 0x20 && irq.mstat == 0x10 && irq.astat == 0x95 &&
              irq.ar == 0x1234 && irq.si == 0x10 && irq.af == 0x6789 && irq.px == 0x5a &&
              irq.i[4] == 0x123 && irq.dm[0x1fc] == 1 && irq_link.Control() == 0xc00 &&
              !irq_link.Irq2Asserted() && irq.Registers()[61] == 2 &&
              irq.Registers()[63] == 0x123 && irq.Registers()[64] == 0x5a,
              "RTI restores status, primary bank, PX and I4 after the original input auto-ack and flag write");
        check(irq.accesses.size() == 2 && irq.accesses[0].pc == 0x172 && irq.accesses[0].address == 0x3400 &&
              irq.accesses[0].value == 2 && irq.accesses[1].pc == 0x173 && irq.accesses[1].address == 0x39fc &&
              irq.accesses[1].value == 1, "IRQ handler records both data accesses once in original order");
        mk2::DcsLink isolated_link;
        mk2::AdspBoot isolated(boot, isolated_link);
        isolated.rebooted_ = true;
        isolated.pm[0x15a] = Firmware(0x15a);
        isolated.pc = 0x15a;
        isolated.i[4] = 0x3400;
        isolated.ar = 0x1234;
        isolated.Step();
        check(isolated_link.Control() == 0xc00 && isolated_link.HostReadOutput(false).value == 0,
              "standalone DSP step leaves output pending until link synchronization");
        isolated_link.Synchronize();
        check(isolated_link.Control() == 0x800 && isolated_link.HostReadOutput(false).value == 0x34,
              "synchronization publishes the standalone DSP output");
        irq_link.HostWrite(0x01d01030, 0xff21); irq_link.Synchronize();
        irq.Step(); irq.Step();
        check(irq.mstat == 0x11 && irq.ar == 2, "second IRQ reuses the retained alternate bank");
        irq.ResetCore();
        check(irq.mstat == 0 && irq.ar == 0x1234 && irq.si == 0x10 && irq.af == 0x6789 &&
              irq.Registers()[61] == 2 && irq.pc_sp == 0 && irq.stat_sp == 0,
              "warm reset selects the primary bank while preserving both banks' data registers");
        for (uint16_t return_pc : {uint16_t(0x136), uint16_t(0x138)}) {
            mk2::DcsLink firmware_link;
            auto firmware = rom_backed(firmware_link);
            firmware.rebooted_ = true; firmware.pm[4] = Firmware(4);
            firmware.pc = return_pc; firmware.imask = 0x20; firmware.mstat = 8; firmware.astat = 0x95;
            firmware_link.HostWrite(0x01d01030, 0xff55); firmware_link.Synchronize();
            firmware.EnterIrq2();
            check(firmware.pc == 4 && firmware.pc_sp == 1 && firmware.stat_sp == 1 &&
                  firmware.pc_stack_[0] == return_pc && firmware.imask == 0 && firmware.sstat == 0x44,
                  "firmware IRQ saves the measured loop return PC and status without changing DAG/loop frames");
            check(firmware_link.DspReadInput() == 0x55, "firmware input auto-ack reads original host byte");
            firmware_link.Synchronize();
            firmware.ReturnIrq();
            check(firmware.pc == return_pc && firmware.pc_sp == 0 && firmware.stat_sp == 0 &&
                  firmware.imask == 0x20 && firmware.mstat == 8 && firmware.astat == 0x95 && firmware.sstat == 0x55,
                  "firmware RTI restores exact interrupt context");
            firmware.pc = 0x137;
            firmware_link.HostWrite(0x01d01030, 0xffaa); firmware_link.Synchronize();
            const auto guard = firmware.Registers();
            rejected([&] { firmware.EnterIrq2(); });
            check(firmware.Registers() == guard, "unobserved firmware IRQ return PC rejects before mutation");
        }
        for (uint8_t mode : {uint8_t(8),uint8_t(24)}) {
            mk2::DcsLink active_link;
            auto active = rom_backed(active_link);
            active.rebooted_=true; active.main_horizon_=5077311; active.pm[4]=Firmware(4);
            active.pc=0xee; active.pc_sp=1; active.pc_stack_[0]=0x44;
            active.loop_sp=1; active.loops_[0]={0xa0,0xfe};
            active.cntr_sp=1; active.counters_[0]=9; active.cntr=7;
            active.imask=0x20; active.mstat=mode; active.astat=0x95; active.sstat=0x10;
            active.ar=0x1234;
            active_link.HostWrite(0x01d01030,0xff55); active_link.Synchronize();
            active.EnterIrq2();
            check(active.pc==4 && active.pc_sp==2 && active.stat_sp==1 && active.sstat==0 &&
                  active.pc_stack_[0]==0x44 && active.pc_stack_[1]==0xee && active.loop_sp==1 &&
                  active.loops_[0].start==0xa0 && active.loops_[0].end==0xfe &&
                  active.cntr_sp==1 && active.counters_[0]==9 && active.cntr==7,
                  "active audio IRQ preserves existing call, counter and loop frames");
            active.SelectBank(uint8_t(mode|1)); active.ar=0xabcd;
            check(active_link.DspReadInput()==0x55,"active IRQ acknowledges the actual host byte");
            active_link.Synchronize();
            active.ReturnIrq();
            check(active.pc==0xee && active.pc_sp==1 && !active.stat_sp && active.sstat==0x10 &&
                  active.imask==0x20 && active.mstat==mode && active.astat==0x95 && active.ar==0x1234 &&
                  active.loop_sp==1 && active.cntr_sp==1 && active.counters_[0]==9,
                  "active RTI restores original mode, registers and existing stack depths");
        }
        {
            mk2::DcsBootMachine local(real_boot,u2),old_scope(real_boot,u2);
            std::copy(boot.begin(),boot.end(),local.dsp.pm.begin()); std::copy(boot.begin(),boot.end(),old_scope.dsp.pm.begin());
            local.main_horizon_=5077311; local.dsp_ticks_=old_scope.dsp_ticks_=54;
            const auto state=local.dsp.Registers();
            local.RunDspUntil(50);
            check(local.dsp_ticks_==54 && local.dsp.Registers()==state && !local.dsp.InstructionCount(),
                  "timer target behind DSP local time neither rewinds nor executes an instruction");
            rejected([&] { old_scope.RunDspUntil(50); });
        }
        {
            const auto boosted = [&](uint64_t local_ticks) {
                auto machine = std::make_unique<mk2::DcsBootMachine>(boot);
                machine->dsp.pc = 0x44;
                machine->last_main_ = 5;
                machine->dsp_ticks_ = local_ticks;
                machine->target_ticks_ = 100;
                machine->main_limit_ = 6;
                machine->sliced_ = true;
                machine->boost_expiry_ticks_ = 500;
                machine->next_scanline_ticks_ = 125;
                return machine;
            };
            auto crossed = boosted(90);
            crossed->MainInstruction(9);
            check(crossed->dsp_ticks_ == 120 && crossed->target_ticks_ == 170 &&
                  crossed->ScanlineEvents() == 1 && crossed->dsp.InstructionCount() == 3,
                  "a crossed scanline retires an exhausted boost grant without replaying DSP instructions");
            auto invalid = boosted(120);
            rejected([&] { invalid->MainInstruction(9); });

            auto input_line = boosted(90);
            input_line->next_scanline_ticks_ = 101;
            input_line->MainInstruction(6, false, 0, true);
            check(input_line->dsp_ticks_ == 100 && input_line->target_ticks_ == 150 &&
                  input_line->main_limit_ == 9 && input_line->ScanlineEvents() == 1 &&
                  input_line->dsp.InstructionCount() == 1,
                  "input-line catch-up leaves the DSP at the timer's later local time");
        }
        {
            auto sport_boot = boot;
            sport_boot[0x26] = BootWord(0x26);
            sport_boot[0x4f] = BootWord(0x4f);
            auto machine = std::make_unique<mk2::DcsBootMachine>(sport_boot);
            auto& dsp = machine->dsp;
            dsp.pc = 0x26;
            dsp.Step();
            dsp.pc = 0x4f;
            dsp.Step();
            dsp.m[0] = 256;
            dsp.Modify(0, 0);
            dsp.dac_enabled_ = true;
            dsp.dac_bufin_ = 3;
            dsp.dac_buffer_[0] = 100;
            dsp.dac_buffer_[1] = -50;
            dsp.dac_buffer_[2] = 25;
            dsp.sport_irq1_latched = true;
            rejected([&] { dsp.SportTransfer(9600); });
            check(dsp.dac_bufout_ == 0 && dsp.i[0] == 0x3900,
                  "zero-length SPORT without board reset rejects without flushing");
            machine->link.HostWrite(0x01d01030, 0xfe00);
            dsp.ReloadBoard();
            machine->link.Synchronize();
            dsp.SportTransfer(9600);
            check(dsp.i[0] == 0x3800 && dsp.sport_base == 0x3800 &&
                  dsp.dac_bufin_ == 3 && dsp.dac_bufout_ == 3 && dsp.sport_pcm.empty() &&
                  !dsp.SportPacketCount() && dsp.sport_irq1_asserted && dsp.sport_irq1_latched,
                  "reset-held zero-length SPORT drains the existing ring and wraps to the saved DAG base");
            dsp.ClearSportIrq1(9610);
            check(!dsp.sport_irq1_asserted && dsp.sport_irq1_latched &&
                  dsp.sport_irq1_events.size() == 2 && dsp.sport_irq1_events[0][0] == 9600 &&
                  dsp.sport_irq1_events[1][0] == 9610,
                  "zero-length SPORT IRQ1 pulse leaves the core latch set");
        }
        {
            auto machine = std::make_unique<mk2::DcsBootMachine>(boot);
            auto& dsp = machine->dsp;
            dsp.pc = 0x44;
            dsp.sport_enabled = dsp.dac_enabled_ = true;
            dsp.sport_ireg = 7;
            dsp.sport_base = 0x3800;
            dsp.sport_size = dsp.l[7] = 480;
            dsp.sport_incs = 1;
            dsp.i[7] = 0x38f0;
            machine->last_main_ = 7;
            machine->dsp_ticks_ = 120;
            machine->sport_deadline_ticks_ = 130;
            machine->MainInstruction(8);
            check(machine->dsp_ticks_ == 140 && dsp.InstructionCount() == 2 &&
                  dsp.SportPacketCount() == 1 && !dsp.sport_irq1_asserted && dsp.sport_irq1_latched &&
                  dsp.sport_irq1_events.size() == 2 && dsp.sport_irq1_events[0][0] == 130 &&
                  dsp.sport_irq1_events[1][0] == 140,
                  "SPORT and IRQ1 clear in one main cycle retain their separate DSP deadlines");
        }
        if (argc==2) {
            const auto rom=mk2::LoadDcsDataRoms(argv[1]);
            const auto first_page=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+4096});
            for (unsigned variant=0;variant<14;++variant) {
                mk2::DcsLink service_link;
                mk2::AdspBoot service(first_page,service_link,rom);
                const bool loop_end=variant>=10;
                const uint16_t resume=loop_end?0x129:0x127;
                const uint16_t counter=loop_end?70:77;
                service.service_irq_domain_=variant!=9;
                service.rebooted_=true;
                for (const auto address : {0x004,0x127,0x129,0x15c,0x394,0x3e7}) {
                    const auto offset=0x1000+4*address;
                    service.pm[address]=uint32_t(rom[offset])<<16 | uint32_t(rom[offset+1])<<8 | rom[offset+2];
                }
                // Synthetic ASTAT and host command bytes; PCs, loop/counter facts and MSTAT/IMASK are the guard's.
                service.pc=resume; service.mstat=8; service.imask=0x20; service.astat=0x93; service.sstat=0x10;
                service.pc_sp=service.loop_sp=service.cntr_sp=1;
                service.pc_stack_[0]=0x126; service.loops_[0]={0x126,0x129};
                service.counters_[0]=250; service.cntr=counter;
                switch (variant) {
                case 1: service.pc=0x129; break;
                case 2: service.pm[0x127]^=1; break;
                case 3: service.pc_stack_[0]=0x125; break;
                case 4: service.loops_[0].end=0x128; break;
                case 5: --service.counters_[0]; break;
                case 6: --service.cntr; break;
                case 7: service.pc=0x15c; service.mstat=10; service.pc_stack_[0]=0x159;
                        service.loops_[0]={0x159,0x15c}; service.cntr=24; break;
                case 8: service.icntl=1; break;
                case 11: service.pm[0x129]^=1; break;
                case 12: service.pc=0x127; break;
                case 13: ++service.cntr; break;
                }
                const uint16_t command=loop_end?0xa5:0x5a;
                service_link.HostWrite(0x01d01030,0xff00|command); service_link.Synchronize();
                if (variant && variant!=10) {
                    const auto before=service.ExecutionState();
                    rejected([&] { service.EnterIrq2(); });
                    check(service.ExecutionState()==before && service_link.Irq2Asserted() &&
                          service_link.Control()==0x400,
                          "unverified FC7C active-loop IRQ2 context rejects before stack or latch mutation");
                    continue;
                }
                service.EnterIrq2();
                check(service.pc==4 && !service.imask && service.pc_sp==2 && service.stat_sp==1 &&
                      service.pc_stack_[0]==0x126 && service.pc_stack_[1]==resume &&
                      service.interrupt_.mstat==8 && service.interrupt_.imask==0x20 && service.interrupt_.astat==0x93,
                      "qualified FC7C IRQ2 preserves the loop PC and pushes its exact return and status");
                check(service_link.DspReadInput()==command && service_link.Irq2Asserted() && service_link.Control()==0xc00,
                      "FC7C input auto-ack fills the empty flag before clearing physical IRQ2");
                service_link.Synchronize();
                service.SelectBank(9); service.astat=1;
                service.ReturnIrq();
                check(!service_link.Irq2Asserted() && service.pc==resume && service.mstat==8 &&
                      service.imask==0x20 && service.astat==0x93 && service.sstat==0x10 && !service.stat_sp &&
                      service.pc_sp==1 && service.pc_stack_[0]==0x126 && service.loop_sp==1 &&
                      service.loops_[0].start==0x126 && service.loops_[0].end==0x129 &&
                      service.cntr_sp==1 && service.counters_[0]==250 && service.cntr==counter,
                      "FC7C RTI restores the exact active loop before the resumed instruction");
                if (loop_end) {
                    service.WriteIndex0(0x38ba);
                    service.m[1]=1; service.mr1=0xfffc;
                    service.Step();
                    check(service.pc==0x126 && service.cntr==69 && service.i[0]==0x38bb &&
                          service.dm[0xba]==0xfffc && service.pc_sp==1 && service.loop_sp==1 && service.cntr_sp==1,
                          "FC7C resumes the loop end, writes MR1, advances I0 and decrements CNTR");
                }
            }
            for (unsigned variant=0;variant<5;++variant) {
                mk2::DcsLink service_link;
                mk2::AdspBoot service(first_page,service_link,rom);
                service.service_irq_domain_=service.rebooted_=true;
                for (const auto address : {0x004,0x136,0x137,0x3a9}) {
                    const auto offset=0x1000+4*address;
                    service.pm[address]=uint32_t(rom[offset])<<16 | uint32_t(rom[offset+1])<<8 | rom[offset+2];
                }
                service.pc=0x3a9; service.mstat=9; service.pc_sp=service.stat_sp=1;
                const uint16_t resume=variant==2?0x137:0x136;
                service.interrupt_={resume,8,0x20,2};
                service.pc_stack_[0]=resume;
                if (variant==3) service.pm[service.pc]^=1;
                service.sport_enabled=service.dac_enabled_=service.sport_irq1_latched=true;
                service.sport_size=service.l[7]=480;
                service.sport_ireg=7; service.sport_incs=1; service.sport_base=0x400;
                service.i[7]=variant==1 || variant==4?0x4f0:0x400;
                if (variant==4) service.main_horizon_=150023965;
                service.sport_transfers.resize(2);
                for (unsigned n=0;n<240;++n) service.external_pm[0x400+n]=(n+1)<<8;
                if (variant) {
                    const auto before=service.ExecutionState();
                    rejected([&] { service.SportTransfer(768000); });
                    check(service.ExecutionState()==before && service.sport_pcm.empty() &&
                          service.SportPacketCount()==2 && service.sport_irq1_events.empty(),
                          "unverified service IRQ2 half, return or opcode rejects before DMA");
                    continue;
                }
                service.SportTransfer(768000);
                check(service.i[7]==0x4f0 && service.sport_pcm.size()==240 &&
                      service.SportPacketCount()==3 && service.dac_bufin_==240 &&
                      !service.sport_irq1_asserted && service.sport_irq1_latched && service.sport_irq1_events.empty(),
                      "qualified FC7C IRQ2 first SPORT half copies without an IRQ1 pulse");
                for (unsigned n=0;n<240;++n) {
                    check(service.sport_pcm[n]==int(n+1) && service.dac_buffer_[n]==int(n+1),
                          "qualified IRQ2 SPORT PCM and DAC match each word");
                }
            }
            for (unsigned variant=0;variant<7;++variant) {
                mk2::DcsLink service_link;
                mk2::AdspBoot service(first_page,service_link,rom);
                service.service_irq_domain_=variant!=6;
                service.rebooted_=true;
                for (const auto address : {0x004,0x130,0x131,0x3e4,0x3e5,0x3e6,0x3e7}) {
                    const auto offset=0x1000+4*address;
                    service.pm[address]=uint32_t(rom[offset])<<16 | uint32_t(rom[offset+1])<<8 | rom[offset+2];
                }
                service.pc=0x3e4; service.mstat=9; service.pc_sp=service.stat_sp=1;
                const uint16_t resume=variant==1?0x130:0x131;
                service.interrupt_={resume,8,0x20,9};
                service.pc_stack_[0]=resume;
                if (variant==2) service.pm[service.pc]^=1;
                if (variant==3) service.pm[resume]^=1;
                if (variant==4) service.pc_sp=2;
                service.sport_enabled=service.dac_enabled_=service.sport_irq1_latched=true;
                service.sport_size=service.l[7]=480;
                service.sport_ireg=7; service.sport_incs=1; service.sport_base=0x400;
                service.i[7]=variant==5?0x400:0x4f0;
                service.sport_transfers.resize(2);
                for (unsigned n=0;n<240;++n) service.external_pm[0x4f0+n]=(0xff00+n)<<8;
                if (variant) {
                    const auto before=service.ExecutionState();
                    rejected([&] { service.SportTransfer(768000); });
                    check(service.ExecutionState()==before && service.sport_pcm.empty() &&
                          service.SportPacketCount()==2 && service.sport_irq1_events.empty(),
                          "unverified service IRQ2 wrap return, opcode, stack, half or DIP rejects before DMA");
                    continue;
                }
                service.SportTransfer(768000);
                check(service.i[7]==0x400 && service.sport_pcm.size()==240 &&
                      service.SportPacketCount()==3 && service.dac_bufin_==240 && service.dac_bufout_==0 &&
                      service.sport_irq1_asserted && service.sport_irq1_latched,
                      "qualified FC7C IRQ2 SPORT wrap copies the second half and asserts IRQ1");
                for (unsigned n=0;n<240;++n) {
                    check(service.sport_pcm[n]==int(n)-256 && service.dac_buffer_[n]==int(n)-256,
                          "qualified IRQ2 SPORT wrap PCM and DAC match each signed word");
                }
                service.Step();
                service.ClearSportIrq1(768010);
                check(!service.sport_irq1_asserted && service.sport_irq1_latched &&
                      service.sport_irq1_events==std::vector<std::vector<uint64_t>>{
                          {768000,0x3e4,0,1},{768010,0x3e5,1,0}},
                      "IRQ1 clears one DSP cycle after the wrap and preserves the latch");
                for (unsigned n=0;n<3;++n) service.Step();
                check(service.pc==0x131 && service.cycles==4 && service.mstat==8 &&
                      service.imask==0x20 && service.astat==9 && !service.pc_sp && !service.stat_sp &&
                      service.sport_irq1_latched,
                      "IRQ2 RTI restores the authenticated idle context after the masked SPORT pulse");
            }
        }
        mk2::DcsLink parallel_link;
        mk2::AdspBoot parallel(boot, parallel_link);
        parallel.rebooted_ = true; parallel.pc = 0x3d3; parallel.pm[0x3d3] = Firmware(0x3d3);
        parallel.ay0 = 0x55aa; parallel.sr0 = 0x5f0f; parallel.ax0 = 0x1234;
        parallel.mstat = 8; parallel.astat = 0xff;
        parallel.Step();
        check(parallel.ar == 0x0aa5 && parallel.ax0 == 0x55aa && parallel.ay0 == 0x55aa &&
              parallel.astat == 0xf0 && parallel.pc == 0x3d4 && parallel.cycles == 1,
              "loaded IRQ parallel ALU and move read original operands with exact flags and one cycle");
        mk2::DcsBootMachine sync(real_boot,u2); std::copy(boot.begin(),boot.end(),sync.dsp.pm.begin());
        sync.link.HostWrite(0x01d01030, 0xff55); sync.link.Synchronize(); sync.link.DspReadInput();
        sync.link.Synchronize();
        auto& timed = sync.dsp;
        timed.rebooted_ = true; timed.pm[4] = Firmware(4);
        timed.pm[0x136] = Firmware(0x136); timed.pm[0x137] = Firmware(0x137); timed.pm[0x138] = Firmware(0x138);
        timed.pm[0x394] = Firmware(0x394); timed.pm[0x395] = Firmware(0x395);
        timed.pm[0x396] = Firmware(0x396); timed.pm[0x397] = Firmware(0x397);
        timed.pc = 0x138; timed.cycles = 31191; timed.imask = 0x20; timed.mstat = 8; timed.astat = 0x6c;
        sync.last_main_ = 815449; sync.dsp_ticks_ = 13047210; sync.target_ticks_ = 13047220;
        sync.main_limit_ = 815451; sync.sliced_ = true; sync.boost_expiry_ticks_ = 13047156;
        sync.next_scanline_ticks_ = 13048000; sync.next_sound_ticks_ = 14000000;
        sync.MainInstruction(815452, true, 0xffaa);
        check(timed.pc == 0x136 && timed.cycles == 31192 && timed.trace.size() == 1 &&
              sync.link.Irq2Asserted() && sync.boost_expiry_ticks_ == 13047684,
              "host synchronization respects existing slice target and stamps boost expiry at bus start");
        sync.MainInstruction(815453); sync.MainInstruction(815456);
        check(timed.pc == 0x398 && timed.cycles == 31197 && timed.trace[1][0] == 4 &&
              timed.trace[1][1] == 31192 && timed.pc_stack_[0] == 0x136,
              "next IRQ enters before an extra ordinary DSP instruction after synchronized host write");
        mk2::DcsBootMachine held(real_boot,u2); std::copy(boot.begin(),boot.end(),held.dsp.pm.begin());
        held.link.HostWrite(0x01d01030, 0xfe00); held.link.Synchronize();
        held.last_main_ = 229; held.dsp_ticks_ = 360; held.target_ticks_ = 410;
        held.main_limit_ = 25; held.sliced_ = true; held.boost_expiry_ticks_ = 820;
        held.MainInstruction(232, true, 0xffff);
        check(held.dsp_ticks_ == 3710 && held.dsp.trace.empty() && held.dsp.cycles == 0 &&
              !held.link.ResetAsserted() && held.target_ticks_ == 3760,
              "reset-held DSP advances suspended clock through release instead of reusing stale quantum");
        boot[0x16e] ^= 1;
        mk2::AdspBoot changed_handler(boot, irq_link); changed_handler.pc = 0x16e;
        before = changed_handler.Registers();
        rejected([&] { changed_handler.Step(); });
        check(changed_handler.Registers() == before && changed_handler.trace.empty(),
              "changed IRQ handler opcode rejects before instruction mutation");
        mk2::AdspBoot unsupported_context(boot, irq_link);
        unsupported_context.pc = 0x45; unsupported_context.imask = 0x20;
        before = unsupported_context.Registers();
        rejected([&] { unsupported_context.Step(); });
        check(unsupported_context.Registers() == before && unsupported_context.trace.empty(),
              "unqualified IRQ context rejects before vector or stack mutation");
        boot[0x38] = BootWord(0x38); boot[0x39] = BootWord(0x39);
        boot[0xf6] = BootWord(0xf6); boot[0xf8] = BootWord(0xf8);
        mk2::AdspBoot mapping(boot, irq_link);
        mapping.pc = 0x38; mapping.i[5] = 0x1000; mapping.m[5] = 1;
        mapping.external_pm[0] = 0x123456;
        mapping.Step();
        check(mapping.ar == 0x1234 && mapping.px == 0x56 && mapping.i[5] == 0x1001 &&
              mapping.accesses.back().space == 'q' && mapping.accesses.back().address == 0x1000,
              "external program aliases preserve the full PM data read and PX");
        mapping.pc = 0x39; mapping.i[4] = 0x1801; mapping.m[6] = 4;
        mapping.ar = 0xabcd; mapping.px = 0xef;
        mapping.Step();
        check(mapping.external_pm[1] == 0xabcdef && mapping.i[4] == 0x1805 &&
              mapping.accesses.back().address == 0x1801, "PM alias write shares canonical external RAM");
        mapping.pc = 0xf6; mapping.si = 1; mapping.Step();
        check(mapping.rom_bank == 1 && mapping.accesses.back().address == 0x3000,
              "original bank selection executes the physical DM write");
        mapping.pc = 0xf8; mapping.si = 0x208;
        before = mapping.Registers();
        const auto before_accesses = mapping.accesses.size();
        rejected([&] { mapping.Step(); });
        check(mapping.Registers() == before && mapping.accesses.size() == before_accesses,
              "software boot rejects missing authenticated ROM before CPU/control mutation");
        mapping.mr2 = 0xff80; mapping.se = 0xfff8; mapping.sb = 0xffff;
        mapping.alternate_.mr2 = 0xff80; mapping.alternate_.se = 0xfff8; mapping.alternate_.sb = 0xffff;
        check(mapping.Registers()[51] == 128 && mapping.Registers()[53] == 248 &&
              mapping.Registers()[54] == 31 && mapping.Registers()[69] == 128 &&
              mapping.Registers()[72] == 248 && mapping.Registers()[73] == 31 &&
              mapping.mr2 == 0xff80 && mapping.se == 0xfff8 && mapping.sb == 0xffff &&
              mapping.alternate_.se == 0xfff8,
              "debugger masks MR2, SE and SB in both banks without changing core storage");
        mk2::AdspBoot zero_count(boot, irq_link);
        zero_count.pc = 0x40;
        zero_count.Step(); zero_count.Step(); zero_count.Step(); zero_count.Step();
        zero_count.cntr = 0; zero_count.Step();
        check(zero_count.pc == 0x45 && zero_count.cntr == 250 && zero_count.loop_sp == 1,
              "CE zero counter exits and restores the outer count like MAME signed decrement");
        mk2::AdspBoot arithmetic(boot, irq_link);
        arithmetic.mstat = 8; arithmetic.astat = 0;
        check(arithmetic.Add(0x7fff, 1, true) == 0x7fff && arithmetic.astat == 6,
              "AR saturation retains unsaturated NZVC");
        check(arithmetic.Sub(0x8000, 1, false) == 0x7fff && arithmetic.astat == 12,
              "AF subtraction does not saturate and carry means no borrow");
        check(arithmetic.Sub(0, 1, true) == 0xffff && arithmetic.astat == 2,
              "subtraction borrow and negative flags");
        check(arithmetic.Negate(0x8000, true) == 0x7fff && arithmetic.astat == 6,
              "negation handles minimum signed word before saturation");
        arithmetic.mstat = 0;
        check(arithmetic.Increment(0xffff, false) == 0 && arithmetic.astat == 9 &&
              arithmetic.Decrement(0, false) == 0xffff && arithmetic.astat == 10,
              "increment and decrement use their original carry conventions");
        arithmetic.mstat = 4; arithmetic.astat = 4;
        check(arithmetic.Add(0, 0, false) == 0 && arithmetic.astat == 5,
              "sticky ALU overflow survives a zero result");
        arithmetic.mstat = 0; arithmetic.astat = 0xbf;
        arithmetic.MacMr(0x8000, 0x8000, true, true, 1, false);
        check(arithmetic.mr2 == 0xffff && arithmetic.mr1 == 0x8000 && arithmetic.mr0 == 0 &&
              arithmetic.astat == 0xbf, "fractional signed product wraps at 32 bits before extending");
        arithmetic.mstat = 0x10;
        arithmetic.MacMr(0xffff, 0xffff, true, false, 1, false);
        check(arithmetic.mr2 == 0xffff && arithmetic.mr1 == 0xffff && arithmetic.mr0 == 1,
              "integer signed-unsigned product");
        arithmetic.MacMr(0xffff, 0xffff, false, false, 1, false);
        check(arithmetic.mr2 == 0xffff && arithmetic.mr1 == 0xfffe && arithmetic.mr0 == 1,
              "integer unsigned product still extends the wrapped signed 32-bit temporary");
        arithmetic.mstat = 0; arithmetic.mr2 = arithmetic.mr1 = 0; arithmetic.mr0 = 1;
        arithmetic.MacMr(1, 0x4000, true, true, 2, true);
        check(arithmetic.mr2 == 0 && arithmetic.mr1 == 0 && arithmetic.mr0 == 1,
              "rounded MAC tie checks product bits rather than accumulated low bits");
        arithmetic.mr0 = 0x8000;
        arithmetic.MacMr(0, 0, true, true, 2, true);
        check(arithmetic.mr1 == 1 && arithmetic.mr0 == 0, "zero product is not a rounding tie");
        arithmetic.mstat = 0x10; arithmetic.mr2 = 0; arithmetic.mr1 = 0x7fff; arithmetic.mr0 = 0xffff;
        arithmetic.MacMr(1, 1, true, true, 2, false);
        check(arithmetic.mr2 == 0 && arithmetic.mr1 == 0x8000 && arithmetic.mr0 == 0 &&
              (arithmetic.astat & 0x40), "MAC overflow detects disagreement with the 32-bit sign");
        const auto before_saturation = arithmetic.astat;
        arithmetic.SaturateMr();
        check(arithmetic.mr2 == 0 && arithmetic.mr1 == 0x7fff && arithmetic.mr0 == 0xffff &&
              arithmetic.astat == before_saturation, "MR saturation preserves MV and all flags");
        arithmetic.mr2 = 0x0100; arithmetic.mr1 = arithmetic.mr0 = 0;
        arithmetic.MacMr(0, 0, true, true, 2, false);
        check(arithmetic.mr2 == 0x0100, "MAC accumulation preserves upper stored MR2 bits");
        for (const auto value : {uint16_t(0), uint16_t(0xffff), uint16_t(1), uint16_t(0x4000), uint16_t(0x8000)}) {
            arithmetic.astat = 0x7f; arithmetic.Exponent(value);
            check(int16_t(arithmetic.se) == (value == 0 || value == 0xffff ? -15 : value == 1 ? -14 : 0) &&
                  arithmetic.astat == ((value & 0x8000) ? 0xff : 0x7f),
                  "EXP counts leading sign bits and changes only SS");
        }
        arithmetic.Exponent(0);
        check(arithmetic.se == 0xfff1 && arithmetic.Registers()[53] == 241,
              "EXP retains signed 16-bit core SE while debugger exposes its low byte");
        arithmetic.rebooted_ = true; arithmetic.pc = 0x8b; arithmetic.pm[0x8b] = Firmware(0x8b);
        arithmetic.Step();
        check(arithmetic.ay0 == 0xfff1 && arithmetic.se == 0xfff1,
              "original AY0 equals SE move consumes the full core word after EXP");
        arithmetic.ShiftLogical(0x8000, -1, false, false);
        check(arithmetic.sr0 == 0x4000 && arithmetic.sr1 == 0, "logical low right shift");
        arithmetic.ShiftLogical(1, 15, true, true);
        check(arithmetic.sr0 == 0x4000 && arithmetic.sr1 == 0x8000, "high OR shift preserves old SR bits");
        arithmetic.ShiftLogical(0xffff, -128, true, false);
        check(arithmetic.sr0 == 0 && arithmetic.sr1 == 0, "large negative shift has no undefined behavior");
        arithmetic.ShiftLogical(0xffff, 127, true, false);
        check(arithmetic.sr0 == 0 && arithmetic.sr1 == 0, "large positive shift has no undefined behavior");
        arithmetic.trace.push_back(arithmetic.Registers());
        arithmetic.mstat = 2; arithmetic.i[0] = 0x400; arithmetic.m[1] = 1;
        arithmetic.external_pm[8] = 0x123456;
        check(arithmetic.ReadDag(0, 1) == 0x1234 && arithmetic.i[0] == 0x401 &&
              arithmetic.accesses.back().address == 8, "DAG1 reverses address bits before the unreversed modifier");
        arithmetic.i[0] = 0x400;
        arithmetic.WriteDag(0, 1, 0xbeef);
        check(arithmetic.external_pm[8] == 0xbeef56 && arithmetic.i[0] == 0x401,
              "reversed data writes preserve the external PM low byte");
        arithmetic.i[4] = 0x400; arithmetic.m[5] = 1; arithmetic.external_pm[0x400] = 0xabcd12;
        check(arithmetic.ReadDag(4, 5) == 0xabcd && arithmetic.i[4] == 0x401 &&
              arithmetic.accesses.back().address == 0x400, "DAG2 never bit-reverses addresses");
        mk2::DcsBootMachine graphics_budget(real_boot,u2); std::copy(boot.begin(),boot.end(),graphics_budget.dsp.pm.begin());
        graphics_budget.last_main_ = 11310681;
        graphics_budget.next_scanline_ticks_ = 180977225;
        graphics_budget.next_sound_ticks_ = 182000000;
        graphics_budget.sport_deadline_ticks_ = 180976570;
        check(graphics_budget.MainBudget(11310681) == 354,
              "FILL restarts at the pending SPORT timer before the next scanline");
        mk2::DcsBootMachine machine(real_boot,u2); std::copy(boot.begin(),boot.end(),machine.dsp.pm.begin());
        machine.dsp.pc = 0x40;
        machine.MainInstruction(5928);
        check(machine.dsp.cycles == 0 && machine.ScanlineEvents() == 0,
              "no DSP catch-up before first timer budget");
        machine.MainInstruction(5929);
        check(machine.dsp.cycles == 9487 && machine.dsp.pc == 0x44 &&
              machine.dsp.cntr == 517 && machine.ScanlineEvents() == 1, "fractional first scanline timer");
        machine.MainInstruction(6325);
        check(machine.dsp.cycles == 10120 && machine.dsp.pc == 0x44 &&
              machine.dsp.cntr == 9890 && machine.ScanlineEvents() == 2, "second scanline and delay exit");
        machine.MainInstruction(100455);
        check(machine.dsp.trace.size() > 150000 && machine.dsp.pc == 0x44 && machine.ScanlineEvents() == 240,
              "bounded long delay trace retained in memory");
        machine.MainInstruction(297193);
        check(machine.MainBudget(297193) == 82,
              "restartable graphics budget ends at the next fractional scanline boundary");
        rejected([&] { machine.MainBudget(297194); });
        check(machine.dsp.trace.size() > 470000 && machine.dsp.trace.size() < 524288 &&
              machine.ScanlineEvents() == 737, "video initialization remains within the complete trace budget");
        machine.MainInstruction(305359);
        check(machine.ScanlineEvents() == 758,
              "bitmap text and CMOS-check frontier retains the complete scanline calendar");
        machine.MainInstruction(379387);
        check(machine.ScanlineEvents() == 945 && machine.dsp.trace.size() > 600000,
              "factory initialization retains every delay iteration through the third frame wrap");
        machine.MainInstruction(399187);
        check(machine.ScanlineEvents() == 995 && machine.dsp.cycles == 638192 &&
              machine.dsp.trace.size() < 655360 && machine.MainBudget(399187) == 78,
              "post-factory status stops before the fourth VTOTAL without changing scanline phase");
        machine.MainInstruction(399321);
        check(machine.ScanlineEvents() == 996 && machine.MainBudget(399321) == 339,
              "sound-command frontier admits the next original scanline and preserves its fractional phase");
        machine.MainInstruction(400774);
        check(machine.ScanlineEvents() == 999 && machine.MainBudget(400774) == 72 &&
              machine.dsp.trace.size() < 655360,
              "partial prompt stops before the next fractional callback without altering the delay");
        rejected([&] { machine.MainInstruction(2173201); });
        mk2::DcsBootMachine overshoot(real_boot,u2); std::copy(boot.begin(),boot.end(),overshoot.dsp.pm.begin());
        overshoot.dsp.pc = 0x40;
        overshoot.MainInstruction(5932);
        check(overshoot.dsp.cycles == 9487 && overshoot.ScanlineEvents() == 1,
              "whole main instruction overshoot does not advance DSP past timer");
        overshoot.MainInstruction(6324);
        check(overshoot.dsp.cycles == 9487, "DSP waits for next timer budget after overshoot");
        overshoot.MainInstruction(6326);
        check(overshoot.dsp.cycles == 10120 && overshoot.ScanlineEvents() == 2,
              "second overshoot respects timer fraction");
        {

    mk2::DcsLink release_link; mk2::AdspBoot d(boot, release_link);
    d.rebooted_=true; d.pc=0x31e; d.pm[0x31e]=Firmware(0x31e);
    d.imask=0; d.mstat=24; d.astat=0xa5; d.cycles=36026450;
    const auto before=d.Registers(); const auto count=d.trace.size();
    d.Step();
    if(d.pc!=0x2e9 || d.cycles!=36026451 || d.astat!=0xa5 || d.mstat!=24 ||
       d.trace.size()!=count+1 || d.trace.back()!=before || !d.accesses.empty()) return 1;
    d.pc=0x8d8; d.external_pm[0xd8]=0x0d0286; d.external_pm[0xda]=0x0d086e;
    d.m[6]=-2; d.sr0=0x3fff; d.Step();
    if(d.si!=0xfffe || d.m[6]!=-2 || d.cycles!=36026452) return 2;
    d.pc=0x8da; d.Step();
    if(d.m[6]!=-1 || d.sr0!=0x3fff || d.astat!=0xa5 || d.cycles!=36026453) return 3;
    d.pc=0x301; d.pm[0x301]=Firmware(0x301); d.i[1]=0x3800; d.m[3]=1; d.l[1]=0;
    d.si=0x1234; d.dm[0]=0xabcd; d.dm[1]=0xef01; d.Step();
    if(d.dm[0]!=0x1234 || d.dm[1]!=0xef01 || d.i[1]!=0x3801 || d.cycles!=36026454 ||
       d.astat!=0xa5 || d.accesses.size()!=1 || d.accesses[0].pc!=0x301 ||
       d.accesses[0].address!=0x3800 || d.accesses[0].value!=0x1234 ||
       d.accesses[0].cycle!=36026453 || d.accesses[0].space!='d') return 4;
    d.pc=0x31e; d.pm[0x31e]=(Firmware(0x31e)&0xfffff0u);
    const auto rejected_state=d.Registers(); const auto rejected_count=d.trace.size();
    bool rejected=false;
    try { d.Step(); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || d.Registers()!=rejected_state || d.trace.size()!=rejected_count) return 5;
        }

        {
            mk2::DcsLink selection_link; mk2::AdspBoot selected(boot, selection_link);
            selected.rebooted_=true;selected.pc=0x9b6;selected.imask=0;selected.astat=0xa5;
            selected.external_pm[0x1b6]=0x3b0004;selected.external_pm[0x1b7]=0x090010;
            selected.external_pm[0x1b8]=0x380004;selected.i[4]=0x123;selected.l[4]=0;selected.m[4]=123;
            selected.Step();
            check(selected.m[4]==-4096 && selected.pc==0x9b7 && selected.cycles==1,"selection original signed14 modifier");
            selected.Step();
            check(selected.i[4]==0x3123 && selected.m[4]==-4096 && selected.cycles==2,"selection DAG wraps14 bits before clearing M4");
            selected.Step();
            check(!selected.m[4] && selected.pc==0x9b9 && selected.cycles==3 && selected.astat==0xa5 &&
                  selected.accesses.empty(),"selection modifier sequence preserves flags and has no memory lane");
            selected.pc=0x9b6;selected.external_pm[0x1b6]=0x3b0005;
            const auto saved=selected.Registers();const auto trace_rows=selected.trace.size();
            rejected([&]{selected.Step();});
            check(selected.Registers()==saved && selected.trace.size()==trace_rows,"changed selection firmware word rejects before mutation");
        }
    } catch (const std::exception& error) { std::cerr << error.what(); return 1; }
}
'''
        compiler = quality.select_compiler(None, "none")
        with quality.scratch_tree() as (scratch, cleanup):
            cpp = scratch / "adsp-delay.cpp"
            cpp.write_text(source, encoding="ascii")
            executable = scratch / "adsp-delay.exe"
            environment = {"PATH": str(compiler.parent) + os.pathsep + os.environ.get("PATH", "")}
            build = quality.command([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-access-control",
                                     "-I" + str(root / "native/mk2"),
                                     "-I" + str(root / "native/include"), cpp,
                                     root / "native/mk2/mk2_adsp.cpp", root / "native/mk2/mk2_dcs.cpp",
                                     root / "native/src/mk5_program.cpp", "-lbcrypt", "-o", executable],
                                    scratch, env=environment)
            self.assertTrue(build["passed"], build.get("stdout", ""))
            roms = root / "roms/mk2"
            rom_args = [roms]  # fixed DSP words and context guards read the user's U2
            result = quality.command([executable, *rom_args], scratch, env=environment)
            self.assertTrue(result["passed"], result.get("stdout", ""))
        self.assertFalse(cleanup["exists_after"])


if __name__ == "__main__":
    unittest.main()
