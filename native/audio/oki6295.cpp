// Integer OKI ADPCM arithmetic derived from pinned BSD-3-Clause reference.
#include "oki6295.hpp"
#include <algorithm>
#include <stdexcept>
#include <utility>
namespace mk5audio {
void Adpcm::Reset(){signal_=step_=0;}
int16_t Adpcm::Clock(uint8_t nibble){
 static constexpr int steps[]={16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552};
 static constexpr int changes[]={-1,-1,-1,-1,2,4,6,8};
 const int step=steps[step_];int delta=step/8;
 if(nibble&4)delta+=step;
 if(nibble&2)delta+=step/2;
 if(nibble&1)delta+=step/4;
 signal_=std::clamp(signal_+((nibble&8)?-delta:delta),-2048,2047);
 step_=std::clamp(step_+changes[nibble&7],0,48);
 return int16_t(signal_);
}
}
namespace mk5audio {
WilliamsSamples::WilliamsSamples(std::vector<uint8_t> a,std::vector<uint8_t>b):u12_(std::move(a)),u13_(std::move(b)){
 if(u12_.size()!=0x40000||u13_.size()!=0x40000)throw std::invalid_argument("Williams U12/U13 require262144bytes each");
}
void WilliamsSamples::SelectBank(uint8_t v){bank_=v&7;}
uint8_t WilliamsSamples::Read(uint32_t address)const{
 if(address>0x3ffff)throw std::out_of_range("OKI18-bit address");
 if(address>=0x20000)return u12_[address];
 static constexpr uint32_t offset[]={0,0,0x20000,0,0x20000,0,0x20000,0};
 return (bank_<4?u12_:u13_)[offset[bank_]+address];
}
Oki6295::Oki6295(const WilliamsSamples&s,uint32_t c,bool h):samples_(s),clock_hz_(c),divisor_(h?132:165){if(!c)throw std::invalid_argument("OKI nonzero clock required");}
void Oki6295::Write(uint8_t data){
 static constexpr uint8_t levels[]={32,22,16,11,8,6,4,3,2,0,0,0,0,0,0,0};
 if(pending_>=0){
  const uint32_t table=uint32_t(pending_)*8;
  const uint32_t start=((uint32_t(samples_.Read(table))<<16)|(uint32_t(samples_.Read(table+1))<<8)|samples_.Read(table+2))&0x3ffff;
  const uint32_t stop=((uint32_t(samples_.Read(table+3))<<16)|(uint32_t(samples_.Read(table+4))<<8)|samples_.Read(table+5))&0x3ffff;
  for(unsigned i=0;i<4;i++)if((data&(0x10u<<i))&&!voices_[i].playing&&start<stop){
   auto&v=voices_[i];v.playing=true;v.base=start;v.position=0;v.count=2*(stop-start+1);v.volume=levels[data&15];v.adpcm.Reset();
  }
  pending_=-1;
 }else if(data&0x80)pending_=data&0x7f;
 else for(unsigned i=0;i<4;i++)if(data&(8u<<i))voices_[i].playing=false;
}
uint8_t Oki6295::Status()const{uint8_t out=0xf0;for(unsigned i=0;i<4;i++)if(voices_[i].playing)out|=uint8_t(1u<<i);return out;}
void Oki6295::Reset(){for(auto&v:voices_)v.playing=false;}
std::vector<int32_t> Oki6295::StepSamples(size_t count){
 if(count>1000000||count>UINT64_MAX-generated_)throw std::overflow_error("OKI sample budget/overflow");
 std::vector<int32_t> out(count);
 for(size_t i=0;i<count;i++)for(auto&v:voices_)if(v.playing){
  const uint8_t byte=samples_.Read(v.base+v.position/2);
  const uint8_t nibble=(v.position&1)?byte&15:byte>>4;
  // MAME add_int takes an s32 sample: truncate each voice at its original
  // volume before summing. Levels are exact multiples of 1/32.
  out[i]+=(int32_t(v.adpcm.Clock(nibble))*v.volume/32)*32;
  if(++v.position>=v.count)v.playing=false;
 }
 generated_+=count;return out;
}
std::vector<int32_t> Oki6295::AdvanceNanoseconds(uint64_t elapsed){
 if(elapsed>(UINT64_MAX-phase_)/clock_hz_)throw std::overflow_error("OKI clock multiplication");
 const uint64_t total=phase_+elapsed*clock_hz_,denominator=uint64_t(divisor_)*1000000000;
 const uint64_t count=total/denominator;
 if(count>1000000)throw std::overflow_error("OKI sample budget");
 auto out=StepSamples(size_t(count));phase_=total%denominator;return out;
}
}
