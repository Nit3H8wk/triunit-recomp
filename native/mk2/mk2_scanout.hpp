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
    // runs (BootVideo::EnableWide). Raw colours of the original scanout, a debug view; not in save states (shortcut: the first frame after a load mixes both, until W4 carries it).
    bool wide_on_=false;std::vector<uint32_t> wide_work_,wide_;uint64_t wide_added_work_=0,wide_added_=0,wide_centre_work_=0,wide_centre_=0;int wide_shift_work_=0,wide_shift_=0;unsigned wide_fitted_work_=0,wide_fitted_=0;
    // Save-state value fields; remastered_ is the edition, checked by the file header.
    template<class A> friend void Fields(A& a,Scanout& s){
        auto enabled=s.display_enabled_.to_string();
        a(s.width_,s.height_,s.rows_,s.frames_,s.collecting_,s.scenery_visible_,s.fighter_capture_started_,enabled,
          s.work_,s.complete_,s.blood_work_,s.presentation_,s.blood_cover_,s.backdrop_work_,s.backdrop_,
          s.fighter_work_,s.fighters_,s.shade_,s.frame_shade_,s.fighter_blood_);
        if constexpr(A::reading)s.display_enabled_=std::bitset<289>(enabled);
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
    static constexpr unsigned kWideWidth=512;   // a VRAM line
    void EnableWide(){wide_on_=true;}
    const std::vector<uint32_t>& wide_pixels() const { return wide_; }   // kWideWidth x height(), the last complete frame
    int wide_shift() const { return wide_shift_; }   // its window offset (mk2::wide::WindowShift)
    unsigned wide_fitted() const { return wide_fitted_; }   // its planes fitted to the window (BootVideo::WidePlane); with none, the centre is exact at offset 0
    uint64_t wide_centre() const { return wide_centre_; }   // its visible pixels that differ from VRAM (0 when exact)
    uint64_t wide_added() const { return wide_added_; }   // its margin pixels the shadow drew beyond the arcade's own spill
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
            if(!rows_){wide_shift_work_=video.WideEnabled()?video.WideShiftOfRow(row>>9):0;wide_fitted_work_=video.WideEnabled()?video.WideFittedOfRow(row>>9):0;}
            // The wide layer when the shadow pass composes it (BootVideo::EnableWide), else VRAM itself.
            for(unsigned x=0;x<kWideWidth;++x){
                const auto index=row+((column+x-margin)&511);
                const uint16_t pen=video.WideEnabled()?video.WidePixel(index):video.vram[index];
                const bool side=x<margin||x>=margin+width_;
                wide_added_work_+=side&&pen!=video.vram[index];wide_centre_work_+=!side&&pen!=video.vram[index];
                wide_work_[size_t(rows_)*kWideWidth+x]=enabled?ExpandRgb555(video.palette_ram[pen&0x7fff]):0xff000000;
            }
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
