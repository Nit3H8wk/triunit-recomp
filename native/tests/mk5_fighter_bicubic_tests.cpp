#include "mk5_fighter_bicubic.hpp"
#include "mk5_fighter_video.hpp"
#include <iostream>
#include <utility>

using mk5presentation::FighterLayer;

static FighterLayer pose(int x,int y,unsigned w,unsigned h,unsigned seed){
    FighterLayer layer{x,y,w,h,true,{}};
    constexpr unsigned opacity[]{0,255,127,63,254,1,255};
    for(unsigned i=0;i<w*h;++i)
        layer.pixels.push_back((opacity[(i+seed)%7]<<24)|(((i*47+seed)&255)<<16)|
                               (((i*19+127)&255)<<8)|((i*97+3)&255));
    return layer;
}

static void check(uint64_t expected,const std::vector<uint32_t>& pixels){
    uint64_t hash=14695981039346656037ull;
    for(auto pixel:pixels)hash=(hash^pixel)*1099511628211ull;
    if(hash!=expected)throw std::runtime_error("Pillow 11.1.0 RGBA reference mismatch");
}

static void check_capture(){
    using namespace mk5presentation;
    FighterSlots slots;
    constexpr uint32_t slot=0x01010000;
    slots.Bind(slot);
    const auto old_generation=slots.Generation(slot);
    slots.Bind(slot);
    if(!old_generation || slots.Generation(slot)!=old_generation)
        throw std::runtime_error("Binding an existing actor changed its generation");
    slots.Forget(slot);
    if(slots.Generation(slot))throw std::runtime_error("Freed fighter still has a generation");
    slots.Bind(slot);
    if(slots.Generation(slot)<=old_generation)
        throw std::runtime_error("Reused fighter slot kept an old generation");
    FighterSurface vram(1024);
    const uint16_t backdrop=0x8005;
    vram.Clear(0,512,backdrop);
    vram.Clear(512,512,backdrop);
    auto fighter=vram.Draw(0x01010000);
    vram.Write(fighter,10,8);
    vram.Write(fighter,512+10,8);
    auto component=vram.Draw(0x01010000);
    vram.Write(component,11,7);
    auto other=vram.Draw(0);
    vram.Write(other,11,7);
    vram.Write(other,12,9);
    auto second=vram.Draw(0x01020000);
    vram.Write(second,12,2);
    FighterCapture capture;
    capture.Begin(4,2);
    const auto first_palette=[](uint16_t pen){return uint32_t(pen)*0x10101;};
    const auto second_palette=[](uint16_t pen){return uint32_t(pen)*0x10000;};
    const uint32_t first_row[]={0x080808,0x070707,0x020202,0x050505};
    const uint32_t second_row[]={0x080000,0x050000,0x050000,0x050000};
    const uint32_t base_row[]={0x050505,0x050505,0x050505,0x80050505};
    capture.Line(vram,0,0,10,first_row,base_row,first_palette);
    capture.Line(vram,1,512,10,second_row,nullptr,second_palette);
    FighterFrame frame;
    capture.Complete(42,frame);
    if(frame.serial!=42 || frame.layers.size()!=2 || frame.layers[0].width!=2 ||
       frame.layers[0].height!=2 || frame.layers[0].pixels[1]!=0xff070707 ||
       frame.layers[0].pixels[2]!=0xff080000 || frame.underlay[1]!=0x070707 ||
       frame.underlay[2]!=0x090909 || frame.backdrop[0]!=0x80050505 ||
       frame.underlay[4]!=0x050000 || frame.covered!=std::vector<uint8_t>{1,0,1,0,1,0,0,0})
        throw std::runtime_error("Fighter capture lost order, the lower layer or live palette");
    auto scaled=ComposeFighterFrame4x(frame,4,2);
    if(scaled[4]!=0x070707 || !(scaled[6]&0xff000000) || !(scaled[9]&0xff000000) || !(scaled[0]&0xff000000))
        throw std::runtime_error("Fighter composition covered an intervening draw or lost the actor");
    vram.Clear(10,3,backdrop);
    capture.Begin(4,2);
    capture.Line(vram,0,0,10,first_row,base_row,first_palette);
    capture.Line(vram,1,512,10,second_row,nullptr,second_palette);
    capture.Complete(43,frame);
    if(frame.layers.size()!=1 || frame.layers[0].y!=1 || frame.layers[0].width!=1)
        throw std::runtime_error("Fighter clear retained expired coverage");
    vram.Clear(0,1024,backdrop);
    auto clipped=vram.Draw(0x01010000);
    vram.Write(clipped,9,8);
    vram.Write(clipped,10,8);
    capture.Begin(4,2);
    capture.Line(vram,0,0,10,first_row,base_row,first_palette);
    capture.Line(vram,1,512,10,second_row,nullptr,second_palette);
    capture.Complete(44,frame);
    if(frame.layers.size()!=1 || frame.layers[0].x!=-1 || frame.layers[0].width!=2 ||
       frame.layers[0].pixels[0]!=0xff080808)
        throw std::runtime_error("Scanout clipped a texel that contributes to the visible fighter edge");
    auto cover=vram.Draw(0);
    for(unsigned y=0;y<2;++y)
        for(unsigned x=10;x<14;++x)vram.Write(cover,y*512+x,5);
    capture.Begin(4,2);
    capture.Line(vram,0,0,10,base_row,base_row,first_palette);
    capture.Line(vram,1,512,10,second_row,nullptr,second_palette);
    capture.Complete(45,frame);
    if(frame.serial || !frame.layers.empty())
        throw std::runtime_error("Fighter capture retained a pose behind an opaque cover");
}

int main(int argc,char**){
    try{
        using namespace mk5presentation;
        const auto first=pose(0,1,7,5,3),second=pose(4,2,4,6,11);
        const auto first_scaled=ScaleFighter4x(first),second_scaled=ScaleFighter4x(second);
        check(0x39b769b452b1a0dfull,first_scaled);
        check(0x00d20a4dd881091aull,second_scaled);
        auto flipped=first;
        for(unsigned y=0;y<first.height;++y)
            std::reverse(flipped.pixels.begin()+y*first.width,flipped.pixels.begin()+(y+1)*first.width);
        auto flipped_scaled=ScaleFighter4x(flipped);
        const unsigned stride=(first.width+4)*4;
        for(unsigned y=0;y<(first.height+4)*4;++y){
            const auto row=y*stride;
            for(unsigned x=0;x<stride;++x)
                if(flipped_scaled[row+x]!=first_scaled[row+stride-x-1])
                    throw std::runtime_error("Fighter horizontal flip changes the filter");
        }
        std::vector<uint32_t> composed;
        for(unsigned y=0;y<32;++y)
            for(unsigned x=0;x<40;++x)
                composed.push_back(x<20?0xffe7ded3:0xff17263d);
        const FighterLayer between{3,3,1,3,false,{0xff11f129,0xff11f129,0xff11f129}};
        const FighterLayer front{8,5,1,1,false,{0xfffd0881}};
        ComposeFighters4x(composed,10,8,{first,between,second,front});
        check(0xdfd0b849637f1b32ull,composed);
        check_capture();
        if(argc>1){
            std::cout<<std::hex;
            for(const auto* pixels:{&first_scaled,&second_scaled,&std::as_const(composed)}){
                for(auto pixel:*pixels)std::cout<<pixel<<' ';
                std::cout<<'\n';
            }
        }else std::cout<<"PASS bicubic RGBA, flip, transparent margin and draw order\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}
}
