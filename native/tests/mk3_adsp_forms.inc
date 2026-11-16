// Per-form checks of the ADSP forms closed by the linear PM sweep (tools/mk3/generate_adsp.py), included by
// mk3_adsp_tests.cpp ("forms" mode). The reference side is a separate transcription of the pinned 2100ops.hxx /
// adsp2100.cpp (shift_op, shift_op_imm, DIVS, DIVQ, modify flag out) on a plain register struct; each negative control
// is a one-rule mutation of that transcription that must be detected. Profile and busy-loop checks run on the real U2.
namespace mk3 {
struct AdspFormTest {
    struct Ref { uint16_t si, ar, mr0, mr1, mr2, sr0, sr1, ax0, ax1, ay0, ay1, af, astat; int16_t se, sb; };
    static uint32_t Lcg(uint64_t& s) { s = s * 6364136223846793005ull + 1442695040888963407ull; return uint32_t(s >> 33); }
    static int Clz(uint32_t v) { return v ? __builtin_clz(v) : 32; }

    // 2100ops.hxx shift_op (count = SE) / shift_op_imm; mutation: 1 NORM(HI) without the carry, 2 EXP(LO) without the
    // SE = -15 guard, 3 EXPADJ against +SB, 4 immediate EXP executed.
    static void RefShift(Ref& c, unsigned fn, unsigned x, int8_t sc, bool imm, int mutation) {
        const uint16_t* regs[8] = {&c.si, &c.si, &c.ar, &c.mr0, &c.mr1, &c.mr2, &c.sr0, &c.sr1};
        const uint16_t ux = *regs[x]; const int16_t sx = int16_t(ux);
        uint32_t sr = uint32_t(c.sr1) << 16 | c.sr0, res = 0;
        int32_t xop;
        if (imm && fn >= 12 && mutation != 4) return;
        switch (fn) {
        case 0: case 1: xop = int32_t(uint32_t(ux) << 16);
            res = sc > 0 ? (sc < 32 ? uint32_t(xop) << sc : 0) : (sc > -32 ? uint32_t(xop) >> -sc : 0); break;
        case 2: case 3: xop = ux; res = sc > 0 ? (sc < 32 ? uint32_t(xop) << sc : 0) : (sc > -32 ? uint32_t(xop) >> -sc : 0); break;
        case 4: case 5: case 6: case 7:
            xop = fn < 6 ? int32_t(uint32_t(int32_t(sx)) << 16) : sx;
            res = sc > 0 ? (sc < 32 ? uint32_t(xop) << sc : 0) : (sc > -32 ? uint32_t(xop >> -sc) : uint32_t(xop >> 31)); break;
        case 8: case 9:
            xop = int32_t(uint32_t(int32_t(sx)) << 16);
            if (sc > 0) {
                xop = int32_t((uint32_t(xop) >> 1) | (mutation == 1 ? 0 : uint32_t(c.astat & 0x08) << 28));
                res = uint32_t(xop >> ((sc - 1) & 31));
            } else res = sc > -32 ? uint32_t(xop) << -sc : 0;
            break;
        case 10: case 11: xop = ux; res = sc > 0 ? (sc < 32 ? uint32_t(xop) >> sc : 0) : (sc > -32 ? uint32_t(xop) << -sc : 0); break;
        case 12: case 13:
            if (fn == 13 && (c.astat & 0x04)) { c.se = 1; c.astat = uint16_t(sx < 0 ? c.astat & ~0x80 : c.astat | 0x80); return; }
            if (sx < 0) { c.astat |= 0x80; c.se = int16_t(-(Clz(~uint32_t(int32_t(sx))) - 16 - 1)); }
            else { c.astat &= ~0x80; c.se = int16_t(-(Clz(uint32_t(int32_t(sx))) - 16 - 1)); }
            return;
        case 14:
            if (c.se == -15 || mutation == 2) c.se = int16_t(-(Clz(uint32_t(((c.astat & 0x80) ? ~int32_t(sx) : int32_t(sx)) & 0xffff)) - 1));
            return;
        default: {
            const int r = Clz(uint32_t(sx < 0 ? ~int32_t(sx) : int32_t(sx))) - 16 - 1;
            if (mutation == 3 ? r < c.sb : r < -c.sb) c.sb = int16_t(-r);
            return;
        }
        }
        sr = (fn & 1) ? sr | res : res;
        c.sr0 = uint16_t(sr); c.sr1 = uint16_t(sr >> 16);
    }
    // adsp2100.cpp DIVS / DIVQ; mutation 5: DIVQ with the Q test inverted, 6: DIVS quotient bit from ~temp.
    static void RefDiv(Ref& c, bool q, unsigned x, unsigned y, int mutation) {
        const uint16_t xs[8] = {c.ax0, c.ax1, c.ar, c.mr0, c.mr1, c.mr2, c.sr0, c.sr1}, ys[4] = {c.ay0, c.ay1, c.af, 0};
        if (!q) {
            const uint32_t xop = xs[x], yop = ys[y], temp = xop ^ yop;
            c.astat = uint16_t((c.astat & ~0x20) | ((temp >> 10) & 0x20));
            c.af = uint16_t((yop << 1) | (c.ay0 >> 15));
            c.ay0 = uint16_t((c.ay0 << 1) | ((mutation == 6 ? ~temp : temp) >> 15 & 1));
        } else {
            const int xop = xs[x];
            const bool qf = (c.astat & 0x20) != 0;
            const int res = (mutation == 5 ? !qf : qf) ? c.af + xop : c.af - xop;
            const uint32_t temp = uint32_t(res ^ xop);
            c.astat = uint16_t((c.astat & ~0x20) | ((temp >> 10) & 0x20));
            c.af = uint16_t((uint32_t(res) << 1) | (c.ay0 >> 15));
            c.ay0 = uint16_t((c.ay0 << 1) | ((~temp >> 15) & 1));
        }
    }
    static void Load(Dcs8k& d, const Ref& r) {
        auto& c = d.core_;
        c.si = r.si; c.ar = r.ar; c.mr0 = r.mr0; c.mr1 = r.mr1; c.mr2 = r.mr2; c.sr0 = r.sr0; c.sr1 = r.sr1;
        c.ax0 = r.ax0; c.ax1 = r.ax1; c.ay0 = r.ay0; c.ay1 = r.ay1; c.af = r.af; c.se = uint16_t(r.se); c.sb = uint16_t(r.sb);
        d.astat_ = r.astat;
    }
    static bool Same(const Dcs8k& d, const Ref& r) {
        const auto& c = d.core_;
        return c.sr0 == r.sr0 && c.sr1 == r.sr1 && int16_t(c.se) == r.se && int16_t(c.sb) == r.sb && d.astat_ == r.astat &&
               c.af == r.af && c.ay0 == r.ay0;
    }
    static Ref Random(uint64_t& s) {
        Ref r{};
        uint16_t* w[] = {&r.si, &r.ar, &r.mr0, &r.mr1, &r.mr2, &r.sr0, &r.sr1, &r.ax0, &r.ax1, &r.ay0, &r.ay1, &r.af};
        for (auto* p : w) { const uint32_t v = Lcg(s); *p = uint16_t(v & 3 ? v : (v & 4 ? 0 : 0xffff)); }
        r.astat = uint16_t(Lcg(s) & 0xff);
        r.se = int16_t(int8_t(Lcg(s) % 5 == 0 ? -15 : Lcg(s)));
        r.sb = int16_t(int32_t(Lcg(s) % 32) - 16);
        return r;
    }

    // Returns {cases, failures, negatives detected (bitmask of mutations 1..6)}.
    static std::array<uint64_t, 3> Run(const std::vector<uint8_t>& u2) {
        Dcs8k d(u2);
        uint64_t seed = 0x6d6b33, cases = 0, failures = 0, detected = 0;
        for (int mutation = 0; mutation <= 6; ++mutation)
            for (unsigned fn = 0; fn < 16; ++fn)
                for (unsigned x = 0; x < 8; ++x)
                    for (int k = 0; k < 600; ++k) {
                        const Ref start = Random(seed);
                        const bool imm = k & 1;
                        const int8_t sc = int8_t(k < 512 ? k / 2 - 128 : int8_t(Lcg(seed)));
                        Ref r = start;
                        RefShift(r, fn, x, imm ? sc : int8_t(start.se), imm, mutation);
                        Load(d, start);
                        d.Shift(fn, x, imm ? sc : int8_t(d.core_.se), imm);
                        const bool same = Same(d, r);
                        if (!mutation) { ++cases; failures += !same; } else if (!same) detected |= 1u << mutation;
                        if (fn < 4 && x < 4) {   // DIVS x, y / DIVQ x on the same states
                            for (const bool q : {false, true}) {
                                Ref rd = start;
                                RefDiv(rd, q, x, fn, mutation);
                                Load(d, start);
                                if (q) d.Divq(x); else d.Divs(x, fn);
                                const bool sd = Same(d, rd);
                                if (!mutation) { ++cases; failures += !sd; } else if (!sd) detected |= 1u << mutation;
                            }
                        }
                    }
        // modify flag out: every flag field, from a cleared state
        for (uint32_t bits = 0; bits < 0x1000; bits += 0x10) {
            d.flagout_ = d.fl0_ = d.fl1_ = d.fl2_ = 1;
            d.FlagOut(bits);
            const auto f = [&](unsigned clr, unsigned tgl) { return uint8_t((bits >> clr & 1 ? 0 : 1) ^ (bits >> tgl & 1)); };
            ++cases;
            failures += !(d.flagout_ == f(5, 4) && d.fl0_ == f(7, 6) && d.fl1_ == f(9, 8) && d.fl2_ == f(11, 10));
        }
        return {cases, failures, detected};
    }

    // Strict vs game on the boot page: PM 0x001 (copyright text, a swept unmeasured block) rejects in strict with the
    // measured-only message and runs in game with one AdspBlock and one AdspEdge; the busy loop at PM 0x15b eats
    // the slice (m_icount = 0, then --): the local time ends one partial cycle past the horizon.
    static std::string Profiles(const std::vector<uint8_t>& u2) {
        std::string out;
        {
            Dcs8k d(u2);
            d.pc = 0x001;
            try { d.Step(); out += "strict:none;"; } catch (const std::runtime_error& e) { out += std::string("strict:") + e.what() + ";"; }
        }
        {
            Dcs8k d(u2);
            FirstExecution log;
            d.profile = Profile::Game; d.first = &log;
            d.pc = 0x001; d.Step(); d.Step();
            out += "game:" + std::to_string(log.order.size());
            for (const auto& e : log.order)
                out += "," + std::to_string(unsigned(e.kind)) + ":" + std::to_string(e.id) + ":" + std::to_string(e.from) + ":" + std::to_string(e.cycle);
            out += ";";
        }
        {
            Dcs8k d(u2);
            d.profile = Profile::Game;
            d.pc = 0x15b;
            const uint64_t start = d.local_ns;
            d.Run({}, start + 1050, nullptr);   // slice: 10 whole cycles fit before the horizon
            out += "busy:" + std::to_string(d.local_ns - start) + ":" + std::to_string(d.totalcycles) + ":" + std::to_string(d.instructions) + ":" + std::to_string(d.pc);
        }
        return out;
    }
};
}
