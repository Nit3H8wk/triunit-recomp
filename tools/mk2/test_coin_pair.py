"""Two-pulse continuation and external INT1 physical-entry controls."""
from copy import deepcopy
import os
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import batch_reference as reference
from tools.mk2 import generate_video_irq as generated
from tools.mk2 import physical_fetch
from tools.quality import run as quality


class ExternalIrqTests(unittest.TestCase):
    # Synthetic CPU state at the Original INT1 bracket (PCs, cycles, opcode words and vector are kept): ST, SP, the
    # MMFM-loaded A3/A8 and the RAM read are sentinels; the stack lanes follow from SP and ST.
    ST, SP, A3, A8, READ = 0x50200015, 0x01234560, 0x01236a90, 0x5a5, 0x2c71

    def context(self):
        before = [0xff804110, self.ST, 4003711] + [0] * 31
        before[18] = self.SP + 64
        after = [0xff8045d0, 0x10, 4003754] + [0] * 31
        after[6], after[11], after[18] = self.A3, self.A8, self.SP
        # MMFM fetches and ordinary reads precede the six asynchronous lanes.
        lanes = [[0xff804120, 0xff804110, 0x09a3, 4003711, 16, 0xff804110, False],
                 [0xff804130, 0xff804120, 0x1bc0, 4003711, 16, 0xff804110, False],
                 [0xff804130, self.A3 - 0xc0, self.READ, 4003711, 16, 0xff804110, False]]
        for address, value, write in (
                (self.SP + 32, 0x4130, True), (self.SP + 48, 0xff80, True),
                (self.SP, self.ST & 0xffff, True), (self.SP + 16, self.ST >> 16, True),
                (0xffffffc0, 0x45d0, False), (0xffffffd0, 0xff80, False)):
            lanes.append([0xff804130, address, value, 4003711, 16, 0xff804110, write])
        return before, after, lanes, (87585, 0xff804130, 0)

    def test_typed_partition_consumes_irq_once_and_preserves_ordinary_mmfm_read(self):
        before,after,lanes,note=self.context()
        decoded={before[0]:(32,0,(0x09a3,0x1bc0),'MMFM A3,A0')}
        words={before[0]:0x09a3,before[0]+16:0x1bc0,0xffffffc0:0x45d0,0xffffffd0:0xff80}
        note=(0,note[1],note[2])
        data,counts=physical_fetch.partition(lanes,[before],after,decoded,words.__getitem__,[note])
        self.assertEqual(counts,{'physical':9,'fetch':2,'data':7,'irq':6})
        self.assertEqual(data[0],[114,0xff804110,self.A3-0xc0,self.READ,4003711,16])
        for notes in ([],[note,note],[(0,note[1],1)],[(False,note[1],0)]):
            with self.subTest(notes=notes),self.assertRaises(ValueError):
                physical_fetch.partition(lanes,[before],after,decoded,words.__getitem__,notes)
        for index in (0,1,-1):
            changed=deepcopy(lanes);changed[index][2]^=1
            with self.subTest(index=index),self.assertRaises(ValueError):
                physical_fetch.partition(changed,[before],after,decoded,words.__getitem__,[note])
        changed=deepcopy(lanes);changed[2][2]=0x1234
        changed_data,_=physical_fetch.partition(changed,[before],after,decoded,words.__getitem__,[note])
        self.assertEqual(changed_data[0][3],0x1234)  # Full native comparison owns data values.

    def test_skipped_conditional_parameter_and_dsj_zero_exit_are_still_authenticated(self):
        for asm,status,reg in [('JREQ 200h',0x30,None),('DSJ A2,200h',0x30,5)]:
            before=[0x100,status,100]+[0]*31
            if reg is not None: before[reg]=1
            after=list(before);after[:3]=0x120,status,102
            if reg is not None: after[reg]=0
            decoded={0x100:(32,0,(0x0d82 if reg else 0xca00,0x10),asm)}
            opcode=lambda pc: decoded[0x100][2][(pc-0x100)//16]
            lanes=[[0x110,0x100,opcode(0x100),100,16,0x100,False]]
            data,counts=physical_fetch.partition(lanes,[before],after,decoded,opcode,[])
            self.assertEqual((data,counts['fetch']),([],1))
            with self.assertRaises(ValueError):
                physical_fetch.partition(lanes+[[0x110,0x110,0x10,100,16,0x100,False]],
                                         [before],after,decoded,opcode,[])
            if reg is not None:
                after[reg]=1
                with self.assertRaises(ValueError):
                    physical_fetch.partition(lanes,[before],after,decoded,opcode,[])

    def test_entry_recovers_post_instruction_state_without_consuming_normal_lanes(self):
        args = self.context()
        original = deepcopy(args)
        post = reference.external_irq_bracket(*args)
        self.assertEqual(post[:3], [0xff804130, self.ST, 4003738])
        self.assertEqual((post[6], post[11], post[18]), (self.A3, self.A8, self.SP + 64))
        self.assertEqual(args, original)

    def test_irq_lane_structure_return_pc_vector_and_order_are_authenticated(self):
        before, after, lanes, note = self.context()
        for index in range(len(lanes)-6, len(lanes)):
            for field in range(7):
                # Saved ST is measured here; native instruction equivalence checks its value.
                if field == 2 and index in (len(lanes)-4, len(lanes)-3):
                    continue
                changed = deepcopy(lanes)
                changed[index][field] ^= 1
                with self.subTest(index=index, field=field), self.assertRaises(ValueError):
                    reference.external_irq_bracket(before, after, changed, note)
        for changed in (lanes[:-1], lanes[:-6]+list(reversed(lanes[-6:]))):
            with self.assertRaises(ValueError):
                reference.external_irq_bracket(before, after, changed, note)
        lanes[-3][2] = 0
        with self.assertRaises(ValueError):
            reference.external_irq_bracket(before, after, lanes, note)

    def test_rejects_wrong_handler_status_clock_stack_and_annotation(self):
        before, after, lanes, note = self.context()
        for field, value in ((0, 0xff816370), (1, 0x30), (2, 4003727), (18, self.SP + 1)):
            changed = list(after); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                reference.external_irq_bracket(before, changed, lanes, note)
        with self.assertRaises(ValueError):
            reference.external_irq_bracket(before, after, lanes, (87585, 0xff804140, 0))
        with self.assertRaises(ValueError):
            reference.external_irq_bracket(before, after, lanes, (87585, 0xff804130, 1))


class PairWindowTests(unittest.TestCase):
    def windows(self):
        first={key:[] for key in reference.ARRAY_KEYS}
        second={key:[] for key in reference.ARRAY_KEYS}
        first.update(batch_cpu=[[0xff80dd30,0x30,3658091]],batch_final_cpu=[0xff808010,0x30,4341320],
                     batch_inputs=[[1,0,0xffff,2]],batch_dsp_accesses=[[1],[2]],batch_dma_positions=[1])
        second.update(batch_cpu=[[0xff808010,0x30,4341320]],batch_final_cpu=[0xff80dd30,0x30,5077311],
                      batch_inputs=[[1,0,0xffff,2],[2,1,0xfffe,3]],batch_dsp_accesses=[[3]],batch_dma_positions=[0],
                      batch_vram=[0x1234])
        return first,second

    def test_join_retains_every_row_and_offsets_dma_access_indices(self):
        first,second=self.windows()
        joined=reference.join_pair_windows(first,second)
        self.assertEqual(joined['batch_cpu'],[[0xff80dd30,0x30,3658091],[0xff808010,0x30,4341320]])
        self.assertEqual(joined['batch_dsp_accesses'],[[1],[2],[3]])
        self.assertEqual(joined['batch_dma_positions'],[1,2])
        self.assertEqual(joined['batch_final_cpu'],second['batch_final_cpu'])
        self.assertEqual(joined['batch_vram'],[0x1234])

    def test_join_rejects_gap_overlap_or_inconsistent_input_prefix(self):
        for field in ('cycle','pc','input','empty'):
            first,second=self.windows()
            if field=='cycle': second['batch_cpu'][0][2]+=1
            if field=='pc': second['batch_cpu'][0][0]+=16
            if field=='input': second['batch_inputs'][0][2]^=1
            if field=='empty': second['batch_cpu']=[]
            with self.subTest(field=field),self.assertRaises(ValueError):
                reference.join_pair_windows(first,second)


class CoinPairPrimitiveTests(unittest.TestCase):
    def compile_and_run(self, body):
        source = r'''
#include "native/mk2/mk2_boot_ops.hpp"
#include <memory>
#include <iostream>
int main() { try {
    mk2::Program program;
    auto machine=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
    machine->link.HostWrite(0x01d01020,0); machine->link.Synchronize();
    auto out=std::make_unique<mk2::BootContinuation>(); out->main_ram.resize(262144);
    auto& s=out->ready; s.board.io[8]=0x2000;
    mk2::BootOps o(program,*machine,*out);
''' + body + '\n} catch(const std::exception& error) { std::cerr << error.what(); return 99; } }\n'
        with quality.scratch_tree() as (scratch, cleanup):
            path=scratch/'pair.cpp'; path.write_text(source)
            executable=scratch/'pair.exe'
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([quality.DEFAULT_CC,'-std=c++17','-Wall','-Wextra','-Werror',
                '-I'+str(quality.ROOT),'-I'+str(quality.ROOT/'native/include'),path,
                quality.ROOT/'native/mk2/mk2_adsp.cpp',quality.ROOT/'native/mk2/mk2_dcs.cpp',
                quality.ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',executable],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            execution=quality.command([executable],scratch,env=env)
            self.assertTrue(execution['passed'],execution)
        self.assertFalse(cleanup['exists_after'])

    def emit(self, asm, size=16, successors=None):
        try:
            return '{\n'+generated.emit_instruction(0x100,size,asm,(0,)*(size//16),
                {0x100,0x110,0x120,0x130,0x200},successors or {})+'\n}\n'
        except ValueError as error:
            self.fail('Measured two-pulse instruction rejected: '+str(error))

    def test_cold_machine_cannot_admit_the_pair_or_change_default_board_bounds(self):
        self.compile_and_run(r'''
    const auto before=machine->dsp.Registers();
    bool rejected=false;
    try { machine->AdmitCoinPair(s.board); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->CoinPairAdmitted() || s.board.CoinPairAdmitted() ||
       machine->LastMainCycles() || machine->dsp.Registers()!=before) return 1;
    rejected=false;
    try { s.board.WriteIo(17,0x406); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || s.board.io[17]) return 2;
    rejected=false;
    try { machine->MainInstruction(3658092); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->LastMainCycles()) return 3;
''')

    def test_new_arithmetic_xy_and_byte_forms_execute_real_primitives(self):
        body='s.status=0x70200030; s.a[1]=0x12345678; s.a[2]=0xabcd9012;\n'
        body+=self.emit('MOVY A1,A2')
        body+='if(s.a[2]!=0x12349012 || s.status!=0x70200030 || s.cycles!=1) return 1;\n'
        body+='s.a[1]=0x00010001; s.a[2]=0x80008000;\n'+self.emit('CMPXY A1,A2')
        body+='if(s.a[2]!=0x80008000 || s.status!=0x00200030 || s.cycles!=2) return 2;\n'
        body+='s.a[1]=s.a[2];\n'+self.emit('CMPXY A1,A2')
        body+='if(s.status!=0xa0200030 || s.cycles!=3) return 3;\n'
        body+='s.a[8]=4;\n'+self.emit('SUBK 8h,A8')
        body+='if(s.a[8]!=0xfffffffc || s.status!=0xc0200030 || s.cycles!=4) return 4;\n'
        body+=self.emit('CLRC')+'if(s.status!=0x80200030 || s.cycles!=5) return 5;\n'
        body+=self.emit('SETC')+'if(s.status!=0xc0200030 || s.cycles!=6) return 6;\n'
        body+='s.a[8]=0x01000008; s.a[7]=0x01000020; out->main_ram[0]=0x80ff; out->main_ram[2]=0x1234;\n'
        body+=self.emit('MOVB *A8,*A7')
        body+='if(out->main_ram[2]!=0x1280 || s.status!=0xc0200030 || s.cycles!=9 || out->bus.size()!=3) return 7;\n'
        body+='s.a[0]=0xab;\n'+self.emit('MOVB A0,@1000038h',48)
        body+='if(out->main_ram[3]!=0xab00 || s.status!=0xc0200030 || s.cycles!=10) return 8;\n'
        self.compile_and_run(body)

    def test_signed_multiply_and_unsigned_divide_preserve_original_flags_pairs_and_cycles(self):
        body='s.status=0x50000030; s.a[0]=0xfffffffd; s.a[4]=2;\n'+self.emit('MPYS A0,A4')
        body+='if(s.a[4]!=0xffffffff || s.a[5]!=0xfffffffa || s.status!=0xd0000030 || s.cycles!=20) return 1;\n'
        body+='s.a[5]=2;\n'+self.emit('MPYS A0,A5')
        body+='if(s.a[5]!=0xfffffffa || s.status!=0xd0000030 || s.cycles!=40) return 2;\n'
        body+='s.a[1]=3; s.a[8]=1; s.a[9]=0;\n'+self.emit('DIVU A1,A8')
        body+='if(s.a[8]!=0x55555555 || s.a[9]!=1 || s.status!=0xc0000030 || s.cycles!=77) return 3;\n'
        body+='s.a[1]=0;\n'+self.emit('DIVU A1,A8')
        body+='if(s.a[8]!=0x55555555 || s.a[9]!=1 || s.status!=0xd0000030 || s.cycles!=114) return 4;\n'
        body+='s.a[1]=2; s.a[8]=3; s.a[9]=0;\n'+self.emit('DIVU A1,A8')
        body+='if(s.a[8]!=3 || s.a[9]!=0 || s.status!=0xd0000030 || s.cycles!=151) return 5;\n'
        body+='s.a[8]=0; s.a[9]=1;\n'+self.emit('DIVU A1,A8')
        body+='if(s.a[8]!=0 || s.a[9]!=1 || s.status!=0xe0000030 || s.cycles!=188) return 6;\n'
        self.compile_and_run(body)

    def test_indirect_calls_exchange_branches_and_new_context_bases_execute(self):
        body='s.next_pc=0x100; s.status=0x00200030; s.a[15]=0x01000100; s.a[2]=0x20f;\n'
        body+=self.emit('CALL A2',successors={0x100:(0x200,)})
        body+='if(s.next_pc!=0x200 || s.a[15]!=0x010000e0 || o.PeekStack()!=0x110 || s.cycles!=3) return 1;\n'
        body+='s.next_pc=0x100; s.a[7]=0x20f;\n'+self.emit('EXGPC A7',successors={0x100:(0x200,)})
        body+='if(s.next_pc!=0x200 || s.a[7]!=0x110 || s.cycles!=5 || s.status!=0x00200030) return 2;\n'
        for number,(asm,status,target,cost) in enumerate((('JRNV 200h',0x30,0x200,3),
                ('JRNV 200h',0x10000030,0x120,2),('JRP 200h',0x30,0x200,3),
                ('JRP 200h',0x20000030,0x120,2),('JRLS 200h',0x40000030,0x200,3),
                ('JRLS 200h',0x30,0x120,2),('JAC 200h',0x40000030,0x200,3))):
            size=48 if asm.startswith('JAC') else 32
            body+=f's.next_pc=0x100; s.status={status}u; const auto cycle{number}=s.cycles;\n'
            body+=self.emit(asm,size,{0x100:(0x200,0x120,0x130)})
            body+=f'if(s.next_pc!={target} || s.cycles!=cycle{number}+{cost}) return {number+3};\n'
        body+='s.a[12]=0x01000200; s.a[1]=0x12345678; s.a[3]=0x89abcdef;\n'
        body+=self.emit('MMTM A12,A1,A3',32)
        body+='if(s.a[12]!=0x010001c0 || out->main_ram[28]!=0xcdef || out->main_ram[30]!=0x5678) return 11;\n'
        body+='s.a[8]=s.a[12]; s.a[1]=s.a[3]=0;\n'+self.emit('MMFM A8,A1,A3',32)
        body+='if(s.a[1]!=0x12345678 || s.a[3]!=0x89abcdef || s.a[8]!=0x01000200) return 12;\n'
        self.compile_and_run(body)

    def test_rets_corrects_low_pc_bits_before_fixed_successor_admission(self):
        self.compile_and_run(r'''
    s.next_pc=0xff804650; s.a[15]=0x01000100; s.board.io[8]=0x2000;
    o.Push(0xff80450f); out->bus.clear();
    o.RetsAllowed({0xff804500});
    if(s.next_pc!=0xff804500 || s.a[15]!=0x01000100 || s.cycles!=7 ||
       out->bus.size()!=2 || out->bus[0].value!=0x450f) return 1;
''')

    def test_unaligned_long_field_preserves_original_four_read_four_write_lanes(self):
        self.compile_and_run(r'''
    s.status=0x30; s.next_pc=0xffa4e8c0;
    out->main_ram[0]=0x1122; out->main_ram[1]=0x3344;
    out->main_ram[2]=0x5566; out->main_ram[3]=0x7788;
    o.WriteField(0x01000008,0xaabbccdd,1);
    if(out->main_ram[0]!=0xdd22 || out->main_ram[1]!=0xbbcc ||
       out->main_ram[2]!=0x55aa || out->main_ram[3]!=0x7788 || out->bus.size()!=8) return 1;
    for(unsigned n=0;n<8;++n) {
        const auto& lane=out->bus[n];
        if(lane.address_bit!=0x01000000+(n%4)*16 || lane.kind!=(n<4?'r':'w') ||
           lane.pc!=0xffa4e8c0 || lane.cycle) return 2;
    }
    out->bus.clear();
    if(o.ReadField(0x01000008,1)!=0xaabbccdd || out->bus.size()!=4 ||
       out->bus.back().address_bit!=0x01000030) return 3;
''')

    def test_cross_word_field_uses_two_word_rmw_and_original_sign_extension(self):
        self.compile_and_run(r'''
    s.status=0x400; s.next_pc=0xffa2d440;
    out->main_ram[0]=0x1122; out->main_ram[1]=0x3344;
    o.WriteField(0x01000008,0xaabb,1);
    if(out->main_ram[0]!=0xbb22 || out->main_ram[1]!=0x33aa || out->bus.size()!=4) return 1;
    for(unsigned n=0;n<4;++n)
        if(out->bus[n].kind!=(n<2?'r':'w') || out->bus[n].address_bit!=0x01000000+(n%2)*16) return 2;
    out->bus.clear();
    if(o.ReadField(0x01000008,1)!=0xaabb || out->bus.size()!=2) return 3;
    s.status|=0x800;
    if(o.ReadField(0x01000008,1)!=0xffffaabb || out->bus.size()!=4) return 4;
''')

    def test_byte_moves_keep_bit_addressing_and_cross_word_physical_order(self):
        self.compile_and_run(r'''
    out->main_ram[0]=0x1122; out->main_ram[1]=0x3344;
    if(o.Read8(0x0100000c)!=0x41 || out->bus.size()!=2) return 1;
    out->bus.clear(); o.WriteByte(0x0100000c,0x1ab);
    if(out->main_ram[0]!=0xb122 || out->main_ram[1]!=0x334a || out->bus.size()!=4) return 2;
    for(unsigned n=0;n<4;++n)
        if(out->bus[n].kind!=(n<2?'r':'w') || out->bus[n].address_bit!=0x01000000+(n%2)*16) return 3;
    if(o.Read8(0x0100000c)!=0xab) return 4;
''')

    def test_all_field_offsets_match_pinned_macros_in_values_and_physical_lanes(self):
        self.compile_and_run(r'''
#include "docs/investigation/decoder-research/upstream/34010ops.h"
    struct Reference {
        std::array<uint16_t,8> ram{};
        std::vector<std::array<uint32_t,3>> bus;
        uint32_t TMS34010_RDMEM_WORD(uint32_t a) {
            const auto value=ram.at((a-0x01000000)/16);bus.push_back({'r',a,value});return value;
        }
        uint32_t TMS34010_RDMEM_DWORD(uint32_t a) {
            const auto low=TMS34010_RDMEM_WORD(a);return low|(TMS34010_RDMEM_WORD(a+16)<<16);
        }
        void TMS34010_WRMEM_WORD(uint32_t a,uint32_t value) {
            ram.at((a-0x01000000)/16)=uint16_t(value);bus.push_back({'w',a,uint16_t(value)});
        }
        void TMS34010_WRMEM_DWORD(uint32_t a,uint32_t value) {
            TMS34010_WRMEM_WORD(a,value);TMS34010_WRMEM_WORD(a+16,value>>16);
        }
        uint32_t read(uint32_t offset,unsigned width) {
            uint32_t ret;
            if(width==32) { RFIELDMAC_32(); }
            else if(width==16) { RFIELDMAC(0xffff,1); }
            else if(width==8) { RFIELDMAC_8(); }
            else if(width==6) { RFIELDMAC(0x3f,11); }
            else { RFIELDMAC(1,16); }
            return ret;
        }
        void write(uint32_t offset,uint32_t data,unsigned width) {
            if(width==32) { WFIELDMAC_32(); }
            else if(width==16) {
                if(offset&15) { WFIELDMAC(0xffff,1); }
                else TMS34010_WRMEM_WORD(offset,data);
            } else if(width==8) { WFIELDMAC_8(); }
            else if(width==6) { WFIELDMAC(0x3f,11); }
            else { WFIELDMAC(1,16); }
        }
    } ref;
    for(unsigned width:{1u,6u,8u,16u,32u}) for(unsigned shift=0;shift<16;++shift) {
        for(unsigned n=0;n<8;++n) out->main_ram[n]=ref.ram[n]=uint16_t(0x1357+n*0x1111);
        out->bus.clear();ref.bus.clear();s.status=(width==32?0:width)<<6;
        const uint32_t address=0x01000000+shift,value=0x8badf00du+shift;
        ref.write(address,value,width);o.WriteField(address,value,1);
        if(out->bus.size()!=ref.bus.size()) return 1;
        for(unsigned n=0;n<8;++n) if(out->main_ram[n]!=ref.ram[n]) return 2;
        auto check_lanes=[&] {
            if(out->bus.size()!=ref.bus.size()) return false;
            for(unsigned n=0;n<ref.bus.size();++n) {
                const auto& a=out->bus[n];const auto& b=ref.bus[n];
                if(uint32_t(a.kind)!=b[0] || a.address_bit!=b[1] || a.value!=b[2]) return false;
            }
            return true;
        };
        if(!check_lanes()) return 3;
        out->bus.clear();ref.bus.clear();
        if(o.ReadField(address,1)!=ref.read(address,width) || !check_lanes()) return 4;
        if(width==8) {
            out->bus.clear();ref.bus.clear();
            if(o.Read8(address)!=ref.read(address,8) || !check_lanes()) return 5;
            out->bus.clear();ref.bus.clear();
            o.WriteByte(address,0x123456ab);ref.write(address,0x123456ab,8);
            if(!check_lanes()) return 6;
            for(unsigned n=0;n<8;++n) if(out->main_ram[n]!=ref.ram[n]) return 7;
        }
    }
''')

    def test_native_irq_admission_uses_board_masks_priority_and_original_vector(self):
        self.compile_and_run(r'''
    program.bytes.resize(0x100000);
    for(auto pair : {std::pair<uint32_t,uint32_t>{0xffffffc0,0xff8045d0},
                     std::pair<uint32_t,uint32_t>{0xfffffea0,0xff816370}}) {
        const auto n=(pair.first-0xff800000)/8;
        for(unsigned k=0;k<4;++k) program.bytes[n+k]=uint8_t(pair.second>>(k*8));
    }
    // Synthetic ST and SP at the Original PCs.
    s.next_pc=0xff804110; s.status=0x50200015; s.a[15]=0x012345a0;
    s.board.io[17]=6; s.board.io[18]=2;
    o.Finish(0xff804130,27);
    if(!o.PendingInterrupt() || s.next_pc!=0xff8045d0 || s.status!=0x10 ||
       s.cycles!=43 || s.instructions!=1 || s.a[15]!=0x01234560 || out->bus.size()!=6) return 1;
    if(out->bus[0].pc!=0xff804110 || out->bus[0].cycle!=0 ||
       out->bus[0].address_bit!=0x01234580 || out->bus[0].value!=0x4130 ||
       out->bus[2].address_bit!=0x01234560 || out->bus[3].value!=0x5020 ||
       out->bus[4].address_bit!=0xffffffc0 || out->bus[5].value!=0xff80) return 2;
    if(o.PendingInterrupt() || s.cycles!=43 || out->bus.size()!=6) return 3;
    s.status=0x50200015; s.a[15]=0x012345a0;
    s.board.io[17]=0x0406; s.board.io[18]=0x0402;
    o.Finish(0xff804130,3);
    if(!o.PendingInterrupt() || s.next_pc!=0xff816370 || s.cycles!=62 ||
       out->bus[out->bus.size()-2].address_bit!=0xfffffea0) return 4;
    s.status=0x50200015; s.board.io[17]=4; s.board.io[18]=2;
    if(o.PendingInterrupt() || s.cycles!=62) return 5;
    s.board.io[17]=6; s.a[15]=0x01000020;
    bool rejected=false;
    try { o.PendingInterrupt(); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || s.a[15]!=0x01000020 || s.status!=0x50200015 || s.cycles!=62) return 6;
''')

    def test_dsp_observation_windows_preserve_execution_count_state_and_access_source(self):
        self.compile_and_run(r'''
    std::vector<uint32_t> boot(376);
    boot[0]=0x18022f; boot[0x22]=0x400108; boot[0x23]=0x93fff8;
    mk2::DcsLink first_link,second_link;
    mk2::AdspBoot first(boot,first_link),second(boot,second_link);
    first.Step(); second.Step(); first.Step(); second.Step();
    const auto state=second.Registers();
    second.DiscardObservedTrace();
    if(second.Registers()!=state || second.InstructionCount()!=2 || !second.trace.empty()) return 1;
    first.Step(); second.Step();
    if(first.Registers()!=second.Registers() || second.InstructionCount()!=3 ||
       second.trace.size()!=1 || first.trace[2]!=second.trace[0]) return 2;
    const auto count=second.InstructionCount();
    bool rejected=false;
    try { second.Step(); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || second.InstructionCount()!=count || second.trace.size()!=1) return 3;
''')


if __name__ == '__main__':
    unittest.main()
