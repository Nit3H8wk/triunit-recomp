#include "mk3_board.hpp"
#include "mk3_dcs.hpp"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>

// Native TMS34010 + DCS 8K co-simulation observations as one JSON object for tools/mk3/test_cosim.py.
// argv: ROM directory, CMOS seed, output file, first TMS cycle whose writes are run-length encoded, graphics list
// (lines "region_offset size path" of the ROM_LOAD32_BYTE "video" region, authenticated by the caller).
namespace {
constexpr uint64_t kWindowEnd = 2763;   // boot-1 ADSP cycle at TMS 1961 (tools/mk3/reference_dcs.py WINDOW_END)
// Every TMS instruction starting in these windows (tools/mk3/test_cosim.py SAMPLES): the ADSP state it sees.
constexpr uint64_t kSamples[][2] = {{545036, 545600}, {13045163, 13045700}, {13083100, 13083400}, {19398900, 19399400},
                                    {19410900, 19411400}, {19621050, 19621400}, {19643900, 19644500}, {19650500, 19650700},
                                    {19764380, 19764700}, {20795200, 20795600}};
struct Checkpoint { const char* name; uint32_t pc; uint64_t cycle; };
// Native frontier (tools/mk3/test_cosim.py POINTS['frontier']), passed by the build.
constexpr uint32_t kFrontierPc = FRONTIER_PC;
constexpr uint64_t kFrontierCycle = FRONTIER_CYCLE;
constexpr Checkpoint kCheckpoints[] = {
    {"cmos_check", 0xff814b40u, 0}, {"pic_check", 0xffaeff00u, 0}, {"init_text", 0xffae8690u, 0}, {"serial", 0xffb096a0u, 0},
    {"sound_wait", 0xffaa8990u, 0}, {"sound_wait2", 0xffaa8990u, 545037}, {"delay", 0xffae9930u, 0},
    {"delay_end", 0xffae99d0u, 0}, {"sound_wait3", 0xffaa8990u, 600000}, {"dcs_read", 0xffae9c40u, 600000},
    {"cmos_scan", 0xffadc240u, 13090000}, {"delay2", 0xffaeb2a0u, 13800000}, {"delay2_mid", 0xffaeb2a0u, 16600000},
    {"dcs_reset", 0xffaa8a40u, 600000}, {"reset_release", 0xffaa8ac0u, 600000}, {"io_table", 0xff81a120u, 19000000},
    {"command_00", 0xffaa8880u, 19600000}, {"command_55", 0xffaa8880u, 19640000}, {"eint", 0xff815070u, 0},
    {"first_ie", 0xff81a8a0u, 0}, {"di_return", 0xff815080u, 0}, {"timer_handler_ie", 0xff81a8a0u, 19764455},
    {"timer_return", 0xff928130u, 19764456}, {"trap1", 0xff8045e0u, 20795200}, {"first_dma", 0xff804640u, 20795274},
    {"first_reti", 0xff8046e0u, 20795274}, {"fill", 0xff8052b0u, 20795274}, {"frame1_di", 0xff81a7e0u, 20906900},
    {"frame3_di", 0xff81a7e0u, 21135390}, {"frontier", kFrontierPc, kFrontierCycle}};

// Hash of a byte string: its little-endian integer modulo 2^61 - 1 (as native/tests/mk3_dma_tests.cpp).
uint64_t Hash(const uint8_t* bytes, size_t n) {
    constexpr uint64_t kP = (uint64_t(1) << 61) - 1;
    uint64_t h = 0;
    const auto step = [&h](unsigned bits, uint32_t digit) {
        const unsigned __int128 x = (unsigned __int128)h << bits | digit;
        const uint64_t r = uint64_t(x & kP) + uint64_t(x >> 61);
        h = r >= kP ? r - kP : r;
    };
    size_t i = n;
    for (; i % 4; --i) step(8, bytes[i - 1]);
    for (; i; i -= 4) step(32, uint32_t(bytes[i - 4]) | uint32_t(bytes[i - 3]) << 8 | uint32_t(bytes[i - 2]) << 16 | uint32_t(bytes[i - 1]) << 24);
    return h;
}

std::vector<uint8_t> LoadGraphics(const wchar_t* list) {   // ROM_LOAD32_BYTE, stride 4, sizes checked
    std::vector<uint8_t> gfx;
    std::ifstream graphics(list);
    std::string path;
    for (size_t offset, size; graphics >> offset >> size && std::getline(graphics >> std::ws, path);) {
        std::ifstream rom(path, std::ios::binary);
        std::vector<char> data(size);
        if (!rom.read(data.data(), std::streamsize(size)) || rom.peek() != std::char_traits<char>::eof()) throw std::runtime_error("bad graphics ROM " + path);
        if (gfx.size() < (offset & ~size_t(3)) + 4 * size) gfx.resize((offset & ~size_t(3)) + 4 * size);
        for (size_t i = 0; i < size; ++i) gfx[offset + 4 * i] = uint8_t(data[i]);
    }
    if (gfx.empty()) throw std::runtime_error("no graphics ROMs");
    return gfx;
}

// Same shape as native/tests/mk3_adsp_tests.cpp, so tools/mk3/test_adsp.py compare() reads it unchanged.
void PrintDcs(std::FILE* f, const mk3::Dcs8k& d) {
    std::fprintf(f, "{\"rows\":[");
    for (size_t r = 0; r < d.rows.size(); ++r) {
        std::fprintf(f, "%s[", r ? "," : "");
        for (size_t k = 0; k < d.rows[r].size(); ++k) std::fprintf(f, "%s%llu", k ? "," : "", (unsigned long long)d.rows[r][k]);
        std::fprintf(f, "]");
    }
    std::fprintf(f, "],\"accesses\":[");
    for (size_t k = 0; k < d.accesses.size(); ++k) {
        const auto& a = d.accesses[k];
        std::fprintf(f, "%s[%u,%llu,%u,\"%c\",%u,%u]", k ? "," : "", a.boot, (unsigned long long)a.cycle, a.pc, a.kind, a.address, a.value);
    }
    std::fprintf(f, "],\"core_resets\":[");
    for (size_t k = 0; k < d.core_resets.size(); ++k)
        std::fprintf(f, "%s[%llu,%llu,%llu]", k ? "," : "", (unsigned long long)d.core_resets[k][0], (unsigned long long)d.core_resets[k][1],
                     (unsigned long long)d.core_resets[k][2]);
    std::fprintf(f, "],\"pm\":[");
    for (unsigned a = 0; a < 0x2000; ++a) if (a < 0x400 || a >= 0x800) std::fprintf(f, "%s%u", a ? "," : "", d.DebugProgram(uint16_t(a)));
    std::fprintf(f, "],\"dm\":[");
    bool first = true;
    for (unsigned a = 0; a < 0x4000; ++a)
        if (a < 0x3000 || (a >= 0x3800 && a < 0x3a00) || a >= 0x3fe0) { std::fprintf(f, "%s%u", first ? "" : ",", d.DebugData(uint16_t(a))); first = false; }
    std::fprintf(f, "],\"final\":[");
    const auto fields = d.Fields();
    for (size_t k = 0; k < fields.size(); ++k) std::fprintf(f, "%s%llu", k ? "," : "", (unsigned long long)fields[k]);
    std::fprintf(f, "],\"boot\":%u,\"pc\":%u,\"totalcycles\":%llu,\"local_ns\":%llu,\"latch_control\":%u}", d.boot, d.pc,
                 (unsigned long long)d.totalcycles, (unsigned long long)d.local_ns, d.latch_control);
}

struct Inputs { const mk3::Program& program; const std::vector<uint8_t>& cmos; const std::vector<uint8_t>& u2; const std::vector<uint8_t>& gfx; };

// ADSP observation runs: stop at the window end (every instruction) or at the bank-1 entry (sampled delay NOP).
void AdspRun(std::FILE* f, const Inputs& in, bool window, mk3::Board::As skew) {
    mk3::Board b(in.program, in.cmos, in.u2, in.gfx);
    b.data_skew = skew;
    if (window) {
        b.dcs.observe = [](const mk3::Dcs8k&) { return true; };
        b.dcs_stop = [](const mk3::Dcs8k& d) { return d.boot == 1 && d.totalcycles == kWindowEnd; };
    } else {
        b.dcs.observe = [](const mk3::Dcs8k& d) { return d.pc != 0x45 || d.totalcycles <= kWindowEnd + 40 || d.totalcycles % 1009 == 0; };
        b.dcs_stop = [](const mk3::Dcs8k& d) { return d.boot == 3; };
    }
    try { b.Run(); } catch (const std::runtime_error&) {}   // a missed stop shows up in the compared observations
    PrintDcs(f, b.dcs);
}

// Full run to the frontier: checkpoints, bus, host events, interrupts taken and the ADSP state each TMS instruction
// sees. The run stops before the frontier instruction, which is then executed alone and must reject. dpyint_skew
// (negative control) moves every DPYINT = 274 the game programs by that many lines; dma_skew (negative control) moves
// every DMA done time by whole cycles; clip_row (negative control) clips the first DMA to its first row.
// DMA observations at the instruction boundary after each trigger: the trigger instruction's start cycle, the 18
// registers, the video RAM words changed since the previous trigger and the hash of the whole video RAM; and every
// boundary where (DMA_COMMAND & 0x8000) | (INTPEND & INT1) changes.
void TmsRun(std::FILE* f, const Inputs& in, uint64_t rle_from, mk3::Board::As boost, bool samples_only, bool input_syncs = true,
            int dpyint_skew = 0, int dma_skew = 0, bool clip_row = false) {
    mk3::Board b(in.program, in.cmos, in.u2, in.gfx);
    b.boost_quantum = boost;
    b.input_syncs = input_syncs;
    b.o.dma_skew = dma_skew;
    bool done[std::size(kCheckpoints)] = {};
    bool first = true;
    std::string triggers, states;
    std::vector<uint16_t> vram = b.o.vram;   // as of the previous trigger
    mk3::VideoTiming::Atto armed = 0;
    unsigned state = 0;
    const bool vram_out = !samples_only || clip_row;
    int clip_old = -1;
    char text[64];
    std::fprintf(f, "{\"samples\":[");
    b.stop = [&](const mk3::Board& board) {
        auto& dpyint = b.o.video.io[mk3::VideoTiming::DPYINT];
        if (dpyint_skew && dpyint == 274) dpyint = uint16_t(274 + dpyint_skew);
        const uint64_t cycle = board.Cycles();
        auto& dma = b.o.blitter;
        if (clip_row && board.s.pc == 0xff804640u) {   // clip the first DMA to its first row, for that DMA only
            clip_old = dma.reg[mk3::Dma::BOTCLIP]; dma.reg[mk3::Dma::BOTCLIP] = dma.reg[mk3::Dma::YSTART] & 0x1ff; clip_row = false;
        }
        if (b.o.video.dma_expire != armed) {   // the previous instruction triggered a DMA (its done timer may have fired already)
            armed = b.o.video.dma_expire;
            if (clip_old >= 0) { dma.reg[mk3::Dma::BOTCLIP] = uint16_t(clip_old); clip_old = -1; }
            if (vram_out) {
                std::snprintf(text, sizeof text, "%s[%llu,[", triggers.empty() ? "" : ",", (unsigned long long)b.o.instruction_cycles);
                triggers += text;
                for (size_t k = 0; k < dma.reg.size(); ++k) { std::snprintf(text, sizeof text, "%s%u", k ? "," : "", dma.reg[k]); triggers += text; }
                triggers += "],[";
                bool any = false;
                for (size_t k = 0; k < vram.size(); ++k)
                    if (vram[k] != dma.vram[k]) {
                        std::snprintf(text, sizeof text, "%s%zu,%u", any ? "," : "", k, dma.vram[k]);
                        triggers += text; any = true; vram[k] = dma.vram[k];
                    }
                std::snprintf(text, sizeof text, "],%llu]", (unsigned long long)Hash(reinterpret_cast<const uint8_t*>(vram.data()), vram.size() * 2));
                triggers += text;
            }
        }
        const unsigned now = unsigned(dma.reg[mk3::Dma::COMMAND] & 0x8000) | (b.o.video.io[mk3::VideoTiming::INTPEND] & mk3::VideoTiming::INT1);
        if (now != state) {
            std::snprintf(text, sizeof text, "%s[%llu,%u,%u]", states.empty() ? "" : ",", (unsigned long long)cycle, now, board.s.pc);
            states += text;
            state = now;
        }
        if (cycle < 247) return false;   // before the CMOS routine entry (lot 2 boundary, TMS 247): no sample
        bool sample = false;
        for (const auto& w : kSamples) sample = sample || (cycle >= w[0] && cycle <= w[1]);
        const char* name = "";
        for (size_t k = 0; k < std::size(kCheckpoints); ++k)
            if (!done[k] && board.s.pc == kCheckpoints[k].pc && cycle >= kCheckpoints[k].cycle) { done[k] = sample = true; name = kCheckpoints[k].name; break; }
        if (!sample) return false;
        std::fprintf(f, "%s{\"name\":\"%s\",\"pc\":%u,\"status\":%u,\"cycles\":%llu,\"instructions\":%llu,\"writes\":%zu,\"reads\":%zu,\"registers\":[",
                     first ? "" : ",", name, board.s.pc, board.s.status, (unsigned long long)cycle, (unsigned long long)board.s.instructions,
                     board.s.writes.size(), board.s.reads.size());
        first = false;
        for (unsigned i = 0; i < 31; ++i) std::fprintf(f, "%s%u", i ? "," : "", i < 16 ? board.s.a[i] : board.s.b[i - 16]);
        std::fprintf(f, "],\"dcs_frozen\":%s,\"dcs_boot\":%u,\"dcs_latch\":%u,\"dcs\":[", board.dcs_frontier.empty() ? "false" : "true",
                     board.dcs.boot, board.dcs.latch_control);
        const auto fields = board.dcs.Fields();
        for (size_t k = 0; k < fields.size(); ++k) std::fprintf(f, "%s%llu", k ? "," : "", (unsigned long long)fields[k]);
        std::fprintf(f, "]}");
        return done[std::size(kCheckpoints) - 1];
    };
    std::string frontier = "none";
    size_t writes_end = SIZE_MAX;   // the Original stops before the frontier instruction: its writes are listed apart
    try {
        b.Run();
        writes_end = b.s.writes.size();
        mk3::StepGenerated(b.o);
    } catch (const std::runtime_error& e) { frontier = e.what(); }
    writes_end = std::min(writes_end, b.s.writes.size());
    std::fprintf(f, "],\"frontier_writes\":[");
    for (size_t k = writes_end; k < b.s.writes.size(); ++k)
        std::fprintf(f, "%s[%u,%u,%llu]", k > writes_end ? "," : "", b.s.writes[k].address_bit, b.s.writes[k].value, (unsigned long long)b.s.writes[k].cycle);
    std::fprintf(f, "],\"frontier\":\"%s\",\"dcs_frontier\":\"%s\",\"pc\":%u,\"cycles\":%llu,\"instructions\":%llu,\"host_events\":[", frontier.c_str(),
                 b.dcs_frontier.c_str(), b.s.pc, (unsigned long long)b.s.cycles, (unsigned long long)b.s.instructions);
    for (size_t k = 0; k < b.host_events.size(); ++k) {
        const auto& e = b.host_events[k];
        std::fprintf(f, "%s[%d,%llu,%llu,%u,%llu]", k ? "," : "", int(e.kind), (unsigned long long)e.write_cycle, (unsigned long long)e.end_cycle,
                     e.value, (unsigned long long)e.adsp_ns);
    }
    std::fprintf(f, "],\"dma_states\":[%s],\"dma_triggers\":[%s],\"interrupts\":[", states.c_str(), triggers.c_str());
    for (size_t k = 0; k < b.o.interrupts.size(); ++k) {
        const auto& i = b.o.interrupts[k];
        std::fprintf(f, "%s[%llu,%u,%u,%u,%u,%u]", k ? "," : "", (unsigned long long)i.entry, i.vector, i.handler, i.pc, i.status, i.sp);
    }
    std::fprintf(f, "]");
    if (!samples_only) {
        // Writes before rle_from in full; later ones as breaks of the run "same address and value, 5 cycles apart".
        std::fprintf(f, ",\"writes\":[");
        size_t k = 0;
        for (; k < writes_end && b.s.writes[k].cycle < rle_from; ++k)
            std::fprintf(f, "%s[%u,%u,%u,%llu]", k ? "," : "", b.s.writes[k].pc, b.s.writes[k].address_bit, b.s.writes[k].value,
                         (unsigned long long)b.s.writes[k].cycle);
        std::fprintf(f, "],\"rle\":{\"breaks\":[");
        mk3::BusWrite last = k ? b.s.writes[k - 1] : mk3::BusWrite{};
        const size_t start = k;
        for (first = true; k < writes_end; last = b.s.writes[k++]) {
            const auto& w = b.s.writes[k];
            if (w.address_bit == last.address_bit && w.value == last.value && w.cycle == last.cycle + 5) continue;
            std::fprintf(f, "%s[%u,%u,%llu]", first ? "" : ",", w.address_bit, w.value, (unsigned long long)w.cycle);
            first = false;
        }
        std::fprintf(f, "],\"count\":%zu,\"last\":[%u,%u,%llu]},\"reads\":[", writes_end - start, last.address_bit, last.value,
                     (unsigned long long)last.cycle);
        for (k = 0; k < b.s.reads.size(); ++k)
            std::fprintf(f, "%s[%u,%u,%u,%llu]", k ? "," : "", b.s.reads[k].pc, b.s.reads[k].address_bit, b.s.reads[k].value,
                         (unsigned long long)b.s.reads[k].cycle);
        std::fprintf(f, "]");
    }
    std::fprintf(f, "}");
}
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 6) return 2;
    try {
        const auto program = mk3::LoadProgram(argv[1]);
        const auto u2 = mk3::LoadDcsU2(argv[1]);
        std::ifstream seed(argv[2], std::ios::binary);
        const std::vector<uint8_t> cmos{std::istreambuf_iterator<char>(seed), std::istreambuf_iterator<char>()};
        const auto gfx = LoadGraphics(argv[5]);
        const Inputs in{program, cmos, u2, gfx};
        std::FILE* f = _wfopen(argv[3], L"w");
        if (!f) return 3;
        std::fprintf(f, "{\"graphics_hash\":%llu,\"fields\":[", (unsigned long long)Hash(gfx.data(), gfx.size()));
        for (size_t k = 0; k < mk3::Dcs8k::FieldNames().size(); ++k) std::fprintf(f, "%s\"%s\"", k ? "," : "", mk3::Dcs8k::FieldNames()[k].c_str());
        std::fprintf(f, "],\"window\":");
        AdspRun(f, in, true, 0);
        std::fprintf(f, ",\"extension\":");
        AdspRun(f, in, false, 0);
        std::fprintf(f, ",\"tms\":");
        TmsRun(f, in, std::stoull(argv[4]), 500 * mk3::Board::kNs, false);
        // Negative controls inside the scheduler: sound-port writes applied 100 ns late; a 600 ns boosted quantum.
        std::fprintf(f, ",\"skew_extension\":");
        AdspRun(f, in, false, 100 * mk3::Board::kNs);
        std::fprintf(f, ",\"boost_tms\":");
        TmsRun(f, in, 0, 600 * mk3::Board::kNs, true);
        // Negative control: HSTCTLH / DMA_COMMAND writes without their input-line synchronize().
        std::fprintf(f, ",\"no_sync_tms\":");
        TmsRun(f, in, 0, 500 * mk3::Board::kNs, true, false);
        // Negative controls: DPYINT one line later / earlier.
        std::fprintf(f, ",\"dpyint_late_tms\":");
        TmsRun(f, in, 0, 500 * mk3::Board::kNs, true, true, 1);
        std::fprintf(f, ",\"dpyint_early_tms\":");
        TmsRun(f, in, 0, 500 * mk3::Board::kNs, true, true, -1);
        // Negative controls: every DMA done one cycle later / earlier; the first DMA clipped to its first row.
        std::fprintf(f, ",\"done_late_tms\":");
        TmsRun(f, in, 0, 500 * mk3::Board::kNs, true, true, 0, 1);
        std::fprintf(f, ",\"done_early_tms\":");
        TmsRun(f, in, 0, 500 * mk3::Board::kNs, true, true, 0, -1);
        std::fprintf(f, ",\"clip_tms\":");
        TmsRun(f, in, 0, 500 * mk3::Board::kNs, true, true, 0, 0, true);
        std::fprintf(f, "}\n");
        std::fclose(f);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
    return 0;
}
