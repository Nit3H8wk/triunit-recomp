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
// Where a pixel of the wide layer came from (diagnostics, Layer::debug): the kind of write and the columns its draw covers
// in layer columns as they follow one another from its x (Span): a pixel outside them got there by a wrap.
enum class Kind:uint8_t{none,real,shadow,cpu,clear,generated};
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
// A scenery layer's art in a build (Layer::Band): per line its pixels cover all of the arcade's 400 columns on, the columns
// of the margins without its art (left: [0, left), right: [right, kLayerWidth)); a side whose draws reach past the layer
// keeps all of it. first: the serial of the layer's first draw in the layer (0: not drawn yet); farther pixels are older.
struct BandRow{uint16_t row;int16_t left,right;template<class A> friend void Fields(A& a,BandRow& b){a(b.row,b.left,b.right);}};
struct Band{uint16_t layer=0;uint32_t first=0;std::vector<BandRow> rows;
    template<class A> friend void Fields(A& a,Band& b){a(b.layer,b.first,b.rows);}};
inline bool ArcadeColumn(int L){return L>=kWideMargin&&L<kWideMargin+kVisible;}
// One scenery layer's draws measured (layer registers, x in layer columns; meant: each draw's columns as the game meant
// them): render(regs, put) calls put(layer index) for each pixel the draw writes. Its lines whose arcade columns it covers
// whole, each with its art's ends in the margins (its outermost pixels on the line; a side where a draw reaches past the
// layer keeps all of its columns).
template<class Render> Band MeasureBand(uint16_t layer,const std::vector<std::array<uint16_t,18>>& draws,
                                        const std::vector<std::pair<int,int>>& meant,Render&& render){
    constexpr size_t kWords=(kVisible+63)/64;
    std::vector<uint64_t> bits(512*kWords,0);std::vector<uint16_t> covered(512,0);
    std::vector<int16_t> lo(512,int16_t(kLayerWidth)),hi(512,0);std::vector<uint8_t> reach(512,0);
    for(size_t k=0;k<draws.size();++k){
        const auto [first,last]=Rows(draws[k]);
        const uint8_t past=uint8_t((meant[k].first<0?1:0)|(meant[k].second>kLayerWidth?2:0));
        if(past)for(int y=std::max(first,0);y<std::min(last,512);++y)reach[size_t(y)]|=past;
        render(draws[k],[&](size_t index){
            const size_t row=index/kLayerWidth;if(row>=512)return;const int c=int(index%kLayerWidth);
            lo[row]=std::min(lo[row],int16_t(c));hi[row]=std::max(hi[row],int16_t(c+1));
            if(!ArcadeColumn(c))return;
            uint64_t& word=bits[row*kWords+size_t(c-kWideMargin)/64];const uint64_t bit=uint64_t(1)<<((c-kWideMargin)%64);
            if(!(word&bit)){word|=bit;++covered[row];}
        });
    }
    Band band;band.layer=layer;
    for(uint16_t y=0;y<512;++y)if(covered[y]==kVisible){
        const int16_t left=(reach[y]&1)?int16_t(0):lo[y],right=(reach[y]&2)?int16_t(kLayerWidth):hi[y];
        if(left>0||right<kLayerWidth)band.rows.push_back({y,left,right});
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
    void Draw(Kind kind,int lo,int hi,int layer=-1){
        if(!++serial)serial=1;
        drawing={int16_t(std::clamp(lo,-32768,32767)),int16_t(std::clamp(hi,-32768,32767)),kind,uint8_t(page)};
        if(layer>=0)for(auto& b:bands)if(b.layer==layer&&!b.first)b.first=serial;
    }
    void Stamp(size_t index){written[index]=serial;if(debug)origin[index]=drawing;}
    // Scenery layers measured this build (MeasureBand); applied when the frame ends (MaskBands).
    std::vector<Band> bands;
    std::vector<Note> notes,notes_done;   // debug: this build's scenery draws, and the last finished build's
    std::vector<Band> bands_done;unsigned builds=0;   // debug: the last frame's measured layers; builds started
    // A margin pixel of a band's line without the band's art shows black when it is older than the band's first draw (the
    // page clear's pen or a farther layer: what the band would cover); a nearer one (a fighter, a projectile) stays.
    void MaskBands(){
        for(const auto& b:bands)if(b.first)for(const auto& r:b.rows){
            const size_t row=size_t(r.row)*kLayerWidth;
            const auto mask=[&](int from,int to){for(int L=std::max(from,0);L<std::min(to,kLayerWidth);++L)
                if(!Arcade(L)&&written[row+size_t(L)]<b.first)fixed[row+size_t(L)]|=kMask;};
            mask(0,r.left);mask(r.right,kLayerWidth);
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
    // columns past the VRAM line included, in the line's pen.
    void Mirror(const std::vector<uint16_t>& vram,size_t start,size_t count){
        if(!Enabled())return;
        if(!(start&511)&&count&&!(count&511)){
            Draw(Kind::clear,0,kLayerWidth);
            for(size_t row=start>>9;row<(start+count)>>9;++row){
                clear_pen[row]=vram[row*512];PlainRow(row,vram);
                for(size_t L=row*kLayerWidth;L<(row+1)*kLayerWidth;++L)Stamp(L);
            }
            return;
        }
        for(size_t i=start;i<start+count;++i)if(const auto at=At(i);at>=0){
            Draw(Kind::cpu,int(at%kLayerWidth),int(at%kLayerWidth)+1);Stamp(size_t(at));
            pens[size_t(at)]=vram[i];fixed[size_t(at)]=0;if(!blood.empty())blood[size_t(at)]=Blood{};
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
        cleared[page]=false;booked.fill(false);page_start[page]=serial;bands.clear();
        ++builds;if(debug){notes_done.swap(notes);notes.clear();}
    }
    // The frame ends (the next display interrupt): the margins without a scenery layer's art are masked, and so is a margin
    // pixel the frame did not write on a line it rewrote across the arcade's 400 columns (the game redraws that line whole:
    // what the margin kept from an earlier frame, a fighter's old pose there, is no longer in the scene).
    void EndFrame(){
        if(!Enabled())return;
        MaskBands();
        const uint32_t start=page_start[page];
        for(size_t row=size_t(page)*256;row<size_t(page)*256+256;++row){
            const size_t base=row*kLayerWidth;bool full=true;
            for(int L=kWideMargin;L<kWideMargin+kVisible&&full;++L)full=written[base+size_t(L)]>start;
            if(full)for(int L=0;L<kLayerWidth;++L)if(!Arcade(L)&&written[base+size_t(L)]<=start)fixed[base+size_t(L)]|=kMask;
        }
    }
    // Save-state fields (W5): the layer and the pages' facts.
    template<class A> void LayerFields(A& a){a(pens,blood,fixed,written,serial,page_start,cleared,page,bands,clear_pen,booked,rom_palette);}
    void Reset(){*this=Layer{};}
};
}
