// MK1 widescreen acceptance (tools/widescreen/acceptance.py): a legal tape played twice in the Remastered edition,
// without and with the widescreen shadow pass (debug diagnostics on, mk5wide::Layer::debug).
//  1. The game is the same in every shown frame: a hash of CPU registers, cycles, RAM, VRAM and palette per frame, the
//     shown frame and its Remastered layers, and at the end the PCM and CMOS.
//  2. The wide frame's 400 centre columns are the arcade frame bit for bit in every frame (raw and presented).
//  3. No margin pixel is left unwritten (sentinel) in a fight frame; masked pixels are counted (the edge policy).
//  4. No margin pixel comes from a draw that never meant to cover its column, or from no draw of the game.
//  2b. A frame whose wide camera is not the arcade's (mk5wide::WindowShift at an arena's end, a far plane held at its
//     art's end) is counted apart: its world is the shadow's draws, its HUD the real ones.
//  6. With the camera still, every scenery list's camera is still.
//  5. Each scenery layer's draws in the margins move by the same columns per frame as the layer's draws in the centre: per
//     layer and pair of builds, the most frequent move of its draws (one image on one row, paired in column order) wholly
//     in the margins equals that of its draws wholly in the centre, when at least 3 draws share it on each side, the
//     layer's list camera moved and the centre's draws moved by minus that move (scenery, not objects of their own motion).
// Prints one JSON line with the counts and, per arena (its camera limits) and scenery layer, the margin columns its art
// covers at least (the edge coverage table). Inputs: the tape (tools/mk1/tapes, rendered by the caller), the setup's seed.
#include "mk5_task_body.hpp"
#include "mk5_scanout.hpp"
#include "mk5_live_video.hpp"
#include "mk5_audio.hpp"
#include "mk5_audio_link.hpp"
#include "mk5_widescreen.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>

namespace {
void check(bool value,const std::string& message){if(!value)throw std::runtime_error(message);}
std::vector<uint8_t> bytes(const std::filesystem::path& p){std::ifstream f(p,std::ios::binary);check(bool(f),"cannot open chip ROM");return {std::istreambuf_iterator<char>(f),{}};}
template<class V> uint64_t Fnv(uint64_t h,const V& v){for(auto x:v)h=(h^uint64_t(x))*0x100000001b3ull;return h;}
constexpr uint64_t kBasis=14695981039346656037ull;
struct Frame{uint64_t state,shown;};
// The edge coverage table: per arena (camera limits) and scenery layer, the fewest margin columns its art covered.
struct Coverage{int left=mk5wide::kWideMargin,right=mk5wide::kWideMargin;unsigned frames=0;int camera_low=1<<20,camera_high=-(1<<20);};
struct Run{
    std::vector<Frame> frames;std::vector<int16_t> pcm;std::vector<uint16_t> cmos;uint64_t faults=0;
    uint64_t centre=0,presented=0,fight_frames=0;mk5wide::Audit fight,other;
    // Frames with a window offset (mk5wide::WindowShift): how many, their arcade columns that differ from the arcade frame
    // at the offset (far planes stand elsewhere there), and their masked margin pixels.
    uint64_t shifted_frames=0,shifted_differ=0,shifted_masked=0;
    uint64_t still_checked=0,still_moved=0;   // builds whose last scenery list (the world's) kept its camera; of them, with a list that moved
    uint64_t parallax_checked=0,parallax_differ=0;std::map<std::tuple<int,int,int>,Coverage> coverage;
};
Run Play(const std::filesystem::path& root,const std::vector<uint32_t>& tape,const std::vector<uint16_t>& cmos,bool widescreen){
    auto program=LoadMk5Program(root/"roms");auto graphics=LoadMk5GlyphBank(root/"roms");
    const auto rom=root/"roms/mk1";
    mk5audio::WilliamsAudio audio(bytes(rom/"mks-u3.rom"),bytes(rom/"mks-u12.rom"),bytes(rom/"mks-u13.rom"));
    mk5audio::GameAudioScope scope(audio);
    Run run;Mk5MemoryBuffers m;Mk5BoardState f;f.cmos=cmos;auto& s=f.check.cpu;BootDiState di;
    Mk5IrqController irq(program,s,m);Mk5TaskBodyRunner runner(program,f,m,irq,di);
    const BootDiInputs released{0xffffffff,0xfeffffff};
    Mk5BootInputs power_on;power_on.ports=released;power_on.pending=0x400;power_on.next_line=1;power_on.quanta_to_next=6325;
    check(runner.Boot(power_on).stop==TaskBodyStop::TaskEntry,"power-on did not reach the first task");
    TaskBodyInputs in;in.dsw=0xfeff;in.main_dsw=0xfeff;in.sound_status=0x80;in.quiet_di=released;
    check(runner.Run(in).stop==TaskBodyStop::MainLoop,"runner did not enter the main loop");
    runner.AttachVideo(graphics,true);
    Mk5Scanout screen(irq,m,&runner.Video());
    if(widescreen){runner.EnableWide();screen.EnableWidePresentation(runner.Video());}
    in.active_di=released;in.stop_after_decompression=true;
    TaskBodyResult result;
    for(unsigned i=0;i<100;++i){result=runner.ContinueMain(in,64);if(result.stop!=TaskBodyStop::Budget && result.stop!=TaskBodyStop::DiLimit)break;}
    check(result.stop==TaskBodyStop::DecompressorComplete,"original decompression did not complete");
    in.stop_after_decompression=false;in.instruction_budget=10000;
    const unsigned W=Mk5Scanout::kWideWidth;const auto& layer=runner.Video().WideLayer();
    std::vector<mk5wide::Note> previous;unsigned seen_builds=0;
    const auto word=[&](uint32_t bit){return m.ram[(bit-0x01000000)/16];};
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
        uint64_t state=Fnv(Fnv(Fnv(Fnv(kBasis,s.a),s.b),m.ram),m.vram);state=Fnv(Fnv(state,m.palette),std::array<uint64_t,2>{s.reference_cycles,s.status});
        run.frames.push_back({state,Fnv(Fnv(Fnv(kBasis,screen.pixels()),screen.backdrop_pixels()),layers)});
        if(!widescreen)continue;
        // 2: the centre, raw and presented (pixels and backdrop).
        const unsigned X=screen.width(),H=screen.height(),margin=(W-X)/2;
        const auto& wide=screen.wide_pixels();const auto& p=screen.wide_presentation();const auto& b=screen.wide_backdrop_pixels();
        const int shift=screen.wide_shift();const bool whole=screen.wide_whole();
        if(whole){++run.shifted_frames;run.shifted_masked+=screen.wide_audit().masked;}
        for(unsigned y=0;y<H;++y)for(unsigned x=0;x<X;++x){
            if(whole){run.shifted_differ+=p[y*W+margin+x-shift]!=screen.pixels()[y*X+x];continue;}
            run.centre+=wide[y*W+margin+x]!=screen.pixels()[y*X+x];
            run.presented+=p[y*W+margin+x]!=screen.pixels()[y*X+x];
            if(!screen.backdrop_pixels().empty())run.presented+=b[y*W+margin+x]!=screen.backdrop_pixels()[y*X+x];
        }
        // Diagnostics: WIDE_DUMP_FRAMES (frame numbers, commas) writes each one's presented wide frame as a PPM in WIDE_DUMP_DIR.
        if(const char* list=std::getenv("WIDE_DUMP_FRAMES");list&&(","+std::string(list)+",").find(","+std::to_string(before)+",")!=std::string::npos){
            std::ofstream out(std::filesystem::path(std::getenv("WIDE_DUMP_DIR"))/("wide-"+std::to_string(before)+".ppm"),std::ios::binary);
            out<<"P6"<<char(10)<<W<<" "<<H<<char(10)<<255<<char(10);for(auto rgb:p){out.put(char(rgb>>16));out.put(char(rgb>>8));out.put(char(rgb));}
        }
        if(std::getenv("WIDE_TRACE")){static int last=1<<20;if(shift!=last){last=shift;
            std::cerr<<"shift frame "<<before<<" d "<<shift<<" camera "<<int16_t(word(mk5widescreen::kCameraX))<<" mode "<<word(mk5widescreen::kMode);
            for(const auto& r:layer.ratio)std::cerr<<" "<<r.plane<<"/"<<r.world;
            for(unsigned k=0;k<mk5widescreen::kScrollSlots;++k)std::cerr<<" S"<<k<<"="<<int16_t(word(mk5widescreen::kScrollFirst+k*0x20+16));
            for(const auto& lim:layer.bound)std::cerr<<" ["<<lim[0]<<","<<lim[1]<<"]";
            std::map<int,int> cameras;for(const auto& k:layer.notes_done)cameras[k.layer]=k.camera;
            for(const auto& [l,c]:cameras)std::cerr<<" L"<<l<<"@"<<c;
            std::cerr<<char(10);}}
        // 3, 4: the margins' audit; fight frames apart.
        const unsigned mode=word(mk5widescreen::kMode);const bool fight=mode==2||mode==3||mode==5||mode==6;
        (fight?run.fight:run.other).Add(screen.wide_audit());run.fight_frames+=fight;
        // 5: per layer, the most frequent move of its draws (same image and row in the last build) in the margins and in
        // the centre.
        if(layer.builds!=seen_builds){seen_builds=layer.builds;
            // The draws of one image on one row pair up in column order when both builds have as many of them.
            std::map<std::tuple<uint16_t,uint32_t,uint16_t>,std::array<std::vector<const mk5wide::Note*>,2>> runs;
            for(const auto& k:previous)runs[{k.layer,k.source,k.row}][0].push_back(&k);
            for(const auto& k:layer.notes_done)runs[{k.layer,k.source,k.row}][1].push_back(&k);
            std::map<uint16_t,std::array<std::map<int,int>,2>> moves;   // layer -> [centre, margin] move -> count
            std::map<uint16_t,std::vector<std::string>> margin_pairs;   // diagnostics of a divergence
            for(auto& [key,two]:runs){
                if(two[0].size()!=two[1].size())continue;
                for(auto& v:two)std::sort(v.begin(),v.end(),[](const mk5wide::Note* a,const mk5wide::Note* b){return a->lo<b->lo;});
                for(size_t i=0;i<two[1].size();++i){
                    const auto& k=*two[1][i];
                    const bool in_margin=(k.hi<=mk5wide::kWideMargin||k.lo>=mk5wide::kWideMargin+mk5wide::kVisible)&&k.hi>0&&k.lo<mk5wide::kLayerWidth;   // shown in a margin
                    const bool in_centre=k.lo>=mk5wide::kWideMargin&&k.hi<=mk5wide::kWideMargin+mk5wide::kVisible;
                    if(in_margin||in_centre)++moves[k.layer][in_margin?1:0][k.lo-two[0][i]->lo];
                    if(in_margin)margin_pairs[k.layer].push_back(std::to_string(k.source)+"@"+std::to_string(k.row)+":"+std::to_string(two[0][i]->lo)+">"+std::to_string(k.lo));
                }
            }
            const auto mode_of=[](const std::map<int,int>& counts){int best=0,most=0;for(const auto& [move,count]:counts)if(count>most){most=count;best=move;}return std::make_pair(best,most);};
            std::map<uint16_t,int> camera_move;   // per layer: the scenery's move, minus its list camera's
            {std::map<uint16_t,int> was;for(const auto& k:previous)was[k.layer]=k.camera;
             for(const auto& k:layer.notes_done)if(was.count(k.layer))camera_move[k.layer]=was[k.layer]-k.camera;}
            // 6: with the camera still every plane stands still (a plane's place depends on the camera alone).
            if(!camera_move.empty()&&!camera_move.rbegin()->second){++run.still_checked;
                for(const auto& [l,move]:camera_move)if(move){++run.still_moved;break;}}
            for(const auto& [l,both]:moves)if(!both[0].empty()&&!both[1].empty()&&camera_move.count(l)&&camera_move[l]&&mode_of(both[0]).first==camera_move[l]){
                const auto c=mode_of(both[0]),g=mode_of(both[1]);   // the centre's scenery moved with the camera: the margins' must too
                if(c.second>=3&&g.second>=3){   // at least 3 draws moved alike on each side: scenery, not one moving object
                    ++run.parallax_checked;run.parallax_differ+=c.first!=g.first;
                    if(c.first!=g.first)std::cerr<<"parallax frame "<<before<<" layer "<<l<<" centre "<<c.first<<"x"<<c.second<<" margin "<<g.first<<"x"<<g.second<<" camera "<<int16_t(word(mk5widescreen::kCameraX));
                    if(c.first!=g.first)for(const auto& d:margin_pairs[l])std::cerr<<" "<<d;
                    if(c.first!=g.first)std::cerr<<char(10);}
            }
            previous=layer.notes_done;
        }
        // The edge coverage table (fight frames): per layer measured this build, the margin columns its art covers.
        if(fight)for(const auto& band:layer.bands_done){
            auto& c=run.coverage[{int16_t(word(mk5widescreen::kCameraMin)),int16_t(word(mk5widescreen::kCameraMax)),band.layer}];
            const int camera=int16_t(word(mk5widescreen::kCameraX));
            c.camera_low=std::min(c.camera_low,camera);c.camera_high=std::max(c.camera_high,camera);++c.frames;
            for(const auto& r:band.rows){
                c.left=std::min(c.left,std::max(0,mk5wide::kWideMargin-std::max<int>(r.left,0)));
                c.right=std::min(c.right,std::max(0,std::min<int>(r.right,mk5wide::kLayerWidth)-(mk5wide::kWideMargin+mk5wide::kVisible)));
            }
        }
    }
    check(screen.frames()==tape.size(),"legal tape endpoint not reached");
    run.cmos=f.cmos;run.faults=runner.Video().wide_faults;
    return run;
}
std::string Json(const mk5wide::Audit& a){
    return "{\"shown\":"+std::to_string(a.shown)+",\"sentinel\":"+std::to_string(a.sentinel)+",\"masked\":"+std::to_string(a.masked)+
           ",\"outside\":"+std::to_string(a.outside)+",\"generated\":"+std::to_string(a.generated)+",\"stale\":"+std::to_string(a.stale)+"}";
}
}
int wmain(int argc,wchar_t** argv){
    try{
        check(argc==4,"usage: root tape seed");
        _wputenv(L"TRIUNIT_WIDE_DEBUG=1");
        std::ifstream timeline(argv[2]);check(bool(timeline),"missing legal tape");std::string header;std::getline(timeline,header);
        std::vector<uint32_t> tape;unsigned frame,duration;uint32_t mask;
        while(timeline>>frame>>duration>>mask){if(tape.size()<frame+duration)tape.resize(frame+duration);for(unsigned k=0;k<duration;++k)tape[frame+k]=mask;}
        const auto cmos=LoadMk5CmosSnapshot(argv[3]);
        const auto plain=Play(argv[1],tape,cmos,false),wide=Play(argv[1],tape,cmos,true);
        check(plain.frames.size()==wide.frames.size(),"frame counts differ");
        for(size_t i=0;i<wide.frames.size();++i){
            check(plain.frames[i].state==wide.frames[i].state,"1: widescreen changed the game state at frame "+std::to_string(i));
            check(plain.frames[i].shown==wide.frames[i].shown,"1: widescreen changed the shown frame or its Remastered layers at frame "+std::to_string(i));
        }
        check(plain.pcm==wide.pcm && plain.cmos==wide.cmos,"1: widescreen changed the PCM or the CMOS");
        check(!wide.faults,"the shadow pass faulted");
        std::cout<<"{\"frames\":"<<wide.frames.size()<<",\"fight_frames\":"<<wide.fight_frames<<",\"centre_differ\":"<<wide.centre
                 <<",\"presented_differ\":"<<wide.presented<<",\"shifted_frames\":"<<wide.shifted_frames<<",\"shifted_differ\":"<<wide.shifted_differ
                 <<",\"shifted_masked\":"<<wide.shifted_masked<<",\"still_checked\":"<<wide.still_checked<<",\"still_moved\":"<<wide.still_moved<<",\"fight\":"<<Json(wide.fight)<<",\"other\":"<<Json(wide.other)
                 <<",\"parallax_checked\":"<<wide.parallax_checked<<",\"parallax_differ\":"<<wide.parallax_differ<<",\"coverage\":[";
        bool first=true;
        for(const auto& [key,c]:wide.coverage){
            std::cout<<(first?"":",")<<"["<<std::get<0>(key)<<","<<std::get<1>(key)<<","<<std::get<2>(key)<<","<<c.frames<<","<<c.camera_low<<","<<c.camera_high<<","<<c.left<<","<<c.right<<"]";first=false;
        }
        std::cout<<"]}\n";
        // The raw layer has no floor blood (the presentation lays it over both): the shown frame is the one compared.
        check(!wide.presented,"2: the wide frame's centre differs from the arcade frame");
        check(!wide.fight.sentinel,"3: a fight frame shows a margin pixel no draw wrote");
        check(!wide.fight.outside && !wide.other.outside && !wide.fight.generated && !wide.other.generated && !wide.fight.stale,
              "4: a margin pixel does not belong to a draw meant to cover its column");
        check(!wide.parallax_differ && wide.parallax_checked,"5: a layer moves differently in the margins and in the centre");
        check(!wide.still_moved,"6: a scenery plane moved while the camera stood still");
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
