"""Execute the newly reached TMS forms with pinned flags, clocks and physical lanes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as generated,test_coin_pair


class FirstFightOpsTests(unittest.TestCase):
    compile_and_run=test_coin_pair.CoinPairPrimitiveTests.compile_and_run

    def test_unmapped_low_window_returns_original_pullups_without_game_state_changes(self):
        # midtunit main_map unmap_value_high: the Original's reads 999810/999830 at FF9B36F0, cycle 1785551759, both
        # returned FFFF. ST and the RAM word are synthetic.
        self.compile_and_run(r'''
    s.next_pc=0xff9b36f0;s.cycles=1785551759;s.status=0x5a200015;
    out->main_ram[0]=0x4567;
    const auto memory=out->main_ram;const auto cmos=s.cmos;const auto io=s.board.io;
    const auto vram=out->video.vram;const auto palette=out->video.palette_ram;
    const auto a=s.a;const auto b=s.b;const auto dsp=machine->dsp.Registers();
    out->observe_history=false;
    for(uint32_t address=0x00400000;address<0x01000000;address+=16)
        if(o.Read16(address)!=0xffff)return 1;
    out->observe_history=true;
    for(uint32_t address:{0x00400000u,0x00999810u,0x00999830u,0x00fffff0u}) {
        out->bus.clear();
        if(o.Read16(address)!=0xffff || out->bus.size()!=1)return 2;
        const auto& row=out->bus[0];
        if(row.pc!=0xff9b36f0 || row.address_bit!=address || row.value!=0xffff ||
           row.kind!='r' || row.cycle!=1785551759)return 3;
    }
    if(o.Read16(0x003ffff0)!=0 || o.Read16(0x01000000)!=0x4567)return 4;
    for(unsigned width:{1u,6u,8u,16u})for(unsigned sign:{0u,0x20u})
    for(unsigned bit=0;bit<16;++bit) {
        s.status=0x00200000|width|sign;
        const auto mask=uint32_t((uint64_t(1)<<width)-1);
        uint32_t expected=uint32_t((uint64_t(0x4567ffff)>>bit)&mask);
        if(sign && (expected&(uint32_t(1)<<(width-1))))expected|=~mask;
        if(o.ReadField(0x00fffff0+bit,0)!=expected)return 5;
    }
    s.status=0x00200000;
    if(o.ReadField(0x00999810,0)!=0xffffffff || o.ReadField(0x00fffff0,0)!=0x4567ffff)return 6;
    s.status=0x5a200015;out->bus.clear();
    for(uint32_t address:{0x00400001u,0x01500000u}) {
        bool rejected=false;try{o.Read16(address);}catch(const std::runtime_error&){rejected=true;}
        if(!rejected || !out->bus.empty())return 7;
    }
    bool rejected=false;try{o.Write16(0x00999810,0);}catch(const std::runtime_error&){rejected=true;}
    if(!rejected || !out->bus.empty() || memory!=out->main_ram || cmos!=s.cmos || io!=s.board.io ||
       vram!=out->video.vram || palette!=out->video.palette_ram || a!=s.a || b!=s.b ||
       dsp!=machine->dsp.Registers() || s.cycles!=1785551759 || s.status!=0x5a200015 ||
       s.next_pc!=0xff9b36f0 || s.instructions)return 8;
''')

    def test_graphics_reads_reject_incomplete_rom_before_bus_or_cpu_changes(self):
        self.compile_and_run(r'''
    s.next_pc=0xff801690;s.cycles=86875721;s.status=0x70200030;
    const auto registers=s.a;
    for(size_t size:{size_t(0),size_t(1),size_t(0xbfffff)}) {
        program.graphics.resize(size);
        bool rejected=false;
        try { o.Read16(0x02000000); }
        catch(const std::runtime_error&) { rejected=true; }
        catch(...) { return 1; }
        if(!rejected || !out->bus.empty() || s.a!=registers || s.next_pc!=0xff801690 ||
           s.cycles!=86875721 || s.status!=0x70200030) return 2;
    }
''')

    def test_word_writes_preserve_both_overlapping_ram_shadows_and_all_other_cells(self):
        self.compile_and_run(r'''
    s.next_pc=0x100;s.status=0x70200030;
    s.ram={{0x00fffff0,0x11223344},{0x01000000,0xaabbccdd},{0x01000010,0x55667788},
           {0x01000008,0x10203040},{0x013ffff0,0x99aabbcc}};
    for(unsigned n=0;n<4096;++n)s.ram[0x01100000+n*32]=0xa5a50000+n;
    auto expected=s.ram;auto memory=out->main_ram;
    o.Write16(0x01000000,0xabcd);o.Write16(0x01000010,0x2468);o.Write16(0x013ffff0,0x9876);
    expected[0x00fffff0]=0xabcd3344;expected[0x01000000]=0x2468abcd;
    expected[0x01000010]=0x55662468;expected[0x013ffff0]=0x99aa9876;
    memory[0]=0xabcd;memory[1]=0x2468;memory.back()=0x9876;
    if(s.ram!=expected || out->main_ram!=memory || out->bus.size()!=3 || s.status!=0x70200030 || s.cycles) return 1;
    const std::array<uint32_t,3> addresses{0x01000000,0x01000010,0x013ffff0};
    const std::array<uint16_t,3> values{0xabcd,0x2468,0x9876};
    for(unsigned n=0;n<3;++n)if(out->bus[n].pc!=0x100 || out->bus[n].kind!='w' ||
        out->bus[n].address_bit!=addresses[n] || out->bus[n].value!=values[n] || out->bus[n].cycle) return 2;
    o.Write32(0x01000000,0xdeadbeef);
    expected[0x00fffff0]=0xbeef3344;expected[0x01000000]=0xdeadbeef;expected[0x01000010]=0x5566dead;
    memory[0]=0xbeef;memory[1]=0xdead;
    if(s.ram!=expected || out->main_ram!=memory || out->bus.size()!=5) return 3;
    bool rejected=false;try{o.Write16(0x01000001,0);}catch(const std::runtime_error&){rejected=true;}
    if(!rejected || s.ram!=expected || out->main_ram!=memory || out->bus.size()!=5) return 4;
''')

    def test_cpu_graphics_reads_use_original_banks_mirrors_bytes_and_physical_lanes(self):
        self.compile_and_run(r'''
    program.graphics.resize(0xc00000);
    for(const auto& item:std::array<std::array<uint32_t,2>,8>{{
            {0,0x1234},{0x3ffffe,0x5678},{0x400000,0x9abc},{0x7ffffe,0xdef0},
            {0x800000,0x1357},{0xbffffe,0x2468},{0x94b78,0xabcd},{0x94b7a,0x78e1}}}) {
        program.graphics[item[0]]=uint8_t(item[1]);program.graphics[item[0]+1]=uint8_t(item[1]>>8);
    }
    s.next_pc=0xff801690;s.cycles=86875721;s.status=8;
    const std::array<uint32_t,6> addresses{0x02000000,0x03fffff0,0x04000000,0x05fffff0,0x06000000,0x07fffff0};
    for(unsigned bank:{0u,0x80u}) {
        s.board.WriteVideoControl(uint16_t(bank));
        const std::array<uint16_t,6> expected=bank?
            std::array<uint16_t,6>{0x1357,0x2468,0x9abc,0xdef0,0x1357,0x2468}:
            std::array<uint16_t,6>{0x1234,0x5678,0x9abc,0xdef0,0x1234,0x5678};
        for(unsigned n=0;n<addresses.size();++n) {
            const auto count=out->bus.size();
            if(o.Read16(addresses[n])!=expected[n] || out->bus.size()!=count+1) return 1;
            const auto& row=out->bus.back();
            if(row.pc!=0xff801690 || row.address_bit!=addresses[n] || row.value!=expected[n] ||
               row.kind!='r' || row.cycle!=86875721) return 2;
        }
    }
    s.board.WriteVideoControl(0x78);
    if(o.ReadField(0x024a5bc0,0)!=0xcd || o.ReadField(0x024a5bc8,0)!=0xab ||
       o.ReadField(0x024a5bcc,0)!=0x1a || s.status!=8 || s.cycles!=86875721) return 3;
    if(out->bus[out->bus.size()-2].address_bit!=0x024a5bc0 ||
       out->bus.back().address_bit!=0x024a5bd0) return 4;
    const auto count=out->bus.size();const auto control=s.board.video_control;
    for(uint32_t address:{0x01fffff0u,0x08000000u,0x02000001u}) {
        bool rejected=false;try{o.Read16(address);}catch(const std::runtime_error&){rejected=true;}
        if(!rejected || out->bus.size()!=count) return 5;
    }
    bool rejected=false;try{o.Write16(0x02000000,0xffff);}catch(const std::runtime_error&){rejected=true;}
    if(!rejected || out->bus.size()!=count || s.board.video_control!=control ||
       program.graphics[0]!=0x34 || program.graphics[1]!=0x12) return 6;
''')

    def emit(self,asm,size=16,successors=None):
        try:
            return '{'+generated.emit_instruction(0x100,size,asm,(0,)*(size//16),
                    {0x100,0x110,0x120,0x130,0x200},successors or {})+'}\n'
        except ValueError as error:self.fail('Reached first-fight instruction rejected: '+str(error))

    def test_mmfm_a0_base_keeps_descending_order_lanes_flags_and_27_cycles(self):
        code=self.emit('MMFM A0,A2-A4,A6-A8',32)
        self.compile_and_run(r'''
    s.next_pc=0x100;s.status=0x70200030;s.a[0]=0x01000000;s.a[1]=0x55667788;
    for(unsigned n=0;n<6;++n) { out->main_ram[n*2]=uint16_t(n);out->main_ram[n*2+1]=0x1122; }
'''+code+r'''
    if(s.a[8]!=0x11220000 || s.a[7]!=0x11220001 || s.a[6]!=0x11220002 ||
       s.a[4]!=0x11220003 || s.a[3]!=0x11220004 || s.a[2]!=0x11220005 ||
       s.a[0]!=0x010000c0 || s.a[1]!=0x55667788 || s.status!=0x70200030 ||
       s.cycles!=27 || s.instructions!=1 || s.next_pc!=0x120 || out->bus.size()!=12) return 1;
    for(unsigned n=0;n<12;++n)
        if(out->bus[n].kind!='r' || out->bus[n].address_bit!=0x01000000+n*16 ||
           out->bus[n].pc!=0x100 || out->bus[n].cycle) return 2;
    s.a[0]=0x01000000;
    o.Mmfm(0x8000,0x120,false,0);
    if(s.a[0]!=0x11220020 || out->bus.size()!=14 || s.cycles!=34 || s.status!=0x70200030) return 3;
''')

    def test_static_rom_mmtm_a7_a13_preserve_register_order_lanes_and_flags(self):
        first=self.emit('MMTM A7,A6,A8-A12',32)
        second=self.emit('MMTM A13,A1-A5',32)
        self.compile_and_run(r'''
    s.next_pc=0x100;s.status=0x70200030;
    for(unsigned n=0;n<15;++n)s.a[n]=0x11220000u+n;
    s.a[7]=0x01000200;
'''+first+r'''
    if(s.a[7]!=0x01000140 || s.cycles!=26 || s.instructions!=1 ||
       s.status!=0x70200030 || s.next_pc!=0x120 || out->bus.size()!=12) return 1;
    const unsigned regs[]{6,8,9,10,11,12};
    for(unsigned n=0;n<6;++n) {
        const auto address=0x01000200-(n+1)*32;
        const auto& low=out->bus[n*2];const auto& high=out->bus[n*2+1];
        if(low.kind!='w' || high.kind!='w' || low.address_bit!=address ||
           high.address_bit!=address+16 || low.value!=regs[n] || high.value!=0x1122 ||
           low.pc!=0x100 || high.pc!=0x100 || low.cycle || high.cycle) return 2;
    }
    out->bus.clear();s.next_pc=0x100;s.a[13]=0x01000400;
'''+second+r'''
    if(s.a[13]!=0x01000360 || s.cycles!=48 || s.instructions!=2 ||
       s.status!=0x70200030 || s.next_pc!=0x120 || out->bus.size()!=10) return 3;
    for(unsigned n=0;n<5;++n) {
        const auto address=0x01000400-(n+1)*32;
        const auto& low=out->bus[n*2];const auto& high=out->bus[n*2+1];
        if(low.address_bit!=address || high.address_bit!=address+16 ||
           low.value!=n+1 || high.value!=0x1122 || low.cycle!=26 || high.cycle!=26) return 4;
    }
    for(unsigned base:{7u,13u}) {
        const auto before=s.a;const auto cycle=s.cycles;const auto count=out->bus.size();
        o.Mmtm(uint16_t(0x8000u>>base),0x120,false,base);
        if(s.a[base]!=before[base]-32 || s.cycles!=cycle+6 || out->bus.size()!=count+2 ||
           out->bus[count].address_bit!=before[base]-32 ||
           out->bus[count].value!=uint16_t(before[base]-32) ||
           out->bus[count+1].value!=uint16_t((before[base]-32)>>16) || s.status!=0x70200030)return 5;
        for(unsigned reg=0;reg<16;++reg)if(reg!=base && s.a[reg]!=before[reg])return 6;
    }
''')

    def test_absolute_ne_branch_preserves_status_and_three_or_four_cycles(self):
        code=self.emit('JANE 200h',48,{0x100:(0x130,0x200)})
        self.compile_and_run('s.next_pc=0x100;s.status=0xc0200030;\n'+code+r'''
    if(s.next_pc!=0x200 || s.cycles!=3 || s.status!=0xc0200030 || !out->bus.empty()) return 1;
    s.next_pc=0x100;s.status=0xe0200030;
'''+code+r'''
    if(s.next_pc!=0x130 || s.cycles!=7 || s.status!=0xe0200030 || s.instructions!=2) return 2;
''')

    def test_absolute_nc_branch_tests_carry_only_and_preserves_flags_and_cycles(self):
        code=self.emit('JANC 200h',48,{0x100:(0x130,0x200)})
        self.compile_and_run(r'''
    for(uint32_t status:{0x00200030u,0xa0200030u,0x70200030u,0xf0200030u}) {
        s.next_pc=0x100;s.status=status;const auto before=s.cycles;
'''+code+r'''
        const bool carry=(status&0x40000000)!=0;
        if(s.next_pc!=(carry?0x130u:0x200u) || s.cycles-before!=(carry?4u:3u) ||
           s.status!=status || !out->bus.empty()) return 1;
    }
''')

    def test_abs_flags_follow_the_negated_value_even_when_positive_input_is_kept(self):
        code=self.emit('ABS A4')
        self.compile_and_run('''
    struct Case {uint32_t input,value,status;};
    const Case cases[]={{5,5,0xc0200030},{0xfffffffbu,5,0x40200030},
                        {0,0,0x60200030},{0x80000000u,0x80000000u,0xd0200030}};
    for(const auto& item:cases) {
        s.next_pc=0x100;s.status=0x70200030;s.a[4]=item.input;
'''+code+'''
        if(s.a[4]!=item.value || s.status!=item.status || s.next_pc!=0x110) return 1;
    }
    if(s.cycles!=4 || s.instructions!=4 || !out->bus.empty()) return 2;
''')

    def test_odd_signed_division_preserves_source_and_uses_39_cycles_including_zero_divisor(self):
        code=self.emit('DIVS A7,A1')
        self.compile_and_run('''
    struct Case {uint32_t value,divisor,quotient,status;};
    const Case cases[]={{12,5,2,0x40200030},{0xfffffff4u,5,0xfffffffeu,0xc0200030},
      {4,0xfffffff8u,0,0x60200030},{0xfffffff7u,0xfffffffdu,3,0x40200030},
      {123,0,123,0x50200030},{0x80000000u,0x80000000u,1,0x40200030}};
    for(const auto& item:cases) {
        s.next_pc=0x100;s.status=0x70200030;s.a[1]=item.value;s.a[7]=item.divisor;s.a[2]=0x12345678;
'''+code+'''
        if(s.a[1]!=item.quotient || s.a[7]!=item.divisor || s.a[2]!=0x12345678 ||
           s.status!=item.status || s.next_pc!=0x110) return 1;
    }
    if(s.cycles!=234 || s.instructions!=6 || !out->bus.empty()) return 2;
''')


if __name__=='__main__':unittest.main()
