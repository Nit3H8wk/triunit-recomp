#pragma once
#include "mk5_irq.hpp"
#include "mk5_fighter_video.hpp"
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
    mk5presentation::FighterCapture fighter_work;
    mk5presentation::FighterFrame fighter_complete;
    void line(const Mk5ScanlineEvent&,const std::array<uint16_t,32>&);
public:
    Mk5Scanout(Mk5IrqController&,const Mk5MemoryBuffers&,const Mk5LiveVideo* presentation=nullptr);
    ~Mk5Scanout(){irq.ClearScanlineObserver();}
    Mk5Scanout(const Mk5Scanout&)=delete;
    Mk5Scanout& operator=(const Mk5Scanout&)=delete;
    unsigned width()const{return width_;}unsigned height()const{return height_;}
    uint64_t frames()const{return frames_;}uint64_t last_frame_quanta()const{return last_frame_quanta_;}
    const std::vector<uint32_t>& pixels()const{return complete;}
    const std::vector<uint32_t>& backdrop_pixels()const{return backdrop_complete;}
    const mk5presentation::FighterFrame& fighter_frame()const{return fighter_complete;}
    void SavePpm(const std::filesystem::path&)const;
};
