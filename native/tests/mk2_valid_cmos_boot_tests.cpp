#include "native/mk2/mk2_executor.hpp"
#include "native/mk2/mk2_adsp.hpp"
#include "native/mk2/mk2_cmos_image.hpp"
#include "native/mk2/mk2_valid_cmos_boot.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
void check(bool value) { if(!value)throw std::runtime_error("valid boot candidate contract"); }
// Generated closure from reset with the factory image: CPU34 at the former reset, board, powerup, video and
// text boundaries (PC, cycle in the arguments) and the CMOS words at the valid revision message.
int main(int argc,char** argv) { try {
 check(argc>=3);
 const auto p=mk2::LoadProgram(argv[1]);const auto rom=mk2::LoadDcsDataRoms(argv[1]);
 const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
 std::ifstream input(argv[2],std::ios::binary);check(bool(input));
 const std::vector<uint8_t> image{std::istreambuf_iterator<char>(input),{}};
 mk2::DcsBootMachine m(boot,rom);m.dsp.SetTraceObservation(false);
 mk2::GeneratedBoot generated(p,m,&image,0xfc7d);
 const auto& s=generated.State().ready;
 std::cout<<"{\"CPU34\":[";
 for(int n=3;n<argc;++n) {
  const std::string point=argv[n];const auto colon=point.find(':');
  generated.RunTo(uint32_t(std::stoul(point.substr(0,colon))),std::stoull(point.substr(colon+1)));
  std::cout<<(n>3?",":"")<<'['<<s.next_pc<<','<<s.status<<','<<s.cycles;
  for(auto r:s.a)std::cout<<','<<r;
  for(auto r:s.b)std::cout<<','<<r;
  std::cout<<']';
 }
 check(mk2::ValidCmosBootBoundary(s,4));
 auto rejected=s;rejected.a[1]^=1;check(!mk2::ValidCmosBootBoundary(rejected,4));
 std::cout<<"],\"cmos\":[";
 for(unsigned n=0;n<s.cmos.size();++n)std::cout<<(n?",":"")<<s.cmos[n];
 std::cout<<"]}\n";
 // Difficulty 1..5 with the recomputed checksum: the firmware's own CMOS check accepts each image (A1).
 for(unsigned difficulty=1;difficulty<=5;++difficulty) {
  auto adjusted=image;
  adjusted.at(0x1076)=uint8_t(difficulty);
  unsigned sum=0;for(unsigned n=0;n<168;++n)sum+=adjusted.at(0x1000+2*n);
  const auto checksum=uint16_t(~sum);
  adjusted.at(0x1150)=uint8_t(checksum>>8);adjusted.at(0x1152)=uint8_t(checksum);
  mk2::DcsBootMachine configured(boot,rom);configured.dsp.SetTraceObservation(false);
  mk2::GeneratedBoot variant(p,configured,&adjusted,0xfc7d);
  variant.RunToPc(0xffa5a6e0);
  check(variant.State().ready.a[1]==checksum && mk2::ValidCmosBootBoundary(variant.State().ready,4));
 }
 for(uint16_t dsw:{uint16_t(0xfc7d),uint16_t(0xbc7d),uint16_t(0x7c7d),uint16_t(0x3c7d)}) {
  mk2::DcsBootMachine configured(boot,rom);configured.dsp.SetTraceObservation(false);
  mk2::GeneratedBoot variant(p,configured,&image,dsw);
  variant.RunToPc(0xff811150);
  check(variant.State().ready.board.dip_switches==dsw);
 }
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
