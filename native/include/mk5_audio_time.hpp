#pragma once
#include <cstdint>
#include <stdexcept>
namespace mk5audio {
// Absolute 2 MHz CPU time plus an exact fraction. One cycle is 3,579,545
// fraction units. Timer rearming retains its oscillator phase even when the
// CPU observes expiry at the next 500 ns bus boundary.
struct YmTime {
    uint64_t cycle=UINT64_MAX;
    uint32_t fraction=0;
    bool Due(uint64_t now)const{return cycle<now || (cycle==now && !fraction);}
    YmTime AfterClocks(uint32_t clocks)const{
        const uint64_t numerator=uint64_t(clocks)*2000000+fraction;
        const uint64_t whole=numerator/3579545;
        if(cycle>UINT64_MAX-whole-1)throw std::overflow_error("YM timer time");
        return {cycle+whole,uint32_t(numerator%3579545)};
    }
};
}
