#pragma once
#include <array>
#include <cstdint>
#include <utility>

// Read handlers from the pinned MK1 T-Unit main_adpcm_map + init_mktunit,
// and the TMS34010 internal register map (MAME 4f9dcc832cc0089de2451696320f671e87da79f4).
// Write-only windows deliberately have no read handler. A field touching any
// mapped read range stays with that range's existing implementation/barrier.
// This classifies original bus holes; it never repairs a pointer or game state.
constexpr bool Mk5ReadIsUnmapped(uint32_t address,unsigned width){
    if(width<1 || width>32)return false;
    const uint64_t begin=address,end=begin+width;
    if(end>0x100000000ull)return false;
    constexpr std::array<std::pair<uint64_t,uint64_t>,13> mapped{{
        {0x00000000ull,0x00400000ull}, // VRAM
        {0x01000000ull,0x01400000ull}, // work RAM
        {0x01400000ull,0x01420000ull}, // CMOS
        {0x01600000ull,0x01600040ull}, // IN0/IN1/IN2/DSW
        {0x01800000ull,0x01880000ull}, // palette RAM
        {0x01a80000ull,0x01a80100ull}, // DMA
        {0x01b00000ull,0x01b70000ull}, // MK protection overlay
        {0x01d00000ull,0x01d00020ull}, // sound status
        {0x01d01020ull,0x01d01040ull}, // sound data
        {0x02000000ull,0x08000000ull}, // banked graphics
        {0x1f800000ull,0x20000000ull}, // program mirror
        {0xc0000000ull,0xc0000200ull}, // TMS34010 internal registers
        {0xff800000ull,0x100000000ull} // program ROM / vectors
    }};
    for(const auto& range:mapped)if(begin<range.second && end>range.first)return false;
    return true;
}
