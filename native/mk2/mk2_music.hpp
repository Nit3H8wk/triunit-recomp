#pragma once
#include "mk2_adsp.hpp"
#include "mk2_audio.hpp"
#include "../audio/host_gain.hpp"
#include <filesystem>

namespace mk2 {
int MusicTrack(unsigned command);
class RemasteredMix {
    mk5audio::HostGain host_{mk5audio::master_db::mk2_remastered};
public:
    // Median stereo R128 difference of eight matched excerpts; see music_normalization.py.
    static constexpr float original_gain=5.27837207f; // +14.45 dB
    std::array<int16_t,2> Render(float original,std::array<int16_t,2> music,float music_gain=.25f,
                                 std::array<double,2> release={}) {
        if(!std::isfinite(original) || !std::isfinite(music_gain) || music_gain<0 ||
           !std::isfinite(release[0]) || !std::isfinite(release[1]))throw std::invalid_argument("MK2 mix is not finite");
        const double base=double(original)*32768.0*original_gain;
        return host_.Render<2>({base+music[0]*double(music_gain)+release[0],base+music[1]*double(music_gain)+release[1]});
    }
    uint64_t Limited()const{return host_.Limited();}
    uint64_t Clipped()const{return host_.Clipped();}
};

class OriginalAudio {
    mk5audio::HostGain host_{mk5audio::master_db::mk2_original};
    DcsFloatAudio audio_;
    template<class A> friend void Fields(A& a,OriginalAudio& o){a(o.host_,o.audio_);}
public:
    explicit OriginalAudio(mk5audio::AudioConsumer consumer)
        :audio_([this,consumer](const float* samples,size_t count) {
            std::array<int16_t,1024> mono{};
            for(size_t n=0;n<count;++n)mono[n]=host_.Render<1>({double(samples[n])*32768.0})[0];
            consumer(mono.data(),count);
        }) {
        if(!consumer)throw std::invalid_argument("original DCS requires a consumer");
    }
    OriginalAudio(const OriginalAudio&)=delete;
    OriginalAudio& operator=(const OriginalAudio&)=delete;
    void Feed(uint64_t first,const float* samples,size_t count){audio_.Feed(first,samples,count);}
    uint64_t SourceSamples()const{return audio_.SourceSamples();}
    uint64_t OutputSamples()const{return audio_.OutputSamples();}
    uint64_t Clipped()const{return host_.Clipped();}
    uint64_t Limited()const{return host_.Limited();}
};

// Optional presentation sidecar. Canonical registers, memories and PCM are read-only.
class DcsEffects {
    AdspBoot& dsp_;
    std::array<uint16_t,258> before_{},spectrum_{};
    std::array<uint32_t,16> overlap_{};
    std::unique_ptr<AdspBoot> transform_;
    std::array<int16_t,480> output_{};
    std::array<uint64_t,480> output_tags_{};
    std::array<float,480> output_gains_{};
    std::array<int16_t,32768> ring_{};
    std::array<uint64_t,32768> tags_{};
    std::array<float,32768> gains_{};
    float channel_gain_=0;
    uint64_t generation_=0,tag_=0;
    bool overlap_valid_=false;
    unsigned channel_=0;
    void Instruction(const AdspBoot&);
    void Sport(const AdspBoot&,uint16_t);
    void TransformUntil(uint16_t);
public:
    explicit DcsEffects(AdspBoot&);
    ~DcsEffects();
    DcsEffects(const DcsEffects&)=delete;
    DcsEffects& operator=(const DcsEffects&)=delete;
    void Read(uint64_t first,size_t count,float* effects,uint64_t* tags,float* gains=nullptr) const;
};

class RemasteredAudio {
    struct Impl;
    std::unique_ptr<Impl> impl_;
public:
    RemasteredAudio(AdspBoot&,const std::filesystem::path&,mk5audio::AudioConsumer);
    ~RemasteredAudio();
    void Feed(uint64_t,const float*,size_t);
    uint64_t SourceSamples()const;
    uint64_t OutputSamples()const;
    uint64_t Starts()const;
    uint64_t Clipped()const;
    uint64_t Limited()const;
};
}
