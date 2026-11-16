// MK3 scanout (native/mk3/mk3_scanout.hpp) driven by VideoTiming's scanline timer over two frames of the Wolf-Unit
// raster, against expectations written directly from get_display_params / midtunit scanline_update (rowaddr from
// DPYADR before its DUDATE step, column from DPYTAP, pens & 0x7fff, black pen outside HEBLNK..HSBLNK-1 and on a
// disabled display), with negative controls. Synthetic registers and memory; no Original capture.
#include "mk3_scanout.hpp"
#include <cstdio>
#include <string>

namespace {
int failures = 0;
void Check(bool ok, const char* what) { if (!ok) { std::fprintf(stderr, "FAIL %s\n", what); ++failures; } }

struct Rig {
    mk3::VideoTiming v;
    mk3::Scanout s;
    std::vector<uint16_t> vram = std::vector<uint16_t>(0x80000);
    int frame_lines = 0;
    std::vector<uint16_t> frame2;   // pens of the visible area when line 273 of the second frame is rendered
    explicit Rig(uint16_t dpyctl) {
        using V = mk3::VideoTiming;
        for (size_t i = 0; i < vram.size(); ++i) vram[i] = uint16_t((i * 13 + 7) & 0xffff);
        auto& io = v.io;
        io[V::HTOTAL] = 505; io[V::HEBLNK] = 101; io[V::HSBLNK] = 501; io[V::HESYNC] = 20;
        io[V::VTOTAL] = 288; io[V::VEBLNK] = 20; io[V::VSBLNK] = 274; io[V::VESYNC] = 3;
        io[V::DPYCTL] = dpyctl; io[V::DPYSTRT] = 0xfff0; io[V::DPYTAP] = 3; io[V::DPYINT] = 300;
        v.update_partial = [this](int vcount) {
            s.Line(vcount, v.io, vram);
            if (vcount == 273 && ++frame_lines == 2) frame2 = s.pens;
            if (vcount == 273) s.ResetPartial();   // stands in for the scanline-0 timer of the screen
        };
    }
};

uint16_t Expected(const Rig& r, int y, int x, int mutation) {
    if (!(r.v.io[mk3::VideoTiming::DPYCTL] & 0x8000) || x < 101 || x >= 501) return mk3::Scanout::kBlackPen;
    // second frame: DPYADR = DPYSTRT at vcount 274, one DUDATE (0x10) step per line from 20, sampled before the step
    const uint16_t dpyadr = uint16_t(0xfff0 - 0x10 * (y - 20 + (mutation == 1 ? 1 : 0)));
    const unsigned row = ((dpyadr >> 4) << 9) & 0x3fe00, col = (3u << 1) + unsigned(x - 101) + (mutation == 2 ? 1 : 0);
    return uint16_t(r.vram[row + (col & 0x1ff)] & (mutation == 3 ? 0xffff : 0x7fff));
}
}

int main() {
    unsigned compared = 0;
    for (const uint16_t dpyctl : {uint16_t(0xe410), uint16_t(0x6410)}) {   // enabled / disabled; NIL, master, SRE, DUDATE 0x10
        Rig r(dpyctl);
        r.v.Advance(2 * 114300);
        Check(r.frame2.size() == r.s.pens.size(), "second frame rendered");
        if (r.frame2.empty()) continue;
        int detected = 0;
        for (int mutation = 0; mutation <= 3; ++mutation) {
            bool same = true;
            for (int y = 20; y <= 273; ++y)
                for (int x = 101; x <= 500; ++x) {
                    const bool equal = r.frame2[size_t(y) * 506 + x] == Expected(r, y, x, mutation);
                    if (!mutation) { ++compared; if (!equal) { same = false; } } else same &= equal;
                }
            if (!mutation) Check(same, dpyctl & 0x8000 ? "enabled frame pens" : "disabled frame is black");
            else if (!same) detected |= 1 << mutation;
        }
        if (dpyctl & 0x8000) Check(detected == 0b1110, "negative controls: DPYADR after the step, column +1, unmasked pen");
    }
    // Present: xRGB_555 through pal5bit, black pen to black, visible area only
    {
        mk3::Scanout s;
        std::vector<uint16_t> palette(0x8000);
        palette[0x1234] = 0x7c1f;   // R 31, G 0, B 31
        s.pens[size_t(20) * 506 + 101] = 0x1234;
        s.pens[size_t(273) * 506 + 500] = 0x1234;
        s.Present(palette);
        Check(s.frame[0] == 0xff00ff && s.frame.back() == 0xff00ff && s.frame[1] == 0 && s.frames == 1, "Present: palette at frame_update");
        std::vector<uint16_t> io_vram(0x80000);
        std::array<uint16_t, 32> io{};
        io[mk3::VideoTiming::DPYCTL] = 0x8000; io[mk3::VideoTiming::HEBLNK] = 0; io[mk3::VideoTiming::HSBLNK] = 507;
        bool threw = false;
        try { s.Line(30, io, io_vram); } catch (const std::runtime_error&) { threw = true; }
        Check(threw, "HSBLNK past the bitmap rejects");
        s.ResetPartial();
        io[mk3::VideoTiming::HSBLNK] = 200;
        s.Line(25, io, io_vram);   // clip 20..25: only its first row (20) is drawn (tms340x0_ind16 uses cliprect.min_y)
        Check(s.pens[size_t(20) * 506 + 150] == 0 && s.pens[size_t(25) * 506 + 150] == mk3::Scanout::kBlackPen && s.last_partial_scan == 26,
              "update_partial over several lines draws the clip's first row");
    }
    std::printf("{\"compared_pens\":%u,\"failures\":%d}\n", compared, failures);
    return failures ? 1 : 0;
}
