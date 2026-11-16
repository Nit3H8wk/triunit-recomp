#include "../mk2/mk2_scanout.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
template<class F> void rejects(F action) {
    bool rejected=false;
    try { action(); } catch(const std::runtime_error&) { rejected=true; }
    require(rejected,"invalid scanout accepted");
}

void first_fighter_dma(bool first_line_enabled) {
    mk2::BootVideo video;
    mk2::BoardBootControls board;
    board.io[1]=50;board.io[2]=52;board.io[3]=252;
    board.io[5]=20;board.io[6]=22;board.io[7]=288;board.io[8]=0x6410;
    board.io[27]=255;
    video.EnableBackdrop();
    video.EnableFighters();
    constexpr uint32_t slot=0x0102d6f0;
    video.BindFighter(slot);
    const auto owner=video.FighterGeneration(slot);
    require(owner && !video.FighterVideo().enabled(),"fighter slots precede surface allocation");
    video.palette_ram[1]=0x7c00;video.palette_ram[2]=0x03e0;video.palette_ram[3]=0x001f;
    video.vram[1022]=1;video.vram[1534]=2;
    video.CopyBackdrop(512,1024,true);
    mk2::Scanout scanout(true);
    if(first_line_enabled)board.io[8]|=0x8000;
    board.vcount=20;board.display_address=0x10;scanout.Line(board,video);
    video.palette_ram[1]=0x7fff;

    auto& dma=video.dma_registers;
    dma[4]=dma[17]=510;dma[5]=dma[12]=dma[13]=2;dma[6]=dma[7]=1;dma[9]=3;
    video.StartDma(0x800c,board,{},false,owner);
    require(video.FighterVideo().enabled(),"first fighter DMA allocates its surface");
    board.io[8]|=0x8000;
    board.vcount=21;board.display_address=0x20;scanout.Line(board,video);
    board.vcount=22;scanout.Line(board,video);
    const auto& frame=scanout.fighter_frame();
    require(frame.serial==1 && frame.layers.size()==1 && frame.layers.front().pixels.front()==0xff0000ff,
            "the first partial fighter frame retains its actor");
    require(frame.underlay.at(0)==(first_line_enabled?0xff0000:0) &&
            frame.opaque_order.at(0)==(first_line_enabled?0:UINT64_MAX) &&
            frame.backdrop.at(0)==(first_line_enabled?(mk5stage::scenery|0xff0000):0),
            "rows before the first actor retain their observed palette, scenery and blanking");
    require(frame.covered.at(4) && frame.underlay.at(4)==0x00ff00 &&
            frame.backdrop.at(4)==(mk5stage::scenery|0x00ff00),
            "the first actor preserves the scenery it covers");
}

void blood_in_front_of_retained_fighter() {
    mk2::Program splash;
    constexpr auto descriptor=(0xffbecd10u-0xff800000u)/8;
    splash.bytes.resize(descriptor+14);
    splash.bytes[descriptor]=35;
    splash.bytes[descriptor+2]=11;
    splash.bytes[descriptor+13]=0x90;
    splash.graphics.assign(50,0xff);

    mk2::BootVideo video;
    video.EnableBlood(splash);
    video.EnableFighters();
    video.palette_ram[1]=0x7c00;
    video.palette_ram[0x101]=0x001f;
    mk2::BoardBootControls board;
    board.io[1]=50;board.io[2]=52;board.io[3]=252;
    board.io[5]=20;board.io[6]=21;board.io[7]=288;board.io[8]=0xe410;
    video.dma_registers[6]=video.dma_registers[7]=video.dma_registers[9]=1;
    video.StartDma(0x800c,board,{},false,1);
    video.KeepBlood(0,0,false,0x0100);
    video.DrawBlood(0,0,0,(11u<<16)|35);

    mk2::Scanout scanout(true);
    board.vcount=20;scanout.Line(board,video);
    board.vcount=21;scanout.Line(board,video);
    require(scanout.pixels().at(0)==0xffff0000 && scanout.presentation().at(0)==0xff0000ff,
            "the remastered blood pass covers the retained fighter only in presentation");
    const auto& frame=scanout.fighter_frame();
    require(frame.layers.empty() || (!frame.covered.at(0) && frame.opaque_order.at(0)==UINT64_MAX &&
                                     frame.underlay.at(0)==0x0000ff),
            "the retained fighter layer stays behind the sampled blood");
}
}

int main() { try {
    first_fighter_dma(true);
    first_fighter_dma(false);
    blood_in_front_of_retained_fighter();
    mk2::BootVideo video;
    mk2::BoardBootControls board;
    board.io[1]=50;board.io[2]=52;board.io[3]=252;
    board.io[5]=20;board.io[6]=22;board.io[7]=288;board.io[8]=0xe410;
    board.io[27]=255;
    video.palette_ram[0]=0x7fff;video.palette_ram[1]=0xfc00;
    video.palette_ram[2]=0x03e0;video.palette_ram[3]=0x001f;video.palette_ram[4]=0x7fff;
    video.vram[1022]=0x8001;video.vram[1023]=2;video.vram[512]=3;video.vram[513]=4;
    video.vram[1534]=1;video.vram[1535]=2;video.vram[1024]=3;video.vram[1025]=4;
    const auto original_vram=video.vram;
    mk2::Scanout scanout;
    board.vcount=21;board.display_address=0x20;scanout.Line(board,video);
    board.vcount=22;scanout.Line(board,video);
    require(scanout.frames()==0 && scanout.pixels().empty(),"partial initial frame must not be published");
    board.vcount=20;board.display_address=0x10;scanout.Line(board,video);
    video.palette_ram[1]=0x4210;
    board.vcount=21;board.display_address=0x20;scanout.Line(board,video);
    board.vcount=22;scanout.Line(board,video);
    const std::vector<uint32_t> expected{0xffff0000,0xff00ff00,0xff0000ff,0xffffffff,
                                        0xff848484,0xff00ff00,0xff0000ff,0xffffffff};
    require(scanout.frames()==1 && scanout.width()==4 && scanout.height()==2 && scanout.pixels()==expected,
            "live scanlines retain palette changes, 512-column wrap and masked xRGB555 indices");
    require(video.vram==original_vram && video.palette_ram[1]==0x4210,
            "scanout must not mutate arcade VRAM or palette");
    board.io[8]=0xa410;
    rejects([&]{scanout.Line(board,video);});
    require(scanout.frames()==1 && scanout.pixels()==expected,
            "unsupported interlace rejects before changing the collected frame");

    // Origin inversion and row wrapping select the same physical row as DPYADR 0x10.
    board.io[8]=0xe010;board.io[27]=0x7fff;
    board.vcount=20;board.display_address=0x7fec;scanout.Line(board,video);
    board.vcount=21;board.display_address=0x7fdc;scanout.Line(board,video);
    board.vcount=22;scanout.Line(board,video);
    auto after_palette_change=expected;after_palette_change[0]=0xff848484;
    require(scanout.frames()==2 && scanout.pixels()==after_palette_change,
            "DPYCTL origin and DPYTAP masking preserve original physical addressing");

    video.EnableBackdrop();
    video.CopyBackdrop(512,1024,true);
    auto& dma=video.dma_registers;
    dma[4]=dma[17]=510;dma[5]=dma[12]=dma[13]=1;dma[6]=dma[7]=1;dma[9]=2;
    video.StageDraw(0x0101d540,{true,0});
    video.StageDraw(0x0101d480,{true,0});
    video.StageDraw(0x0101d480,{false,0x01010000});
    require(video.TakeDraw(0x0101d480).fighter==0x01010000,"a reused DMA slot keeps the new owner");
    video.StageDraw(0x0101d480,{false,0x01010000});
    video.StageDraw(0x0101d480,{});
    require(!video.TakeDraw(0x0101d480).fighter,"an unowned DMA clears a stale owner");
    video.StartDma(0x800c,board,{},video.TakeDraw(0x0101d540).scenery);
    require(!video.TakeDraw(0x0101d540).scenery,"DMA ownership is consumed with its command");
    dma[9]=3;
    video.StartDma(0x800c,board,{});
    mk2::Scanout remastered(true);
    board.vcount=20;board.display_address=0x7fec;
    remastered.Line(board,video);scanout.Line(board,video);
    board.vcount=21;board.display_address=0x7fdc;
    remastered.Line(board,video);scanout.Line(board,video);
    board.vcount=22;remastered.Line(board,video);scanout.Line(board,video);
    require(remastered.pixels()==scanout.pixels() && scanout.backdrop_pixels().empty(),
            "the presentation layer does not alter the arcade raster");
    require(remastered.backdrop_pixels().at(0)==0x00ff00 &&
            remastered.backdrop_pixels().at(1)==(mk5stage::scenery|0x00ff00),
            "foreground DMA hides ownership but retains the green scenery behind it");
    const auto composite=mk5stage::Bicubic4x(remastered.presentation(),remastered.backdrop_pixels(),4,2);
    require(composite[0]==0x0000ff && (composite[4]&mk5stage::scenery),
            "opaque MK2 foreground uses the existing ScaleFX path");

    board.io[8]&=uint16_t(~0x8000);
    board.vcount=20;scanout.Line(board,video);remastered.Line(board,video);
    board.vcount=21;scanout.Line(board,video);remastered.Line(board,video);
    board.vcount=22;scanout.Line(board,video);remastered.Line(board,video);
    require(scanout.frames()==4 && scanout.pixels()==std::vector<uint32_t>(8,0xff000000) &&
            remastered.backdrop_pixels().empty(),
            "disabled display produces physical black independently of palette entry zero");
    const auto complete=scanout.pixels();const auto count=scanout.frames();
    board.io[2]=board.io[1];rejects([&]{scanout.Line(board,video);});
    require(scanout.frames()==count && scanout.pixels()==complete,
            "invalid geometry rejects before replacing the completed frame");
    board.io[2]=52;video.vram.resize(1);rejects([&]{scanout.Line(board,video);});
    video.vram.resize(524288);video.palette_ram.resize(1);rejects([&]{scanout.Line(board,video);});
    std::cout<<"PASS MK2 live scanout\n";
} catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;} }
