#pragma once
// MK3 save states at a TMS instruction boundary where `stop` ended Board::Run (resumable): CPU34, memories, DMA,
// video timers, DCS/ADSP, the board scheduler, the scanout and, in the Remastered edition, its DMA layers, plus the
// host fields the caller names (audio stream, PCM cursor). ROMs, observers, stop callbacks, logs and the
// configuration stay bound to the live session, so a load restores state inside the same machine.
#include "mk3_board.hpp"
#include "mk3_dma_observer.hpp"
#include "../mk2/mk2_state_io.hpp"
#include "mk5_program.hpp"

namespace mk3 {
inline constexpr uint32_t kSaveStateVersion = 1;
inline constexpr const char* kSaveStateRevision = "mk3 2.1";
inline constexpr const char* kSaveStateMagic = "TRIUNIT-MK3-STATE";
static_assert(mk2::state::kBlock<Board::As> && mk2::state::kBlock<VideoTiming::Atto>, "128-bit times are copied as blocks");

template<class A> void Fields(A& a, BusWrite& w) { a(w.pc, w.address_bit, w.value, w.cycle); }
template<class A> void Fields(A& a, ResetTrace& s) {
    a(s.a, s.b, s.status, s.pc, s.cycles, s.instructions, s.writes, s.ram, s.video_control, s.io, s.reads, s.rand, s.pic, s.dcs_control);
}
template<class A> void Fields(A& a, Dma& d) { a(d.reg, d.vram, d.draws); }
template<class A> void Fields(A& a, VideoTiming& v) {
    a(v.io, v.scan_expire, v.scan_param, v.dma_armed, v.dma_expire, v.di_count, v.last_di_cycle, v.int1_count,
      v.last_int1_cycle, v.hblank_stable);
}
template<class A> void Fields(A& a, OpsState::Interrupt& i) { a(i.entry, i.vector, i.handler, i.pc, i.status, i.sp); }
template<class A> void Fields(A& a, OpsState::DcsWrite& w) { a(w.sound, w.value); }
// Not state: cosim, dma_skew, io_default_reads and profile (configuration), `noted` (the first-execution log's cache).
template<class A> void Fields(A& a, OpsState& o) {
    a(o.ram, o.cmos, o.cmos_enable, o.palette, o.blitter, o.video, o.elapsed, o.interrupts, o.ports, o.pixblt,
      o.instruction_pc, o.taken_, o.taken_handler_, o.taken_index_, o.instruction_cycles, o.dcs_known, o.dcs_writes,
      o.dcs_output, o.dcs_reads, o.syncs, o.sync_cycle, o.int1_seen, o.io_written, o.shiftreg, o.slice_end, o.empty_reads);
}
template<class A> void Fields(A& a, AdspAccess& x) { a(x.boot, x.cycle, x.pc, x.kind, x.address, x.value); }
template<class A> void Fields(A& a, HostEvent& e) { a(e.kind, e.write_ns, e.end_ns, e.value, e.slice_min_ns, e.slice_max_ns); }
template<class A> void Fields(A& a, DacBlock& d) { a(d.ns, d.boot, d.cycle, d.address, d.step, d.first, d.count, d.sample_ns, d.arm); }
template<class A> void Fields(A& a, Scanout& s) {
    a(s.pens, s.frame, s.last_partial_scan, s.frames, s.lines, s.fighter_work, s.fighters, s.backdrop_pens, s.backdrop);
}
template<class A> void Fields(A& a, DmaSource& s) { a(s.producer, s.list, s.scroll, s.routine, s.object, s.appender, s.bound); }
template<class A> void Fields(A& a, DmaQueue& q) { a(q.list, q.scroll, q.routine, q.direct, q.staged, q.appended); }
template<class A> void Fields(A& a, ObjectBinder& o) { a(o.bound, o.effect_parent, o.freed, o.effect, o.pending); }
template<class A> void Fields(A& a, DmaLayers& l) {
    a(l.queue, l.objects, l.stored, l.under, l.cls, l.fighters, l.draws, l.pixels, l.cpu_words, l.bound_draws, l.now,
      l.token, l.cpu_begin, l.cpu_end);
}

namespace state {
struct Header { std::string magic, program, revision, edition, payload; uint32_t version = 0; };
template<class A> void Fields(A& a, Header& h) { a(h.magic, h.version, h.program, h.revision, h.edition, h.payload); }
// The Remastered edition is the one with DMA layers; nothing else in the emulation differs between them.
inline std::string Edition(const DmaLayers* layers) { return layers ? "remastered" : "original"; }
// Identity and integrity before anything is applied; a refused file leaves the session untouched.
inline mk2::state::Reader CheckLiveState(const Program& program, const std::vector<uint8_t>& bytes, const std::string& edition) {
    mk2::state::Reader reader{bytes.data(), bytes.data() + bytes.size()};
    Header header;
    reader(header);
    if (header.magic != kSaveStateMagic || header.version != kSaveStateVersion || header.revision != kSaveStateRevision)
        throw std::invalid_argument("MK3 save state format or revision differs");
    if (header.program != program.sha256) throw std::invalid_argument("MK3 save state belongs to another program ROM");
    if (header.edition != edition) throw std::invalid_argument("MK3 save state belongs to another edition");
    if (header.payload != Sha256(std::vector<uint8_t>(reader.at, reader.end))) throw std::invalid_argument("MK3 save state payload is damaged");
    return reader;
}
template<class A, class... Host> void Session(A& a, Board& b, Scanout& scanout, DmaLayers* layers, Host&... host) {
    a(b, scanout);
    if (layers) a(*layers);
    a(host...);
}
inline void RequireBoundary(const Board& b) {
    if (!b.StoppedInTimeslice()) throw std::logic_error("MK3 save state requires Run stopped at a TMS instruction boundary");
}
}

// Only after `stop` ended Board::Run; the next Run resumes the restored timeslice.
template<class... Host> std::vector<uint8_t> SaveLiveState(const Program& program, Board& b, Scanout& scanout,
                                                         DmaLayers* layers, Host&... host) {
    state::RequireBoundary(b);
    mk2::state::Writer payload;   // the writer only reads its operands
    state::Session(payload, b, scanout, layers, host...);
    state::Header header{kSaveStateMagic, program.sha256, kSaveStateRevision, state::Edition(layers), Sha256(payload.bytes), kSaveStateVersion};
    mk2::state::Writer out;
    out(header);
    out.bytes.insert(out.bytes.end(), payload.bytes.begin(), payload.bytes.end());
    return std::move(out.bytes);
}
// Call CheckLiveState first to refuse a file without side effects; a failure here leaves partial state and is fatal.
template<class... Host> void LoadLiveState(const Program& program, const std::vector<uint8_t>& bytes, Board& b, Scanout& scanout,
                                           DmaLayers* layers, Host&... host) {
    auto reader = state::CheckLiveState(program, bytes, state::Edition(layers));
    state::RequireBoundary(b);
    state::Session(reader, b, scanout, layers, host...);
    if (reader.at != reader.end) throw std::runtime_error("MK3 save state has trailing data");
    state::RequireBoundary(b);
}
}
