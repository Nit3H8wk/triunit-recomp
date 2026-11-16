#pragma once
// User music for the Remastered presentation: custom_audio/<game>/<slot>.wav plus an optional slots.json.
// The Arcade Original never constructs this. Every failure is per slot and silent: a slot that is missing,
// linked, unreadable or in another format stays empty and the caller plays the arcade's own music instead.
#include "tiny_json.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace customaudio {
inline constexpr uint32_t rate=48000;
inline constexpr uintmax_t max_wav_bytes=uintmax_t(1)<<30; // about 93 minutes of 48 kHz stereo
inline constexpr uintmax_t max_slots_bytes=64*1024;

// One slot after slots.json: frame positions in the 48 kHz file. repeat_end==0 means the whole cue repeats
// without the de-click/splice that a user loop window gets.
struct Track {
    std::vector<int16_t> pcm; // interleaved stereo
    uint64_t begin=0,end=0,repeat_begin=0,repeat_end=0;
    bool loop=true;
    float gain=1.f; // linear, from gain_db
    uint64_t Frames()const{return pcm.size()/2;}
};

struct Report {unsigned loaded=0,missing=0,rejected=0;bool slots_json=false,slots_json_rejected=false;};

namespace detail {
using tinyjson::Linked;using tinyjson::Read;using tinyjson::Value;using tinyjson::Parser;
inline uint32_t Le(const std::string& b,size_t at,unsigned n){uint32_t v=0;for(unsigned i=0;i<n;++i)v|=uint32_t(uint8_t(b[at+i]))<<(8*i);return v;}
inline bool SafeName(const std::string& n){
    if(n.empty()||n.size()>64||n.front()=='.')return false;
    for(char c:n)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='-'||c=='_'||c=='.'))return false;
    return true;
}
inline std::optional<double> Number(const Value& o,const char* key){
    const auto it=o.fields.find(key);if(it==o.fields.end()||it->second.kind!=Value::Number)return std::nullopt;return it->second.number;
}
}

// RIFF/WAVE, PCM 16-bit little-endian (format 1 or extensible PCM), 48000 Hz, mono or stereo. Returns interleaved stereo.
inline std::optional<std::vector<int16_t>> ReadWav(const std::filesystem::path& path) {
    using detail::Le;
    const auto file=detail::Read(path,max_wav_bytes);if(!file)return std::nullopt;
    const auto& b=*file;
    if(b.size()<12||b.compare(0,4,"RIFF")!=0||b.compare(8,4,"WAVE")!=0)return std::nullopt;
    unsigned channels=0;bool format=false;
    for(size_t at=12;at+8<=b.size();){
        const auto size=uint64_t(Le(b,at+4,4));const size_t body=at+8;
        if(body+size>b.size())return std::nullopt;
        if(b.compare(at,4,"fmt ")==0){
            if(size<16)return std::nullopt;
            unsigned tag=Le(b,body,2);channels=Le(b,body+2,2);
            if(tag==0xfffe&&size>=40)tag=Le(b,body+24,2); // WAVE_FORMAT_EXTENSIBLE: first word of the subformat GUID
            format=tag==1&&(channels==1||channels==2)&&Le(b,body+4,4)==rate&&Le(b,body+12,2)==channels*2&&Le(b,body+14,2)==16;
            if(!format)return std::nullopt;
        }else if(b.compare(at,4,"data")==0){
            if(!format||size%(channels*2)||size==0)return std::nullopt;
            const size_t frames=size_t(size/(channels*2));std::vector<int16_t> pcm(frames*2);
            for(size_t n=0;n<frames;++n)for(unsigned c=0;c<2;++c)
                pcm[n*2+c]=int16_t(uint16_t(Le(b,body+(n*channels+(channels==2?c:0))*2,2)));
            return pcm;
        }
        at=body+size_t(size)+(size&1);
    }
    return std::nullopt;
}

// Loads every named slot of a game folder; tracks[i] is empty when slot i falls back to the original music.
// slots.json (optional): {"slots":{"<slot>":{"file":"name.wav","begin":s,"end":s,"loop":bool,
// "loop_begin":s,"loop_end":s,"gain_db":dB}}}, times in seconds. An invalid slots.json is ignored as a whole;
// an invalid entry leaves only its own slot empty.
inline std::vector<std::optional<Track>> LoadSlots(const std::filesystem::path& directory,const std::vector<std::string>& slots,
                                                    const std::vector<bool>& loops,Report* report=nullptr) {
    Report local;auto& r=report?*report:local;r=Report{};
    std::vector<std::optional<Track>> tracks(slots.size());
    detail::Value config;
    if(directory.empty())return tracks;
    if(const auto text=detail::Read(directory/"slots.json",max_slots_bytes)){
        detail::Parser parser(*text);detail::Value root;
        if(parser.Parse(root)&&parser.End()&&root.kind==detail::Value::Object){
            const auto it=root.fields.find("slots");
            if(it!=root.fields.end()&&it->second.kind==detail::Value::Object){config=it->second;r.slots_json=true;}
            else r.slots_json_rejected=true;
        }else r.slots_json_rejected=true;
    }
    for(size_t i=0;i<slots.size();++i){
        const auto entry=config.fields.find(slots[i]);
        const detail::Value* o=entry!=config.fields.end()?&entry->second:nullptr;
        if(o&&o->kind!=detail::Value::Object){++r.rejected;continue;}
        std::string file=slots[i]+".wav";
        if(o){const auto f=o->fields.find("file");if(f!=o->fields.end()){if(f->second.kind!=detail::Value::String||!detail::SafeName(f->second.text)){++r.rejected;continue;}file=f->second.text;}}
        std::error_code error;
        if(!std::filesystem::exists(directory/file,error)){++r.missing;continue;}
        auto pcm=ReadWav(directory/file);if(!pcm){++r.rejected;continue;}
        Track t;t.pcm=std::move(*pcm);t.loop=i<loops.size()?bool(loops[i]):true;t.end=t.Frames();
        bool valid=true;
        const auto frame=[&](const char* key,uint64_t fallback){
            if(!o)return fallback;
            const auto v=detail::Number(*o,key);
            if(!v){if(o->fields.count(key))valid=false;return fallback;}
            if(*v<0||*v*rate>double(t.Frames())){valid=false;return fallback;}
            return uint64_t(std::llround(*v*rate));
        };
        if(o){
            const auto l=o->fields.find("loop");
            if(l!=o->fields.end()){if(l->second.kind==detail::Value::Bool)t.loop=l->second.boolean;else valid=false;}
            if(const auto g=detail::Number(*o,"gain_db")){if(*g<-60||*g>24)valid=false;else t.gain=float(std::pow(10.0,*g/20));}
            else if(o->fields.count("gain_db"))valid=false;
        }
        t.begin=frame("begin",0);t.end=frame("end",t.Frames());
        const bool window=o&&(o->fields.count("loop_begin")||o->fields.count("loop_end"));
        if(window){t.repeat_begin=frame("loop_begin",t.begin);t.repeat_end=frame("loop_end",t.end);}
        if(!valid||t.begin>=t.end||(window&&(t.repeat_begin<t.begin||t.repeat_end>t.end||t.repeat_begin>=t.repeat_end))){++r.rejected;continue;}
        tracks[i]=std::move(t);++r.loaded;
    }
    return tracks;
}
}
