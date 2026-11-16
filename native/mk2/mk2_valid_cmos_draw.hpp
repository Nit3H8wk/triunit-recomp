#pragma once
#include "mk2_valid_cmos_continuation.hpp"
#include "mk2_valid_cmos_draw_boundary.hpp"
namespace mk2 {
inline bool ValidCmosDrawBoundary(const ResetTrace& s) {
    if((s.board.dip_switches!=0xfc7d || OperatorStartupProfile(s)))return OperatorCpuBoundary(s,OperatorBoundary::Draw);
    // Original FC7D factory first draw ff80dd30/7316296 (CPU34 SHA-256, mk2_oracle_digest.hpp).
    return Cpu34Is(s,"d73e16802db7d0d363fac475f467ef5018a9f8a7ce6692c4c206f8f4113e255c");
}
}
