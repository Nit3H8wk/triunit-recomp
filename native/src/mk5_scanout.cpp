#include "mk5_scanout.hpp"
#include "mk5_live_video.hpp"
#include "mk5_stage_bicubic.hpp"
#include <stdexcept>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
namespace {
uint32_t expand_rgb(uint16_t color){
    auto expand=[](unsigned v){return (v<<3)|(v>>2);};
    return (expand((color>>10)&31)<<16)|(expand((color>>5)&31)<<8)|expand(color&31);
}
}
Mk5Scanout::Mk5Scanout(Mk5IrqController& controller,const Mk5MemoryBuffers& buffers,const Mk5LiveVideo* video)
    :irq(controller),memory(buffers),presentation(video){
    const auto& io=irq.io();
    if(io[1]>=io[2] || io[5]>=io[6] || io[2]>io[3]+1 || (io[8]&0x6000)!=0x6000 || memory.vram.size()!=524288 || memory.palette.size()!=32768)throw std::runtime_error("MK5 unsupported scanout geometry");
    width_=2u*(io[2]-io[1]);height_=io[6]-io[5];work.resize(width_*height_);
    if(presentation && presentation->BackdropEnabled())backdrop_work.resize(work.size());
    irq.SetScanlineObserver([this](const auto& edge,const auto& regs){line(edge,regs);});
}
void Mk5Scanout::line(const Mk5ScanlineEvent& edge,const std::array<uint16_t,32>& io){
    if(2u*(io[2]-io[1])!=width_ || unsigned(io[6]-io[5])!=height_)throw std::runtime_error("MK5 live scanout geometry changed");
    if(edge.vcount==io[6]){
        if(collecting && rows_==height_){
            for(auto pixel:blood_cover)work[pixel]=blood_shade.Apply(work[pixel]);
            frame_shade=blood_shade;
            complete=work;
            if(scenery_visible)backdrop_complete=backdrop_work;
            else backdrop_complete.clear();
            ++frames_;last_frame_quanta_=edge.at_quanta;
            if(presentation && presentation->FighterVideo().enabled()){
                fighter_work.Complete(frames_,fighter_complete);
                if(fighter_complete.serial)for(auto pixel:fighter_blood)
                    if(fighter_complete.covered[pixel])fighter_complete.underlay[pixel]=blood_shade.Apply(fighter_complete.underlay[pixel]);
                // The persistent blood pass can cover actor texels retained on the page.
                if(fighter_complete.serial)for(auto pixel:blood_cover){
                    fighter_complete.opaque_order[pixel]=UINT64_MAX;
                    fighter_complete.covered[pixel]=0;
                    fighter_complete.underlay[pixel]=complete[pixel];
                    if(!fighter_complete.backdrop.empty())fighter_complete.backdrop[pixel]=backdrop_work[pixel];
                }
            }
            if(wide_video){
                if(wide_soft_work&&wide_work.size()==size_t(kWideWidth)*height_){   // a menu's soft sides (mk5wide::SoftMargins)
                    mk5wide::SoftMargins(wide_work.data(),height_,true,[&](size_t i){if(wide_present){wide_source_work[i]=kRaw;wide_blood_work[i]=0;}});
                }
                wide_complete=wide_work;wide_centre_=wide_centre_work;wide_audit_=wide_audit_work;wide_shift_=wide_shift_work;wide_whole_=wide_whole_work;wide_soft_=wide_soft_work;
                if(wide_present){wide_source=wide_source_work;wide_blood=wide_blood_work;wide_stale=true;}
            }
        }
        collecting=false;return;
    }
    if(edge.vcount==io[5]){
        collecting=true;rows_=0;scenery_visible=false;blood_cover.clear();fighter_blood.clear();blood_shade={};wide_centre_work=0;
        if(presentation && presentation->FighterVideo().enabled())fighter_work.Begin(width_,height_);
    }
    if(!collecting || edge.vcount<io[5] || edge.vcount>=io[6])return;
    uint16_t dpy=edge.dpyadr;if(!(io[8]&0x400))dpy^=0xfffc;
    unsigned row=((unsigned(dpy>>4)<<9)&0x3fe00),col=((((dpy&0x7c)<<4)|(io[27]&0x3fff))<<1);
    const bool enabled=(io[8]&0x8000)!=0;
    for(unsigned x=0;x<width_;++x){
        const auto index=row+((col+x)&511);
        const auto pixel=rows_*width_+x;
        const uint16_t color=enabled?memory.palette.at(memory.vram.at(index)&0x7fff):0;
        const auto blood=presentation && enabled?presentation->BloodPixel(index):0;
        work.at(pixel)=blood?blood:expand_rgb(color);
        if(blood){
            blood_cover.push_back(pixel);
            blood_shade.Cover(presentation->BloodPen(index),presentation->BloodFloor(index),memory.palette.data());
        }
        if(!backdrop_work.empty()){
            const uint16_t backdrop=enabled?presentation->BackdropPixel(index):0;
            const bool scenery=(backdrop&Mk5LiveVideo::backdrop_owner) && !blood;
            backdrop_work[pixel]=enabled?expand_rgb(memory.palette[backdrop&~Mk5LiveVideo::backdrop_owner]):0;
            if(scenery)backdrop_work[pixel]|=mk5stage::scenery;
            scenery_visible|=scenery;
        }
    }
    if(presentation && presentation->FighterVideo().enabled()){
        const auto start=rows_*width_;
        fighter_work.Line(presentation->FighterVideo(),rows_,row,col,work.data()+start,
                          backdrop_work.empty()?nullptr:backdrop_work.data()+start,
                          [this](uint16_t pen){return expand_rgb(memory.palette[pen]);},enabled);
        for(unsigned x=0;x<width_;++x)
            if(presentation->FighterVideo().Blood(row+((col+x)&511)))fighter_blood.push_back(rows_*width_+x);
    }
    if(wide_video)wide_line(row,col,enabled);
    ++rows_;
}
void Mk5Scanout::wide_line(unsigned row,unsigned col,bool enabled){
    const auto& layer=wide_video->WideLayer();const unsigned margin=(kWideWidth-width_)/2;const size_t n=size_t(kWideWidth)*height_;
    if(!rows_){
        wide_work.assign(n,0);
        if(wide_present){wide_source_work.assign(n,kBlank);wide_blood_work.assign(n,0);}
        wide_audit_work={};wide_shift_work=layer.Enabled()?layer.page_shift[(row>>17)&1]:0;wide_whole_work=layer.Enabled()&&layer.page_whole[(row>>17)&1];
        wide_soft_work=layer.Enabled()&&layer.page_soft[(row>>17)&1];wide_dim_work=wide_video->WideDim();
    }
    const int shift=wide_shift_work;
    const size_t base=size_t(row>>9)*mk5wide::kLayerWidth;   // the layer's line (mk5_wide.hpp)
    for(unsigned dest_x=0;dest_x<kWideWidth;++dest_x){
        const auto index=row+((col+dest_x-margin)&511);
        const size_t dest=size_t(rows_)*kWideWidth+dest_x,at=base+dest_x;
        const uint16_t pen=layer.Enabled()?layer.pens[at]:memory.vram[index];
        const bool shown=!layer.Enabled() || layer.Shown(at);
        // The pixel's arcade column: the HUD's (screen space) or, with a window offset, the world's.
        const int hud=int(dest_x)-int(margin),world=hud+shift;
        const bool fixed=!shift || (layer.fixed[at]&mk5wide::Layer<uint8_t>::kFixed);
        const int column=fixed?hud:world;const bool arcade=column>=0 && column<int(width_);
        const bool same=arcade && pen==memory.vram[row+((col+unsigned(column))&511)];
        wide_centre_work+=arcade && !same;   // the arcade's columns against the arcade
        if(arcade && !same && layer.debug && layer.origin[at].kind==mk5wide::Kind::shadow && layer.origin[at].Covers(int(dest_x)) &&
           layer.written[at]>layer.page_start[(row>>17)&1])++wide_audit_work.filled;
        wide_work[dest]=enabled?expand_rgb(pen&0x8000?layer.Colour(at,pen,memory.palette.data(),wide_dim_work):memory.palette.at(pen&0x7fff)):0;   // Layer::Book
        if(enabled && !shown)wide_work[dest]=layer.debug && !layer.written[at]?mk5wide::kSentinel:mk5wide::kMasked;
        if(!wide_present)continue;
        const int16_t source=!enabled?kBlank:same && shown?int16_t(column):kRaw;
        wide_source_work[dest]=source;
        wide_blood_work[dest]=source==kRaw && shown && layer.Enabled()?wide_video->WideBloodPixel(at):0;
    }
    if(layer.Enabled())layer.AuditRow(wide_audit_work,row>>9);
}
// The wide frame of the Remastered layers: a pixel with an arcade column takes that column's data (colour with blood,
// backdrop, fighter order and cover); a pixel only the shadow has is its raw colour as scenery, or its floor stain dimmed
// as the frame's. The fighter layers are world: they move with the window.
void Mk5Scanout::ComposeWide()const{
    const size_t n=size_t(kWideWidth)*height_;const int move=int(kWideWidth-width_)/2-wide_shift_;
    const bool backdrop=!backdrop_complete.empty(),fighters=fighter_complete.serial!=0,fighter_backdrop=fighters && !fighter_complete.backdrop.empty();
    wide_presentation_.resize(n);wide_backdrop_.assign(backdrop?n:0,0);
    auto& f=wide_fighters_;f.serial=fighter_complete.serial;f.layers.clear();
    f.underlay.assign(fighters?n:0,0);f.backdrop.assign(fighter_backdrop?n:0,0);f.opaque_order.assign(fighters?n:0,0);f.covered.assign(fighters?n:0,0);
    for(size_t i=0;i<n;++i){
        const int source=wide_source[i];const uint32_t raw=wide_complete[i];
        if(source>=0){
            const size_t a=i/kWideWidth*width_+size_t(source);
            wide_presentation_[i]=complete[a];if(backdrop)wide_backdrop_[i]=backdrop_complete[a];
            if(fighters){f.underlay[i]=fighter_complete.underlay[a];f.opaque_order[i]=fighter_complete.opaque_order[a];f.covered[i]=fighter_complete.covered[a];
                if(fighter_backdrop)f.backdrop[i]=fighter_complete.backdrop[a];}
            continue;
        }
        const uint32_t blood=wide_blood[i]?frame_shade.Apply(wide_blood[i]):0,shown=blood?blood:raw;
        const uint32_t scenery=source==kRaw && !blood?(raw&0xffffff)|mk5stage::scenery:0;
        wide_presentation_[i]=shown;if(backdrop)wide_backdrop_[i]=scenery;
        if(fighters){f.underlay[i]=shown&0xffffff;f.opaque_order[i]=UINT64_MAX;if(fighter_backdrop)f.backdrop[i]=scenery;}
    }
    if(fighters)for(auto layer:fighter_complete.layers){layer.x+=move;f.layers.push_back(std::move(layer));}
}
void Mk5Scanout::SavePpm(const std::filesystem::path& path)const{
    if(!frames_)throw std::runtime_error("MK5 no complete scanout frame");
    std::string bytes="P6\n"+std::to_string(width_)+" "+std::to_string(height_)+"\n255\n";
    for(auto rgb:complete){bytes.push_back(char(rgb>>16));bytes.push_back(char(rgb>>8));bytes.push_back(char(rgb));}
    if(bytes.size()>MAXDWORD)throw std::runtime_error("MK5 scanout export too large");
    HANDLE file=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE)throw std::runtime_error("MK5 scanout output must be a new file");
    DWORD written=0;bool ok=WriteFile(file,bytes.data(),DWORD(bytes.size()),&written,nullptr)!=0;
    bool closed=CloseHandle(file)!=0;
    if(!ok || written!=bytes.size() || !closed){DeleteFileW(path.c_str());throw std::runtime_error("MK5 scanout export failed");}
}
