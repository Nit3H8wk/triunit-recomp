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
            complete=work;
            if(scenery_visible)backdrop_complete=backdrop_work;
            else backdrop_complete.clear();
            ++frames_;last_frame_quanta_=edge.at_quanta;
            if(presentation && presentation->FighterVideo().enabled()){
                fighter_work.Complete(frames_,fighter_complete);
                // The persistent blood pass can cover actor texels retained on the page.
                if(fighter_complete.serial)for(auto pixel:blood_cover){
                    fighter_complete.opaque_order[pixel]=UINT64_MAX;
                    fighter_complete.covered[pixel]=0;
                    fighter_complete.underlay[pixel]=complete[pixel];
                    if(!fighter_complete.backdrop.empty())fighter_complete.backdrop[pixel]=backdrop_work[pixel];
                }
            }
        }
        collecting=false;return;
    }
    if(edge.vcount==io[5]){
        collecting=true;rows_=0;scenery_visible=false;blood_cover.clear();
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
        if(blood)blood_cover.push_back(pixel);
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
    }
    ++rows_;
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
