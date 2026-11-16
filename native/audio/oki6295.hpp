#pragma once
#include <cstdint>
namespace mk5audio {
class Adpcm {
 int signal_=0,step_=0;
public:
 void Reset();
 int16_t Clock(uint8_t nibble);
 int signal()const{return signal_;}
 int step()const{return step_;}
};
}

#include <array>
#include <cstddef>
#include <vector>
namespace mk5audio {
class WilliamsSamples {
 std::vector<uint8_t> u12_,u13_; uint8_t bank_=0;
public:
 WilliamsSamples(std::vector<uint8_t> u12,std::vector<uint8_t> u13);
 void SelectBank(uint8_t value);
 uint8_t Read(uint32_t address)const;
 uint8_t bank()const{return bank_;}
};
struct Voice {bool playing=false;uint32_t base=0,position=0,count=0;uint8_t volume=0;Adpcm adpcm;};
class Oki6295 {
 const WilliamsSamples& samples_;std::array<Voice,4> voices_{};int pending_=-1;
 uint32_t clock_hz_,divisor_;uint64_t phase_=0,generated_=0;
public:
 explicit Oki6295(const WilliamsSamples&,uint32_t clock_hz=1000000,bool pin7_high=true);
 void Write(uint8_t data);
 uint8_t Status()const;
 void Reset(); // Reference chip reset stops voices; pending command/clock survive.
 std::vector<int32_t> StepSamples(size_t count);
 std::vector<int32_t> AdvanceNanoseconds(uint64_t elapsed_ns);
 uint64_t generated_samples()const{return generated_;}
 uint64_t phase_numerator()const{return phase_;}
 uint32_t divisor()const{return divisor_;}
 const std::array<Voice,4>& voices()const{return voices_;}
};
}
