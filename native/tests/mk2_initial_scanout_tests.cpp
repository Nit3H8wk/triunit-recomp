#include "../mk2/mk2_executor.hpp"
#include "../mk2/mk2_adsp.hpp"
#include "../mk2/mk2_scanout.hpp"
#include <iostream>
#include <memory>

int main(int argc,char** argv) { try {
    if (argc!=2) throw std::runtime_error("expected authenticated MK2 ROM directory");
    const auto program=mk2::LoadProgram(argv[1]);
    const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    auto machine=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    auto plain=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    mk2::Scanout scanout;
    unsigned lines=0;
    std::vector<uint64_t> boundaries;
    machine->SetScanlineObserver([&](const auto& board,const auto& video) {
        ++lines;
        const auto count=scanout.frames();scanout.Line(board,video);
        if (count!=scanout.frames())
            boundaries.push_back(94875+uint64_t(board.scanline_events-1)*6325);
    });
    // Generated closure from reset to the end of the original video initialization.
    auto run=[&](auto& m) {
        mk2::GeneratedBoot generated(program,m,nullptr,0xfc7d);
        generated.RunTo(0xffa5a190,297193);
        return std::make_unique<mk2::BootContinuation>(std::move(generated.State()));
    };
    const auto observed=run(*machine);
    const auto control=run(*plain);
    if (lines!=737 || boundaries!=std::vector<uint64_t>{1827925,3655850} ||
        scanout.width()!=400 || scanout.height()!=254 || scanout.pixels().size()!=101600)
        throw std::runtime_error("early boot must deliver every live raster edge and two complete frames");
    const auto& a=observed->ready;const auto& b=control->ready;
    if (a.next_pc!=0xffa5a190 || a.cycles!=297193 || a.a!=b.a || a.b!=b.b ||
        a.next_pc!=b.next_pc || a.status!=b.status || a.cycles!=b.cycles || a.instructions!=b.instructions ||
        a.board.io!=b.board.io || a.board.display_address!=b.board.display_address ||
        a.board.scanline_events!=b.board.scanline_events || a.board.vcount!=b.board.vcount ||
        a.board.active_updates!=b.board.active_updates || observed->main_ram!=control->main_ram ||
        observed->video.palette_ram!=control->video.palette_ram || observed->video.vram!=control->video.vram ||
        machine->dsp.Registers()!=plain->dsp.Registers() ||
        machine->dsp.pm!=plain->dsp.pm || machine->dsp.dm!=plain->dsp.dm ||
        machine->dsp.DeviceState()!=plain->dsp.DeviceState())
        throw std::runtime_error("early observation changed reset CPU, DSP, memory or raster state");
    std::cout<<"PASS MK2 initial scanout: 737 edges, 2 complete frames, unchanged CPU/DSP/video\n";
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; } }
