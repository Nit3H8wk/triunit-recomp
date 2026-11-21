#pragma once
// Widescreen (Remastered presentation only) shared by the games whose VRAM line has 512 columns with the 400 visible ones
// from column 56 (MK1 rev 5.0, MK2 L3.1). The game runs unchanged: a shadow pass, run by the generated code on journaled
// RAM with no cycles, draws the frame over all 512 columns into a layer of its own. Game facts (addresses) stay in each
// game's table (mk5_widescreen.hpp, mk2/mk2_widescreen.hpp).
#include <algorithm>
#include <array>
#include <cstdint>
#include <utility>
#include <vector>

namespace mk5wide {
constexpr int kMargin=56;      // VRAM columns beyond each side of the visible ones
constexpr int kVisible=400;
constexpr int kWidth=512;      // a VRAM line
constexpr int kReach=112;      // the shadow's clip reaches this far past the window: the far planes' art beyond it
constexpr int kEndSlack=4;
constexpr int kWorldMax=4096;  // camera limits wider than this (a finisher frees the camera) keep the arena's last ones
// Screen pixels the wide window moves right (+) or left (-) from centred so that it never shows beyond the arena's world:
// its art ends where the arcade screen stands at each camera limit (a camera past a limit counts as at it).
inline int WindowShift(int camera,int minimum,int maximum){
    if(minimum>maximum)return 0;
    camera=std::clamp(camera,minimum,maximum);
    const int left=camera-minimum,right=maximum-camera;
    if(left<kMargin&&right<kMargin)return 0;   // an arena narrower than the wide screen: centred
    return left<kMargin?kMargin-left:right<kMargin?right-kMargin:0;
}
// A DMA draw's columns [first, last) from its x register (10-bit, read as -256..767), width, X step and flip.
inline std::pair<int,int> Span(uint16_t x_register,uint16_t width_register,uint16_t xstep_register,bool flip){
    int x=x_register&0x3ff;if(x>=768)x-=1024;
    const unsigned xstep=xstep_register?xstep_register:0x100;const int w=int(((width_register&0x3ffu)<<8)/xstep),lo=flip?x-w+1:x;
    return {lo,lo+w};
}
// A far plane's parallax: its velocity and the world's in a frame where the world moved (world 0: not known yet).
struct Ratio{int64_t plane=0,world=0;
    template<class A> friend void Fields(A& a,Ratio& r){a(r.plane,r.world);}};
// Whether the arcade screen itself shows this end of a plane's art (layer column end, a left or right end) at some camera
// position within the arena's limits, the plane moving by its ratio. Unknown ratio or limits: not shown.
inline bool EndShown(int end,bool left_end,int shift,int camera,const std::array<int,3>& limits,const Ratio* ratio){
    if(!limits[2]||!ratio||!ratio->world)return false;
    const auto& r=*ratio;
    const int64_t at=std::clamp(camera,limits[0],limits[1]),screen=end-kMargin+shift;
    return left_end?screen*r.world+r.plane*(at-limits[0])>kEndSlack*r.world
                   :screen*r.world-r.plane*(limits[1]-at)<(kVisible-kEndSlack)*r.world;
}
// How a far plane reaches the layer: moved by shift columns and, when width < 512, its columns [0, width) stretched to the
// 512 (nearest neighbour).
struct Fit{int shift=0,width=kWidth;bool fitted()const{return shift||width<kWidth;}};
// The plane's art in layer columns: what its draws put inside the layer (drawn) and the hull of their spans beyond it. A
// band (it draws in every column of the arcade's 400) whose art ends inside the layer, at an end the arcade never shows,
// is moved inside its art, and stretched only if the art is narrower than the layer. Any other plane is left as is.
template<class Shown>
Fit FitPlane(const std::array<bool,kWidth>& drawn,int hull_left,int hull_right,int shift,Shown&& shown){
    int drawn_left=kWidth,drawn_right=0;
    for(int c=0;c<kWidth;++c)if(drawn[c]){drawn_left=std::min(drawn_left,c);drawn_right=c+1;}
    const int left=drawn_left>0?drawn_left:std::min(hull_left,0),right=drawn_right<kWidth?drawn_right:std::max(hull_right,kWidth);
    const int arcade=kMargin-shift;   // the arcade's first column in the layer
    const bool band=std::all_of(drawn.begin()+std::max(arcade,0),drawn.begin()+std::min(arcade+kVisible,kWidth),[](bool c){return c;});
    Fit fit;
    if(band&&left<=arcade&&right>=arcade+kVisible&&(left>0||right<kWidth)&&
       !(left>0&&shown(left,true))&&!(right<kWidth&&shown(right,false))){
        if(right-left>=kWidth)fit.shift=left>0?-left:kWidth-right;
        else{fit.shift=-left;fit.width=right-left;}
    }
    return fit;
}
// Each layer column a draw's column c covers: [c, c+1) * 512 / width.
template<class Put> void Stretch(size_t index,int width,Put&& put){
    if(width>=kWidth){put(index);return;}
    const size_t row=index&~size_t(kWidth-1),c=index&size_t(kWidth-1);
    for(size_t x=c*kWidth/size_t(width);x<(c+1)*kWidth/size_t(width)&&x<size_t(kWidth);++x)put(row+x);
}

// The wide frame over the two 256-line VRAM pages: pens (the VRAM's format), the floor stains over it (Blood: the game's
// blood layer element, 0 = none) and the pixels a screen-fixed draw left (HUD: the window offset does not move them).
// Each page keeps the offset it was composed with: the window holds screen x -56+d .. 456+d.
template<class Blood>
struct Layer {
    std::vector<uint16_t> pens;std::vector<Blood> blood;std::vector<uint8_t> fixed;
    std::array<int,2> page_shift{};std::array<unsigned,2> page_fitted{};
    std::array<bool,2> cleared{{true,true}};   // the page clear ran on the page since its last build
    // A build that kept a page's composition without the shadow composing it turns that page back into its plain VRAM; a
    // frame with no build (the game drawing straight onto its pages) does the same at the next display interrupt.
    bool kept=false,frame_started=false;
    int shift=0;unsigned page=0;
    std::array<int,2> held{};     // the last shifting frame's camera x and offset (the hold modes keep it)
    std::array<int,3> limits{};   // the arena's last usable camera limits (min, max, valid)
    std::array<Ratio,8> ratio{};std::array<int,2> ratio_limits{};int world=0;   // per far camera, for this arena
    bool Enabled()const{return !pens.empty();}
    void Enable(const std::vector<uint16_t>& vram,bool with_blood){pens=vram;fixed.assign(vram.size(),0);if(with_blood)blood.assign(vram.size(),0);}
    void Write(size_t index,uint16_t pen,bool screen_fixed=false){pens[index]=pen;fixed[index]=screen_fixed;if(!blood.empty())blood[index]=0;}
    void Mirror(const std::vector<uint16_t>& vram,size_t start,size_t count){
        if(!Enabled())return;
        std::copy_n(vram.begin()+start,count,pens.begin()+start);
        if(!blood.empty())std::fill_n(blood.begin()+start,count,Blood{});
        std::fill_n(fixed.begin()+start,count,uint8_t(0));
    }
    void MarkCleared(size_t index){if(Enabled())cleared[(index>>17)&1]=true;}
    int ShiftOfRow(unsigned vram_row)const{return page_shift[(vram_row>>8)&1];}
    unsigned FittedOfRow(unsigned vram_row)const{return page_fitted[(vram_row>>8)&1];}
    void PlainPage(unsigned p,const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood){
        const size_t at=size_t(p)*256*kWidth,n=256*size_t(kWidth);
        std::copy_n(vram.begin()+at,n,pens.begin()+at);page_shift[p]=0;page_fitted[p]=0;
        if(!blood.empty()){if(arcade_blood.size()==blood.size())std::copy_n(arcade_blood.begin()+at,n,blood.begin()+at);else std::fill_n(blood.begin()+at,n,Blood{});}
        std::fill_n(fixed.begin()+at,n,uint8_t(0));
    }
    // A page composed with an offset and not cleared since keeps its last composition, moved by the change of offset.
    void SetShift(int d){
        int& now=page_shift[page];shift=d;kept=false;   // the shadow composes this build
        if(now==d||!Enabled()){now=d;return;}
        const int move=d-now;now=d;   // the new column c shows the old column c+move
        const auto rows=[&](auto& layer){
            if(!layer.empty())for(size_t y=size_t(page)*256;y<size_t(page)*256+256;++y){
                auto* row=layer.data()+y*kWidth;
                if(move>0)std::copy(row+move,row+kWidth,row);else std::copy_backward(row,row+kWidth+move,row+kWidth);
            }};
        rows(pens);rows(blood);rows(fixed);
    }
    // The frame's build starts on its page: from VRAM at offset 0, unless the page was composed with an offset and not
    // cleared since (then what the game left on it is that composition; valid only if the shadow composes this build).
    void StartFrame(unsigned page_row,const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood){
        page=(page_row>>8)&1;
        kept=!cleared[page]&&page_shift[page];
        if(!kept)PlainPage(page,vram,arcade_blood);
        cleared[page]=false;shift=page_shift[page];frame_started=true;page_fitted[page]=0;
    }
    void EndUnbuiltFrame(const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood){
        if(!Enabled())return;
        if(kept){PlainPage(page,vram,arcade_blood);kept=false;}
        if(!frame_started)for(unsigned p=0;p<2;++p)if(page_shift[p])PlainPage(p,vram,arcade_blood);
    }
    // This frame's offset from the mode (shifting, holding or neither), the camera and the arena's limits (a finisher
    // frees the camera: limits wider than world_max keep the arena's last ones).
    int Offset(bool shifting,bool holding,int camera,int low,int high,int world_max){
        if(low<=high&&high-low<=world_max)limits={low,high,1};
        else if(limits[2]){low=limits[0];high=limits[1];}
        const int d=holding?(camera==held[0]?held[1]:0):shifting?WindowShift(camera,low,high):0;
        if(!holding)held={camera,d};
        world=camera;return d;
    }
    // A far plane's ratio slot for this arena (a new arena forgets the old ratios).
    Ratio& PlaneRatio(unsigned slot){
        if(ratio_limits[0]!=limits[0]||ratio_limits[1]!=limits[1]){ratio={};ratio_limits={limits[0],limits[1]};}
        return ratio[slot&7];
    }
    // Save-state fields (W4): the layer, the pages' offsets and fits and the arena's window facts.
    template<class A> void LayerFields(A& a){a(pens,blood,fixed,page_shift,page_fitted,cleared,held,limits,ratio,ratio_limits,kept,frame_started,shift,page,world);}
    void Reset(){*this=Layer{};}
};
}
