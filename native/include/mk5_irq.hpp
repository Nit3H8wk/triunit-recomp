#pragma once
#include "mk5_machine.hpp"
#include <functional>

// Explicit host epoch. The frozen boot prefix did not establish raster phase
// or pending IRQ state. Quanta are 10ns; a CPU model cycle is 16 quanta.
struct Mk5IrqEpoch {
    std::array<uint16_t,32> io{};
    uint16_t next_scanline=0;
    uint32_t quanta_to_next_scanline=0;
};
struct Mk5IrqEntry {
    uint32_t source_pc,return_pc,saved_status,vector_bit,target_pc;
    uint16_t source_mask;
    int external_line;
    bool stacked;
    uint64_t at_quanta;
};
struct Mk5ScanlineEvent {uint64_t at_quanta;uint16_t vcount,dpyadr;bool display_pending;};

// Fixed interrupt/raster operations for translated functions. No opcode fetch,
// instruction decoder, CPU dispatcher, guest handler execution or tick write.
// Exclusive live CPU/RAM pair; not copyable/serializable. No OOM rollback.
// Power-on construction leaves the raster unstarted: CPU time accumulates, IO
// writes are recorded as requests and an enabled interrupt is a hard error.
// Start() then declares the host raster epoch (pending, next line, phase) from
// the requested registers, exactly once, before the first EINT.
class Mk5IrqController {
    const VerifiedMk5Program& program_;
    ResetTrace& cpu_;
    Mk5MemoryBuffers& memory_;
    std::array<uint16_t,32> io_;
    uint16_t next_scanline_;
    uint64_t elapsed_=0,next_edge_=0,line_quanta_=0;
    bool started_=true;
    uint32_t requested_=0;
    void validate_epoch(uint32_t quanta_to_next);
    std::vector<Mk5IrqEntry> entries_;
    std::vector<Mk5ScanlineEvent> scanlines_;
    std::function<void(const Mk5ScanlineEvent&,const std::array<uint16_t,32>&)> scanline_observer_;
    void guard()const;
    void guard_advance(uint64_t cycles)const;
    void guard_frame(bool push)const;
    void push(uint32_t pc,uint32_t value);
    uint32_t pop();
    void advance(uint64_t cycles);
public:
    void SetScanlineObserver(std::function<void(const Mk5ScanlineEvent&,const std::array<uint16_t,32>&)>);
    void ClearScanlineObserver(){scanline_observer_={};}
    Mk5IrqController(const VerifiedMk5Program&,ResetTrace&,Mk5MemoryBuffers&,const Mk5IrqEpoch&);
    Mk5IrqController(const VerifiedMk5Program&,ResetTrace&,Mk5MemoryBuffers&);
    bool Started()const{return started_;}
    // IO = last requests of registers 0..27 (all required); INTPEND=pending,
    // DPYADR=DPYSTRT, VCOUNT=next_line-1 (or VTOTAL for line 0). elapsed=0.
    void Start(uint16_t pending,uint16_t next_line,uint32_t quanta_to_next);
    bool Requested(unsigned index)const{return index<32 && ((requested_>>index)&1);}
    Mk5IrqController(const Mk5IrqController&)=delete;
    Mk5IrqController& operator=(const Mk5IrqController&)=delete;
    const std::array<uint16_t,32>& io()const{return io_;}
    const std::vector<Mk5IrqEntry>& entries()const{return entries_;}
    const std::vector<Mk5ScanlineEvent>& scanlines()const{return scanlines_;}
    // The most recent real entry is also the continuation provenance consumed
    // by the active DI guard. Preserve it verbatim across host history pruning.
    void DiscardDiagnostics(){if(entries_.size()>1)entries_.erase(entries_.begin(),entries_.end()-1);scanlines_.clear();}
    uint64_t elapsed_quanta()const{return elapsed_;}
    uint64_t quanta_to_next_scanline()const{return next_edge_-elapsed_;}
    uint16_t SampleHcount()const;
    bool IsBoundTo(const ResetTrace& cpu,const Mk5MemoryBuffers& memory)const{return &cpu_==&cpu && &memory_==&memory;}
    // Conservative barrier for fixed blocks that preserve IE/INTENB and do not
    // generate sources. False means instruction-level scheduling is required.
    bool CanRunIrqFree(uint64_t cycles)const;
    // A translated block has already charged CPU cycles. Adopt its time without
    // charging CPU again; use only after CanRunIrqFree(max_block_cycles).
    void AdoptBlockCycles(uint64_t cycles);
    // Advance instruction/block time only; caller checks at execution boundary.
    // Each call is bounded to <=65536 scanline events before any effects.
    void AdvanceCycles(uint64_t cycles);
    bool CheckBoundary(uint32_t source_pc);
    bool Eint(uint32_t source_pc,uint32_t next_pc);
    void Dint(uint32_t source_pc,uint32_t next_pc);
    bool Reti(uint32_t source_pc);
    bool PopStatus(uint32_t source_pc,uint32_t next_pc);
    bool SetStatus(uint32_t source_pc,uint32_t status);
    bool WriteEnable(uint32_t source_pc,uint16_t value);
    // Aligned 16-bit requests used by the translated handler; instruction cost
    // is charged separately. Returns true if INTENB causes immediate entry.
    bool WriteIo16(uint32_t source_pc,uint32_t address_bit,uint16_t value);
    void WritePending(uint16_t value);
    void SetExternalLine(unsigned line,bool asserted);
    void LatchInternal(uint16_t mask);
};
