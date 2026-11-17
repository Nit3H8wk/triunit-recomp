// license:BSD-3-Clause
// copyright-holders:Olivier Galibert,TriUnit Recomp contributors
// Bounded streaming adaptation of MAME 0.280 resampler.cpp's default
// four-point interpolation and pre-decimation average. See LICENSE.txt.
#pragma once
#include <array>
#include <cstdint>
#include <stdexcept>
namespace mk5audio {
class WilliamsResampler {
    std::array<float,256> samples{};
    uint64_t written=0;
    uint32_t rate,divide;
    // Sample's pre-decimation groups are aligned to divide. Accumulate each
    // group once, preserving the original left-to-right float summation order.
    float group_sum=0;std::array<float,256> groups{};
    template<class A> friend void Fields(A& a,WilliamsResampler& r){a(r.samples,r.written,r.group_sum,r.groups);}
    static const std::array<std::array<float,4097>,2>& Table(){
        static const auto table=[] {
            std::array<std::array<float,4097>,2> t{};
            for(unsigned i=1;i<4096;++i){float p=i/4096.0f;t[0][i]=(p-p*p*p)/6;}
            for(unsigned i=1;i<=2048;++i){float p=i/4096.0f;t[1][i]=p+(p*p-p*p*p)/2;}
            // MAME deliberately evaluates this symmetry correction in double.
            for(unsigned i=2049;i<4096;++i)t[1][i]=1.0+t[0][i]+t[0][4096-i]-t[1][4096-i];
            t[1][4096]=1.0f;return t;
        }();return table;
    }
    float At(int64_t index)const{
        if(index<0)return 0;
        if(uint64_t(index)>=written || written-uint64_t(index)>samples.size())throw std::logic_error("audio reconstruction history range");
        return samples[size_t(index)%samples.size()];
    }
public:
    explicit WilliamsResampler(uint32_t source_rate):rate(source_rate),divide(rate<=48000?1:1+rate/48000){
        if(!rate || 5*divide+rate/48000+1>samples.size())throw std::invalid_argument("audio reconstruction rate");
    }
    uint64_t Written()const{return written;}
    void Push(float sample){samples[size_t(written)%samples.size()]=sample;group_sum+=sample;++written;if(written%divide==0){groups[size_t(written/divide-1)%groups.size()]=group_sum/divide;group_sum=0;}}
    float Sample(uint64_t output_index)const{
        // The reference speaker updates at 50 Hz and includes the sample at
        // its current time: first block 0..960, then 961..1920, etc. Its
        // lo-fi kernel starts each block with a 12-bit phase, then advances
        // by a truncated 24-bit step. Recomputing the rational position for
        // every sample changes both that truncation and block restart rounding.
        const uint64_t block_start=output_index<=960?0:1+(output_index-1)/960*960;
        const uint64_t seconds=block_start/48000,dsamp=block_start%48000;
        const uint64_t position=dsamp*rate*4096/48000;
        uint64_t integer=(position>>12)+seconds*rate;
        unsigned phase=unsigned(position&4095);
        if(divide>1){unsigned delta=unsigned(integer%divide);phase=(phase|(delta<<12))/divide;integer-=delta;}
        const uint64_t step=uint64_t(rate)*0x1000000/48000/divide;
        const uint64_t advance=(uint64_t(phase)<<12)+(output_index-block_start)*step;
        integer+=(advance>>24)*divide;
        phase=unsigned((advance&0xffffff)>>12);
        int64_t cursor=int64_t(integer)-4*int64_t(divide);
        auto next=[&]{auto group=cursor/int64_t(divide);cursor+=divide;if(group<0)return 0.f;if(uint64_t(group)>=written/divide || written-uint64_t(group)*divide>samples.size())throw std::logic_error("audio averaged history range");return groups[size_t(group)%groups.size()];};
        float s0=next(),s1=next(),s2=next(),s3=next();const auto& t=Table();
        return -s0*t[0][4096-phase]+s1*t[1][4096-phase]+s2*t[1][phase]-s3*t[0][phase];
    }
};
}
