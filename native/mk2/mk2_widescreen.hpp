#pragma once
#include <cstdint>
// Widescreen shadow pass (mk2_task_batch.cpp, BootOps::shadow): address-only facts of MK2 L3.1, recovered locally from
// the user's ROM. Bit addresses: program FF800000.., RAM 01000000..
namespace mk2::wide {
// Display table walk of the frame builder: after the queue reset, to the direct-DMA stage.
constexpr uint32_t kWalkStart=0xff804e30,kWalkEnd=0xff805050,kQueueReset=0xff808a40;
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
constexpr uint32_t kArcadeBottomRight=0x00fe0190,kWideTopLeft=0x0000ffc8,kWideBottomRight=0x00fe01c8;   // 400; -56..456
}
