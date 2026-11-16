#pragma once
#include "mk3_reset.hpp"
#include <array>
#include <stdexcept>
#include <string>

namespace mk3 {
// TMS34010 PIXBLT B,XY (opcodes 0x0fa0-0x0faf) as the pinned MAME 0.280 core executes it:
// 34010gfx.hxx pixblt_b_xy -> pixblt_b_8_op0_trans (FUNCTION_NAME(pixblt_b)), compute_pixblt_b_cycles, DXYTOL.
// Verified scope: PSIZE 8, CONTROL rop 0 with transparency, window mode 0, DPYCTL.SRT clear, PMASK 0.
// Anything else rejects before touching the bus. Source reads must stay in program ROM, destination in VRAM.
struct PixbltProgress { int32_t remaining = 0; };  // MAME m_gfxcycles while ST.P is set.
struct PixbltStep { unsigned cycles = 0; bool completed = false; };

[[noreturn]] inline void RejectPixblt(uint32_t pc, const char* why, uint32_t value) {
    throw std::runtime_error(std::string("MK3 PIXBLT B,XY ") + why + "; PC " + std::to_string(pc) + "; value " + std::to_string(value));
}

// One execution at s.pc. budget = MAME m_icount at the opcode (cycles left in the CPU timeslice, >= 1).
// On !completed the caller keeps s.pc (MAME m_pc -= 0x10) and re-executes; on completed it continues at s.pc + 16.
// Bus: uint16_t Read16(uint32_t bit), void Write16(uint32_t bit, uint16_t) (mk3::Ops: Wolf-Unit VRAM/ROM, records writes).
template <class Bus>
PixbltStep PixbltBinaryXY(Bus& bus, const std::array<uint16_t, 32>& io, ResetTrace& s, PixbltProgress& progress, int32_t budget) {
    constexpr uint32_t kP = 1u << 25;
    constexpr int bpp = 8, per_word = 16 / bpp;
    constexpr uint16_t pixel_mask = (1u << bpp) - 1;
    if (budget < 1) RejectPixblt(s.pc, "needs a positive timeslice budget", uint32_t(budget));
    auto& b = s.b;
    if (!(s.status & kP)) {
        const uint16_t control = io[11], psize = io[21], convdp_reg = io[20];
        if (psize != 8) RejectPixblt(s.pc, "PSIZE outside verified scope", psize);
        if ((control >> 10) & 0x1f) RejectPixblt(s.pc, "raster op outside verified scope", control);
        if (!(control & 0x20)) RejectPixblt(s.pc, "opaque mode outside verified scope", control);
        if ((control >> 6) & 3) RejectPixblt(s.pc, "window checking outside verified scope", control);
        if (io[8] & 0x0800) RejectPixblt(s.pc, "shift-register transfer mode outside verified scope", io[8]);
        if (io[22]) RejectPixblt(s.pc, "plane mask outside verified scope (MAME ignores it)", io[22]);
        if (!convdp_reg) RejectPixblt(s.pc, "CONVDP never written (m_convdp unknown)", convdp_reg);
        const uint32_t convdp = 1u << (~convdp_reg & 0x1f), shift = 3;  // io_register_w CONVDP / PSIZE 8.
        uint32_t saddr = b[0];
        const int dx = int16_t(b[7]), dy = int16_t(b[7] >> 16);
        int32_t gfx = 4 + 2;  // window mode 0: apply_window returns 0.
        uint32_t daddr = uint32_t(int32_t(int16_t(b[2] >> 16))) * convdp + (uint32_t(int32_t(int16_t(b[2]))) << shift) + b[4];
        daddr &= ~uint32_t(bpp - 1);
        if (dx <= 0 || dy <= 0) return {0, true};  // MAME returns before ST.P and before eating cycles.
        int left = (per_word - int((daddr & 15) / bpp)) & (per_word - 1);
        int right = int(((daddr + uint32_t(dx * bpp)) & 15) / bpp);
        int full = dx - left - right;
        if (full < 0) { left = dx; right = full = 0; }
        else full /= per_word;
        const int words = full + (left != 0) + (right != 0);
        gfx += (words * 4 + words * bpp / 16 * 2) * dy + 2;  // op0_trans PIXEL_OP_TIMING 4.
        for (int y = 0; y < dy; ++y) {  // Pre-check every address so a rejection leaves the bus untouched.
            const uint32_t src = saddr + uint32_t(y) * b[1], dst = daddr + uint32_t(y) * b[3];  // 32-bit wrap as in MAME.
            if (src < kProgramBaseBit || uint64_t(src & ~15u) + ((src & 15) + uint64_t(dx)) / 16 * 16 > 0xfffffff0)
                RejectPixblt(s.pc, "source outside program ROM", src);
            if (uint64_t(dst & ~15u) + uint64_t(words) * 16 > 0x00400000) RejectPixblt(s.pc, "destination outside VRAM", dst);
        }
        s.status |= kP;
        const uint16_t color0 = uint16_t(b[8]), color1 = uint16_t(b[9]);
        for (int y = 0; y < dy; ++y) {
            uint32_t sword = saddr >> 4, dword = daddr >> 4;
            uint16_t src = bus.Read16(sword++ << 4), srcmask = uint16_t(1u << (saddr & 15));
            auto put = [&](int count, uint16_t dstmask) {
                uint16_t dst = bus.Read16(dword << 4);  // Transparency always fetches the destination word.
                for (int x = 0; x < count; ++x) {
                    const uint16_t pixel = uint16_t((src & srcmask ? color1 : color0) & dstmask);
                    if (pixel) dst = uint16_t((dst & ~dstmask) | pixel);
                    srcmask = uint16_t(srcmask << 1);
                    if (!srcmask) { src = bus.Read16(sword++ << 4); srcmask = 1; }
                    dstmask = uint16_t(dstmask << bpp);
                }
                bus.Write16(dword++ << 4, dst);
            };
            if (left) put(left, uint16_t(pixel_mask << (daddr & 15)));
            for (int w = 0; w < full; ++w) put(per_word, pixel_mask);
            if (right) put(right, pixel_mask);
            saddr += b[1]; daddr += b[3];
        }
        progress.remaining = gfx;
    } else if (progress.remaining <= 0) {
        RejectPixblt(s.pc, "ST.P set without native PIXBLT progress", s.status);
    }
    if (progress.remaining > budget) { progress.remaining -= budget; return {unsigned(budget), false}; }
    const unsigned cycles = unsigned(progress.remaining);
    progress.remaining = 0;
    s.status &= ~kP;
    const int16_t rows = int16_t(b[7] >> 16);
    b[0] += uint32_t(int32_t(rows)) * b[1];
    b[2] = (b[2] & 0xffffu) | uint32_t(uint16_t(int16_t(b[2] >> 16) + rows)) << 16;
    return {cycles, true};
}
}
