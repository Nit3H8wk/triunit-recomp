#pragma once
#include "mk5_irq.hpp"
#include "mk5_fighter_video.hpp"
#include "mk5_blood_shade.hpp"
#include <array>
#include <map>
#include <tuple>

struct VerifiedMk5GlyphBank {std::vector<uint8_t> bytes,graphics;};
VerifiedMk5GlyphBank LoadMk5GlyphBank(const std::filesystem::path&);
struct Mk5DmaCommand {uint32_t pc;uint64_t start_ns,due_ns;std::array<uint16_t,18> registers;};
// Bounded MK1 non-stream DMA, fixed-point scale, up to 1048576 output samples.
// Draws at command issue, busy/IRQ completes at 41ns/pixel, as pinned driver.
class Mk5LiveVideo {
    Mk5MemoryBuffers& m;Mk5IrqController& irq;BootDiState& di;
    const ResetTrace& cpu;
    std::vector<uint8_t> gfx;std::array<uint16_t,18> regs{};
    uint64_t due=0;bool pending=false;
    bool data_bank=true;
    struct BloodSprite {
        uint32_t frame=0;
        int width=0,height=0;
        std::vector<uint8_t> pixels;
        std::array<uint32_t,64> colors{};
    } blood_sprite;
    // A stain per kept pose, with the floor each splash pixel first covered (mk5_blood_shade.hpp): its pen | kTaken
    // (0 = not drawn yet) and that pen's brightness then.
    struct BloodStain {
        std::vector<uint16_t> pen;std::vector<uint8_t> floor;
        template<class A> friend void Fields(A& a,BloodStain& s){a(s.pen,s.floor);}
    };
    std::map<std::tuple<int16_t,int16_t,bool>,BloodStain> blood_stains;
    std::vector<uint8_t> blood_layer;
    std::vector<uint16_t> blood_pen;    // per video RAM word under a stain: the floor of its splash pixel
    std::vector<uint8_t> blood_floor;
    std::vector<uint16_t> backdrop;
    mk5presentation::FighterSurface fighters;
    mk5presentation::FighterSlots fighter_objects;
    uint32_t held_prop=0;
    // Save states: gfx and blood_sprite come from the ROMs and stay with the live object.
    template<class A> friend void Fields(A& a,Mk5LiveVideo& v){
        a(v.regs,v.due,v.pending,v.data_bank,v.blood_stains,v.blood_layer,v.blood_pen,v.blood_floor,v.backdrop,v.fighters,v.fighter_objects,v.held_prop,
          v.commands,v.completions,v.pixels_written,v.shift_loads,v.shift_stores);
    }
    void DrawBlood(const ResetTrace&, bool arena_visible);
    bool IsBackdropMode()const;
    bool IsBackdropDma(uint32_t caller)const;
    uint32_t ObjectDrawReturn(uint32_t pc)const;
    uint64_t FighterOwner(uint32_t caller)const;
public:
    static constexpr uint16_t backdrop_owner=0x8000;
    std::vector<Mk5DmaCommand> commands;
    std::vector<uint64_t> completions;
    uint64_t pixels_written=0,shift_loads=0,shift_stores=0;
    Mk5LiveVideo(const VerifiedMk5GlyphBank&,ResetTrace&,Mk5MemoryBuffers&,Mk5IrqController&,BootDiState&,const VerifiedMk5Program* blood_program=nullptr);
    void ObserveBlood(uint32_t pc,const ResetTrace&);
    void BindFighter(uint32_t object);
    void BindHeldProp(uint32_t object);
    void FighterRamWrite(uint32_t pc,uint32_t address,uint32_t value);
    bool BackdropEnabled()const{return !backdrop.empty();}
    const mk5presentation::FighterSurface& FighterVideo()const{return fighters;}
    uint16_t BackdropPixel(size_t index)const{return backdrop[index];}
    uint32_t BloodPixel(size_t index)const {
        return blood_layer.empty()?0:blood_sprite.colors[blood_layer[index]];
    }
    // The floor of the stain word at `index` (meaningful where BloodPixel is not 0): pen | kTaken and its brightness then.
    uint16_t BloodPen(size_t index)const{return blood_pen.empty()?0:blood_pen[index];}
    uint8_t BloodFloor(size_t index)const{return blood_floor.empty()?0:blood_floor[index];}
    void Update();
    uint16_t Read(unsigned offset)const;
    void Write(uint32_t pc,unsigned offset,uint16_t value);
    uint32_t CpuRead(uint32_t bit,unsigned width)const;
    void CpuWrite(uint32_t bit,unsigned width,uint32_t value);
    void Control(uint16_t value){data_bank=(value&32)!=0;}
    uint32_t ShiftLoad(uint32_t bit);
    uint32_t FillXY(ResetTrace&);
};
