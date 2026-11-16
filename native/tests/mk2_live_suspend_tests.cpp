#include "../mk2/mk2_live_host.hpp"
#include "../mk2/mk2_executor.hpp"
#include "../mk2/mk2_valid_cmos_boot.hpp"
#include "../mk2/mk2_valid_cmos_continuation.hpp"
#include "../mk2/mk2_valid_cmos_startup.hpp"
#include "../mk2/mk2_valid_cmos_draw.hpp"
#include "../mk2/mk2_scanout.hpp"
#include "../mk2/mk2_cmos_image.hpp"
#include "mk5_program.hpp"
#include "mk5_operator_settings.hpp"
#include <cstring>
#include <deque>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <memory>
#include <optional>
#include <tuple>

namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Frame {uint64_t tick;unsigned width,height;std::vector<uint32_t> pixels;};
struct Dac {uint64_t tick;std::vector<float> samples;};
struct Comparison {
    std::deque<Frame> frames;std::deque<Dac> dac;std::deque<std::array<uint64_t,2>> input;
    uint64_t compared_frames=0,compared_samples=0,compared_inputs=0;
};
mk2::ValidCmosContinuation boot(const mk2::Program& p,mk2::DcsBootMachine& m,const std::vector<uint8_t>& seed,uint16_t dsw=0xfc7d){
    mk2::GeneratedBoot generated(p,m,&seed,dsw); // generated closure from reset to delivery
    return mk2::DeliverAs<mk2::ValidCmosContinuation>(generated);
}
struct Session {
    std::unique_ptr<mk2::DcsBootMachine> machine;
    mk2::Scanout scanout;
    std::optional<mk2::LiveHostContinuation> current;
    uint64_t coin_requests=0,start_requests=0,punch_requests=0;
    Session(const mk2::Program& p,const std::vector<uint8_t>& rom,const std::vector<uint8_t>& seed,
            Comparison& compare,bool reference,uint16_t dsw=0xfc7d){
        machine=std::make_unique<mk2::DcsBootMachine>(mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000}),rom);
        machine->dsp.SetTraceObservation(false);
        machine->SetScanlineObserver([this,&compare,reference](const auto& b,const auto& v){
            const auto before=scanout.frames();scanout.Line(b,v);
            if(before==scanout.frames())return;
            const auto tick=94875+uint64_t(b.scanline_events-1)*6325;
            if(reference)compare.frames.push_back({tick,scanout.width(),scanout.height(),scanout.pixels()});
            else {
                check(!compare.frames.empty(),"suspended run emitted an extra raster");
                const auto& expected=compare.frames.front();
                check(expected.tick==tick && expected.width==scanout.width() && expected.height==scanout.height() &&
                      expected.pixels==scanout.pixels(),"suspension changed complete raster pixels or clock");
                compare.frames.pop_front();++compare.compared_frames;
            }
        });
        machine->dsp.SetDacObserver([&compare,reference](uint64_t tick,const float* pcm,size_t count){
            if(reference)compare.dac.push_back({tick,{pcm,pcm+count}});
            else {
                check(!compare.dac.empty(),"suspended run emitted extra DAC data");const auto& expected=compare.dac.front();
                check(expected.tick==tick && expected.samples.size()==count &&
                      (!count || !std::memcmp(expected.samples.data(),pcm,count*sizeof(float))),"suspension changed DAC bits, block order or clock");
                compare.dac.pop_front();compare.compared_samples+=count;
            }
        });
        const auto draw=boot(p,*machine,seed,dsw);
        const bool freeplay=mkoperator::ReadParameter(seed,18)!=0;
        auto provider=[this,&compare,reference,freeplay](uint64_t tick){
            uint32_t mask=0;
            if(!freeplay && ((tick>=200000000 && tick<240000000)||(tick>=280000000 && tick<320000000)))mask|=0x10000;
            if(tick>=400000000 && tick<440000000)mask|=0x40000;
            if(tick>=700000000 && tick<740000000)mask|=0x10;
            coin_requests+=bool(mask&0x10000);start_requests+=bool(mask&0x40000);punch_requests+=bool(mask&0x10);
            const uint32_t value=0xffffffffu^mask;
            if(reference)compare.input.push_back({tick,value});
            else {
                check(!compare.input.empty() && compare.input.front()==std::array<uint64_t,2>{tick,value},"suspension changed physical input requests");
                compare.input.pop_front();++compare.compared_inputs;
            }
            return value;
        };
        current.emplace(mk2::RunValidLiveHost(p,draw,*machine,provider,draw.ready.cycles+1));
        check(current->State().ready.next_pc!=0xff80dd30,"live suspension still requires an arcade task yield");
    }
    void advance(const mk2::Program& p,uint64_t target,uint64_t step){
        while(current->State().ready.cycles<target){
            const auto request=std::min(target,current->State().ready.cycles+step);
            current.emplace(mk2::ResumeValidLiveHost(p,std::move(*current),*machine,request));
        }
    }
};
void compare_state(const Session& left,const Session& right){
    const auto& a=left.current->State();const auto& b=right.current->State();
    const auto& x=a.ready;const auto& y=b.ready;
    check(x.next_pc==y.next_pc && x.status==y.status && x.cycles==y.cycles && x.a==y.a && x.b==y.b && x.instructions==y.instructions,"partition CPU34 or instruction count differs");
    check(x.cmos==y.cmos && a.main_ram==b.main_ram && a.video.vram==b.video.vram && a.video.palette_ram==b.video.palette_ram &&
          x.board.io==y.board.io && a.video.DmaRegisters(x.board)==b.video.DmaRegisters(y.board) && a.video.shift_register==b.video.shift_register,"partition full memory or DMA/shift register differs");
    check(x.board.input0==y.board.input0 && x.board.input1==y.board.input1 && x.board.input2==y.board.input2 &&
          x.board.HostLatchState()==y.board.HostLatchState() && x.board.LiveInputEventCount()==y.board.LiveInputEventCount() &&
          x.board.LiveLastInputTick()==y.board.LiveLastInputTick() && x.board.vcount==y.board.vcount &&
          x.board.display_address==y.board.display_address && x.board.active_updates==y.board.active_updates &&
          x.board.protection.Read()==y.board.protection.Read(),"partition physical board state differs");
    check(std::tie(a.execution.fill_remaining,a.execution.fill_b,a.execution.last_instruction_pc,a.execution.last_instruction_cycles,a.execution.shift_loaded)==
          std::tie(b.execution.fill_remaining,b.execution.fill_b,b.execution.last_instruction_pc,b.execution.last_instruction_cycles,b.execution.shift_loaded),"partition translator execution state differs");
    const auto& m=*left.machine;const auto& n=*right.machine;
    check(m.dsp.ExecutionState()==n.dsp.ExecutionState() && m.link.ExecutionState()==n.link.ExecutionState() &&
          m.dsp.ObservationCounts()==n.dsp.ObservationCounts(),"partition raw DSP stacks/interrupt/reset/DAC clocks or DCS queue differs");
    check(m.SchedulerClocks()==n.SchedulerClocks() && m.dsp.Registers()==n.dsp.Registers() && m.dsp.DeviceState()==n.dsp.DeviceState(),"partition scheduler/DSP76/device state differs");
    check(m.dsp.pm==n.dsp.pm && m.dsp.dm==n.dsp.dm && m.dsp.external_pm==n.dsp.external_pm && m.dsp.DacBuffer(32768)==n.dsp.DacBuffer(32768),"partition complete DSP memory or DAC ring differs");
    for(unsigned i=0;i<32;++i)check(m.dsp.ReadControl(uint16_t(0x3fe0+i))==n.dsp.ReadControl(uint16_t(0x3fe0+i)),"partition DSP controls differ");
}
}
int main(int argc,char** argv){try{
    check(argc==3 || argc==4,"expected authenticated ROM directory, factory seed and optional private preview directory");
    const auto program=mk2::LoadProgram(argv[1]);const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    std::ifstream seed_file(argv[2],std::ios::binary);const std::vector<uint8_t> seed{std::istreambuf_iterator<char>(seed_file),{}};
    check(seed.size()==16384 && Sha256(seed)=="f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f","seed identity differs");
    Comparison compared;Session a(program,rom,seed,compared,true),b(program,rom,seed,compared,false);
    constexpr uint64_t end=550000000;uint64_t checkpoints=0;
    for(uint64_t target=10000000;;target=std::min(end,target+2000000)){
        a.advance(program,target,1000000);b.advance(program,target,2000000);compare_state(a,b);
        check(compared.frames.empty() && compared.dac.empty() && compared.input.empty(),"suspension left unmatched output");
        ++checkpoints;if(target==end)break;
    }
    a.current->ValidateBoundary(program,*a.machine);b.current->ValidateBoundary(program,*b.machine);
    bool rejected=false;try{a.current->ValidateBoundary(program,*b.machine);}catch(const std::runtime_error&){rejected=true;}
    check(rejected,"final boundary accepted a different machine");
    auto moved=std::move(*b.current);rejected=false;
    try{b.current->ValidateBoundary(program,*b.machine);}catch(const std::runtime_error&){rejected=true;}
    check(rejected,"final boundary accepted a consumed chain");moved.ValidateBoundary(program,*b.machine);
    const auto before=a.machine->dsp.ExecutionState();a.machine->dsp.sport_irq1_latched=!a.machine->dsp.sport_irq1_latched;
    check(before!=a.machine->dsp.ExecutionState(),"raw DSP state omitted IRQ1 latch");
    a.machine->dsp.sport_irq1_latched=!a.machine->dsp.sport_irq1_latched;
    for(bool freeplay:{false,true}){
        auto image=seed;mkoperator::ApplyMk2Coinage(image,program.bytes,3,freeplay);
        mkoperator::WriteParameter(image,14,freeplay?1:5);mkoperator::UpdateSettingsChecksum(image);
        const uint16_t dsw=freeplay?0x7c7d:0xbc7d;
        Comparison operator_compare;Session first(program,rom,image,operator_compare,true,dsw),second(program,rom,image,operator_compare,false,dsw);
        for(uint64_t target=10000000;target<=180000000;target+=2000000){
            first.advance(program,target,1000000);second.advance(program,target,2000000);compare_state(first,second);
            check(operator_compare.frames.empty() && operator_compare.dac.empty() && operator_compare.input.empty(),"operator suspension left unmatched output");
        }
        check(first.start_requests && first.punch_requests && (freeplay?!first.coin_requests:bool(first.coin_requests)),"operator legal Start/selection input timeline differs");
        const auto persisted=mk2::EncodeCmosImage(first.current->State().ready.cmos);
        check(mkoperator::ReadParameter(persisted,14)==(freeplay?1u:5u) && mkoperator::ReadParameter(persisted,18)==unsigned(freeplay),"live operator adjustments were overwritten");
        if(argc==4){
            const auto path=std::filesystem::path(argv[3])/(freeplay?"operator-freeplay.bgra":"operator-paid.bgra");
            std::ofstream frame(path,std::ios::binary);const auto& pixels=first.scanout.pixels();
            frame.write(reinterpret_cast<const char*>(pixels.data()),std::streamsize(pixels.size()*4));
            if(!frame)throw std::runtime_error("private operator preview write failed");
        }
        std::cout<<"OPERATOR "<<(freeplay?"freeplay":"paid")<<" cycles="<<first.current->State().ready.cycles<<" rasters="<<operator_compare.compared_frames
                 <<" DAC="<<operator_compare.compared_samples<<" coins="<<first.coin_requests<<" start="<<first.start_requests<<" selection="<<first.punch_requests<<'\n';
    }
    std::cout<<"{\"passed\":true,\"CPU34_cycles\":"<<a.current->State().ready.cycles<<",\"checkpoints\":"<<checkpoints
             <<",\"integral_frames\":"<<compared.compared_frames<<",\"DAC_float32_samples\":"<<compared.compared_samples
             <<",\"input_requests\":"<<compared.compared_inputs<<",\"full_DSP_instruction_prefix_compared\":false}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
