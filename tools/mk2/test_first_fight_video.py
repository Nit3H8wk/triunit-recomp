"""Fight DMA modes against the exact pinned blitter template, every framebuffer word and the DMA cost."""
import hashlib,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import run
from tools.quality import run as quality


# DMA command words of the first-fight route (mode encodings: BPP, skip, flip and pixel-op bits, as opcode classes).
# The Original register contexts are not versioned; GEOMETRY below sweeps synthetic positions, sizes, clips, edge
# skips, palettes and source aliases for every mode. Scaled modes: the route's E002 shrink and D002 zoom steps.
FIGHT_COMMANDS=(0x9008,0x900c,0xa002,0xa00c,0xb082,0xb182,0xb582,0xc002,0xc012,0xc082,0xc092,0xc192,0xc482,0xc582,
    0xc592,0xc692,0xd002,0xd082,0xd092,0xd182,0xd192,0xd282,0xd382,0xd582,0xd592,0xd682,0xd692,0xd882,0xe002,0xe008,
    0xe012,0xe082,0xe088,0xe092,0xe098,0xe182,0xe188,0xe192,0xe198,0xe282,0xe382,0xe482,0xe488,0xe492,0xe498,0xe582,
    0xe588,0xe592,0xe598,0xe5b2,0xe682,0xe692,0xe698,0xe782,0xe792,0xe882,0xe888,0xe892,0xe898,0xe982,0xe992,0xe998,
    0xea82,0xea92,0xea98,0xeb82,0xed82,0xed92,0xed98,0xef82,0xf002,0xf00c,0x8423,0x800c)
SCALED=tuple((0xe002,step) for step in range(0x120,0x301,0x20))+tuple((0xd002,step) for step in range(0x40,0x301,0x20) if step!=0x100)
GEOMETRY=r'''
// Synthetic DMA geometry, no Original register value: centred, X/Y wraps in both directions, a one-line clip
// window, edge-skip encodings, a clip box on every side, the 0xf8000000 source alias with narrow X clips, and a
// double-buffer half; each at four sizes, palette/colour varied per case.
std::vector<std::array<uint16_t,18>> geometry(unsigned command,unsigned step) {
    std::vector<std::array<uint16_t,18>> out;
    const bool fill=(command&15)==12;
    const unsigned sizes[][2]={{1,1},{7,3},{35,45},{161,13}};
    for(unsigned mode=0;mode<8;++mode) for(const auto& size:sizes) {
        const unsigned w=size[0],h=size[1];
        std::array<uint16_t,18> r{};
        const uint32_t source=fill?0u:(mode==5?0xf8000000u:0u)+0x12340u+mode*0x40000u+w*7u;
        r[0]=mode==3?uint16_t(command&0x40?(w/3)|((w/4)<<8):w/3):0;
        r[2]=uint16_t(source);r[3]=uint16_t(source>>16);
        r[4]=uint16_t(mode==1?0:mode==2?1023-w/2:mode==6?250:mode==7?w/2:256);
        r[5]=uint16_t(mode==1?511-h/2:mode==6?300:mode==3?100:mode==7?h/2:256);
        r[6]=uint16_t(w);r[7]=uint16_t(h);
        r[8]=uint16_t((mode*0x1500u+w)^0x8023u);r[9]=uint16_t(0xa500u|((mode*53u+w)&0xff));
        r[10]=r[11]=uint16_t(step);
        r[12]=uint16_t(mode==2?257:mode==6?256:mode==4?260:0);r[13]=uint16_t(mode==2?257:mode==6?509:mode==4?270:511);
        r[16]=uint16_t(mode==5?250:mode==4?262:0);r[17]=uint16_t(mode==5?254:mode==4?280:mode==6?511:1023);
        out.push_back(r);
    }
    return out;
}
'''


class FirstFightVideoTests(unittest.TestCase):
    def test_all_fight_mode_scale_contexts_match_every_framebuffer_word_and_dma_cost(self):
        upstream=(run.ROOT/'docs/investigation/sources/midtunit_v.cpp').read_text(encoding='utf-8')
        core=upstream.split('/*** core blitter routine macro ***/')[1].split('DEFINE_TEMPLATED_DMA_DRAW_GROUP')[0]
        self.assertEqual(hashlib.sha256(core.encode()).hexdigest(),
                         '63b6dbaca7057fa9590c2283baf3699179cc91e3eddd4120425a23f7a457c8a2')
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
    std::vector<uint16_t> m_local_videoram=std::vector<uint16_t>(524288);
    template<int BitsPerPixel,bool XFlip,bool Skip,bool Scale,op_type_t Zero,op_type_t NonZero> void dma_draw();
};
#define EXTRACTGEN(m) (((base[o>>3]|(base[(o>>3)+1]<<8))>>(o&7))&(m))
'''+core+GEOMETRY+r'''
const std::vector<uint8_t>& test_graphics(bool fill) {
    static const std::vector<uint8_t> empty;
    static const auto graphics=[] {
        std::vector<uint8_t> data(16*1024*1024);
        for(size_t i=0;i<data.size();++i)data[i]=uint8_t(i^(i>>7)^(i>>13));
        return data;
    }();
    return fill?empty:graphics;
}
const std::vector<uint16_t>& test_framebuffer() {
    static const auto pixels=[] {
        std::vector<uint16_t> data(524288);
        for(size_t i=0;i<data.size();++i)data[i]=uint16_t(i*73u^(i>>7)^0x1234u);
        return data;
    }();
    return pixels;
}
// Reuse allocation only; every case restores all VRAM words and every DMA state field.
mk2::BootVideo native_video;
midtunit_video_device original_video;
template<unsigned Command,bool Scale> void check(std::array<uint16_t,18> r) {
    auto& native=native_video;auto& original=original_video;mk2::BoardBootControls board;
    native.dma_registers=r;native.dma_palette=r[8];board.io[18]=0x402;
    native.vram=original.m_local_videoram=test_framebuffer();
    const auto& graphics=test_graphics((Command&15)==12);
    constexpr unsigned Bpp=((Command>>12)&7)?((Command>>12)&7):8;
    auto& s=original.m_dma_state;
    s.gfxrom=graphics.data();s.offset=(Command&15)==12?0:r[2]|(uint32_t(r[3])<<16);
    if(s.offset>=0xf8000000)s.offset-=0xf8000000;
    s.palette=r[8]&0x7f00;s.color=r[9]&0xff;s.xpos=r[4]&0x3ff;s.ypos=r[5]&0x1ff;
    s.width=r[6]&0x3ff;s.height=r[7]&0x3ff;s.xstep=r[10]?r[10]:0x100;s.ystep=r[11]?r[11]:0x100;
    s.preskip=(Command>>8)&3;s.postskip=(Command>>10)&3;
    s.startskip=Command&0x40?r[0]&0xff:0;s.endskip=Command&0x40?r[0]>>8:r[0];
    s.topclip=r[12]&0x1ff;s.botclip=r[13]&0x1ff;s.leftclip=r[16]&0x3ff;s.rightclip=r[17]&0x3ff;
    s.yflip=Command&0x20;
    static_assert((Command&15)==2 || (Command&15)==3 || (Command&15)==8 || (Command&15)==12);
    if constexpr((Command&15)==12)
        original.dma_draw<Bpp,bool(Command&0x10),bool(Command&0x80),Scale,
                          midtunit_video_device::PIXEL_COLOR,midtunit_video_device::PIXEL_COLOR>();
    else if constexpr((Command&15)==8)
        original.dma_draw<Bpp,bool(Command&0x10),bool(Command&0x80),Scale,
                          midtunit_video_device::PIXEL_SKIP,midtunit_video_device::PIXEL_COLOR>();
    else if constexpr((Command&15)==3)
        original.dma_draw<Bpp,bool(Command&0x10),bool(Command&0x80),Scale,
                          midtunit_video_device::PIXEL_COPY,midtunit_video_device::PIXEL_COPY>();
    else
        original.dma_draw<Bpp,bool(Command&0x10),bool(Command&0x80),Scale,
                          midtunit_video_device::PIXEL_SKIP,midtunit_video_device::PIXEL_COPY>();
    const auto pixels=native.StartDma(Command,board,graphics);
    const unsigned expected=Scale?((s.width<<8)/s.xstep)*((s.height<<8)/s.ystep):s.width*s.height;
    r[1]=Command;
    if(pixels!=expected || native.vram!=original.m_local_videoram || native.DmaRegisters(board)!=r || board.io[18]!=0x400)
        throw std::runtime_error("Pinned fight DMA framebuffer or completion cost differs");
}
int main() { try {
    // Source starts with zero then nonzero pixels. The second row wraps from Y=0 to Y=511.
    check<0x8423,false>({0,0,0,0,20,0,3,2,0xff23,0x5a,256,256,0,511,0,48,0,511});
'''
        for command in FIGHT_COMMANDS:
            source+=f'    for(const auto& r:geometry(0x{command:04x},256))check<0x{command:04x},false>(r);\n'
        for command,step in SCALED:
            source+=f'    for(const auto& r:geometry(0x{command:04x},{step}))check<0x{command:04x},true>(r);\n'
        source+=r'''
    // D012: 5bpp, no row headers, X flip, transparent zero; compare every VRAM word.
    for(unsigned bit=0;bit<8;++bit)
    for(unsigned width: {0u,1u,2u,7u,31u,1023u})
    for(unsigned mode=0;mode<6;++mode) {
        std::array<uint16_t,18> r{};
        r[0]=mode==3?uint16_t(width+1):mode==4?2:0;
        const uint32_t source=(mode==5?0xf8000000u:0u)+bit+0x12340;
        r[2]=uint16_t(source);r[3]=uint16_t(source>>16);
        r[4]=mode==1?0:mode==2?1023:256;r[5]=mode==1?511:256;
        r[6]=uint16_t(width);r[7]=mode==0?0:3;r[8]=0xff23;
        r[10]=r[11]=mode==4?0:256;
        r[12]=mode==2?257:0;r[13]=mode==2?257:511;
        r[16]=mode==5?250:0;r[17]=mode==5?254:1023;
        check<0xd012,false>(r);
        check<0xd492,false>(r);
        check<0xb002,false>(r);
        check<0x9002,false>(r);
        check<0x9012,false>(r);
        check<0x9042,false>(r);
        check<0x9052,false>(r);
        check<0xa012,false>(r);
        check<0xa042,false>(r);
        check<0xa052,false>(r);
        check<0xe022,false>(r);
        check<0xe032,false>(r);
        check<0xe062,false>(r);
        check<0xe072,false>(r);
'''
        # Uncompressed transparent copy, both X directions and both start/end skip encodings.
        for bpp in (0,1,2,3,4,5,6,7):
            for flip in (0,0x10):
                for dualskip in (0,0x40):
                    source+=f'        check<0x{0x8002+(bpp<<12)+flip+dualskip:04x},false>(r);\n'
                    source+=f'        check<0x{0x8022+(bpp<<12)+flip+dualskip:04x},false>(r);\n'
        # All 16 source pre/post pairs, both X directions, one pinned unscaled mode.
        for bpp in (0,1,2,3,4,5,6,7):
            for pair in range(16):
                for flip in (0,0x10):
                    source+=f'        check<0x{0x8082+(bpp<<12)+(pair<<8)+flip:04x},false>(r);\n'
                    source+=f'        check<0x{0x80a2+(bpp<<12)+(pair<<8)+flip:04x},false>(r);\n'
        for pair in range(16):
            for flips in (0,0x10,0x20,0x30):
                source+=f'        check<0x{0xe088+(pair<<8)+flips:04x},false>(r);\n'
        # Every non-skipping unscaled color-fill BPP encoding and independent X/Y flip.
        source+='        r[8]=uint16_t((mode*0x1500u+width+bit)^0x8023u); r[9]=uint16_t(0xa500u|((mode*53u+width+bit)&0xff));\n'
        # E048 belongs to uncompressed transparent/color: every BPP, X/Y flip and dual-skip flag.
        for bpp in range(8):
            for flips in (0,0x10,0x20,0x30):
                for dualskip in (0,0x40):
                    source+=f'        check<0x{0x8008+(bpp<<12)+flips+dualskip:04x},false>(r);\n'
        for bpp in range(8):
            for flips in (0,0x10,0x20,0x30):
                source+=f'        check<0x{0x800c+(bpp<<12)+flips:04x},false>(r);\n'
        source+=r'''
    }
    // Exhaust every admissible encoded uniform shrink step, restoring and comparing all VRAM.
    for(unsigned step=0x100;step<=0xffff;++step) {
        std::array<uint16_t,18> r{};
        r[0]=1;r[2]=3;r[4]=1023;r[5]=511;r[6]=7;r[7]=5;r[8]=0xff23;
        r[10]=r[11]=uint16_t(step);r[13]=511;r[17]=1023;
        check<0xe002,true>(r);
        check<0xd002,true>(r);
    }
    for(unsigned step=0x40;step<0x100;++step) {
        std::array<uint16_t,18> r{};
        r[0]=1;r[2]=3;r[4]=1023;r[5]=511;r[6]=7;r[7]=5;r[8]=0xff23;
        r[10]=r[11]=uint16_t(step);r[13]=511;r[17]=511;
        check<0xd002,true>(r);
    }
    for(unsigned step:{257u,287u,289u,768u,769u,1213u,65535u})
    for(unsigned bit=0;bit<8;++bit)
    for(unsigned width:{0u,1u,7u,31u,1023u})
    for(unsigned mode=0;mode<6;++mode) {
        std::array<uint16_t,18> r{};
        r[0]=mode==3?uint16_t(width+1):mode==4?2:0;
        const uint32_t source=(mode==5?0xf8000000u:0u)+bit+0x12340;
        r[2]=uint16_t(source);r[3]=uint16_t(source>>16);
        r[4]=mode==1?0:mode==2?1023:256;r[5]=mode==1?511:256;
        r[6]=uint16_t(width);r[7]=mode==0?0:5;r[8]=0xff23;
        r[10]=r[11]=uint16_t(step);
        r[12]=mode==2?257:0;r[13]=mode==2?257:511;
        r[16]=mode==5?250:0;r[17]=mode==5?254:1023;
        check<0xe002,true>(r);
        check<0xd002,true>(r);
    }
    for(const auto& item:std::array<std::array<uint16_t,2>,7>{{{0xe003,256},{0xe002,128},{0xe082,288},{0xe5b9,256},{0xe5b8,257},{0xe048,257},{0xe049,256}}}) {
        mk2::BootVideo native;mk2::BoardBootControls board;board.io[18]=2;
        native.dma_registers[6]=native.dma_registers[7]=1;
        native.dma_registers[10]=native.dma_registers[11]=item[1];
        const auto before=native.vram;bool rejected=false;
        try {native.StartDma(item[0],board,std::vector<uint8_t>(2,1));}
        catch(const std::exception&){rejected=true;}
        if(!rejected || native.vram!=before || board.dma_command || board.io[18]!=2) return 2;
    }
    {
        mk2::BootVideo native;mk2::BoardBootControls board;board.io[18]=0x402;board.dma_command=0x1234;
        native.dma_registers[6]=native.dma_registers[7]=1;
        native.dma_registers[10]=257;native.dma_registers[11]=258;
        const auto before=native.vram;const auto registers=native.DmaRegisters(board);bool rejected=false;
        try {native.StartDma(0xe002,board,{1,0});}catch(const std::exception&){rejected=true;}
        if(!rejected || native.vram!=before || native.DmaRegisters(board)!=registers || board.io[18]!=0x402)return 4;
    }
    for(const auto& item:std::array<std::array<uint16_t,2>,6>{{{0xd013,256},{0xd012,768},{0xd002,63},{0xd033,256},{0x8423,257},{0x84a3,256}}}) {
        mk2::BootVideo native;mk2::BoardBootControls board;board.io[18]=0x402;board.dma_command=0x1234;
        native.dma_registers[6]=native.dma_registers[7]=1;
        native.dma_registers[10]=native.dma_registers[11]=item[1];
        const auto before=native.vram;const auto registers=native.DmaRegisters(board);bool rejected=false;
        try {native.StartDma(item[0],board,{1,0});}catch(const std::exception&){rejected=true;}
        if(!rejected || native.vram!=before || native.DmaRegisters(board)!=registers || board.io[18]!=0x402)return 3;
    }
    // New fill admission excludes row headers, dual-skip and every scaled variant.
    for(const auto& item:std::array<std::array<uint16_t,2>,4>{{{0x808c,256},{0x804c,256},{0x800c,257},{0x803c,128}}}) {
        mk2::BootVideo native;mk2::BoardBootControls board;board.io[18]=0x402;board.dma_command=0x1234;
        native.dma_registers[6]=native.dma_registers[7]=1;
        native.dma_registers[10]=native.dma_registers[11]=item[1];
        const auto before=native.vram;const auto registers=native.DmaRegisters(board);bool rejected=false;
        try {native.StartDma(item[0],board,{});}catch(const std::exception&){rejected=true;}
        if(!rejected || native.vram!=before || native.DmaRegisters(board)!=registers || board.io[18]!=0x402)return 5;
    }
} catch(const std::exception& e) { std::cerr<<e.what();return 1; } }
'''
        with quality.scratch_tree() as (scratch,cleanup):
            cpp=scratch/'fight-dma.cpp';cpp.write_text(source,encoding='utf-8');exe=scratch/'fight-dma.exe'
            cc=quality.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                                   '-I'+str(run.ROOT),cpp,'-o',exe],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([exe],scratch,env=env,timeout=240)
            self.assertTrue(result['passed'],quality.compact(result))
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
