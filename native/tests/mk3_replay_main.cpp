#include "mk3_board.hpp"
#include "mk3_dcs.hpp"
#include <algorithm>
#include <array>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>

// MK3 route replay for tools/mk3/replay.py: one native run of mk3::Board from reset (the way
// native/tests/mk3_cosim_tests.cpp drives it) with a legal input tape, emitting the complete state at checkpoints as
// compact JSON lines on stdout (region hashes; whole regions only where a dump is asked).
// argv: ROM directory, CMOS seed, graphics list ("region_offset size path" rows of the "video" region), spec file.
// Spec lines (cycles are TMS cycles; a checkpoint is the first instruction boundary at a cycle >= C with ST.P clear,
// the rule tools/mk3/replay_reference.py gives the Original's registerpoint):
//   every FIRST STEP LAST   periodic checkpoints FIRST, FIRST+STEP, ... <= LAST; several due at one boundary give one record
//   point C                 one more record at the first boundary >= C (after the periodic one there)
//   horizon H               stop at the first boundary >= H (END record there)
//   tape CYCLE PORT VALUE   from the boundary >= CYCLE on, io port PORT (0-3: IN0, IN1, DSW, IN2) reads VALUE
//   dump REGION CYCLE       whole REGION (ram cmos palette vram dm pm) as hex at the first boundary >= CYCLE (0: at END)
//   window LO HI            every bus write and device read with LO <= cycle <= HI, after the run (several lines: their union)
//   mutate WORD XOR CYCLE   negative control: main RAM word WORD ^= XOR at the boundary >= CYCLE
//   profile game            mk3::Profile::Game (default Strict); the summary carries the first-execution log per kind
//   profile strict-routes   Strict that also accepts the route-verified keys (mk3::RouteVerifiedSet, tools/mk3/route_verified.json)
//   first all               the summary also lists every first execution [kind, id, from, cycle] (first_set)
//   bot PERIOD WORD...      closed-loop input source (tools/mk3/tower.py bot): from the first tape-free boundary on, every
//                           PERIOD cycles prints {"bot":CYCLE,"w":[main RAM words at the bit addresses WORD...],"dcs":[new
//                           sound port values]} and reads one stdin line of "PORT VALUE" pairs, applied at that boundary
//                           (only reads the machine; the pairs are legal input rows "CYCLE PORT VALUE" of a later tape)
//   events                  event streams: each record carries, per stream, the count and running FNV-1a 64 of its events
//                           since reset; after the summary, the whole dcs, input and cmos streams (the dma one is too long)
//   fork N                  exploration snapshot (mk3::Board copy; search only, never an acceptance): the lines above are the
//                           base, run from reset up to the first boundary >= N, where the Board and this harness are copied
//                           before that boundary is handled ({"snapshot":...}); the lines below are commands:
//     branch                a continuation of the current snapshot; the lines after it, up to the next command, are added
//                           to its spec: tape / point / horizon / mutate (cycle >= N) and dump (cycle 0 or >= N); "keep" also
//                           copies it before it handles its horizon boundary; "drop latches" (negative control) resets the
//                           copy's DCS latches to their power-on values
//     run                   runs the branches given since the last run, in parallel; prints, per branch in order,
//                           {"branch":K} and then exactly the lines a run from reset of base + branch prints after the base's
//                           records; then {"ran":COUNT}
//     adopt K               the kept copy of branch K becomes the snapshot (N = its horizon)
//     serve                 the next commands come from stdin (tools/mk3/replay.py Explorer)
// Bus writes/reads are kept only inside the windows (the summary counts all of them).
// Event streams (the ResetTrace bus records: cycle of the instruction start, value as on the bus), each event hashed as
// address, value, cycle low, cycle high: dcs = writes to the sound port 0x01680000 (dcs data_w); dma = writes to the DMA
// registers 0x01a00000-0x01a000ff and the mirror 0x01a80000-0x01a800ff; input = reads of io offsets 0-3 (IN0 IN1 DSW
// IN2, value returned); cmos = writes to 0x01400000-0x0145ffff (enabled or not, as midwunit cmos_w receives them).
namespace {
constexpr uint32_t kPixbltRestart = 0x02000000;   // ST.P: a PIXBLT restart re-entry is not an instruction boundary

uint64_t Fnv(uint64_t h, uint32_t v) { return (h ^ v) * 0x100000001b3ull; }
constexpr uint64_t kFnvBasis = 0xcbf29ce484222325ull;
// Little-endian 32-bit words of a 16-bit word image (the MAME share bytes read as u32).
uint64_t HashWords(const uint16_t* w, size_t n) {
    uint64_t h = kFnvBasis;
    for (size_t i = 0; i + 1 < n; i += 2) h = Fnv(h, uint32_t(w[i]) | uint32_t(w[i + 1]) << 16);
    return h;
}

std::vector<uint8_t> LoadGraphics(const char* list) {   // ROM_LOAD32_BYTE, stride 4, sizes checked (as mk3_cosim_tests.cpp)
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

// The ADSP views compared (native/tests/mk3_cosim_tests.cpp PrintDcs ranges): PM words and DM words.
bool PmMapped(unsigned a) { return a < 0x400 || (a >= 0x800 && a < 0x2000); }
bool DmMapped(unsigned a) { return a < 0x3000 || (a >= 0x3800 && a < 0x3a00); }

struct Spec {
    uint64_t first = 0, step = 0, last = 0, horizon = ~0ull;
    std::vector<std::pair<uint64_t, uint64_t>> windows;
    struct Tape { uint64_t cycle; unsigned port; uint16_t value; };
    std::vector<Tape> tape;
    std::vector<std::pair<std::string, uint64_t>> dumps;
    std::vector<uint64_t> points;
    struct Mutation { uint32_t word; uint16_t mask; uint64_t cycle; };
    std::vector<Mutation> mutations;
    bool game = false, routes = false, first_all = false, events = false;
    uint64_t bot = 0;
    struct BotWord { uint32_t address; bool pointer; uint32_t offset; };
    std::vector<BotWord> bot_words;
};

Spec ReadSpec(const std::vector<std::string>& lines) {
    Spec s;
    for (const std::string& line : lines) {
        std::istringstream row(line);
        std::string key;
        if (!(row >> key)) continue;
        bool ok = true;
        if (key == "every") ok = bool(row >> s.first >> s.step >> s.last) && s.step && s.first >= 1000;
        else if (key == "horizon") ok = bool(row >> s.horizon);
        else if (key == "point") { uint64_t c = 0; ok = bool(row >> c) && c >= 1000 && (s.points.empty() || c >= s.points.back()); s.points.push_back(c); }
        else if (key == "window") { uint64_t lo = 0, hi = 0; ok = bool(row >> lo >> hi) && lo <= hi; s.windows.emplace_back(lo, hi); }
        else if (key == "first") { std::string all; ok = bool(row >> all) && all == "all"; s.first_all = true; }
        else if (key == "events") s.events = true;
        else if (key == "bot") {
            ok = bool(row >> s.bot) && s.bot;
            for (std::string t; row >> t;) {   // WORD, or POINTER:OFFSET (the word at OFFSET bits past the long at POINTER)
                const size_t colon = t.find(':');
                const uint32_t w = uint32_t(std::stoul(t.substr(0, colon))), off = colon == std::string::npos ? 0 : uint32_t(std::stoul(t.substr(colon + 1)));
                ok = ok && w >= 0x01000000 && w < 0x01400000 && !(w & 15) && !(off & 15);
                s.bot_words.push_back({w, colon != std::string::npos, off});
            }
        }
        else if (key == "tape") {
            Spec::Tape t{}; unsigned value = 0;
            ok = bool(row >> t.cycle >> t.port >> value) && t.port < 4 && value <= 0xffff && t.cycle >= 1000 &&
                 (s.tape.empty() || t.cycle >= s.tape.back().cycle);
            t.value = uint16_t(value); s.tape.push_back(t);
        } else if (key == "dump") {
            std::string region; uint64_t cycle = 0;
            ok = bool(row >> region >> cycle); s.dumps.emplace_back(region, cycle);
        } else if (key == "mutate") {
            Spec::Mutation m{}; unsigned mask = 0;
            ok = bool(row >> m.word >> mask >> m.cycle) && m.word < 0x40000 && mask && mask <= 0xffff;
            m.mask = uint16_t(mask); s.mutations.push_back(m);
        } else if (key == "profile") {
            std::string name;
            ok = bool(row >> name) && (name == "game" || name == "strict" || name == "strict-routes");
            s.game = name == "game"; s.routes = name == "strict-routes";
        } else ok = false;
        if (!ok) throw std::runtime_error("invalid replay spec line: " + line);
    }
    s.events = s.events || s.bot;
    return s;
}

std::string Hex(const std::vector<uint8_t>& bytes) {
    static const char* d = "0123456789abcdef";
    std::string out(bytes.size() * 2, '0');
    for (size_t i = 0; i < bytes.size(); ++i) { out[2 * i] = d[bytes[i] >> 4]; out[2 * i + 1] = d[bytes[i] & 15]; }
    return out;
}
// Output of one run: stdout, or a buffer (fork branches run in parallel and are printed in order afterwards).
void Put(std::string* buffer, const char* format, ...) {
    va_list args;
    va_start(args, format);
    if (!buffer) std::vprintf(format, args);
    else {
        va_list again;
        va_copy(again, args);
        const int n = std::vsnprintf(nullptr, 0, format, again);
        va_end(again);
        const size_t at = buffer->size();
        buffer->resize(at + size_t(n) + 1);
        std::vsnprintf(&(*buffer)[at], size_t(n) + 1, format, args);
        buffer->resize(at + size_t(n));
    }
    va_end(args);
}

template <class T> void Append(std::vector<uint8_t>& out, T v) { for (unsigned k = 0; k < sizeof(T); ++k) out.push_back(uint8_t(uint64_t(v) >> (8 * k))); }

std::vector<uint8_t> Region(const mk3::Board& b, const std::string& name) {
    std::vector<uint8_t> out;
    const auto words = [&](const std::vector<uint16_t>& w) { for (const uint16_t v : w) Append(out, v); };
    if (name == "ram") words(b.o.ram);
    else if (name == "cmos") words(b.o.cmos);
    else if (name == "palette") words(b.o.palette);
    else if (name == "vram") words(b.o.vram);
    else if (name == "dm") { for (unsigned a = 0; a < 0x4000; ++a) if (DmMapped(a)) Append(out, b.dcs.DebugData(uint16_t(a))); }
    else if (name == "pm") { for (unsigned a = 0; a < 0x2000; ++a) if (PmMapped(a)) Append(out, b.dcs.DebugProgram(uint16_t(a))); }
    else throw std::runtime_error("unknown replay region " + name);
    return out;
}

// Event streams scanned from the bus records as they grow (before any trim).
struct Events {
    static constexpr const char* kNames[4] = {"dcs", "dma", "input", "cmos"};
    struct Event { uint64_t cycle; uint32_t address; uint16_t value; };
    std::array<std::vector<Event>, 4> all;            // dma kept only as count and hash
    std::array<uint64_t, 4> count{}, hash{};
    size_t writes_seen = 0, reads_seen = 0;
    Events() { hash.fill(kFnvBasis); }
    static int WriteStream(uint32_t a) {
        if (a == 0x01680000) return 0;
        if ((a & ~0x00080000u) >= 0x01a00000 && (a & ~0x00080000u) <= 0x01a000ff) return 1;
        if (a >= 0x01400000 && a <= 0x0145ffff) return 3;
        return -1;
    }
    void Add(int k, const mk3::BusWrite& w) {
        const uint64_t c = w.cycle;
        for (const uint32_t v : {w.address_bit, uint32_t(w.value), uint32_t(c), uint32_t(c >> 32)}) hash[k] = Fnv(hash[k], v);
        ++count[k];
        if (k != 1) all[k].push_back({c, w.address_bit, w.value});
    }
    void Scan(const mk3::ResetTrace& s) {
        for (; writes_seen < s.writes.size(); ++writes_seen) if (const int k = WriteStream(s.writes[writes_seen].address_bit); k >= 0) Add(k, s.writes[writes_seen]);
        for (; reads_seen < s.reads.size(); ++reads_seen) {
            const auto& r = s.reads[reads_seen];
            if (r.address_bit >= 0x01800000 && r.address_bit <= 0x0187fff0 && mk3::Ops::IoOffset(r.address_bit) < 4) Add(2, r);
        }
    }
    std::string Cumulative() const {   // ,"events":{...} of a record: count and running hash since reset
        std::string out = ",\"events\":{";
        char row[96];
        for (unsigned k = 0; k < 4; ++k) {
            std::snprintf(row, sizeof row, "%s\"%s\":[%llu,\"%llx\"]", k ? "," : "", kNames[k], (unsigned long long)count[k], (unsigned long long)hash[k]);
            out += row;
        }
        return out + "}";
    }
    void PrintAll(std::string* out) const {
        Put(out, "{\"events_total\":{");
        for (unsigned k = 0; k < 4; ++k) Put(out, "%s\"%s\":[%llu,\"%llx\"]", k ? "," : "", kNames[k], (unsigned long long)count[k], (unsigned long long)hash[k]);
        Put(out, "},\"events_full\":{");
        for (unsigned k = 0, n = 0; k < 4; ++k) {
            if (k == 1) continue;
            Put(out, "%s\"%s\":[", n++ ? "," : "", kNames[k]);
            for (size_t i = 0; i < all[k].size(); ++i) {
                const auto& e = all[k][i];
                if (k == 0) Put(out, "%s[%llu,%u]", i ? "," : "", (unsigned long long)e.cycle, unsigned(e.value));
                else if (k == 2) Put(out, "%s[%llu,%u,%u]", i ? "," : "", (unsigned long long)e.cycle, mk3::Ops::IoOffset(e.address), unsigned(e.value));
                else Put(out, "%s[%llu,%u,%u]", i ? "," : "", (unsigned long long)e.cycle, e.address, unsigned(e.value));
            }
            Put(out, "]");
        }
        Put(out, "}}\n");
    }
};

// First-execution log (Profile::Game): per kind the count and the first entries [id, from, cycle].
void PrintFirst(std::string* out, const mk3::FirstExecution& log, bool all) {
    static const char* names[] = {"TmsBlock", "TmsEdge", "AdspBlock", "AdspEdge", "DmaPath", "IrqPath", "DevicePath"};
    Put(out, "\"first_executions\":{");
    for (unsigned k = 0; k < 7; ++k) {
        size_t n = 0;
        Put(out, "%s\"%s\":{\"first\":[", k ? "," : "", names[k]);
        for (const auto& e : log.order)
            if (unsigned(e.kind) == k && n++ < 16) Put(out, "%s[%u,%u,%llu]", n > 1 ? "," : "", e.id, e.from, (unsigned long long)e.cycle);
        Put(out, "],\"count\":%zu}", n);
    }
    Put(out, "}");
    if (!all) return;
    Put(out, ",\"first_set\":[");
    for (size_t k = 0; k < log.order.size(); ++k) {
        const auto& e = log.order[k];
        Put(out, "%s[%u,%u,%u,%llu]", k ? "," : "", unsigned(e.kind), e.id, e.from, (unsigned long long)e.cycle);
    }
    Put(out, "]");
}

struct Snapshot;
// The harness state of one run, copied with the Board at a fork: spec, event streams, first-execution log and the
// progress through the spec. `last`: the last boundary handled.
struct Session {
    std::vector<std::string> lines;   // spec lines (a branch: its snapshot's lines, then its own)
    Spec spec;
    Events events;
    mk3::FirstExecution log;
    std::string* out = nullptr;       // null: stdout
    size_t pcm_seen = 0, nonzero = 0, writes_dropped = 0, reads_dropped = 0, bot_dcs = 0;
    size_t tape = 0, mutation = 0, dump = 0, point = 0;
    uint64_t next = ~0ull, bot_next = 0, last = 0;
    std::vector<std::pair<std::string, uint64_t>> dumps;   // spec.dumps by cycle; 0: at the END record
    uint64_t stop_at = ~0ull;         // fork: the first boundary >= stop_at is left unhandled (keep: handled after a copy)
    bool keep = false, forked = false;
    std::shared_ptr<Snapshot> kept;

    // The spec of `lines`. A branch only adds entries past `last`: the progress indices stay, the sorted dumps are redone.
    void Parse() {
        spec = ReadSpec(lines);
        dumps = spec.dumps;
        std::stable_sort(dumps.begin(), dumps.end(), [](const auto& x, const auto& y) { return x.second < y.second; });
        for (dump = 0; dump < dumps.size() && (!dumps[dump].second || (last && dumps[dump].second <= last)); ++dump) {}
        if (!last) next = spec.step ? spec.first : ~0ull;
    }
    bool Inside(uint64_t cycle) const {
        for (const auto& [lo, hi] : spec.windows) if (cycle >= lo && cycle <= hi) return true;
        return false;
    }
    void Emit(const mk3::Board& b, const char* at) {
        const auto& s = b.s;
        Put(out, "{\"spec\":%s,\"cycle\":%llu,\"pc\":%u,\"status\":%u,\"instructions\":%llu,\"registers\":[", at,
            (unsigned long long)b.Cycles(), s.pc, s.status, (unsigned long long)s.instructions);
        for (unsigned i = 0; i < 31; ++i) Put(out, "%s%u", i ? "," : "", i < 16 ? s.a[i] : s.b[i - 16]);
        uint64_t dm = kFnvBasis, pm = kFnvBasis, pcm = kFnvBasis;
        for (unsigned a = 0; a < 0x4000; ++a) if (DmMapped(a)) dm = Fnv(dm, b.dcs.DebugData(uint16_t(a)));
        for (unsigned a = 0; a < 0x2000; ++a) if (PmMapped(a)) pm = Fnv(pm, b.dcs.DebugProgram(uint16_t(a)));
        for (size_t k = pcm_seen; k < b.dcs.pcm.size(); ++k) { pcm = Fnv(pcm, uint16_t(b.dcs.pcm[k])); nonzero += b.dcs.pcm[k] != 0; }
        Put(out, "],\"hash\":{\"ram\":\"%llx\",\"cmos\":\"%llx\",\"palette\":\"%llx\",\"vram\":\"%llx\",\"dm\":\"%llx\",\"pm\":\"%llx\"},",
            (unsigned long long)HashWords(b.o.ram.data(), b.o.ram.size()), (unsigned long long)HashWords(b.o.cmos.data(), b.o.cmos.size()),
            (unsigned long long)HashWords(b.o.palette.data(), b.o.palette.size()), (unsigned long long)HashWords(b.o.vram.data(), b.o.vram.size()),
            (unsigned long long)dm, (unsigned long long)pm);
        Put(out, "\"dma\":[");
        for (size_t k = 0; k < b.o.dma.size(); ++k) Put(out, "%s%u", k ? "," : "", b.o.dma[k]);
        Put(out, "],\"io\":[");
        for (size_t k = 0; k < b.o.tms_io.size(); ++k) Put(out, "%s%u", k ? "," : "", b.o.tms_io[k]);
        Put(out, "],\"control\":%u,\"pcm\":{\"count\":%zu,\"segment\":%zu,\"hash\":\"%llx\",\"nonzero\":%zu},\"adsp\":{\"frozen\":%s,\"boot\":%u,\"latch\":%u,\"fields\":[",
            s.video_control, b.dcs.pcm.size(), b.dcs.pcm.size() - pcm_seen, (unsigned long long)pcm, nonzero,
            b.dcs_frontier.empty() ? "false" : "true", b.dcs.boot, b.dcs.latch_control);
        const auto fields = b.dcs.Fields();
        for (size_t k = 0; k < fields.size(); ++k) Put(out, "%s%llu", k ? "," : "", (unsigned long long)fields[k]);
        std::vector<uint8_t> samples;   // the DAC samples stored since the previous record, whole
        for (size_t k = pcm_seen; k < b.dcs.pcm.size(); ++k) Append(samples, uint16_t(b.dcs.pcm[k]));
        if (spec.events) events.Scan(b.s);
        Put(out, "]},\"samples\":\"%s\"%s}\n", Hex(samples).c_str(), spec.events ? events.Cumulative().c_str() : "");
        pcm_seen = b.dcs.pcm.size();
    }
    void Dump(const mk3::Board& b, const std::string& region, uint64_t at) {
        Put(out, "{\"dump\":\"%s\",\"spec\":%llu,\"hex\":\"%s\"}\n", region.c_str(), (unsigned long long)at, Hex(Region(b, region)).c_str());
    }
    bool Handle(mk3::Board& b);   // the stop callback
    void Finish(mk3::Board& b, const std::string& frontier);
};
struct Snapshot { mk3::Board board; Session session; uint64_t at; };   // at: every boundary handled so far is < at

bool Session::Handle(mk3::Board& b) {
    const uint64_t cycle = b.Cycles();
    if (cycle < 1000 || (b.s.status & kPixbltRestart)) return false;   // tape rows apply from cycle 1000 / restart re-entry
    if (cycle >= stop_at) {
        if (!keep) { forked = true; return true; }
        if (!kept) { Session copy = *this; copy.out = nullptr; kept.reset(new Snapshot{b, copy, stop_at}); }
    }
    if (spec.events) events.Scan(b.s);   // before the trim: every bus record is seen once
    const auto trim = [&](auto& list, size_t& dropped) {   // bounded memory on long routes: keep the window entries only
        if (list.size() < (size_t(1) << 20)) return;
        const auto kept_end = std::remove_if(list.begin(), list.end(), [&](const auto& x) { return !Inside(x.cycle); });
        dropped += size_t(list.end() - kept_end); list.erase(kept_end, list.end());
    };
    trim(b.s.writes, writes_dropped); trim(b.s.reads, reads_dropped);
    if (spec.events) { events.writes_seen = b.s.writes.size(); events.reads_seen = b.s.reads.size(); }
    for (; tape < spec.tape.size() && spec.tape[tape].cycle <= cycle; ++tape) b.o.ports[spec.tape[tape].port] = spec.tape[tape].value;
    if (spec.bot && tape == spec.tape.size() && cycle >= bot_next) {
        bot_next = cycle + spec.bot;   // the events stream is on (bot implies events) and scanned above
        std::printf("{\"bot\":%llu,\"w\":[", (unsigned long long)cycle);
        const auto peek = [&](uint32_t a) -> unsigned { return a >= 0x01000000 && a < 0x01400000 ? b.o.ram[(a - 0x01000000) >> 4] : 0; };
        for (size_t k = 0; k < spec.bot_words.size(); ++k) {
            const auto& w = spec.bot_words[k];
            const uint32_t a = w.pointer ? (peek(w.address) | peek(w.address + 16) << 16) + w.offset : w.address;
            std::printf("%s%u", k ? "," : "", peek(a));   // outside main RAM: 0
        }
        std::printf("],\"dcs\":[");
        for (size_t k = bot_dcs; k < events.all[0].size(); ++k) std::printf("%s%u", k > bot_dcs ? "," : "", unsigned(events.all[0][k].value));
        bot_dcs = events.all[0].size();
        std::printf("]}\n");
        std::fflush(stdout);
        std::string reply;
        if (!std::getline(std::cin, reply)) throw std::runtime_error("bot: no reply");
        std::istringstream pairs(reply);
        for (unsigned port, value; pairs >> port >> value;) {
            if (port > 3 || value > 0xffff) throw std::runtime_error("bot: bad reply " + reply);
            b.o.ports[port] = uint16_t(value);
        }
    }
    for (; mutation < spec.mutations.size() && spec.mutations[mutation].cycle <= cycle; ++mutation)
        b.o.ram[spec.mutations[mutation].word] ^= spec.mutations[mutation].mask;
    if (next <= cycle && next <= spec.last) {
        const uint64_t due = next;
        next += spec.step * (1 + (cycle - next) / spec.step);   // the Original's registerpoint does the same
        Emit(b, std::to_string(due).c_str());
    }
    for (; point < spec.points.size() && spec.points[point] <= cycle; ++point) Emit(b, std::to_string(spec.points[point]).c_str());
    for (; dump < dumps.size() && dumps[dump].second <= cycle; ++dump) Dump(b, dumps[dump].first, dumps[dump].second);
    last = cycle;
    return cycle >= spec.horizon;
}

void Session::Finish(mk3::Board& b, const std::string& frontier) {
    Emit(b, "\"end\"");
    for (const auto& [region, at] : spec.dumps) if (!at) Dump(b, region, 0);   // dump REGION 0: at the END record
    Put(out, "{\"frontier\":\"%s\",\"dcs_frontier\":\"%s\",\"tape_applied\":%zu,\"mutations_applied\":%zu,\"writes\":%zu,\"reads\":%zu,\"host_events\":%zu,\"interrupts\":%zu,\"dac_ns\":[",
        frontier.c_str(), b.dcs_frontier.c_str(), tape, mutation, b.s.writes.size() + writes_dropped, b.s.reads.size() + reads_dropped,
        b.host_events.size(), b.o.interrupts.size());
    for (size_t k = 0; k < b.dcs.dac_blocks.size(); ++k) Put(out, "%s%llu", k ? "," : "", (unsigned long long)b.dcs.dac_blocks[k].ns);
    Put(out, "],\"profile\":\"%s\",", spec.game ? "game" : spec.routes ? "strict-routes" : "strict");
    PrintFirst(out, log, spec.first_all);
    Put(out, "}\n");
    if (spec.events) events.PrintAll(out);
    if (!spec.windows.empty()) {
        Put(out, "{\"window\":[");
        bool first = true;
        for (const auto& w : b.s.writes)
            if (Inside(w.cycle)) {
                Put(out, "%s[%u,%u,%u,%llu]", first ? "" : ",", w.pc, w.address_bit, w.value, (unsigned long long)w.cycle);
                first = false;
            }
        Put(out, "],\"reads\":[");
        first = true;
        for (const auto& r : b.s.reads)
            if (Inside(r.cycle)) {
                Put(out, "%s[%u,%u,%u,%llu]", first ? "" : ",", r.pc, r.address_bit, r.value, (unsigned long long)r.cycle);
                first = false;
            }
        Put(out, "]}\n");
    }
}

// Profile, ADSP access log and stop callback of the Board that `z` drives (again after a copy: the copy's point at the source).
void Bind(mk3::Board& b, Session& z) {
    if (z.spec.game) b.SetProfile(mk3::Profile::Game, &z.log);
    else if (z.spec.routes) b.SetProfile(mk3::Profile::Strict, &z.log, &mk3::RouteVerifiedSet());
    b.dcs.observe_access = [](const mk3::Dcs8k&, const mk3::AdspAccess&) { return false; };   // no ADSP access history (bounded memory)
    b.stop = [&z, &b](const mk3::Board&) { return z.Handle(b); };
}

std::string RunToEnd(mk3::Board& b) {
    try { b.Run(); } catch (const std::runtime_error& e) { return e.what(); }
    return "none";
}

void PrintSnapshot(const Snapshot& s) {
    const auto& b = s.board;
    std::printf("{\"snapshot\":%llu,\"at\":%llu,\"pc\":%u,\"instructions\":%llu,\"pending_syncs\":%zu,\"boost\":%s,\"dma_command\":%u,"
                "\"latch_control\":%u,\"input_data\":%u,\"output_data\":%u,\"adsp_ns\":%llu}\n",
                (unsigned long long)b.Cycles(), (unsigned long long)s.at, b.s.pc, (unsigned long long)b.s.instructions, b.PendingSyncs(),
                b.Boosted() ? "true" : "false", unsigned(b.o.dma[mk3::Dma::COMMAND]), b.dcs.latch_control, b.dcs.input_data,
                b.dcs.output_data, (unsigned long long)b.dcs.local_ns);
    std::fflush(stdout);
}

// One continuation of a snapshot: its own copy of the Board and the harness, with the extra spec lines of the branch.
struct Branch {
    std::vector<std::string> lines;
    std::string out;
    std::shared_ptr<Snapshot> kept;
};
void RunBranch(const Snapshot& from, Branch& branch) {
    std::unique_ptr<Snapshot> s(new Snapshot{from.board, from.session, from.at});
    Session& z = s->session;
    bool drop = false;
    for (const std::string& line : branch.lines) {
        std::istringstream row(line);
        std::string key, word;
        uint64_t cycle = 0, w = 0, m = 0;
        row >> key;
        bool ok = true;
        if (key == "keep") z.keep = true;
        else if (key == "drop") { ok = bool(row >> word) && word == "latches"; drop = true; }
        else if (key == "tape" || key == "point" || key == "horizon") ok = bool(row >> cycle) && cycle >= from.at;
        else if (key == "mutate") ok = bool(row >> w >> m >> cycle) && cycle >= from.at;
        else if (key == "dump") ok = bool(row >> word >> cycle) && (!cycle || cycle >= from.at);
        else ok = false;
        if (!ok) throw std::runtime_error("invalid branch line: " + line);
        if (key != "keep" && key != "drop") z.lines.push_back(line);
    }
    z.Parse();
    z.out = &branch.out;
    if (z.keep && z.spec.horizon == ~0ull) throw std::runtime_error("keep without a horizon");
    z.stop_at = z.keep ? z.spec.horizon : ~0ull;
    if (drop) { s->board.dcs.latch_control = 0x0c00; s->board.dcs.input_data = 0; s->board.dcs.output_data = 0; }
    Bind(s->board, z);
    z.Finish(s->board, RunToEnd(s->board));
    if (z.kept) {
        branch.kept = z.kept;
        Session& k = branch.kept->session;
        k.stop_at = ~0ull; k.keep = false;
        Bind(branch.kept->board, k);
    }
}
}

int main(int argc, char** argv) {
    if (argc != 5) return 2;
    try {
        const auto program = mk3::LoadProgram(argv[1]);
        const auto u2 = mk3::LoadDcsU2(argv[1]);
        std::ifstream seed(argv[2], std::ios::binary);
        const std::vector<uint8_t> cmos{std::istreambuf_iterator<char>(seed), std::istreambuf_iterator<char>()};
        const auto gfx = LoadGraphics(argv[3]);
        std::vector<std::string> lines, script;   // script: the commands after `fork`
        uint64_t fork = 0;
        {
            std::ifstream in(argv[4]);
            for (std::string line; std::getline(in, line);) {
                std::istringstream row(line);
                std::string key;
                if (!(row >> key)) continue;
                if (fork) script.push_back(line);
                else if (key == "fork") { if (!(row >> fork) || fork < 1000) throw std::runtime_error("invalid replay spec line: " + line); }
                else lines.push_back(line);
            }
        }
        std::shared_ptr<Snapshot> base(new Snapshot{mk3::Board(program, cmos, u2, gfx), Session{}, fork});
        mk3::Board& b = base->board;
        Session& z = base->session;
        z.lines = lines;
        z.Parse();
        if (fork && z.spec.bot) throw std::runtime_error("fork with a bot");
        b.dcs.AttachSoundData(argv[1]);   // U3-U5 (authenticated by Dcs8k): the data banks 0x100-0x3ff, as the Original loads them
        Bind(b, z);
        std::printf("{\"fields\":[");
        for (size_t k = 0; k < mk3::Dcs8k::FieldNames().size(); ++k) std::printf("%s\"%s\"", k ? "," : "", mk3::Dcs8k::FieldNames()[k].c_str());
        std::printf("]}\n");
        z.stop_at = fork ? fork : ~0ull;
        const std::string frontier = RunToEnd(b);
        if (!fork) { z.Finish(b, frontier); std::fflush(stdout); return 0; }
        if (!z.forked) throw std::runtime_error("fork: the base run ended before cycle " + std::to_string(fork) + " (" + frontier + ")");
        z.stop_at = ~0ull;
        PrintSnapshot(*base);
        std::shared_ptr<Snapshot> current = base;
        std::vector<Branch> branches;
        bool serve = false, ran = false;   // ran: the next `branch` starts a new batch
        for (size_t k = 0;;) {
            std::string line;
            if (serve) { if (!std::getline(std::cin, line)) break; }
            else if (k < script.size()) line = script[k++];
            else break;
            std::istringstream row(line);
            std::string key;
            if (!(row >> key)) continue;
            if (key == "branch") { if (ran) branches.clear(); ran = false; branches.emplace_back(); }
            else if (key == "run") {
                std::vector<std::thread> threads;
                std::vector<std::string> errors(branches.size());
                for (size_t i = 0; i < branches.size(); ++i)
                    threads.emplace_back([&, i] { try { RunBranch(*current, branches[i]); } catch (const std::exception& e) { errors[i] = e.what(); } });
                for (auto& t : threads) t.join();
                for (const auto& e : errors) if (!e.empty()) throw std::runtime_error(e);
                for (size_t i = 0; i < branches.size(); ++i) {
                    std::printf("{\"branch\":%zu}\n", i);
                    std::fwrite(branches[i].out.data(), 1, branches[i].out.size(), stdout);
                    branches[i].out.clear();
                }
                std::printf("{\"ran\":%zu}\n", branches.size());
                std::fflush(stdout);
                ran = true;
            } else if (key == "adopt") {
                size_t i = 0;
                if (!(row >> i) || i >= branches.size() || !branches[i].kept) throw std::runtime_error("adopt: no kept branch: " + line);
                current = branches[i].kept;
                branches.clear();
                PrintSnapshot(*current);
            } else if (key == "serve") serve = true;
            else if (key == "quit") break;
            else if (branches.empty()) throw std::runtime_error("command before any branch: " + line);
            else branches.back().lines.push_back(line);
        }
        std::fflush(stdout);
    } catch (const std::exception& e) {
        std::fflush(stdout);
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
    return 0;
}
