#pragma once
// Widescreen (Remastered presentation only) shared by the games whose VRAM line has 512 columns with the 400 visible ones
// from column 56 (MK1 rev 5.0, MK2 L3.1). The game runs unchanged: a shadow pass, run by the generated code on journaled
// RAM with no cycles, draws the frame into a 16:9 layer of its own (534 columns: the arcade's 400 and 67 on each side, more
// than a VRAM line holds). Game facts (addresses) stay in each game's table (mk5_widescreen.hpp, mk2/mk2_widescreen.hpp).
// Layer index: VRAM row (both 256-line pages) * kLayerWidth + layer column; layer column L shows screen x L-67+d.
#include <algorithm>
#include <array>
#include <cstdint>
#include <utility>
#include <vector>

namespace mk5wide {
constexpr int kMargin=56;      // VRAM columns beyond each side of the visible ones
constexpr int kVisible=400;
constexpr int kWidth=512;      // a VRAM line
constexpr int kWideMargin=67;  // layer columns beyond each side of the visible ones: 534/400 x 4:3 = 16:9
constexpr int kLayerWidth=kVisible+2*kWideMargin;
constexpr int kExtra=kWideMargin-kMargin;   // VRAM column c is layer column c+kExtra at offset 0
constexpr unsigned kAcross=16,kDown=9;      // the wide frame's physical aspect
constexpr size_t kLayerSize=size_t(512)*kLayerWidth;
constexpr int kReach=112;      // the shadow's clip reaches this far past the window: the far planes' art beyond it
constexpr int kEndSlack=4;
constexpr int kWorldMax=4096;  // camera limits wider than this (a finisher frees the camera) keep the arena's last ones
// A draw's x register in layer columns: the shadow renders its draws with this x, the layer's stride and its clip.
constexpr uint16_t LayerX(uint16_t x){return uint16_t((x+kExtra)&0x3ff);}
// Screen pixels the wide window moves right (+) or left (-) from centred so that it never shows beyond the arena's world:
// its art ends where the arcade screen stands at each camera limit (a camera past a limit counts as at it).
inline int WindowShift(int camera,int minimum,int maximum){
    if(minimum>maximum)return 0;
    camera=std::clamp(camera,minimum,maximum);
    const int left=camera-minimum,right=maximum-camera;
    if(left<kWideMargin&&right<kWideMargin)return 0;   // an arena narrower than the wide screen: centred
    return left<kWideMargin?kWideMargin-left:right<kWideMargin?right-kWideMargin:0;
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
inline Ratio MeasuredRatio(int32_t velocity,int32_t world_velocity){
    return world_velocity>0?Ratio{velocity,world_velocity}:Ratio{-int64_t(velocity),-int64_t(world_velocity)};
}
// The shadow pass's virtual camera: with the window offset d the wide screen shows the world as the arcade would at camera
// x + d, so each scroll (16.16) moves by its ratio times d (the world's by d; an unknown ratio counts as the world's).
inline int32_t VirtualScroll(int32_t scroll,int d,const Ratio* ratio){
    const int64_t move=ratio&&ratio->world?int64_t(d)*65536*ratio->plane/ratio->world:int64_t(d)*65536;
    return int32_t(int64_t(scroll)+move);
}
// Where a plane stands against the arcade's own screen in the wide window: its ratio times d, rounded.
inline int PlaneShift(int d,const Ratio* ratio){
    if(!ratio||!ratio->world)return d;
    const int64_t m=int64_t(d)*ratio->plane;return int((m>=0?m+ratio->world/2:m-ratio->world/2)/ratio->world);
}
// Whether the arcade screen itself shows this end of a plane's art (layer column end, a left or right end) at some camera
// position within the arena's limits, the plane moving by its ratio. Unknown ratio or limits: not shown. shift: the
// plane's own (PlaneShift).
inline bool EndShown(int end,bool left_end,int shift,int camera,const std::array<int,3>& limits,const Ratio* ratio){
    if(!limits[2]||!ratio||!ratio->world)return false;
    const auto& r=*ratio;
    const int64_t at=std::clamp(camera,limits[0],limits[1]),screen=end-kWideMargin+shift;
    return left_end?screen*r.world+r.plane*(at-limits[0])>kEndSlack*r.world
                   :screen*r.world-r.plane*(limits[1]-at)<(kVisible-kEndSlack)*r.world;
}
// How a far plane reaches the layer: moved by shift columns and, when width < kLayerWidth, its columns [0, width) stretched
// to the layer's (nearest neighbour); or left in place with its art mirrored beyond an end: the layer columns before
// mirror_left (its first column with art) or from mirror_right (its first column past the art) show the art reflected
// about that end.
struct Fit{int shift=0,width=kLayerWidth,mirror_left=0,mirror_right=kLayerWidth;
    bool fitted()const{return shift||width<kLayerWidth;}
    bool mirrored()const{return mirror_left>0||mirror_right<kLayerWidth;}};
// The plane's art in layer columns: what its draws put inside the layer (drawn) and the hull of their spans beyond it. A
// band (it draws in every column of the arcade's 400) whose art ends inside the layer, at an end the arcade never shows,
// keeps its place, its motion and the arcade's columns, and is mirrored beyond that end (moving it to the end would pin it
// there while the camera moves: it would slide against the other planes); only a band narrower than the layer is stretched
// to it. Any other plane is left as is. shift: the plane's own (PlaneShift).
template<class Shown>
Fit FitPlane(const std::array<bool,kLayerWidth>& drawn,int hull_left,int hull_right,int shift,Shown&& shown){
    int drawn_left=kLayerWidth,drawn_right=0;
    for(int c=0;c<kLayerWidth;++c)if(drawn[c]){drawn_left=std::min(drawn_left,c);drawn_right=c+1;}
    const int left=drawn_left>0?drawn_left:std::min(hull_left,0),right=drawn_right<kLayerWidth?drawn_right:std::max(hull_right,kLayerWidth);
    const int arcade=kWideMargin-shift;   // the arcade's first column in the layer
    const bool band=std::all_of(drawn.begin()+std::clamp(arcade,0,kLayerWidth),drawn.begin()+std::clamp(arcade+kVisible,0,kLayerWidth),
                                [](bool c){return c;});
    Fit fit;
    if(band&&left<=arcade&&right>=arcade+kVisible&&(left>0||right<kLayerWidth)&&
       !(left>0&&shown(left,true))&&!(right<kLayerWidth&&shown(right,false))){
        if(right-left>=kLayerWidth){if(left>0)fit.mirror_left=left;else fit.mirror_right=right;}
        else{fit.shift=-left;fit.width=right-left;}
    }
    return fit;
}
// A draw's mirror image about a mirrored plane's end (Fit; registers in layer columns, the X register 10-bit as -256..767):
// column c goes to 2*end-1-c (the X flip toggled), clipped to the columns beyond that end. False when the board cannot draw
// it so: a scaled draw (the scaler has no X flip).
template<class Registers> bool MirrorDraw(Registers& r,const Fit& fit,bool right_end){
    if((r[10]&&r[10]!=0x100)||(r[11]&&r[11]!=0x100))return false;
    const int end=right_end?fit.mirror_right:fit.mirror_left;
    int x=r[4]&0x3ff;if(x>=768)x-=1024;
    r[4]=uint16_t((r[4]&~0x3ffu)|(unsigned(2*end-1-x)&0x3ffu));r[1]^=0x10;
    r[16]=uint16_t(right_end?end:0);r[17]=uint16_t(right_end?kLayerWidth-1:end-1);
    return true;
}
// Each layer column a draw's column c covers: [c, c+1) * kLayerWidth / width.
template<class Put> void Stretch(size_t index,int width,Put&& put){
    if(width>=kLayerWidth){put(index);return;}
    const size_t row=index/kLayerWidth*kLayerWidth,c=index%kLayerWidth;
    for(size_t x=c*kLayerWidth/size_t(width);x<(c+1)*kLayerWidth/size_t(width)&&x<size_t(kLayerWidth);++x)put(row+x);
}

// The wide frame over the two 256-line VRAM pages: pens (the VRAM's format), the floor stains over it (Blood: the game's
// blood layer element, 0 = none) and the pixels a screen-fixed draw left (HUD: the window offset does not move them).
// Each page keeps the offset it was composed with: the window holds screen x -67+d .. 467+d. A plain page shows the VRAM
// ring: layer column L is VRAM column (L-11) mod 512.
template<class Blood>
struct Layer {
    std::vector<uint16_t> pens;std::vector<Blood> blood;std::vector<uint8_t> fixed;
    std::array<int,2> page_shift{};std::array<unsigned,2> page_fitted{};
    std::array<bool,2> cleared{{true,true}};   // the page clear ran on the page since its last build
    // A page not cleared since its last build keeps its margins (the game draws over what the page holds: a frozen screen
    // keeps its scenery beside the arcade's 400 columns, which come from VRAM). A shifted page keeps its whole composition;
    // kept by a build the shadow did not compose, it turns back into its plain VRAM; a frame with no build (the game drawing
    // straight onto its pages) does the same at the next display interrupt.
    bool kept=false,frame_started=false;
    int shift=0;unsigned page=0;
    std::array<int,2> held{};     // the last shifting frame's camera x and offset (the hold modes keep it)
    std::array<int,3> limits{};   // the arena's last usable camera limits (min, max, valid)
    std::array<Ratio,10> ratio{};std::array<int,2> ratio_limits{};int world=0;   // per scroll slot (far planes, world, front), for this arena
    // A screen without an arena (no far plane draws and the mode is not a fight's: menus, bios, story, records, logos) fills
    // each margin: its draws near an edge mirrored about it (edge_mirrored), else its own art when that covers the margin
    // (kCovered of its pixels away from the page clear's pen), else the page clear's pen (Tidy).
    // clear_pen: each line's pen at its last page clear.
    static constexpr unsigned kCovered=85;
    std::vector<uint16_t> clear_pen=std::vector<uint16_t>(512,0);bool arena=false,tidy=false,composed=false;
    bool Enabled()const{return !pens.empty();}
    // fill_edges: Tidy also fills the arcade's last kEdge columns where its art leaves them in the page's pen (MK1, whose
    // centre metric leaves those columns out; MK2 keeps every arcade column).
    bool fill_edges=false;
    void Enable(const std::vector<uint16_t>& vram,bool with_blood,bool edges=false){
        fill_edges=edges;
        pens.assign(kLayerSize,0);fixed.assign(kLayerSize,0);blood.assign(with_blood?kLayerSize:0,Blood{});
        for(unsigned p=0;p<2;++p)PlainPage(p,vram,{});
    }
    // The layer index of a VRAM index's screen position at offset 0, moved left by move columns (-1: outside the layer).
    static int64_t At(size_t vram_index,int move=0){
        const int c=int(vram_index&511)+kExtra-move;
        return c>=0&&c<kLayerWidth?int64_t(vram_index>>9)*kLayerWidth+c:-1;
    }
    void Write(size_t index,uint16_t pen,bool screen_fixed=false){pens[index]=pen;fixed[index]=screen_fixed;if(!blood.empty())blood[index]=Blood{};}
    // CPU writes and line copies (the page clear) are screen-fixed at their VRAM column; a whole line fills the layer's line
    // from the VRAM ring.
    void Mirror(const std::vector<uint16_t>& vram,size_t start,size_t count){
        if(!Enabled())return;
        if(!(start&511)&&count&&!(count&511)){for(size_t row=start>>9;row<(start+count)>>9;++row){clear_pen[row]=vram[row*512];PlainRow(row,vram);}return;}
        for(size_t i=start;i<start+count;++i)if(const auto at=At(i);at>=0){
            pens[size_t(at)]=vram[i];fixed[size_t(at)]=0;if(!blood.empty())blood[size_t(at)]=Blood{};
            if(!arena)MirrorEdge(size_t(at),vram[i]);}
    }
    // Margins a screen without an arena got as mirror images (per page and side; the page's clear resets them): Tidy keeps
    // them, gaps included (the screen's own background reflected).
    std::array<std::array<bool,2>,2> edge_mirrored{};
    // A CPU write on a screen without an arena (a decompressed image, written before its text): a pixel within kWideMargin
    // of an arcade edge also goes to its mirror image about that edge.
    void MirrorEdge(size_t at,uint16_t pen){
        const int L=int(at%kLayerWidth),right=kWideMargin+kVisible;size_t mirror;bool right_end;
        if(L>=kWideMargin&&L<2*kWideMargin){mirror=size_t(2*kWideMargin-1-L);right_end=false;}
        else if(L>=right-kWideMargin&&L<right){mirror=size_t(2*right-1-L);right_end=true;}
        else return;
        const size_t row=at/kLayerWidth;Write(row*kLayerWidth+mirror,pen,true);edge_mirrored[(row>>8)&1][right_end]=true;
    }
    // The layer's columns past the VRAM line on each side (screen x -67..-57 and 456..466) have no VRAM column of their own
    // (a draw there is clipped): a plain page shows them in the last page clear's pen, not the ring's far side.
    static bool PastVram(int L){return L<kExtra||L>=kWidth+kExtra;}
    void PlainRow(size_t row,const std::vector<uint16_t>& vram){
        auto* p=pens.data()+row*kLayerWidth;const auto* v=vram.data()+row*512;
        for(int L=0;L<kLayerWidth;++L)p[L]=PastVram(L)?clear_pen[row]:v[(L-kExtra+512)&511];
        std::fill_n(fixed.begin()+row*kLayerWidth,kLayerWidth,uint8_t(0));
        if(!blood.empty())std::fill_n(blood.begin()+row*kLayerWidth,kLayerWidth,Blood{});
    }
    void MarkCleared(size_t index){if(Enabled()){cleared[(index>>17)&1]=true;edge_mirrored[(index>>17)&1]={};}}
    int ShiftOfRow(unsigned vram_row)const{return page_shift[(vram_row>>8)&1];}
    unsigned FittedOfRow(unsigned vram_row)const{return page_fitted[(vram_row>>8)&1];}
    void PlainPage(unsigned p,const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood,bool centre_only=false){
        const int first=centre_only?kWideMargin:0,last=centre_only?kWideMargin+kVisible:kLayerWidth;
        const bool stains=!blood.empty(),arcade=arcade_blood.size()==vram.size();
        for(size_t row=size_t(p)*256;row<size_t(p)*256+256;++row){   // plain pointers: the stores cannot move the layers
            uint16_t* to=pens.data()+row*kLayerWidth;uint8_t* marks=fixed.data()+row*kLayerWidth;
            Blood* stain=stains?blood.data()+row*kLayerWidth:nullptr;
            const uint16_t* from=vram.data()+row*512;const Blood* arcade_stain=arcade?arcade_blood.data()+row*512:nullptr;
            for(int L=first;L<last;++L){const size_t v=size_t((L-kExtra+512)&511);const bool past=PastVram(L);
                to[L]=past?clear_pen[row]:from[v];marks[L]=0;if(stain)stain[L]=arcade_stain&&!past?arcade_stain[v]:Blood{};}
        }
        page_shift[p]=0;page_fitted[p]=0;
    }
    // A page composed with an offset and not cleared since keeps its last composition, moved by the change of offset.
    void SetShift(int d){
        int& now=page_shift[page];shift=d;kept=false;arena=false;tidy=false;composed=true;   // the shadow composes this build
        if(now==d||!Enabled()){now=d;return;}
        const int move=std::clamp(d-now,-kLayerWidth,kLayerWidth);now=d;   // the new column c shows the old column c+move
        const auto rows=[&](auto& layer){
            if(!layer.empty())for(size_t y=size_t(page)*256;y<size_t(page)*256+256;++y){
                auto* row=layer.data()+y*kLayerWidth;
                if(move>0)std::copy(row+move,row+kLayerWidth,row);else std::copy_backward(row,row+kLayerWidth+move,row+kLayerWidth);
            }};
        rows(pens);rows(blood);rows(fixed);
    }
    // The frame's build starts on its page: from VRAM at offset 0 (the margins too after a page clear), unless the page was
    // composed with an offset and not cleared since (then what the game left on it is that composition; valid only if the
    // shadow composes this build).
    void StartFrame(unsigned page_row,const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood){
        page=(page_row>>8)&1;
        kept=!cleared[page]&&page_shift[page];
        if(!kept)PlainPage(page,vram,arcade_blood,!cleared[page]);
        cleared[page]=false;shift=page_shift[page];frame_started=true;page_fitted[page]=0;composed=false;
    }
    // The composed page of a screen without an arena, once complete (the next display interrupt): each margin keeps its
    // art only where the art covers it.
    void Tidy(){
        if(!tidy)return;
        tidy=false;
        // An arcade edge the screen leaves in the page's pen (its art ends up to kEdge columns before it) would be a seam once
        // the margin beside it is filled: per line, those columns and as many margin ones take the art mirrored about its end.
        constexpr int kEdge=4;
        for(size_t row=size_t(page)*256;row<size_t(page)*256+256;++row){
            uint16_t* p=pens.data()+row*kLayerWidth;const uint16_t clear=clear_pen[row];
            if(fill_edges){
                int e=kWideMargin+kVisible;while(e>kWideMargin+kVisible-kEdge&&p[e-1]==clear)--e;
                if(e<kWideMargin+kVisible&&p[e-1]!=clear)for(int c=e;c<2*(kWideMargin+kVisible)-e;++c)if(p[c]==clear)Write(row*kLayerWidth+size_t(c),p[2*e-1-c],fixed[row*kLayerWidth+size_t(2*e-1-c)]);
                int s=kWideMargin;while(s<kWideMargin+kEdge&&p[s]==clear)++s;
                if(s>kWideMargin&&p[s]!=clear)for(int c=s-1;c>=2*kWideMargin-s;--c)if(p[c]==clear)Write(row*kLayerWidth+size_t(c),p[2*s-1-c],fixed[row*kLayerWidth+size_t(2*s-1-c)]);
            }
            // A mirrored margin's seams between its pieces (up to kEdge columns in the page's pen) take the column before.
            for(const int first:{0,kWideMargin+kVisible})if(edge_mirrored[page][first!=0])
                for(int c=first+1;c<first+kWideMargin;++c)if(p[c]==clear&&p[c-1]!=clear){
                    int end=c;while(end<first+kWideMargin&&end-c<=kEdge&&p[end]==clear)++end;
                    if(end<first+kWideMargin&&end-c<=kEdge)for(;c<end;++c)Write(row*kLayerWidth+size_t(c),p[c-1],fixed[row*kLayerWidth+size_t(c-1)]);
                }
            // What a mirrored margin still leaves in the page's pen (a draw with transparent pixels was not mirrored) takes the
            // arcade's own pixel mirrored about the edge.
            for(const int first:{0,kWideMargin+kVisible})if(edge_mirrored[page][first!=0]){
                const int edge=first?kWideMargin+kVisible:kWideMargin;
                for(int L=first;L<first+kWideMargin;++L)if(p[L]==clear){const size_t from=row*kLayerWidth+size_t(2*edge-1-L);Write(row*kLayerWidth+size_t(L),pens[from],fixed[from]);}
            }
        }
        for(const int first:{0,kWideMargin+kVisible}){
            if(edge_mirrored[page][first!=0])continue;
            size_t covered=0;
            for(size_t row=size_t(page)*256;row<size_t(page)*256+256;++row)
                for(int L=first;L<first+kWideMargin;++L)covered+=pens[row*kLayerWidth+size_t(L)]!=clear_pen[row];
            if(covered*100>=size_t(kCovered)*256*kWideMargin)continue;
            for(size_t row=size_t(page)*256;row<size_t(page)*256+256;++row)
                for(int L=first;L<first+kWideMargin;++L)Write(row*kLayerWidth+size_t(L),clear_pen[row]);
        }
    }
    void EndUnbuiltFrame(const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood){
        if(!Enabled())return;
        if(frame_started&&!composed&&!page_shift[page])tidy=true;   // a build the shadow did not compose: its margins are VRAM's
        Tidy();
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
    // A scroll's ratio slot for this arena (a new arena forgets the old ratios).
    Ratio& PlaneRatio(unsigned slot){
        if(ratio_limits[0]!=limits[0]||ratio_limits[1]!=limits[1]){ratio={};ratio_limits={limits[0],limits[1]};}
        return ratio[std::min(slot,unsigned(ratio.size()-1))];
    }
    // Save-state fields (W4): the layer, the pages' offsets and fits and the arena's window facts.
    template<class A> void LayerFields(A& a){a(pens,blood,fixed,page_shift,page_fitted,cleared,held,limits,ratio,ratio_limits,kept,frame_started,shift,page,world,
                                                clear_pen,arena,tidy,composed,edge_mirrored);}
    // The shadow composed this build: a draw that follows a camera makes it an arena's screen, unless the game's mode is a
    // menu's.
    void Composed(bool menu=false){tidy=!arena||menu;}
    void Reset(){const bool edges=fill_edges;*this=Layer{};fill_edges=edges;}
};
}
