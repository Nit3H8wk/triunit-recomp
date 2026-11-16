#include "mk3_board.hpp"
#include "mk3_dcs.hpp"
#include <cstdio>
#include <fstream>
#include <iterator>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>

// Ops::vram_observer (mk3_cpu.hpp) neutrality and reach on one route: mk3::Board from reset in Profile::Game with a legal
// tape, the way native/tests/mk3_replay_main.cpp drives it (tape applied at instruction boundaries >= 1000 cycles with
// ST.P clear). Every STEP cycles the complete state (registers, cycles, RAM, CMOS, palette, VRAM, DMA and I/O registers,
// ADSP DM/PM, PCM, bus/interrupt/host-event/first-execution counts) is folded into a running FNV-1a 64; the run with the
// observer attached must give the same chain as the run without it. The observer checks each call against the store it
// follows (value == vram[word]; a midtunit_vram_w call matches the last bus record's PC, cycle and word pair).
// argv: ROM directory, CMOS seed, graphics list (as mk3_replay_main.cpp), spec ("horizon H", "step S", "tape C PORT V",
// "reads LO HI": io reads 0x01800000-0x0187fff0 inside the window, "negative-io": Ops::io_default_reads = false),
// mode "on" | "off". Output: one JSON line (also the DevicePath first executions).
namespace {
constexpr uint32_t kPixbltRestart = 0x02000000;
constexpr uint64_t kFnvBasis = 0xcbf29ce484222325ull;
uint64_t Fnv(uint64_t h, uint64_t v) { return (h ^ v) * 0x100000001b3ull; }
uint64_t Words(uint64_t h, const std::vector<uint16_t>& w) { for (const uint16_t v : w) h = Fnv(h, v); return h; }

std::vector<uint8_t> LoadGraphics(const char* list) {   // ROM_LOAD32_BYTE, stride 4 (mk3_replay_main.cpp)
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

struct Tape { uint64_t cycle; unsigned port; uint16_t value; };

struct Watch : mk3::CpuVramObserver {
    const mk3::Board* b = nullptr;
    uint64_t calls = 0, bus_matched = 0, mismatches = 0, hash = kFnvBasis, first_cycle = ~0ull, last_cycle = 0;
    std::map<uint32_t, uint64_t> by_pc;
    std::map<uint16_t, uint64_t> by_mask;
    void CpuVram(uint32_t pc, size_t word, uint16_t value, uint16_t mask, uint64_t cycle) override {
        ++calls; ++by_pc[pc]; ++by_mask[mask];
        for (const uint64_t v : {uint64_t(pc), uint64_t(word), uint64_t(value), uint64_t(mask), cycle}) hash = Fnv(hash, v);
        first_cycle = std::min(first_cycle, cycle); last_cycle = std::max(last_cycle, cycle);
        if (word >= b->o.vram.size() || b->o.vram[word] != value || pc != b->o.instruction_pc || cycle != b->o.instruction_cycles) ++mismatches;
        if (!b->s.writes.empty()) {
            const auto& w = b->s.writes.back();
            if (w.address_bit <= 0x003ffff0 && w.pc == pc && w.cycle == cycle && (word & ~size_t(1)) == (w.address_bit / 16) * 2) ++bus_matched;
        }
    }
};

uint64_t State(const mk3::Board& b, size_t writes, size_t reads, const mk3::FirstExecution& log) {
    const auto& s = b.s;
    uint64_t h = kFnvBasis;
    for (const uint64_t v : {b.Cycles(), uint64_t(s.pc), uint64_t(s.status), uint64_t(s.instructions), uint64_t(s.video_control),
                             uint64_t(writes), uint64_t(reads), uint64_t(b.o.interrupts.size()), uint64_t(b.host_events.size()),
                             uint64_t(log.order.size()), uint64_t(b.dcs.pcm.size())}) h = Fnv(h, v);
    for (unsigned i = 0; i < 16; ++i) h = Fnv(Fnv(h, s.a[i]), s.b[i]);
    h = Words(Words(Words(Words(h, b.o.ram), b.o.cmos), b.o.palette), b.o.vram);
    for (const uint16_t v : b.o.dma) h = Fnv(h, v);
    for (const uint16_t v : b.o.tms_io) h = Fnv(h, v);
    for (unsigned a = 0; a < 0x4000; ++a) if (a < 0x3000 || (a >= 0x3800 && a < 0x3a00)) h = Fnv(h, b.dcs.DebugData(uint16_t(a)));   // mk3_replay_main.cpp DmMapped
    for (unsigned a = 0; a < 0x2000; ++a) if (a < 0x400 || a >= 0x800) h = Fnv(h, b.dcs.DebugProgram(uint16_t(a)));                  // PmMapped
    for (const auto& e : b.dcs.pcm) h = Fnv(h, uint16_t(e));
    return h;
}
}

int main(int argc, char** argv) {
    if (argc != 6 || (std::string(argv[5]) != "on" && std::string(argv[5]) != "off")) return 2;
    try {
        const auto program = mk3::LoadProgram(argv[1]);
        const auto u2 = mk3::LoadDcsU2(argv[1]);
        std::ifstream seed(argv[2], std::ios::binary);
        const std::vector<uint8_t> cmos{std::istreambuf_iterator<char>(seed), std::istreambuf_iterator<char>()};
        const auto gfx = LoadGraphics(argv[3]);
        uint64_t horizon = 0, step = 1u << 17, reads_lo = 1, reads_hi = 0;
        bool negative_io = false;
        std::vector<Tape> tape;
        std::ifstream spec(argv[4]);
        for (std::string line; std::getline(spec, line);) {
            std::istringstream row(line);
            std::string key;
            if (!(row >> key)) continue;
            bool ok = true;
            if (key == "horizon") ok = bool(row >> horizon);
            else if (key == "step") ok = bool(row >> step) && step;
            else if (key == "negative-io") negative_io = true;
            else if (key == "reads") ok = bool(row >> reads_lo >> reads_hi) && reads_lo <= reads_hi;
            else if (key == "tape") { Tape t{}; unsigned v = 0; ok = bool(row >> t.cycle >> t.port >> v) && t.port < 4 && v <= 0xffff; t.value = uint16_t(v); tape.push_back(t); }
            else ok = false;
            if (!ok) throw std::runtime_error("invalid spec line: " + line);
        }
        const bool on = std::string(argv[5]) == "on";
        mk3::Board b(program, cmos, u2, gfx);
        b.dcs.AttachSoundData(argv[1]);
        mk3::FirstExecution log;
        b.SetProfile(mk3::Profile::Game, &log);
        b.dcs.observe_access = [](const mk3::Dcs8k&, const mk3::AdspAccess&) { return false; };
        Watch watch; watch.b = &b;
        if (on) b.o.vram_observer = &watch;
        b.o.io_default_reads = !negative_io;
        std::vector<mk3::BusWrite> io_reads;   // "reads LO HI": device reads of 0x01800000-0x0187fff0 inside the window
        const auto harvest = [&] {
            for (const auto& r : b.s.reads)
                if (r.cycle >= reads_lo && r.cycle <= reads_hi && r.address_bit >= 0x01800000 && r.address_bit <= 0x0187fff0) io_reads.push_back(r);
        };
        uint64_t chain = kFnvBasis, next = step, records = 0;
        size_t applied = 0, writes = 0, reads = 0;
        b.stop = [&](const mk3::Board& board) {
            const uint64_t cycle = board.Cycles();
            if (cycle < 1000 || (board.s.status & kPixbltRestart)) return false;
            if (b.s.writes.size() >= (size_t(1) << 20)) { writes += b.s.writes.size(); b.s.writes.clear(); }   // bounded memory
            if (b.s.reads.size() >= (size_t(1) << 20)) { harvest(); reads += b.s.reads.size(); b.s.reads.clear(); }
            for (; applied < tape.size() && tape[applied].cycle <= cycle; ++applied) b.o.ports[tape[applied].port] = tape[applied].value;
            if (next <= cycle) {
                next += step * (1 + (cycle - next) / step);
                chain = Fnv(chain, State(board, writes + board.s.writes.size(), reads + board.s.reads.size(), log)); ++records;
            }
            return horizon && cycle >= horizon;
        };
        std::string frontier = "none";
        try { b.Run(); } catch (const std::runtime_error& e) { frontier = e.what(); }
        harvest();
        chain = Fnv(chain, State(b, writes + b.s.writes.size(), reads + b.s.reads.size(), log)); ++records;
        uint64_t first_hash = kFnvBasis;
        for (const auto& e : log.order) for (const uint64_t v : {uint64_t(e.kind), uint64_t(e.id), uint64_t(e.from), e.cycle}) first_hash = Fnv(first_hash, v);
        for (const auto& i : b.o.interrupts) for (const uint64_t v : {i.entry, uint64_t(i.vector), uint64_t(i.handler), uint64_t(i.pc)}) first_hash = Fnv(first_hash, v);
        std::printf("{\"pc\":%u,\"instructions\":%llu,", b.s.pc, (unsigned long long)b.s.instructions);
        std::printf("\"mode\":\"%s\",\"frontier\":\"%s\",\"cycles\":%llu,\"records\":%llu,\"chain\":\"%016llx\",\"first_irq\":\"%016llx\",\"tape_applied\":%zu,"
                    "\"calls\":%llu,\"bus_matched\":%llu,\"mismatches\":%llu,\"hash\":\"%016llx\",\"first_cycle\":%llu,\"last_cycle\":%llu,\"masks\":{",
                    on ? "on" : "off", frontier.c_str(), (unsigned long long)b.Cycles(), (unsigned long long)records, (unsigned long long)chain,
                    (unsigned long long)first_hash, applied, (unsigned long long)watch.calls, (unsigned long long)watch.bus_matched,
                    (unsigned long long)watch.mismatches, (unsigned long long)watch.hash, (unsigned long long)(watch.calls ? watch.first_cycle : 0),
                    (unsigned long long)watch.last_cycle);
        bool comma = false;
        for (const auto& [m, n] : watch.by_mask) { std::printf("%s\"%u\":%llu", comma ? "," : "", unsigned(m), (unsigned long long)n); comma = true; }
        std::printf("},\"pcs\":{");
        comma = false;
        for (const auto& [pc, n] : watch.by_pc) { std::printf("%s\"%08x\":%llu", comma ? "," : "", pc, (unsigned long long)n); comma = true; }
        std::printf("},\"device_paths\":[");
        comma = false;
        for (const auto& e : log.order)
            if (e.kind == mk3::Unverified::DevicePath) { std::printf("%s[%u,%u,%llu]", comma ? "," : "", e.id, e.from, (unsigned long long)e.cycle); comma = true; }
        std::printf("],\"io_reads\":[");
        for (size_t k = 0; k < io_reads.size(); ++k)
            std::printf("%s[%u,%u,%u,%llu]", k ? "," : "", io_reads[k].pc, io_reads[k].address_bit, unsigned(io_reads[k].value), (unsigned long long)io_reads[k].cycle);
        std::printf("]}\n");
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
    return 0;
}
