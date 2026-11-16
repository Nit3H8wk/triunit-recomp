#include "../mk2/mk2_music.hpp"
#include "../runtime/mk2_music_manifest.hpp"
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
int main(int argc,char** argv) {try {
    const float master=float(std::pow(10.0,mk5audio::master_db::mk2_remastered/20));
    mk2::RemasteredMix linear;
    for(float source:{-.02f,-.01f,0.f,.01f,.02f}){
        const auto stereo=linear.Render(source,{4000,-2000});
        for(unsigned c=0;c<2;++c){
            const float expected=(source*32768*mk2::RemasteredMix::original_gain+(c==0?1000:-500))*master;
            if(std::abs(float(stereo[c])-expected)>=1.01f)throw std::runtime_error("original mix or stereo music gain changed");
        }
    }
    for(float gain:{0.f,.025f,.125f,.25f}){
        const auto stereo=linear.Render(.01f,{4000,-2000},gain);
        for(unsigned c=0;c<2;++c){
            const float expected=(.01f*32768*mk2::RemasteredMix::original_gain+(c==0?4000:-2000)*gain)*master;
            if(std::abs(float(stereo[c])-expected)>=1.01f)throw std::runtime_error("firmware music attenuation affected original sounds");
        }
    }
    if(linear.Limited() || linear.Clipped())throw std::runtime_error("linear mix unnecessarily limited");
    mk2::RemasteredMix overload;
    for(float source:{1.25f,-1.25f,0.f}){
        const auto stereo=overload.Render(source,{32767,-32768});
        for(auto sample:stereo)if(std::abs(int(sample))>mk5audio::HostGain::ceiling)throw std::runtime_error("overload escaped peak ceiling");
        const float left=source*32768*mk2::RemasteredMix::original_gain+32767*.25f;
        const float right=source*32768*mk2::RemasteredMix::original_gain-32768*.25f;
        if(std::abs(stereo[0]*right-stereo[1]*left)>std::abs(left)+std::abs(right))
            throw std::runtime_error("peak protection changed stereo balance");
    }
    if(!overload.Limited() || overload.Clipped())throw std::runtime_error("peak protection did not prevent signed clipping");
    for(unsigned n=0;n<96000;++n)overload.Render(0,{0,0});
    const auto limited=overload.Limited();
    const auto recovered=overload.Render(.01f,{0,0});
    if(std::abs(recovered[0]-.01f*32768*mk2::RemasteredMix::original_gain*master)>1.f)
        throw std::runtime_error("peak protection failed to release");
    if(overload.Render(0,{0,0})!=std::array<int16_t,2>{0,0})throw std::runtime_error("peak protection manufactured sound");
    if(overload.Limited()!=limited)throw std::runtime_error("peak protection did not return to unity");
    for(float source:{std::numeric_limits<float>::max(),-std::numeric_limits<float>::max()}){
        const auto stereo=overload.Render(source,{32767,-32768});
        for(auto sample:stereo)if(std::abs(int(sample))>mk5audio::HostGain::ceiling)throw std::runtime_error("finite extreme escaped peak ceiling");
    }
    bool rejected=false;
    try{overload.Render(std::numeric_limits<float>::quiet_NaN(),{0,0});}catch(const std::invalid_argument&){rejected=true;}
    if(!rejected)throw std::runtime_error("non-finite mix accepted");
    if(mk2::MusicTrack(6)<0 || mk2::MusicTrack(5)<0 ||
       mk2::MusicTrack(0)>=0 || mk2::MusicTrack(0x221)>=0)
        throw std::runtime_error("MK2 confirmed music selectors and original fallback differ");
    for(const auto& cue:mk2::music_cues)if(cue.slot>=mk2::music_slots.size())throw std::runtime_error("MK2 cue names no slot");
    if(mk2::music_cues.at(mk2::MusicTrack(5)).slot!=mk2::music_cues.at(mk2::MusicTrack(6)).slot)
        throw std::runtime_error("MK2 music variants of one theme must share a slot");
    mk2::DcsLink link;mk2::AdspBoot dsp(std::vector<uint32_t>(376),link);
    const auto state=dsp.ExecutionState();
    {mk2::DcsEffects observer(dsp);
        if(dsp.ExecutionState()!=state)throw std::runtime_error("presentation changed canonical DSP state");
    }
    if(dsp.ExecutionState()!=state)throw std::runtime_error("presentation detach changed canonical DSP state");
    // Absent, corrupted and unset user folders: no cue has music, so Remastered plays the full DCS signal unchanged.
    if(argc==2){
        const std::filesystem::path root=std::filesystem::absolute(argv[1]);
        std::filesystem::create_directories(root/"corrupt");
        {std::ofstream f(root/"corrupt"/"music-01.wav",std::ios::binary);f<<"RIFF....WAVEfmt ";}
        std::vector<int16_t> reference;
        for(const auto& folder:{root/"absent",root/"corrupt",std::filesystem::path{}}){
            mk2::DcsLink l;mk2::AdspBoot d(std::vector<uint32_t>(376),l);
            std::vector<int16_t> out;
            mk2::RemasteredAudio audio(d,folder,[&](const int16_t* p,size_t n){out.insert(out.end(),p,p+n);});
            std::vector<float> source(512);
            for(uint64_t first=0;first<31250;first+=source.size()){
                for(size_t n=0;n<source.size();++n)source[n]=float(std::sin(double(first+n)*.01))*.02f;
                audio.Feed(first,source.data(),source.size());
            }
            if(audio.Starts()||out.empty())throw std::runtime_error("fallback folder started user music or produced no output");
            if(reference.empty())reference=out;
            else if(out!=reference)throw std::runtime_error("fallback output depends on the folder contents");
        }
    }
    std::cout<<"PASS MK2 music selectors, original fallback, absent/corrupt user folders and observer ownership\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
