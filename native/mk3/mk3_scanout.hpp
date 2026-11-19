// MK3 2.1 (Wolf-Unit) scanout: the screen bitmap as MAME 0.280 builds it, line by line, from live video RAM.
// Contract (S = decoder-research/upstream/tms34010.cpp, SCR = decoder-research/upstream/screen.cpp, V = sources/
// midtunit_v.cpp, W = sources/midwunit.cpp): the scanline timer calls screen().update_partial(vcount) inside the
// visible area before DPYADR's DUDATE step (S:1094-1097, VideoTiming::update_partial); update_partial renders
// [last_partial_scan, vcount] clipped to the visible area (SCR:628-700) through tms340x0_ind16, which draws only the
// clip's first row (S:1168-1196) with get_display_params (S:1137-1155) and midtunit scanline_update (V:845-855):
// pens = VRAM & 0x7fff from HEBLNK to HSBLNK - 1, black pen elsewhere in the clip and on a disabled display. The
// scanline-0 timer resets last_partial_scan (SCR:902). The ind16 bitmap goes through the xRGB_555 palette (W:643) at
// the primary screen's frame_update in vblank_begin (SCR:1153-1162): Present() takes the palette RAM at that point.
// Geometry: 506 x 289 raw, visible 101..500 x 20..273, 1 pixel per 8 MHz clock (W:625-647).
// Not modelled (reject): an HSBLNK past the bitmap width. Frame skipping and render liveness (SCR:633-647) are
// assumed off/live, as for the reference captures.
// Compared with the Original (tools/mk3/test_scanout_original.py): every VBLANK from reset to the native `jogo`
// frontier, visible RGB equal frame by frame (as screen_device::pixels sees it) and palette RAM equal at each VBLANK.
// Remastered layer 2 (presentation only): with `layers` attached, each rendered row also keeps the backdrop pen of
// every pixel (DmaLayers::Backdrop) and Present() resolves it through the same palette into `backdrop`; `pens`,
// `frame` and the hashes are computed exactly as without it. Each row also samples layers->fighters through
// mk5presentation::FighterCapture (as MK2's scanout, with pens instead of colours); Present() completes `fighters`
// through the same palette (serial 0 = no fighter layer this frame or a row the capture cannot follow).
// Floor blood (mk3_blood.hpp): a visible word under a stain of layers->blood is the stain's colour in `presentation`
// (the frame the Remastered window shows), unflagged in `backdrop` and in the fighters' underlay; `frame` stays canonical.
// Present dims the frame's stains by the brightness of the canonical pens they cover (the floor words) through the
// VBLANK palette against their FloorBlood floor references, so the program's palette fades take them along.
#pragma once
#include "mk3_dma_observer.hpp"
#include "mk3_video.hpp"
#include <algorithm>
#include <array>
#include <cstdint>
#include <functional>
#include <stdexcept>
#include <vector>

namespace mk3 {

struct Scanout {
    using V = VideoTiming;
    static constexpr int kWidth = V::kWidth, kHeight = V::kHeight, kLeft = V::kVisLeft, kRight = V::kVisRight;
    static constexpr int kTop = V::kVisTop, kBottom = V::kVisBottom;
    static constexpr int kFrameWidth = kRight - kLeft + 1, kFrameHeight = kBottom - kTop + 1;   // 400 x 254
    static constexpr uint16_t kBlackPen = 0x8000;   // palette black_pen(): outside the 32768 palette entries

    std::vector<uint16_t> pens = std::vector<uint16_t>(size_t(kWidth) * kHeight, kBlackPen);   // the ind16 bitmap
    std::vector<uint32_t> frame = std::vector<uint32_t>(size_t(kFrameWidth) * kFrameHeight);  // 0x00RRGGBB, visible area
    int last_partial_scan = 0;
    uint64_t frames = 0, lines = 0;
    // Host observer after every Present (window, audio pump, hashes); it reads the frame and never feeds back.
    std::function<void(const Scanout&)> presented;
    DmaLayers* layers = nullptr;
    mk5presentation::FighterCapture fighter_work;
    mk5presentation::FighterFrame fighters;
    std::vector<uint32_t> row_pens = std::vector<uint32_t>(kFrameWidth), row_back = std::vector<uint32_t>(kFrameWidth);
    std::vector<uint32_t> backdrop_pens, backdrop;   // pen | DmaLayers::kScenery; 0x00RRGGBB | kSceneryRgb (visible area)
    std::vector<uint32_t> presentation_pens, presentation;   // visible area: pen or FloorBlood::kMark | RGB555; 0x00RRGGBB
    std::vector<uint8_t> presentation_floor;   // visible area: FloorBlood floor reference of a stained pixel
    std::vector<uint16_t> row_blood = std::vector<uint16_t>(kWidth);
    std::vector<uint8_t> row_floor = std::vector<uint8_t>(kWidth);
    static constexpr uint32_t kSceneryRgb = 0x80000000u;   // mk5stage::scenery

    void ResetPartial() { last_partial_scan = 0; }   // scanline-0 timer: reset_partial_updates

    // update_partial(vcount) with the TMS registers and video RAM at that instant.
    void Line(int vcount, const std::array<uint16_t, 32>& io, const std::vector<uint16_t>& vram) {
        if (vcount < last_partial_scan) return;   // already rendered
        const int top = std::max(kTop, last_partial_scan), bottom = std::min(kBottom, vcount);
        if (top > bottom) return;
        last_partial_scan = bottom + 1;
        ++lines;
        uint16_t* dest = &pens[size_t(top) * kWidth];
        int heblnk = io[V::HEBLNK], hsblnk = io[V::HSBLNK];   // m_pixperclock = 1
        size_t row_base = 0; unsigned row_col = 0;
        const bool enabled = io[V::DPYCTL] & 0x8000;
        if (enabled) {   // enabled: midtunit_video_device::scanline_update
            if (hsblnk > kWidth) throw std::runtime_error("MK3 scanout: HSBLNK past the screen bitmap is not modelled");
            uint16_t dpyadr = io[V::DPYADR];
            if (!(io[V::DPYCTL] & 0x0400)) dpyadr ^= 0xfffc;
            const unsigned rowaddr = dpyadr >> 4, coladdr = ((dpyadr & 0x007c) << 4) | (io[V::DPYTAP] & 0x3fff);
            const uint16_t* src = &vram[(rowaddr << 9) & 0x3fe00];
            unsigned col = coladdr << 1;
            row_base = (rowaddr << 9) & 0x3fe00; row_col = col;
            if (layers) {
                if (backdrop_pens.empty()) backdrop_pens.assign(pens.size(), kBlackPen);
                uint32_t* back = &backdrop_pens[size_t(top) * kWidth];
                const size_t base = (rowaddr << 9) & 0x3fe00;
                std::fill(row_blood.begin(), row_blood.end(), uint16_t(0));
                for (int x = heblnk, c = int(col); x < hsblnk; ++x, ++c) {
                    back[x] = layers->Backdrop(base + (c & 0x1ff), src[c & 0x1ff]);
                    row_blood[x] = layers->blood.At(base + (c & 0x1ff)); row_floor[x] = layers->blood.Floor(base + (c & 0x1ff));
                    if (row_blood[x]) back[x] = FloorBlood::kMark | (row_blood[x] & 0x7fffu);
                }
            }
            for (int x = heblnk; x < hsblnk; ++x) dest[x] = src[col++ & 0x1ff] & 0x7fff;
        } else heblnk = hsblnk = kRight + 1;
        for (int x = kLeft; x < heblnk && x <= kRight; ++x) dest[x] = kBlackPen;
        for (int x = std::max(hsblnk, kLeft); x <= kRight; ++x) dest[x] = kBlackPen;
        if (layers) {
            if (backdrop_pens.empty()) backdrop_pens.assign(pens.size(), kBlackPen);
            uint32_t* back = &backdrop_pens[size_t(top) * kWidth];
            for (int x = kLeft; x <= kRight; ++x) if (x < heblnk || x >= hsblnk) back[x] = kBlackPen;
            if (top == kTop) fighter_work.Begin(kFrameWidth, kFrameHeight);
            if (!enabled) std::fill(row_blood.begin(), row_blood.end(), uint16_t(0));
            if (presentation_pens.empty()) presentation_pens.assign(frame.size(), kBlackPen);
            if (presentation_floor.empty()) presentation_floor.assign(frame.size(), 0);
            for (int x = 0; x < kFrameWidth; ++x) {
                const uint16_t stain = row_blood[x + kLeft];
                row_pens[x] = stain ? FloorBlood::kMark | (stain & 0x7fffu) : dest[x + kLeft];
                row_back[x] = stain ? row_pens[x] : (back[x + kLeft] & 0xffff) | (back[x + kLeft] & DmaLayers::kScenery ? kSceneryRgb : 0);
                presentation_pens[size_t(top - kTop) * kFrameWidth + x] = row_pens[x];
                presentation_floor[size_t(top - kTop) * kFrameWidth + x] = stain ? row_floor[x + kLeft] : uint8_t(0);
            }
            layers->Flush();
            fighter_work.Line(layers->fighters, unsigned(top - kTop), row_base, row_col, row_pens.data(), row_back.data(),
                              [](uint16_t pen) { return uint32_t(pen); }, enabled && heblnk == kLeft && hsblnk == kRight + 1);
        }
    }

    // vblank_begin -> frame_update: the visible area through the palette (xRGB_555, pal5bit expansion).
    void Present(const std::vector<uint16_t>& palette) {
        for (int y = 0; y < kFrameHeight; ++y)
            for (int x = 0; x < kFrameWidth; ++x) {
                const uint16_t pen = pens[size_t(y + kTop) * kWidth + size_t(x + kLeft)];
                frame[size_t(y) * kFrameWidth + x] = pen == kBlackPen ? 0 : Rgb(palette[pen]);
            }
        if (layers) {
            if (backdrop_pens.empty()) backdrop_pens.assign(pens.size(), kBlackPen);
            if (presentation_pens.empty()) presentation_pens.assign(frame.size(), kBlackPen);
            if (presentation_floor.empty()) presentation_floor.assign(frame.size(), 0);
            uint64_t now = 0, then = 0;   // the floor under this frame's stains: now (VBLANK palette) and at its references
            for (int y = 0; y < kFrameHeight; ++y)
                for (int x = 0; x < kFrameWidth; ++x) {
                    const size_t i = size_t(y) * kFrameWidth + size_t(x);
                    if (!(presentation_pens[i] & FloorBlood::kMark) || !presentation_floor[i]) continue;
                    const uint16_t pen = pens[size_t(y + kTop) * kWidth + size_t(x + kLeft)];
                    now += pen == kBlackPen ? 0 : FloorBlood::Sum(palette[pen]); then += presentation_floor[i] - 1u;
                }
            const auto rgb = [&](uint32_t pen) {
                return pen & FloorBlood::kMark ? Rgb(FloorBlood::Dim(uint16_t(pen & 0x7fff), now, then))
                                               : (pen & 0xffff) == kBlackPen ? 0 : Rgb(palette[pen & 0x7fff]);
            };
            presentation.resize(frame.size());
            for (size_t i = 0; i < frame.size(); ++i) presentation[i] = rgb(presentation_pens[i]);
            backdrop.resize(frame.size());
            for (int y = 0; y < kFrameHeight; ++y)
                for (int x = 0; x < kFrameWidth; ++x) {
                    const uint32_t pen = backdrop_pens[size_t(y + kTop) * kWidth + size_t(x + kLeft)];
                    backdrop[size_t(y) * kFrameWidth + x] = rgb(pen) | (pen & DmaLayers::kScenery ? kSceneryRgb : 0);
                }
            fighter_work.Complete(frames + 1, fighters);
            if (fighters.serial) {
                for (auto& v : fighters.underlay) v = rgb(v);
                for (auto& v : fighters.backdrop) v = rgb(v) | (v & kSceneryRgb);
                for (auto& l : fighters.layers) for (auto& v : l.pixels) if (v >> 24) v = 0xff000000u | rgb(v);
            }
        }
        ++frames;
        if (presented) presented(*this);
    }
    // Self-check of `fighters`: its layers over the underlay at 1x (opaque order kept) must give `presentation`; mismatched pixels.
    uint64_t FighterMismatched() const {
        if (!fighters.serial) return 0;
        std::vector<uint32_t> img = fighters.underlay;
        for (const auto& l : fighters.layers)
            for (unsigned y = 0; y < l.height; ++y) for (unsigned x = 0; x < l.width; ++x) {
                const int fx = l.x + int(x), fy = l.y + int(y);
                const uint32_t v = l.pixels[size_t(y) * l.width + x];
                if (!(v >> 24) || fx < 0 || fy < 0 || fx >= kFrameWidth || fy >= kFrameHeight) continue;
                const size_t i = size_t(fy) * kFrameWidth + size_t(fx);
                if (fighters.opaque_order[i] < l.order) img[i] = v;
            }
        uint64_t n = 0;
        for (size_t i = 0; i < img.size(); ++i) n += (img[i] & 0xffffff) != presentation[i];
        return n;
    }
    static uint32_t Rgb(uint16_t c) {
        const auto five = [](unsigned v) { v &= 31; return (v << 3) | (v >> 2); };
        return five(c >> 10) << 16 | five(c >> 5) << 8 | five(c);
    }
};

} // namespace mk3
