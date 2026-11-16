#include "../mk2/mk2_scanout.hpp"
#include "../mk2/mk2_boot_ops.hpp"
#include <iostream>
#include <memory>
#include <stdexcept>

int main() { try {
    mk2::Program program;
    auto machine=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
    auto plain=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
    machine->link.HostWrite(0x01d01030,0);machine->link.Synchronize();
    plain->link.HostWrite(0x01d01030,0);plain->link.Synchronize();
    auto out=std::make_unique<mk2::BootContinuation>();
    auto control=std::make_unique<mk2::BootContinuation>();
    auto& b=out->ready.board;
    b.io[1]=50;b.io[2]=52;b.io[3]=252;b.io[5]=20;b.io[6]=22;b.io[7]=288;
    b.io[8]=0xe410;b.io[9]=0x10;b.display_address=0x10;
    control->ready=out->ready;
    out->video.palette_ram[1]=0x7c00;out->video.vram[512]=1;
    out->video.palette_ram[2]=0x03e0;out->video.vram[0]=2;
    mk2::Scanout scanout;
    std::vector<std::array<unsigned,2>> edges;
    machine->SetScanlineObserver([&](const auto& board,const auto& video) {
        edges.push_back({board.vcount,board.display_address});scanout.Line(board,video);
    });
    mk2::BootOps ops(program,*machine,*out),reference(program,*plain,*control);
    for(const unsigned cost:{13836u,395u,395u}) {
        ops.Finish(0x100,cost);reference.Finish(0x100,cost);
    }
    if(edges.size()!=23 || edges[20]!=std::array<unsigned,2>{20,0x10} ||
       edges[21]!=std::array<unsigned,2>{21,0} || edges[22]!=std::array<unsigned,2>{22,0x10})
        throw std::runtime_error("raster observer must sample every edge before DPYADR advances");
    if(scanout.frames()!=1 || scanout.pixels()!=std::vector<uint32_t>{0xffff0000,0xff000000,0xff000000,0xff000000,
                                                                    0xff00ff00,0xff000000,0xff000000,0xff000000})
        throw std::runtime_error("instruction-driven scanout must publish original live rows");
    const auto& a=out->ready;const auto& c=control->ready;
    if(a.a!=c.a || a.b!=c.b || a.status!=c.status || a.cycles!=c.cycles || a.instructions!=c.instructions ||
       b.io!=c.board.io || b.display_address!=c.board.display_address || b.vcount!=c.board.vcount ||
       b.scanline_events!=c.board.scanline_events || b.active_updates!=c.board.active_updates ||
       machine->dsp.Registers()!=plain->dsp.Registers() || machine->LastMainCycles()!=plain->LastMainCycles())
        throw std::runtime_error("observation must preserve CPU, DSP and raster progression");
    machine->SetScanlineObserver({});ops.Finish(0x110,400);
    if(edges.size()!=23)throw std::runtime_error("detached raster observer was invoked");
    std::cout<<"PASS MK2 scanout clock\n";
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;} }
