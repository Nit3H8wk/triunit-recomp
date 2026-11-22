#pragma once
#include "mk2_video.hpp"
#include "../include/mk5_stage_bicubic.hpp"
#include <bitset>

namespace mk2 {
class Scanout {
    unsigned width_=0,height_=0,rows_=0;
    uint64_t frames_=0;
    bool collecting_=false;
    bool remastered_;
    bool scenery_visible_=false;
    bool fighter_capture_started_=false;
    std::bitset<289> display_enabled_;
    std::vector<uint32_t> work_,complete_;
    std::vector<uint32_t> blood_work_,presentation_;
    std::vector<size_t> blood_cover_;
    // The floor of this frame's stains (mk5_blood_shade.hpp): their first covered pens through each line's palette,
    // against their references; stains dim with it at the frame's end (palette fades), never brighten. fighter_blood_: pixels
    // whose actor underlay is a covered stain.
    mk5blood::Shade shade_,frame_shade_;
    std::vector<size_t> fighter_blood_;
    std::vector<uint32_t> backdrop_work_,backdrop_;
    mk5presentation::FighterCapture fighter_work_;
    mk5presentation::FighterFrame fighters_;
    // Widescreen: every VRAM column of each line, the visible ones at the centre, from the shadow pass's wide layer when it
    // runs (BootVideo::EnableWide). Raw colours of the original scanout.
    bool wide_on_=false;std::vector<uint32_t> wide_work_,wide_;uint64_t wide_added_work_=0,wide_added_=0,wide_centre_work_=0,wide_centre_=0;int wide_shift_work_=0,wide_shift_=0;unsigned wide_fitted_work_=0,wide_fitted_=0;
    // Widescreen presentation (Remastered, W3): each wide pixel's arcade column, where its pen is the arcade's own at that
    // column (the world's x = L-56+d; a pixel of a screen-fixed draw, the layer's fixed mark, the HUD's x = L-56), so the
    // Remastered layers of that column apply; kRaw where
    // only the shadow pass has it (margins, fitted planes): its raw colour, as scenery; kBlank on a blanked line.
    static constexpr int16_t kRaw=-1,kBlank=-2;
    bool wide_present_=false;std::vector<int16_t> wide_source_work_,wide_source_;
    std::vector<uint32_t> wide_blood_work_,wide_blood_;   // the floor stain on a kRaw pixel (0: none), dimmed as the frame's
    std::vector<uint32_t> wide_presentation_,wide_backdrop_;mk5presentation::FighterFrame wide_fighters_;
    void ComposeWide(){
        const size_t n=size_t(kWideWidth)*height_;const int move=int(kWideWidth-width_)/2-wide_shift_;
        const bool backdrop=!backdrop_.empty(),fighters=fighters_.serial!=0,fighter_backdrop=fighters&&!fighters_.backdrop.empty();
        // Every pixel of each layer is written below: sized, not cleared.
        wide_presentation_.resize(n);wide_backdrop_.resize(backdrop?n:0);
        auto& f=wide_fighters_;f.serial=fighters_.serial;f.layers.clear();
        f.underlay.resize(fighters?n:0);f.backdrop.resize(fighter_backdrop?n:0);f.opaque_order.resize(fighters?n:0);f.covered.resize(fighters?n:0);
        // Plain pointers: the loop's stores cannot move the layers.
        const int16_t* sources=wide_source_.data();const uint32_t *raws=wide_.data(),*bloods=wide_blood_.data(),*shown_from=presentation_.data(),
            *backdrop_from=backdrop_.data(),*underlay_from=fighters_.underlay.data(),*fighter_backdrop_from=fighters_.backdrop.data();
        const uint64_t* order_from=fighters_.opaque_order.data();const uint8_t* covered_from=fighters_.covered.data();
        uint32_t *shown_to=wide_presentation_.data(),*backdrop_to=wide_backdrop_.data(),*underlay_to=f.underlay.data(),*fighter_backdrop_to=f.backdrop.data();
        uint64_t* order_to=f.opaque_order.data();uint8_t* covered_to=f.covered.data();
        for(size_t i=0,y=0;y<height_;++y)for(size_t x=0,line=y*width_;x<kWideWidth;++x,++i){   // line: the arcade frame's
            const int source=sources[i];const uint32_t raw=raws[i];
            if(source>=0){
                const size_t a=line+size_t(source);
                shown_to[i]=shown_from[a];if(backdrop)backdrop_to[i]=backdrop_from[a];
                if(fighters){underlay_to[i]=underlay_from[a];order_to[i]=order_from[a];covered_to[i]=covered_from[a];
                    if(fighter_backdrop)fighter_backdrop_to[i]=fighter_backdrop_from[a];}
                continue;
            }
            const uint32_t blood=bloods[i]?frame_shade_.Apply(bloods[i]):0,shown=blood?blood:raw;
            const uint32_t scenery=source==kRaw&&!blood?(raw&0xffffff)|mk5stage::scenery:0;
            shown_to[i]=shown;if(backdrop)backdrop_to[i]=scenery;
            if(fighters){underlay_to[i]=shown&0xffffff;order_to[i]=UINT64_MAX;covered_to[i]=0;if(fighter_backdrop)fighter_backdrop_to[i]=scenery;}
        }
        if(fighters)for(auto layer:fighters_.layers){layer.x+=move;f.layers.push_back(std::move(layer));}   // the fighters are world
    }
    // Save-state value fields; remastered_ is the edition, checked by the file header.
    template<class A> friend void Fields(A& a,Scanout& s){
        auto enabled=s.display_enabled_.to_string();
        a(s.width_,s.height_,s.rows_,s.frames_,s.collecting_,s.scenery_visible_,s.fighter_capture_started_,enabled,
          s.work_,s.complete_,s.blood_work_,s.presentation_,s.blood_cover_,s.backdrop_work_,s.backdrop_,
          s.fighter_work_,s.fighters_,s.shade_,s.frame_shade_,s.fighter_blood_);
        if constexpr(A::reading)s.display_enabled_=std::bitset<289>(enabled);
        s.WideFields(a);
    }
    // Widescreen state (W4), kept when the session captures the wide layer (as BootVideo::WideFields): the composed frame
    // is not state, ComposeWide makes it again from the rest.
    template<class A> void WideFields(A& a){
        const bool enabled=wide_on_;bool present=enabled;a(present);
        if(present)a(wide_work_,wide_,wide_added_work_,wide_added_,wide_centre_work_,wide_centre_,wide_shift_work_,wide_shift_,
                     wide_fitted_work_,wide_fitted_,wide_source_work_,wide_source_,wide_blood_work_,wide_blood_);
        if constexpr(A::reading){
            const size_t n=size_t(kWideWidth)*height_;
            if(!enabled){wide_work_.clear();wide_.clear();wide_source_work_.clear();wide_source_.clear();wide_blood_work_.clear();wide_blood_.clear();}
            else if(!present){   // a state saved without widescreen: blank wide frames until the next one completes
                wide_work_.assign(n,0xff000000);wide_=wide_work_;wide_shift_work_=wide_shift_=0;wide_fitted_work_=wide_fitted_=0;
                wide_added_work_=wide_added_=wide_centre_work_=wide_centre_=0;
                if(wide_present_){wide_source_work_.assign(n,kBlank);wide_source_=wide_source_work_;wide_blood_work_.assign(n,0);wide_blood_=wide_blood_work_;}
            }
            if(wide_present_&&wide_.size()==n&&wide_source_.size()==n&&wide_blood_.size()==n&&presentation_.size()==size_t(width_)*height_)ComposeWide();
        }
    }
public:
    explicit Scanout(bool remastered=false):remastered_(remastered){}
    bool remastered() const { return remastered_; }
    unsigned width() const { return width_; }
    unsigned height() const { return height_; }
    uint64_t frames() const { return frames_; }
    const std::vector<uint32_t>& pixels() const { return complete_; }
    const std::vector<uint32_t>& presentation() const { return remastered_?presentation_:complete_; }
    const std::vector<uint32_t>& backdrop_pixels() const { return backdrop_; }
    const mk5presentation::FighterFrame& fighter_frame() const { return fighters_; }
    const mk5blood::Shade& blood_shade() const { return frame_shade_; }   // the last complete frame's
    static constexpr unsigned kWideWidth=mk5wide::kLayerWidth;   // the 16:9 layer (mk5_wide.hpp)
    void EnableWide(){wide_on_=true;}
    const std::vector<uint32_t>& wide_pixels() const { return wide_; }   // kWideWidth x height(), the last complete frame
    int wide_shift() const { return wide_shift_; }   // its window offset (mk2::wide::WindowShift)
    unsigned wide_fitted() const { return wide_fitted_; }   // its planes fitted to the window (BootVideo::WidePlane); with none, the centre is exact at offset 0
    uint64_t wide_centre() const { return wide_centre_; }   // its visible pixels that differ from VRAM (0 when exact)
    uint64_t wide_added() const { return wide_added_; }   // its margin pixels the shadow drew beyond the arcade's own spill
    // Widescreen presentation (Remastered): the frame, backdrop and fighter layers over kWideWidth columns.
    void EnableWidePresentation(){wide_on_=true;wide_present_=remastered_;}
    bool wide_presentation_enabled() const { return wide_present_; }
    const std::vector<uint32_t>& wide_presentation() const { return wide_presentation_; }
    const std::vector<uint32_t>& wide_backdrop_pixels() const { return wide_backdrop_; }
    const mk5presentation::FighterFrame& wide_fighter_frame() const { return wide_fighters_; }
    // Sample live memory before DPYADR advances; never rebuild past rows from final VRAM.
    void Line(const BoardBootControls& board, const BootVideo& video) {
        const auto& io=board.io;
        if (io[1]>=io[2] || io[2]>io[3]+1 || io[5]>=io[6] || io[6]>io[7]+1 ||
            io[3]!=252 || io[7]!=288 || (io[8]&0x6000)!=0x6000 ||
            video.vram.size()!=524288 || video.palette_ram.size()!=32768)
            throw std::runtime_error("MK2 scanout outside supported T-unit geometry or memory");
        const unsigned width=2u*(io[2]-io[1]),height=io[6]-io[5];
        if (width_ && (width_!=width || height_!=height))
            throw std::runtime_error("MK2 scanout geometry changed during collection");
        if (!width_) {
            width_=width;height_=height;work_.resize(size_t(width)*height);
            if(remastered_)blood_work_.resize(work_.size());
            if(wide_on_)wide_work_.resize(size_t(kWideWidth)*height);
            if(wide_present_){wide_source_work_.resize(size_t(kWideWidth)*height);wide_blood_work_.resize(size_t(kWideWidth)*height);}
        }
        if (board.vcount==io[6]) {
            if (collecting_ && rows_==height_) {
                complete_=work_;
                if(wide_on_){wide_=wide_work_;wide_added_=wide_added_work_;wide_centre_=wide_centre_work_;wide_shift_=wide_shift_work_;wide_fitted_=wide_fitted_work_;}
                if(remastered_){
                    for(const auto pixel:blood_cover_)blood_work_[pixel]=shade_.Apply(blood_work_[pixel]);
                    presentation_=blood_work_;
                    frame_shade_=shade_;
                }
                if(scenery_visible_)backdrop_=backdrop_work_;
                else backdrop_.clear();
                ++frames_;
                if(fighter_capture_started_){
                    fighter_work_.Complete(frames_,fighters_);
                    if(fighters_.serial)for(const auto pixel:fighter_blood_)
                        if(fighters_.covered[pixel])fighters_.underlay[pixel]=shade_.Apply(fighters_.underlay[pixel]);
                    // Persistent blood can cover actor texels retained on the page.
                    if(fighters_.serial)for(const auto pixel:blood_cover_){
                        fighters_.opaque_order[pixel]=UINT64_MAX;
                        fighters_.covered[pixel]=0;
                        fighters_.underlay[pixel]=blood_work_[pixel]&0xffffff;
                        if(!fighters_.backdrop.empty())fighters_.backdrop[pixel]&=~mk5stage::scenery;
                    }
                }
                if(wide_present_){wide_source_=wide_source_work_;wide_blood_=wide_blood_work_;ComposeWide();}
            }
            collecting_=false;return;
        }
        if (board.vcount==io[5]) {
            collecting_=true;rows_=0;scenery_visible_=false;wide_added_work_=0;wide_centre_work_=0;
            if(remastered_ && video.BackdropEnabled())backdrop_work_.resize(work_.size());
            else backdrop_work_.clear();
            fighter_capture_started_=false;
            blood_cover_.clear();fighter_blood_.clear();shade_={};
        }
        if (!collecting_ || board.vcount<io[5] || board.vcount>=io[6]) return;
        if (rows_!=unsigned(board.vcount-io[5])) { collecting_=false;return; }
        uint16_t dpy=board.display_address;
        if (!(io[8]&0x0400)) dpy^=0xfffc;
        const unsigned row=((unsigned(dpy>>4)<<9)&0x3fe00);
        const unsigned column=(((dpy&0x7c)<<4)|(io[27]&0x3fff))<<1;
        const bool enabled=(io[8]&0x8000)!=0;
        for (unsigned x=0;x<width_;++x) {
            const auto index=row+((column+x)&511);
            uint32_t rgb=0xff000000;
            if (enabled) {
                const auto color=video.palette_ram[video.vram[index]&0x7fff];
                rgb=ExpandRgb555(color);
            }
            const auto dest=size_t(rows_)*width_+x;
            work_[dest]=rgb;
            if(remastered_) {
                const auto blood=enabled?video.BloodPixel(index):0;
                blood_work_[dest]=blood?blood:work_[dest];
                if(blood){blood_cover_.push_back(dest);shade_.Cover(video.BloodPen(index),video.BloodFloor(index),video.palette_ram.data());}
                if(!backdrop_work_.empty()) {
                    const uint16_t pen=enabled?video.BackdropPixel(index):0;
                    const bool scenery=(pen&BootVideo::backdrop_owner) && !blood;
                    const uint32_t bg=enabled?ExpandRgb555(video.palette_ram[pen&0x7fff])&0xffffff:0;
                    backdrop_work_[dest]=bg|(scenery?mk5stage::scenery:0);
                    scenery_visible_|=scenery;
                }
            }
        }
        if(wide_on_){
            const unsigned margin=(kWideWidth-width_)/2;
            const bool layer=video.WideEnabled();
            if(!rows_){wide_shift_work_=layer?video.WideShiftOfRow(row>>9):0;wide_fitted_work_=layer?video.WideFittedOfRow(row>>9):0;}
            // The wide layer when the shadow pass composes it (BootVideo::EnableWide), else VRAM itself.
            const size_t base=size_t(row>>9)*mk5wide::kLayerWidth;   // the layer's line (mk5_wide.hpp)
            const uint16_t* vram=video.vram.data()+row;const uint16_t* palette=video.palette_ram.data();
            const size_t line=size_t(rows_)*kWideWidth;uint32_t* out=wide_work_.data()+line;
            int16_t* sources=wide_present_?wide_source_work_.data()+line:nullptr;uint32_t* bloods=wide_present_?wide_blood_work_.data()+line:nullptr;
            const int shift=wide_shift_work_;uint64_t added=0,centre=0;
            // The layer's line as plain pointers (the loop's stores cannot move them).
            const uint16_t* pens=layer?video.wide.pens.data()+base:nullptr;const uint8_t* fixed_marks=layer?video.wide.fixed.data()+base:nullptr;
            const uint16_t* stains=layer&&!video.wide.blood.empty()?video.wide.blood.data()+base:nullptr;
            for(unsigned x=0;x<kWideWidth;++x){
                const uint16_t own=vram[(column+x-margin)&511];
                const uint16_t pen=layer?pens[x]:own;
                const bool side=x<margin||x>=margin+width_;
                added+=side&&pen!=own;centre+=!side&&pen!=own;
                out[x]=enabled?ExpandRgb555(palette[pen&0x7fff]):0xff000000;
                if(sources){
                    const int world=int(x)-int(margin)+shift,hud=int(x)-int(margin);
                    int16_t source=enabled?kRaw:kBlank;
                    const bool fixed=layer&&fixed_marks[x];
                    if(enabled&&!fixed&&world>=0&&world<int(width_)&&pen==vram[(column+unsigned(world))&511])source=int16_t(world);
                    else if(enabled&&(fixed||!layer)&&hud>=0&&hud<int(width_)&&pen==own)source=int16_t(hud);
                    sources[x]=source;
                    bloods[x]=source==kRaw&&stains&&stains[x]?ExpandRgb555(stains[x]):0;
                }
            }
            wide_added_work_+=added;wide_centre_work_+=centre;
        }
        if(remastered_ && video.FightersEnabled()){
            if(video.FighterVideo().enabled()){
                const auto sample=[&](const auto& surface,unsigned y,size_t base,unsigned x,bool on){
                    const auto start=size_t(y)*width_;
                    fighter_work_.Line(surface,y,base,x,blood_work_.data()+start,
                                       backdrop_work_.empty()?nullptr:backdrop_work_.data()+start,
                                       [&video](uint16_t pen){return ExpandRgb555(video.palette_ram[pen]);},on);
                };
                if(!fighter_capture_started_){
                    fighter_work_.Begin(width_,height_);
                    if(rows_){
                        // Earlier scanlines had no actor writes. Reuse their sampled colors and blanking.
                        static const mk5presentation::FighterSurface empty_line(512);
                        for(unsigned y=0;y<rows_;++y)sample(empty_line,y,0,0,display_enabled_[y]);
                    }
                    fighter_capture_started_=true;
                }
                sample(video.FighterVideo(),rows_,row,column,enabled);
                for(unsigned x=0;x<width_;++x)
                    if(video.FighterVideo().Blood(row+((column+x)&511)))fighter_blood_.push_back(size_t(rows_)*width_+x);
            }else display_enabled_[rows_]=enabled;
        }
        ++rows_;
    }
};
}
