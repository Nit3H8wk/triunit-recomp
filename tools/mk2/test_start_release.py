"""Original Start release and measured field-one SETF semantics."""
import sys
import os
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import test_coin_pair as pair_controls,run,batch_reference,generate_video_irq as generated
from tools.mk2.test_first_fight_video import GEOMETRY
from tools.quality import run as quality


class StartReleaseTests(unittest.TestCase):
    compile_and_run=pair_controls.CoinPairPrimitiveTests.compile_and_run

    def test_absolute_to_postincrement_move_costs_original_five_cycles(self):
        code=generated.emit_instruction(0x100,48,'MOVE @1000040h,*A1+,1',
                                        (0,0,0),{0x100,0x130},{})
        self.compile_and_run('''
    s.next_pc=0x100; s.status=0x80200406; s.a[1]=0x01000080; out->main_ram[4]=0xabcd;
    {'''+code+'''}
    if(s.cycles!=5 || s.instructions!=1 || s.next_pc!=0x130 ||
       s.status!=0x80200406 || s.a[1]!=0x01000090 || out->main_ram[8]!=0xabcd ||
       out->bus.size()!=2 || out->bus[0].kind!='r' || out->bus[1].kind!='w' ||
       out->bus[0].address_bit!=0x01000040 || out->bus[1].address_bit!=0x01000080) return 1;
''')

    def test_release_dma_modes_match_pinned_blitter_with_complete_framebuffers(self):
        upstream=(run.ROOT/'docs/investigation/sources/midtunit_v.cpp').read_text(encoding='utf-8')
        core=upstream.split('/*** core blitter routine macro ***/')[1].split('DEFINE_TEMPLATED_DMA_DRAW_GROUP')[0]
        source=r'''
#include "native/mk2/mk2_video.hpp"
#include <iostream>
class midtunit_video_device {
public:
    enum op_type_t { PIXEL_SKIP, PIXEL_COLOR, PIXEL_COPY };
    static constexpr unsigned XPOSMASK=0x3ff,YPOSMASK=0x1ff;
    struct State {
        const uint8_t* gfxrom; uint32_t offset; uint16_t palette,color;
        int xpos,ypos,width,height,xstep,ystep,preskip,postskip,startskip,endskip;
        int topclip,botclip,leftclip,rightclip; bool yflip;
    } m_dma_state{};
    std::vector<uint16_t> m_local_videoram=std::vector<uint16_t>(524288,0x1234);
    template<int BitsPerPixel,bool XFlip,bool Skip,bool Scale,op_type_t Zero,op_type_t NonZero> void dma_draw();
};
#define EXTRACTGEN(m) (((base[o>>3]|(base[(o>>3)+1]<<8))>>(o&7))&(m))
'''+core+GEOMETRY+r'''
template<unsigned Command> void check(std::array<uint16_t,18> r) {
    mk2::BootVideo native; mk2::BoardBootControls board; midtunit_video_device original;
    native.dma_registers=r; native.dma_palette=r[8]; std::fill(native.vram.begin(),native.vram.end(),0x1234);
    static const std::vector<uint8_t> empty,pattern=[] {
        std::vector<uint8_t> data(16*1024*1024);
        for(size_t i=0;i<data.size();++i)data[i]=uint8_t(i^(i>>7)^(i>>13));
        return data;
    }();
    const auto& graphics=(Command&15)==12?empty:pattern;
    auto& s=original.m_dma_state;
    s.gfxrom=graphics.data();s.offset=(Command&15)==12?0:r[2]|(uint32_t(r[3])<<16);
    if(s.offset>=0xf8000000)s.offset-=0xf8000000;  // the driver's DMA source alias, as the fight harness
    s.palette=r[8]&0x7f00;s.color=r[9]&0xff;s.xpos=r[4]&0x3ff;s.ypos=r[5]&0x1ff;
    s.width=r[6]&0x3ff;s.height=r[7]&0x3ff;s.xstep=s.ystep=0x100;
    s.preskip=(Command>>8)&3;s.postskip=(Command>>10)&3;s.startskip=0;s.endskip=r[0];
    s.topclip=r[12]&0x1ff;s.botclip=r[13]&0x1ff;s.leftclip=r[16]&0x3ff;s.rightclip=r[17]&0x3ff;
    s.yflip=Command&0x20;
    if constexpr((Command&15)==12)
        original.dma_draw<(Command>>12)&7,bool(Command&0x10),bool(Command&0x80),false,
                          midtunit_video_device::PIXEL_COLOR,midtunit_video_device::PIXEL_COLOR>();
    else
        original.dma_draw<(Command>>12)&7,bool(Command&0x10),bool(Command&0x80),false,
                          midtunit_video_device::PIXEL_SKIP,midtunit_video_device::PIXEL_COPY>();
    const auto pixels=native.StartDma(Command,board,graphics);
    if(pixels!=unsigned(s.width*s.height) || native.vram!=original.m_local_videoram ||
       board.dma_command!=Command || board.io[18]&2)throw std::runtime_error("Pinned DMA framebuffer differs");
}
int main() { try {
    // The release route's DMA modes; synthetic geometry (test_first_fight_video.GEOMETRY), no Original registers.
    unsigned n=0;  // DMA control before the start: idle on even cases, the command itself on odd ones
    for(unsigned command:{0xc002u,0xc012u,0xe582u,0xf002u,0x900cu,0xe982u,0xf00cu})
        for(auto r:geometry(command,256)) {
            if(n++&1)r[1]=uint16_t(command);
            switch(command) {
            case 0xc002:check<0xc002>(r);break; case 0xc012:check<0xc012>(r);break; case 0xe582:check<0xe582>(r);break;
            case 0xf002:check<0xf002>(r);break; case 0x900c:check<0x900c>(r);break; case 0xe982:check<0xe982>(r);break;
            default:check<0xf00c>(r);
            }
        }
} catch(const std::exception& e) { std::cerr<<e.what();return 1; } }
'''
        with quality.scratch_tree() as (scratch,cleanup):
            cpp=scratch/'dma.cpp';cpp.write_text(source,encoding='utf-8');exe=scratch/'dma.exe'
            cc=quality.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                                   '-I'+str(run.ROOT),cpp,'-o',exe],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([exe],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
        self.assertFalse(cleanup['exists_after'])

    def test_offset_to_postincrement_move_keeps_lanes_flags_and_five_cycles(self):
        code=generated.emit_instruction(0x100,32,'MOVE *A5(40h),*A1+,1',
                                        (0,0),{0x100,0x120},{})
        self.compile_and_run('''
    s.next_pc=0x100; s.status=0x80200406;
    s.a[5]=0x01000000; s.a[1]=0x01000080; out->main_ram[4]=0xabcd;
    {'''+code+'''}
    if(s.cycles!=5 || s.instructions!=1 || s.next_pc!=0x120 ||
       s.status!=0x80200406 || s.a[5]!=0x01000000 || s.a[1]!=0x01000090 ||
       out->main_ram[8]!=0xabcd || out->bus.size()!=2) return 1;
    if(out->bus[0].kind!='r' || out->bus[1].kind!='w' ||
       out->bus[0].address_bit!=0x01000040 || out->bus[1].address_bit!=0x01000080 ||
       out->bus[0].value!=0xabcd || out->bus[1].value!=0xabcd ||
       out->bus[0].cycle || out->bus[1].cycle) return 2;
''')

    def test_read_only_protection_writes_keep_latch_and_every_bus_lane(self):
        self.compile_and_run(r'''
    o.Write16(0x00f42820,0xfe00); out->bus.clear();
    for(uint32_t address:{0x01a190e0u,0x01a190f0u,0x01a191c0u,0x01a191d0u,
                         0x01a3d0c0u,0x01a3d0d0u,0x01a3d0e0u,0x01a3d0f0u,
                         0x01d9d1e0u,0x01d9d1f0u,0x01def920u,0x01def930u}) {
        o.Write16(address,0xff00);
        if(out->bus.back().kind!='w' || out->bus.back().address_bit!=address ||
           out->bus.back().value!=0xff00 || s.board.protection.Read()!=0xfe00) return 1;
    }
    if(out->bus.size()!=12 || s.cycles || s.instructions) return 2;
    bool rejected=false;
    try { o.Write16(0x01a3d100,0); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || out->bus.size()!=12 || s.board.protection.Read()!=0xfe00) return 3;
''')

    def test_protection_latch_aliases_and_continuation_preserve_the_word(self):
        self.compile_and_run(r'''
    s.next_pc=0x100; s.status=0x30;
    o.Write16(0x00f42820,0xfe00);
    for(uint32_t address:{0x01a190e0u,0x01a190f0u,0x01a3d0c0u,0x01a3d0d0u,0x01a3d0e0u,0x01a3d0f0u})
        if(o.Read16(address)!=0xfe00) return 1;
    if(o.Read16(0x01a191c0)!=0x7f00 || o.Read16(0x01a191d0)!=0x7f00) return 2;
    o.Write16(0x00f20c70,0x8001);
    auto continuation=std::make_unique<mk2::BootContinuation>(); continuation->ready=s;
    mk2::BootOps next(program,*machine,*continuation);
    if(next.Read16(0x01a190e0)!=0x8001 || next.Read16(0x01a191c0)!=0x4000 ||
       next.Read16(0x01def920)!=2 || s.board.protection.Read()!=0x8001) return 3;
    if(out->bus.front().kind!='w' || out->bus.front().address_bit!=0x00f42820 ||
       out->bus.front().value!=0xfe00) return 4;
''')

    def test_release_comparator_requires_exact_latch_state_and_complete_schema(self):
        native={key:[] for key in batch_reference.ARRAY_KEYS}
        native['batch_protection']=[0xfe00]
        observed={**native,'batch_protection':[0x8001]}
        self.assertFalse(batch_reference.compare(native,observed,instruction_trace=False)['passed'])
        try:
            result=batch_reference.compare(native,observed,instruction_trace=False,protection=True)
        except TypeError as error:self.fail('Protection state comparison missing: '+str(error))
        self.assertFalse(result['passed'])
        self.assertEqual(result['first_difference'],'batch_protection')
        observed['batch_protection']=[0xfe00]
        self.assertTrue(batch_reference.compare(native,observed,instruction_trace=False,protection=True)['passed'])
        for changed in ({key:value for key,value in observed.items() if key!='batch_protection'},
                        {**observed,'unconsumed':[1]},
                        {**observed,'batch_protection':[]}):
            self.assertFalse(batch_reference.compare(native,changed,instruction_trace=False,protection=True)['passed'])

    def test_protection_constant_aliases_and_movb_preserve_real_bus_reads(self):
        code=generated.emit_instruction(0x100,16,'MOVB *A0,A9',(0x8e09,),{0x100,0x110},{})
        self.compile_and_run('''
    s.next_pc=0x100; s.status=0x40000030;
    for(uint32_t address:{0x01d9d1e0u,0x01d9d1f0u,0x01def920u,0x01def930u}) {
        if(o.Read16(address)!=2 || out->bus.back().address_bit!=address ||
           out->bus.back().value!=2 || out->bus.back().kind!='r') return 1;
    }
    out->bus.clear(); s.a[0]=0x01def920;
    {'''+code+'''}
    if(s.a[9]!=2 || s.a[0]!=0x01def920 || s.status!=0x40000030 ||
       s.cycles!=3 || s.instructions!=1 || s.next_pc!=0x110 || out->bus.size()!=1 ||
       out->bus[0].pc!=0x100 || out->bus[0].address_bit!=0x01def920 ||
       out->bus[0].value!=2 || out->bus[0].cycle!=0) return 2;
    bool rejected=false;
    try { o.Read16(0x01def940); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || out->bus.size()!=1) return 3;
''')

    def test_setf_one_preserves_other_status_bits_and_costs_two_cycles(self):
        try:
            code=generated.emit_instruction(0x100,16,'SETF 10h,0,1',(0x0750,),{0x100,0x110},{})
        except ValueError as error:self.fail('Measured SETF1 rejected: '+str(error))
        self.compile_and_run('''
    s.next_pc=0x100; s.status=0xf6a00fff; out->main_ram[0]=0x8001;
    {'''+code+'''}
    if(s.status!=0xf6a0043f || s.next_pc!=0x110 || s.cycles!=2 || s.instructions!=1 ||
       o.ReadField(0x01000000,1)!=0x8001) return 1;
    o.SetField(0x30,0x120);
    if(s.status!=0xf6a00430 || s.cycles!=3 || s.instructions!=2 ||
       o.ReadField(0x01000000,0)!=0xffff8001 || o.ReadField(0x01000000,1)!=0x8001) return 2;
''')
        with self.assertRaises(ValueError):
            generated.emit_instruction(0x100,16,'SETF 10h,0,2',(0,),{0x100,0x110},{})

    def test_cold_release_admission_rejects_without_mutating_devices_or_bounds(self):
        self.compile_and_run(r'''
    const auto registers=machine->dsp.Registers(),device=machine->dsp.DeviceState();
    const auto io=s.board.io;
    bool rejected=false;
    try { machine->AdmitStartRelease(s.board); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->CoinPairAdmitted() || s.board.CoinPairAdmitted() ||
       machine->LastMainCycles() || machine->dsp.Registers()!=registers ||
       machine->dsp.DeviceState()!=device || s.board.io!=io || !s.board.input_events.empty()) return 1;
    rejected=false;
    try { s.board.HorizontalCount(7005801); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected) return 2;
    rejected=false;
    try { machine->MainInstruction(7005801); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->LastMainCycles()) return 3;
''')

    def test_release_mode_rejects_mixed_endpoints_and_preserves_measured_limits(self):
        calls=[lambda:run.run('check',run.ROOT/'roms/mk2',start_release=True),
               lambda:run.run('reset',run.ROOT/'roms/mk2',batch=True,start_release=True,start_input=True),
               lambda:run.run('reset',run.ROOT/'roms/mk2',batch=True,start_release=True,prestart_window=0),
               lambda:batch_reference.capture(Path('unused'),start_release=True,prestart_window=0)]
        for call in calls:
            try:
                with self.assertRaises(ValueError):call()
            except TypeError as error:self.fail('Start release API missing: '+str(error))
        try:
            from tools.mk2 import generate_start_release as release
        except ImportError as error:self.fail('Measured release manifest missing: '+str(error))
        self.assertEqual((release.START,release.END,release.CPU_ROWS,release.PHYSICAL_ROWS),
                         (23108559,24004881,389582,727879))


if __name__=='__main__':unittest.main()
