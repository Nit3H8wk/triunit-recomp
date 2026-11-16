#include "mk3_cpu.hpp"
#include "mk3_pixblt.hpp"
#include <climits>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <stdexcept>

// Instruction-level differential driver for tools/mk3/test_pixblt.py. Input (whitespace-separated decimals),
// built from the Original's PIXBLT entry checkpoints: count, then per instruction pc status cycles 31 registers,
// 32 TMS I/O words, video control, DMA_PALETTE, the per-execution timeslice budgets and the VRAM words (CPU view)
// first read there that no earlier PIXBLT wrote. Output: one JSON object (scheduled, single, rejections).
namespace {
constexpr uint32_t kPc = 0xffae8690;
struct Entry {
    uint32_t pc = 0, status = 0;
    unsigned long long cycles = 0;
    std::array<uint32_t, 31> regs{};
    std::array<uint16_t, 32> io{};
    uint16_t video_control = 0, palette = 0;
    std::vector<int32_t> budgets;
    std::vector<std::pair<uint32_t, uint16_t>> seeds;
};
struct Recorder {  // mk3::Ops bus plus a record of every read made by the instruction.
    mk3::Ops& o;
    std::vector<mk3::BusWrite> reads;
    uint16_t Read16(uint32_t address) { const auto v = o.Read16(address); reads.push_back({o.instruction_pc, address, v, o.instruction_cycles}); return v; }
    void Write16(uint32_t address, uint16_t value) { o.Write16(address, value); }
};
void Load(mk3::Ops& o, const Entry& e) {
    auto& s = o.s;
    s.pc = e.pc; s.status = e.status; s.cycles = e.cycles;
    for (unsigned i = 0; i < 31; ++i) (i < 16 ? s.a[i] : s.b[i - 16]) = e.regs[i];
    o.tms_io = e.io; s.video_control = e.video_control; o.dma[8] = e.palette;
    for (const auto& [address, value] : e.seeds) {  // Wolf-Unit select=1 keeps the CPU bytes in the low halves.
        const auto offset = (address / 16) * 2;
        o.vram.at(offset) = uint16_t((o.vram[offset] & 0xff00) | (value & 0xff));
        o.vram.at(offset + 1) = uint16_t((o.vram[offset + 1] & 0xff00) | (value >> 8));
    }
}
void State(const mk3::ResetTrace& s) {
    std::printf("\"pc\":%u,\"status\":%u,\"cycles\":%llu,\"registers\":[", s.pc, s.status, (unsigned long long)s.cycles);
    for (unsigned i = 0; i < 31; ++i) std::printf("%s%u", i ? "," : "", i < 16 ? s.a[i] : s.b[i - 16]);
    std::printf("]");
}
void List(const char* name, const std::vector<mk3::BusWrite>& list, size_t from) {
    std::printf(",\"%s\":[", name);
    for (size_t i = from; i < list.size(); ++i)
        std::printf("%s[%u,%u,%llu]", i > from ? "," : "", list[i].address_bit, list[i].value, (unsigned long long)list[i].cycle);
    std::printf("]");
}
// Runs every instruction; unbounded = one execution each (no timeslice model).
void Run(const mk3::Program& program, const std::vector<Entry>& entries, bool unbounded) {
    mk3::ResetTrace trace;
    mk3::Ops o(program, trace, std::vector<uint16_t>(0x6000));
    Recorder bus{o, {}};
    mk3::PixbltProgress progress;
    std::printf("[");
    for (size_t n = 0; n < entries.size(); ++n) {
        Load(o, entries[n]);
        const size_t writes = trace.writes.size(), reads = bus.reads.size();
        std::printf("%s{\"steps\":[", n ? "," : "");
        const size_t count = unbounded ? 1 : entries[n].budgets.size();
        for (size_t i = 0; i < count; ++i) {
            if (trace.pc != kPc) throw std::runtime_error("PIXBLT left before its reference executions");
            o.Begin();
            const auto step = mk3::PixbltBinaryXY(bus, o.tms_io, trace, progress, unbounded ? INT32_MAX : entries[n].budgets[i]);
            o.Finish(step.completed ? kPc + 16 : kPc, step.cycles);
            std::printf("%s{\"consumed\":%u,\"completed\":%d,", i ? "," : "", step.cycles, int(step.completed));
            State(trace);
            std::printf("}");
        }
        std::printf("]");
        List("writes", trace.writes, writes);
        List("reads", bus.reads, reads);
        std::printf("}");
    }
    std::printf("]");
}
// Each mutation must reject before any bus access.
void Rejections(const mk3::Program& program, const Entry& base) {
    struct Case { const char* label; void (*mutate)(Entry&, mk3::PixbltProgress&); };
    const Case cases[] = {
        {"psize16", [](Entry& e, mk3::PixbltProgress&) { e.io[21] = 16; }},
        {"raster_op", [](Entry& e, mk3::PixbltProgress&) { e.io[11] |= 0x0400; }},
        {"opaque", [](Entry& e, mk3::PixbltProgress&) { e.io[11] &= ~0x20; }},
        {"window", [](Entry& e, mk3::PixbltProgress&) { e.io[11] |= 0x40; }},
        {"shift_register", [](Entry& e, mk3::PixbltProgress&) { e.io[8] |= 0x0800; }},
        {"plane_mask", [](Entry& e, mk3::PixbltProgress&) { e.io[22] = 1; }},
        {"convdp_unwritten", [](Entry& e, mk3::PixbltProgress&) { e.io[20] = 0; }},
        {"p_without_progress", [](Entry& e, mk3::PixbltProgress&) { e.status |= 1u << 25; }},
        {"zero_budget", [](Entry& e, mk3::PixbltProgress&) { e.budgets = {0}; }},
        {"destination_outside_vram", [](Entry& e, mk3::PixbltProgress&) { e.regs[18] = (e.regs[18] & 0xffff) | 0x04000000; }},  // Y 1024
        {"source_outside_rom", [](Entry& e, mk3::PixbltProgress&) { e.regs[16] = 0x01000000; }},
    };
    std::printf("{");
    bool first = true;
    for (const auto& c : cases) {
        Entry e = base;
        mk3::PixbltProgress progress;
        c.mutate(e, progress);
        mk3::ResetTrace trace;
        mk3::Ops o(program, trace, std::vector<uint16_t>(0x6000));
        Recorder bus{o, {}};
        Load(o, e);
        std::string message;
        try { o.Begin(); mk3::PixbltBinaryXY(bus, o.tms_io, trace, progress, e.budgets.at(0)); }
        catch (const std::runtime_error& error) { message = error.what(); }
        const bool clean = !message.empty() && message.find(std::to_string(kPc)) != std::string::npos &&
                           trace.writes.empty() && bus.reads.empty() && trace.status == e.status;
        std::printf("%s\"%s\":%s", first ? "" : ",", c.label, clean ? "true" : "false");
        first = false;
    }
    std::printf("}");
}
}  // namespace

int wmain(int argc, wchar_t** argv) {
    if (argc != 4) return 2;
    try {
        const auto program = mk3::LoadProgram(argv[1]);
        std::ifstream in(argv[2]);
        size_t count = 0;
        if (!(in >> count) || !count) throw std::runtime_error("empty PIXBLT input");
        std::vector<Entry> entries(count);
        for (auto& e : entries) {
            unsigned value = 0;
            size_t n = 0;
            in >> e.pc >> e.status >> e.cycles;
            for (auto& r : e.regs) in >> r;
            for (auto& r : e.io) { in >> value; r = uint16_t(value); }
            in >> value; e.video_control = uint16_t(value);
            in >> value; e.palette = uint16_t(value);
            in >> n; e.budgets.resize(n);
            for (auto& b : e.budgets) in >> b;
            in >> n; e.seeds.resize(n);
            for (auto& [address, v] : e.seeds) { in >> address >> value; v = uint16_t(value); }
            if (!in || e.pc != kPc) throw std::runtime_error("malformed PIXBLT input");
        }
        if (!_wfreopen(argv[3], L"w", stdout)) return 3;
        std::printf("{\"opcode\":%u,\"scheduled\":", program.Word(kPc));
        Run(program, entries, false);
        std::printf(",\"single\":");
        Run(program, entries, true);
        std::printf(",\"rejections\":");
        Rejections(program, entries.front());
        std::printf("}\n");
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
