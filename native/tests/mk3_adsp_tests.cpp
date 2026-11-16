#include "mk3_adsp.hpp"
#include "mk3_dcs.hpp"
#include "mk3_cpu.hpp"
#include <algorithm>
#include <array>
#include <cstdio>
#include <fstream>
#include <set>
#include <stdexcept>
#include <string>

// Native DCS 8K ADSP observations as one JSON object for tools/mk3/test_adsp.py.
// argv: ROM directory, output file, host-event file for the extension ("kind write_cycle end_cycle value" per line,
// TMS34010 cycles; kind 0 assert, 1 release, 2 data write, 3 data read), comma-free list of TMS status-read cycles.
// With three more arguments ("bank1", the observation schedule, the probe time in ns) it writes the bank-1 program
// observations as text lines for tools/mk3/test_adsp_bank1.py instead; its host-event times are in ns.
#include "mk3_adsp_forms.inc"

namespace {
constexpr uint64_t kTmsCycleNs = 160;    // TMS34010 50 MHz / 8 (tms34010.h execute_clocks_to_cycles)
constexpr uint64_t kMoveAbsCycles = 3;   // MOVE Rs,@abs,0 cost (34010ops.hxx MOVE_RA: COUNT_CYCLES(3))
constexpr uint64_t kWindowEnd = 2763;    // boot-1 ADSP cycle at TMS 1961: (1961 * 160 - 37400) / 100 = 2763.6

void Print(std::FILE* f, const mk3::Dcs8k& d) {
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
    std::fprintf(f, "],\"latch_changes\":[");
    for (size_t k = 0; k < d.latch_changes.size(); ++k)
        std::fprintf(f, "%s[%llu,%u]", k ? "," : "", (unsigned long long)d.latch_changes[k].first, d.latch_changes[k].second);
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
    const auto final_fields = d.Fields();
    for (size_t k = 0; k < final_fields.size(); ++k) std::fprintf(f, "%s%llu", k ? "," : "", (unsigned long long)final_fields[k]);
    std::fprintf(f, "],\"boot\":%u,\"pc\":%u,\"totalcycles\":%llu,\"local_ns\":%llu,\"latch_control\":%u}", d.boot, d.pc,
                 (unsigned long long)d.totalcycles, (unsigned long long)d.local_ns, d.latch_control);
}

template <class F> bool Rejects(F f) { try { f(); } catch (const std::runtime_error&) { return true; } return false; }

std::vector<uint64_t> Numbers(const std::wstring& text, wchar_t a, wchar_t b) {
    std::vector<uint64_t> out;
    for (size_t p = 0; p < text.size();) {
        const size_t q = std::min(text.find(a, p), text.find(b, p));
        out.push_back(std::stoull(text.substr(p, q - p)));
        p = q == std::wstring::npos ? text.size() : q + 1;
    }
    return out;
}

// Bank-1 program observations, same filter as tools/mk3/reference_dcs.py schedule_script. schedule: "boot:cycles:mode,..."
// switch points in order; cycles 0 = the boot's PC-0 entry, otherwise the frame marker at totalcycles >= cycles in that boot.
// Modes: F full (every instruction but the sampled waits, every access), S sparse (marker rows; autobuffer, DM 0x3000-0x37ff
// and control-register data accesses), E end. Nothing is observed before the first switch; every switch records its row.
// probe_ns > 0: a second executor runs the same events to probe_ns and reports its rejection ("none" if it gets there).
int Bank1(const std::vector<uint8_t>& u2, const wchar_t* roms, const std::vector<mk3::HostEvent>& events, const wchar_t* path, const std::wstring& status,
          const std::wstring& schedule, uint64_t probe_ns) {
    constexpr uint16_t kMarker = 0x131, kBufferBegin = 0x0c00, kBufferEnd = 0x0de0;
    struct Switch { unsigned boot; uint64_t cycles; wchar_t mode; };
    std::vector<Switch> steps;
    for (size_t p = 0; p < schedule.size();) {
        const size_t q = std::min(schedule.find(L',', p), schedule.size());
        const auto part = schedule.substr(p, q - p);
        const size_t c1 = part.find(L':'), c2 = part.rfind(L':');
        steps.push_back({unsigned(std::stoul(part.substr(0, c1))), std::stoull(part.substr(c1 + 1, c2 - c1 - 1)), part.back()});
        p = q + 1;
    }
    if (steps.empty() || steps.back().mode != L'E') return 2;
    size_t next = 0;
    wchar_t mode = L'N';
    const auto bank1 = [](unsigned boot) { return boot == 3 || boot == 5; };   // boots that run the bank-1 program
    const auto due = [&](const mk3::Dcs8k& x) {
        if (next == steps.size()) return false;
        const auto& s = steps[next];
        return x.boot == s.boot && (s.cycles ? x.pc == kMarker && x.totalcycles >= s.cycles : x.pc == 0);
    };
    const size_t irq1 = std::find(mk3::Dcs8k::FieldNames().begin(), mk3::Dcs8k::FieldNames().end(), "irq1") - mk3::Dcs8k::FieldNames().begin();
    std::vector<uint32_t> seen(0x2000);
    unsigned seen_boot = ~0u;
    std::set<uint64_t> executed;   // (boot, pc, opcode) executed from the first switch on
    mk3::Dcs8k d(u2);
    d.AttachSoundData(roms);
    d.observe = [&](const mk3::Dcs8k& x) {
        const bool switched = due(x);
        if (switched) mode = steps[next++].mode;
        if (mode == L'N') return false;
        if (x.boot != seen_boot) { seen_boot = x.boot; std::fill(seen.begin(), seen.end(), 0); }
        if (const uint32_t op = x.DebugProgram(x.pc); seen[x.pc] != op + 1) {
            seen[x.pc] = op + 1;
            executed.insert(uint64_t(x.boot) << 48 | uint64_t(x.pc) << 24 | op);
        }
        if (switched || x.pc == kMarker) return true;
        if (mode == L'S') return false;
        if (bank1(x.boot)) {
            const bool wait = (x.pc >= 0x137 && x.pc <= 0x139) || (x.pc >= 0x13d && x.pc <= 0x13f);
            return !wait || x.totalcycles % 1009 == 0 || x.Fields()[irq1];
        }
        return x.pc != 0x45 || x.totalcycles % 1009 == 0 || x.Fields()[irq1];   // bank-0 delay NOP
    };
    d.observe_access = [&](const mk3::Dcs8k&, const mk3::AdspAccess& a) {
        if (mode == L'N') return false;
        const bool data = a.kind == 'r' || a.kind == 'w' || a.kind == 'd';
        return mode == L'F' || (data && ((a.address >= kBufferBegin && a.address < kBufferEnd) || (a.address >= 0x3000 && a.address < 0x3800) || a.address >= 0x3fe0));
    };
    d.Run(events, ~0ull >> 1, [&](const mk3::Dcs8k& x) { return next + 1 == steps.size() && due(x); });
    std::string frontier = "none";
    if (probe_ns) {
        try { mk3::Dcs8k x(u2); x.AttachSoundData(roms); x.Run(events, probe_ns, nullptr); }
        catch (const std::runtime_error& e) { frontier = e.what(); }
    }
    std::FILE* f = _wfopen(path, L"w");
    if (!f) return 3;
    std::fprintf(f, "F");
    for (const auto& name : mk3::Dcs8k::FieldNames()) std::fprintf(f, " %s", name.c_str());
    for (const auto& row : d.rows) {
        std::fprintf(f, "\nB");
        for (size_t k = 1; k < row.size(); ++k) std::fprintf(f, " %llX", (unsigned long long)row[k]);
    }
    std::fprintf(f, "\nE");
    for (const auto v : d.Fields()) std::fprintf(f, " %llX", (unsigned long long)v);
    for (const auto& a : d.accesses) std::fprintf(f, "\nA %c %X %llX %X %X %X", a.kind, a.pc, (unsigned long long)a.cycle, a.address, a.value, a.boot);
    for (const auto& [ns, value] : d.latch_changes) std::fprintf(f, "\nL %llu %u", (unsigned long long)ns, value);
    for (const auto& r : d.core_resets) std::fprintf(f, "\nR %llu %llu %llu", (unsigned long long)r[0], (unsigned long long)r[1], (unsigned long long)r[2]);
    for (const auto& b : d.dac_blocks) {
        std::fprintf(f, "\nK %llu %u %llu %u %d %u %u %u %u\nP", (unsigned long long)b.ns, b.boot, (unsigned long long)b.cycle, b.address, b.step, b.first, b.count,
                     b.sample_ns, b.arm);
        for (uint32_t k = 0; k < b.count; ++k) std::fprintf(f, " %d", d.pcm[b.first + k]);
    }
    for (const auto& [ns, value] : d.host_reads) std::fprintf(f, "\nH %llu %u", (unsigned long long)ns, value);
    for (const auto cycle : Numbers(status, L'_', L'_')) std::fprintf(f, "\nS %llu %u", (unsigned long long)cycle, d.LatchAt(cycle * kTmsCycleNs));
    std::fprintf(f, "\nM");
    for (unsigned a = 0; a < 0x2000; ++a) if (a < 0x400 || a >= 0x800) std::fprintf(f, " %X", d.DebugProgram(uint16_t(a)));
    std::fprintf(f, "\nN");
    for (unsigned a = 0; a < 0x4000; ++a) if (a < 0x3000 || (a >= 0x3800 && a < 0x3a00) || a >= 0x3fe0) std::fprintf(f, " %X", d.DebugData(uint16_t(a)));
    std::fprintf(f, "\nX %llu %llu %llu %u %zu %zu\nZ %s\n", (unsigned long long)d.local_ns, (unsigned long long)d.instructions,
                 (unsigned long long)d.totalcycles, d.sounddata_bank, executed.size(), d.pcm.size(), frontier.c_str());
    for (const auto pair : executed) std::fprintf(f, "C %llX\n", (unsigned long long)pair);
    std::fclose(f);
    return 0;
}
}

int wmain(int argc, wchar_t** argv) {
    if (argc == 3 && std::wstring(argv[1]) == L"forms") {   // per-form and profile checks: one JSON line on stdout
        const auto u2 = mk3::LoadDcsU2(argv[2]);
        const auto r = mk3::AdspFormTest::Run(u2);
        std::printf("{\"cases\":%llu,\"failures\":%llu,\"negatives\":%llu,\"profiles\":\"%s\"}\n", (unsigned long long)r[0],
                    (unsigned long long)r[1], (unsigned long long)r[2], mk3::AdspFormTest::Profiles(u2).c_str());
        return r[1] ? 1 : 0;
    }
    if (argc != 5 && argc != 8) return 2;
    try {
        const auto u2 = mk3::LoadDcsU2(argv[1]);
        // Host timeline inside the window comes from the generated main-CPU code from reset to the first device read
        // (0xff814aa0; the CMOS is not read before it): io[1] bit 4 = DCS reset.
        std::vector<mk3::HostEvent> window;
        for (const auto& w : mk3::RunGenerated(mk3::LoadProgram(argv[1]), std::vector<uint8_t>(0xc000), 0xff814aa0u).writes)
            if (w.address_bit == 0x0187ff90)
                window.push_back({(w.value & 0x10) ? mk3::HostEvent::ResetAssert : mk3::HostEvent::ResetRelease,
                                  w.cycle * kTmsCycleNs, (w.cycle + kMoveAbsCycles) * kTmsCycleNs, 0, 0, w.cycle * kTmsCycleNs});
        // Power-on slice: the TMS34010 scanline timer fires at t = 0 and next at line 1, 15 lines after the screen's
        // initial vblank start (vpos 275 of 289, 63.25 us lines); no other timer is due, so the slice starts at 0.
        window[0].slice_max_ns = 0;
        if (window.size() != 2) throw std::runtime_error("unexpected reset prefix host timeline");

        mk3::Dcs8k a(u2);
        a.observe = [](const mk3::Dcs8k&) { return true; };
        a.Run(window, ~0ull >> 1, [](const mk3::Dcs8k& d) { return d.boot == 1 && d.totalcycles == kWindowEnd; });

        std::vector<mk3::HostEvent> extension = window;
        std::ifstream events(argv[3]);
        uint64_t last_data_ns = 0;
        for (unsigned kind; events >> kind;) {
            uint64_t write = 0, end = 0; unsigned value = 0;
            if (!(events >> write >> end >> value) || kind > 3) throw std::runtime_error("malformed host event");
            // Slice start bound: the scanline timer cuts every 63.25 us line; within 5 us after a sound-port write,
            // dcs_delayed_data_w's add_quantum(500 ns) does, and a slice begun before that expiry still ends 500 ns
            // later (schedule.cpp reclaims an expired quantum only on entering timeslice(), i.e. at a slice boundary).
            // Margins cover the main CPU's last-instruction overrun. The boosted slices leave a boundary at most 500 ns
            // apart up to the quantum's expiry, so a later slice starts no earlier than 4.5 us after that write.
            const uint64_t unit = argc == 8 ? 1 : kTmsCycleNs, h = write * unit;
            const bool boosted = last_data_ns && h < last_data_ns + 5500;
            const uint64_t slice_min = boosted ? h - 1000 : std::max(h - 64000, last_data_ns ? last_data_ns + 4500 : 0);
            if (kind == 2) last_data_ns = h;
            // A host read is placed in a slice of its own (declared assumption, checked through the value it returns).
            extension.push_back({mk3::HostEvent::Kind(kind), h, end * unit, uint16_t(value), kind == 3 ? h : slice_min, h});
        }
        if (argc == 8) return Bank1(u2, argv[1], extension, argv[2], argv[4], argv[6], std::stoull(argv[7]));
        mk3::Dcs8k b(u2);
        // Same filter as tools/mk3/reference_dcs.py breakpoints: every PC but the delay NOP, which is sampled.
        b.observe = [](const mk3::Dcs8k& d) {
            return d.pc != 0x45 || d.totalcycles <= kWindowEnd + 40 || d.totalcycles % 1009 == 0;
        };
        b.Run(extension, ~0ull >> 1, [](const mk3::Dcs8k& d) { return d.boot == 3; });   // bank-1 image entry

        // Negative controls inside the executor: altered U2; running past the frontier must reject at the bank-1 image.
        auto bad = u2; bad[0x100] ^= 1;
        const bool u2_rejected = Rejects([&] { mk3::Dcs8k x(bad); });
        // The bank-1 entry no longer rejects; its frontier is probed by the bank-1 mode above.
        std::string frontier = "none";
        try { mk3::Dcs8k x(u2); x.Run(extension, ~0ull >> 1, [](const mk3::Dcs8k& d) { return d.boot == 3 && d.totalcycles == 8; }); }
        catch (const std::runtime_error& e) { frontier = e.what(); }
        std::FILE* f = _wfopen(argv[2], L"w");
        if (!f) return 3;
        std::fprintf(f, "{\"fields\":[");
        for (size_t k = 0; k < mk3::Dcs8k::FieldNames().size(); ++k) std::fprintf(f, "%s\"%s\"", k ? "," : "", mk3::Dcs8k::FieldNames()[k].c_str());
        std::fprintf(f, "],\"latch_at\":[");
        std::wstring reads = argv[4];
        bool first = true;
        for (size_t p = 0; p < reads.size();) {
            const size_t q = reads.find(L'_', p);
            const uint64_t cycle = std::stoull(reads.substr(p, q - p));
            std::fprintf(f, "%s[%llu,%u]", first ? "" : ",", (unsigned long long)cycle, a.LatchAt(cycle * kTmsCycleNs));
            first = false;
            p = q == std::wstring::npos ? reads.size() : q + 1;
        }
        std::fprintf(f, "],\"u2_rejected\":%s,\"frontier\":\"%s\",\"window\":", u2_rejected ? "true" : "false", frontier.c_str());
        Print(f, a);
        std::fprintf(f, ",\"extension\":");
        Print(f, b);
        std::fprintf(f, "}\n");
        std::fclose(f);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
    return 0;
}
