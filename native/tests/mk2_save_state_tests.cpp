// Save at a live chunk boundary, record m chunks, load and replay them: same rasters, ticks, DAC bits, host PCM
// and complete serialized state. The same state also loads into a second session at a different boundary.
#include "../mk2/mk2_save_state.hpp"
#include "../mk2/mk2_executor.hpp"
#include "../mk2/mk2_valid_cmos_boot.hpp"
#include "../mk2/mk2_valid_cmos_continuation.hpp"
#include "../mk2/mk2_valid_cmos_startup.hpp"
#include "../mk2/mk2_valid_cmos_draw.hpp"
#include "../mk2/mk2_cmos_image.hpp"
#include "mk5_program.hpp"
#include "mk5_operator_settings.hpp"
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>

namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Frame {uint64_t tick;unsigned width,height;std::vector<uint32_t> pixels;};
struct Dac {uint64_t tick;std::vector<float> samples;};
// Records one pass, then compares later passes against it without consuming the recording.
struct Recording {
    enum class Mode {off,record,compare} mode=Mode::off;
    std::vector<Frame> frames;std::vector<Dac> dac;std::vector<std::vector<int16_t>> pcm;std::vector<std::array<uint64_t,2>> input;
    size_t frame=0,block=0,output=0,request=0;
    uint64_t compared_samples=0;
    void Rewind(){frame=block=output=request=0;}
    bool Complete()const{return frame==frames.size() && block==dac.size() && output==pcm.size() && request==input.size();}
};
struct Session {
    std::unique_ptr<mk2::DcsBootMachine> machine;
    mk2::Scanout scanout;
    std::unique_ptr<mk2::OriginalAudio> audio;
    std::optional<mk2::LiveHostContinuation> current;
    Session(const mk2::Program& p,const std::vector<uint8_t>& rom,const std::vector<uint8_t>& seed,Recording& r){
        machine=std::make_unique<mk2::DcsBootMachine>(mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000}),rom);
        machine->dsp.SetTraceObservation(false);
        audio=std::make_unique<mk2::OriginalAudio>([&r](const int16_t* pcm,size_t count){
            if(r.mode==Recording::Mode::record)r.pcm.emplace_back(pcm,pcm+count);
            else if(r.mode==Recording::Mode::compare){
                check(r.output<r.pcm.size() && r.pcm[r.output]==std::vector<int16_t>(pcm,pcm+count),"load changed host PCM output");
                ++r.output;
            }
        });
        machine->SetScanlineObserver([this,&r](const auto& b,const auto& v){
            const auto before=scanout.frames();scanout.Line(b,v);
            if(before==scanout.frames())return;
            const auto tick=94875+uint64_t(b.scanline_events-1)*6325;
            if(r.mode==Recording::Mode::record)r.frames.push_back({tick,scanout.width(),scanout.height(),scanout.pixels()});
            else if(r.mode==Recording::Mode::compare){
                check(r.frame<r.frames.size(),"load emitted an extra raster");const auto& expected=r.frames[r.frame++];
                check(expected.tick==tick && expected.width==scanout.width() && expected.height==scanout.height() &&
                      expected.pixels==scanout.pixels(),"load changed complete raster pixels or clock");
            }
        });
        machine->dsp.SetDacObserver([this,&r](uint64_t tick,const float* pcm,size_t count){
            audio->Feed(tick,pcm,count);
            if(r.mode==Recording::Mode::record)r.dac.push_back({tick,{pcm,pcm+count}});
            else if(r.mode==Recording::Mode::compare){
                check(r.block<r.dac.size(),"load emitted extra DAC data");const auto& expected=r.dac[r.block++];
                check(expected.tick==tick && expected.samples.size()==count &&
                      (!count || !std::memcmp(expected.samples.data(),pcm,count*sizeof(float))),"load changed DAC bits, block order or clock");
                r.compared_samples+=count;
            }
        });
        mk2::GeneratedBoot generated(p,*machine,&seed,0xfc7d); // generated closure from reset to delivery
        const auto draw=mk2::DeliverAs<mk2::ValidCmosContinuation>(generated);
        const bool freeplay=mkoperator::ReadParameter(seed,18)!=0;
        auto provider=[&r,freeplay](uint64_t tick){
            uint32_t mask=0;
            if(!freeplay && ((tick>=200000000 && tick<240000000)||(tick>=280000000 && tick<320000000)))mask|=0x10000;
            if(tick>=400000000 && tick<440000000)mask|=0x40000;
            if(tick>=700000000 && tick<740000000)mask|=0x10;
            const uint32_t value=0xffffffffu^mask;
            if(r.mode==Recording::Mode::record)r.input.push_back({tick,value});
            else if(r.mode==Recording::Mode::compare){
                check(r.request<r.input.size() && r.input[r.request]==std::array<uint64_t,2>{tick,value},"load changed physical input requests");
                ++r.request;
            }
            return value;
        };
        current.emplace(mk2::RunValidLiveHost(p,draw,*machine,provider,draw.ready.cycles+mk2::live_detail::kRequestCycles));
    }
    // The same chunking as the live window loop (mk2_native_check.cpp).
    void Chunks(const mk2::Program& p,unsigned count){
        for(unsigned n=0;n<count;++n)
            current.emplace(mk2::ResumeValidLiveHost(p,std::move(*current),*machine,current->State().ready.cycles+mk2::live_detail::kRequestCycles));
    }
    void Until(const mk2::Program& p,uint64_t cycles){while(current->State().ready.cycles<cycles)Chunks(p,1);}
    std::vector<uint8_t> Save(const mk2::Program& p)const{return mk2::SaveLiveState(p,*current,*machine,scanout,audio.get());}
    void Load(const mk2::Program& p,const std::vector<uint8_t>& bytes){mk2::LoadLiveState(p,bytes,*current,*machine,scanout,audio.get());}
};
template<class Error,class F> void refused(F&& f,const char* message){
    bool thrown=false;try{f();}catch(const Error&){thrown=true;}check(thrown,message);
}
}
int main(int argc,char** argv){try{
    check(argc==3,"expected authenticated ROM directory and factory seed");
    const auto program=mk2::LoadProgram(argv[1]);const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    std::ifstream seed_file(argv[2],std::ios::binary);const std::vector<uint8_t> seed{std::istreambuf_iterator<char>(seed_file),{}};
    check(seed.size()==16384 && Sha256(seed)=="f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f","seed identity differs");
    constexpr unsigned m=10; // 20M cycles across the selection press and release at 43.75M..46.25M
    Recording r;Session a(program,rom,seed,r);
    a.Until(program,40000000);
    const auto k=a.current->State().ready.cycles;
    const auto saved=a.Save(program);
    r.mode=Recording::Mode::record;a.Chunks(program,m);r.mode=Recording::Mode::off;
    const auto expected=a.Save(program);
    check(!r.frames.empty() && !r.dac.empty() && !r.pcm.empty() && !r.input.empty(),"recorded pass is empty");

    a.Load(program,saved);
    check(a.current->State().ready.cycles==k && a.Save(program)==saved,"load did not restore the saved boundary");
    r.mode=Recording::Mode::compare;a.Chunks(program,m);r.mode=Recording::Mode::off;
    check(r.Complete() && a.Save(program)==expected,"in-session load left unmatched output or state");

    // A later session (as after a restart with the slot file) loads at another boundary of its own.
    Session b(program,rom,seed,r);b.Chunks(program,3);
    check(b.current->State().ready.cycles!=k,"second session must load from a different boundary");
    b.Load(program,saved);r.Rewind();
    r.mode=Recording::Mode::compare;b.Chunks(program,m);r.mode=Recording::Mode::off;
    check(r.Complete() && b.Save(program)==expected,"cross-session load left unmatched output or state");

    auto damaged=saved;damaged.back()^=1;
    refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(program,damaged,true);},"damaged payload accepted");
    auto truncated=saved;truncated.resize(truncated.size()/2);
    refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(program,truncated,true);},"truncated state accepted");
    refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(program,saved,false);},"state accepted without its audio stream");
    auto other=program;other.sha256=std::string(64,'0');
    refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(other,saved,true);},"state accepted for another program ROM");

    std::cout<<"{\"passed\":true,\"save_cycle\":"<<k<<",\"chunks\":"<<m<<",\"state_bytes\":"<<saved.size()
             <<",\"rasters\":"<<r.frames.size()<<",\"DAC_float32_samples\":"<<r.compared_samples/2
             <<",\"host_pcm_blocks\":"<<r.pcm.size()<<",\"input_requests\":"<<r.input.size()<<",\"passes\":2}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
