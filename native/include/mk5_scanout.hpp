#pragma once
#include "mk5_irq.hpp"
#include "mk5_fighter_video.hpp"
#include "mk5_blood_shade.hpp"
#include "mk5_wide.hpp"
#include <filesystem>
class Mk5LiveVideo;
// RGB is sampled from live VRAM/palette at each raster edge, before DPYADR
// advances. CPU instructions remain atomic at the fixed model's granularity.
class Mk5Scanout {
    Mk5IrqController& irq;const Mk5MemoryBuffers& memory;
    const Mk5LiveVideo* presentation;
    unsigned width_=0,height_=0,rows_=0;uint64_t frames_=0,last_frame_quanta_=0;
    bool collecting=false;
    bool scenery_visible=false;
    std::vector<uint32_t> work,complete;
    std::vector<uint32_t> backdrop_work,backdrop_complete;
    std::vector<unsigned> blood_cover;
    // The floor of this frame's stains (mk5_blood_shade.hpp): their first covered pens through each line's palette,
    // against their references; the stains dim with it at the frame's end (palette fades), never brighten. fighter_blood:
    // pixels whose actor underlay is a covered stain.
    mk5blood::Shade blood_shade,frame_shade;
    std::vector<unsigned> fighter_blood;
    mk5presentation::FighterCapture fighter_work;
    mk5presentation::FighterFrame fighter_complete;
    // Widescreen: every VRAM column of each line, the visible ones at the centre, from the shadow pass's wide layer
    // (Mk5LiveVideo::EnableWide) or VRAM itself; raw colours. Per frame: its window offset, its fitted planes and its visible
    // pixels that differ from VRAM (0 when exact).
    const Mk5LiveVideo* wide_video=nullptr;
    std::vector<uint32_t> wide_work,wide_complete;
    uint64_t wide_centre_work=0,wide_centre_=0;int wide_shift_work=0,wide_shift_=0;unsigned wide_fitted_work=0,wide_fitted_=0;
    // Widescreen presentation (Remastered): each wide pixel's arcade column, where its pen is the arcade's own at that column
    // (the world's x = L-56+d; a pixel of a screen-fixed draw, the HUD's x = L-56), so the Remastered layers of that column
    // apply; kRaw where only the shadow pass has it (margins, fitted planes): its raw colour, as scenery, with the wide floor
    // stain; kBlank on a blanked line. The composed frame is not state: ComposeWide makes it from the rest.
    static constexpr int16_t kRaw=-1,kBlank=-2;
    bool wide_present=false;
    std::vector<int16_t> wide_source_work,wide_source;
    std::vector<uint32_t> wide_blood_work,wide_blood;
    // Composed when first asked for (wide_stale), so a frame nobody presents (run-ahead's held real frame, a run-ahead
    // snapshot's load) is never composed.
    mutable std::vector<uint32_t> wide_presentation_,wide_backdrop_;mutable mk5presentation::FighterFrame wide_fighters_;
    mutable bool wide_stale=false;
    void wide_line(unsigned row,unsigned col,bool enabled);
    void ComposeWide()const;
    void Composed()const{if(wide_stale){wide_stale=false;ComposeWide();}}
    void line(const Mk5ScanlineEvent&,const std::array<uint16_t,32>&);
    template<class A> friend void Fields(A& a,Mk5Scanout& s){   // save states, the partial frame included
        a(s.width_,s.height_,s.rows_,s.frames_,s.last_frame_quanta_,s.collecting,s.scenery_visible,s.work,s.complete,
          s.backdrop_work,s.backdrop_complete,s.blood_cover,s.fighter_work,s.fighter_complete,s.blood_shade,s.frame_shade,
          s.fighter_blood);
        s.WideFields(a);
    }
    // Widescreen state (W4) with a presence mark, kept when the session captures the wide layer: a session without it drops
    // a file's; one with it that loads a state without it starts from blank wide frames until the next one completes.
    template<class A> void WideFields(A& a){
        const bool enabled=wide_video!=nullptr;bool present=enabled;a(present);
        if(present)a(wide_work,wide_complete,wide_centre_work,wide_centre_,wide_shift_work,wide_shift_,wide_fitted_work,wide_fitted_,
                     wide_source_work,wide_source,wide_blood_work,wide_blood);
        if constexpr(A::reading){
            const size_t n=size_t(kWideWidth)*height_;
            if(!enabled){wide_work.clear();wide_complete.clear();wide_source_work.clear();wide_source.clear();wide_blood_work.clear();wide_blood.clear();}
            else if(!present){
                wide_work.assign(n,0);wide_complete=wide_work;wide_shift_work=wide_shift_=0;wide_fitted_work=wide_fitted_=0;
                wide_centre_work=wide_centre_=0;
                if(wide_present){wide_source_work.assign(n,kBlank);wide_source=wide_source_work;wide_blood_work.assign(n,0);wide_blood=wide_blood_work;}
            }
            wide_stale=wide_present && wide_complete.size()==n && wide_source.size()==n && wide_blood.size()==n &&
                       complete.size()==size_t(width_)*height_;
        }
    }
public:
    Mk5Scanout(Mk5IrqController&,const Mk5MemoryBuffers&,const Mk5LiveVideo* presentation=nullptr);
    ~Mk5Scanout(){irq.ClearScanlineObserver();}
    Mk5Scanout(const Mk5Scanout&)=delete;
    Mk5Scanout& operator=(const Mk5Scanout&)=delete;
    unsigned width()const{return width_;}unsigned height()const{return height_;}
    bool Remastered()const{return presentation!=nullptr;}
    uint64_t frames()const{return frames_;}uint64_t last_frame_quanta()const{return last_frame_quanta_;}
    const std::vector<uint32_t>& pixels()const{return complete;}
    const std::vector<uint32_t>& backdrop_pixels()const{return backdrop_complete;}
    const mk5presentation::FighterFrame& fighter_frame()const{return fighter_complete;}
    const mk5blood::Shade& blood_frame_shade()const{return frame_shade;}   // the last complete frame's
    static constexpr unsigned kWideWidth=mk5wide::kLayerWidth;   // the 16:9 layer (mk5_wide.hpp)
    void EnableWide(const Mk5LiveVideo& video){wide_video=&video;}
    const std::vector<uint32_t>& wide_pixels()const{return wide_complete;}   // kWideWidth x height(), the last complete frame
    int wide_shift()const{return wide_shift_;}   // its window offset (0: the window stays centred)
    unsigned wide_fitted()const{return wide_fitted_;}   // its far planes fitted to the window: with none, the centre is exact
    uint64_t wide_centre()const{return wide_centre_;}
    // Widescreen presentation (Remastered, from the attached video): the frame, backdrop and fighter layers over kWideWidth.
    void EnableWidePresentation(const Mk5LiveVideo& video){wide_video=&video;wide_present=presentation!=nullptr;}
    bool wide_presentation_enabled()const{return wide_present;}
    const std::vector<uint32_t>& wide_presentation()const{Composed();return wide_presentation_;}
    const std::vector<uint32_t>& wide_backdrop_pixels()const{Composed();return wide_backdrop_;}
    const mk5presentation::FighterFrame& wide_fighter_frame()const{Composed();return wide_fighters_;}
    void SavePpm(const std::filesystem::path&)const;
};
