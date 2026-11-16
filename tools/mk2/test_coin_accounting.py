"""Original coin accounting endpoint admission and translation controls."""
from pathlib import Path
import sys
import unittest
import os
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import run
from tools.mk2 import reference
from tools.mk2 import generate_video_irq as shared
from tools.quality import run as quality


class CoinAccountingTests(unittest.TestCase):
    def test_byte_lanes_use_pinned_instruction_fetch_widths(self):
        for pc,word,bits,address,write in (
                (0xffa51ad0,0x8c2a,16,0x010b9810,True),
                (0xffa54ad0,0xaf43,32,0x010b9830,False)):
            words={pc:word,pc+16:0x20}
            try:
                lane=reference.dispatcher_bus_row(pc+bits,address,0x80,12,16,pc,write,words.__getitem__)
            except ValueError as error:
                self.fail('Pinned byte instruction rejected: '+str(error))
            self.assertEqual(lane,[119 if write else 114,pc,address,0x80,12,16])
            self.assertIsNone(reference.dispatcher_bus_row(pc+16,pc,word,12,16,pc,False,words.__getitem__))
            if bits==32:
                self.assertIsNone(reference.dispatcher_bus_row(pc+32,pc+16,0x20,12,16,pc,False,words.__getitem__))

    def test_original_byte_store_and_offset_load_preserve_bus_flags_and_cycles(self):
        try:
            store=shared.emit_instruction(0x100,16,'MOVB A1,*A10',(0x8c2a,),{0x110},{})
            load=shared.emit_instruction(0x110,32,'MOVB *A10(20h),A3',(0xaf43,0x20),{0x130},{})
        except ValueError as error:
            self.fail('Required original byte operand rejected: '+str(error))
        source=r'''
#include "native/mk2/mk2_boot_ops.hpp"
#include <memory>
int main() {
    mk2::Program program;
    auto machine=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
    machine->link.HostWrite(0x01d01020,0); machine->link.Synchronize();
    auto out=std::make_unique<mk2::BootContinuation>(); out->main_ram.resize(262144);
    auto& s=out->ready; s.board.io[8]=0x2000;
    s.next_pc=0x100; s.status=0x71230048; s.a[1]=0x1ab; s.a[10]=0x01000008;
    out->main_ram[0]=0x1234; out->main_ram[2]=0x80cd;
    mk2::BootOps o(program,*machine,*out);
''' + store + r'''
    if(out->main_ram[0]!=0xab34 || s.cycles!=1 || s.status!=0x71230048 ||
       out->bus.size()!=2 || out->bus[0].value!=0x1234 || out->bus[1].value!=0xab34) return 1;
''' + load + r'''
    if(s.a[3]!=0xffffff80 || s.cycles!=6 || s.status!=0xc1230048 || s.next_pc!=0x130 ||
       out->bus.size()!=3 || out->bus.back().address_bit!=0x01000020 ||
       out->bus.back().value!=0x80cd || out->main_ram[2]!=0x80cd) return 2;
}
'''
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'bytes.cpp';path.write_text(source)
            executable=scratch/'bytes.exe'
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([quality.DEFAULT_CC,'-std=c++17','-Wall','-Wextra','-Werror',
                '-I'+str(quality.ROOT),'-I'+str(quality.ROOT/'native/include'),path,
                quality.ROOT/'native/mk2/mk2_adsp.cpp',quality.ROOT/'native/mk2/mk2_dcs.cpp',
                quality.ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',executable],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            execution=quality.command([executable],scratch,env=env)
            self.assertTrue(execution['passed'],execution['stdout'])
        self.assertFalse(cleanup['exists_after'])

    def test_accounting_requires_batch_before_rom_access(self):
        try:
            run.run('reset',Path('missing-mk2-directory'),coin_accounting=True)
        except Exception as error:
            self.assertIsInstance(error,ValueError)
        else:
            self.fail('accounting accepted without batch observations')

    def test_accounting_rejects_other_endpoints_before_rom_access(self):
        for endpoint in ('coin_queue','larger_batch','next_batch','extended_batch'):
            with self.subTest(endpoint=endpoint):
                try:
                    run.run('reset',Path('missing-mk2-directory'),batch=True,
                            coin_accounting=True,**{endpoint:True})
                except Exception as error:
                    self.assertIsInstance(error,ValueError)
                else:
                    self.fail('accounting accepted another endpoint')


if __name__=='__main__':unittest.main()
