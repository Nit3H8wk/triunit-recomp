"""Architectural PC transfers, independent of observed source/target pairs."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as g
from tools.mk2 import test_coin_pair


class ArchitecturalDispatchTests(unittest.TestCase):
    compile_and_run = test_coin_pair.CoinPairPrimitiveTests.compile_and_run

    def test_all_branch_conditions_preserve_isa_truth_table_and_costs(self):
        from tools.mk2.generate_static_cfg import direct_targets
        # Literal truth masks indexed by N,C,Z,V: pinned34010ops predicates.
        conditions=(('',0xffff),('P',0x0033),('LS',0xfcfc),('HI',0x0303),('LT',0x55aa),
                    ('GE',0xaa55),('LE',0xddee),('GT',0x2211),('C',0xf0f0),
                    ('NC',0x0f0f),('EQ',0xcccc),('NE',0x3333),('V',0xaaaa),
                    ('NV',0x5555),('N',0xff00),('NN',0x00ff))
        body=''
        for condition,(suffix,truth) in enumerate(conditions):
            base=0xc000 | condition<<8
            for form,words,operand,target,take,skip in (
                    ('JR',(base | 7,),0x180,0x180,2,1),
                    ('JR',(base | 0xfd,),0xe0,0xe0,2,1),
                    ('JR',(base,7),0x190,0x190,3,2),
                    ('JR',(base,0xfffd),0xf0,0xf0,3,2),
                    ('JA',(base | 0x80,0x20d,0),0x20d,0x200,3,4)):
                size=len(words)*16
                next_pc=0x100+size
                asm=f'{form}{suffix} {operand:X}h'
                targets=(target,) if not suffix else tuple(sorted((target,next_pc)))
                self.assertEqual(direct_targets(0x100,size,asm,0xff8045d0),targets)
                code=g.emit_instruction(0x100,size,asm,words,{next_pc,target},{})
                body+='for(unsigned flags=0;flags<16;++flags){\n'
                body+='s.next_pc=0x100;s.status=(flags<<28)|0x00200030;const auto status=s.status;const auto cycles=s.cycles;\n'
                body+=code+'\n'
                body+=f'const bool taken=(0x{truth:04x}u>>flags)&1;\n'
                body+=(f'if(s.next_pc!=(taken?0x{target:x}u:0x{next_pc:x}u)||'
                       f's.cycles!=cycles+(taken?{take}:{skip})||s.status!=status)return 1;\n}}\n')
        self.compile_and_run(body)

    def test_absolute_call_masks_target_and_pushes_encoded_return(self):
        from tools.mk2.generate_static_cfg import direct_targets
        asm='CALLA 20Dh'
        self.assertEqual(direct_targets(0x100,48,asm,0xff8045d0),(0x200,))
        code=g.emit_instruction(0x100,48,asm,(0x0d5f,0x020d,0),{0x200},{})
        self.compile_and_run(r'''
    s.next_pc=0x100;s.a[15]=0x01000040;s.status=0x30;
    const auto cycles=s.cycles;
''' + code + r'''
    if(s.next_pc!=0x200 || s.cycles!=cycles+4 || s.status!=0x30 ||
       s.a[15]!=0x01000020 || o.Read32(s.a[15])!=0x130)return 1;
''')

    def test_authenticated_jan_both_outcomes_and_cycles(self):
        from tools.mk2.offline_decode import decode
        rom=g.load_program(g.ROOT/'roms/mk2')
        rows,_=decode(rom,[0xff9b3d60])
        size,_,words,asm=rows[0xff9b3d60]
        self.assertEqual((size,asm.split()),(48,['JAN','FF8BDDE0h']))
        code=g.emit_instruction(0xff9b3d60,size,asm,words,{0xff9b3d90,0xff8bdde0},{})
        # Pinned j_N_8/j_xx_8: absolute N branch costs3 taken,4 not taken.
        self.compile_and_run(r'''
    for(unsigned flags=0;flags<16;++flags) {
        const uint32_t status=(flags<<28)|0x00200030;
        s.next_pc=0xff9b3d60;s.status=status;
        const auto cycles=s.cycles;const auto instructions=s.instructions;
        const auto a=s.a;const auto b=s.b;const auto ram=out->main_ram;
        const auto cmos=s.cmos;const auto io=s.board.io;
        const auto palette=out->video.palette_ram;const auto vram=out->video.vram;
        const auto bus=out->bus.size();
''' + code + r'''
        if(s.next_pc!=((flags&8)?0xff8bdde0u:0xff9b3d90u) ||
           s.cycles!=cycles+((flags&8)?3:4) || s.instructions!=instructions+1 ||
           s.status!=status || s.a!=a || s.b!=b || out->main_ram!=ram || s.cmos!=cmos ||
           s.board.io!=io || out->video.palette_ram!=palette || out->video.vram!=vram ||
           out->bus.size()!=bus)return 1;
    }
''')

    def test_obfuscated_pc_constants_add_jump_and_saved_return_entries(self):
        from tools.mk2 import generate_architectural as static
        rows={0xff8cd9e0:(48,0,(),'MOVI FF84736Dh,A3'),
              0xff8cda10:(16,0,(),'MOVE A3,A14'),
              0xff8cda20:(48,0,(),'ADDI 86753h,A14'),
              0xff8cda50:(48,0,(),'MOVI FEBB6868h,A0'),
              0xff8cda80:(48,0,(),'ADDI E58468h,A0')}
        self.assertEqual(static.computed_pc_entries(rows),{0xff8cdac0,0xffa0ecd0})
        self.assertEqual(static.computed_pc_entries({0xff800000:(48,0,(),'MOVI FF800100h,B3'),
            0xff800030:(32,0,(),'ADDI FFF0h,B3')}),{0xff8000f0})
        self.assertEqual(static.computed_pc_entries({0xff800000:(48,0,(),'MOVI FF800100h,A0'),
            0xff800030:(48,0,(),'ADDI 20h,A0'),0xff800060:(48,0,(),'ADDI FF80h,A0')}),{0xff8100a0})
        for altered in ('register','gap','unaligned','nonrom'):
            bad={0xff800000:(48,0,(),'MOVI FF800100h,A0'),0xff800030:(48,0,(),'ADDI 20h,A0')}
            if altered=='register':bad[0xff800030]=(48,0,(),'ADDI 20h,A1')
            if altered=='gap':bad[0xff800040]=bad.pop(0xff800030)
            if altered=='unaligned':bad[0xff800030]=(48,0,(),'ADDI 21h,A0')
            if altered=='nonrom':bad[0xff800030]=(48,0,(),'ADDI 800000h,A0')
            with self.subTest(altered=altered):self.assertEqual(static.computed_pc_entries(bad),set())

    def test_authenticated_fighter_reported_checksum_reaches_encoded_return_without_memory_writes(self):
        from tools.mk2.offline_decode import decode
        from tools.mk2 import generate_static_cfg as cfg
        rom=g.load_program(g.ROOT/'roms/mk2');cache={}
        decode(rom,[0xffa0ecd0],cache=cache)
        rows={pc:row for pc,row in cache.items()if pc<=0xffa0ee50}
        self.assertEqual(rows[0xffa0ecd0][3].split(),['MOVI','FFA24960h,A0'])
        generated=(__import__('tools.setup.mk2',fromlist=['inc_dir']).inc_dir()/'mk2_first_fight.inc').read_text()
        for pc in (0xffa0ecd0,0xff8cdac0):self.assertIn(f'case 0x{pc:08x}u:',generated)
        pcs=set(rows)|{0xffa0ee60,0xff8cdac0}
        edges={pc:cfg.direct_targets(pc,row[0],row[3],0xff8045d0) or ()for pc,row in rows.items()}
        cases=''.join(f'case 0x{pc:08x}:{{'+g.emit_instruction(pc,row[0],row[3],row[2],pcs,edges)+'break;}\n'for pc,row in rows.items())
        # Component fixture: only the two authenticated ROM ranges read by this routine.
        fixture='program.bytes.resize(0x100000);\n'
        for address,count in ((0xffa1d690,18),(0xff9993a0,300)):
            offset=(address-0xff800000)//8;values=','.join(str(v)for v in rom[offset:offset+count])
            fixture+='{const uint8_t bytes[]={'+values+'};std::copy(std::begin(bytes),std::end(bytes),program.bytes.begin()+'+str(offset)+');}\n'
        # A1 keeps the last word the routine reads (sign-extended field of size 16), read from the user's ROM.
        last=(0xff9993a0+149*16-0xff800000)//8;last=int.from_bytes(rom[last:last+2],'little',signed=True)
        last_word=f'0x{last&0xffffffff:x}u'
        self.compile_and_run(fixture+r'''
    // Synthetic registers: the routine writes A0, A1, A8 and B0 before reading them and returns through A14;
    // the others are sentinels. Pinned Original independently stepped 644 instructions/1449 relative cycles.
    s.next_pc=0xffa0ecd0;s.status=0x10200030;
    for(unsigned n=0;n<16;++n)s.a[n]=0x5e000000u|n<<4;
    for(unsigned n=0;n<15;++n)s.b[n]=0x5e100000u|n<<4;
    s.a[14]=0xff8cdac0u;
    auto expected_a=s.a;auto expected_b=s.b;
    expected_a[0]=0xff99aef0u;expected_a[1]='''+last_word+r''';expected_a[8]=0;expected_b[0]=0;
    const auto ram=out->main_ram;const auto cmos=s.cmos;const auto palette=out->video.palette_ram;
    const auto vram=out->video.vram;const auto io=s.board.io;
    unsigned steps=0;
    while(s.next_pc!=0xff8cdac0) {
        if(++steps>1000)return 1;
        switch(s.next_pc) {
'''+cases+r'''
        default:return 2;
        }
    }
    if(s.a!=expected_a || s.b!=expected_b || s.status!=0x60200030 || s.cycles!=1449 || steps!=644 ||
       ram!=out->main_ram || cmos!=s.cmos || palette!=out->video.palette_ram ||
       vram!=out->video.vram || io!=s.board.io || out->bus.size()!=159) {
        std::cerr<<std::hex<<s.a[8]<<' '<<s.a[0]<<' '<<s.a[14]<<std::dec<<' '<<steps
                 <<' '<<(ram!=out->main_ram)<<' '<<(cmos!=s.cmos)<<' '<<(palette!=out->video.palette_ram)
                 <<' '<<(vram!=out->video.vram)<<' '<<(io!=s.board.io)<<' '<<out->bus.size();return 3;
    }
    for(unsigned n=0;n<159;++n) {
        const auto address=n<9?0xffa1d690+n*16:0xff9993a0+(n-9)*16;
        const auto offset=(address-0xff800000u)/8;
        const auto value=uint16_t(program.bytes[offset]|uint16_t(program.bytes[offset+1])<<8);
        if(out->bus[n].address_bit!=address || out->bus[n].kind!='r' || out->bus[n].value!=value)return 4;
    }
''')

    def test_saved_getpc_plus_immediate_addition_supplies_static_continuation(self):
        from tools.mk2 import generate_architectural as static
        self.assertEqual(static.saved_pc_entry(0xff843110,'ADDI 60h,A7',
                         (16,0,(0,),'GETPC A7')),0xff843170)
        self.assertEqual(static.saved_pc_entry(0xffa4e480,'ADDI 60h,A7',
                         (16,0,(0,),'GETPC A7')),0xffa4e4e0)
        self.assertIsNone(static.saved_pc_entry(0xff843110,'ADDI 60h,A6',
                         (16,0,(0,),'GETPC A7')))
        self.assertIsNone(static.saved_pc_entry(0xff843110,'ADDI 60h,A7',None))
        self.assertEqual(static.saved_pc_entry(0xff843110,'ADDI FFF0h,A7',
                         (16,0,(0,),'GETPC A7'),size=32),0xff843100)

    def test_partitioned_dispatch_preserves_cross_page_call_return_and_missing_pc(self):
        from tools.mk2 import generate_architectural as static
        source='''case 0x00000100u: { // CALL A0
    o.Call(s.a[0],0x110,3);
    break;
}
case 0x00000110u: { // NOP
    o.Finish(0x120,1);
    break;
}
case 0x00001010u: { // RETS
    o.ReturnSubroutine();
    break;
}
case 0x00001020u: { // unsupported
    throw std::runtime_error("untranslated instruction");
    break;
}
'''
        code=static.partition(source)
        self.compile_and_run('using mk2::BootOps; struct Dispatch {\n'+code+r'''
    };
    if(!Dispatch::IsFirstFightStaticPC(0x100) || !Dispatch::IsFirstFightStaticPC(0x110) ||
       !Dispatch::IsFirstFightStaticPC(0x1010) || Dispatch::IsFirstFightStaticPC(0x120) ||
       Dispatch::IsFirstFightStaticPC(0x101) || Dispatch::IsFirstFightStaticPC(0x1020))return 6;
    for(unsigned pc=0;pc<=0x1030;pc+=16)
        if(Dispatch::IsFirstFightStaticPC(pc)!=(pc==0x100 || pc==0x110 || pc==0x1010))return 7;
    s.a[0]=0x1010;s.a[15]=0x01000100;s.next_pc=0x100;s.status=0x70200030;
    if(!Dispatch::ExecuteFirstFightStatic(o) || s.next_pc!=0x1010 || s.cycles!=3 || o.PeekStack()!=0x110)return 1;
    if(!Dispatch::ExecuteFirstFightStatic(o) || s.next_pc!=0x110 || s.cycles!=10 || s.a[15]!=0x01000100)return 2;
    if(!Dispatch::ExecuteFirstFightStatic(o) || s.next_pc!=0x120 || s.cycles!=11 || s.status!=0x70200030)return 3;
    if(Dispatch::ExecuteFirstFightStatic(o) || s.next_pc!=0x120 || s.cycles!=11)return 4;
    s.next_pc=0x1020;bool rejected=false;
    try{Dispatch::ExecuteFirstFightStatic(o);}catch(const std::runtime_error&){rejected=true;}
    if(!rejected || s.next_pc!=0x1020 || s.cycles!=11)return 5;
''')

    def test_offline_closure_preserves_call_continuations_and_rejects_wrong_rom(self):
        from tools.mk2 import generate_architectural as static
        self.assertEqual(static.closure_targets(0xff800000,48,'CALLA FF800100h',0xff8045d0),
                         (0xff800030,0xff800100))
        self.assertEqual(static.closure_targets(0xff800000,16,'CALL A0',0xff8045d0),(0xff800010,))
        self.assertEqual(static.closure_targets(0xff800000,16,'EXGPC A7',0xff8045d0),(0xff800010,))
        self.assertEqual(static.closure_targets(0xff800000,16,'TRAP 1h',0xff8045d0),(0xff800010,0xff8045d0))
        self.assertEqual(static.closure_targets(0xff800000,16,'RETS',0xff8045d0),())
        with self.assertRaisesRegex(ValueError,'authenticated ROM'):static.generate(bytes(0x100000))

    def test_actor_selector_also_reaches_the_instruction_after_its_inline_pointer(self):
        from tools.mk2 import generate_architectural as static
        self.assertEqual(static.closure_targets(0xff9ba100,48,'CALLA FF83D7E0h',0xff8045d0),
                         (0xff83d7e0,0xff9ba130,0xff9ba150))
        self.assertEqual(static.closure_targets(0xff9ba100,48,'CALLA FF83D7F0h',0xff8045d0),
                         (0xff83d7f0,0xff9ba130))

    def test_authenticated_boot_exchange_retains_the_observed_target(self):
        from tools.mk2 import generate_architectural as static

        rom = g.load_program(g.ROOT/'roms/mk2')
        pc = 0xffa59f20
        vector = 0xff8045d0
        self.assertEqual(static.closure_targets(pc,16,'EXGPC  B6',vector,rom=rom), (0xffa5a190,))
        self.assertEqual(static.closure_targets(pc,16,'EXGPC  B6',vector), (0xffa59f30,))
        self.assertEqual(static.closure_targets(pc,16,'EXGPC  B5',vector,rom=rom), (0xffa59f30,))
        self.assertEqual(static.closure_targets(0xffa59e90,16,'EXGPC  B6',vector,rom=rom), (0xffa59ea0,))
        for address in (0xffa5a150,0xffa59f10,0xffa5a1c0):
            changed = bytearray(rom)
            changed[(address-0xff800000)//8] ^= 1
            with self.subTest(address=hex(address)):
                self.assertEqual(static.closure_targets(pc,16,'EXGPC  B6',vector,rom=changed), (0xffa59f30,))

    def test_boot_exchange_and_overwrite_match_original_cpu34(self):
        from tools.mk2.offline_decode import decode

        pcs = (0xffa59f20, 0xffa5a190, 0xffa5a1c0, 0xffa5a1f0)
        rom = g.load_program(g.ROOT/'roms/mk2')
        rows, _ = decode(rom, pcs[:-1])
        self.assertEqual(tuple(rows[pc][3].split() for pc in pcs[:-1]),
                         (['EXGPC', 'B6'], ['MOVI', 'FFA401C0h,A0'], ['MOVI', 'FFA593B0h,B6']))
        def emit(pc):
            width, _, words, asm = rows[pc]
            return '{' + g.emit_instruction(pc, width, asm, words, set(pcs), {}, batch_forms=True) + '}\n'

        # PCs and cycles of the MAME 0.280 breakpoints (normal and service factory reset); B6 holds the exchanged
        # target, ST flags and the other registers are synthetic sentinels (the three instructions write A0 and B6
        # only; MOVI sets N/Z, clears V and keeps C).
        # This component seeds the TMS boundary and holds the unrelated DSP in reset.
        self.compile_and_run(r'''
    std::array<uint32_t, 34> expected{0xffa59f20, 0x70000015, 297188};
    for(unsigned n=3;n<34;++n)expected[n]=0x5e000000u|n<<4;
    expected[25]=0xffa5a190;
    s.next_pc=expected[0]; s.status=expected[1]; s.cycles=expected[2];
    std::copy_n(expected.begin()+3, s.a.size(), s.a.begin());
    std::copy_n(expected.begin()+19, s.b.size(), s.b.begin());
    machine->link.HostWrite(0x01d01030,0);
    machine->link.Synchronize();
    machine->MainInstruction(s.cycles);
    machine->AdvanceVideo(s.board,out->video);
    auto matches = [&] {
        return s.next_pc==expected[0] && s.status==expected[1] && s.cycles==expected[2] &&
            std::equal(s.a.begin(),s.a.end(),expected.begin()+3) &&
            std::equal(s.b.begin(),s.b.end(),expected.begin()+19);
    };
    const auto bus_size=out->bus.size();
    const auto ram=out->main_ram;
''' + emit(pcs[0]) + r'''
    expected[0]=0xffa5a190; expected[2]=297190; expected[25]=0xffa59f30;
    if(!matches() || s.instructions!=1) return 1;
''' + emit(pcs[1]) + r'''
    expected[0]=0xffa5a1c0; expected[1]=0xc0000015; expected[2]=297193; expected[3]=0xffa401c0;
    if(!matches() || s.instructions!=2) return 2;
''' + emit(pcs[2]) + r'''
    expected[0]=0xffa5a1f0; expected[2]=297196; expected[25]=0xffa593b0;
    if(!matches() || s.instructions!=3 || out->bus.size()!=bus_size || out->main_ram!=ram) return 3;
''')

    def lane_component(self, group):
        """Synthetic start states (tools/mk2/tms_lane_witnesses.py); each step must reach the SHA-256 of the state
        the pinned MAME reached from the same start, and each segment the SHA-256 of its ordered bus lanes."""
        from tools.mk2.offline_decode import decode
        from tools.mk2 import tms_lane_witnesses as witnesses

        segments = witnesses.load()['groups'][group]
        pcs = {pc for segment in segments for pc in segment['pcs']}
        rom = g.load_program(g.ROOT/'roms/mk2')
        rows, _ = decode(rom, {pc for segment in segments for pc in segment['pcs'][:-1]})
        def emit(pc):
            width, _, words, asm = rows[pc]
            return '{' + g.emit_instruction(pc, width, asm, words, pcs, {}, batch_forms=True) + '}\n'

        def values(registers):
            return '{'+', '.join(f'0x{witnesses.resolve(value, rows):x}u' for value in registers)+'}'

        body = r'''
    // Local components keep their synthetic CPU registers and share a monotonic host clock.
    machine->link.HostWrite(0x01d01030,0);
    machine->link.Synchronize();
    auto cpu34 = [&](uint64_t clock) {
        auto row=mk2::Cpu34(s); row[2]=s.cycles-clock; return mk2::WordsDigest(row.data(),row.size());
    };
    auto lanes = [&](size_t from) {
        std::vector<uint64_t> words;
        for(size_t n=from;n<out->bus.size();++n) {
            words.push_back(uint64_t(out->bus[n].kind)); words.push_back(out->bus[n].address_bit);
            words.push_back(out->bus[n].value);
        }
        return mk2::WordsDigest(words);
    };
    [[maybe_unused]] auto& ram=out->main_ram;
    program.bytes.resize(0x100000);
'''
        for segment in segments:
            start = segment['start']
            body += '{\nconst auto clock=s.cycles; const auto bus=out->bus.size();\n'
            body += (f's.next_pc=0x{segment["pcs"][0]:x}u; s.status=0x{start["st"]:x}u; '
                     f's.a={values(start["a"])}; s.b={values(start["b"])};\n')
            irq = segment.get('irq_io')
            if irq is not None:
                for index, value in zip(witnesses.IRQ_IO, irq):
                    body += f's.board.io[{index}]=0x{value:04x};\n'
                body += 'if(o.PendingInterrupt()) return 5;\n'
            for address, value in segment['ram']:
                body += f'ram[{(address-0x01000000)//16}]=0x{witnesses.resolve(value, rows):04x};\n'
            for address in segment['program_reads']:
                offset = (address-0xff800000)//8
                body += (f'program.bytes[{offset}]=0x{rom[offset]:02x};\n'
                         f'program.bytes[{offset+1}]=0x{rom[offset+1]:02x};\n')
            for pc, digest in zip(segment['pcs'][:-1], segment['cpu34_sha256'], strict=True):
                body += emit(pc)
                body += f'if(cpu34(clock)!="{digest}") {{std::cerr << "CPU34 after {pc:08x}";return 1;}}\n'
            body += f'if(out->bus.size()!=bus+{segment["lane_count"]}) return 2;\n'
            body += f'if(lanes(bus)!="{segment["lanes_sha256"]}") return 3;\n'
            if irq is not None:
                for index, value in zip(witnesses.IRQ_IO, irq):
                    body += f'if(s.board.io[{index}]!=0x{value:04x}) return 6;\n'
            body += '}\n'
        return body, emit, values, segments

    def test_original_task_continuations_match_cpu34_and_ordered_ram_lanes(self):
        body, emit, values, segments = self.lane_component('mmfm')
        # A changed saved PC must flow through the real load and alignment rules.
        start = segments[1]['start']
        self.assertEqual(segments[1]['pcs'][:2], [0xff81a290, 0xff81a2b0])
        index = (start['a'][12]-0x01000000)//16
        body += (f's.next_pc=0xff81a290u; s.status=0x{start["st"]:x}u; s.a={values(start["a"])}; '
                 f's.b={values(start["b"])};\nram[{index}]=0x59ff; ram[{index+1}]=0xffa5;\n')
        body += emit(0xff81a290) + emit(0xff81a2b0)
        body += 'if(s.next_pc!=0xffa559f0 || s.a[7]!=0xff81a2c0) return 4;\n'
        self.compile_and_run(body)

    def test_original_stream_calls_match_cpu34_and_ordered_rom_ram_lanes(self):
        self.compile_and_run(self.lane_component('call')[0])

    def test_original_callback_matches_cpu34_and_ordered_cell_stack_lanes(self):
        self.compile_and_run(self.lane_component('callback')[0])

    def test_original_pit_callback_matches_cpu34_and_ordered_lanes(self):
        self.compile_and_run(self.lane_component('pit_callback')[0])

    def test_original_scheduler_matches_cpu34_and_ordered_task_lanes(self):
        self.compile_and_run(self.lane_component('scheduler')[0])

    def test_original_scheduler_and_masked_render_jumps_match_cpu34(self):
        self.compile_and_run(self.lane_component('round6_jump')[0])

    def test_task_exchange_witnesses_preserve_lexical_continuators(self):
        from tools.mk2 import generate_architectural as static

        rom = g.load_program(g.ROOT/'roms/mk2')
        changed = bytearray(rom)
        changed[(0xff819100-0xff800000)//8] ^= 1
        for pc, target in ((0xff81a2b0,0xff819140), (0xff81a890,0xff8191b0)):
            with self.subTest(pc=hex(pc)):
                self.assertEqual(static.closure_targets(pc,16,'EXGPC  A7',0,rom=rom), (target,pc+16))
                self.assertEqual(static.closure_targets(pc,16,'EXGPC  A7',0), (pc+16,))
                self.assertEqual(static.closure_targets(pc,16,'EXGPC  A7',0,rom=changed), (pc+16,))
                self.assertEqual(static.closure_targets(pc,16,'EXGPC  B7',0,rom=rom), (pc+16,))
                self.assertEqual(static.closure_targets(pc+16,16,'EXGPC  A7',0,rom=rom), (pc+32,))

    def test_original_stream_calls_retain_targets_and_lexical_returns(self):
        from tools.mk2 import generate_architectural as static
        from tools.mk2.offline_decode import decode

        rom = g.load_program(g.ROOT/'roms/mk2')
        calls = {
            0xff804f90: ('A2', 0xff800000, 0xffa044c0),
            0xff9f88e0: ('A1', 0xffa04620, 0xffa03fc0),
        }
        rows, _ = decode(rom, calls.keys())
        for pc, (register, target, operand) in calls.items():
            with self.subTest(pc=hex(pc)):
                width, _, _, asm = rows[pc]
                self.assertEqual((width, asm.split()), (16, ['CALL', register]))
                self.assertEqual(static.closure_targets(pc, width, asm, 0, rom=rom),
                                 tuple(sorted((target, pc+16))))
                changed = bytearray(rom)
                changed[(operand-0xff800000)//8] ^= 0x10
                self.assertEqual(static.closure_targets(pc, width, asm, 0, rom=changed), (pc+16,))
                self.assertEqual(static.closure_targets(pc, width, asm, 0), (pc+16,))
                self.assertEqual(static.closure_targets(pc, width, 'CALL A0', 0, rom=rom), (pc+16,))
                self.assertEqual(static.closure_targets(pc, 32, asm, 0, rom=rom), (pc+32,))

    def test_original_callback_edge_requires_authenticated_producer_and_caller(self):
        from tools.mk2 import generate_architectural as static
        from tools.mk2.offline_decode import decode

        rom = g.load_program(g.ROOT/'roms/mk2')
        rows, _ = decode(rom, {0xff82c6f0, 0xff82c720, 0xff8049a0, 0xff8049e0, 0xff82da10,
                               0xff85c240, 0xff85c270, 0xff85d400})
        self.assertEqual(rows[0xff82c6f0][3].split(), ['MOVI', 'FF82DA10h,A0'])
        self.assertEqual(rows[0xff82c720][3].split(), ['MOVE', 'A0,@105D0E0h,1'])
        self.assertEqual(rows[0xff8049a0][3].split(), ['MOVE', '@105D0E0h,A0,1'])
        self.assertEqual(rows[0xff82da10][3].split(), ['MOVE', '@1061CF0h,A0,0'])
        self.assertEqual(rows[0xff85c240][3].split(), ['MOVI', 'FF85D400h,A0'])
        self.assertEqual(rows[0xff85c270][3].split(), ['MOVE', 'A0,@105D0E0h,1'])
        self.assertEqual(rows[0xff85d400][3].split(), ['MOVE', '@105ECD0h,A0,0'])
        width, _, _, asm = rows[0xff8049e0]
        self.assertEqual(static.closure_targets(0xff8049e0, width, asm, 0, rom=rom),
                         (0xff8049f0, 0xff82da10, 0xff85d400))
        for address in (0xff82c700, 0xff82c720, 0xff8049e0, 0xff82da10,
                        0xff85c250, 0xff85c270, 0xff85d400):
            changed = bytearray(rom)
            changed[(address-0xff800000)//8] ^= 0x10
            with self.subTest(address=hex(address)):
                self.assertEqual(static.closure_targets(0xff8049e0, width, asm, 0, rom=changed), (0xff8049f0,))
        self.assertEqual(static.closure_targets(0xff8049e0, width, 'CALL A1', 0, rom=rom), (0xff8049f0,))

    def test_original_pit_callback_transfers_require_authenticated_producers(self):
        from tools.mk2 import generate_architectural as static
        from tools.mk2.offline_decode import decode

        rom = g.load_program(g.ROOT/'roms/mk2')
        sites = {
            0xff83c420: ('EXGPC', 'A7', (0xff83c430, 0xff8bde90), (0xff83c430,), (0xff8bde40,)),
            0xff85d960: ('JUMP', 'A10', (0xff85dab0, 0xff85db40, 0xff85dbb0, 0xff85dc50), (),
                        (0xff85d5a0, 0xff85d6a0, 0xff85d780, 0xff85d860)),
        }
        rows, _ = decode(rom, sites.keys())
        for pc, (op, reg, expected, fallback, producers) in sites.items():
            width, _, _, asm = rows[pc]
            with self.subTest(pc=hex(pc)):
                self.assertEqual((width, asm.split()), (16, [op, reg]))
                self.assertEqual(static.closure_targets(pc, width, asm, 0, rom=rom), expected)
                self.assertEqual(static.closure_targets(pc, width, asm, 0), fallback)
                self.assertEqual(static.closure_targets(pc, width, f'{op} A9', 0, rom=rom), fallback)
                for address in producers:
                    changed = bytearray(rom)
                    changed[(address-0xff800000)//8] ^= 0x10
                    self.assertEqual(static.closure_targets(pc, width, asm, 0, rom=changed), fallback)

    def test_original_scheduler_destinations_require_authenticated_task_code(self):
        from tools.mk2 import generate_architectural as static
        from tools.mk2.offline_decode import decode

        rom = g.load_program(g.ROOT/'roms/mk2')
        pc = 0xff80de00
        rows, _ = decode(rom, {pc, 0xff80dde0, 0xff80dd00, 0xff80e3d0, 0xffa0d5d0})
        self.assertEqual(rows[0xff80dde0][3].split(), ['MMFM', 'A1,A7-A12'])
        self.assertEqual(rows[0xff80dd00][3].split(), ['MMTM', 'A1,A7-A12'])
        self.assertEqual(rows[0xff80e3d0][3].split(), ['MMTM', 'A2,A7-A12'])
        self.assertEqual(rows[0xffa0d5d0][3].split(), ['CALLA', 'FF80DCC0h'])
        from tools.mk2 import tms_lane_witnesses as witnesses
        targets = tuple(sorted({after for segment in witnesses.load()['groups']['scheduler']
                                for before,after in zip(segment['pcs'], segment['pcs'][1:])
                                if before == pc}))
        self.assertEqual(len(targets), 40)
        width, _, _, asm = rows[pc]
        self.assertEqual((width, asm.split()), (16, ['JUMP', 'A7']))
        self.assertEqual(static.closure_targets(pc, width, asm, 0, rom=rom), targets)
        self.assertEqual(static.closure_targets(pc, width, asm, 0), ())
        self.assertEqual(static.closure_targets(pc, width, 'JUMP A8', 0, rom=rom), ())
        for address in (0xff80dde0, 0xff80dd00, 0xff80e3d0, 0xffa0d5d0, 0xff8eb7c0):
            changed = bytearray(rom)
            changed[(address-0xff800000)//8] ^= 0x10
            with self.subTest(address=hex(address)):
                self.assertEqual(static.closure_targets(pc, width, asm, 0, rom=changed), ())

    def test_computed_transfers_status_and_banked_mmfm(self):
        def emit(asm, size=16):
            return '{' + g.emit_instruction(0x100, size, asm, (0,) * (size//16),
                                            {0x110, 0x120, 0x200}, {}) + '}\n'
        call, ret, exchange, jump = [emit(a) for a in ('CALL A0', 'RETS', 'EXGPC A7', 'JUMP B15')]
        get, put, field = [emit(a) for a in ('GETST B2', 'PUTST B2', 'SETF 0h,0,1')]
        mmfm = emit('MMFM B6,B2-B5,B9-B10',32)
        self.compile_and_run(r'''
    s.next_pc=0x100;s.status=0x70200030;s.a[15]=0x01000100;s.a[0]=0x20f;
''' + call + r'''
    if(s.next_pc!=0x200 || s.cycles!=3 || s.a[15]!=0x010000e0 || o.PeekStack()!=0x110 || s.status!=0x70200030)return 1;
''' + ret + r'''
    if(s.next_pc!=0x110 || s.cycles!=10 || s.a[15]!=0x01000100 || s.status!=0x70200030)return 2;
    s.a[7]=0x20f;
''' + exchange + r'''
    if(s.next_pc!=0x200 || s.a[7]!=0x110 || s.cycles!=12 || s.status!=0x70200030)return 3;
    s.a[15]=0x210;
''' + jump + r'''
    bool rejected=false;try{switch(s.next_pc){case 0x200:break;default:throw std::runtime_error("untranslated PC");}}
    catch(const std::runtime_error&){rejected=true;}
    if(!rejected || s.next_pc!=0x210 || s.cycles!=14 || s.a[15]!=0x210)return 4;
    s.a[15]=0x01000100;
''' + get + r'''
    if(s.b[2]!=0x70200030 || s.cycles!=15)return 5;
    s.b[2]=0x50000030;
''' + put + field + r'''
    if(s.status!=0x50000030 || s.cycles!=20 || o.FieldWidth(1)!=32)return 6;
    s.b[6]=0x01000000;
    for(unsigned n=0;n<6;++n){out->main_ram[n*2]=0x1100+n;out->main_ram[n*2+1]=0x2200+n;}
''' + mmfm + r'''
    const unsigned regs[]={10,9,5,4,3,2};
    for(unsigned n=0;n<6;++n)if(s.b[regs[n]]!=((0x2200+n)<<16 | (0x1100+n)))return 7;
    if(s.b[6]!=0x010000c0 || s.a[15]!=0x01000100 || s.status!=0x50000030 || s.cycles!=47)return 8;
''')

    def test_setf32_real_opcode_clears_old_field_width_and_preserves_other_status_bits(self):
        code=g.emit_instruction(0xff904b30,16,'SETF 20h,0,1',(0x740,),{0xff904b40},{})
        self.compile_and_run(r'''
    s.next_pc=0xff904b30;s.status=0x90000430;s.a[15]=0x01200400;
    const auto a=s.a;const auto b=s.b;
'''+code+r'''
    if(s.status!=0x90000030 || s.cycles!=2 || s.next_pc!=0xff904b40 || s.instructions!=1 ||
       s.a!=a || s.b!=b || o.FieldWidth(1)!=32 || !out->bus.empty())return 1;
    out->main_ram[0]=1;out->main_ram[1]=0x8000;
    if(o.ReadField(0x01000000,1)!=0x80000001u)return 2;
''')

    def test_direct_branch_uses_encoded_target_without_observed_edge(self):
        code=g.emit_instruction(0x100,16,'JR 200h',(0,),{0x110,0x200},{})
        self.assertNotIn('throw',code)

    def test_program_rom_writes_keep_physical_lanes_and_leave_all_memory_cpu_and_clocks_unchanged(self):
        self.compile_and_run(r'''
    program.bytes.resize(0x100000);
    for(unsigned n=0;n<program.bytes.size();++n)program.bytes[n]=uint8_t(n^(n>>7));
    const auto rom=program.bytes;const auto ram=out->main_ram;const auto vram=out->video.vram;
    const auto palette=out->video.palette_ram;const auto cmos=s.cmos;const auto io=s.board.io;
    s.next_pc=0xff80a3e0;s.status=0x50000010;s.a[0]=0x5e000000;s.a[8]=0x5e000080;
    const auto a=s.a;const auto b=s.b;
    for(unsigned address:{0xff800000u,0xffa21670u,0xffa21680u,0xfffffff0u,
                          0x1f800000u,0x1ffffff0u}) {
        const auto n=out->bus.size();o.Write16(address,0x1234);
        if(out->bus.size()!=n+1 || out->bus.back().kind!='w' || out->bus.back().address_bit!=address ||
           out->bus.back().value!=0x1234 || out->bus.back().pc!=s.next_pc || out->bus.back().cycle)return 1;
    }
    for(unsigned address:{0xff7ffff0u,0x1f7ffff0u,0x20000000u,0xffa21671u}) {
        const auto n=out->bus.size();bool rejected=false;
        try{o.Write16(address,1);}catch(const std::runtime_error&){rejected=true;}
        if(!rejected || out->bus.size()!=n)return 2;
    }
    if(program.bytes!=rom || out->main_ram!=ram || out->video.vram!=vram ||
       out->video.palette_ram!=palette || s.cmos!=cmos || s.board.io!=io || s.a!=a || s.b!=b ||
       s.status!=0x50000010 || s.next_pc!=0xff80a3e0 || s.cycles || s.instructions || machine->LastMainCycles())return 3;
    program.bytes.clear();bool rejected=false;
    try{o.Write16(0xffa21670,1);}catch(const std::runtime_error&){rejected=true;}
    if(!rejected || out->bus.size()!=6)return 4;
''')

    def test_unmapped_sound_preceding_word_is_a_bus_write_without_dcs_effects(self):
        self.compile_and_run(r'''
    const auto control=machine->link.MainStatus();const auto clocks=machine->SchedulerClocks();
    const auto io=s.board.io;const auto ram=out->main_ram;
    s.next_pc=0xff903a00;s.status=0x200030;s.a[14]=1;
    for(unsigned value:{0u,1u,0xffffu})o.Write16(0x01d01010,uint16_t(value));
    if(out->bus.size()!=3 || out->bus[1].address_bit!=0x01d01010 || out->bus[1].value!=1 ||
       out->bus[1].kind!='w' || out->bus[1].pc!=0xff903a00 || out->bus[1].cycle ||
       machine->link.MainStatus()!=control || machine->link.Irq2Asserted() ||
       machine->SchedulerClocks()!=clocks || s.board.io!=io || out->main_ram!=ram ||
       s.next_pc!=0xff903a00 || s.status!=0x200030 || s.a[14]!=1 || s.cycles || s.instructions)return 1;
    for(unsigned address:{0x01d01000u,0x01d01040u,0x01d01011u}) {
        bool rejected=false;try{o.Write16(address,1);}catch(const std::runtime_error&){rejected=true;}
        if(!rejected || out->bus.size()!=3)return 2;
    }
''')

    def test_mmfm_base_destination_and_sp_alias_follow_assignment_order(self):
        self.compile_and_run(r'''
    s.status=0x50000030;s.a[0]=0x01000000;
    out->main_ram[0]=0x0100;out->main_ram[1]=0x0100;
    o.Mmfm(0x8000,0x120,false,0);
    if(s.a[0]!=0x01000120 || s.status!=0x50000030 || s.cycles!=7)return 1;
    s.a[15]=0x01000000;out->main_ram[0]=0x0200;
    o.Mmfm(1,0x140,true);
    if(s.a[15]!=0x01000220 || s.status!=0x50000030 || s.cycles!=14)return 2;
''')

    def test_putst_takes_pending_irq_and_rets_discards_words(self):
        self.compile_and_run(r'''
    program.bytes.resize(0x100000);program.bytes[0xffff8]=0xd0;program.bytes[0xffff9]=0x45;
    program.bytes[0xffffa]=0x80;program.bytes[0xffffb]=0xff;
    s.a[15]=0x01000100;s.board.io[17]=2;s.board.io[18]=2;s.status=0x30;
    o.PutStatus(0x00200030,0x110);
    if(s.next_pc!=0xff8045d0 || s.status!=0x10 || s.a[15]!=0x010000c0 || s.cycles!=19 ||
       o.PeekStack()!=0x00200030 || o.PeekStack(32)!=0x110)return 1;
    s.board.io[17]=0;s.board.io[18]=0;s.a[15]=0x01000100;o.Push(0x20f);
    o.ReturnSubroutine(3);
    if(s.next_pc!=0x200 || s.a[15]!=0x01000130 || s.cycles!=26 || s.status!=0x10)return 2;
    s.a[15]=0xff800000;bool rejected=false;
    try{o.ReturnSubroutine();}catch(const std::runtime_error&){rejected=true;}
    if(!rejected || s.a[15]!=0xff800000 || s.cycles!=26)return 3;
''')


if __name__=='__main__':unittest.main()
