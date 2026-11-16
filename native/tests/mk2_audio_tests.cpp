#include "../mk2/mk2_music.hpp"
#include <iostream>
#include <limits>
#include <vector>

namespace {
void check(bool condition,const char* message) {if (!condition) throw std::runtime_error(message);}
template<class F> void rejected(F action) {
    bool caught=false;try {action();}catch(const std::invalid_argument&) {caught=true;}
    check(caught,"invalid audio boundary was accepted");
}
}
int main() {try {
    rejected([] {mk2::DcsAudio invalid({});});
    std::vector<float> source(6251);
    for (size_t n=0;n<source.size();++n)
        source[n]=n<100?0.0f:n<500?2.0f:n<1000?-2.0f:float(int(n%65536)-32768)*(1.0f/32767.0f);
    std::vector<int16_t> baseline;
    std::vector<float> float_baseline;
    for (size_t chunk:{size_t(1),size_t(7),size_t(239),size_t(512)}) {
        std::vector<int16_t> output;
        std::vector<float> floats;
        mk2::DcsFloatAudio unquantized([&](const float* data,size_t count){floats.insert(floats.end(),data,data+count);});
        mk2::DcsAudio stream([&](const int16_t* data,size_t count) {
            check(count && count<=1024,"output storage is not bounded");
            output.insert(output.end(),data,data+count);
        });
        for (size_t at=0;at<source.size();) {
            const auto count=std::min(chunk,source.size()-at);
            stream.Feed(at,source.data()+at,count);unquantized.Feed(at,source.data()+at,count);at+=count;
        }
        check(stream.SourceSamples()==6251 && stream.OutputSamples()==9601 && output.size()==9601,
              "48k output must preserve absolute 31250Hz source phase");
        check(output[0]==0 && output[600]==32767 && output[1200]==-32768,
              "speaker conversion must preserve cold silence and clip exact signed limits");
        if (baseline.empty()) baseline=output;
        else check(output==baseline,"host source chunk boundaries changed PCM bytes");
        check(floats.size()==output.size() && floats[600]>1 && floats[1200]<-1,
              "floating presentation clipped before the final mix");
        if(float_baseline.empty())float_baseline=floats;
        else check(floats==float_baseline,"host source chunks changed floating presentation");
        for(size_t n=0;n<floats.size();++n){
            const auto value=floats[n];
            const auto pcm=value>=1?32767:value<=-1?-32768:int(value*32768);
            check(pcm==output[n],"floating presentation diverged from canonical resampling");
        }
        const auto written=stream.SourceSamples(),produced=stream.OutputSamples();const auto size=output.size();
        rejected([&]{stream.Feed(written,nullptr,1);});
        rejected([&]{stream.Feed(written,source.data(),513);});
        rejected([&]{stream.Feed(written+1,source.data(),1);});
        rejected([&]{stream.Feed(written-1,source.data(),1);});
        const float invalid[]={0,std::numeric_limits<float>::quiet_NaN()};
        rejected([&]{stream.Feed(written,invalid,2);});
        check(stream.SourceSamples()==written && stream.OutputSamples()==produced && output.size()==size,
              "rejected input changed resampler, output clock or consumer");
        stream.Feed(written,nullptr,0);
        check(stream.OutputSamples()==produced,"empty input manufactured samples");
    }
    std::vector<int16_t> presented;
    mk2::OriginalAudio playback([&](const int16_t* data,size_t count) {
        presented.insert(presented.end(),data,data+count);
    });
    std::array<float,512> block{};
    block.fill(.002f);
    playback.Feed(0,block.data(),block.size());
    check(std::abs(presented.back()-.002*32768*std::pow(10.0,mk5audio::master_db::mk2_original/20))<1,"Original Arcade playback is not at its master gain");
    for (float peak:{2.f,-2.f}) {
        block.fill(peak);
        playback.Feed(playback.SourceSamples(),block.data(),block.size());
        const auto sample=presented.back();
        check(std::abs(int(sample))<=mk5audio::HostGain::ceiling && std::abs(int(sample))>=mk5audio::HostGain::ceiling-1 && sample*peak>0,
              "Original Arcade playback did not limit a signed overload");
    }
    check(presented.size()==playback.OutputSamples() && playback.Limited() && !playback.Clipped(),
          "Original Arcade playback lost samples or misreported peak protection");
    std::cout<<"PASS bounded canonical DCS PCM and calibrated mono playback with peak protection\n";
}catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}}
