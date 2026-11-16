#pragma once
#include "mk2_oracle_digest.hpp"
#include "mk2_reset.hpp"
#include "mk2_valid_cmos_startup.hpp"
namespace mk2 {
// Original observed CPU34 boundaries (SHA-256, mk2_oracle_digest.hpp) are guards only; never assigned to guest state.
inline bool ValidCmosBootBoundary(const ResetTrace& s,unsigned index) {
    if(index==5 && s.board.dip_switches==kTestSwitchDsw)return TestSwitchCpuBoundary(s,0);
    if(index==5 && (s.board.dip_switches!=0xfc7d || OperatorStartupProfile(s)))return OperatorCpuBoundary(s,OperatorBoundary::Post);
    static constexpr struct { uint64_t pc, cycle; const char* cpu34; } expected[6]={
        {0xff8111f0ull,0x74cull,"770635de027f0dc91c7a860842d85fcc5eb375e8b547e35dd8c60ad6aa41aabe"},
        {0xffa5c200ull,0x826ull,"1326f8339c88f96cc869e0d963408ceea2fd6a9282b43b6a9235539e13f99f6e"},
        {0xffa5a000ull,0x18864ull,"14159ede7c4b754fc8d56884a211dad9b3a984efff3da77283710495b0757640"},
        {0xffa5a190ull,0x488e6ull,"094d7805ed765e1e571a45c229dc2e8017ecb1bb95770e405203eb036fe6a432"},
        {0xffa5a6e0ull,306026ull,"cbb1ee40fdab8683315b99d4c2229a8c2382b07770ed4bdafe6332492473754d"}, // A1 digested as 0
        {0xffa5b090ull,311971ull,"81b1b7dedfc50af415b405b6d35cbd880e67129b22f9e531971d6e83caef2ab4"},
    };
    if(index>=6) return false;
    const auto& e=expected[index];
    if(s.next_pc!=e.pc || s.cycles!=e.cycle) return false;
    auto row=Cpu34(s);
    if(index==4) {
        if(s.cmos.size()!=8192) return false;
        uint32_t sum=0;for(unsigned k=0;k<168;++k)sum+=uint8_t(s.cmos[0x800+k]);
        const uint32_t expected_a=uint16_t(~sum); // FFA4C250 retains the computed checksum in A1.
        if(((uint32_t(uint8_t(s.cmos[0x8a8]))<<8)|uint8_t(s.cmos[0x8a9]))!=expected_a)return false;
        if(s.a[1]!=expected_a)return false;
        row[4]=0;
    }
    return Cpu34Is(row,e.cpu34);
}
}
