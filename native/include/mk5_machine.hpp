#pragma once
#include "mk5_program.hpp"
#include <array>
#include <filesystem>
#include <vector>

// State containers of the MK1 rev 5.0 T-Unit board seen by the generated
// graphs (tools/mk1/generate.py). They hold no game logic: every value is
// produced from power-on by generated code and the hardware semantics.
struct Write16 {uint32_t source_pc,address_bit;uint16_t value;};
// TMS34010 register file, status, PC, model cycles and the ordered bus history.
struct ResetTrace {
    std::array<uint32_t,16> a{};
    std::array<uint32_t,15> b{}; // B15 is shared SP (A15), never a second stored value.
    uint32_t status=0x10,next_original_pc=0;
    uint64_t reference_cycles=0;
    std::vector<Write16> writes;
};
// Host storage supplied by the caller. Unwritten words retain their input
// contents; zero initialization is a host choice, not verified PCB power-on RAM.
struct Mk5MemoryBuffers {
    std::vector<uint16_t> ram=std::vector<uint16_t>(262144);
    std::vector<uint16_t> vram=std::vector<uint16_t>(524288);
    std::vector<uint16_t> palette=std::vector<uint16_t>(32768);
};
struct GuestReturn {uint32_t source_pc,target_pc,sp_before;};
struct Mk5CpuHistory {
    ResetTrace cpu;
    uint32_t stack_read_count=0,lowest_sp=0x010ffff0;
    std::vector<GuestReturn> returns;
};
struct CmosBusWrite8 {
    uint32_t source_pc,address_bit;
    uint8_t value;
    bool applied_to_cmos;
    uint16_t before_word,after_word;
    size_t scalar_writes_before;
};
// CPU history plus the battery-backed CMOS (8192 words, low byte per cell).
struct Mk5BoardState {
    Mk5CpuHistory check;
    std::vector<uint16_t> cmos=std::vector<uint16_t>(8192);
    std::vector<CmosBusWrite8> byte_writes;
    uint32_t memory_write_count=0,unique_words_written=0;
};
struct DswRead16 {
    uint32_t source_pc=0,address_bit=0;
    uint16_t raw=0;
    uint32_t extended=0;
};
// IN0|IN1<<16 and IN2|DSW<<16 as the CPU reads them at 01600000h/01600020h.
struct BootDiInputs {uint32_t in01,in2_dsw;};
struct BootDiState {std::array<uint16_t,1024> shiftreg{};uint64_t completed_handlers=0;};
struct BootDiInstruction {uint32_t source_pc,next_pc;uint64_t cycles;};
// Raw CMOS snapshot file: exactly 16384 bytes, 8192 little-endian words.
std::vector<uint16_t> LoadMk5CmosSnapshot(const std::filesystem::path& path);
void SaveMk5CmosSnapshot(const std::filesystem::path& path,const std::vector<uint16_t>& words);
std::vector<uint8_t> Mk5CmosBytes(const std::vector<uint16_t>& words);
