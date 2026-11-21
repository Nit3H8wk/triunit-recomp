#pragma once
#include "../include/mk5_wide.hpp"
#include <cstdint>
// Widescreen shadow pass (mk2_task_batch.cpp, BootOps::shadow): address-only facts of MK2 L3.1, recovered locally from
// the user's ROM. Bit addresses: program FF800000.., RAM 01000000..
namespace mk2::wide {
// Display table walk of the frame builder: after the queue reset, to the direct-DMA stage.
constexpr uint32_t kWalkStart=0xff804e30,kWalkEnd=0xff805050,kQueueReset=0xff808a40;
// The display interrupt's entry: each frame's build (when the game builds one) follows it.
constexpr uint32_t kDisplayIrq=0xff816370;
// The table's marker entry (B8 = A1): when the drain reaches it, the fighters' floor shadows are drawn (FF801000 by direct
// DMA, FF801590/FF801600), before the entries staged after it (the world objects).
constexpr uint32_t kMarker=0xff804f60,kDrain=0xff804630;
// The list drawer's interrupt kick (DINT, INT1 enable, DMA busy test, TRAP 1, EINT), skipped by the shadow.
constexpr uint32_t kKick=0xff804440,kKickEnd=0xff804510;
// Staging MMTMs: the list drawer (A12 A11 A10 A9 A8 A6 as r0/r1..r10/r11) and the floor producer (A9 A8 A7 A6 A3 A2).
constexpr uint32_t kDrawerStage=0xff804410,kFloorStage=0xff800490;
// Scenery streamer: entry, the return of its only call, and the object pool resets that end its planes.
constexpr uint32_t kStreamer=0xff9f8030,kStreamerReturn=0xff9f7fe0,kPoolReset[2]={0xff808990,0xff83f160};
struct Range {uint32_t from,to;};
constexpr Range kStreamerCode[]={{0xff9f8030,0xff9f8260},{0xff80af00,0xff80c600},{0xff8090b0,0xff809280},
                                 {0xff8093a0,0xff809580},{0xff809ea0,0xff809fa0},{0xff80c6b0,0xff80c7e0},{0xff80d180,0xff80d790}};
inline bool StreamerCode(uint32_t pc){for(const auto& r:kStreamerCode)if(pc>=r.from&&pc<=r.to)return true;return false;}
// The object pool's free list: its head long; each free object's first long links the next (0 ends it; FF8090D0).
constexpr uint32_t kFreeList=0x01060130;constexpr size_t kPoolObjects=4096;
// RAM: the clip longs (top-left, bottom-right as y<<16|x) and the page origin long (its high word: the page's first row).
constexpr uint32_t kClipTopLeft=0x01060150,kClipBottomRight=0x01060170,kPageOrigin=0x0105d050;
constexpr uint32_t kArcadeBottomRight=0x00fe0190;   // x 400
constexpr int kMargin=mk5wide::kMargin;   // VRAM columns beyond each side of the 400 visible ones
// Each list's camera: at kCameraLoad A13 holds the address of the variable the walk reads as the list's camera. Lists whose
// camera is a world or parallax scroll (kScrollFirst..kScrollLast) are scenery; any other camera is screen-fixed (HUD).
constexpr uint32_t kCameraLoad=0xff804fc0,kScrollFirst=0x0105d260,kScrollLast=0x0105d370;
// The walk's next table entry (MOVE *A3+,A0): the previous list or callback has ended.
constexpr uint32_t kTableNext=0xff804f10;
// The window offset: the camera x word (WORLDTLX) and the arena's camera limits (words), read in the fight modes (mode
// word, bit per value: 2, 6, 7; modes 3 and 5 hold, see kHoldModes and mk2_task_batch.cpp). Limits wider than
// kWorldMax (a finisher frees the camera) keep the arena's last limits.
constexpr uint32_t kCameraX=0x0105d350,kCameraMin=0x0105ecf0,kCameraMax=0x0105ed00,kMode=0x010601d0;
constexpr unsigned kFightModes=0xc4;
// Modes that keep the last fight frame's offset while the camera stays: 3 (the finisher's scene) and 5 (the round's end).
constexpr unsigned kHoldModes=(1u<<3)|(1u<<5);
constexpr int kWorldMax=mk5wide::kWorldMax;
inline bool Shifting(unsigned mode){return mode<16&&(kFightModes>>mode&1);}
inline bool Holding(unsigned mode){return mode<16&&(kHoldModes>>mode&1);}
// Per-plane fit (BootVideo::WidePlane): the far planes, lists whose camera is a parallax scroll below the world's (kCameraX:
// the fighting plane, fighters and floor never fit).
inline bool FitCamera(uint32_t camera){return camera>=kScrollFirst&&camera<kCameraX;}
// Each frame the scroll longs (16.16, from 0105D260; a camera word is the high word of its long) add their velocity longs,
// kVelocityGap lower (FF804B60..FF804D50); the world's velocity is kWorldVelocity. A far plane's ratio is its velocity over
// the world's, read per arena while the world camera moves. An end of a plane's art that the arcade screen itself shows at
// some camera position within the limits (within kEndSlack pixels) belongs to the arena: that plane is not fitted.
constexpr uint32_t kVelocityGap=0x130,kWorldVelocity=0x0105d220;
constexpr int kEndSlack=mk5wide::kEndSlack;
// Screen pixels the wide window moves right (+) or left (-) from centred, so that it never shows beyond the arena's
// world: its art ends where the arcade screen stands at each camera limit (the camera can pass a limit by a few pixels:
// it counts as at the limit). 0 outside a fight or with unusable limits.
inline int WindowShift(unsigned mode,int camera,int minimum,int maximum){return Shifting(mode)?mk5wide::WindowShift(camera,minimum,maximum):0;}
// The shadow's clip for a window shift (y<<16|x): screen x -56+d .. 456+d, plus kReach on each side so that the streamer
// builds, and the walk stages, the far planes' art beyond the window (the per-plane fit measures where it ends; the DMA
// clip keeps the layer's 512 columns). Its 10-bit DMA x stays within -256..767.
constexpr int kReach=mk5wide::kReach;
constexpr uint32_t WideTopLeft(int d){return uint32_t(uint16_t(int16_t(d-kMargin-kReach)));}
constexpr uint32_t WideBottomRight(int d){return (kArcadeBottomRight&0xffff0000u)|uint16_t(int16_t(400+kMargin+kReach+d));}
}
