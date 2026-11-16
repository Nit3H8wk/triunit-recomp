// MK3 video timing model: self-checks, then replay of an event file built from Original observations.
// Events (cycles are instruction-start cycles, in non-decreasing order):
//   W c reg data      io_register_w                    R c e reg   io_register_r -> prints the value
//   S c e             debugger-style sample -> prints HCOUNT VCOUNT DPYADR INTPEND
//   D c e cmd w h sx sy in   DMA_COMMAND write (pixels from the DMA registers at that write)
//   (e = cycles the instruction had already counted at the access)
//   I c0 c st         interrupt probe -> prints Vector(st) with the state already replayed up to c0 (the last
//                     instruction before the acceptance), then Vector(st) after Advance(c), plus the DI/INT1
//                     counters and the cycle of the last DI and INT1 timer events.
// Usage: mk3-video [events [pixel_hz]]. One output line per R/S/I event.
#include "mk3_video.hpp"
#include <cinttypes>
#include <cstdio>
#include <fstream>
#include <string>

namespace {
int failures = 0;
void Check(bool ok, const char* what) { if (!ok) { std::fprintf(stderr, "FAIL %s\n", what); ++failures; } }
template <class F> bool Throws(F f) { try { f(); } catch (const std::runtime_error&) { return true; } return false; }

void Program(mk3::VideoTiming& v, uint64_t cycle, uint16_t vtotal = 288) {
    const uint16_t table[] = {43, 101, 501, 505, 3, 20, 274, vtotal, 0xf010, 0xfffc, 274};  // MK3 2.1 table at 0xff81a160
    for (unsigned i = 0; i < 11; ++i) v.Write(i, table[i], cycle + i);
}

void SelfChecks() {
    using V = mk3::VideoTiming;
    V v;
    Check(v.scan == V::Atto(63250) * 1000000000 && v.frame == V::Atto(18279250) * 1000000000, "63.25 us line, 18.27925 ms frame");
    Check(v.Vpos(0) == 274 && v.Hpos(0) == 0 && v.Vpos(15 * v.scan) == 0, "VBLANK start is line 274 at time 0");
    Check(v.Vpos(v.frame - v.pixel) == 273 && v.Hpos(v.frame - v.pixel) == 505, "last pixel of the frame");
    Check(v.TimeUntilPos(0, 274) == v.frame && v.TimeUntilPos(0, 275) == v.scan, "time_until_pos skips the current position");
    v.Advance(0);
    Check(v.io[V::VCOUNT] == 274 && v.scan_expire == 15 * v.scan + 1 && v.scan_param == 0, "slave callback at time 0 latches vpos and waits for line 0");
    Program(v, 2000);
    v.Advance(uint64_t((15 * v.scan) / V::kCycle) - 1);
    Check(v.io[V::VCOUNT] == 274, "line 0 timer not visible one cycle early");
    v.Advance(uint64_t((15 * v.scan) / V::kCycle));
    Check(v.io[V::VCOUNT] == 0 && v.scan_expire == 16 * v.scan, "master counts lines from the programmed table");
    const uint64_t di = uint64_t(v.frame / V::kCycle);  // line 274 of the second frame, 114245.3125 cycles
    Check(v.Read(V::INTPEND, di - 4) == 0, "690 ns before the DPYINT line: no early DI");
    Check(v.Read(V::INTPEND, di - 3) == V::DI && v.io[V::INTPEND] == 0, "530 ns before: DI reported early, not latched");
    Check(v.Vector(V::kStatusIE) == 0, "nothing pending before the line");
    v.Write(V::INTENB, V::DI | V::INT1, di - 2);
    v.Advance(di);
    Check(v.di_count == 1 && v.last_di_cycle == di && v.Vector(V::kStatusIE) == 0xfffffea0u && v.Vector(0) == 0, "DI at floor(T/cycle), gated by IE");
    v.Write(V::INTPEND, uint16_t(~V::DI), di + 1);
    Check(v.io[V::INTPEND] == 0, "writing 0 to DIP clears it");
    v.Write(V::INTPEND, 0xffff, di + 2);
    Check(v.io[V::INTPEND] == 0, "DIP cannot be set by a write");
    v.DmaCommand(di + 10, 0x8000, V::DmaPixels(100, 10, 0, 0, true));  // 41000 ns = 256.25 cycles
    v.Advance(di + 10 + 255);
    Check(v.Vector(V::kStatusIE) == 0, "DMA still running");
    v.Advance(di + 10 + 256);
    Check(v.Vector(V::kStatusIE) == 0xffffffc0u && v.int1_count == 1, "DMA done raises INT1");
    v.DmaCommand(di + 300, 0, 0);
    Check(v.Vector(V::kStatusIE) == 0, "any DMA_COMMAND write drops INT1");
    Check(V::DmaPixels(0x7ff, 2, 0x200, 0x80, true) == (0x3ff00 / 0x200) * (0x200 / 0x80) && V::DmaPixels(9, 9, 0, 0, false) == 0, "scaled and skipped DMA sizes");
    Check(Throws([] { V w; Program(w, 2000, 287); w.Advance(200000); }), "geometry change rejects");
    Check(Throws([] { V w; w.Write(V::HSTCTLH, 0x0100, 5); }) && Throws([] { V w; w.Write(V::HSTCTLL, 0x0080, 5); }), "NMI and the INTOUT edge reject");
}
} // namespace

int main(int argc, char** argv) {
    SelfChecks();
    if (failures) return 1;
    if (argc < 2) { std::puts("self checks passed"); return 0; }
    std::ifstream events(argv[1]);
    if (!events) { std::fprintf(stderr, "cannot open events\n"); return 2; }
    mk3::VideoTiming v(argc > 2 ? uint32_t(std::stoul(argv[2])) : 8000000u);
    char kind;
    uint64_t cycle, last = 0;
    try {
        while (events >> kind >> cycle) {
            if (cycle < last) { std::fprintf(stderr, "events out of order at %" PRIu64 "\n", cycle); return 2; }
            last = cycle;
            unsigned a, b, c, d, e, f;
            if (kind == 'W') { events >> a >> b; v.Write(a, uint16_t(b), cycle); }
            else if (kind == 'R') { events >> e >> a; std::printf("%u\n", unsigned(v.Read(a, cycle, e))); }
            else if (kind == 'S') {
                events >> e;
                const unsigned h = v.Read(v.HCOUNT, cycle, e), p = v.Read(v.INTPEND, cycle, e);
                std::printf("%u %u %u %u\n", h, unsigned(v.io[v.VCOUNT]), unsigned(v.io[v.DPYADR]), p);
            } else if (kind == 'D') { unsigned g; events >> e >> a >> b >> c >> d >> f >> g; v.DmaCommand(cycle, uint16_t(a), v.DmaPixels(uint16_t(b), uint16_t(c), uint16_t(d), uint16_t(f), g != 0), e); }
            else if (kind == 'I') {
                uint64_t boundary; uint32_t status;
                events >> boundary >> status;
                const uint32_t before = v.Vector(status);
                v.Advance(boundary);
                last = boundary;
                std::printf("%u %u %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64 "\n", unsigned(before), unsigned(v.Vector(status)), v.di_count, v.last_di_cycle, v.int1_count, v.last_int1_cycle);
            } else { std::fprintf(stderr, "unknown event %c\n", kind); return 2; }
        }
    } catch (const std::runtime_error& error) {
        std::printf("REJECT %" PRIu64 " %s\n", last, error.what());
    }
    return 0;
}
