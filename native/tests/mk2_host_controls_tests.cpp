#include "../mk2/mk2_task_batch.hpp"
#include "../mk2/mk2_executor.hpp"
#include <iostream>
#include <memory>

static mk2::BootContinuation ColdDraw(const mk2::Program& p,mk2::DcsBootMachine& m) {
    mk2::GeneratedBoot generated(p,m,nullptr,0xfc7d); // generated closure from reset to delivery
    return std::move(generated.Deliver());
}

int main(int argc,char** argv) {try {
    if(argc!=3) throw std::runtime_error("expected MK2 ROM directory and neutral|high_punch|low_punch|right");
    const std::string mode=argv[2];
    const bool held=mode=="right_high_punch_held" || mode=="right_low_punch_held";
    const uint32_t mask=mode=="neutral" ? 0u : mode=="high_punch" ? 0x10u :
                        mode=="low_punch" ? 0x10000000u : mode=="right" ? 8u :
                        mode=="right_high_punch_held" ? 0x18u : mode=="right_low_punch_held" ? 0x10000008u : 0u;
    const bool chunked=mode=="chunked_neutral";
    const bool prolonged=mode=="prolonged_neutral" || chunked;
    if(!mask && mode!="neutral" && !prolonged) throw std::runtime_error("unknown host replay");
    const auto program=mk2::LoadProgram(argv[1]);const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    struct Stage {uint64_t end,instructions;const char* cpu;};
    const std::array<Stage,mk2::kFirstFightWindowCount> stages{{
#include "mk2_first_fight_bounds.inc"
    }};
    auto machine=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    machine->dsp.SetTraceObservation(false);
    const auto draw=ColdDraw(program,*machine);
    const unsigned start_window=prolonged ? 0 : 85;
    const int stop_window=chunked ? 85 : prolonged ? int(mk2::kFirstFightWindowCount)-2 : -1;
    const auto range=mk2::HostControlRange(start_window,stop_window);
    if(range.start_window!=start_window || range.start_cycle!=stages[start_window].end ||
       range.minimum_stop_cycle!=(chunked ? stages[85].end : prolonged ? stages[mk2::kFirstFightWindowCount-2].end : 130000000) ||
       range.maximum_cycle!=stages.back().end)
        throw std::runtime_error("host bounds differ from translated endpoints");
    const auto prefix=mk2::RunTranslatedContinuation(program,draw,*machine,int(start_window));
    const auto before=machine->dsp.Registers();
    for(unsigned invalid=0;invalid<9;++invalid) {
        auto bad=prefix;
        if(invalid==0)bad.ready.a[0]^=1;
        if(invalid==2)bad.main_ram.pop_back();
        if(invalid==3)bad.ready.cmos.pop_back();
        if(invalid==4)bad.video.vram.pop_back();
        if(invalid==5)bad.video.palette_ram.pop_back();
        if(invalid==6)bad.ready.board.input0=0xffef;
        if(invalid==7)++bad.ready.board.scanline_events;
        bool rejected=false;
        try {mk2::RunHostContinuation(program,bad,*machine,invalid==1 ?
            std::function<uint32_t(uint64_t)>{} : [](uint64_t){return 0xffffffffu;},
            invalid==8 ? mk2::kFirstFightWindowCount : start_window,stop_window);}
        catch(const std::runtime_error&) {rejected=true;}
        if(!rejected || machine->dsp.Registers()!=before || machine->LastMainCycles()!=prefix.ready.cycles)
            throw std::runtime_error("host admission mutated invalid prefix");
    }
    const auto provider_clock=std::make_shared<uint64_t>(0);
    auto result=mk2::RunHostContinuation(program,prefix,*machine,[=](uint64_t tick) {
        if(*provider_clock && tick!=*provider_clock+1827925)
            throw std::runtime_error("host provider clock replayed or skipped across chunks");
        *provider_clock=tick;
        return 0xffffffffu ^ ((tick>=2050931850 && tick<(held?2109425450ull:2058243550ull)) ? mask : 0u);
    },start_window,stop_window);
    uint64_t session_instructions=result.executed_instructions;
    if(held) {
        if(result.ready.board.input0!=(mode=="right_high_punch_held" ? 0xffe7 : 0xfff7) ||
           result.ready.board.input2!=(mode=="right_low_punch_held" ? 0xfffe : 0xffff))
            throw std::runtime_error("host chunk did not retain the held physical controls");
        result=mk2::ResumeHostContinuation(program,result,*machine,134000000);
        session_instructions+=result.executed_instructions;
        if(result.ready.board.input0!=0xffff || result.ready.board.input2!=0xffff)
            throw std::runtime_error("resumed host provider did not release both physical controls");
    }
    if(chunked) {
        const auto dsp_before=machine->dsp.Registers();
        const auto cycle_before=machine->LastMainCycles();
        for(unsigned invalid=0;invalid<8;++invalid) {
            auto bad=result;
            uint64_t stop=stages[86].end;
            if(invalid==0)bad.ready.next_pc+=16;
            if(invalid==1)bad.ready.board=mk2::BoardBootControls{};
            if(invalid==2)bad.ready.board.input_events.clear();
            if(invalid==3)bad.main_ram.pop_back();
            if(invalid==4)++bad.ready.board.scanline_events;
            if(invalid==5)stop=bad.ready.cycles;
            if(invalid==6)stop=stages.back().end;
            if(invalid==7)++bad.ready.cycles;
            bool rejected=false;
            try {mk2::ResumeHostContinuation(program,bad,*machine,stop);}
            catch(const std::runtime_error&) {rejected=true;}
            if(!rejected || machine->dsp.Registers()!=dsp_before || machine->LastMainCycles()!=cycle_before)
                throw std::runtime_error("host resume mutated invalid admission");
        }
        for(unsigned stop:{86u,90u,mk2::kFirstFightWindowCount-2}) {
            result=mk2::ResumeHostContinuation(program,result,*machine,stages[stop].end);
            session_instructions+=result.executed_instructions;
        }
    }
    if(result.ready.next_pc!=0xff80dd30 || !result.ready.board.HostInputProviderActive() ||
       result.ready.board.input_events.size()<=20 || !result.cpu_trace.empty() || !result.bus.empty())
        throw std::runtime_error("neutral host route differs from measured window86");
    const auto& s=result.ready;
    std::array<uint64_t,34> cpu{s.next_pc,s.status,s.cycles};
    for(unsigned n=0;n<16;++n)cpu[3+n]=s.a[n];
    for(unsigned n=0;n<15;++n)cpu[19+n]=s.b[n];
    if(mode=="neutral" && (!mk2::Cpu34Is(cpu,stages[86].cpu) || result.executed_instructions!=594173))
        throw std::runtime_error("neutral host CPU34 differs");
    uint64_t expected_instructions=0;
    if(prolonged) {
        for(unsigned n=start_window+1;n<mk2::kFirstFightWindowCount-1;++n)
            expected_instructions+=stages[n].instructions;
        if(!mk2::Cpu34Is(cpu,stages[mk2::kFirstFightWindowCount-2].cpu) ||
           session_instructions!=expected_instructions)
            throw std::runtime_error("prolonged neutral host CPU34/instructions differ");
        auto control_machine=std::make_unique<mk2::DcsBootMachine>(boot,rom);
        control_machine->dsp.SetTraceObservation(false);
        const auto control_draw=ColdDraw(program,*control_machine);
        const auto control=mk2::RunTranslatedContinuation(program,control_draw,*control_machine,
            int(mk2::kFirstFightWindowCount)-2);
        const auto& t=control.ready;
        if(s.a!=t.a || s.b!=t.b || s.next_pc!=t.next_pc || s.status!=t.status ||
           s.cycles!=t.cycles || s.instructions!=t.instructions || s.cmos!=t.cmos || s.ram!=t.ram ||
           s.board.io!=t.board.io || s.board.display_address!=t.board.display_address ||
           s.board.scanline_events!=t.board.scanline_events || s.board.active_updates!=t.board.active_updates ||
           s.board.vcount!=t.board.vcount || result.main_ram!=control.main_ram ||
           result.video.vram!=control.video.vram || result.video.palette_ram!=control.video.palette_ram ||
           result.video.shift_register!=control.video.shift_register ||
           result.video.dma_registers!=control.video.dma_registers || result.video.dma_palette!=control.video.dma_palette ||
           machine->dsp.Registers()!=control_machine->dsp.Registers() || machine->dsp.pm!=control_machine->dsp.pm ||
           machine->dsp.dm!=control_machine->dsp.dm || machine->dsp.external_pm!=control_machine->dsp.external_pm ||
           machine->dsp.DeviceState()!=control_machine->dsp.DeviceState() ||
           machine->dsp.DacBuffer(32768)!=control_machine->dsp.DacBuffer(32768) ||
           machine->dsp.AccessCount()!=control_machine->dsp.AccessCount() ||
           machine->dsp.InstructionCount()!=control_machine->dsp.InstructionCount() ||
           machine->dsp.sport_dma_positions!=control_machine->dsp.sport_dma_positions ||
           machine->dsp.sport_dma_position!=control_machine->dsp.sport_dma_position ||
           machine->dsp.sport_pcm!=control_machine->dsp.sport_pcm ||
           machine->SportDeadlineTicks()!=control_machine->SportDeadlineTicks() ||
           machine->DmaDeadlineSubticks()!=control_machine->DmaDeadlineSubticks() ||
           machine->DmaCompletions()!=control_machine->DmaCompletions() ||
           machine->link.Control()!=control_machine->link.Control() ||
           !machine->dsp.accesses.empty() || !machine->dsp.trace.empty())
            throw std::runtime_error("prolonged host observation changed native guest/device/memory state");
    }
    std::cout<<"{\"passed\":true,\"host_events\":"<<s.board.input_events.size()-20
             <<",\"instructions\":"<<session_instructions
             <<",\"chunks\":"<<(chunked?4:held?2:1)
             <<",\"fixed_native_state_compared\":"<<(prolonged?"true":"false")<<",\"cpu34\":["
             <<s.next_pc<<','<<s.status<<','<<s.cycles;
    for(auto v:s.a)std::cout<<','<<v;
    for(auto v:s.b)std::cout<<','<<v;
    std::cout<<"],\"events\":[";
    for(size_t n=20;n<s.board.input_events.size();++n) {
        const auto& e=s.board.input_events[n];
        std::cout<<(n==20?"":",")<<'['<<e[0]<<','<<e[1]<<','<<e[2]<<','<<e[3]<<']';
    }
    std::cout<<"]}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
