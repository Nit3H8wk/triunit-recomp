// Focal contracts of the MK3 Remastered layer 2 (tools/mk3/test_remaster.py builds them with a one-line main):
// mk3::Dma draws observed by mk3::DmaLayers (classes from the producers of mk3_dma_observer.hpp, through DmaQueue),
// mk3::Scanout with the backdrop and mk5stage::Bicubic4x, the filter the window applies. Synthetic graphics, video RAM,
// palette and registers; no Original capture. Each contract has a negative control that must be detected.
#pragma once
#include "mk3_dma.hpp"
#include "mk3_scanout.hpp"
#include "mk5_stage_bicubic.hpp"
#include <cstdio>
#include <functional>

namespace mk3remaster_tests {
using mk3::Dma;
using mk3::Scanout;

struct Rig {
    std::vector<uint8_t> gfx = std::vector<uint8_t>(1 << 18);
    Dma dma{gfx};
    mk3::DmaLayers layers;
    uint32_t pc = 0, b14 = 0;
    std::vector<uint16_t> palette = std::vector<uint16_t>(0x8000);
    std::array<uint16_t, 32> io{};
    std::vector<uint16_t> ram = std::vector<uint16_t>(0x40000);   // main RAM words (fighter slots)
    explicit Rig(bool observe = true) {
        for (size_t i = 0; i < gfx.size(); ++i) gfx[i] = uint8_t(1 + (i * 37 + (i >> 6) * 11) % 250);   // non-zero 8-bit pixels
        for (size_t i = 0; i < palette.size(); ++i) palette[i] = uint16_t((i * 2654435761u >> 9) & 0x7fff);
        dma.profile = mk3::Profile::Game;
        if (observe) { layers.writer_pc = &pc; layers.b14 = &b14; layers.ram = &ram; dma.observer = &layers; }
        dma.reg[Dma::TOPCLIP] = 0; dma.reg[Dma::BOTCLIP] = 511; dma.reg[Dma::LEFTCLIP] = 0; dma.reg[Dma::RIGHTCLIP] = 1023;
        io[mk3::VideoTiming::HEBLNK] = Scanout::kLeft; io[mk3::VideoTiming::HSBLNK] = Scanout::kRight + 1;
        io[mk3::VideoTiming::DPYCTL] = 0x8400;   // enabled, no DPYADR inversion; DPYTAP 0: visible x = kLeft is column 0
    }
    // One draw: 8-bit copy of non-zero pixels (command 0x8002) or a colour fill (0x800c), from the given producer.
    void Draw(int x, int y, int w, int h, uint16_t palette_hi, uint32_t source_bits, bool fill = false) {
        dma.reg[Dma::XSTART] = uint16_t(x); dma.reg[Dma::YSTART] = uint16_t(y); dma.reg[Dma::WIDTH] = uint16_t(w); dma.reg[Dma::HEIGHT] = uint16_t(h);
        dma.reg[Dma::PALETTE] = palette_hi; dma.reg[Dma::COLOR] = 0x21;
        dma.reg[Dma::OFFSETLO] = uint16_t(source_bits); dma.reg[Dma::OFFSETHI] = uint16_t(source_bits >> 16);
        dma.Write(Dma::COMMAND, fill ? 0x800c : 0x8002);
    }
    void Direct(uint32_t writer) {   // a direct writer after the display table
        const uint32_t a[16] = {};
        layers.queue.Step(mk3::DmaQueue::kAfterTable, a);
        pc = writer;
    }
    void Slot(unsigned k, uint32_t object) {   // the fighter slot k holds `object`
        const size_t i = (mk3::kFighterSlots[k] - 0x01000000) / 16;
        ram[i] = uint16_t(object); ram[i + 1] = uint16_t(object >> 16);
    }
    // The walker enqueues one entry of `object` and the DMA-done handler pops it.
    void Queued(uint32_t list, uint32_t scroll, uint32_t object = 0x01080000) {
        uint32_t a[16] = {list, 0x01100000 + 0xc0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, scroll, 0, 0};
        layers.queue.Step(mk3::DmaQueue::kPass, a); layers.queue.Step(mk3::DmaQueue::kScroll, a);
        layers.queue.Step(mk3::DmaQueue::kWalk, a); a[0] = object; layers.Step(mk3::DmaQueue::kObject, a);
        pc = mk3::DmaQueue::kPump; b14 = 0x01100000;
    }
    void Render(Scanout& s, std::function<void(int, std::array<uint16_t, 32>&)> line = {}) {
        s.ResetPartial();
        for (int v = Scanout::kTop; v <= Scanout::kBottom; ++v) {
            auto r = io;
            r[mk3::VideoTiming::DPYADR] = uint16_t((v - Scanout::kTop) << 4);   // video RAM row v - kTop
            if (line) line(v, r);
            s.Line(v, r, dma.vram);
        }
        s.Present(palette);
    }
};

inline int failures = 0, checks = 0, negatives = 0, detected = 0;
inline void Check(bool ok, const char* what) { ++checks; if (!ok) { std::fprintf(stderr, "FAIL %s\n", what); ++failures; } }
inline void Negative(bool caught, const char* what) { ++negatives; detected += caught; if (!caught) std::fprintf(stderr, "NEGATIVE NOT DETECTED %s\n", what); }
inline size_t At(int x, int y) { return size_t(y) * Scanout::kFrameWidth + size_t(x); }
// The 4 x 4 tile of native pixel (x, y) in the composed frame.
inline bool TileIs(const std::vector<uint32_t>& c, int x, int y, uint32_t rgb) {
    for (int dy = 0; dy < 4; ++dy) for (int dx = 0; dx < 4; ++dx)
        if ((c[size_t(4 * y + dy) * Scanout::kFrameWidth * 4 + size_t(4 * x + dx)] & 0xffffff) != (rgb & 0xffffff)) return false;
    return true;
}
inline bool TilesEqual(const std::vector<uint32_t>& a, const std::vector<uint32_t>& b, int x, int y) {
    for (int dy = 0; dy < 4; ++dy) for (int dx = 0; dx < 4; ++dx) {
        const size_t i = size_t(4 * y + dy) * Scanout::kFrameWidth * 4 + size_t(4 * x + dx);
        if ((a[i] & 0xffffff) != (b[i] & 0xffffff)) return false;
    }
    return true;
}
inline uint64_t Mismatched(const Scanout& s) {   // flagged backdrop pixels whose colour is not the canonical one
    uint64_t n = 0;
    for (size_t i = 0; i < s.frame.size(); ++i) n += (s.backdrop[i] & Scanout::kSceneryRgb) && (s.backdrop[i] & 0xffffff) != s.frame[i];
    return n;
}
inline std::vector<uint32_t> Compose(const Scanout& s) { return mk5stage::Bicubic4x(s.frame, s.backdrop, Scanout::kFrameWidth, Scanout::kFrameHeight); }

// Scene: a scenery plane over the whole visible area, a fighter (world-object list, object in fighter slot 0) over part
// of it, a HUD glyph.
constexpr uint32_t kPlaneScroll = 0x0105da40, kWorld = 0x0105dc10, kWorldScroll = 0x0105dae0, kHud = 0x0105dc30;
constexpr uint32_t kFighter = 0x01090000;
inline void Scene(Rig& r, bool fighter, bool hud) {
    r.Slot(0, kFighter);
    r.Queued(0x0105db70, kPlaneScroll); r.Draw(0, 0, Scanout::kFrameWidth, Scanout::kFrameHeight, 0x0100, 0);
    if (fighter) { r.Queued(kWorld, kWorldScroll, kFighter); r.Draw(100, 60, 40, 80, 0x0200, 0x40000); }
    if (hud) { r.Queued(kHud, kWorldScroll); r.Draw(300, 10, 20, 12, 0x0300, 0x60000); }
}

inline int Run() {
    // 1. The canonical frame does not depend on the observer.
    Rig plain(false), observed;
    Scanout a, b;
    Scene(plain, true, true); Scene(observed, true, true);
    b.layers = &observed.layers;
    plain.Render(a); observed.Render(b);
    Check(a.frame == b.frame && a.pens == b.pens, "canonical frame and pens equal with and without the layers");
    Check(observed.layers.draws[unsigned(mk3::DmaClass::Scenery)] == 1 && observed.layers.draws[unsigned(mk3::DmaClass::Fighter)] == 1 &&
          observed.layers.draws[unsigned(mk3::DmaClass::Text)] == 1, "classes of the plane, the fighter and the HUD");
    Check(observed.layers.queue.staged.empty(), "every queued entry popped");

    // 2. Palette: a flagged pixel is the canonical pixel's own colour, also after a palette change before VBLANK.
    Check(Mismatched(b) == 0, "flagged backdrop colour equals the canonical colour");
    {
        Rig r; Scanout s; s.layers = &r.layers;
        Scene(r, true, false);
        for (auto& c : r.palette) c ^= 0x1234;
        r.Render(s);
        Check(Mismatched(s) == 0, "palette at VBLANK used for both");
        auto bad = s; for (size_t i = 0; i < bad.backdrop.size(); ++i) if (bad.backdrop[i] & Scanout::kSceneryRgb) bad.backdrop[i] ^= 0x000100;
        Negative(Mismatched(bad) != 0, "backdrop through another palette");
    }

    // 3. Occlusion: fighter and HUD pixels are unflagged and stay nearest-neighbour copies of the canonical pixel.
    const auto composed = Compose(b);
    bool occluded = true, nearest = true;
    for (int y = 60; y < 140; ++y) for (int x = 100; x < 140; ++x) {
        occluded &= !(b.backdrop[At(x, y)] & Scanout::kSceneryRgb);
        nearest &= TileIs(composed, x, y, b.frame[At(x, y)]);
    }
    for (int y = 10; y < 22; ++y) for (int x = 300; x < 320; ++x) occluded &= !(b.backdrop[At(x, y)] & Scanout::kSceneryRgb);
    Check(occluded, "fighter and HUD pixels unflagged");
    Check(nearest, "fighter pixels are the canonical colour, 4 x 4");
    {
        auto bad = b; for (int y = 60; y < 140; ++y) for (int x = 100; x < 140; ++x) bad.backdrop[At(x, y)] |= Scanout::kSceneryRgb;
        const auto c = Compose(bad);
        bool same = true; for (int y = 61; y < 139; ++y) for (int x = 101; x < 139; ++x) same &= TileIs(c, x, y, b.frame[At(x, y)]);
        Negative(!same, "fighter pixels flagged as scenery are filtered");
    }

    // 4. Border: the filter around the fighter reads the hidden scenery, so the scenery next to it is as without it.
    {
        Rig r; Scanout s; s.layers = &r.layers; Scene(r, false, false); r.Render(s);
        const auto alone = Compose(s);
        bool border = true;
        for (int y = 58; y < 142; ++y) for (int x : {98, 99, 140, 141}) border &= TilesEqual(composed, alone, x, y);
        for (int x = 98; x < 142; ++x) for (int y : {58, 59, 140, 141}) border &= TilesEqual(composed, alone, x, y);
        Check(border, "scenery border filtered from the hidden scenery");
        auto bad = b;   // negative: the visible (fighter) colour under the fighter
        for (int y = 60; y < 140; ++y) for (int x = 100; x < 140; ++x) bad.backdrop[At(x, y)] = b.frame[At(x, y)];
        const auto c = Compose(bad);
        bool same = true;
        for (int y = 58; y < 142; ++y) for (int x : {98, 99, 140, 141}) same &= TilesEqual(c, alone, x, y);
        Negative(!same, "fighter colour bleeding into the scenery border");
        Check(TileIs(alone, 200, 200, 0) == false && Mismatched(s) == 0, "scenery-only frame filtered");
    }

    // 5. CPU write (outside Dma) over scenery: unflagged, its own pen. Negative: ignoring the stored-value check.
    {
        Rig r; Scanout s; s.layers = &r.layers; Scene(r, false, false);
        const size_t word = size_t(30) * 512 + 50;   // row 30, column 50 = visible (50, 30)
        r.dma.vram[word] = uint16_t(r.dma.vram[word] ^ 0x0005);
        r.Render(s);
        Check(!(s.backdrop[At(50, 30)] & Scanout::kSceneryRgb) && (s.backdrop[At(50, 30)] & 0xffffff) == s.frame[At(50, 30)], "CPU-written word unflagged, own colour");
        auto bad = s; bad.backdrop[At(50, 30)] = Scanout::Rgb(r.palette[r.layers.under[word]]) | Scanout::kSceneryRgb;
        Negative(Mismatched(bad) != 0, "CPU write taken as the scenery draw");
    }

    // 6. Blanking: lines with the display disabled and columns outside HEBLNK..HSBLNK-1 are black and unflagged.
    {
        Rig r; Scanout s; s.layers = &r.layers; Scene(r, false, false);
        r.Render(s, [](int v, std::array<uint16_t, 32>& io) {
            if (v == 100) io[mk3::VideoTiming::DPYCTL] = 0x0400;
            if (v == 120) io[mk3::VideoTiming::HEBLNK] = Scanout::kLeft + 8;
        });
        bool blank = true;
        for (int x = 0; x < Scanout::kFrameWidth; ++x) blank &= s.backdrop[At(x, 100 - Scanout::kTop)] == 0 && s.frame[At(x, 100 - Scanout::kTop)] == 0;
        for (int x = 0; x < 8; ++x) blank &= s.backdrop[At(x, 120 - Scanout::kTop)] == 0;
        Check(blank, "blanked line and columns black and unflagged");
        Check(s.backdrop[At(8, 120 - Scanout::kTop)] & Scanout::kSceneryRgb, "first displayed column flagged");
    }

    // 7. Clear: a colour fill classed Clear replaces the scenery under it; an unclassified draw keeps it unflagged.
    {
        Rig r; Scanout s; s.layers = &r.layers; Scene(r, false, false);
        r.Direct(0xff8052b0); r.Draw(0, 0, 10, 10, 0x0400, 0, true);
        r.Direct(0xffabcdef); r.Draw(20, 0, 10, 10, 0x0500, 0x8000);
        r.Queued(0x0105dc50, kWorldScroll); r.Draw(40, 0, 10, 10, 0x0600, 0x9000);   // a list past the table's lists: no rule
        r.Queued(0x0105dbf0, kWorldScroll); r.Draw(60, 0, 10, 10, 0x0700, 0xa000);   // plane list on the camera word (FF9117F0)
        r.Render(s);
        Check(r.layers.draws[unsigned(mk3::DmaClass::Scenery)] == 2 && !(s.backdrop[At(45, 5)] & Scanout::kSceneryRgb) &&
              (s.backdrop[At(65, 5)] & Scanout::kSceneryRgb), "plane list on the camera word is scenery, an unknown list is not");
        const size_t cleared = 5 * 512 + 5, unknown = 5 * 512 + 25;
        Check(r.layers.under[cleared] == r.dma.vram[cleared] && !(s.backdrop[At(5, 5)] & Scanout::kSceneryRgb), "clear replaces the scenery under it");
        Check(r.layers.under[unknown] != r.dma.vram[unknown] && !(s.backdrop[At(25, 5)] & Scanout::kSceneryRgb), "unclassified draw keeps the hidden scenery, unflagged");
        Check(r.layers.draws[unsigned(mk3::DmaClass::Clear)] == 1 && r.layers.draws[unsigned(mk3::DmaClass::None)] == 2, "clear and unclassified counted");
        mk3::DmaQueue q;
        Check(q.Take(mk3::DmaQueue::kPump, 0x01100000).list == mk3::DmaQueue::kUnstaged, "pop without an observed enqueue is unstaged");
    }
    // 8. Fighter slots: a world-list object in a fighter slot is Fighter, any other is World.
    {
        Rig r; r.Slot(0, kFighter); r.Slot(1, kFighter + 0x1000);
        r.Queued(kWorld, kWorldScroll, kFighter + 0x1000); r.Draw(0, 0, 4, 4, 0x0200, 0x40000);
        r.Queued(kWorld, kWorldScroll, kFighter + 0x2000); r.Draw(8, 0, 4, 4, 0x0200, 0x40000);
        Check(r.layers.draws[unsigned(mk3::DmaClass::Fighter)] == 1 && r.layers.draws[unsigned(mk3::DmaClass::World)] == 1, "fighter slot object Fighter, other World");
        Rig n(true); n.layers.ram = nullptr;   // negative: without the slots nothing is Fighter
        n.Queued(kWorld, kWorldScroll, kFighter); n.Draw(0, 0, 4, 4, 0x0200, 0x40000);
        Negative(n.layers.draws[unsigned(mk3::DmaClass::Fighter)] == 0, "fighter without the slots");
    }

    // 9. Fighter layer: the capture rebuilds the canonical frame at 1x, the 4x composition smooths the fighter, a HUD drawn
    // after it stays on top; a CPU store over the fighter removes its texels.
    {
        Rig r; Scanout s; s.layers = &r.layers;
        Scene(r, true, false);
        r.Queued(kHud, kWorldScroll); r.Draw(110, 70, 6, 6, 0x0300, 0x60000);   // HUD over the fighter
        r.Render(s);
        Check(s.fighters.serial != 0 && s.fighters.layers.size() == 1 && s.FighterMismatched() == 0, "one fighter layer, 1x equals the canonical frame");
        const auto c = mk5presentation::ComposeFighterFrame4x(s.fighters, Scanout::kFrameWidth, Scanout::kFrameHeight);
        bool hud = true; for (int y = 70; y < 76; ++y) for (int x = 110; x < 116; ++x) hud &= TileIs(c, x, y, s.frame[At(x, y)]);
        bool smooth = false; for (int y = 61; y < 139 && !smooth; ++y) for (int x = 101; x < 139; ++x) smooth |= !TileIs(c, x, y, s.frame[At(x, y)]);
        Check(hud, "HUD after the fighter stays nearest on top"); Check(smooth, "fighter interior filtered 4x");
        auto bad = s; bad.fighters.layers[0].pixels[0] ^= 0x010101;
        Negative(bad.FighterMismatched() != 0, "fighter layer pixel off the canonical frame");
        auto under = s; for (int y = 70; y < 76; ++y) for (int x = 110; x < 116; ++x) under.fighters.opaque_order[At(x, y)] = 0;
        const auto u = mk5presentation::ComposeFighterFrame4x(under.fighters, Scanout::kFrameWidth, Scanout::kFrameHeight);
        bool covered = true; for (int y = 70; y < 76; ++y) for (int x = 110; x < 116; ++x) covered &= TileIs(u, x, y, s.frame[At(x, y)]);
        Negative(!covered, "HUD under the fighter when the opaque order is lost");

        Rig w; Scanout t; t.layers = &w.layers; Scene(w, true, false);
        for (int y = 60; y < 140; ++y) for (int x = 100; x < 140; ++x) {   // CPU stores over the whole fighter
            const size_t word = size_t(y) * 512 + size_t(x);
            w.dma.vram[word] = 0x0444; w.layers.Cpu(0xff928130, word, 0x0444);
        }
        w.Render(t);
        Check(t.fighters.serial == 0 && w.layers.cpu_words[0] == 3200, "CPU stores remove the fighter layer");
        Rig v; Scanout z; z.layers = &v.layers; Scene(v, true, false);   // negative: the stores without the hook
        for (int y = 60; y < 140; ++y) for (int x = 100; x < 140; ++x) v.dma.vram[size_t(y) * 512 + size_t(x)] = 0x0444;
        v.Render(z);
        Negative(z.FighterMismatched() != 0, "fighter layer kept over CPU stores without the hook");
    }
    // 10. CPU page fill (FF81B580) is scenery under the planes; any other CPU store is its own unflagged pixel.
    {
        Rig r; Scanout s; s.layers = &r.layers;
        for (int y = 0; y < Scanout::kFrameHeight; ++y) for (int x = 0; x < Scanout::kFrameWidth; ++x) {
            const size_t word = size_t(y) * 512 + size_t(x);
            r.dma.vram[word] = 0x053f; r.layers.Cpu(mk3::DmaLayers::kPageFill, word, 0x053f);
        }
        const size_t other = size_t(20) * 512 + 20;
        r.dma.vram[other] = 0x0601; r.layers.Cpu(0xffae8690, other, 0x0601);
        r.Queued(0x0105db70, kPlaneScroll); r.Draw(100, 100, 30, 30, 0x0100, 0);
        r.Render(s);
        Check((s.backdrop[At(5, 5)] & Scanout::kSceneryRgb) && !(s.backdrop[At(20, 20)] & Scanout::kSceneryRgb) && Mismatched(s) == 0,
              "page fill flagged, other CPU store unflagged");
        Check(r.layers.cpu_words[1] == size_t(Scanout::kFrameWidth) * Scanout::kFrameHeight && r.layers.cpu_words[0] == 1, "CPU stores counted by class");
        auto bad = s; bad.backdrop[At(20, 20)] = Scanout::Rgb(r.palette[0x053f]) | Scanout::kSceneryRgb;
        Negative(Mismatched(bad) != 0, "other CPU store taken as the page fill");
    }
    // 11. Objects bound by their creator (ObjectBinder): a child built by fighter code (return PC FFA132D0, A8 = fighter
    // slot object) is a Fighter layer of its own; a select-screen portrait (FF9E8D10) is scenery; the same object from an
    // unknown site, or after its return to the free list, is World again. Negatives: parent not in a slot; no unbinding.
    {
        constexpr uint32_t kChild = 0x01095000, kPortrait = 0x01096000, kSp = 0x010ff000;
        const auto put = [](Rig& r, uint32_t at, uint32_t v) { const size_t i = (at - 0x01000000) / 16; r.ram[i] = uint16_t(v); r.ram[i + 1] = uint16_t(v >> 16); };
        const auto insert = [&](Rig& r, uint32_t object, uint32_t ret, uint32_t a8) {
            uint32_t a[16] = {object, 0, 0, 0, mk3::ObjectBinder::kWorldList, 0, 0, 0, a8, 0, 0, 0, 0, 0, 0, kSp};
            put(r, kSp + 0xa0, ret); r.layers.Step(mk3::ObjectBinder::kInsert, a);
        };
        const auto draw = [&](Rig& r, uint32_t object, int x) { r.Queued(kWorld, kWorldScroll, object); r.Draw(x, 0, 4, 4, 0x0200, 0x40000); };
        Rig r; Scanout s; s.layers = &r.layers; r.Slot(0, kFighter);
        insert(r, kChild, 0xffa132d0, kFighter); insert(r, kPortrait, 0xff9e8d10, 0);
        draw(r, kChild, 0); draw(r, kPortrait, 8); r.Render(s);
        Check(r.layers.draws[unsigned(mk3::DmaClass::Fighter)] == 1 && r.layers.draws[unsigned(mk3::DmaClass::Scenery)] == 1 &&
              r.layers.bound_draws[0] == 1 && r.layers.bound_draws[1] == 1, "fighter child and screen art bound by their creators");
        Check(s.fighters.serial && s.fighters.layers.size() == 1 && s.FighterMismatched() == 0 && (s.backdrop[At(9, 1)] & Scanout::kSceneryRgb),
              "child is a fighter layer, screen art flagged");
        insert(r, kChild, 0xff800000, kFighter);   // re-inserted by another site
        put(r, mk3::ObjectBinder::kFreeHead, kPortrait); put(r, kPortrait, 0);   // the portrait back on the free list
        { const uint32_t a[16] = {}; r.layers.Step(mk3::ObjectBinder::kFreeHeadStores[2], a); r.layers.Step(0xff800010, a); }
        draw(r, kChild, 16); draw(r, kPortrait, 24);
        Check(r.layers.draws[unsigned(mk3::DmaClass::World)] == 2 && r.layers.objects.bound.empty(), "other site and free list unbind");
        Rig n; n.Slot(0, kFighter + 0x10);   // negative: the parent register is not a fighter slot object
        insert(n, kChild, 0xffa132d0, kFighter); draw(n, kChild, 0);
        Negative(n.layers.draws[unsigned(mk3::DmaClass::Fighter)] == 0, "child of a non-fighter bound");
        Rig k; k.Slot(0, kFighter); insert(k, kChild, 0xffa132d0, kFighter);   // negative: no unbinding at the free list
        put(k, mk3::ObjectBinder::kFreeHead, kChild); put(k, kChild, 0);
        draw(k, kChild, 0);
        Negative(k.layers.draws[unsigned(mk3::DmaClass::Fighter)] == 1, "child kept bound without the free-list store");
    }
    // 12. CPU picture rows (FF92A8B0/D0/F0) are scenery; counted apart from the page fill.
    {
        Rig r; Scanout s; s.layers = &r.layers;
        for (int x = 0; x < 40; ++x) { const size_t word = size_t(30) * 512 + size_t(x); r.dma.vram[word] = uint16_t(0x0700 + x); r.layers.Cpu(mk3::DmaLayers::kPictureRows[1], word, uint16_t(0x0700 + x)); }
        const size_t other = size_t(31) * 512; r.dma.vram[other] = 0x0601; r.layers.Cpu(0xff928130, other, 0x0601);
        r.Render(s);
        Check((s.backdrop[At(5, 30)] & Scanout::kSceneryRgb) && !(s.backdrop[At(0, 31)] & Scanout::kSceneryRgb) && Mismatched(s) == 0 &&
              r.layers.cpu_words[2] == 40 && r.layers.cpu_words[0] == 1, "picture rows flagged, other CPU store not");
        auto bad = s; bad.backdrop[At(0, 31)] = Scanout::Rgb(r.palette[0x0700]) | Scanout::kSceneryRgb;
        Negative(Mismatched(bad) != 0, "other CPU store taken as a picture row");
    }
    // 13. RAM plane lists of table FF9100B0 on their own scroll word are scenery; on another word they are not.
    {
        Rig r; r.Queued(0x01062750, 0x010628a0); r.Draw(0, 0, 4, 4, 0x0100, 0);
        Check(r.layers.draws[unsigned(mk3::DmaClass::Scenery)] == 1, "RAM plane list on its own scroll word is scenery");
        Rig n; n.Queued(0x01062750, 0x0105dae0); n.Draw(0, 0, 4, 4, 0x0100, 0);
        Negative(n.layers.draws[unsigned(mk3::DmaClass::Scenery)] == 0, "RAM plane list on the camera word taken as scenery");
        mk3::DmaQueue q; uint32_t a[16] = {0x0105dc30, 0x01100000 + 0xc0};   // an entry left when the queue is emptied
        q.Step(mk3::DmaQueue::kObject, a); const bool left = q.staged.size() == 1; q.Step(mk3::DmaQueue::kReset, a);
        Check(left && q.staged.empty(), "queue reset FF806840 drops the unpopped entries");
    }
    // 14. Direct list (FF8081A0 append, FF8051D0 pop, FF8052B0 draw): a glyph appended by the string printer (caller return
    // FFAB9C00) is Text; one from another caller stays unclassified; any colour fill (mode 0xC, e.g. 0xE00C) is Clear.
    // Negatives: a pop without its append, and the same entry popped again after it was drawn.
    {
        constexpr uint32_t kSp = 0x010ff000, kEntry = 0x0102c9d0;
        const auto append = [&](Rig& r, uint32_t ret) {
            const size_t i = (kSp + 0x60 - 0x01000000) / 16; r.ram[i] = uint16_t(ret); r.ram[i + 1] = uint16_t(ret >> 16);
            uint32_t a[16] = {}; a[13] = kEntry + 0xa0; a[15] = kSp; r.layers.Step(mk3::DmaQueue::kAppend, a);
        };
        const auto pop = [&](Rig& r) { uint32_t a[16] = {}; a[1] = kEntry; r.Direct(0); r.layers.Step(mk3::DmaQueue::kDirectPop, a); r.pc = mk3::DmaQueue::kDirect; };
        Rig r; append(r, 0xffab9c00); pop(r); r.Draw(0, 0, 4, 4, 0x0100, 0);
        append(r, 0xff800000); pop(r); r.Draw(8, 0, 4, 4, 0x0100, 0);
        Check(r.layers.draws[unsigned(mk3::DmaClass::Text)] == 1 && r.layers.draws[unsigned(mk3::DmaClass::None)] == 1 && r.layers.queue.appended.empty(),
              "string printer glyph is Text, another appender unclassified");
        mk3::DmaDraw box{}; box.command = 0xe00c;
        Check(mk3::ClassifyDma({mk3::DmaQueue::kDirect, 0, 0, mk3::DmaQueue::kAfterTable}, box) == mk3::DmaClass::Clear, "direct colour fill E00C is Clear");
        mk3::DmaDraw row{}; row.command = 0x8003;
        Check(mk3::ClassifyDma({mk3::kDmaSelfTest, 0, 0, mk3::DmaQueue::kAfterTable}, row) == mk3::DmaClass::Clear, "DMA self-test row is Clear");
        row.command = 0x8002;
        Negative(mk3::ClassifyDma({mk3::kDmaSelfTest, 0, 0, mk3::DmaQueue::kAfterTable}, row) == mk3::DmaClass::None, "self-test writer with another command classed");
        Rig n; pop(n); n.Draw(0, 0, 4, 4, 0x0100, 0);
        Negative(n.layers.draws[unsigned(mk3::DmaClass::Text)] == 0, "glyph classed without its append");
        Rig k; append(k, 0xffab9c00); pop(k); k.Draw(0, 0, 4, 4, 0x0100, 0); pop(k); k.Draw(8, 0, 4, 4, 0x0100, 0);
        Negative(k.layers.draws[unsigned(mk3::DmaClass::Text)] == 1, "entry kept staged after its draw");
    }
    // 15. round start/ROUND (FFA99AD0) is Text; the frames chained at FF9FCA00 after the one inserted from FF9FC940 are scenery;
    // a plane list on scroll word 0105D9E0 is scenery. Negative: a chain after an unbound object stays World.
    {
        constexpr uint32_t kSp = 0x010ff000, kBanner = 0x01097000, kHead = 0x01098000, kNext = 0x01099000;
        const auto put = [](Rig& r, uint32_t at, uint32_t v) { const size_t i = (at - 0x01000000) / 16; r.ram[i] = uint16_t(v); r.ram[i + 1] = uint16_t(v >> 16); };
        const auto insert = [&](Rig& r, uint32_t object, uint32_t ret) {
            uint32_t a[16] = {object, 0, 0, 0, mk3::ObjectBinder::kWorldList}; a[15] = kSp;
            put(r, kSp + 0xa0, ret); r.layers.Step(mk3::ObjectBinder::kInsert, a);
        };
        const auto chain = [](Rig& r, uint32_t after, uint32_t object) { uint32_t a[16] = {}; a[8] = object; a[9] = after; r.layers.Step(mk3::ObjectBinder::kChain, a); };
        const auto draw = [&](Rig& r, uint32_t object, int x) { r.Queued(kWorld, kWorldScroll, object); r.Draw(x, 0, 4, 4, 0x0200, 0x40000); };
        Rig r; insert(r, kBanner, 0xffa99ad0); insert(r, kHead, 0xff9fc940); chain(r, kHead, kNext);
        draw(r, kBanner, 0); draw(r, kHead, 8); draw(r, kNext, 16);
        r.Queued(0x0105db10, 0x0105d9e0); r.Draw(24, 0, 4, 4, 0x0100, 0);
        Check(r.layers.draws[unsigned(mk3::DmaClass::Text)] == 1 && r.layers.draws[unsigned(mk3::DmaClass::Scenery)] == 3 &&
              r.layers.bound_draws[1] == 2 && r.layers.bound_draws[2] == 1, "banner Text, chained frames and plane 0105DB10 scenery");
        Rig n; chain(n, kHead, kNext); draw(n, kNext, 0);
        Negative(n.layers.draws[unsigned(mk3::DmaClass::Scenery)] == 0, "chain after an unbound object taken as scenery");
        // String printer glyph objects bound at the allocator (FF806EB0, return at SP + 40h): FFAB8FC0 is Text, another
        // allocation of the same object is World again.
        const auto alloc = [&](Rig& g, uint32_t object, uint32_t ret) { uint32_t a[16] = {object}; a[15] = kSp; put(g, kSp + 0x40, ret); g.layers.Step(mk3::ObjectBinder::kAlloc, a); };
        Rig g; alloc(g, kNext, 0xffab8fc0); draw(g, kNext, 0); alloc(g, kNext, 0xff95cb70); draw(g, kNext, 8);
        Check(g.layers.draws[unsigned(mk3::DmaClass::Text)] == 1 && g.layers.draws[unsigned(mk3::DmaClass::World)] == 1, "printer glyph object Text, other allocation World");
        Rig h; alloc(h, kNext, 0xffab8fb0); draw(h, kNext, 0);
        Negative(h.layers.draws[unsigned(mk3::DmaClass::Text)] == 0, "allocation from another return taken as a printer glyph");
    }
    // 16. K6 creators: body parts of FFA9E1A0 (return FFA9E7A0, parent A9 = fighter) are Fighter, and a part sprayed from a
    // bound part (FFA9F190, parent A10 = that part) too; a character figure (FF93F680) is Fighter with no parent; the combo
    // counter (FFA960C0), the countdown (FF940130) are Text; the code row (FF93E4B0) is scenery. Negatives: a part
    // whose A9 is not a fighter; a spray from an unbound object; the counter's return one instruction off.
    {
        constexpr uint32_t kSp = 0x010ff000, kPart = 0x01095000, kSpray = 0x01096000, kFigure = 0x01097000, kCombo = 0x01098000,
                           kDigit = 0x01099000, kIcon = 0x0109a000;
        const auto put = [](Rig& r, uint32_t at, uint32_t v) { const size_t i = (at - 0x01000000) / 16; r.ram[i] = uint16_t(v); r.ram[i + 1] = uint16_t(v >> 16); };
        const auto insert = [&](Rig& r, uint32_t object, uint32_t ret, unsigned reg = 0, uint32_t value = 0) {
            uint32_t a[16] = {object, 0, 0, 0, mk3::ObjectBinder::kWorldList}; a[15] = kSp; if (reg) a[reg] = value;
            put(r, kSp + 0xa0, ret); r.layers.Step(mk3::ObjectBinder::kInsert, a);
        };
        const auto draw = [&](Rig& r, uint32_t object, int x) { r.Queued(kWorld, kWorldScroll, object); r.Draw(x, 0, 4, 4, 0x0200, 0x40000); };
        const auto count = [](Rig& r, mk3::DmaClass c) { return r.layers.draws[unsigned(c)]; };
        Rig r; r.Slot(0, kFighter);
        insert(r, kPart, 0xffa9e7a0, 9, kFighter); insert(r, kSpray, 0xffa9f190, 10, kPart); insert(r, kFigure, 0xff93f680);
        insert(r, kCombo, 0xffa960c0); insert(r, kDigit, 0xff940130); insert(r, kIcon, 0xff93e4b0);
        draw(r, kPart, 0); draw(r, kSpray, 8); draw(r, kFigure, 16); draw(r, kCombo, 24); draw(r, kDigit, 32); draw(r, kIcon, 40);
        Check(count(r, mk3::DmaClass::Fighter) == 3 && count(r, mk3::DmaClass::Text) == 2 && count(r, mk3::DmaClass::Scenery) == 1 &&
              count(r, mk3::DmaClass::World) == 0 && r.layers.bound_draws[0] == 3, "K6 creators: parts, spray and figure Fighter, counter and countdown Text, code row scenery");
        Rig n; n.Slot(0, kFighter); insert(n, kPart, 0xffa9e7a0, 9, kFighter + 0x10); draw(n, kPart, 0);
        Negative(count(n, mk3::DmaClass::Fighter) == 0, "body part of a non-fighter bound");
        Rig k; k.Slot(0, kFighter); insert(k, kSpray, 0xffa9f190, 10, kPart); draw(k, kSpray, 0);
        Negative(count(k, mk3::DmaClass::Fighter) == 0, "spray from an unbound object bound");
        Rig m; insert(m, kCombo, 0xffa960b0); draw(m, kCombo, 0);
        Negative(count(m, mk3::DmaClass::Text) == 0, "combo counter return off by one instruction classed");
    }
    // 17. K7: the binding is read at the enqueue (a child freed before the DMA-done handler pops its last entry stays
    // Fighter); an effect process started by FFA8C3D0 from a fighter (A8 at the call, FF9270C0 A0 = the process) binds its
    // object (FFA9CB70, A13 = that process); FFA9BFF0 (A10 = fighter) is Fighter; the label FFAA3790 is Text. Negatives:
    // the class read at the pop; an effect process started from a non-fighter; FFA9BFF0 with A10 not a fighter.
    {
        constexpr uint32_t kSp = 0x010ff000, kChild = 0x01095000, kFx = 0x01096000, kProc = 0x01070000, kPart = 0x01097000, kLabel = 0x01098000;
        const auto put = [](Rig& r, uint32_t at, uint32_t v) { const size_t i = (at - 0x01000000) / 16; r.ram[i] = uint16_t(v); r.ram[i + 1] = uint16_t(v >> 16); };
        const auto insert = [&](Rig& r, uint32_t object, uint32_t ret, unsigned reg = 0, uint32_t value = 0) {
            uint32_t a[16] = {object, 0, 0, 0, mk3::ObjectBinder::kWorldList}; a[13] = kProc; a[15] = kSp; if (reg) a[reg] = value;
            put(r, kSp + 0xa0, ret); r.layers.Step(mk3::ObjectBinder::kInsert, a);
        };
        const auto effect = [](Rig& r, uint32_t a8, uint32_t process) {
            uint32_t a[16] = {5}; a[8] = a8; r.layers.Step(mk3::ObjectBinder::kEffect, a);
            a[0] = process; r.layers.Step(mk3::ObjectBinder::kProcessMade, a);
        };
        const auto freed = [&](Rig& r, uint32_t object) {
            put(r, mk3::ObjectBinder::kFreeHead, object); put(r, object, 0);
            const uint32_t a[16] = {}; r.layers.Step(mk3::ObjectBinder::kFreeHeadStores[2], a); r.layers.Step(0xff800010, a);
        };
        const auto count = [](Rig& r, mk3::DmaClass c) { return r.layers.draws[unsigned(c)]; };
        Rig r; r.Slot(0, kFighter);
        insert(r, kChild, 0xffa132d0, 8, kFighter); r.Queued(kWorld, kWorldScroll, kChild); freed(r, kChild); r.Draw(0, 0, 4, 4, 0x0200, 0x40000);
        effect(r, kFighter, kProc); insert(r, kFx, 0xffa9cb70); r.Queued(kWorld, kWorldScroll, kFx); r.Draw(8, 0, 4, 4, 0x0200, 0x40000);
        insert(r, kPart, 0xffa9bff0, 10, kFighter); r.Queued(kWorld, kWorldScroll, kPart); r.Draw(16, 0, 4, 4, 0x0200, 0x40000);
        insert(r, kLabel, 0xffaa3790); r.Queued(kWorld, kWorldScroll, kLabel); r.Draw(24, 0, 4, 4, 0x0200, 0x40000);
        Check(count(r, mk3::DmaClass::Fighter) == 3 && count(r, mk3::DmaClass::Text) == 1 && count(r, mk3::DmaClass::World) == 0 &&
              r.layers.objects.bound.count(kChild) == 0, "K7: freed child drawn as enqueued, effect of a fighter, FFA9BFF0 Fighter, label Text");
        Rig p; p.Slot(0, kFighter);   // negative: the class read at the pop (entry staged without the enqueue capture)
        insert(p, kChild, 0xffa132d0, 8, kFighter); p.Queued(kWorld, kWorldScroll, kChild); freed(p, kChild);
        p.layers.queue.staged[0x01100000].bound = uint8_t(p.layers.objects.bound.count(kChild) ? mk3::DmaClass::Fighter : mk3::DmaClass::None);
        p.Draw(0, 0, 4, 4, 0x0200, 0x40000);
        Negative(count(p, mk3::DmaClass::Fighter) == 0, "child freed before its pop drawn as Fighter when read at the pop");
        Rig e; e.Slot(0, kFighter); effect(e, kFighter + 0x10, kProc); insert(e, kFx, 0xffa9cb70); e.Queued(kWorld, kWorldScroll, kFx);
        e.Draw(0, 0, 4, 4, 0x0200, 0x40000);
        Negative(count(e, mk3::DmaClass::Fighter) == 0, "effect process of a non-fighter bound");
        Rig f; f.Slot(0, kFighter); insert(f, kPart, 0xffa9bff0, 10, kFighter + 0x10); f.Queued(kWorld, kWorldScroll, kPart);
        f.Draw(0, 0, 4, 4, 0x0200, 0x40000);
        Negative(count(f, mk3::DmaClass::Fighter) == 0, "FFA9BFF0 part of a non-fighter bound");
        // FFA1BA60: the parent is the A8 saved on the stack (SP + 0E0h at the insertion). Negative: the fighter one long lower.
        const auto stacked = [&](Rig& g, uint32_t at) {
            g.Slot(0, kFighter); put(g, at, kFighter); insert(g, kPart, 0xffa1ba60); g.Queued(kWorld, kWorldScroll, kPart); g.Draw(0, 0, 4, 4, 0x0200, 0x40000);
        };
        Rig sp; stacked(sp, kSp + 0xe0);
        Check(count(sp, mk3::DmaClass::Fighter) == 1, "K7: FFA1BA60 bound by the A8 saved at SP + 0E0h");
        Rig sq; stacked(sq, kSp + 0xc0);
        Negative(count(sq, mk3::DmaClass::Fighter) == 0, "FFA1BA60 parent read at another stack slot");
        // The text list 0105DC30 appended to 0105DC10 (FF960080, A0 = 105DC30h, A1 = 105DC10h): its objects stay Text.
        // Negative: the same call with another source list.
        const auto move = [&](Rig& g, uint32_t from) {
            put(g, mk3::ObjectBinder::kTextList, kLabel); put(g, kLabel, kChild); put(g, kChild, 0);
            uint32_t a[16] = {from, mk3::ObjectBinder::kWorldList}; g.layers.Step(mk3::ObjectBinder::kTextMove, a);
            g.Queued(kWorld, kWorldScroll, kLabel); g.Draw(0, 0, 4, 4, 0x0200, 0x40000); g.Queued(kWorld, kWorldScroll, kChild); g.Draw(8, 0, 4, 4, 0x0200, 0x40000);
        };
        Rig t; move(t, mk3::ObjectBinder::kTextList);
        Check(count(t, mk3::DmaClass::Text) == 2 && count(t, mk3::DmaClass::World) == 0, "K7: text list moved into 0105DC10 stays Text");
        Rig u; move(u, 0x0105dc50);
        Negative(count(u, mk3::DmaClass::Text) == 0, "move from another list taken as the text list");
    }
    // 18. K8: the effect parent is read at the FFA8C3D0 call: a bound child that calls the effect and is then freed, its
    // object reused for the effect's own (FFA1CA40 -> FFA1CCF0 -> FFA9CB70), binds it; FFA9D8F0 with A10 = that effect
    // object follows. The arena floor tiles FF90D5A0/FF90D6B0/FF90D830 are Scenery. Negatives: an A8 bound only after the
    // call; a floor return one instruction off.
    {
        constexpr uint32_t kSp = 0x010ff000, kChild = 0x01095000, kProc = 0x01070000, kPiece = 0x01096000, kTile = 0x01097000;
        const auto put = [](Rig& r, uint32_t at, uint32_t v) { const size_t i = (at - 0x01000000) / 16; r.ram[i] = uint16_t(v); r.ram[i + 1] = uint16_t(v >> 16); };
        const auto insert = [&](Rig& r, uint32_t object, uint32_t ret, unsigned reg = 0, uint32_t value = 0) {
            uint32_t a[16] = {object, 0, 0, 0, mk3::ObjectBinder::kWorldList}; a[13] = kProc; a[15] = kSp; if (reg) a[reg] = value;
            put(r, kSp + 0xa0, ret); r.layers.Step(mk3::ObjectBinder::kInsert, a);
        };
        const auto effect = [](Rig& r, uint32_t a8) {
            uint32_t a[16] = {5}; a[8] = a8; r.layers.Step(mk3::ObjectBinder::kEffect, a);
            a[0] = kProc; r.layers.Step(mk3::ObjectBinder::kProcessMade, a);
        };
        const auto freed = [&](Rig& r, uint32_t object) {
            put(r, mk3::ObjectBinder::kFreeHead, object); put(r, object, 0);
            const uint32_t a[16] = {}; r.layers.Step(mk3::ObjectBinder::kFreeHeadStores[2], a); r.layers.Step(0xff800010, a);
        };
        const auto draw = [&](Rig& r, uint32_t object, int x) { r.Queued(kWorld, kWorldScroll, object); r.Draw(x, 0, 4, 4, 0x0200, 0x40000); };
        const auto count = [](Rig& r, mk3::DmaClass c) { return r.layers.draws[unsigned(c)]; };
        Rig r; r.Slot(0, kFighter);
        put(r, kSp + 0xe0, kFighter); insert(r, kChild, 0xffa1ba60);   // the projectile, bound by the A8 saved at SP + 0E0h
        effect(r, kChild); freed(r, kChild); insert(r, kChild, 0xffa9cb70); insert(r, kPiece, 0xffa9d8f0, 10, kChild);
        insert(r, kTile, 0xff90d5a0);
        draw(r, kChild, 0); draw(r, kPiece, 8); draw(r, kTile, 16);
        Check(count(r, mk3::DmaClass::Fighter) == 2 && count(r, mk3::DmaClass::Scenery) == 1 && count(r, mk3::DmaClass::World) == 0,
              "K8: effect of a freed, reused bound child Fighter, FFA9D8F0 follows, arena floor tile Scenery");
        Rig n; n.Slot(0, kFighter);
        effect(n, kChild); put(n, kSp + 0xe0, kFighter); insert(n, kChild, 0xffa1ba60); insert(n, kPiece, 0xffa9cb70); draw(n, kPiece, 0);
        Negative(count(n, mk3::DmaClass::Fighter) == 0, "effect parent bound only after the call taken as a fighter");
        Rig t; insert(t, kTile, 0xff90d5b0); draw(t, kTile, 0);
        Negative(count(t, mk3::DmaClass::Scenery) == 0, "floor tile return off by one instruction classed");
        // FFAA2DF0 (A11 = fighter) and FF9A4990 (the fighter A8 saved at SP + 0C0h). Negative: the saved A8 one long higher.
        const auto saved = [&](Rig& g, uint32_t at) {
            g.Slot(0, kFighter); insert(g, kTile, 0xffaa2df0, 11, kFighter); put(g, at, kFighter); insert(g, kPiece, 0xff9a4990);
            draw(g, kTile, 0); draw(g, kPiece, 8);
        };
        Rig s; saved(s, kSp + 0xc0);
        Check(count(s, mk3::DmaClass::Fighter) == 2, "K8: FFAA2DF0 (A11) and FF9A4990 (SP + 0C0h) bound to the fighter");
        Rig q; saved(q, kSp + 0xe0);
        Negative(count(q, mk3::DmaClass::Fighter) == 1, "FF9A4990 parent read at another stack slot");
        Rig b; insert(b, kTile, 0xffa93be0); draw(b, kTile, 0);
        Check(count(b, mk3::DmaClass::Text) == 1, "K8: banner of effect 1Ch (FFA93BE0) Text");
        // 19. K9: the arena 0Ah floor object (FF9125D0, return FF912820) is Scenery, with the fighter in A10.
        // Negative: a return one instruction later (FF912840) stays World.
        Rig k; k.Slot(0, kFighter); insert(k, kTile, 0xff912820, 10, kFighter); draw(k, kTile, 0);
        Check(count(k, mk3::DmaClass::Scenery) == 1 && count(k, mk3::DmaClass::World) == 0, "K9: arena 0Ah floor object (FF912820) Scenery");
        Rig o; o.Slot(0, kFighter); insert(o, kTile, 0xff912840, 10, kFighter); draw(o, kTile, 0);
        Negative(count(o, mk3::DmaClass::Scenery) == 0, "stage floor return one instruction off classed");
        // 20. K10: the two-part banner of effect 2Ah (FFA8E7B0, return FFA8E8E0) is Text. Negative: the return of the
        // position call before the insertion (FFA8E8B0) stays World.
        Rig e; insert(e, kTile, 0xffa8e8e0); draw(e, kTile, 0);
        Check(count(e, mk3::DmaClass::Text) == 1 && count(e, mk3::DmaClass::World) == 0, "K10: banner of effect 2Ah (FFA8E8E0) Text");
        Rig f; insert(f, kTile, 0xffa8e8b0); draw(f, kTile, 0);
        Negative(count(f, mk3::DmaClass::Text) == 0, "effect 2Ah banner return one instruction off classed");
    }
    // 21. Floor blood (mk3_blood.hpp): a splash kept at the world position of its last staged draw, with the colours of
    // its slot at the keep, composed when the pump pops the world pass's first entry, mirrored, following camera and
    // page, covered by later draws, dimmed by the program's fades, hidden off the arena, cleared on round 1 and the arena
    // switch; `frame` canonical.
    {
        using mk3::FloorBlood;
        const auto put = [](Rig& r, uint32_t at, uint32_t v) { const size_t i = (at - 0x01000000) / 16; r.ram[i] = uint16_t(v); r.ram[i + 1] = uint16_t(v >> 16); };
        constexpr uint32_t kSplashA = 0x010a0000, kSplashB = 0x010a1000, kDrop = 0x010a2000, kCursor = 0x01100000;
        constexpr uint32_t kPage1 = 256u << 16 | 56, kPage0 = 0;
        const auto rig = [&](Rig& r) {
            r.layers.palette = &r.palette;
            r.layers.blood.shape.resize(size_t(FloorBlood::kWidth) * FloorBlood::kHeight);
            for (size_t k = 0; k < r.layers.blood.shape.size(); ++k) r.layers.blood.shape[k] = uint8_t(k % 7 == 3 ? 0 : 1 + k % 15);
            r.layers.blood.layer.assign(r.dma.vram.size(), 0);
            for (unsigned s = 0; s < 16; ++s) r.palette[0x0400 + s] = uint16_t(0x0421 * s + 0x1000);
            for (uint32_t o : {kSplashA, kSplashB, kDrop}) { put(r, o + 0x1a0, o == kDrop ? 0xffc839a0 : FloorBlood::kFrame); put(r, o + 0x140, 0x0404); }
            put(r, kSplashB + 0xf0, 0x10);
            put(r, FloorBlood::kArenaShown, 1);
        };
        const auto step = [](Rig& r, uint32_t pc, std::initializer_list<std::pair<unsigned, uint32_t>> regs) {
            uint32_t a[16] = {}; for (const auto& [k, v] : regs) a[k] = v; r.layers.Step(pc, a);
        };
        const auto stage = [&](Rig& r, uint32_t o, uint32_t xy, uint32_t page, uint32_t camera) { step(r, FloorBlood::kEnqueue, {{0, o}, {10, xy}, {5, page}, {4, camera}}); };
        const auto keep = [&](Rig& r, uint32_t o) { step(r, FloorBlood::kKeep, {{8, o}}); };
        const auto walk = [&](Rig& r, uint32_t page, uint32_t camera) {
            put(r, FloorBlood::kPage, page);
            step(r, FloorBlood::kWalk, {{0, FloorBlood::kWorldList}, {1, kCursor + 0xc0}, {4, camera}, {14, 0}, {13, 254u << 16 | 400}});
        };
        const auto shade = [](const Rig& r, int dx, int dy, bool flip) { return r.layers.blood.shape[size_t(dy) * FloorBlood::kWidth + size_t(flip ? FloorBlood::kWidth - 1 - dx : dx)]; };
        const auto stain_ok = [&](const Rig& r, int left, int top, bool flip, uint16_t xor_colour = 0) {
            for (int dy = 0; dy < FloorBlood::kHeight; ++dy) for (int dx = 0; dx < FloorBlood::kWidth; ++dx) {
                const uint8_t s = shade(r, dx, dy, flip);
                const uint16_t want = s ? uint16_t(((0x0421 * s + 0x1000) ^ xor_colour) | 0x8000) : 0;
                if (r.layers.blood.At(size_t(top + dy) * 512 + size_t(left + dx)) != want) return false;
            }
            return true;
        };
        // A: staged on page 1 at (120, 200) with camera (10, 8): world (130, 208). B: mirrored, staged on page 0, DMA start
        // x = 300 (its right column) with camera 0: world left 266, top 100. Then the slot is reused, the pass runs on page 0
        // with camera (20, 0).
        Rig r; rig(r);
        stage(r, kSplashA, (256u + 200) << 16 | (56 + 120), kPage1, 8u << 16 | 10); keep(r, kSplashA);
        stage(r, kSplashB, 100u << 16 | 300, kPage0, 0); keep(r, kSplashB);
        stage(r, kDrop, 50u << 16 | 50, kPage0, 0); keep(r, kDrop);
        for (unsigned s = 0; s < 16; ++s) r.palette[0x0400 + s] = 0x03e0;
        walk(r, kPage0, 20);
        r.pc = mk3::DmaQueue::kPump; r.layers.blood.Pump(kCursor + 0x20, r.layers.stored, r.layers.palette);
        Check(r.layers.blood.stains.size() == 2, "floor blood: the two splashes kept, the drop frame not");
        Check(r.layers.blood.At(208 * 512 + 110) == 0, "floor blood: the pass waits for its own cursor");
        r.layers.blood.Pump(kCursor, r.layers.stored, r.layers.palette);
        Check(stain_ok(r, 110, 208, false) && stain_ok(r, 246, 100, true), "floor blood: world position of the staged draw, camera, mirror, colours at the keep");
        Negative(!stain_ok(r, 111, 208, false) && !stain_ok(r, 246, 100, false) && !stain_ok(r, 110, 208, false, 0x0001),
                 "stain one pixel off, unmirrored or with another colour accepted");
        // Page 1 with the camera at (10, 8): A back at its staged place.
        walk(r, kPage1, 8u << 16 | 10); r.layers.blood.Pump(kCursor, r.layers.stored, r.layers.palette);
        Check(stain_ok(r, 56 + 120, 256 + 200, false), "floor blood: the stain follows the camera onto page 1");
        // A later draw (any class) covers the words it stores; the composed page keeps the rest.
        walk(r, kPage0, 20); r.layers.blood.Pump(kCursor, r.layers.stored, r.layers.palette);
        r.pc = 0xff800000; r.Draw(110, 208, 4, 2, 0x0100, 0, true);
        Check(r.layers.blood.At(208 * 512 + 110) == 0 && r.layers.blood.At(209 * 512 + 113) == 0 && r.layers.blood.At(208 * 512 + 115) != 0,
              "floor blood: a later DMA covers the stain where it draws");
        // Scanout on page 0: the presented frame shows the stain, `frame` and the pens stay canonical, the backdrop unflagged.
        {
            Rig plain(false); Scanout canonical, s; s.layers = &r.layers;
            r.Render(s); plain.palette = r.palette; plain.dma.vram = r.dma.vram; plain.Render(canonical);
            const size_t at = At(121, 210);
            const uint16_t word = r.layers.blood.At(210 * 512 + 121);
            Check(word && s.presentation[at] == Scanout::Rgb(word & 0x7fff) && !(s.backdrop[at] & Scanout::kSceneryRgb),
                  "floor blood: presented colour, unflagged backdrop");
            Check(s.frame == canonical.frame && s.pens == canonical.pens, "floor blood: canonical frame and pens without the stain");
            Negative(s.presentation != s.frame, "presented frame equal to the canonical one");
        }
        // A fade: the palette dims the floor words the stain covers to 45/93 of their brightness, then to black, then
        // restores them, with no pass in between; Present dims the stain with them (rounded per channel) and shows its
        // kept colours again, exactly, once they are back.
        {
            Rig g; rig(g); stage(g, kSplashA, 200u << 16 | 120, kPage0, 0); keep(g, kSplashA);
            for (int dy = 0; dy < FloorBlood::kHeight; ++dy) for (int dx = 0; dx < FloorBlood::kWidth; ++dx) {
                const size_t i = size_t(200 + dy) * 512 + size_t(120 + dx);
                g.dma.vram[i] = g.layers.stored[i] = 0x0010;
            }
            g.palette[0x0010] = 0x7fff; walk(g, kPage0, 0); g.layers.blood.Pump(kCursor, g.layers.stored, g.layers.palette);
            const auto shown = [&] { Scanout s; s.layers = &g.layers; g.Render(s); return s.presentation[At(121, 200)]; };
            const uint16_t kept = uint16_t(0x0421 * shade(g, 1, 0, false) + 0x1000);
            const auto dim = [](unsigned v) { return (v * 45 + 46) / 93; };   // every stain pixel over word 0010h
            const uint32_t half = Scanout::Rgb(uint16_t(dim(kept >> 10 & 31) << 10 | dim(kept >> 5 & 31) << 5 | dim(kept & 31)));
            const bool bright = shown() == Scanout::Rgb(kept);
            g.palette[0x0010] = 0x3def; const bool dimmed = shown() == half;
            g.palette[0x0010] = 0; const bool black = shown() == 0;
            g.palette[0x0010] = 0x7fff;
            Check(bright && dimmed && black && shown() == Scanout::Rgb(kept), "floor blood: Present dims the stain with the floor it covers and restores it exactly");
            g.palette[0x0010] = 0x3def; std::fill(g.layers.blood.floor.begin(), g.layers.blood.floor.end(), uint8_t(0));
            Negative(shown() != half, "stain kept bright through a fade");
        }
        // Off the arena: the pass clears its page and draws nothing.
        put(r, FloorBlood::kArenaShown, 0); walk(r, kPage0, 20); r.layers.blood.Pump(kCursor, r.layers.stored, r.layers.palette);
        Check(r.layers.blood.At(100 * 512 + 250) == 0 && r.layers.blood.stains.size() == 2, "floor blood: hidden off the arena, kept for its fight");
        // Round 2 keeps, round 1 (a new fight) clears; the arena switch clears.
        Rig k; rig(k); stage(k, kSplashA, 200u << 16 | 120, kPage0, 0); keep(k, kSplashA);
        step(k, FloorBlood::kRound, {{0, 2}});
        Check(k.layers.blood.stains.size() == 1, "floor blood: kept across rounds");
        step(k, FloorBlood::kRound, {{0, 1}});
        Check(k.layers.blood.stains.empty(), "floor blood: a new fight clears");
        stage(k, kSplashA, 200u << 16 | 120, kPage0, 0); keep(k, kSplashA); step(k, FloorBlood::kArenaSwitch, {});
        Check(k.layers.blood.stains.empty(), "floor blood: the arena switch clears");
        Rig n; rig(n); keep(n, kSplashA);
        Negative(n.layers.blood.stains.empty(), "splash kept without a staged draw");
        // A fighter texel over a stain keeps the stain as its base (the fighters' underlay); disabled = no stain at all.
        Rig f; rig(f); f.Slot(0, kFighter);
        stage(f, kSplashA, 60u << 16 | 100, kPage0, 0); keep(f, kSplashA); walk(f, kPage0, 0);
        f.Queued(kWorld, kWorldScroll, kFighter); f.Draw(100, 60, 10, 4, 0x0200, 0x40000);
        Scanout fs; fs.layers = &f.layers; f.Render(fs);
        Check(fs.fighters.serial && fs.FighterMismatched() == 0, "floor blood: fighter layers over the stained underlay rebuild the presented frame");
        Rig d; d.layers.palette = &d.palette; stage(d, kSplashA, 0, 0, 0); keep(d, kSplashA);
        Check(!d.layers.blood.enabled() && d.layers.blood.stains.empty(), "floor blood: disabled without the decoded frame");
    }
    std::printf("{\"checks\":%d,\"failures\":%d,\"negatives\":%d,\"detected\":%d}\n", checks, failures, negatives, detected);
    return failures || detected != negatives;
}
} // namespace mk3remaster_tests
