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
// its art ends where the arcade screen stands at each camera limit (a camera past a limit counts as at it). The offset
// grows over the last kRamp columns of the camera's way (at most half the arena), so the wide view keeps moving, slower,
// until the camera stops at the limit instead of standing still for its last kWideMargin columns (the far planes' camera
// then lags behind it, Layer::Push, and they still move forward, slower than the world).
constexpr int kRamp=3*kWideMargin;
inline int WindowShift(int camera,int minimum,int maximum){
    if(minimum>maximum)return 0;
    camera=std::clamp(camera,minimum,maximum);
    const int left=camera-minimum,right=maximum-camera,zone=std::clamp((maximum-minimum)/2,kWideMargin,kRamp);
    if(left<zone&&right<zone)return 0;   // an arena narrower than the wide screen: centred
    const auto ramp=[&](int from){return (kWideMargin*(zone-from)+zone-1)/zone;};
    return left<zone?ramp(left):right<zone?-ramp(right):0;
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
// x + d, so each scroll (16.16) moves by its ratio times d (the world's by d; an unknown ratio counts as the world's). While
// the window holds the camera still at an arena's end, every plane stands still too (FitPlane keeps a plane whose art runs
// out there at the window's edge).
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
struct Fit{int shift=0,width=kLayerWidth,mirror_left=0,mirror_right=kLayerWidth,gap=-(1<<20);
    bool fitted()const{return shift||width<kLayerWidth;}
    bool mirrored()const{return mirror_left>0||mirror_right<kLayerWidth;}};
// The plane's art in layer columns: what its draws put inside the layer (drawn) and the hull of their spans beyond it. A
// band (it draws in every column of the arcade's 400) whose art ends inside the layer, at an end the arcade never shows,
// keeps its place, its motion and the arcade's columns, and is mirrored beyond that end (moving it to the end would pin it
// there while the camera moves: it would slide against the other planes); only a band narrower than the layer is stretched
// to it. Any other plane is left as is. shift: the plane's own (PlaneShift). push: the plane's move this frame (Layer::Push;
// every far plane but a stretched one moves by it); side: the arena end the camera is nearer to (1 left, -1 right, 0 none:
// Layer::Side). gap: a band's art end on that side, an end the arcade never shows, in layer columns from the layer's edge
// inward (negative: beyond it) before the push, when the shadow built it (its draws reach less than kReach past the
// layer); kNoGap otherwise (Layer::NeedPush).
constexpr int kNoGap=-(1<<20);
template<class Shown>
Fit FitPlane(const std::array<bool,kLayerWidth>& drawn,int hull_left,int hull_right,int shift,Shown&& shown,int push=0,int side=0){
    int drawn_left=kLayerWidth,drawn_right=0;
    for(int c=0;c<kLayerWidth;++c)if(drawn[c]){drawn_left=std::min(drawn_left,c);drawn_right=c+1;}
    const int left=drawn_left>0?drawn_left:std::min(hull_left,0),right=drawn_right<kLayerWidth?drawn_right:std::max(hull_right,kLayerWidth);
    const int arcade=kWideMargin-shift;   // the arcade's first column in the layer
    // A camera kEndSlack columns past its limit (the game lets it overshoot) may leave the band's last columns undrawn.
    const bool band=std::all_of(drawn.begin()+std::clamp(arcade+kEndSlack,0,kLayerWidth),drawn.begin()+std::clamp(arcade+kVisible-kEndSlack,0,kLayerWidth),
                                [](bool c){return c;});
    Fit fit;
    if(band&&side>0&&hull_left>-kReach){const int end=drawn_left>0?drawn_left:hull_left;if(!shown(end,true))fit.gap=end;}
    if(band&&side<0&&hull_right<kLayerWidth+kReach){const int end=drawn_right<kLayerWidth?drawn_right:hull_right;if(!shown(end,false))fit.gap=kLayerWidth-end;}
    if(band&&left<=arcade+kEndSlack&&right>=arcade+kVisible-kEndSlack&&(left>0||right<kLayerWidth)&&
       !(left>0&&shown(left,true))&&!(right<kLayerWidth&&shown(right,false))){
        if(right-left>=kLayerWidth){
            if(left>0){if(left+push>0)fit.mirror_left=left+push;}
            else if(right+push<kLayerWidth)fit.mirror_right=right+push;
            fit.shift=push;
        }
        else{fit.shift=-left;fit.width=right-left;}
        return fit;
    }
    fit.shift=push;return fit;
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
    // The far planes' camera lag at an arena's end (FitPlane): with the window moved toward an end where the bands (art that
    // the arcade never shows ending) would show their end inside the window, every far plane moves back by its ratio times
    // the lag (camera columns), so they stand as the arcade composes them at a camera that many columns from the virtual
    // one (an arcade view within the arena) and their art reaches the window's edge: no reflected scenery beyond the
    // arena's end. need: the lag the last build's bands asked for (gap / ratio, measured where parallax puts them); the lag
    // is need times |d| / kWideMargin, so it grows from nothing as the window leaves the centre.
    int push=0,push_need=0,push_seen=0;static constexpr int kPushStep=2;
    int Push(const Ratio* r)const{
        if(!push||!r||!r->world||r->plane<=0)return 0;
        const int64_t m=int64_t(push)*r->plane;return int((m>=0?m+r->world/2:m-r->world/2)/r->world);
    }
    // A band's gap grows by (1 - ratio) per column the virtual camera still moves toward the limit (dist + |d| - kWideMargin
    // of them, dist the camera's columns to it): the lag it needs there, gap / ratio + (1 / ratio - 1) * that, so the lag
    // grows evenly with |d| and the far planes keep moving forward.
    // Measured while the camera is centred too (the side nearer to it), so the lag is known before the window moves.
    int Side()const{
        if(shift)return shift>0?1:-1;
        if(!limits[2])return 0;
        return world-limits[0]<=limits[1]-world?1:-1;
    }
    void NeedPush(const Fit& fit,const Ratio* r){
        const int side=Side();
        if(fit.gap==kNoGap||!r||!r->world||r->plane<=0||!side)return;
        const int dist=std::max(0,side>0?world-limits[0]:limits[1]-world),ahead=std::max(0,dist+std::abs(shift)-kWideMargin);
        const int64_t w=std::abs(r->world),q=std::abs(r->plane),gap=int64_t(fit.gap)*w+int64_t(ahead)*(w-std::min(q,w));
        if(gap>0)push_need=std::max(push_need,int((gap+q-1)/q));
    }
    // A screen without an arena (no far plane draws and the mode is not a fight's: menus, bios, story, records, logos;
    // Backdrop) keeps its 400 columns as the arcade draws them, and its margins show only its background extended: no draw
    // writes them (Arcade), and at the frame's end (Tidy) the background draws that reach an arcade edge continue past it
    // (EdgeDraws) and a decompressed image's background is reflected (ImageEdges). clear_pen: each line's pen at its last
    // page clear. menu: this build's mode is a menu's (its objects may follow a camera).
    static constexpr unsigned kCovered=85;   // an opaque draw writes this share of its rectangle (percent)
    // What a draw writes, unclipped: whether it is opaque (kCovered) and its art's columns [first, last), counted from its X
    // register in drawing order (a flipped draw goes left).
    struct Cover{bool opaque=false;int first=0,last=0;};
    std::vector<uint16_t> clear_pen=std::vector<uint16_t>(512,0);bool arena=false,menu=false,composed=false;
    bool Enabled()const{return !pens.empty();}
    bool Backdrop()const{return Enabled()&&!shift&&(!arena||menu);}
    static bool Arcade(int L){return L>=kWideMargin&&L<kWideMargin+kVisible;}
    // A Backdrop draw (registers in layer columns): its palette and, when it reaches an arcade edge (its art ends within kNear
    // columns of it: MK2 screens often leave the arcade's last 7 columns black), the draw itself, for Tidy.
    static constexpr int kEdge=4,kNear=16;static constexpr size_t kPlacements=4096;
    std::vector<std::array<uint16_t,18>> edge_draws;std::array<uint16_t,128> palette_uses{};
    // Every noted draw's source, line and first column: a tile's step along its row (the game overlaps its tiles).
    struct Placement{uint32_t source;uint16_t line;int16_t first,width;
        template<class A> friend void Fields(A& a,Placement& p){a(p.source,p.line,p.first,p.width);}};
    std::vector<Placement> placements;
    static uint32_t Source(const std::array<uint16_t,18>& r){return r[2]|uint32_t(r[3])<<16;}
    void Note(const std::array<uint16_t,18>& r){
        uint16_t& uses=palette_uses[(r[8]>>8)&0x7f];uses=uint16_t(std::min(uses+1,0xffff));
        const auto [lo,hi]=Span(r[4],r[6],r[10],(r[1]&0x10)!=0);
        if(placements.size()<kPlacements)placements.push_back({Source(r),uint16_t(r[5]&0x1ff),int16_t(lo),int16_t(hi-lo)});
        if((lo<=kWideMargin+kNear&&hi>kWideMargin)||(hi>=kWideMargin+kVisible-kNear&&lo<kWideMargin+kVisible))edge_draws.push_back(r);
    }
    void Enable(const std::vector<uint16_t>& vram,bool with_blood,int fill=0){
        edge_fill=fill;pens.assign(kLayerSize,0);fixed.assign(kLayerSize,0);blood.assign(with_blood?kLayerSize:0,Blood{});
        for(unsigned p=0;p<2;++p)PlainPage(p,vram,{});
    }
    // The layer index of a VRAM index's screen position at offset 0, moved left by move columns (-1: outside the layer).
    static int64_t At(size_t vram_index,int move=0){
        const int c=int(vram_index&511)+kExtra-move;
        return c>=0&&c<kLayerWidth?int64_t(vram_index>>9)*kLayerWidth+c:-1;
    }
    void Write(size_t index,uint16_t pen,bool screen_fixed=false){
        pens[index]=booked[(pen>>8)&0x7f]?uint16_t(pen|kBooked):pen;fixed[index]=screen_fixed;if(!blood.empty())blood[index]=Blood{};
    }
    // A palette slot the shadow pass booked this build (the game has not built the object, so its colours are not loaded):
    // a draw in it writes its pen | kBooked, whose colour is the palette's own in the ROM (the slot's pointer: a count word,
    // then the colours, as the game loads them), kept per page (the page it was drawn on). read: a ROM word at a bit address.
    static constexpr uint16_t kBooked=0x8000;
    std::array<bool,128> booked{};std::array<std::vector<uint16_t>,2> rom_palette;
    template<class Read> void Book(unsigned slot,uint32_t pointer,Read read){
        auto& to=rom_palette[page];if(to.empty())to.assign(0x8000,0);
        const unsigned count=std::min(unsigned(read(pointer)),256u);
        for(unsigned k=0;k<count;++k)to[slot*256+k]=uint16_t(read(pointer+16+16*k));
        booked[slot&0x7f]=true;
    }
    uint16_t Colour(size_t index,uint16_t pen,const uint16_t* palette)const{
        const auto& rom=rom_palette[(index/kLayerWidth>>8)&1];
        return pen&kBooked&&!rom.empty()?rom[pen&0x7fff]:palette[pen&0x7fff];
    }
    // CPU writes and line copies (the page clear) are screen-fixed at their VRAM column; a whole line fills the layer's line
    // from the VRAM ring.
    void Mirror(const std::vector<uint16_t>& vram,size_t start,size_t count){
        if(!Enabled())return;
        if(!(start&511)&&count&&!(count&511)){for(size_t row=start>>9;row<(start+count)>>9;++row){clear_pen[row]=vram[row*512];PlainRow(row,vram);}return;}
        for(size_t i=start;i<start+count;++i)if(const auto at=At(i);at>=0){
            pens[size_t(at)]=vram[i];fixed[size_t(at)]=0;if(!blood.empty())blood[size_t(at)]=Blood{};
            // A CPU write at a VRAM line's first column clears the line (the decompressor writes only inside the arcade's
            // columns): a screen set up by the CPU, which has no arena, with that line's pen. On a Backdrop screen a clear
            // reaches the layer's columns past the VRAM too; a write at an arcade edge band is a decompressed image's edge
            // (Tidy reflects its background).
            const int L=int(at%kLayerWidth);const size_t row=size_t(at)/kLayerWidth;
            if(L==kExtra){clear_pen[row]=vram[i];arena=false;}
            if(!Backdrop())continue;
            if(L==kExtra)std::fill_n(pens.begin()+row*kLayerWidth,kExtra,vram[i]);
            else if(L==kWidth+kExtra-1)std::fill_n(pens.begin()+row*kLayerWidth+kWidth+kExtra,kExtra,vram[i]);
            else if(Arcade(L)&&(L<kWideMargin+kBand||L>=kWideMargin+kVisible-kBand)){
                image_lines[row&511]|=L<kWideMargin+kBand?1:2;image_dirty[(row>>8)&1]=true;}
        }
    }
    static constexpr int kBand=8;   // the arcade columns at each edge whose pens are a decompressed image's background
    // The layer's columns past the VRAM line on each side (screen x -67..-57 and 456..466) have no VRAM column of their own
    // (a draw there is clipped): a plain page shows them in the last page clear's pen, not the ring's far side.
    static bool PastVram(int L){return L<kExtra||L>=kWidth+kExtra;}
    void PlainRow(size_t row,const std::vector<uint16_t>& vram){
        image_lines[row&511]=0;
        auto* p=pens.data()+row*kLayerWidth;const auto* v=vram.data()+row*512;
        for(int L=0;L<kLayerWidth;++L)p[L]=PastVram(L)?clear_pen[row]:v[(L-kExtra+512)&511];
        std::fill_n(fixed.begin()+row*kLayerWidth,kLayerWidth,uint8_t(0));
        if(!blood.empty())std::fill_n(blood.begin()+row*kLayerWidth,kLayerWidth,Blood{});
    }
    void MarkCleared(size_t index){if(Enabled())cleared[(index>>17)&1]=true;}
    int ShiftOfRow(unsigned vram_row)const{return page_shift[(vram_row>>8)&1];}
    unsigned FittedOfRow(unsigned vram_row)const{return page_fitted[(vram_row>>8)&1];}
    void PlainPage(unsigned p,const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood,bool centre_only=false){
        // edge_fill: a Backdrop page keeps the pixels Tidy filled in the arcade's edge columns (EdgeDraws, ImageEdges) where
        // the arcade still leaves the page clear's pen; anything the game drew there since comes from VRAM.
        const int keep=centre_only&&Backdrop()?edge_fill:0;
        const int first=centre_only?kWideMargin:0,last=centre_only?kWideMargin+kVisible:kLayerWidth;
        const bool stains=!blood.empty(),arcade=arcade_blood.size()==vram.size();
        for(size_t row=size_t(p)*256;row<size_t(p)*256+256;++row){   // plain pointers: the stores cannot move the layers
            uint16_t* to=pens.data()+row*kLayerWidth;uint8_t* marks=fixed.data()+row*kLayerWidth;
            Blood* stain=stains?blood.data()+row*kLayerWidth:nullptr;
            const uint16_t* from=vram.data()+row*512;const Blood* arcade_stain=arcade?arcade_blood.data()+row*512:nullptr;
            for(int L=first;L<last;++L){const size_t v=size_t((L-kExtra+512)&511);const bool past=PastVram(L);
                if(keep&&(L<kWideMargin+keep||L>=kWideMargin+kVisible-keep)&&from[v]==clear_pen[row])continue;
                to[L]=past?clear_pen[row]:from[v];marks[L]=0;if(stain)stain[L]=arcade_stain&&!past?arcade_stain[v]:Blood{};}
        }
        page_shift[p]=0;page_fitted[p]=0;
    }
    // A page composed with an offset and not cleared since keeps its last composition, moved by the change of offset.
    void SetShift(int d){
        // The lag follows need * |d| / kWideMargin by at most kPushStep columns a build (a band's end entering the layer
        // inside the ramp would otherwise make the far planes jump).
        push_seen=push_need;push_need=0;
        const int target=d>0?-(push_seen*d/kWideMargin):d<0?push_seen*-d/kWideMargin:0;
        push=std::clamp(target,push-kPushStep,push+kPushStep);
        int& now=page_shift[page];shift=d;kept=false;arena=false;menu=false;composed=true;   // the shadow composes this build
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
        cleared[page]=false;shift=page_shift[page];frame_started=true;page_fitted[page]=0;composed=false;booked.fill(false);
    }
    // A Backdrop screen's frame is complete (the next display interrupt): its margins take its background. render(regs,
    // under) draws layer registers (their clip included) into the layer as scenery, inside the arcade's columns (under) only
    // over the page clear's pen; opaque(regs) tells whether a draw writes kCovered of its rectangle.
    template<class Render,class Opaque> void Tidy(Render&& render,Opaque&& opaque){
        if(Backdrop()){EdgeDraws(render,opaque);ImageEdges();}
        edge_draws.clear();palette_uses={};image_rows={};image_dirty={};placements.clear();
    }
    // Lines whose margin reflects the picture's background (bit 0: the left margin, bit 1: the right one): this frame's large
    // background pieces at an edge (EdgeDraws), and a decompressed image's lines (CPU writes at an arcade edge band; until
    // the line's page clear), all of them again whenever the image grows (image_dirty: the decompressor writes over frames).
    std::array<uint8_t,512> image_rows{},image_lines{},image_palette{};std::array<bool,2> image_dirty{};   // image_palette: a piece's line's palette
    // Those lines' background at an edge is the pens of their kBand edge columns (from the picture's edge: a line may leave
    // up to kNear arcade columns in the page clear's pen) that occur at least kSeen times on the page's marked lines (the
    // figure in front of it, a logo, a fighter or an ornament, has pens of its own). Per line, the background run from the
    // picture's edge inward (a lone other pixel, the dither, does not end it) is reflected back and forth over the margin
    // (edge_fill: also over the arcade's last edge_fill columns); a line with no run takes the page clear's pen.
    static constexpr unsigned kSeen=3;static constexpr int kFull=32;
    void ImageEdges(){
        for(unsigned p=0;p<2;++p)for(const bool right:{false,true}){
            const uint8_t side=right?2:1;
            const auto marked=[&](size_t row){return ((image_rows[row]|(image_dirty[p]?image_lines[row]:0))&side)!=0;};
            // A piece's lines (no decompressed image there) are read more strictly: only the piece's palette, the pens of the
            // outermost kEdge columns, and the run ends at the first other pixel (an ornament shares the piece's palette, a
            // fighter in front of it does not); a line whose run is shorter than kFull takes the margin of one of the piece's
            // lines with a full run (so neither the ornament nor a short run's stripes reach the margin).
            const auto strict=[&](size_t row){return !(image_lines[row]&side);};
            bool any=false;for(size_t row=size_t(p)*256;row<size_t(p)*256+256;++row)any|=marked(row);
            if(!any)continue;
            const auto column=[&](int i){return right?kWideMargin+kVisible-1-i:kWideMargin+i;};   // i: arcade column from the edge inward
            const auto start=[&](size_t base,uint16_t clear){int s=0;while(s<kNear&&pens[base+size_t(column(s))]==clear)++s;return s;};
            const auto own=[&](size_t row,uint16_t pen){return !strict(row)||((pen>>8)&0x7f)==image_palette[row];};
            std::vector<uint16_t> seen;
            for(size_t row=size_t(p)*256;row<size_t(p)*256+256;++row)if(marked(row)){
                const size_t base=row*kLayerWidth;const int s=start(base,clear_pen[row]);
                for(int i=s;i<s+(strict(row)?kEdge:kBand);++i)if(own(row,pens[base+size_t(column(i))]))seen.push_back(pens[base+size_t(column(i))]);
            }
            std::sort(seen.begin(),seen.end());std::vector<uint16_t> background;
            for(size_t i=0;i<seen.size();){size_t j=i;while(j<seen.size()&&seen[j]==seen[i])++j;if(j-i>=kSeen)background.push_back(seen[i]);i=j;}
            const auto is=[&](size_t row,int i){const uint16_t pen=pens[row*kLayerWidth+size_t(column(i))];
                return own(row,pen)&&std::binary_search(background.begin(),background.end(),pen);};
            const auto margin=[&](int t){return right?kWideMargin+kVisible+t:kWideMargin-1-t;};
            std::vector<size_t> full,partial;   // a piece's lines with a full run, and with a shorter one
            for(size_t row=size_t(p)*256;row<size_t(p)*256+256;++row)if(marked(row)){
                const size_t base=row*kLayerWidth;const int s=start(base,clear_pen[row]);int run=0;
                const bool lone=!strict(row);
                while(s+run<kWideMargin&&(is(row,s+run)||(lone&&s+run+1<kWideMargin&&run&&is(row,s+run+1))))++run;
                if(strict(row))(run>=kFull?full:partial).push_back(row);
                for(int t=-std::min(s,edge_fill);t<kWideMargin;++t){   // t: columns outward from the arcade's edge (negative: inside it)
                    const int m=run?(t+s)%(2*run):0,i=s+(m<run?m:2*run-1-m);
                    Write(base+size_t(margin(t)),run?pens[base+size_t(column(i))]:clear_pen[row]);
                }
            }
            if(!full.empty())for(const size_t row:partial){
                const size_t from=full[row%full.size()];
                for(int t=0;t<kWideMargin;++t)Write(row*kLayerWidth+size_t(margin(t)),pens[from*kLayerWidth+size_t(margin(t))]);
            }
        }
    }
    // The background draws among this frame's draws at an arcade edge, unscaled and opaque: a tile, in a palette kShared draws
    // of the frame use (the stone, tiles and panels; a portrait or a sprite has a palette of its own), at least kTile wide and
    // narrower than kWide, puts its art beyond the edge in the margin and repeats there at its step (Step), as the screen's
    // own tiling would continue (edge_fill: the continuation also covers the pixels of the arcade's last edge_fill columns
    // that the screen leaves in the page clear's pen: MK1's tiles end a column short of the screen's edge, MK2's story and
    // logo screens leave their last 7 columns black); a large piece (at least kPiece on each side, or kWide wide: a marble, a gradient band or a
    // picture behind the screen; any palette) marks its lines for ImageEdges. Narrow strips (a border line at the edge) do not continue.
    static constexpr unsigned kShared=8;static constexpr int kTile=16,kWide=200,kPiece=64,kStrip=8;
    template<class Render,class Opaque> void EdgeDraws(Render&& render,Opaque&& opaque){
        constexpr int left_edge=kWideMargin,right_edge=kWideMargin+kVisible;
        for(const auto& r:edge_draws){
            if((r[10]&&r[10]!=0x100)||(r[11]&&r[11]!=0x100))continue;
            const auto [lo,hi]=Span(r[4],r[6],r[10],(r[1]&0x10)!=0);const int w=hi-lo,h=r[7]&0x3ff;
            // A piece the game itself puts past the screen's edge is the scene going on (the Test Your Might wall and base,
            // palettes of their own), unless it is a strip (a meter's frame sliding in); a constant fill (a meter's level) is
            // not a tile.
            const bool past=(lo<left_edge||hi>right_edge)&&h>=kStrip,fill=(r[1]&15)==12;
            const bool tile=!fill&&w>=kTile&&w<kWide&&(palette_uses[(r[8]>>8)&0x7f]>=kShared||past),piece=(w>=kPiece&&h>=kPiece)||w>=kWide;
            if(!(tile||piece))continue;
            const Cover art=opaque(r);if(!art.opaque)continue;
            const auto draw=[&](std::array<uint16_t,18> c,int first,int last){
                c[16]=uint16_t(std::max<int>(first,c[16]));c[17]=uint16_t(std::min<int>(last,c[17]));if(c[16]<=c[17])render(c,edge_fill>0);};
            for(const bool right:{false,true}){
                const int first=right?right_edge-edge_fill:0,last=right?kLayerWidth-1:left_edge-1+edge_fill;
                if(right?!(hi>=right_edge-kNear&&lo<right_edge):!(lo<=left_edge+kNear&&hi>left_edge))continue;
                if(!tile){   // its lines (within the drawn page and the clip) reflect the picture's background
                    const int top=std::max<int>(r[5]&0x1ff,r[12]&0x1ff),bottom=std::min<int>((r[5]&0x1ff)+h,(r[13]&0x1ff)+1);
                    for(int y=top;y<bottom&&y<512;++y){image_rows[size_t(y)]|=right?2:1;image_palette[size_t(y)]=uint8_t((r[8]>>8)&0x7f);}
                    continue;
                }
                auto c=r;c[16]=0;c[17]=kLayerWidth-1;draw(c,first,last);   // its own art there
                const int step=Step(Source(r),w,art.last>art.first?art.last-art.first:w);
                for(int k=1;right?lo+k*step<kLayerWidth:hi-k*step>0;++k){c=r;c[4]=uint16_t((c[4]+(right?k*step:-k*step))&0x3ff);c[16]=0;c[17]=kLayerWidth-1;draw(c,first,last);}
            }
        }
    }
    // A tile's step along its row: the most frequent distance between neighbouring draws of its source on a line (the game
    // overlaps its tiles), up to its width; without neighbours, that of the draws as wide (a tile cut to a border strip);
    // else the width of its art (a piece whose outer column is transparent would leave a gap at each repeat).
    int Step(uint32_t source,int width,int art)const{
        const int own=Step(width,[&](const Placement& p){return p.source==source;});if(own)return own;
        const int alike=Step(width,[&](const Placement& p){return p.width==width;});return alike?alike:art;
    }
    template<class Same> int Step(int width,Same&& same)const{
        std::vector<std::pair<uint64_t,int16_t>> own;   // per source and line, its draws' first columns
        for(const auto& p:placements)if(same(p))own.push_back({uint64_t(p.source)<<9|p.line,p.first});
        std::sort(own.begin(),own.end());std::vector<int> steps;
        for(size_t i=1;i<own.size();++i)if(own[i].first==own[i-1].first){const int s=own[i].second-own[i-1].second;if(s>0&&s<=width)steps.push_back(s);}
        std::sort(steps.begin(),steps.end());int best=0;size_t most=0;
        for(size_t i=0;i<steps.size();){size_t j=i;while(j<steps.size()&&steps[j]==steps[i])++j;if(j-i>most){most=j-i;best=steps[i];}i=j;}
        return best;   // 0: no neighbours
    }
    int edge_fill=0;   // the arcade columns at each edge Tidy may fill where the screen leaves the page clear's pen
    template<class Render,class Opaque> void EndUnbuiltFrame(const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood,
                                                             Render&& render,Opaque&& opaque){
        if(!Enabled())return;
        Tidy(render,opaque);
        if(kept){PlainPage(page,vram,arcade_blood);kept=false;}
        if(!frame_started)for(unsigned p=0;p<2;++p)if(page_shift[p])PlainPage(p,vram,arcade_blood);
        shift=page_shift[page];   // until the next build: no shadow, no offset
    }
    // This frame's offset from the mode (shifting, holding or neither), the camera and the arena's limits (a finisher
    // frees the camera: limits wider than world_max keep the arena's last ones).
    int Offset(bool shifting,bool holding,int camera,int low,int high,int world_max){
        if(low<=high&&high-low<=world_max){if(limits[0]!=low||limits[1]!=high)push_need=0;limits={low,high,1};}   // another arena: no push yet
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
    template<class A> void LayerFields(A& a){a(pens,blood,fixed,page_shift,page_fitted,cleared,held,limits,ratio,ratio_limits,kept,frame_started,shift,page,world,push,push_need,push_seen,
                                                clear_pen,arena,menu,composed,edge_draws,palette_uses,image_rows,image_lines,image_palette,image_dirty,placements,booked,rom_palette);}
    void Reset(){const int fill=edge_fill;*this=Layer{};edge_fill=fill;}
};
}
