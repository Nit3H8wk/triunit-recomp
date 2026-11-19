// Remastered floor blood of MK1 (mk5_live_video.cpp) and MK2 (mk2_video.hpp) through the program's palette fades.
// The stains keep fixed colours (MK1: the ROM's splash palette; MK2: the colours of the splash's slot at the keep),
// while the fades (the screen fading to black between rounds, the arena darkening behind a finishing move) rewrite only
// the palette. Each stain pixel keeps the pen of the video RAM word it first covered (bit 15 set) and that pen's
// brightness then (Sum, through the palette of that draw); the scanout adds, for every stain pixel shown, the
// brightness of that same pen through the palette of its line (Cover), and dims every stain of the frame by now / then,
// never above 1. Without a palette change the ratio is 1 and the colours are the kept ones, exactly, whatever the
// program draws under the stain later (fighter shadows: MK1 draws them before the blood pass); the read-only probes of
// 19/11/2026 showed that measuring the pens under the stain each frame dims them in plain fighting.
#pragma once
#include <cstdint>

namespace mk5blood {
inline unsigned Sum(uint16_t c) { return (c >> 10 & 31) + (c >> 5 & 31) + (c & 31); }
// A stain colour once its floor went from brightness `then` to `now` (Sums).
inline uint16_t Dim(uint16_t c, uint64_t now, uint64_t then) {
    if (now >= then) return c;
    const auto ch = [&](unsigned v) { return uint16_t((v * now + then / 2) / then); };
    return uint16_t(ch(c >> 10 & 31) << 10 | ch(c >> 5 & 31) << 5 | ch(c & 31));
}
// The same on a colour expanded from RGB555 as (v << 3) | (v >> 2), the bits above RGB kept (v = e >> 3, exactly).
inline uint32_t DimExpanded(uint32_t rgb, uint64_t now, uint64_t then) {
    if (now >= then) return rgb;
    const auto c = Dim(uint16_t((rgb >> 19 & 31) << 10 | (rgb >> 11 & 31) << 5 | (rgb >> 3 & 31)), now, then);
    const auto e = [](unsigned v) { return (v << 3) | (v >> 2); };
    return (rgb & 0xff000000u) | e(c >> 10 & 31) << 16 | e(c >> 5 & 31) << 8 | e(c & 31);
}
inline constexpr uint16_t kTaken = 0x8000;   // a floor pen kept by a stain pixel (pen | kTaken; 0 = none yet)
// One frame of stains: the floor pens they first covered, through the palette now and at their references.
struct Shade {
    uint64_t now = 0, then = 0;
    void Cover(uint16_t pen, uint8_t sum, const uint16_t* palette) {
        if (!(pen & kTaken)) return;
        now += Sum(palette[pen & 0x7fff]); then += sum;
    }
    uint32_t Apply(uint32_t rgb) const { return DimExpanded(rgb, now, then); }
    template<class A> friend void Fields(A& a, Shade& s) { a(s.now, s.then); }
};
} // namespace mk5blood
