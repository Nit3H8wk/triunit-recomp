#pragma once
#include "mk2_oracle_digest.hpp"
#include "mk2_reset.hpp"
#include "mk2_operator_boundaries.hpp"
#include <algorithm>
namespace mk2 {
inline constexpr uint16_t kTestSwitchDsw=0xfc7c;
inline constexpr uint64_t kTestSwitchPostCycle=311977, kTestSwitchResetCycle=6607535;
inline constexpr uint64_t kTestSwitchIrqCycle=6852682, kTestSwitchStartupCycle=6855614;
inline constexpr char kTestSwitchFactorySha256[]="f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f";

// MAME 0.280 FC7C factory startup guards (SHA-256, mk2_oracle_digest.hpp), with the native executed DSP clock.
// The observed registers are compared against live state and never installed.
inline bool TestSwitchCpuBoundary(const ResetTrace& s,unsigned stage) {
    static constexpr const char* expected[]={
        "b9ba41967c759eba188bd226a1f14eb2703c35c85519e4d9bf7368d339db5e49", // ffa5b090
        "251b8452d23d63d5f6e2b6a995336b65428143de5253626e9139414706da2f2c", // ff811340
        "269f6629709c52ce08459529acd2bd8356d9c0151d1f21b116df23a7385a56da", // ff815090
        "f8f486849be4e954adec1826ce65d6295ffd0786a6abc675a24b61587edb6a6e", // ff8114d0
        "02eb32bdc7155ee97b6140aa980921eb9b5cce051c0378c29097e59e1c48f0dc", // ffa38c10
    };
    if (s.board.dip_switches!=kTestSwitchDsw || stage>=std::size(expected)) return false;
    return Cpu34Is(s,expected[stage]);
}

inline bool TestSwitchDspBoundary(const std::vector<uint64_t>& registers,unsigned stage) {
    static constexpr const char* expected[]={
        "1bd2d4d9635e3672a069a45b3e690d887345fbd97bc17e846033fac1bf0a5c89",
        "7c1ed496a73b2900bfeeab767e89e9f2f745b818c73b8e07d0b3c82e044daa9f",
        "1ce49d0be3e65868af0e8e4f3ab5466243f77aae8eeb33faac209a76319bd1c8",
        "ec1014efd4b96d65d1e718dad1e56118d424511432272476c6398c48da33a3ff",
    };
    return stage>=1 && stage<=std::size(expected) && registers.size()==76 && WordsDigest(registers)==expected[stage-1];
}

// Original measured CPU34 boundaries are comparisons only, never imported state.
inline bool ValidCmosStartupBoundary(const ResetTrace& s,unsigned index) {
 if(s.board.dip_switches==kTestSwitchDsw)return index<4 && TestSwitchCpuBoundary(s,index+1);
 if((s.board.dip_switches!=0xfc7d || OperatorStartupProfile(s)) && index==6)return OperatorCpuBoundary(s,OperatorBoundary::StartupDi);
 if((s.board.dip_switches!=0xfc7d || OperatorStartupProfile(s)) && index<6){
  const OperatorBoundary stages[]={OperatorBoundary::Reset,OperatorBoundary::Button,OperatorBoundary::Irq,
   OperatorBoundary::Startup,OperatorBoundary::Yield,OperatorBoundary::Setup};
  return OperatorCpuBoundary(s,stages[index]);
 }
 static constexpr const char* expected[7]={
  "b172188b3180d47465680d2fa515e7621bf5703285197e847503f9b6fa0a4054",
  "283a12fb755d314b6afa553521186f17dc0cfb87abb98f4b7c38b720fbc57e73",
  "6ecbf37916f0162f962516192e2cadc42beccc7fa4daa4243474698d1af6dda5",
  "41c0f1f22ea43c95aca44f466c55f1f606c70434ef02d405f4ba81c0307168dd",
  "0ef21d182d0c431d2b62dc88efe782104ba176abad40efcacc52824e112d1e95",
  "a676ac790b28324b90e4ada25012f5e714ad229158270806da79067fed702904",
  "5ad8644c243535d2c204131f31f7c820cfe1dcfa1fa1d034bff739b43d81c677",
 };
 if(index>=7)return false;
 return Cpu34Is(s,expected[index]);
}
}
