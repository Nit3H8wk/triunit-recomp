// Save at a live chunk boundary, record m chunks, load and replay them: same rasters, ticks, DAC bits, host PCM
// and complete serialized state. The same state also loads into a second session at a different boundary.
// Original edition, then Remastered with music: its presentation layers, fighter frames and the stereo music mix
// (synthetic user tracks written by this test) are compared as well.
#include "../mk2/mk2_save_state.hpp"
#include "../mk2/mk2_executor.hpp"
#include "../mk2/mk2_valid_cmos_boot.hpp"
#include "../mk2/mk2_valid_cmos_continuation.hpp"
#include "../mk2/mk2_valid_cmos_startup.hpp"
#include "../mk2/mk2_valid_cmos_draw.hpp"
#include "../mk2/mk2_cmos_image.hpp"
#include "../runtime/mk2_music_manifest.hpp"
#include "mk5_program.hpp"
#include "mk5_operator_settings.hpp"
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>

namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Frame {uint64_t tick;unsigned width,height;std::vector<uint32_t> pixels;std::string layers;};
struct Dac {uint64_t tick;std::vector<float> samples;};
// Records one pass, then compares later passes against it without consuming the recording.
struct Recording {
    enum class Mode {off,record,compare} mode=Mode::off;
    std::vector<Frame> frames;std::vector<Dac> dac;std::vector<std::vector<int16_t>> pcm;std::vector<std::array<uint64_t,2>> input;
    size_t frame=0,block=0,output=0,request=0;
    uint64_t compared_samples=0,fighter_frames=0,backdrop_frames=0;
    void Rewind(){frame=block=output=request=0;}
    bool Complete()const{return frame==frames.size() && block==dac.size() && output==pcm.size() && request==input.size();}
};
// Remastered presentation of one frame: blood layer, scenery and fighter layers, as one digest.
std::string Layers(const mk2::Scanout& s){
    mk2::state::Writer w;auto presentation=s.presentation();auto backdrop=s.backdrop_pixels();auto fighters=s.fighter_frame();
    w(presentation,backdrop,fighters);
    return Sha256(w.bytes);
}
struct Session {
    std::unique_ptr<mk2::DcsBootMachine> machine;
    mk2::Scanout scanout;
    std::unique_ptr<mk2::OriginalAudio> audio;
    std::unique_ptr<mk2::RemasteredAudio> music;
    std::optional<mk2::LiveHostContinuation> current;
    Session(const mk2::Program& p,const std::vector<uint8_t>& rom,const std::vector<uint8_t>& seed,Recording& r,
            const std::filesystem::path* tracks=nullptr):scanout(tracks!=nullptr){
        machine=std::make_unique<mk2::DcsBootMachine>(mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000}),rom);
        machine->dsp.SetTraceObservation(false);
        auto consumer=[&r](const int16_t* pcm,size_t count){
            if(r.mode==Recording::Mode::record)r.pcm.emplace_back(pcm,pcm+count);
            else if(r.mode==Recording::Mode::compare){
                check(r.output<r.pcm.size() && r.pcm[r.output]==std::vector<int16_t>(pcm,pcm+count),"load changed host PCM output");
                ++r.output;
            }
        };
        if(tracks)music=std::make_unique<mk2::RemasteredAudio>(machine->dsp,*tracks,consumer);
        else audio=std::make_unique<mk2::OriginalAudio>(consumer);
        machine->SetScanlineObserver([this,&r](const auto& b,const auto& v){
            const auto before=scanout.frames();scanout.Line(b,v);
            if(before==scanout.frames())return;
            const auto tick=94875+uint64_t(b.scanline_events-1)*6325;
            const auto layers=music?Layers(scanout):std::string{};
            if(r.mode==Recording::Mode::record){
                r.frames.push_back({tick,scanout.width(),scanout.height(),scanout.pixels(),layers});
                r.fighter_frames+=scanout.fighter_frame().serial!=0;r.backdrop_frames+=!scanout.backdrop_pixels().empty();
            }else if(r.mode==Recording::Mode::compare){
                check(r.frame<r.frames.size(),"load emitted an extra raster");const auto& expected=r.frames[r.frame++];
                check(expected.tick==tick && expected.width==scanout.width() && expected.height==scanout.height() &&
                      expected.pixels==scanout.pixels(),"load changed complete raster pixels or clock");
                check(expected.layers==layers,"load changed Remastered blood, scenery or fighter layers");
            }
        });
        machine->dsp.SetDacObserver([this,&r](uint64_t tick,const float* pcm,size_t count){
            if(music)music->Feed(tick,pcm,count);else audio->Feed(tick,pcm,count);
            if(r.mode==Recording::Mode::record)r.dac.push_back({tick,{pcm,pcm+count}});
            else if(r.mode==Recording::Mode::compare){
                check(r.block<r.dac.size(),"load emitted extra DAC data");const auto& expected=r.dac[r.block++];
                check(expected.tick==tick && expected.samples.size()==count &&
                      (!count || !std::memcmp(expected.samples.data(),pcm,count*sizeof(float))),"load changed DAC bits, block order or clock");
                r.compared_samples+=count;
            }
        });
        mk2::GeneratedBoot generated(p,*machine,&seed,0xfc7d); // generated closure from reset to delivery
        if(tracks)generated.OnVideoReady([&p](mk2::BootVideo& video){video.EnableBlood(p);video.EnableBackdrop();video.EnableFighters();});
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
    mk2::LiveAudio Audio()const{return {audio.get(),music.get()};}
    // The same chunking as the live window loop (mk2_native_check.cpp).
    void Chunks(const mk2::Program& p,unsigned count){
        for(unsigned n=0;n<count;++n)
            current.emplace(mk2::ResumeValidLiveHost(p,std::move(*current),*machine,current->State().ready.cycles+mk2::live_detail::kRequestCycles));
    }
    void Until(const mk2::Program& p,uint64_t cycles){while(current->State().ready.cycles<cycles)Chunks(p,1);}
    std::vector<uint8_t> Save(const mk2::Program& p)const{return mk2::SaveLiveState(p,*current,*machine,scanout,Audio());}
    void Load(const mk2::Program& p,const std::vector<uint8_t>& bytes){mk2::LoadLiveState(p,bytes,*current,*machine,scanout,Audio());}
    mk2::state::Identity Identity()const{return mk2::state::LiveIdentity(*current,scanout,Audio());}
};
template<class Error,class F> void refused(F&& f,const char* message){
    bool thrown=false;try{f();}catch(const Error&){thrown=true;}check(thrown,message);
}
// Synthetic user tracks (tones, 48 kHz stereo) with a repeat window, so cues start, loop and release.
void WriteTracks(const std::filesystem::path& folder,double gain_db){
    std::filesystem::create_directories(folder);
    std::ofstream json(folder/"slots.json");json<<"{\"slots\":{";
    for(size_t slot=0;slot<mk2::music_slots.size();++slot){
        constexpr uint32_t frames=96000;
        std::vector<int16_t> pcm(frames*2);
        for(uint32_t n=0;n<frames;++n)for(unsigned c=0;c<2;++c)
            pcm[n*2+c]=int16_t(6000*std::sin(double(n)*(0.01+0.002*double(slot+c))));
        const uint32_t data=uint32_t(pcm.size()*2);
        std::ofstream wav(folder/(std::string(mk2::music_slots[slot])+".wav"),std::ios::binary);
        const auto le=[&wav](uint32_t value,unsigned bytes){for(unsigned b=0;b<bytes;++b)wav.put(char(value>>(8*b)));};
        wav<<"RIFF";le(36+data,4);wav<<"WAVEfmt ";le(16,4);le(1,2);le(2,2);le(48000,4);le(192000,4);le(4,2);le(16,2);
        wav<<"data";le(data,4);wav.write(reinterpret_cast<const char*>(pcm.data()),std::streamsize(data));
        check(bool(wav),"cannot write synthetic track");
        json<<(slot?",":"")<<'"'<<mk2::music_slots[slot]<<"\":{\"loop_begin\":0.5,\"loop_end\":1.5,\"gain_db\":"<<gain_db<<'}';
    }
    json<<"}}";check(bool(json),"cannot write synthetic slots.json");
}
struct Result {uint64_t k,bytes;Recording r;uint64_t starts=0;};
Result Exercise(const mk2::Program& program,const std::vector<uint8_t>& rom,const std::vector<uint8_t>& seed,
                const std::filesystem::path* tracks,uint64_t save_at,unsigned m){
    Result out;auto& r=out.r;Session a(program,rom,seed,r,tracks);
    a.Until(program,save_at);
    out.k=a.current->State().ready.cycles;
    const auto saved=a.Save(program);out.bytes=saved.size();
    const auto starts=a.music?a.music->Starts():0;
    r.mode=Recording::Mode::record;a.Chunks(program,m);r.mode=Recording::Mode::off;
    if(a.music)out.starts=a.music->Starts()-starts;
    const auto expected=a.Save(program);
    check(!r.frames.empty() && !r.dac.empty() && !r.pcm.empty() && !r.input.empty(),"recorded pass is empty");

    a.Load(program,saved);
    check(a.current->State().ready.cycles==out.k && a.Save(program)==saved,"load did not restore the saved boundary");
    r.mode=Recording::Mode::compare;a.Chunks(program,m);r.mode=Recording::Mode::off;
    check(r.Complete() && a.Save(program)==expected,"in-session load left unmatched output or state");

    // A later session (as after a restart with the slot file) loads at another boundary of its own.
    Session b(program,rom,seed,r,tracks);b.Chunks(program,3);
    check(b.current->State().ready.cycles!=out.k,"second session must load from a different boundary");
    b.Load(program,saved);r.Rewind();
    r.mode=Recording::Mode::compare;b.Chunks(program,m);r.mode=Recording::Mode::off;
    check(r.Complete() && b.Save(program)==expected,"cross-session load left unmatched output or state");

    const auto identity=a.Identity();
    auto damaged=saved;damaged.back()^=1;
    refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(program,damaged,identity);},"damaged payload accepted");
    auto truncated=saved;truncated.resize(truncated.size()/2);
    refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(program,truncated,identity);},"truncated state accepted");
    auto silent=identity;silent.audio=0;silent.music.clear();
    refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(program,saved,silent);},"state accepted without its audio stream");
    auto edition=identity;edition.edition=tracks?"original":"remastered";
    refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(program,saved,edition);},"state accepted by another edition");
    auto other=program;other.sha256=std::string(64,'0');
    refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(other,saved,identity);},"state accepted for another program ROM");
    if(tracks){
        // Other user tracks (here only one gain differs): another fingerprint, and the state is refused.
        auto folder=tracks->parent_path()/"other-tracks";WriteTracks(folder,-1);
        mk2::DcsLink link;mk2::AdspBoot dsp(std::vector<uint32_t>(376),link);
        mk2::RemasteredAudio changed(dsp,folder,[](const int16_t*,size_t){});
        auto retracked=identity;retracked.music=changed.MusicFingerprint();
        check(retracked.music!=identity.music,"other user tracks kept the fingerprint");
        refused<std::invalid_argument>([&]{mk2::state::CheckLiveState(program,saved,retracked);},"state accepted with other music tracks");
    }
    return out;
}
void Report(const char* edition,const Result& x,unsigned m){
    std::cout<<'"'<<edition<<"\":{\"save_cycle\":"<<x.k<<",\"chunks\":"<<m<<",\"state_bytes\":"<<x.bytes
             <<",\"rasters\":"<<x.r.frames.size()<<",\"fighter_frames\":"<<x.r.fighter_frames<<",\"backdrop_frames\":"<<x.r.backdrop_frames
             <<",\"DAC_float32_samples\":"<<x.r.compared_samples/2<<",\"host_pcm_blocks\":"<<x.r.pcm.size()
             <<",\"music_starts\":"<<x.starts<<",\"input_requests\":"<<x.r.input.size()<<",\"passes\":2}";
}
}
int main(int argc,char** argv){try{
    check(argc==4,"expected authenticated ROM directory, factory seed and a scratch music folder");
    const auto program=mk2::LoadProgram(argv[1]);const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    std::ifstream seed_file(argv[2],std::ios::binary);const std::vector<uint8_t> seed{std::istreambuf_iterator<char>(seed_file),{}};
    check(seed.size()==16384 && Sha256(seed)=="f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f","seed identity differs");
    const std::filesystem::path tracks=std::filesystem::absolute(argv[3])/"tracks";WriteTracks(tracks,0);
    // Original: 10 chunks (20M cycles) across the selection press and release at 43.75M..46.25M.
    const auto original=Exercise(program,rom,seed,nullptr,40000000,10);
    // Remastered: 14 chunks from 155.3M, in the first fight: the DCS transform copy is live at that boundary, a user
    // track is repeating; it ends with a release tail near 158M, blood stays from 163M and the next cue starts near 181M.
    const auto remastered=Exercise(program,rom,seed,&tracks,155000000,14);
    check(remastered.starts && remastered.r.fighter_frames && remastered.r.backdrop_frames,"Remastered pass lost music, fighters or scenery");
    // Remastered: 6 chunks from 191.3M, with three floor stains kept and drawn, a cue entering its repeat window
    // and the transform copy live at the boundary.
    const auto blood=Exercise(program,rom,seed,&tracks,191000000,6);
    check(blood.r.fighter_frames && blood.r.backdrop_frames,"Remastered blood pass lost fighters or scenery");
    std::cout<<"{\"passed\":true,";Report("original",original,10);std::cout<<',';Report("remastered",remastered,14);
    std::cout<<',';Report("remastered_blood",blood,6);std::cout<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
