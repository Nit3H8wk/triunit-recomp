#include "mk5_operator_settings.hpp"
#include "mk5_program.hpp"
#ifdef MKOPERATOR_ORACLE
#include "mk5_task_body.hpp"
#endif
#include "../mk2/mk2_factory_seed.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace {
void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
#ifdef MKOPERATOR_ORACLE
// The game's own power-on through the generated graph, one cabinet snapshot:
// stops at the first task (valid CMOS) or inside the post-restore input wait.
struct PowerOn {Mk5BoardState board;TaskBodyStop stop;};
PowerOn power_on(const VerifiedMk5Program& program,const std::vector<uint16_t>& cmos,uint16_t dsw){
  PowerOn out;out.board.cmos=cmos;Mk5MemoryBuffers memory;BootDiState di;
  Mk5IrqController irq(program,out.board.check.cpu,memory);Mk5TaskBodyRunner runner(program,out.board,memory,irq,di);
  Mk5BootInputs in;in.ports={0xffffffffu,0xffffu|(uint32_t(dsw)<<16)};in.pending=0x400;in.next_line=1;in.quanta_to_next=6325;in.instruction_budget=24000000;
  out.stop=runner.Boot(in).stop;return out;
}
#endif
template<class F>void rejects(F action){bool failed=false;try{action();}catch(const std::exception&){failed=true;}require(failed,"invalid operation accepted");}
std::vector<uint8_t> read(const std::filesystem::path& path){std::ifstream f(path,std::ios::binary);if(!f)throw std::runtime_error("test input unavailable");return {std::istreambuf_iterator<char>(f),{}};}
}
int wmain(int argc,wchar_t** argv){
 try{
  require(argc==2,"project root required");const std::filesystem::path root=argv[1];
  // Program image of the user's ROMs staged by the setup (roms/mk1): lane 0 at even, lane 1 at odd bytes.
  const auto even=read(root/"roms/mk1/mkt-uj12.bin"),odd=read(root/"roms/mk1/mkt-ug12.bin");
  require(even.size()==524288 && odd.size()==524288,"MK1 program lanes (python tools/setup/setup.py --game mk1)");
  std::vector<uint8_t> program(1048576);for(size_t i=0;i<524288;++i){program[2*i]=even[i];program[2*i+1]=odd[i];}
  // CMOS seed written by the setup for this program image (the game's factory restore, tools/setup/mk1.make_seed).
  auto image=read(root/"generated/mk1"/Sha256(program)/"factory-default-control-input.bin");
  require(mkoperator::ReadParameter(image,14)==3,"native difficulty default");
  require(mkoperator::SettingsChecksumValid(image),"native seed settings checksum");
  auto original=image;mkoperator::WriteParameter(image,14,5);mkoperator::UpdateSettingsChecksum(image);
  require(mkoperator::ReadParameter(image,14)==5,"difficulty roundtrip");
  for(size_t i=0;i<image.size();++i)if(i%2 || ((i<0x1070 || i>0x1076) && i!=0x1150 && i!=0x1152))require(image[i]==original[i],"parameter changed unrelated byte");
  unsigned sum=0;for(size_t i=0;i<168;++i)sum+=image[0x1000+i*2];
  require(((unsigned(image[0x1150])<<8)|image[0x1152])==((~sum)&65535),"settings checksum order");
  require(mkoperator::SettingsChecksumValid(image),"updated settings checksum");
  image[0x1000]^=1;require(!mkoperator::SettingsChecksumValid(image),"corrupt checksum rejected");
  require(mkoperator::CoinageLabel(mkoperator::Game::Mk1,program,1)=="USA 1","ROM preset label");
  require(mkoperator::CoinageLabel(mkoperator::Game::Mk1,program,20)=="FRANCE 5","native compressed pricing label");
  for(unsigned preset=1;preset<=58;++preset)require(!mkoperator::CoinageLabel(mkoperator::Game::Mk1,program,preset).empty(),"all ROM presets labelled");
  for(unsigned preset:{1u,2u,3u,58u}){
   image=original;mkoperator::ApplyMk1Coinage(image,program,preset,false);
   require(mkoperator::ReadParameter(image,1)==preset && mkoperator::ReadParameter(image,18)==0,"coinage selection");
   const unsigned expectedStart=preset==1||preset==2?2:1;
   if(preset!=58)require(mkoperator::ReadParameter(image,11)==expectedStart,"native coinage start price");
   if(preset<=3)require(mkoperator::ReadParameter(image,12)==(preset==1?2u:1u),"native continue price");
  }
  image=original;mkoperator::ApplyMk1Coinage(image,program,3,true);require(mkoperator::ReadParameter(image,18)==1,"free play native flag");
  image=original;for(size_t i=0;i<image.size();++i)if(i%2)image[i]=uint8_t(i*13);original=image;
  mkoperator::ResetMk1HighScores(image,program);
  require(image[0x1800]==2 && image[0x1802]==17 && image[0x1804]==11 && image[0x1806]==10,"native initial record CRL 10");
  require(image[0x190e]==0xad && image[0x1910]==0x0f,"native streak checksum 4013");
  for(size_t i=0;i<image.size();++i)if(i%2 || i<0x1800 || i>0x1910)require(image[i]==original[i],"reset changed unrelated byte");
  auto repeated=image;mkoperator::ResetMk1HighScores(repeated,program);require(repeated==image,"ranking reset idempotent");
  auto changedProgram=program;changedProgram[17]^=1;
  auto before=image;rejects([&]{mkoperator::ResetMk1HighScores(image,changedProgram);});require(image==before,"bad ROM mutated image");
  rejects([&]{mkoperator::ApplyMk1Coinage(image,program,0,false);});require(image==before,"bad preset mutated image");
  rejects([&]{mkoperator::ApplyMk1Coinage(image,program,59,false);});require(image==before,"bad preset mutated image");
  rejects([&]{mkoperator::WriteParameter(image,42,1);});require(image==before,"bad index mutated image");
  rejects([&]{mkoperator::WriteParameter(image,14,1,1);});require(image==before,"misaligned parameter mutated image");
  rejects([&]{mkoperator::UpdateSettingsChecksum(image,1);});require(image==before,"misaligned checksum mutated image");
  std::vector<uint8_t> shortImage(16383);rejects([&]{mkoperator::UpdateSettingsChecksum(shortImage);});
  const auto mk2Even=read(root/"roms/mk2/uj12.l31"),mk2Odd=read(root/"roms/mk2/ug12.l31");
  require(mk2Even.size()==524288 && mk2Odd.size()==mk2Even.size(),"MK2 program lanes");
  std::vector<uint8_t> mk2Program(mk2Even.size()*2);for(size_t i=0;i<mk2Even.size();++i){mk2Program[i*2]=mk2Even[i];mk2Program[i*2+1]=mk2Odd[i];}
  const auto mk2Seed=read(mk2::FactorySeedPath(root));
  require(mkoperator::SettingsChecksumValid(mk2Seed),"MK2 native settings checksum");
  image=original;mkoperator::ResetMk2HighScores(image,mk2Program);
  require(image[0x190e]==0x94 && image[0x1910]==0x0f,"MK2 native unsigned ranking checksum");
  for(size_t i=0;i<image.size();++i){
   if(i%2 || i<0x1800 || i>0x1910)require(image[i]==original[i],"MK2 reset changed unrelated byte");
   else require(image[i]==mk2Seed[i],"MK2 ROM reset differs from native seed ranking");
  }
  for(unsigned preset=1;preset<=58;++preset){
   image=mk2Seed;mkoperator::ApplyMk2Coinage(image,mk2Program,preset,false);
   require(mkoperator::ReadParameter(image,1)==preset && mkoperator::SettingsChecksumValid(image),"MK2 coinage checksum/preset");
   require(!mkoperator::CoinageLabel(mkoperator::Game::Mk2,mk2Program,preset).empty(),"all MK2 ROM presets labelled");
  }
#ifdef MKOPERATOR_ORACLE
  VerifiedMk5Program verified;verified.bytes=program;verified.sha256=Sha256(program);
  std::vector<uint16_t> words(8192);for(size_t i=0;i<words.size();++i)words[i]=uint16_t(original[i*2])|(uint16_t(original[i*2+1])<<8);
  words[0x8a8]^=1;const auto factory=power_on(verified,words,0xfeff);
  require(factory.stop==TaskBodyStop::Budget && !factory.board.byte_writes.empty(),"native factory oracle executed");
  image=original;mkoperator::ResetMk1HighScores(image,program);
  for(size_t i=0xc00;i<=0xc88;++i)require(image[i*2]==(factory.board.cmos[i]&255),"MK1 reset differs from translated native factory routine");
  mkoperator::WriteParameter(image,14,5);mkoperator::ApplyMk1Coinage(image,program,3,false);
  for(size_t i=0;i<words.size();++i)words[i]=uint16_t(image[i*2])|(uint16_t(image[i*2+1])<<8);
  const auto reboot=power_on(verified,words,0xfeff);
  require(reboot.stop==TaskBodyStop::TaskEntry,"operator settings rejected by native reset validation");
  for(bool freeplay:{false,true}){
   image=original;mkoperator::ApplyMk1Coinage(image,program,3,freeplay);
   for(size_t i=0;i<words.size();++i)words[i]=uint16_t(image[i*2])|(uint16_t(image[i*2+1])<<8);
   const auto coinage=power_on(verified,words,0xfe7f);
   require(coinage.stop==TaskBodyStop::TaskEntry,"native CMOS-source coinage boot did not reach the first task");
   for(size_t i=0x800;i<=0x8a9;++i)require(coinage.board.cmos[i]==words[i],"native CMOS-source boot overwrote coinage settings");
  }
  std::cout<<"PASS: MK1 translated factory/reset oracle and native settings reboot validation\n";
#endif
  std::cout<<"PASS: MK1/MK2 CMOS parameters, 116 ROM pricing labels, ranking records/checksums and unrelated-byte preservation\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
