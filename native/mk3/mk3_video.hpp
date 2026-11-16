// MK3 2.1 (Wolf-Unit) TMS34010 video timing and interrupt sources, isolated from the CPU executor.
// Contract: MAME 0.280 as archived in docs/investigation (S = sources/tms34010.cpp, SCR = decoder-research/
// upstream/screen.cpp, SCH = decoder-research/upstream/schedule.cpp, W = sources/midwunit.cpp,
// V = sources/midtunit_v.cpp). Time is exact attoseconds, as attotime; a "cycle" is one TMS34010 cycle
// (50 MHz / 8 = 160 ns, W:630). A `cycle` argument is the start cycle of the instruction doing the access;
// `elapsed` is what that instruction had already counted at the access (machine().time() runs ahead inside
// MMTM/MMFM, upstream/34010ops.hxx:670-693: write n lands at start + 2 + 4n), 0 for single-access moves.
//
// Timer rule (SCH:430-501): a CPU is only run while target - localtime >= one cycle and then for
// floor(delta / cycle) cycles, so a timer expiring at T has fired before the instruction that starts at the
// first boundary c >= floor(T / cycle). Advance(c) fires everything due by that rule.
// Not modelled, rejected with an exception: any screen reconfiguration (screen.cpp configure re-arms the screen
// timers), interlace, NMI, host-interrupt edges and halt bits. No register write re-arms the scanline timer (S:1247-1366):
// timing registers are sampled when the callback runs.
#pragma once
#include <array>
#include <cstdint>
#include <functional>
#include <stdexcept>

namespace mk3 {

struct VideoTiming {
    // shortcut: __int128 (GCC/Clang) holds attoseconds exactly; use a seconds+attoseconds pair if MSVC is needed.
    using Atto = __int128;
    enum Reg { HESYNC, HEBLNK, HSBLNK, HTOTAL, VESYNC, VEBLNK, VSBLNK, VTOTAL, DPYCTL, DPYSTRT, DPYINT, CONTROL,
               HSTDATA, HSTADRL, HSTADRH, HSTCTLL, HSTCTLH, INTENB, INTPEND, CONVSP, CONVDP, PSIZE, PMASK,
               DPYTAP = 27, HCOUNT, VCOUNT, DPYADR, REFCNT };
    enum : uint16_t { INT1 = 0x0002, INT2 = 0x0004, HI = 0x0200, DI = 0x0400, WV = 0x0800 };  // tms34010.h:99-103
    static constexpr uint32_t kStatusIE = 1u << 21;                 // upstream/tms34010.cpp:131
    static constexpr int kInterruptCycles = 16;                     // S:704; pushes PC then ST, ST = 0x10 (S:700-702)
    static constexpr Atto kSecond = Atto(1000000000) * 1000000000;
    static constexpr Atto kCycle = kSecond / (50000000 / 8);        // W:630, TMS34010 clock divider 8
    static constexpr int kWidth = 506, kHeight = 289, kVisTop = 20, kVisBottom = 273, kVisLeft = 101, kVisRight = 500;  // W:647 set_raw
    static constexpr int kPixelsPerClock = 1;                       // W:634

    Atto pixel, scan, frame;                // SCR:475-477 from screen.h:207 (m_frame_period, m_scantime, m_pixeltime)
    std::array<uint16_t, 32> io{};          // m_IOregs, zero at reset (S:795)
    Atto scan_expire = 0;                   // m_scantimer: armed for time 0, param 0 (S:743-744)
    int scan_param = 0;
    bool dma_armed = false;                 // midtunit_video_device m_dma_timer
    Atto dma_expire = 0;
    // Each timer event with the first boundary able to see it. dma_done also clears DMA_COMMAND bit 15 (V:630):
    // the owner of the DMA registers applies that whenever int1_count advances.
    uint64_t di_count = 0, last_di_cycle = 0, int1_count = 0, last_int1_cycle = 0;
    int hblank_stable = 0;                  // m_hblank_stable (S:1083)
    // screen().update_partial(vcount) (S:1094-1097): called inside the visible area, after the DPYADR reload and
    // before its DUDATE step, with the registers as the scanline callback sees them (mk3_scanout.hpp). Optional.
    std::function<void(int vcount)> update_partial;

    explicit VideoTiming(uint32_t pixel_hz = 8000000)               // W:625 PIXEL_CLOCK
        : pixel(kSecond / pixel_hz), scan(pixel * kWidth), frame(pixel * kWidth * kHeight) {}

    static Atto At(uint64_t cycle) { return Atto(cycle) * kCycle; }

    // screen_device::vpos / hpos (SCR:1013-1060). m_vblank_start_time is always a multiple of the frame
    // period here, and the "delta < 0" branch equals the previous frame's last scanline, so both are
    // functions of the time modulo the frame.
    int Vpos(Atto t) const { return int((kVisBottom + 1 + ((t + pixel / 2) % frame) / scan) % kHeight); }
    int Hpos(Atto t) const { return int((((t + pixel / 2) % frame) % scan) / pixel); }

    // screen_device::time_until_pos(vpos, 0) (SCR:1069-1091).
    Atto TimeUntilPos(Atto now, int vpos) const {
        const Atto current = now % frame;
        Atto target = Atto((vpos + kHeight - (kVisBottom + 1)) % kHeight) * scan;
        if (target <= current + pixel / 2) target += frame;
        while (target <= current) target += frame;
        return target - current;
    }

    // tms340x0_device::scanline_callback (S:999-1134), TMS34010 branches only.
    void Scanline() {
        const Atto now = scan_expire;
        int vcount = scan_param;
        const bool enabled = io[DPYCTL] & 0x8000, master = io[DPYCTL] & 0x2000;
        const int vsblnk = io[VSBLNK], veblnk = io[VEBLNK];
        int vtotal = io[VTOTAL];
        if (!master) {
            if (vtotal > kHeight - 1) vtotal = kHeight - 1;
            vcount = Vpos(now);
        }
        io[VCOUNT] = uint16_t(vcount);
        if (enabled && vcount == io[DPYINT]) {  // S:1023-1027 -> internal_interrupt_callback (S:846-856)
            io[INTPEND] |= DI;
            ++di_count;
            last_di_cycle = uint64_t(now / kCycle);
        }
        if (vcount == vsblnk) io[DPYADR] = io[DPYSTRT];  // S:1030-1037
        if (vcount == vtotal && master && io[HTOTAL] > 0 && vtotal > 0) {  // S:1048-1093
            const int width = (io[HTOTAL] + 1) * kPixelsPerClock, height = vtotal + 1;
            const int min_x = io[HEBLNK] * kPixelsPerClock, max_x = io[HSBLNK] * kPixelsPerClock - 1, min_y = veblnk, max_y = vsblnk - 1;
            // S:1073-1083: configure() runs on a geometry change, or on a horizontal change once HEBLNK/HSBLNK were
            // stable for a few frames; the current visarea is midwunit's set_raw 101..500.
            if (min_x < max_x && max_x <= width && min_y < max_y && max_y <= height) {
                if (width != kWidth || height != kHeight || min_y != kVisTop || max_y != kVisBottom ||
                    (hblank_stable > 2 && (min_x != kVisLeft || max_x != kVisRight)))
                    throw std::runtime_error("MK3 video: unmodelled screen reconfiguration");
                ++hblank_stable;
            }
            if (!(io[DPYCTL] & 0x4000)) throw std::runtime_error("MK3 video: interlace is unsupported by the reference");
        }
        if (update_partial && vcount >= kVisTop && vcount <= kVisBottom) update_partial(vcount);
        if (vcount >= veblnk && vcount < vsblnk) {  // S:1100-1111
            uint16_t dpyadr = io[DPYADR];
            if ((dpyadr & 3) == 0) dpyadr = uint16_t(((dpyadr & 0xfffc) - (io[DPYCTL] & 0x03fc)) | (io[DPYSTRT] & 0x0003));
            else dpyadr = uint16_t((dpyadr & 0xfffc) | ((dpyadr - 1) & 3));
            io[DPYADR] = dpyadr;
        }
        if (++vcount > vtotal) vcount = 0;  // S:1127-1133
        scan_expire = now + TimeUntilPos(now, vcount) + (master ? 0 : 1);
        scan_param = vcount;
    }

    // tms340x0_device::execute_set_input (S:817-838); line 0 = INT1 = DMA (W:628), line 1 = INT2.
    void SetLine(int line, bool state) {
        const uint16_t bit = line == 0 ? INT1 : INT2;
        io[INTPEND] = uint16_t(state ? io[INTPEND] | bit : io[INTPEND] & ~bit);
    }

    // The earliest armed timer of this device and its callback; a scheduler that fires timers itself uses these.
    Atto NextExpire() const { return dma_armed && dma_expire < scan_expire ? dma_expire : scan_expire; }
    void FireNext() {
        if (dma_armed && dma_expire < scan_expire) {  // midtunit_video_device::dma_done (V:628-632)
            dma_armed = false;
            SetLine(0, true);
            ++int1_count;
            last_int1_cycle = uint64_t(dma_expire / kCycle);
        } else Scanline();
    }
    void Advance(uint64_t cycle) { while (uint64_t(NextExpire() / kCycle) <= cycle) FireNext(); }

    // tms34010_device::io_register_r (S:1550-1589).
    uint16_t Read(unsigned offset, uint64_t cycle, unsigned elapsed = 0) {
        Advance(cycle);
        const Atto now = At(cycle + elapsed);
        switch (offset & 31) {
        case HCOUNT: {
            const int total = io[HTOTAL] + 1;
            int result = Hpos(now) * total / kWidth + io[HEBLNK];
            if (result > total) result -= total;
            return uint16_t(result);
        }
        case REFCNT: return uint16_t(((cycle + elapsed) / 16) & 0xfffc);
        case INTPEND:  // DI reported early when the DPYINT line starts within from_hz(40000000/8/3) (S:1582-1584)
            return uint16_t(io[INTPEND] | (io[VCOUNT] + 1 == io[DPYINT] && scan_expire - now < kSecond / (40000000 / 8 / 3) ? DI : 0));
        }
        return io[offset & 31];
    }

    // tms34010_device::io_register_w (S:1247-1366): the stored value and the interrupt-side rules. CONTROL,
    // PSIZE, CONVSP/CONVDP and DPYCTL also drive CPU drawing state, which stays with the executor. After an
    // INTENB write the caller must test Vector() inside the same instruction (S:1344-1346).
    void Write(unsigned offset, uint16_t data, uint64_t cycle) {
        Advance(cycle);
        offset &= 31;
        const uint16_t old = io[offset];
        io[offset] = data;
        switch (offset) {
        case HSTCTLH:
            if (data & 0x8100) throw std::runtime_error("MK3 video: unmodelled halt/NMI request");
            break;
        case HSTCTLL: {  // S:1302-1333, TMS side: MSGOUT/INTOUT set, INTIN cleared; INTOUT/INTIN edges are not modelled
            const uint16_t next = uint16_t(((old & 0xff8f) | (data & 0x0070) | (data & 0x0080)) & (data | ~0x0008));
            if ((old ^ next) & 0x0088) throw std::runtime_error("MK3 video: unmodelled host interrupt edge");
            io[offset] = next;
            break;
        }
        case INTPEND:  // S:1348-1356: only zeros written to WVP and DIP land
            io[offset] = uint16_t(old & ~((~data) & (WV | DI)));
            break;
        }
    }

    // tms340x0_device::check_interrupt (S:619-706): the vector that would be taken now, or 0. Called by the
    // reference at the start of every timeslice (S:882), i.e. right after any timer fired, and from EINT,
    // POPST, PUTST, RETI (SET_ST, upstream/tms34010.cpp:218-222), INTENB writes and restartable PIXBLTs.
    uint32_t Vector(uint32_t status) const {
        if (io[HSTCTLH] & 0x0100) throw std::runtime_error("MK3 video: unmodelled NMI");
        const uint16_t irq = io[INTPEND] & io[INTENB];
        if (!(status & kStatusIE) || !irq) return 0;
        if (irq & HI) return 0xfffffec0u;
        if (irq & DI) return 0xfffffea0u;
        if (irq & WV) return 0xfffffe80u;
        if (irq & INT1) return 0xffffffc0u;
        if (irq & INT2) return 0xffffffa0u;
        return 0;
    }

    // midtunit_video_device::dma_w pixel count for the done timer (V:731-741, 815-835, skipdma V:761-767).
    static int DmaPixels(uint16_t width, uint16_t height, uint16_t scale_x, uint16_t scale_y, bool source_in_range) {
        if (!source_in_range) return 0;
        const int w = width & 0x3ff, h = height & 0x3ff, xstep = scale_x ? scale_x : 0x100, ystep = scale_y ? scale_y : 0x100;
        return xstep == 0x100 && ystep == 0x100 ? w * h : ((w << 8) / xstep) * ((h << 8) / ystep);
    }

    // Any DMA_COMMAND write (V:713-721, 839): the IRQ line drops; with bit 15 the done timer is (re)armed
    // 41 ns per pixel after the write. A write without bit 15 leaves a running timer.
    void DmaCommand(uint64_t cycle, uint16_t command, int pixels, unsigned elapsed = 0) {
        Advance(cycle);
        SetLine(0, false);
        if (!(command & 0x8000)) return;
        dma_armed = true;
        dma_expire = At(cycle + elapsed) + Atto(41) * pixels * 1000000000;
    }
};

} // namespace mk3
