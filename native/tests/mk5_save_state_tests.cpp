// MK1 save states: save between two ContinueMain calls of the live loop (after the diagnostic trim), record m calls,
// load and replay them: same rasters, Remastered layers, host PCM (after the host gain) and complete serialized state.
// The same state then loads into a second session at another boundary. Original, then Remastered with music
// (synthetic user tracks written by this test). Inputs: a legal route tape (tools/mk1/tapes, rendered by the caller).
#include "mk5_save_state.hpp"
#include "mk5_audio_link.hpp"
#include "mk5_audio_output.hpp"
#include "../runtime/remastered_music_manifest.hpp"
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>

namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
std::vector<uint8_t> bytes(const std::filesystem::path& p){std::ifstream f(p,std::ios::binary);check(bool(f),"cannot open chip ROM");return {std::istreambuf_iterator<char>(f),{}};}
struct Frame {uint64_t frame;std::vector<uint32_t> pixels;std::string layers;};
struct Recording {
    enum class Mode {off,record,compare} mode=Mode::off;
    std::vector<Frame> frames;std::vector<std::vector<int16_t>> pcm;size_t frame=0,block=0;uint64_t fighter_frames=0,samples=0;
    void Rewind(){frame=block=0;}
    bool Complete()const{return frame==frames.size() && block==pcm.size();}
};
std::string Layers(const Mk5Scanout& s){
    mk2::state::Writer w;auto backdrop=s.backdrop_pixels();auto fighters=s.fighter_frame();w(backdrop,fighters);return Sha256(w.bytes);
}
struct Inputs {std::vector<uint32_t> masks;uint32_t At(uint64_t frame)const{return frame<masks.size()?masks[frame]:0;}};
Inputs ReadTape(const std::filesystem::path& path){
    std::ifstream timeline(path);check(bool(timeline),"missing legal tape");std::string header;std::getline(timeline,header);
    Inputs in;unsigned frame,duration;uint32_t mask;
    while(timeline>>frame>>duration>>mask){if(in.masks.size()<frame+duration)in.masks.resize(frame+duration);for(unsigned n=0;n<duration;++n)in.masks[frame+n]=mask;}
    return in;
}
// The product's live objects (mk5_boot_flow_cli.cpp visual stage, probe_audio_main.cpp audio), without the window.
struct Session {
    const VerifiedMk5Program& program;
    mk5audio::WilliamsAudio audio;mk5audio::GameAudioScope scope{audio};mk5audio::HostGain gain;std::vector<int16_t> gained;
    Mk5MemoryBuffers m;Mk5BoardState f;BootDiState di;
    std::unique_ptr<Mk5IrqController> irq;std::unique_ptr<Mk5TaskBodyRunner> runner;std::unique_ptr<Mk5Scanout> screen;
    TaskBodyInputs in;const Inputs& tape;Recording& r;bool remastered;
    Session(const VerifiedMk5Program& p,const std::filesystem::path& root,const std::vector<uint16_t>& cmos,const VerifiedMk5GlyphBank& graphics,
            const Inputs& t,Recording& rec,const std::filesystem::path* tracks)
        :program(p),audio(bytes(root/"roms/mk1/mks-u3.rom"),bytes(root/"roms/mk1/mks-u12.rom"),bytes(root/"roms/mk1/mks-u13.rom")),
         gain(tracks?mk5audio::master_db::mk1_remastered:mk5audio::master_db::mk1_original),tape(t),r(rec),remastered(tracks!=nullptr){
        if(tracks)audio.EnableRemasteredMusic(*tracks);
        mk5audio::SetGameAudioConsumer([this](const int16_t* data,size_t count){
            gained.resize(count);gain.Process(data,gained.data(),count,remastered?2:1);
            if(r.mode==Recording::Mode::record){r.pcm.emplace_back(gained);r.samples+=count;}
            else if(r.mode==Recording::Mode::compare){check(r.block<r.pcm.size() && r.pcm[r.block]==gained,"load changed host PCM output");++r.block;}
        });
        f.cmos=cmos;auto& s=f.check.cpu;
        irq=std::make_unique<Mk5IrqController>(p,s,m);runner=std::make_unique<Mk5TaskBodyRunner>(p,f,m,*irq,di);
        const BootDiInputs released{0xffffffff,0xfeffffff};
        Mk5BootInputs power_on;power_on.ports=released;power_on.pending=0x400;power_on.next_line=1;power_on.quanta_to_next=6325;
        check(runner->Boot(power_on).stop==TaskBodyStop::TaskEntry,"power-on did not reach the first task");
        in.dsw=0xfeff;in.main_dsw=0xfeff;in.sound_status=0x80;in.quiet_di=released;
        check(runner->Run(in).stop==TaskBodyStop::MainLoop,"runner did not enter the main loop");
        runner->AttachVideo(graphics,remastered);
        screen=std::make_unique<Mk5Scanout>(*irq,m,remastered?&runner->Video():nullptr);
        in.active_di=released;in.stop_after_decompression=true;
        TaskBodyResult result;
        for(unsigned i=0;i<100;++i){result=runner->ContinueMain(in,64);if(result.stop!=TaskBodyStop::Budget && result.stop!=TaskBodyStop::DiLimit)break;}
        check(result.stop==TaskBodyStop::DecompressorComplete,"original decompression did not complete");
        in.stop_after_decompression=false;in.instruction_budget=10000;
    }
    ~Session(){screen.reset();}
    Mk5LiveSession Live(){return {*runner,*screen,audio,gain};}
    // One product loop iteration: inputs of the shown frame, ContinueMain, then the trim that publishes the PCM.
    void Call(){
        const auto before=screen->frames();
        in.active_di=BootDiInputs{0xffffffffu&~tape.At(before),0xfeffffff};
        const auto result=runner->ContinueMain(in,64);
        check(result.stop==TaskBodyStop::Budget || result.stop==TaskBodyStop::DiLimit,"MK1 replay left the native route");
        runner->CompactDiagnostics();check(mk5audio::TrimGameAudioDiagnostics(),"PCM trim needs the consumer");
        if(screen->frames()==before)return;
        const auto layers=remastered?Layers(*screen):std::string{};
        if(r.mode==Recording::Mode::record){r.frames.push_back({screen->frames(),screen->pixels(),layers});r.fighter_frames+=screen->fighter_frame().serial!=0;}
        else if(r.mode==Recording::Mode::compare){
            check(r.frame<r.frames.size(),"load emitted an extra raster");const auto& e=r.frames[r.frame++];
            check(e.frame==screen->frames() && e.pixels==screen->pixels(),"load changed complete raster pixels or frame");
            check(e.layers==layers,"load changed Remastered blood, scenery or fighter layers");
        }
    }
    void UntilFrame(uint64_t frame){while(screen->frames()<frame)Call();}
    void Calls(uint64_t n){for(uint64_t k=0;k<n;++k)Call();}
};
template<class Error,class F> void refused(F&& f,const char* message){bool thrown=false;try{f();}catch(const Error&){thrown=true;}check(thrown,message);}
void WriteTracks(const std::filesystem::path& folder,double gain_db){
    std::filesystem::create_directories(folder);std::ofstream json(folder/"slots.json");json<<"{\"slots\":{";
    for(size_t slot=0;slot<mk5audio::remastered_slots.size();++slot){
        constexpr uint32_t frames=96000;std::vector<int16_t> pcm(frames*2);
        for(uint32_t n=0;n<frames;++n)for(unsigned c=0;c<2;++c)pcm[n*2+c]=int16_t(6000*std::sin(double(n)*(0.01+0.002*double(slot+c))));
        const uint32_t data=uint32_t(pcm.size()*2);
        std::ofstream wav(folder/(std::string(mk5audio::remastered_slots[slot].slot)+".wav"),std::ios::binary);
        const auto le=[&wav](uint32_t value,unsigned n){for(unsigned b=0;b<n;++b)wav.put(char(value>>(8*b)));};
        wav<<"RIFF";le(36+data,4);wav<<"WAVEfmt ";le(16,4);le(1,2);le(2,2);le(48000,4);le(192000,4);le(4,2);le(16,2);
        wav<<"data";le(data,4);wav.write(reinterpret_cast<const char*>(pcm.data()),std::streamsize(data));check(bool(wav),"cannot write synthetic track");
        json<<(slot?",":"")<<'"'<<mk5audio::remastered_slots[slot].slot<<"\":{\"loop_begin\":0.5,\"loop_end\":1.5,\"gain_db\":"<<gain_db<<'}';
    }
    json<<"}}";check(bool(json),"cannot write synthetic slots.json");
}
struct Result {uint64_t frame=0,bytes=0,calls=0;Recording r;};
Result Exercise(const VerifiedMk5Program& p,const std::filesystem::path& root,const std::vector<uint16_t>& cmos,const VerifiedMk5GlyphBank& g,
                const Inputs& tape,const std::filesystem::path* tracks,uint64_t save_frame,uint64_t frames){
    Result out;auto& r=out.r;std::vector<uint8_t> saved,expected;mk5state::Identity identity;
    {
        Session a(p,root,cmos,g,tape,r,tracks);
        a.UntilFrame(save_frame);a.Calls(2);   // mid-frame, as an F5 at any instant: the partial raster is state
        out.frame=a.screen->frames();saved=Mk5SaveLiveState(a.Live());out.bytes=saved.size();identity=mk5state::LiveIdentity(a.Live());
        r.mode=Recording::Mode::record;while(a.screen->frames()<save_frame+frames){a.Call();++out.calls;}r.mode=Recording::Mode::off;
        expected=Mk5SaveLiveState(a.Live());
        check(!r.frames.empty() && !r.pcm.empty(),"recorded pass is empty");
        Mk5LoadLiveState(saved,a.Live());
        check(a.screen->frames()==out.frame && Mk5SaveLiveState(a.Live())==saved,"load did not restore the saved boundary");
        r.mode=Recording::Mode::compare;a.Calls(out.calls);r.mode=Recording::Mode::off;
        check(r.Complete() && Mk5SaveLiveState(a.Live())==expected,"in-session load left unmatched output or state");
    }
    {   // A later session (as after a restart with the slot file) loads at another boundary of its own.
        Session b(p,root,cmos,g,tape,r,tracks);b.Calls(3);
        check(b.screen->frames()!=out.frame,"second session must load from a different boundary");
        Mk5LoadLiveState(saved,b.Live());r.Rewind();
        r.mode=Recording::Mode::compare;b.Calls(out.calls);r.mode=Recording::Mode::off;
        check(r.Complete() && Mk5SaveLiveState(b.Live())==expected,"cross-session load left unmatched output or state");
    }
    auto damaged=saved;damaged.back()^=1;
    refused<std::invalid_argument>([&]{mk5state::CheckLiveState(damaged,identity);},"damaged payload accepted");
    auto truncated=saved;truncated.resize(truncated.size()/2);
    refused<std::invalid_argument>([&]{mk5state::CheckLiveState(truncated,identity);},"truncated state accepted");
    auto edition=identity;edition.edition=tracks?"original":"remastered";
    refused<std::invalid_argument>([&]{mk5state::CheckLiveState(saved,edition);},"state accepted by another edition");
    if(tracks){
        const auto folder=tracks->parent_path()/"other-tracks";WriteTracks(folder,-1);
        mk5audio::WilliamsAudio other(bytes(root/"roms/mk1/mks-u3.rom"),bytes(root/"roms/mk1/mks-u12.rom"),bytes(root/"roms/mk1/mks-u13.rom"));
        other.EnableRemasteredMusic(folder);
        auto retracked=identity;retracked.music=other.MusicFingerprint();
        check(retracked.music!=identity.music,"other user tracks kept the fingerprint");
        refused<std::invalid_argument>([&]{mk5state::CheckLiveState(saved,retracked);},"state accepted with other music tracks");
    }
    return out;
}
void Report(const char* edition,const Result& x){
    std::cout<<'"'<<edition<<"\":{\"save_frame\":"<<x.frame<<",\"calls\":"<<x.calls<<",\"state_bytes\":"<<x.bytes<<",\"rasters\":"<<x.r.frames.size()
             <<",\"fighter_frames\":"<<x.r.fighter_frames<<",\"host_pcm_blocks\":"<<x.r.pcm.size()<<",\"host_pcm_samples\":"<<x.r.samples<<",\"passes\":2}";
}
}
int wmain(int argc,wchar_t** argv){try{
    check(argc==5,"expected project root, rendered tape, CMOS seed and a scratch music folder");
    const std::filesystem::path root=argv[1];
    const auto program=LoadMk5Program(root/"roms");const auto graphics=LoadMk5GlyphBank(root/"roms");
    const auto cmos=LoadMk5CmosSnapshot(argv[3]);const auto tape=ReadTape(argv[2]);
    const auto tracks=std::filesystem::absolute(argv[4])/"tracks";WriteTracks(tracks,0);
    constexpr uint64_t save_frame=3150,frames=600;   // in the versus fight, with a floor stain kept since ~frame 3100
    const auto original=Exercise(program,root,cmos,graphics,tape,nullptr,save_frame,frames);
    const auto remastered=Exercise(program,root,cmos,graphics,tape,&tracks,save_frame,frames);
    check(remastered.r.fighter_frames!=0,"Remastered pass lost the fighter layers");
    std::cout<<"{\"passed\":true,";Report("original",original);std::cout<<',';Report("remastered",remastered);std::cout<<"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
