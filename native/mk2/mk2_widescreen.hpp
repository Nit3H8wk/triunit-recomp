#pragma once
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
// RAM: the clip longs (top-left, bottom-right as y<<16|x) and the page origin long (its high word: the page's first row).
constexpr uint32_t kClipTopLeft=0x01060150,kClipBottomRight=0x01060170,kPageOrigin=0x0105d050;
constexpr uint32_t kArcadeBottomRight=0x00fe0190;   // x 400
constexpr int kMargin=56;   // VRAM columns beyond each side of the 400 visible ones
// Each list's camera: at kCameraLoad A13 holds the address of the variable the walk reads as the list's camera. Lists whose
// camera is a world or parallax scroll (kScrollFirst..kScrollLast) are scenery; any other camera is screen-fixed (HUD).
constexpr uint32_t kCameraLoad=0xff804fc0,kScrollFirst=0x0105d260,kScrollLast=0x0105d370;
// The window offset: the camera x word (WORLDTLX) and the arena's camera limits (words), read in the fight modes (mode
// word, bit per value: 2, 6, 7; modes 3 and 5 hold, see kHoldModes and mk2_task_batch.cpp). Limits wider than
// kWorldMax (a finisher frees the camera) keep the arena's last limits.
constexpr uint32_t kCameraX=0x0105d350,kCameraMin=0x0105ecf0,kCameraMax=0x0105ed00,kMode=0x010601d0;
constexpr unsigned kFightModes=0xc4;
// Modes that keep the last fight frame's offset while the camera stays: 3 (the finisher's scene) and 5 (the round's end).
constexpr unsigned kHoldModes=(1u<<3)|(1u<<5);
constexpr int kWorldMax=4096;
// Screen pixels the wide window moves right (+) or left (-) from centred, so that it never shows beyond the arena's
// world: its art ends where the arcade screen stands at each camera limit (the camera can pass a limit by a few pixels:
// it counts as at the limit). 0 outside a fight or with unusable limits.
inline int WindowShift(unsigned mode,int camera,int minimum,int maximum){
    if(mode>15||!(kFightModes>>mode&1)||minimum>maximum)return 0;
    camera=camera<minimum?minimum:camera>maximum?maximum:camera;
    const int left=camera-minimum,right=maximum-camera;
    if(left<kMargin&&right<kMargin)return 0;   // an arena narrower than the wide screen: centred
    return left<kMargin?kMargin-left:right<kMargin?right-kMargin:0;
}
// The shadow's clip for a window shift (y<<16|x): screen x -56+d .. 456+d.
constexpr uint32_t WideTopLeft(int d){return uint32_t(uint16_t(int16_t(d-kMargin)));}
constexpr uint32_t WideBottomRight(int d){return (kArcadeBottomRight&0xffff0000u)|uint16_t(int16_t(400+kMargin+d));}
}
