#include "mk2_music.hpp"
#include "mk5_program.hpp"
#include "../runtime/mk2_music_manifest.hpp"
#include "../audio/custom_audio.hpp"

namespace mk2 {
int MusicTrack(unsigned command) {
    for(size_t n=0;n<music_cues.size();++n)if(command==music_cues[n].command)return int(n);
    return -1;
}
DcsEffects::DcsEffects(AdspBoot& dsp):dsp_(dsp) {
    if(dsp_.music_instruction_ || dsp_.music_sport_)throw std::runtime_error("DCS presentation already attached");
    dsp_.music_instruction_=[this](const auto& state){Instruction(state);};
    dsp_.music_sport_=[this](const auto& state,uint16_t start){Sport(state,start);};
}
DcsEffects::~DcsEffects(){dsp_.music_instruction_={};dsp_.music_sport_={};}
void DcsEffects::TransformUntil(uint16_t end) {
    for(unsigned count=0;transform_->pc!=end;++count){
        if(count>=20000)throw std::runtime_error("DCS presentation transform exceeded finite boundary");
        transform_->Step();
    }
}
void DcsEffects::Instruction(const AdspBoot& dsp) {
    if(dsp.pc==8){tag_=0;overlap_valid_=false;transform_.reset();output_.fill(0);output_tags_.fill(0);output_gains_.fill(0);channel_gain_=0;return;}
    if(dsp.pc==0x31 && dsp.rom_.size()==6*0x80000){
        const auto& rom=dsp.rom_;
        const unsigned command=dsp.ar;
        if(command<1403){
            const size_t entry=0x4048+command*3;
            const uint32_t address=(uint32_t(rom[entry])<<16)|(uint32_t(rom[entry+1])<<8)|rom[entry+2];
            const size_t offset=(address>>20)*0x80000+(address&0x7ffff);
            if(address>>16!=255 && offset+1<rom.size() && rom[offset]==1 && rom[offset+1]==0){
                const int track=MusicTrack(command);
                tag_=track<0?0:(++generation_<<16)|unsigned(track+1);
            }
        }
    }
    if(dsp.pc==0x21)spectrum_.fill(0);
    if(dsp.pc==0xa4){before_=std::array<uint16_t,258>{};std::copy_n(dsp.dm.begin(),before_.size(),before_.begin());channel_=dsp.external_pm[0x5fb]>>8;
        if(channel_==0){
            // Firmware normalized channel multiplier times its inverse FFT scale (0124-0129).
            const bool active=(dsp.external_pm[0x388]>>8)||(dsp.external_pm[0x389]>>8);
            channel_gain_=active?float((dsp.external_pm[0x3a0]>>8)*uint32_t(dsp.dm[0x10e]))/1073741824.f:0.f;
        }
    }
    if(dsp.pc==0xa5 && (channel_!=0 || !tag_))
        for(size_t n=0;n<spectrum_.size();++n)spectrum_[n]=uint16_t(spectrum_[n]+dsp.dm[n]-before_[n]);
    if(dsp.pc==0xaa){
        transform_=std::unique_ptr<AdspBoot>(new AdspBoot(dsp));
        auto& copy=*transform_;
        copy.music_instruction_={};copy.music_sport_={};copy.dac_observer_={};
        copy.presentation_only_=true;copy.observe_trace_=false;
        copy.trace.clear();copy.accesses.clear();
        std::copy(spectrum_.begin(),spectrum_.end(),copy.dm.begin());
        if(overlap_valid_)std::copy(overlap_.begin(),overlap_.end(),copy.external_pm.begin()+0x61d);
        TransformUntil(0x12a);
    }
    if(dsp.pc==0x13b && transform_){
        auto& copy=*transform_;copy.pc=0x13b;
        copy.external_pm[0x60c]=dsp.external_pm[0x60c];
        TransformUntil(0x166);
        const unsigned start=(dsp.external_pm[0x60c]>>8)-0x400;
        if(start!=0 && start!=240)throw std::runtime_error("DCS presentation half-buffer differs");
        for(unsigned n=0;n<240;++n){output_[start+n]=int16_t(copy.external_pm[0x400+start+n]>>8);output_tags_[start+n]=tag_;output_gains_[start+n]=channel_gain_;}
        std::copy_n(copy.external_pm.begin()+0x61d,overlap_.size(),overlap_.begin());overlap_valid_=true;
        transform_.reset();
    }
}
void DcsEffects::Sport(const AdspBoot& dsp,uint16_t start) {
    for(unsigned n=0;n<240;++n){
        const auto ring=(dsp.dac_bufin_+n)%ring_.size();
        ring_[ring]=dsp.rebooted_?output_.at(start-0x400+n):int16_t(dsp.dm.at(start-0x3800+n));
        tags_[ring]=dsp.rebooted_?output_tags_.at(start-0x400+n):0;
        gains_[ring]=dsp.rebooted_?output_gains_.at(start-0x400+n):0;
    }
}
void DcsEffects::Read(uint64_t first,size_t count,float* effects,uint64_t* tags,float* gains) const {
    const uint64_t queued=(dsp_.dac_bufin_+32768-dsp_.dac_bufout_)%32768;
    if(first<dsp_.dac_write_sample_ || count>512)throw std::runtime_error("DCS presentation DAC boundary differs");
    for(size_t n=0;n<count;++n){
        const auto offset=first+n-dsp_.dac_write_sample_;
        const auto at=(dsp_.dac_bufout_+offset)%32768;
        effects[n]=offset<queued?float(ring_[at])*(1.0f/32767.0f):0.0f;
        tags[n]=offset<queued?tags_[at]:0;
        if(gains)gains[n]=offset<queued?gains_[at]:0;
    }
}

// Music level relative to the DCS music channel envelope: the median of the per-cue stereo R128 matches measured
// for the former reference recordings (music_normalization.py). A slot's gain_db in slots.json scales it.
static constexpr float music_gain_default=4.903509576f;
struct RemasteredAudio::Impl {
    static constexpr uint64_t attack=240,splice=720; // 5 ms de-click, 15 ms overlap at 48 kHz.
    DcsEffects effects;
    std::vector<std::optional<customaudio::Track>> tracks;
    std::vector<float> original_pcm,effects_pcm,gain_pcm;
    DcsFloatAudio original,effect_audio,gain_audio;
    RemasteredMix mix;
    mk5audio::AudioConsumer consumer;
    std::array<uint64_t,32768> tags{};
    uint64_t last_tag=0,position=0,starts=0,output=0;
    float cue_gain=0,music_gain=0,release_gain=0;
    const customaudio::Track* release_track=nullptr;
    uint64_t release_position=0,release_remaining=0;
    Impl(AdspBoot& dsp,const std::filesystem::path& directory,mk5audio::AudioConsumer out)
        :effects(dsp),original([this](const auto*p,size_t n){original_pcm.assign(p,p+n);}),
         effect_audio([this](const auto*p,size_t n){effects_pcm.assign(p,p+n);}),
         gain_audio([this](const auto*p,size_t n){gain_pcm.assign(p,p+n);}),consumer(std::move(out)) {
        if(!consumer)throw std::invalid_argument("remastered DCS requires a consumer");
        tracks=customaudio::LoadSlots(directory,std::vector<std::string>(music_slots.begin(),music_slots.end()),
                                      std::vector<bool>(music_slots.size(),true));
    }
    // A cue whose slot has no usable user file keeps the arcade's own music (the full DCS signal).
    const customaudio::Track* Track(uint64_t tag) const {
        if(!tag)return nullptr;
        const auto& slot=tracks.at(music_cues.at(unsigned(tag&0xffff)-1).slot);
        return slot?&*slot:nullptr;
    }
    static std::array<int16_t,2> Frame(const customaudio::Track& cue,uint64_t offset) {
        const auto length=cue.end-cue.begin;
        const bool repeating=cue.loop && offset>=length;
        const auto repeat_begin=cue.repeat_end?cue.repeat_begin:cue.begin;
        const auto end=repeating && cue.repeat_end?cue.repeat_end:cue.end;
        const auto frame=repeating?repeat_begin+(offset-length)%(end-repeat_begin):cue.begin+offset;
        std::array<int16_t,2> music{};
        if(frame<end){
            const auto& track=cue.pcm;
            for(unsigned c=0;c<2;++c)music[c]=track.at(size_t(frame)*2+c);
            if(cue.repeat_end){
                const auto remaining=end-frame;
                for(unsigned c=0;c<2;++c){
                    if(offset<attack)music[c]=int16_t(int32_t(music[c])*int32_t(offset)/int32_t(attack));
                    if(remaining<=splice && repeat_begin>=remaining){
                        // Land on the sample immediately before the repeat so the seam is continuous.
                        const auto before=track.at(size_t(repeat_begin-remaining)*2+c);
                        const auto weight=int32_t(splice-remaining+1);
                        music[c]=int16_t((music[c]*(int32_t(splice)-weight)+before*weight)/int32_t(splice));
                    }
                }
            }
        }
        return music;
    }
};
RemasteredAudio::RemasteredAudio(AdspBoot& dsp,const std::filesystem::path& path,mk5audio::AudioConsumer out)
    :impl_(std::make_unique<Impl>(dsp,path,std::move(out))){}
RemasteredAudio::~RemasteredAudio()=default;
void RemasteredAudio::Feed(uint64_t first,const float* samples,size_t count){
    auto& s=*impl_;
    if(first!=s.original.SourceSamples() || count>512 || (count&&!samples))throw std::invalid_argument("remastered DCS source discontinuity");
    std::array<float,512> effects{},gains{};std::array<uint64_t,512> tags{};
    s.effects.Read(first,count,effects.data(),tags.data(),gains.data());
    for(size_t n=0;n<count;++n)s.tags[(first+n)%s.tags.size()]=tags[n];
    s.original_pcm.clear();s.effects_pcm.clear();s.original.Feed(first,samples,count);s.effect_audio.Feed(first,effects.data(),count);s.gain_pcm.clear();s.gain_audio.Feed(first,gains.data(),count);
    if(s.original_pcm.size()!=s.effects_pcm.size() || s.original_pcm.size()!=s.gain_pcm.size())throw std::runtime_error("remastered DCS output phases differ");
    std::array<int16_t,2048> out{};
    for(size_t n=0;n<s.original_pcm.size();++n){
        const auto raw=s.tags[(s.output*31250/48000)%s.tags.size()];
        const auto* track=s.Track(raw);
        const auto tag=track?raw:0;
        if(tag!=s.last_tag){
            if(s.last_tag){
                const auto* outgoing=s.Track(s.last_tag);
                if(outgoing && outgoing->repeat_end && s.music_gain>0){
                    s.release_track=outgoing;
                    s.release_position=s.position;
                    s.release_gain=s.music_gain;
                    s.release_remaining=Impl::attack;
                }
            }
            s.last_tag=tag;s.position=0;
            if(tag){++s.starts;s.cue_gain=music_gain_default*track->gain;}
        }
        std::array<int16_t,2> music{};
        if(tag)music=Impl::Frame(*track,s.position);
        s.music_gain=tag?s.cue_gain*std::max(0.f,s.gain_pcm[n]):0.f;
        float original=tag?s.effects_pcm[n]:s.original_pcm[n];
        std::array<double,2> release{};
        if(s.release_remaining){
            const auto tail=Impl::Frame(*s.release_track,s.release_position++);
            const float weight=float(s.release_remaining--)/Impl::attack;
            for(unsigned c=0;c<2;++c)release[c]=tail[c]*double(s.release_gain)*weight;
            // The full DCS signal can still carry the old music in its overlap buffer.
            if(!tag)original+=(s.effects_pcm[n]-original)*weight;
        }
        const auto stereo=s.mix.Render(original,music,s.music_gain,release);
        std::copy(stereo.begin(),stereo.end(),out.begin()+n*2);
        ++s.position;++s.output;
    }
    if(!s.original_pcm.empty())s.consumer(out.data(),s.original_pcm.size()*2);
}
uint64_t RemasteredAudio::SourceSamples()const{return impl_->original.SourceSamples();}
uint64_t RemasteredAudio::OutputSamples()const{return impl_->output;}
uint64_t RemasteredAudio::Starts()const{return impl_->starts;}
uint64_t RemasteredAudio::Clipped()const{return impl_->mix.Clipped();}
uint64_t RemasteredAudio::Limited()const{return impl_->mix.Limited();}
}
