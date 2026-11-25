#pragma once
// Widescreen (Remastered presentation only) shared by the games whose VRAM line has 512 columns with the 400 visible ones
// from column 56 (MK1 rev 5.0, MK2 L3.1). The game runs unchanged: a shadow pass, run by the generated code on journaled
// RAM with no cycles, runs the frame's display-list walk again with the game's clip widened, and its draws land at their
// own signed screen x in a 16:9 layer of its own (534 columns: the arcade's 400 and 67 on each side, more than a VRAM line
// holds; no column wraps to the other side). The arcade's 400 columns stay the arcade's own pixels. A margin shows only
// what the game's draws put there; where a scenery layer has no art the margin is masked (black), never filled.
// Game facts (addresses) stay in each game's table (mk5_widescreen.hpp, mk2/mk2_widescreen.hpp).
// Layer index: VRAM row (both 256-line pages) * kLayerWidth + layer column; layer column L shows screen x L-67.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <utility>
#include <vector>

namespace mk5wide {
constexpr int kMargin=56;      // VRAM columns beyond each side of the visible ones
constexpr int kVisible=400;
constexpr int kWidth=512;      // a VRAM line
constexpr int kWideMargin=67;  // layer columns beyond each side of the visible ones: 534/400 x 4:3 = 16:9
constexpr int kLayerWidth=kVisible+2*kWideMargin;
constexpr int kExtra=kWideMargin-kMargin;   // VRAM column c is layer column c+kExtra
constexpr unsigned kAcross=16,kDown=9;      // the wide frame's physical aspect
constexpr size_t kLayerSize=size_t(512)*kLayerWidth;
constexpr int kReach=112;      // the shadow's clip reaches this far past the layer: objects partly inside it are built
// A draw's x register in layer columns: the shadow renders its draws with this x, the layer's stride and its clip.
constexpr uint16_t LayerX(uint16_t x){return uint16_t((x+kExtra)&0x3ff);}
// A DMA draw's columns [first, last) from its x register (the board reads 10 bits, here as -256..767: the bits above them
// are the game's flags), width, X step and flip, as the columns follow one another (the board's blitter wraps them at 1024).
inline std::pair<int,int> Span(uint16_t x_register,uint16_t width_register,uint16_t xstep_register,bool flip){
    int x=x_register&0x3ff;if(x>=768)x-=1024;
    const unsigned xstep=xstep_register?xstep_register:0x100;   // a source column every xstep/256: ceil(width*256/xstep) of them
    const int w=int((((width_register&0x3ffu)<<8)+xstep-1)/xstep),lo=flip?x-w+1:x;
    return {lo,lo+w};
}
// A DMA draw's rows [first, last) of the 512 (both pages) from its y register, height, Y step and vertical flip, within its
// clip rows; the rows the board's blitter visits (Blit/Render: y steps by one row per source row, modulo 512).
inline std::pair<int,int> Rows(const std::array<uint16_t,18>& r){
    const unsigned ystep=r[11]?r[11]:0x100;const int h=int(((r[7]&0x3ffu)*256+ystep-1)/ystep),y=r[5]&0x1ff;
    const int lo=(r[1]&0x20)?y-h+1:y;return {std::max(lo,int(r[12]&0x1ff)),std::min(lo+h,int(r[13]&0x1ff)+1)};
}
// The wide window's offset d at an arena's ends: the wide screen shows the world as the arcade would at camera x + d, and
// its camera is the arcade's limited to [minimum+67, maximum-67], so the 16:9 picture never passes the world's ends (the
// arcade screen stands at them at each camera limit). No ramp, no lag: d depends on the camera alone. An arena narrower
// than that keeps its world centred.
inline int WindowShift(int camera,int minimum,int maximum){
    if(minimum>maximum)return 0;
    camera=std::clamp(camera,minimum,maximum);
    const int low=minimum+kWideMargin,high=maximum-kWideMargin;
    return (low>high?(minimum+maximum)/2:std::clamp(camera,low,high))-camera;
}
constexpr int kWorldMax=4096;  // camera limits wider than this (a finisher frees the camera) keep the arena's last ones
// A far plane's parallax: its velocity and the world's in a frame where the world moved (world 0: not known yet).
struct Ratio{int64_t plane=0,world=0;
    template<class A> friend void Fields(A& a,Ratio& r){a(r.plane,r.world);}};
inline Ratio MeasuredRatio(int32_t velocity,int32_t world_velocity){
    return world_velocity>0?Ratio{velocity,world_velocity}:Ratio{-int64_t(velocity),-int64_t(world_velocity)};
}
// The window offset as the world scroll's move (16.16): with offset d the shadow's world camera is the whole column
// camera + d, whatever fraction the arcade's scroll carries (so nothing trembles while the arcade's camera moves under a
// wide camera that stands at its limit).
inline int64_t ScrollOffset(int32_t world_scroll,int d){return d?(int64_t((world_scroll>>16)+d)<<16)-world_scroll:0;}
// Where a pixel of the wide layer came from (diagnostics, Layer::debug): the kind of write and the columns its draw covers
// in layer columns as they follow one another from its x (Span): a pixel outside them got there by a wrap.
enum class Kind:uint8_t{none,real,shadow,cpu,clear,generated,continued};   // continued: Layer::MaskBands
struct Origin{int16_t lo=0,hi=0;Kind kind=Kind::none;uint8_t page=0;
    bool Covers(int column)const{return column>=lo&&column<hi;}
    template<class A> friend void Fields(A& a,Origin& o){a(o.lo,o.hi,o.kind,o.page);}};
constexpr uint32_t kSentinel=0xffff00ff;   // magenta: a margin pixel no draw wrote (Layer::debug)
constexpr uint32_t kMasked=0xff000000;     // black: a margin pixel without art (Layer::Shown)
// A shown frame's margin pixels audited (Layer::AuditRow, debug): shown (all of them), sentinel (no draw wrote it), masked
// (no art: Layer::Shown), outside (the draw that wrote it never meant to cover its column: a wrap, a copy, a move),
// generated (written by no draw of the game), stale (on a line the frame rewrote across the arcade's 400 columns, written
// before the frame).
struct Audit{uint64_t shown=0,sentinel=0,masked=0,outside=0,outside_real=0,generated=0,stale=0;   // outside_real: of outside, a real DMA's
    void Add(const Audit& o){shown+=o.shown;sentinel+=o.sentinel;masked+=o.masked;outside+=o.outside;outside_real+=o.outside_real;generated+=o.generated;stale+=o.stale;}};
// A scenery layer's draw in a build (debug, the parallax check): its layer, image source and row, its columns (layer
// columns) and its list's camera x (scenery moves by minus the camera's move; an object with a velocity of its own does not).
struct Note{uint16_t layer;uint32_t source;uint16_t row;int16_t lo,hi,camera;};
// A staged draw as placed on the layer (debug): its columns (layer columns), first row and rows, image source, control
// word, whether it is screen-fixed and its scenery layer (-1: none).
struct Placed{int16_t lo,hi;uint16_t row,rows;uint32_t source;uint16_t control;bool fixed;int16_t layer;};
// A scenery layer's art in a build (Layer::Band): per line its pixels cover all of the arcade's 400 columns on, the columns
// of the margins without its art (left: [0, left), right: [right, kLayerWidth)); a side whose draws reach past the layer
// keeps all of it. first: the serial of the layer's first draw in the layer (0: not drawn yet); farther pixels are older.
struct BandRow{uint16_t row;int16_t left,right;template<class A> friend void Fields(A& a,BandRow& b){a(b.row,b.left,b.right);}};
struct Band{uint16_t layer=0;uint32_t first=0;std::vector<BandRow> rows;uint16_t full=0;   // full: its lines that cover the arcade's columns whole
    template<class A> friend void Fields(A& a,Band& b){a(b.layer,b.first,b.rows,b.full);}};
inline bool ArcadeColumn(int L){return L>=kWideMargin&&L<kWideMargin+kVisible;}
// A screen without an arena whose margins the game does not fill (a menu, a story picture: Layer::page_soft) shows soft
// sides instead of pieces of art and black: each margin line takes the colour of the arcade line's own end (its outermost
// kSoftColumns columns, past at most kSoftSkip black ones: a picture a few columns short of the screen's edge), blurred
// over kSoftRows lines up and down and dimmed towards the screen's edge. Nothing of the picture is copied: no object can
// appear twice. frame: kLayerWidth columns by height lines, 0xAARRGGBB.
constexpr int kSoftColumns=4,kSoftRows=10,kSoftSkip=12;
inline void SoftMargins(uint32_t* frame,unsigned height){
    for(int side=0;side<2;++side){
        std::vector<std::array<unsigned,3>> edge(height);   // each line's end colour
        for(unsigned y=0;y<height;++y){
            std::array<unsigned,3> sum{};
            const auto at=[&](int k){return frame[size_t(y)*kLayerWidth+size_t(side?kWideMargin+kVisible-1-k:kWideMargin+k)];};
            int skip=0;while(skip<kSoftSkip&&!(at(skip)&0xffffffu))++skip;
            for(int k=skip;k<skip+kSoftColumns;++k){
                const uint32_t p=at(k);
                sum[0]+=p>>16&255;sum[1]+=p>>8&255;sum[2]+=p&255;
            }
            edge[y]={sum[0]/unsigned(kSoftColumns),sum[1]/unsigned(kSoftColumns),sum[2]/unsigned(kSoftColumns)};
        }
        for(unsigned y=0;y<height;++y){
            std::array<unsigned,3> sum{};unsigned n=0;
            for(int dy=-kSoftRows;dy<=kSoftRows;++dy)if(const int at=int(y)+dy;at>=0&&at<int(height)){for(int c=0;c<3;++c)sum[size_t(c)]+=edge[size_t(at)][size_t(c)];++n;}
            for(int k=0;k<kWideMargin;++k){   // k: columns from the arcade's edge
                const unsigned light=150-90u*unsigned(k)/unsigned(kWideMargin);   // of 256: 59% beside the picture, 23% at the screen's edge
                const uint32_t rgb=(sum[0]/n*light>>8)<<16|(sum[1]/n*light>>8)<<8|(sum[2]/n*light>>8);
                frame[size_t(y)*kLayerWidth+size_t(side?kWideMargin+kVisible+k:kWideMargin-1-k)]=0xff000000u|rgb;
            }
        }
    }
}
// One scenery layer's draws measured (layer registers, x in layer columns; meant: each draw's columns as the game meant
// them): render(regs, put) calls put(layer index) for each pixel the draw writes. Its lines whose arcade columns it covers
// whole, each with its art's ends in the margins (its outermost pixels on the line; a side where a draw reaches past the
// layer keeps all of its columns).
// The draws may be measured over a wider canvas (width columns, the layer's column 0 at its column origin; draws, meant and
// render in canvas columns): the ends are then known that far past the layer (BandRow in layer columns all the same).
template<class Render> Band MeasureBand(uint16_t layer,const std::vector<std::array<uint16_t,18>>& draws,
                                        const std::vector<std::pair<int,int>>& meant,Render&& render,
                                        int width=kLayerWidth,int origin=0){
    constexpr size_t kWords=(kVisible+63)/64;
    std::vector<uint64_t> bits(512*kWords,0);std::vector<uint16_t> covered(512,0);
    std::vector<int16_t> lo(512,int16_t(width)),hi(512,0);std::vector<uint8_t> reach(512,0);
    for(size_t k=0;k<draws.size();++k){
        const auto [first,last]=Rows(draws[k]);
        const uint8_t past=uint8_t((meant[k].first<0?1:0)|(meant[k].second>width?2:0));
        if(past)for(int y=std::max(first,0);y<std::min(last,512);++y)reach[size_t(y)]|=past;
        render(draws[k],[&](size_t index){
            const size_t row=index/size_t(width);if(row>=512)return;const int at=int(index%size_t(width)),c=at-origin;
            lo[row]=std::min(lo[row],int16_t(at));hi[row]=std::max(hi[row],int16_t(at+1));
            if(!ArcadeColumn(c))return;
            uint64_t& word=bits[row*kWords+size_t(c-kWideMargin)/64];const uint64_t bit=uint64_t(1)<<((c-kWideMargin)%64);
            if(!(word&bit)){word|=bit;++covered[row];}
        });
    }
    Band band;band.layer=layer;
    for(uint16_t y=0;y<512;++y)if(covered[y]==kVisible){
        ++band.full;
        const int16_t left=int16_t(((reach[y]&1)?0:lo[y])-origin),right=int16_t(((reach[y]&2)?width:hi[y])-origin);
        if(left>-origin||right<width-origin)band.rows.push_back({y,left,right});
    }
    return band;
}

// The wide frame over the two 256-line VRAM pages: pens (the VRAM's format), the floor stains over it (Blood: the game's
// blood layer element, 0 = none) and per pixel its marks (fixed: kFixed a screen-fixed (HUD) draw's, kActor a floor
// shadow's, kFighter a fighter's, kMask a margin pixel without art) and its writer's serial.
template<class Blood>
struct Layer {
    std::vector<uint16_t> pens;std::vector<Blood> blood;std::vector<uint8_t> fixed;
    static constexpr uint8_t kFixed=1,kActor=2,kFighter=4,kMask=8;   // fixed: bits
    // A constant-colour draw (DMA control's low nibble 8: a fighter's floor shadow) is an actor's, not the scene's.
    static bool ActorDraw(uint16_t control){return (control&15)==8;}
    // Each draw that writes the layer takes the next serial (Draw); every pixel keeps its last writer's serial (written; 0:
    // none since the page was taken plain from VRAM: never shown in a margin). With debug on (TRIUNIT_WIDE_DEBUG set when
    // the layer is enabled) each pixel also keeps that draw's Origin, the scanouts show kSentinel for a margin pixel no draw
    // wrote and each build's scenery draws are noted (notes, the parallax check).
    std::vector<uint32_t> written;std::vector<Origin> origin;uint32_t serial=0;Origin drawing;bool debug=false;
    std::array<uint32_t,2> page_start{};   // the serial when each page's frame started (a later serial: written by the frame)
    std::array<bool,2> cleared{{true,true}};   // the page clear ran on the page since its last build
    unsigned page=0;
    // The window offset (WindowShift) of the frame being built and of each page's last build. held: the camera and the
    // offset of the fight's last frame: after the fight's modes (the finisher, the round's end, the arena fading out) the
    // offset and the held planes stay while the camera does, build after build. limits:
    // the arena's last usable camera limits (min, max, valid). ratio: per scroll slot, for this arena.
    int shift=0;std::array<int,2> page_shift{},held{};std::array<int,3> limits{};
    std::array<Ratio,10> ratio{};std::array<int,2> ratio_limits{};
    // whole: this build's world comes from the shadow's draws alone (an offset window, or a far plane held at its art's
    // end: PlaneScroll); per page too. bound: per scroll slot, for this arena, the plane cameras between which its art
    // covers the wide screen whole (Learn, from the plane's measured bands).
    bool whole=false,fight=false;std::array<bool,2> page_whole{};   // fight: the build is a fight's (Offset): far planes are held
    // scene: this build drew a far plane that covers kPicture lines or more of the arcade screen (an arena, in a fight or
    // not). page_soft: the page's last build was a screen without an arena whose margins the game left unfilled
    // (EndFrame): its sides are shown soft (SoftMargins).
    // wider: in this build a scenery layer's art went on past the arcade screen (kSliver columns or more of a margin, on
    // kPicture lines or more that cover the arcade's columns whole): an arena, not a picture the size of the arcade
    // screen. arena: the build before had one. It tells an attract demo's fight from the attract's other screens (the
    // game's mode word is the same).
    bool scene=false,wider=false,arena=false;std::array<bool,2> page_soft{};
    // A scenery layer's band, measured from its staged draws; slot: its far plane's scroll slot (-1: none).
    void Measured(int slot,int camera,Band&& band){
        int narrow=0;
        for(const auto& r:band.rows)narrow+=r.left>kWideMargin-kSliver&&r.right<kWideMargin+kVisible+kSliver;
        wider|=int(band.full)-narrow>=kPicture;
        if(slot>=0){scene|=band.full>=kPicture;Learn(unsigned(slot),camera,band);}
        if(!band.rows.empty())bands.push_back(std::move(band));
    }
    std::array<uint32_t,2> page_cleared_at{};   // the serial of each page's last clear (Mirror): a later pixel is art
    static constexpr int kNoLow=-(1<<30),kNoHigh=1<<30;
    static std::array<std::array<int,2>,10> Unbound(){std::array<std::array<int,2>,10> b;b.fill({kNoLow,kNoHigh});return b;}
    std::array<std::array<int,2>,10> bound=Unbound();
    void Whole(){page_whole[page]=whole=true;}
    // span: per scroll slot, the plane cameras of the arcade at the arena's camera limits (PlaneScroll; first > second:
    // not known yet).
    std::array<std::array<int,2>,10> span=NoSpan();
    static std::array<std::array<int,2>,10> NoSpan(){std::array<std::array<int,2>,10> s;s.fill({1,0});return s;}
    // A far plane's measured band, drawn with its list's camera: where its art ends inside the shadow's clip. Only an end
    // the arcade never shows counts (the line's art reaches the arcade screen's edge at that camera limit): a narrower
    // line (an object on the plane) shows its ends on the arcade screen too, and keeps them.
    void Learn(unsigned slot,int camera,const Band& b){
        slot=std::min(slot,unsigned(bound.size()-1));auto& at=bound[slot];const auto [first,last]=span[slot];
        if(first>last||!fight)return;
        for(const auto& r:b.rows){
            if(r.left>-kReach&&camera+r.left-kWideMargin<=first)at[0]=std::max(at[0],camera+r.left);
            if(r.right<kLayerWidth+kReach&&camera+r.right-kWideMargin-kVisible>=last)at[1]=std::min(at[1],camera+r.right-kLayerWidth);
        }
    }
    // A far plane's scroll (16.16) in the shadow pass at the world camera x: the arcade's moved by its ratio times the
    // window offset (offset: ScrollOffset), then kept between its bounds, so its art's end stops at the wide screen's edge. The
    // plane slows down into the bound instead of stopping dead: over the last 2g columns before it, g being how far past
    // the bound the plane would stand at the wide camera's limit, it moves along a parabola (slope 1 to 0). Everything
    // depends on the camera alone: with the camera still, every plane stands still.
    int32_t PlaneScroll(unsigned slot,int32_t scroll,int camera,int64_t offset){
        slot=std::min(slot,unsigned(ratio.size()-1));const Ratio& r=ratio[slot];
        const auto part=[&](int64_t by){return r.world?by*r.plane/r.world:by;};   // an unknown ratio counts as the world's
        const auto move=[&](int64_t columns){return part(columns*65536);};
        // A sixteenth of a column: the sum's last bits depend on the arcade's fraction and must not tip a whole column.
        const auto settle=[&](int64_t v){return v==scroll?scroll:int32_t((v+2048)&~int64_t(4095));};
        int64_t q=int64_t(scroll)+part(offset);
        if(!limits[2]||!r.world||!fight)return settle(q);   // no arena, no ratio yet or no fight: as the arcade has it
        const int at=std::clamp(camera,limits[0],limits[1]),wide=at+shift;   // the arcade's camera and the wide one
        span[slot]={int((scroll-move(at-limits[0])+65535)>>16),int((scroll+move(limits[1]-at))>>16)};
        const int low=bound[slot][0],high=bound[slot][1];
        if(low>high)return settle(q);   // art narrower than the wide screen: as the arcade has it
        const int wide_low=limits[0]+WindowShift(limits[0],limits[0],limits[1]),wide_high=limits[1]+WindowShift(limits[1],limits[0],limits[1]);
        const auto ease=[](int64_t u,int64_t g){return u>=g?u:u<=-g?int64_t(0):(u+g)*(u+g)/(4*g);};
        if(low!=kNoLow){const int64_t edge=int64_t(low)*65536,g=edge-(q-move(wide-wide_low));if(g>0)q=edge+ease(q-edge,g);}
        if(high!=kNoHigh){const int64_t edge=int64_t(high)*65536,g=(q+move(wide_high-wide))-edge;if(g>0)q=edge-ease(edge-q,g);}
        return settle(q);
    }
    // keep: after the fight's modes the offset stays while the camera does (an attract demo's does not: Layer::arena).
    int Offset(bool shifting,int camera,int low,int high,bool keep=true){
        // Limits wider than kWorldMax: a finisher freed the camera (the fight goes on: the arena's last limits stay), or the
        // arena has a free camera from its start (no limits: the window stays centred).
        if(low<=high&&high-low<=kWorldMax)limits={low,high,1};
        else if(!fight)limits[2]=0;   // fight: still the last build's
        NewArena();
        const bool hold=keep&&!shifting&&fight&&camera==held[0];
        const int d=shifting?(limits[2]?WindowShift(camera,limits[0],limits[1]):0):hold?held[1]:0;
        if(shifting)held={camera,d};
        fight=shifting||hold;
        if(d)Whole();
        return page_shift[page]=shift=d;
    }
    void NewArena(){   // a new arena forgets the old one's ratios and bounds
        if(ratio_limits[0]!=limits[0]||ratio_limits[1]!=limits[1]){ratio={};bound=Unbound();span=NoSpan();ratio_limits={limits[0],limits[1]};}
    }
    Ratio& PlaneRatio(unsigned slot){NewArena();return ratio[std::min(slot,unsigned(ratio.size()-1))];}
    void Draw(Kind kind,int lo,int hi,int layer=-1){
        if(!++serial)serial=1;
        drawing={int16_t(std::clamp(lo,-32768,32767)),int16_t(std::clamp(hi,-32768,32767)),kind,uint8_t(page)};
        if(layer>=0)for(auto& b:bands)if(b.layer==layer&&!b.first)b.first=serial;
    }
    void Stamp(size_t index){written[index]=serial;if(debug)origin[index]=drawing;}
    // Scenery layers measured this build (MeasureBand); applied when the frame ends (MaskBands).
    std::vector<Band> bands;
    std::vector<Note> notes,notes_done;   // debug: this build's scenery draws, and the last finished build's
    std::vector<Placed> placed,placed_done;   // debug: this build's staged draws as placed, and the last finished build's
    std::vector<Band> bands_done;unsigned builds=0;   // debug: the last frame's measured layers; builds started
    // A margin pixel of a band's line without the band's art, older than the band's first draw (the page clear's pen or a
    // farther layer: what the band would cover; a nearer one, a fighter or a projectile, stays), continues the line's art
    // where that is its own pattern going on:
    //  - a layer most of whose short lines on a side (3 in 5) end flat or in a two-column dither (their last kPattern
    //    columns repeat every two: a sky's gradient), or whose short lines there end on one straight edge (9 in 10 at
    //    the same column, kPicture lines or more: a backdrop picture narrower than the wide screen), keeps each line's
    //    last columns to the screen's edge, all its lines alike (no line left out among the others);
    //  - a gap of at most kSliver columns takes the columns next to it (a floor's texture a few columns on).
    // Any other shows black. Only an arena's lines are continued (a fight's build, or one with a far plane's picture): a
    // menu's textured background would come out as streaks, and its sides are shown soft instead (page_soft).
    static constexpr int kPattern=8,kSliver=24,kPicture=32;
    void MaskBands(){
        const bool art=fight||scene;
        for(const auto& b:bands)if(b.first){
            const auto own=[&](size_t row,int L){return L>=0&&L<kLayerWidth&&written[row+size_t(L)]>=b.first;};   // the band's art or nearer
            // The line's art from `edge` inwards (side -1: the left gap's, +1: the right gap's) repeats every two columns.
            const auto dithered=[&](size_t row,int edge,int side){
                for(int k=0;k<kPattern;++k){const int L=edge-side*k;
                    if(!own(row,L)||(k>=2&&pens[row+size_t(L)]!=pens[row+size_t(L+2*side)]))return false;}
                return true;
            };
            std::array<int,2> lines{},patterned{};std::array<std::vector<int>,2> ends{std::vector<int>(kLayerWidth+1,0),std::vector<int>(kLayerWidth+1,0)};
            for(const auto& r:b.rows){
                const size_t row=size_t(r.row)*kLayerWidth;
                if(r.left>0){++lines[0];patterned[0]+=dithered(row,r.left,-1);++ends[0][size_t(std::min<int>(r.left,kLayerWidth))];}
                if(r.right<kLayerWidth){++lines[1];patterned[1]+=dithered(row,r.right-1,+1);++ends[1][size_t(std::max<int>(r.right,0))];}
            }
            const auto straight=[&](int side){   // the short lines end at one column, give or take one
                int best=0;for(int c=1;c<kLayerWidth;++c)best=std::max(best,ends[size_t(side)][size_t(c-1)]+ends[size_t(side)][size_t(c)]+ends[size_t(side)][size_t(c+1)]);
                return lines[size_t(side)]>=kPicture&&best*10>=lines[size_t(side)]*9;
            };
            const std::array<bool,2> gradient{patterned[0]*5>=lines[0]*3||straight(0),patterned[1]*5>=lines[1]*3||straight(1)};
            for(const auto& r:b.rows){
                const size_t row=size_t(r.row)*kLayerWidth;
                const auto gap=[&](int from,int to,int edge,int side){   // the art's first column is `edge`
                    from=std::max(from,0);to=std::min(to,kLayerWidth);if(from>=to)return;
                    const int width=to-from;const bool whole=art&&gradient[side>0]&&own(row,edge),dither=whole&&dithered(row,edge,side);
                    bool sliver=art&&!whole&&width<=kSliver;
                    for(int k=0;k<width&&sliver;++k)sliver=own(row,edge-side*k);
                    for(int L=from;L<to;++L){
                        const size_t at=row+size_t(L);
                        if(Arcade(L)||written[at]>=b.first)continue;
                        if(!whole&&!sliver){fixed[at]|=kMask;continue;}
                        const int away=side<0?edge-L:L-edge;   // columns from the art's first column, outwards (>= 1)
                        const int source=sliver?edge-side*(width-away):dither?edge-side*(away&1):edge;
                        pens[at]=pens[row+size_t(source)];fixed[at]=0;if(!blood.empty())blood[at]=Blood{};
                        written[at]=b.first;if(debug)origin[at]={int16_t(L),int16_t(L+1),Kind::continued,uint8_t(page)};
                    }
                };
                gap(0,r.left,r.left,-1);gap(r.right,kLayerWidth,r.right-1,+1);
            }
        }
        if(debug)bands_done=bands;
        bands.clear();
    }
    // Whether a layer pixel is shown: always in the arcade's columns; in a margin only when a draw wrote it and it has art.
    bool Shown(size_t index)const{return Arcade(int(index%kLayerWidth))||(written[index]&&!(fixed[index]&kMask));}
    // One shown line's margins (debug): the layer line of VRAM row vram_row.
    void AuditRow(Audit& a,unsigned vram_row)const{
        if(!debug)return;
        const size_t row=size_t(vram_row)*kLayerWidth;const uint32_t start=page_start[(vram_row>>8)&1];
        bool full=true;for(int L=kWideMargin;L<kWideMargin+kVisible&&full;++L)full=written[row+size_t(L)]>start;
        for(int L=0;L<kLayerWidth;++L){
            if(Arcade(L))continue;
            const size_t at=row+size_t(L);const Origin& o=origin[at];++a.shown;
            if(!written[at]){++a.sentinel;continue;}
            if(fixed[at]&kMask){++a.masked;continue;}
            a.generated+=o.kind==Kind::generated;
            a.outside+=(o.kind==Kind::real||o.kind==Kind::shadow)&&!o.Covers(L);a.outside_real+=o.kind==Kind::real&&!o.Covers(L);
            a.stale+=full&&written[at]<=start;
        }
    }
    bool Enabled()const{return !pens.empty();}
    static bool Arcade(int L){return ArcadeColumn(L);}
    void Enable(const std::vector<uint16_t>& vram,bool with_blood){
        pens.assign(kLayerSize,0);fixed.assign(kLayerSize,0);blood.assign(with_blood?kLayerSize:0,Blood{});
        written.assign(kLayerSize,0);debug=std::getenv("TRIUNIT_WIDE_DEBUG")!=nullptr;origin.assign(debug?kLayerSize:0,Origin{});
        for(unsigned p=0;p<2;++p)PlainPage(p,vram,{});
    }
    // The layer index of a VRAM index's screen position (-1: outside the layer).
    static int64_t At(size_t vram_index){
        const int c=int(vram_index&511)+kExtra;
        return c>=0&&c<kLayerWidth?int64_t(vram_index>>9)*kLayerWidth+c:-1;
    }
    void Write(size_t index,uint16_t pen,bool screen_fixed=false){
        pens[index]=booked[(pen>>8)&0x7f]?uint16_t(pen|kBooked):pen;fixed[index]=screen_fixed;if(!blood.empty())blood[index]=Blood{};
        Stamp(index);
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
    // CPU writes are screen-fixed at their VRAM column; a line copy (the page clear) writes the whole layer line, the
    // columns past the VRAM line included, in the line's pen. A cleared page holds no build any more: its window is the
    // arcade's and its sides are soft until a build ends on it (a picture the CPU writes on it, with no walk, is shown so).
    void Mirror(const std::vector<uint16_t>& vram,size_t start,size_t count){
        if(!Enabled())return;
        if(!(start&511)&&count&&!(count&511)){
            Draw(Kind::clear,0,kLayerWidth);
            for(size_t row=start>>9;row<(start+count)>>9;++row){
                const size_t p=(row>>8)&1;page_cleared_at[p]=serial;page_shift[p]=0;page_whole[p]=false;page_soft[p]=true;
                clear_pen[row]=vram[row*512];PlainRow(row,vram);
                for(size_t L=row*kLayerWidth;L<(row+1)*kLayerWidth;++L)Stamp(L);
            }
            return;
        }
        const auto put=[&](size_t to,uint16_t pen){Stamp(to);pens[to]=pen;fixed[to]=0;if(!blood.empty())blood[to]=Blood{};};
        for(size_t i=start;i<start+count;++i)if(const auto at=At(i);at>=0){
            Draw(Kind::cpu,int(at%kLayerWidth),int(at%kLayerWidth)+1);put(size_t(at),vram[i]);
            // The VRAM line's end column (far off the arcade screen: a line written whole, a wipe or a picture) gives its
            // pen to the layer's columns past it, as a line copy does.
            if(const size_t c=i&511;c==0||c==511)
                for(int L=c?kWidth+kExtra:0;L<(c?kLayerWidth:kExtra);++L)if(PastVram(L))put(size_t(at)/kLayerWidth*kLayerWidth+size_t(L),vram[i]);
        }
    }
    std::vector<uint16_t> clear_pen=std::vector<uint16_t>(512,0);   // each line's pen at its last page clear
    // The layer's columns past the VRAM line on each side (screen x -67..-57 and 456..466) have no VRAM column of their own.
    static bool PastVram(int L){return L<kExtra||L>=kWidth+kExtra;}
    void PlainRow(size_t row,const std::vector<uint16_t>& vram){
        auto* p=pens.data()+row*kLayerWidth;const auto* v=vram.data()+row*512;
        for(int L=0;L<kLayerWidth;++L)p[L]=PastVram(L)?clear_pen[row]:v[L-kExtra];
        std::fill_n(fixed.begin()+row*kLayerWidth,kLayerWidth,uint8_t(0));
        if(!blood.empty())std::fill_n(blood.begin()+row*kLayerWidth,kLayerWidth,Blood{});
        std::fill_n(written.begin()+row*kLayerWidth,kLayerWidth,0u);if(debug)std::fill_n(origin.begin()+row*kLayerWidth,kLayerWidth,Origin{});
    }
    void MarkCleared(size_t index){if(Enabled())cleared[(index>>17)&1]=true;}
    // A page taken from VRAM: its arcade columns (and, unless centre_only, the margins, which then hold no draw: masked).
    // After the page clear every pixel keeps the clear's serial (it wrote them all).
    void PlainPage(unsigned p,const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood,bool centre_only=false){
        const int first=centre_only?kWideMargin:0,last=centre_only?kWideMargin+kVisible:kLayerWidth;
        const bool stains=!blood.empty(),arcade=arcade_blood.size()==vram.size(),fresh=cleared[p]&&!centre_only;
        for(size_t row=size_t(p)*256;row<size_t(p)*256+256;++row){   // plain pointers: the stores cannot move the layers
            uint16_t* to=pens.data()+row*kLayerWidth;uint8_t* marks=fixed.data()+row*kLayerWidth;
            Blood* stain=stains?blood.data()+row*kLayerWidth:nullptr;
            const uint16_t* from=vram.data()+row*512;const Blood* arcade_stain=arcade?arcade_blood.data()+row*512:nullptr;
            for(int L=first;L<last;++L){const bool past=PastVram(L);const size_t v=past?0:size_t(L-kExtra);
                to[L]=past?clear_pen[row]:from[v];marks[L]=0;if(stain)stain[L]=arcade_stain&&!past?arcade_stain[v]:Blood{};
                if(!fresh){written[row*kLayerWidth+size_t(L)]=0;if(debug)origin[row*kLayerWidth+size_t(L)]={};}}
        }
    }
    // The frame's build starts on its page: from VRAM (the margins too after a page clear; a page not cleared since its
    // last build keeps its margins: the game draws over what the page holds).
    void StartFrame(unsigned page_row,const std::vector<uint16_t>& vram,const std::vector<Blood>& arcade_blood){
        page=(page_row>>8)&1;
        PlainPage(page,vram,arcade_blood,!cleared[page]);
        cleared[page]=false;booked.fill(false);page_start[page]=serial;bands.clear();page_shift[page]=shift=0;page_whole[page]=whole=false;scene=false;arena=wider;wider=false;
        ++builds;if(debug){notes_done.swap(notes);notes.clear();placed_done.swap(placed);placed.clear();}
    }
    // The frame ends (the next display interrupt): the margins without a scenery layer's art are masked, and so is a margin
    // pixel the frame did not write on a line it rewrote across the arcade's 400 columns (the game redraws that line whole:
    // what the margin kept from an earlier frame, a fighter's old pose there, is no longer in the scene).
    // After kIdle display interrupts in a row with no build, and something written since the first of them (a slow build's
    // last draws come before it), the game is showing a picture drawn without its display walk (straight to the page,
    // over what a build left there): the pages hold no build's window any more, and their sides are shown soft.
    static constexpr unsigned kIdle=3;
    unsigned ended=0,idle=0;uint32_t idle_serial=0;bool released=false;   // builds at the last interrupt; interrupts without one; the serial at the first
    void EndFrame(){
        if(!Enabled())return;
        if(builds!=ended){ended=builds;idle=0;released=false;}
        else if(!idle++)idle_serial=serial;
        else if(idle>=kIdle&&serial!=idle_serial&&!released){
            released=true;page_shift={};page_whole={};page_soft={true,true};shift=0;whole=fight=arena=wider=false;
        }
        if(released)return;
        MaskBands();
        const uint32_t start=page_start[page];
        for(size_t row=size_t(page)*256;row<size_t(page)*256+256;++row){
            const size_t base=row*kLayerWidth;bool full=true;
            for(int L=kWideMargin;L<kWideMargin+kVisible&&full;++L)full=written[base+size_t(L)]>start;
            if(full)for(int L=0;L<kLayerWidth;++L)if(!Arcade(L)&&written[base+size_t(L)]<=start)fixed[base+size_t(L)]|=kMask;
        }
        // Filled: every margin pixel of the page's visible lines is shown and is art (drawn since the page's last clear) or
        // the colour its arcade line ends in (black beside black, a sky beside its sky).
        bool filled=true;
        for(size_t row=size_t(page)*256;row<size_t(page)*256+254&&filled;++row){
            const size_t base=row*kLayerWidth;
            for(int L=0;L<kLayerWidth&&filled;++L){
                if(Arcade(L))continue;
                const size_t at=base+size_t(L),edge=base+size_t(L<kWideMargin?kWideMargin:kWideMargin+kVisible-1);
                filled=Shown(at)&&(written[at]>page_cleared_at[page]||pens[at]==pens[edge]);
            }
        }
        page_soft[page]=!fight&&!scene&&!filled;
    }
    // Save-state fields (W5): the layer and the pages' facts.
    template<class A> void LayerFields(A& a){a(pens,blood,fixed,written,serial,page_start,cleared,page,bands,clear_pen,booked,rom_palette,shift,page_shift,held,limits,ratio,ratio_limits,whole,page_whole,bound,span,fight,scene,page_soft,page_cleared_at,arena,wider,released);}
    void Reset(){*this=Layer{};}
};
}
