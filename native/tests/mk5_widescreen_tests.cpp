// MK1 widescreen (W1-W3): a legal route tape played twice in the Remastered edition, without and with the widescreen
// shadow pass. The game is the same (every shown frame and its Remastered layers, the PCM, CPU, cycles, RAM, VRAM,
// palette and CMOS), the shadow pass never faults, the wide frame's centre is the arcade's frame in every centred frame
// with no fitted plane (raw capture and Remastered presentation, backdrop included), and the margins carry the arena's
// art beyond what VRAM itself holds there. Inputs: the tape (tools/mk1/tapes, rendered by the caller), the setup's seed.
#include "mk5_task_body.hpp"
#include "mk5_scanout.hpp"
#include "mk5_live_video.hpp"
#include "mk5_audio.hpp"
#include "mk5_audio_link.hpp"
#include <fstream>
#include <iostream>
#include <memory>

namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
std::vector<uint8_t> bytes(const std::filesystem::path& p){std::ifstream f(p,std::ios::binary);check(bool(f),"cannot open chip ROM");return {std::istreambuf_iterator<char>(f),{}};}
uint64_t Fnv(uint64_t h,const std::vector<uint32_t>& v){for(auto x:v)h=(h^x)*0x100000001b3ull;return h;}
struct Frame {uint64_t shown,wide;int shift;unsigned fitted;uint64_t centre,margin,presented_centre;};
struct Run {
    std::vector<Frame> frames;std::vector<int16_t> pcm;
    std::array<uint32_t,16> a{};uint64_t cycles=0;Mk5MemoryBuffers m;std::vector<uint16_t> cmos;uint64_t faults=0;
};
Run Play(const std::filesystem::path& root,const std::vector<uint32_t>& tape,const std::vector<uint16_t>& cmos,bool widescreen){
    auto program=LoadMk5Program(root/"roms");auto graphics=LoadMk5GlyphBank(root/"roms");
    const auto rom=root/"roms/mk1";
    mk5audio::WilliamsAudio audio(bytes(rom/"mks-u3.rom"),bytes(rom/"mks-u12.rom"),bytes(rom/"mks-u13.rom"));
    mk5audio::GameAudioScope scope(audio);
    Run run;Mk5BoardState f;f.cmos=cmos;auto& s=f.check.cpu;BootDiState di;
    Mk5IrqController irq(program,s,run.m);Mk5TaskBodyRunner runner(program,f,run.m,irq,di);
    const BootDiInputs released{0xffffffff,0xfeffffff};
    Mk5BootInputs power_on;power_on.ports=released;power_on.pending=0x400;power_on.next_line=1;power_on.quanta_to_next=6325;
    check(runner.Boot(power_on).stop==TaskBodyStop::TaskEntry,"power-on did not reach the first task");
    TaskBodyInputs in;in.dsw=0xfeff;in.main_dsw=0xfeff;in.sound_status=0x80;in.quiet_di=released;
    check(runner.Run(in).stop==TaskBodyStop::MainLoop,"runner did not enter the main loop");
    runner.AttachVideo(graphics,true);
    Mk5Scanout screen(irq,run.m,&runner.Video());
    // Without widescreen the capture is VRAM's own 512 columns (the margins as the arcade leaves them).
    if(widescreen){runner.EnableWide();screen.EnableWidePresentation(runner.Video());}else screen.EnableWide(runner.Video());
    in.active_di=released;in.stop_after_decompression=true;
    TaskBodyResult result;
    for(unsigned i=0;i<100;++i){result=runner.ContinueMain(in,64);if(result.stop!=TaskBodyStop::Budget && result.stop!=TaskBodyStop::DiLimit)break;}
    check(result.stop==TaskBodyStop::DecompressorComplete,"original decompression did not complete");
    in.stop_after_decompression=false;in.instruction_budget=10000;
    const unsigned W=Mk5Scanout::kWideWidth;
    for(unsigned n=0;screen.frames()<tape.size() && n<tape.size()*250;++n){
        const auto before=screen.frames();
        in.active_di=BootDiInputs{0xffffffffu&~tape[before],0xfeffffff};
        result=runner.ContinueMain(in,64);
        check(result.stop==TaskBodyStop::Budget || result.stop==TaskBodyStop::DiLimit,"MK1 replay left the native route");
        const auto& pcm=audio.Pcm();run.pcm.insert(run.pcm.end(),pcm.begin(),pcm.end());audio.DiscardDiagnostics();
        runner.CompactDiagnostics();
        if(screen.frames()==before)continue;
        check(screen.frames()==before+1,"observer missed a raster frame");
        const auto& fighter=screen.fighter_frame();
        std::vector<uint32_t> layers(fighter.underlay);for(auto o:fighter.opaque_order)layers.push_back(uint32_t(o));
        for(const auto& l:fighter.layers){layers.push_back(uint32_t(l.x));layers.push_back(l.y);layers.insert(layers.end(),l.pixels.begin(),l.pixels.end());}
        Frame frame{Fnv(Fnv(Fnv(14695981039346656037ull,screen.pixels()),screen.backdrop_pixels()),layers),
                    Fnv(14695981039346656037ull,screen.wide_pixels()),screen.wide_shift(),screen.wide_fitted(),screen.wide_centre(),0,0};
        const auto& wide=screen.wide_pixels();const unsigned X=screen.width(),H=screen.height(),margin=(W-X)/2;
        for(unsigned y=0;y<H;++y)for(unsigned x=0;x<W;++x)if(x<margin||x>=margin+X)frame.margin=Fnv(frame.margin,{wide[y*W+x]});
        if(widescreen && !frame.shift && !frame.fitted){   // the presented wide frame's centre is the presented frame
            const auto& p=screen.wide_presentation();const auto& b=screen.wide_backdrop_pixels();
            for(unsigned y=0;y<H;++y)for(unsigned x=0;x<X;++x){
                frame.presented_centre+=p[y*W+margin+x]!=screen.pixels()[y*X+x];
                if(!screen.backdrop_pixels().empty())frame.presented_centre+=b[y*W+margin+x]!=screen.backdrop_pixels()[y*X+x];
            }
        }
        run.frames.push_back(frame);
    }
    check(screen.frames()==tape.size(),"legal tape endpoint not reached");
    run.a=s.a;run.cycles=s.reference_cycles;run.cmos=f.cmos;run.faults=runner.Video().wide_faults;
    return run;
}
}
int wmain(int argc,wchar_t** argv){
    try{
        check(argc==4,"usage: root tape seed");
        std::ifstream timeline(argv[2]);check(bool(timeline),"missing legal tape");std::string header;std::getline(timeline,header);
        std::vector<uint32_t> tape;unsigned frame,duration;uint32_t mask;
        while(timeline>>frame>>duration>>mask){if(tape.size()<frame+duration)tape.resize(frame+duration);for(unsigned k=0;k<duration;++k)tape[frame+k]=mask;}
        const auto cmos=LoadMk5CmosSnapshot(argv[3]);
        const auto plain=Play(argv[1],tape,cmos,false),wide=Play(argv[1],tape,cmos,true);
        check(plain.a==wide.a && plain.cycles==wide.cycles && plain.m.ram==wide.m.ram && plain.m.vram==wide.m.vram &&
              plain.m.palette==wide.m.palette && plain.cmos==wide.cmos,"widescreen changed the game state");
        check(plain.pcm==wide.pcm,"widescreen changed the PCM");
        check(plain.frames.size()==wide.frames.size(),"frame counts differ");
        check(!wide.faults,"the shadow pass faulted");
        uint64_t centred=0,art=0,shifted=0;
        for(size_t i=0;i<wide.frames.size();++i){
            const auto& p=plain.frames[i];const auto& w=wide.frames[i];
            check(p.shown==w.shown,"widescreen changed a shown frame or its Remastered layers");
            if(!w.shift && !w.fitted){++centred;check(!w.centre && !w.presented_centre,"a centred wide frame differs from the arcade's");}
            shifted+=w.shift!=0;art+=w.margin!=p.margin;
        }
        check(centred>wide.frames.size()/2 && art>wide.frames.size()/4,"too few centred frames or margins with the shadow's art");
        std::cout<<"{\"frames\":"<<wide.frames.size()<<",\"centred_exact\":"<<centred<<",\"shifted\":"<<shifted<<",\"margins_with_art\":"<<art
                 <<",\"pcm_samples\":"<<wide.pcm.size()<<"}\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
