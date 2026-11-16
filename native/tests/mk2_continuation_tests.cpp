#include "../mk2/mk2_task_batch.hpp"
#include "../mk2/mk2_executor.hpp"
#include "../mk2/mk2_scanout.hpp"
#include <cstring>
#include <iostream>
#include <memory>

static mk2::BootContinuation ColdDraw(const mk2::Program& program,mk2::DcsBootMachine& m) {
    mk2::GeneratedBoot generated(program,m,nullptr,0xfc7d); // generated closure from reset to delivery
    return std::move(generated.Deliver());
}

int main(int argc,char** argv) { try {
    if(argc!=2) throw std::runtime_error("expected authenticated MK2 ROM directory");
    const auto program=mk2::LoadProgram(argv[1]);
    const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    auto full=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    auto lean=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    std::array<mk2::Scanout,2> rasters;
    std::array<std::vector<uint64_t>,2> frame_ticks;
    std::array<std::vector<float>,2> pcm;
    auto observe=[&](auto& m,unsigned index) {
        m.dsp.SetTraceObservation(false);
        m.dsp.SetDacObserver([&,index](uint64_t,const float* p,size_t n) {
            pcm[index].insert(pcm[index].end(),p,p+n);
        });
        m.SetScanlineObserver([&,index](const auto& board,const auto& video) {
            const auto before=rasters[index].frames();rasters[index].Line(board,video);
            if(before!=rasters[index].frames())
                frame_ticks[index].push_back(94875+uint64_t(board.scanline_events-1)*6325);
        });
    };
    observe(*full,0);observe(*lean,1);
    const auto draw_full=ColdDraw(program,*full);
    const auto draw_lean=ColdDraw(program,*lean);
    const auto before=lean->dsp.Registers();
    for(int invalid : {-2,int(mk2::kFirstFightWindowCount)}) {
        bool rejected=false;
        try { mk2::RunTranslatedContinuation(program,draw_lean,*lean,invalid); }
        catch(const std::runtime_error&) { rejected=true; }
        if(!rejected || lean->dsp.Registers()!=before || lean->LastMainCycles()!=1261260)
            throw std::runtime_error("invalid continuation mutated the native prefix");
    }
    const auto a=mk2::RunTranslatedContinuation(program,draw_full,*full,-1,true);
    const auto b=mk2::RunTranslatedContinuation(program,draw_lean,*lean);
    const auto& x=a.ready;const auto& y=b.ready;
    if(x.next_pc!=0xff80dd30 || x.cycles!=7005800 || x.a!=y.a || x.b!=y.b ||
       x.next_pc!=y.next_pc || x.status!=y.status || x.cycles!=y.cycles || x.instructions!=y.instructions ||
       x.cmos!=y.cmos || x.ram!=y.ram || x.board.io!=y.board.io ||
       x.board.display_address!=y.board.display_address || x.board.scanline_events!=y.board.scanline_events ||
       x.board.vcount!=y.board.vcount || x.board.active_updates!=y.board.active_updates ||
       x.board.input_events!=y.board.input_events || a.main_ram!=b.main_ram ||
       a.video.palette_ram!=b.video.palette_ram || a.video.vram!=b.video.vram ||
       a.video.shift_register!=b.video.shift_register || a.video.dma_registers!=b.video.dma_registers ||
       a.video.dma_palette!=b.video.dma_palette || full->dsp.Registers()!=lean->dsp.Registers() ||
       full->dsp.pm!=lean->dsp.pm || full->dsp.dm!=lean->dsp.dm ||
       full->dsp.external_pm!=lean->dsp.external_pm || full->dsp.DeviceState()!=lean->dsp.DeviceState() ||
       full->dsp.DacBuffer(32768)!=lean->dsp.DacBuffer(32768) ||
       full->dsp.AccessCount()!=lean->dsp.AccessCount() ||
       full->dsp.sport_dma_positions!=lean->dsp.sport_dma_positions ||
       full->dsp.sport_dma_position!=lean->dsp.sport_dma_position ||
       full->dsp.sport_pcm!=lean->dsp.sport_pcm || full->dsp.InstructionCount()!=lean->dsp.InstructionCount() ||
       frame_ticks[0]!=frame_ticks[1] || rasters[0].pixels()!=rasters[1].pixels() ||
       pcm[0].size()!=pcm[1].size() || std::memcmp(pcm[0].data(),pcm[1].data(),pcm[0].size()*sizeof(float)))
        throw std::runtime_error("history observation changed native CPU/DSP/memories/DAC/raster state");
    if(a.cpu_trace.size()!=392474 || a.executed_instructions!=392474 || a.bus.empty() || a.points.empty() ||
       !a.observe_history || b.observe_history || b.executed_instructions!=392474 ||
       !b.cpu_trace.empty() || !b.bus.empty() || !b.points.empty() ||
       !lean->dsp.accesses.empty() || full->dsp.AccessCount()!=full->dsp.accesses.size() ||
       frame_ticks[0].size()!=61)
        throw std::runtime_error("continuation history, instruction count or raster contract differs");
    std::cout<<"PASS MK2 continuation: 7005800 cycles, 61 rasters, CPU/DSP/memories/DAC equal with history on/off\n";
} catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;} }
