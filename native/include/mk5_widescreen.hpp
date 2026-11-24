#pragma once
#include "mk5_wide.hpp"
#include <cstdint>
// Widescreen shadow pass of MK1 rev 5.0 (Mk5TaskBodyRunner shadow mode, Mk5LiveVideo wide layer): address-only facts,
// recovered locally from the user's ROM. Bit addresses: program FF800000.., RAM 01000000..
namespace mk5widescreen {
// The frame builder (called by the display interrupt after the page flip) and its display-list walk: from the page origin
// load to the direct-DMA queue (HUD), after the last list. The walk draws each list with the list drawer, which writes the
// DMA registers itself (MMTM at kDrawerDma) after its busy wait.
constexpr uint32_t kBuilder=0xffc79b90,kWalkStart=0xffc7a010,kWalkEnd=0xffc7a950;
constexpr uint32_t kDisplayIrq=0xffc98bd0;   // the display interrupt: a frame boundary
// The walk's calls of the list drawer (A0 = the list head, A4 = its camera x) and the drawer's screen-fixed test (A7 bit 0:
// the object's position is screen space, no camera).
constexpr uint32_t kListCalls[]={0xffc7a180,0xffc7a280,0xffc7a580,0xffc7a650,0xffc7a700,0xffc7a7e0,0xffc7a8e0,0xffc7a930};
constexpr uint32_t kFixedTest=0xffc79580,kDrawerDma=0xffc79b40;
struct Range {uint32_t from,to;};
constexpr Range kWalkCode[]={{0xffc79400,0xffc79b80},{0xffc7a010,0xffc7a950}};
// Scenery streamer: the process calls it every 8 frames (FFCB5EA0); it rebuilds every plane from its window (the clip
// longs +-30h), so one call fills a wider window. kStreamerReturn is that call's return, a PC the streamer never reaches.
constexpr uint32_t kStreamer=0xffcb5f10,kStreamerEnd=0xffcb60d0,kStreamerReturn=0xffcb5ec0;
constexpr Range kStreamerCode[]={{0xffc7f2f0,0xffc7f4b0},{0xffc7f9f0,0xffc7fbc0},{0xffc80550,0xffc806a0},{0xffcb5f10,0xffcb6150},
                                 {0xffce0c40,0xffce0d70},{0xffce1710,0xffce1d20},{0xffce3090,0xffce4780},{0xffdd1860,0xffdd19c0},
                                 {0xffe12e70,0xffe13840},{0xffe141e0,0xffe14290},{0xffe14a20,0xffe15040}};
// The streamer's only status restore (POPST of a PUSHST pair): the shadow pops the status itself, the IRQ controller is
// never involved.
constexpr uint32_t kStreamerPopStatus=0xffe14280;
inline bool In(const Range* r,size_t n,uint32_t pc){for(size_t i=0;i<n;++i)if(pc>=r[i].from&&pc<=r[i].to)return true;return false;}
inline bool WalkCode(uint32_t pc){return In(kWalkCode,std::size(kWalkCode),pc);}
inline bool StreamerCode(uint32_t pc){return In(kStreamerCode,std::size(kStreamerCode),pc);}
// RAM: the clip longs (top-left, bottom-right as y<<16|x) and the page origin long (its high word: the page's first row).
constexpr uint32_t kClipTopLeft=0x01008020,kClipBottomRight=0x01008040,kPageOrigin=0x01051160;
constexpr uint32_t kArcadeBottomRight=0x00fe0190;   // x 400, y 254
// Scroll longs (16.16; a camera x is the high word): the far planes from kScrollFirst every 20h, the world (the fighting
// plane, its objects and the fighters) and the front plane. Each frame each adds its velocity long, kVelocityGap lower
// (the builder, FFC79E00..FFC79FF0).
constexpr uint32_t kScrollFirst=0x0104f790,kWorldScroll=0x0104f870,kFrontScroll=0x0104f890,kVelocityGap=0x120;
// The far lists: the first (its camera the first scroll) and the parallax lists from kParallaxLists every 20h, each with the
// scroll at the same offset; the last parallax list is the world's (not a far plane). FarSlot: a list's scroll slot (-1:
// not a far plane's list).
constexpr uint32_t kFirstList=0x0104fa50,kParallaxLists=0x0104f8b0,kParallaxEnd=0x0104f9b0;
inline int FarSlot(uint32_t list){
    const uint32_t scroll=list==kFirstList?kScrollFirst:list>=kParallaxLists&&list<kParallaxEnd&&!((list-kParallaxLists)%0x20)?
                          kScrollFirst+(list-kParallaxLists):0;
    return scroll&&scroll<kWorldScroll?int((scroll-kScrollFirst)/0x20):-1;
}
constexpr unsigned kScrollSlots=(kFrontScroll-kScrollFirst)/0x20+1,kWorldSlot=(kWorldScroll-kScrollFirst)/0x20;
// The camera x word, the arena's camera limits (words; the builder's fighter walls are [min+3Ah, max+15Fh]) and the mode
// word: in the fight (2) and the round's start (6) the wide window follows the camera within the arena's limits
// (mk5wide::WindowShift); afterwards its offset stays while the camera does (mk5wide::Layer::Offset).
constexpr uint32_t kCameraX=kWorldScroll+16,kCameraMin=0x010517e0,kCameraMax=0x010517f0,kMode=0x01051190;
constexpr unsigned kShiftModes=(1u<<2)|(1u<<6);
inline bool Shifting(unsigned mode){return mode<16&&(kShiftModes>>mode&1);}
// The palette slots' table (the allocator FFCE10E0 searches kPaletteSlots entries from kPaletteTable, kPaletteEntry apart):
// each the long of the palette's ROM pointer in the slot (then its use count). A palette the shadow's streamer allocates is
// only booked in that table, which the journal undoes: its colours are not in the palette RAM.
constexpr uint32_t kPaletteTable=0x0104fc20,kPaletteEntry=0x40;constexpr unsigned kPaletteSlots=0x3c;
// The shadow's clip (y<<16|x): screen x -67 .. 467 plus mk5wide::kReach on each side.
constexpr uint32_t WideTopLeft(){return uint32_t(uint16_t(int16_t(-mk5wide::kWideMargin-mk5wide::kReach)));}
constexpr uint32_t WideBottomRight(){
    return (kArcadeBottomRight&0xffff0000u)|uint16_t(int16_t(mk5wide::kVisible+mk5wide::kWideMargin+mk5wide::kReach));}
}
