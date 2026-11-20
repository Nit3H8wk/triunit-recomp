#pragma once
#include "mk5_training.hpp"
#include <algorithm>
#include <array>
#include <climits>
#include <cstdint>
#include <vector>
// Training-mode boxes, read only from the game's RAM and registers; nothing is written back. Address-only facts per
// game (bit addresses), recovered locally from each ROM: the strike check's compare PC, where A4/A5 hold the attack box
// and A2/A3 the victim box in world space (y<<16|x, bottom-right exclusive); the fighter object longs; the camera
// (integer words of the world's top-left). Object fields shared by the engine: x +90h, y +B0h (top-left corner,
// integer words), width +120h, height +130h, flags +160h (bit 0: fixed to the screen, bit 1: multipart).
namespace mk5hitbox {
enum class Body:uint8_t {Chain,Parts};   // how the strike check builds the victim box (see Bodies)
// A fighter is shown while its game shows a fight: mode is the game mode word and arena the modes (bit per value) of a
// fight, as the blood layers use them; without a mode word (0), while the object is linked (+00h) in the world list.
// unhittable: the object flags that make the strike check leave before it builds a box.
struct Facts {uint32_t strike_pc;std::array<uint32_t,2> objects;uint32_t camera_x,camera_y,mode;uint16_t arena;
              uint32_t world_list;uint16_t unhittable;Body body;};
constexpr Facts kMk1{0xffcef0c0,{{0x01051230,0x01051510}},0x0104f880,0x0104f660,0x01051190,0x6c,0,0,Body::Chain};
constexpr Facts kMk2{0xff835b70,{{0x01060220,0x01060df0}},0x0105d350,0x0105d130,0x010601d0,0xe4,0,0,Body::Parts};
constexpr Facts kMk3{0xffa5cc30,{{0x010609b0,0x01061560}},0x0105dae0,0x0105d8a0,0,0,0x0105dc10,0x100,Body::Parts};
inline bool enabled=false;                     // set by the game loop when training mode is on
inline std::vector<mk5training::Box> strikes;  // attack boxes the game tested since the last presented frame
struct Ram {
    const std::vector<uint16_t>& w;
    static bool in(uint32_t bit){return bit>=0x01000000&&bit<0x01400000&&!(bit&15);}
    uint16_t word(uint32_t bit)const{const size_t i=(bit-0x01000000)/16;return in(bit)&&i<w.size()?w[i]:0;}
    int s16(uint32_t bit)const{return int16_t(word(bit));}
    uint32_t lng(uint32_t bit)const{return word(bit)|uint32_t(word(bit+16))<<16;}
};
struct Rect {int l=INT_MAX,t=INT_MAX,r=INT_MIN,b=INT_MIN;
    void add(int x,int y,int w,int h){if(w<=0||h<=0)return;l=std::min(l,x);t=std::min(t,y);r=std::max(r,x+w);b=std::max(b,y+h);}
    bool empty()const{return l>=r||t>=b;}};
inline mk5training::Box screen(const Facts& f,const Ram& m,Rect r,mk5training::Kind kind,bool fixed=false){
    const int cx=fixed?0:m.s16(f.camera_x),cy=fixed?0:m.s16(f.camera_y);
    return {r.l-cx,r.t-cy,r.r-r.l,r.b-r.t,kind};
}
// At strike_pc (read-only): the attack box the game is testing, in screen pixels.
inline void Strike(const Facts& f,const uint32_t* a,const std::vector<uint16_t>& ram){
    if(!enabled)return;
    const Ram m{ram};Rect r;r.l=int16_t(a[4]);r.t=int16_t(a[4]>>16);r.r=int16_t(a[5]);r.b=int16_t(a[5]>>16);
    if(!r.empty()&&strikes.size()<16)strikes.push_back(screen(f,m,r,mk5training::Strike));
}
// The victim box of each fighter by the strike check's own rule, without the per-attack narrowing (entry flag bit 0).
// MK1 (Chain): the union of the object's components (+20h links), less the empty image FFC864D0; character 7 is 1Eh
// narrower on each side and character 1 in its FFD14A30 frame 0Ah taller. MK2 (Parts): the union of the part list at
// +1A0h (70h-bit entries: width +20h, height +30h, x and y offsets +50h/+60h, a 0 source ends it); MK3 the same.
inline std::vector<mk5training::Box> Bodies(const Facts& f,const std::vector<uint16_t>& ram){
    const Ram m{ram};std::vector<mk5training::Box> out;
    if(f.mode){const unsigned mode=m.word(f.mode);if(mode>15||!(f.arena>>mode&1))return out;}   // no fight: stale longs
    const auto linked=[&](uint32_t object){
        if(!f.world_list)return true;
        for(uint32_t o=m.lng(f.world_list),n=0;Ram::in(o)&&n<1024;o=m.lng(o),++n)if(o==object)return true;
        return false;
    };
    for(const uint32_t slot:f.objects){
        const uint32_t object=m.lng(slot);if(!Ram::in(object)||(m.word(object+0x160)&f.unhittable)||!linked(object))continue;
        Rect r;const int x=m.s16(object+0x90),y=m.s16(object+0xb0);
        if(f.body==Body::Chain){
            uint32_t o=object;
            for(unsigned n=0;n<16&&Ram::in(o);++n,o=m.lng(o+0x20))
                if(m.lng(o+0x180)!=0xffc864d0)r.add(m.s16(o+0x90),m.s16(o+0xb0),m.word(o+0x120),m.word(o+0x130));
            const unsigned character=m.word(object+0x260);
            if(character==7){r.l+=0x1e;r.r-=0x1e;}
            if(character==1&&m.lng(object+0x220)==0xffd14a30)r.t-=0xa;
        }else if(m.word(object+0x160)&2){
            uint32_t e=m.lng(object+0x1a0);
            for(unsigned n=0;n<32&&Ram::in(e)&&m.lng(e);++n,e+=0x70)
                r.add(x-m.s16(e+0x50),y-m.s16(e+0x60),m.word(e+0x20),m.word(e+0x30));
        }else r.add(x,y,m.word(object+0x120),m.word(object+0x130));
        if(!r.empty())out.push_back(screen(f,m,r,mk5training::Body,m.word(object+0x160)&1));
    }
    return out;
}
inline std::vector<mk5training::Box> bodies;   // Capture: the bodies as the game drew its latest frame
inline void Capture(const Facts& f,const std::vector<uint16_t>& ram){if(enabled)bodies=Bodies(f,ram);}
// The boxes of one presented frame: both bodies, then the attacks tested since the last one.
inline std::vector<mk5training::Box> Take(){
    if(!enabled)return {};
    auto out=bodies;out.insert(out.end(),strikes.begin(),strikes.end());strikes.clear();return out;
}
}
