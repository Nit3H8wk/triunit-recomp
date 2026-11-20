#pragma once
#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <vector>
// Training mode (launcher CONTROLS, MK1_CONTROLS): an overlay drawn by the host over the game image, never into the
// game. It shows each player's input history and the boxes the game itself tests (each game's facts, read-only).
namespace mk5training {
// The actions the game receives (mk5controls bits after SOCD), published by the input poll of each game.
inline std::array<std::atomic<uint32_t>,2> held{};
enum Kind:uint8_t {Body,Strike};
struct Box {int x,y,w,h;Kind kind;};   // source pixels of the presented frame
constexpr unsigned kRows=12,kMaxFrames=99,kActions=10;   // Up..Run (mk5controls::Action); coin and start are not shown
struct History {
    struct Entry {uint32_t held=0;unsigned frames=0;};
    std::array<std::array<Entry,kRows>,2> rows{};std::array<unsigned,2> count{};
    // One call per presented frame: a new row when the held actions change, else the row's frame count grows.
    void Push(unsigned player,uint32_t actions){
        actions&=(1u<<kActions)-1;auto& r=rows[player];auto& n=count[player];
        if(n&&r[0].held==actions){r[0].frames=std::min(r[0].frames+1,kMaxFrames);return;}
        std::move_backward(r.begin(),r.end()-1,r.end());r[0]={actions,1};n=std::min(n+1,kRows);
    }
};
namespace detail {
// 3x5 glyphs, rows top to bottom, 3 bits each (MSB left): digits, then H P L B K R N.
constexpr uint16_t kGlyphs[]={0x7b6f,0x2c97,0x73e7,0x73cf,0x5bc9,0x79cf,0x79ef,0x7249,0x7bef,0x7bcf,
                              0x5bed,0x7be4,0x4927,0x6bae,0x5d35,0x6bad,0x5ffd};
enum {H=10,P,L,B,K,R,N};
// 5x5 arrows, 5 bits per row: neutral, then by the held direction bits (Up 1, Down 2, Left 4, Right 8).
constexpr uint32_t kArrows[16]={0x0001000,0x0475484,0x04255c4,0,0x0447d04,0x1ec5241,0x019531e,0,0x0417c44,0x0f19530,0x104946f};
// Button labels in display order: HP LP BL HK LK RN, as Action bits.
constexpr std::array<std::array<uint8_t,3>,6> kButtons{{{4,H,P},{7,L,P},{5,B,L},{6,H,K},{8,L,K},{9,R,N}}};
inline void put(std::vector<uint32_t>& o,unsigned w,unsigned h,int x,int y,uint32_t c){
    if(x>=0&&y>=0&&unsigned(x)<w&&unsigned(y)<h)o[size_t(y)*w+unsigned(x)]=c;
}
inline void fill(std::vector<uint32_t>& o,unsigned w,unsigned h,int x,int y,int bw,int bh,uint32_t c){
    for(int j=std::max(y,0);j<std::min(y+bh,int(h));++j)for(int i=std::max(x,0);i<std::min(x+bw,int(w));++i)o[size_t(j)*w+unsigned(i)]=c;
}
inline void bits(std::vector<uint32_t>& o,unsigned w,unsigned h,int x,int y,uint32_t mask,int cols,int rows,uint32_t c){
    for(int j=0;j<rows;++j)for(int i=0;i<cols;++i)if(mask>>((rows-1-j)*cols+(cols-1-i))&1)put(o,w,h,x+i,y+j,c);
}
}
constexpr uint32_t kBodyColor=0x3c8cff,kStrikeColor=0xff3c3c,kArrowColor=0xffe040,kTextColor=0xffffff;
// The overlay at the source size (BGRA, alpha 0 = game shows): boxes (light fill, solid outline), then per player a
// panel of the newest rows at the top: direction, held buttons and the frames the row was held. P1 left, P2 right.
inline void Draw(std::vector<uint32_t>& out,unsigned w,unsigned h,const History& history,const std::vector<Box>& boxes){
    using namespace detail;out.assign(size_t(w)*h,0);
    for(const auto& b:boxes){
        const uint32_t c=b.kind==Strike?kStrikeColor:kBodyColor;
        fill(out,w,h,b.x,b.y,b.w,b.h,0x50000000u|c);
        fill(out,w,h,b.x,b.y,b.w,1,0xff000000u|c);fill(out,w,h,b.x,b.y+b.h-1,b.w,1,0xff000000u|c);
        fill(out,w,h,b.x,b.y,1,b.h,0xff000000u|c);fill(out,w,h,b.x+b.w-1,b.y,1,b.h,0xff000000u|c);
    }
    constexpr int kWidth=71,kHeight=7,kTop=44;
    for(unsigned p=0;p<2;++p){
        const int x0=p?int(w)-6-kWidth:6;
        for(unsigned r=0;r<history.count[p];++r){
            const auto& e=history.rows[p][r];const int y=kTop+int(r)*kHeight;
            fill(out,w,h,x0,y,kWidth,kHeight,0xa0000000u);
            bits(out,w,h,x0+1,y+1,kArrows[e.held&15],5,5,0xff000000u|kArrowColor);
            int x=x0+8;
            for(const auto& b:kButtons)if(e.held>>b[0]&1){
                bits(out,w,h,x,y+1,kGlyphs[b[1]],3,5,0xff000000u|kTextColor);bits(out,w,h,x+4,y+1,kGlyphs[b[2]],3,5,0xff000000u|kTextColor);x+=9;
            }
            const int x9=x0+kWidth-8;
            if(e.frames>=10)bits(out,w,h,x9,y+1,kGlyphs[e.frames/10],3,5,0xffa0a0a0u);
            bits(out,w,h,x9+4,y+1,kGlyphs[e.frames%10],3,5,0xffa0a0a0u);
        }
    }
}
}
