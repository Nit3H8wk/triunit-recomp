#pragma once
#include <array>
#include <cstdint>
#include <cstdio>
#include <string>
#include "mk5_machine.hpp"
// Player controls shared by the games and the launcher: per-player keyboard keys and controller buttons for each action,
// and SOCD cleaning. The defaults are the original maps (Mk5KeyboardInputs, mk5pad::map, MK3 Run/Block shoulders).
namespace mk5controls {
// Controller directions are always the D-pad, the left stick or a HID hat/axes; the buttons are mapped.
enum Action:unsigned {Up,Down,Left,Right,HighPunch,Block,HighKick,LowPunch,LowKick,Run,Coin,Start,Count};
constexpr std::array<const wchar_t*,Count> names{{L"UP",L"DOWN",L"LEFT",L"RIGHT",L"HIGH PUNCH",L"BLOCK",L"HIGH KICK",
                                                 L"LOW PUNCH",L"LOW KICK",L"RUN (MK3)",L"COIN",L"START"}};
// Controller buttons as one mask: XInput wButtons (bits 0-15), LT bit 16, RT bit 17. HID buttons 1-10 land on the XInput
// bits of the common DirectInput layout (X A B Y LB RB LT RT Back Start); HID buttons 11-24 on bits 18-31.
constexpr uint32_t LT=1u<<16,RT=1u<<17;
constexpr uint32_t A=0x1000,B=0x2000,X=0x4000,Y=0x8000,LB=0x100,RB=0x200,BACK=0x20,START=0x10;
constexpr std::array<uint32_t,10> hidButtons{{X,A,B,Y,LB,RB,LT,RT,BACK,START}};
inline uint32_t hid_button(unsigned usage){return usage>=1&&usage<=10?hidButtons[usage-1]:usage<=24&&usage>10?1u<<(usage+7):0;}
struct Config {
    // Virtual keys: arrows A S D Z X C 5 1 for player 1, I K J L F G H V B N 6 2 for player 2.
    std::array<std::array<uint8_t,Count>,2> keys{{{0x26,0x28,0x25,0x27,'A','S','D','Z','X','C','5','1'},
                                                  {'I','K','J','L','F','G','H','V','B','N','6','2'}}};
    // Block on RB / RT and Run on LB / LT (MK3); without Run (MK1, MK2) Run also blocks, as LB / LT always did.
    std::array<std::array<uint32_t,Count>,2> pad{{{0,0,0,0,X,RB|RT,Y,A,B,LB|LT,BACK,START},{0,0,0,0,X,RB|RT,Y,A,B,LB|LT,BACK,START}}};
    int socd=0; // 0 neutral (an arcade lever cannot hold both), 1 last input wins
};
// Text form for the launcher profile and MK1_CONTROLS: 24 keys, 24 pad masks, SOCD, comma-separated hex.
inline std::string format(const Config& c){
    std::string out;char cell[16];
    for(const auto& p:c.keys)for(auto k:p){std::snprintf(cell,sizeof cell,"%x,",unsigned(k));out+=cell;}
    for(const auto& p:c.pad)for(auto m:p){std::snprintf(cell,sizeof cell,"%x,",unsigned(m));out+=cell;}
    return out+std::to_string(c.socd);
}
inline bool parse(const std::string& text,Config& c){
    Config out;size_t at=0;std::array<unsigned long,2*Count*2+1> v{};
    for(size_t i=0;i<v.size();++i){
        const size_t end=i+1<v.size()?text.find(',',at):text.size();
        if(end==std::string::npos||end==at||end-at>8||text.find_first_not_of("0123456789abcdef",at)<end)return false;
        v[i]=std::stoul(text.substr(at,end-at),nullptr,16);at=end+1;
    }
    for(size_t i=0;i<2*Count;++i){if(v[i]>255)return false;out.keys[i/Count][i%Count]=uint8_t(v[i]);}
    for(size_t i=0;i<2*Count;++i)out.pad[i/Count][i%Count]=i%Count<HighPunch?0:uint32_t(v[2*Count+i]);
    if(v.back()>1)return false;
    out.socd=int(v.back());c=out;return true;
}
// Held actions (bit per Action) of one player.
inline uint32_t from_keys(const Config& c,unsigned player,const std::array<bool,256>& keys){
    uint32_t held=0;for(unsigned i=0;i<Count;++i)if(c.keys[player][i]&&keys[c.keys[player][i]])held|=1u<<i;return held;
}
inline uint32_t from_pad(const Config& c,unsigned player,uint32_t buttons,unsigned directions){
    uint32_t held=directions&15;for(unsigned i=HighPunch;i<Count;++i)if(c.pad[player][i]&buttons)held|=1u<<i;return held;
}
// SOCD: opposite directions held together. Neutral releases both; last input keeps the one pressed most recently.
struct Socd {uint32_t raw=0,won=0;};
inline uint32_t clean(uint32_t held,int mode,Socd& s){
    const uint32_t raw=held;
    for(const auto pair:{std::array<unsigned,2>{Up,Down},std::array<unsigned,2>{Left,Right}}){
        const uint32_t a=1u<<pair[0],b=1u<<pair[1];if((held&(a|b))!=(a|b))continue;
        uint32_t win=0;
        if(mode==1)win=!(s.raw&a)&&(s.raw&b)?a:!(s.raw&b)&&(s.raw&a)?b:(s.raw&a)&&(s.raw&b)?s.won&(a|b):0;
        held=(held&~(a|b))|win;
    }
    s.raw=raw;s.won=held;return held;
}
// The original electrical bits (active low) of the shared MK1/MK2 word; Run has none there.
inline uint32_t shared(uint32_t p1,uint32_t p2,uint32_t in01,bool runBlocks){
    constexpr std::array<std::array<int,Count>,2> bits{{{0,1,2,3,4,5,6,28,29,-1,16,18},{8,9,10,11,12,13,14,25,26,-1,17,21}}};
    const std::array<uint32_t,2> held{{p1,p2}};
    for(unsigned p=0;p<2;++p){uint32_t a=held[p];if(runBlocks&&(a>>Run&1))a|=1u<<Block;
        for(unsigned i=0;i<Count;++i)if((a>>i&1)&&bits[p][i]>=0)in01&=~(1u<<bits[p][i]);}
    return in01;
}
}
