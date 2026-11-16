#pragma once
#include "mk2_oracle_digest.hpp"
#include "mk2_reset.hpp"
#include "mk2_operator_boundaries.hpp"
namespace mk2 {
inline bool ValidCmosDrawTrapBoundary(const ResetTrace& s) {
    if((s.board.dip_switches!=0xfc7d || OperatorStartupProfile(s)))return OperatorCpuBoundary(s,OperatorBoundary::Trap);
    return Cpu34Is(s,"c3262196c9589f46ae927e28239da4c34ded5f75dc6012bc57145c2cde80ee42");
}
inline bool ValidCmosDrawDmaBoundary(const ResetTrace& s) {
    const bool factory=s.board.dip_switches==0xfc7d&&!OperatorStartupProfile(s);
    const char* expected=factory?"0b53600a31e18198790309e1b63dab9a6213040d3f2b1e0a8e9233741019d4f0":
        OperatorCpuDigest(s.board.dip_switches,OperatorBoundary::Dma,OperatorStartupProfile(s));
    // The authenticated 32-bit MOVE -*B14,-*B10 has decremented both pointers before its high-word bus write.
    auto row=Cpu34(s);
    row[19+10]+=32;row[19+14]+=32;
    return Cpu34Is(row,expected);
}
}
