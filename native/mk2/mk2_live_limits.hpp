#pragma once
#include <cstdint>
#include <limits>
#include <stdexcept>
namespace mk2 { namespace live_detail {
inline constexpr uint64_t kRequestCycles=2000000,kCooperativeSlack=2000000;
inline constexpr uint64_t kChunkWallTimeoutMs=10000;
inline uint64_t ChunkDeadline(uint64_t current,uint64_t requested) {
    const auto max=std::numeric_limits<uint64_t>::max();
    if(requested<=current || requested-current>kRequestCycles || requested>max-kCooperativeSlack)
        throw std::invalid_argument("MK2 live requires an increasing request of at most2M cycles");
    const auto end=requested+kCooperativeSlack;
    // Preserve the existing absolute32-bit scanline/active-update counters; never wrap or reset them.
    constexpr uint64_t last=(uint64_t(std::numeric_limits<unsigned>::max())-1)*6325+94875-15;
    if(end>last/16 || end>(max-uint64_t(1023)*1023*41)/160)
        throw std::overflow_error("MK2 live absolute hardware counter capacity exhausted");
    return end;
}
inline uint64_t DspInstructionCeiling(uint64_t count,uint64_t dsp_ticks,uint64_t main_deadline) {
    const auto max=std::numeric_limits<uint64_t>::max();
    if(main_deadline>(max-15)/16)throw std::overflow_error("MK2 live DSP deadline overflow");
    const auto target=main_deadline*16+15;
    if(target<dsp_ticks)throw std::invalid_argument("MK2 live DSP clock exceeds renewed deadline");
    const auto steps=(target-dsp_ticks)/10;
    if(count>max-steps)throw std::overflow_error("MK2 live DSP instruction counter overflow");
    return count+steps;
}
}}
