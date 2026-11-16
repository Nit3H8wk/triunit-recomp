#include "launcher_backend.hpp"
#include "mk5_program.hpp"
#include "mk2_program.hpp"
#include "../mk2/mk2_factory_seed.hpp"
#include <array>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>

namespace fs=std::filesystem;
using mklauncher::Backend;
void need(bool value,const char* why){if(!value)throw std::runtime_error(why);}
std::vector<uint8_t> read(const fs::path& path){std::ifstream file(path,std::ios::binary);need(bool(file),"fixture read");return {std::istreambuf_iterator<char>(file),{}};}
void write(const fs::path& path,const std::vector<uint8_t>& bytes){std::ofstream file(path,std::ios::binary);file.write(reinterpret_cast<const char*>(bytes.data()),std::streamsize(bytes.size()));need(bool(file),"fixture write");}
void parameter(std::vector<uint8_t>& image,unsigned index,uint32_t value){for(unsigned n=0;n<4;++n)image.at(0x1000+index*8+n*2)=uint8_t(value>>(24-n*8));}
void checksum(std::vector<uint8_t>& image){unsigned sum=0;for(unsigned n=0;n<168;++n)sum+=image.at(0x1000+n*2);image.at(0x1150)=uint8_t((~sum)>>8);image.at(0x1152)=uint8_t(~sum);}
bool same(const mklauncher::GameAdjustments& a,const mklauncher::GameAdjustments& b){return a.difficulty==b.difficulty&&a.coinage==b.coinage&&a.freePlay==b.freePlay&&a.customCoinage==b.customCoinage;}
std::vector<uint8_t> expectedSave(std::vector<uint8_t> image,const std::vector<uint8_t>& program,const mklauncher::GameAdjustments& before,const mklauncher::GameAdjustments& after,bool mk2=false){
 if(same(before,after))return image;
 if(before.coinage!=after.coinage||(!after.customCoinage&&before.customCoinage)){
  const size_t table=((mk2?0xffc14c50u:0xfffaeed0u)-0xff800000u)/8+size_t(after.coinage-1)*56;
  constexpr std::array<unsigned,11> indices{2,3,4,5,6,7,8,11,12,9,10};
  parameter(image,1,unsigned(after.coinage));
  for(unsigned n=0;n<indices.size();++n){const uint32_t word=program.at(table+n*2)|(uint32_t(program.at(table+n*2+1))<<8);parameter(image,indices[n],word&0x8000?word|0xffff0000u:word);}
  parameter(image,21,1);
 }
 parameter(image,18,after.freePlay?1:0);
 parameter(image,14,unsigned(after.difficulty));checksum(image);return image;
}
struct HeldFile{
 HANDLE handle;
 HeldFile(const fs::path& path,DWORD access,DWORD share,DWORD disposition):handle(CreateFileW(path.c_str(),access,share,nullptr,disposition,FILE_ATTRIBUTE_NORMAL,nullptr)){need(handle!=INVALID_HANDLE_VALUE,"fixture lock acquisition");}
 ~HeldFile(){CloseHandle(handle);}
};
void mk2Case(const fs::path& source,const fs::path& root,const fs::path& self,const std::wstring& mode){
 const auto even=read(source/L"roms/mk2/uj12.l31"),odd=read(source/L"roms/mk2/ug12.l31");
 const auto program=mk2::VerifyProgramLanes(even,odd);
 const auto seed=read(mk2::FactorySeedPath(source));need(seed.size()==16384,"MK2 seed exact size");
 const auto roms=root/L"roms/mk2";fs::create_directories(roms);
 fs::create_hard_link(source/L"roms/mk2/uj12.l31",roms/L"uj12.l31");fs::create_hard_link(source/L"roms/mk2/ug12.l31",roms/L"ug12.l31");
 const auto product=root/L"build/native/mk2-native-v1/product";fs::create_directories(product);
 const auto manifest=product/L"native-package.ini";
 const auto templateBytes=read(source/L"build/native/mk2-native-v1/product/native-package.ini");
 std::map<std::string,std::string> fields;std::istringstream lines(std::string(templateBytes.begin(),templateBytes.end()));std::string line;
 while(std::getline(lines,line)){
  if(!line.empty()&&line.back()=='\r')line.pop_back();
  const auto equals=line.find('=');if(equals!=std::string::npos)fields[line.substr(0,equals)]=line.substr(equals+1);
 }
 fields["executable"]=fs::absolute(self).u8string();fields["executable_sha256"]=Sha256(read(self));
 fields["rom_directory"]=(source/L"roms/mk2").u8string();fields["factory_seed"]=(mk2::FactorySeedPath(source)).u8string();
 fields["profile_directory"]="profiles/player";
 auto writeManifest=[&]{std::ofstream file(manifest,std::ios::binary);for(const auto& field:fields)file<<field.first<<'='<<field.second<<'\n';need(bool(file),"MK2 fixture manifest write");};
 writeManifest();
 auto image=seed;for(size_t n=1;n<image.size();n+=2)image[n]=uint8_t(n*109+(n>>2));
 const auto player=product/L"profiles/player";fs::create_directories(player);write(player/L"cmos.bin",image);write(player/L"factory-seed.bin",seed);
 const auto ini=root/L"build/native/mk2-native-v1/profile/launcher.ini";
 if(mode==L"mk2-independent"){fs::remove(roms/L"uj12.l31");fs::remove(roms/L"ug12.l31");}
 Backend backend(root);need(backend.selectGame(1)&&backend.adjustmentsAvailable(),"MK2 verified native fixture exposes real operator profile");
 need(backend.saveAll(backend.config,backend.adjustments),"MK2 initial preferences save");
 if(mode==L"mk2-core"||mode==L"mk2-independent"){
  auto wanted=backend.adjustments;wanted.difficulty=5;wanted.coinage=3;wanted.freePlay=true;wanted.customCoinage=false;
  auto preferences=backend.config;preferences.gameVolume=37;preferences.blood=false;preferences.violence=false;
  const auto expected=expectedSave(image,program.bytes,backend.adjustments,wanted,true);
  need(backend.saveAll(preferences,wanted)&&read(player/L"cmos.bin")==expected,"MK2 difficulty/pricing/Free Play changes only independently expected CMOS bytes");
  Backend reopened(root);need(reopened.selectGame(1)&&reopened.adjustmentsAvailable()&&same(reopened.adjustments,wanted),"MK2 native adjustments reload");
  need(reopened.config.gameVolume==37&&!reopened.config.blood&&!reopened.config.violence&&reopened.config.cmosCoinage,"MK2 volume/violence/CMOS pricing persist");
  need(reopened.selectGame(0)&&reopened.config.gameVolume==100&&reopened.config.blood&&reopened.config.violence,"MK1 defaults isolated from MK2 settings");
  need(reopened.selectGame(1)&&reopened.config.gameVolume==37&&same(reopened.adjustments,wanted),"MK2 preferences survive switching games");
  const auto before=read(player/L"cmos.bin"),beforeIni=read(ini);const auto lock=player/L".cmos.lock";
  {
   HeldFile held(lock,GENERIC_READ|GENERIC_WRITE,0,CREATE_NEW);
   auto changed=wanted;changed.difficulty=1;preferences.gameVolume=50;
   need(!backend.saveAll(preferences,changed)&&!backend.saveAll(preferences,wanted)&&!backend.resetHighScores(),"MK2 writer lock rejects combined/settings-only saves and ranking reset");
   need(read(player/L"cmos.bin")==before&&read(ini)==beforeIni&&backend.config.gameVolume==37,"MK2 writer contention preserves exact profile and preferences");
  }
  fs::remove(lock);std::cout<<"PASS MK2: native adjustments, Free Play, full CMOS preservation, preferences reload/isolation and writer-lock contention\n";
 }else if(mode==L"mk2-metadata-save"||mode==L"mk2-metadata-reset"){
  const auto other=product/L"profiles/other";fs::create_directories(other);write(other/L"cmos.bin",image);write(other/L"factory-seed.bin",seed);
  const auto before=read(player/L"cmos.bin"),otherBefore=read(other/L"cmos.bin"),beforeIni=read(ini);
  fields["profile_directory"]="profiles/other";writeManifest();
  if(mode==L"mk2-metadata-save"){
   auto wanted=backend.adjustments;wanted.difficulty=5;auto preferences=backend.config;preferences.gameVolume=37;
   need(!backend.saveAll(preferences,wanted),"changed MK2 package profile identity must reject cached adjustment save");
  }else need(!backend.resetHighScores(),"changed MK2 package profile identity must reject cached ranking reset");
  need(read(player/L"cmos.bin")==before&&read(other/L"cmos.bin")==otherBefore&&read(ini)==beforeIni,"neither cached nor newly advertised profile/INI may change after metadata replacement");
  std::cout<<"PASS MK2 changed profile identity rejects "<<(mode==L"mk2-metadata-save"?"save":"reset")<<" with both complete profiles/INI unchanged\n";
 }else if(mode==L"mk2-presence"){
  const auto beforeIni=read(ini);const auto hidden=product/L"native-package.hidden";const auto legacyIni=root/L"build/native/mk2-arcade-v1/profile/launcher.ini";
  fs::rename(manifest,hidden);backend.config.gameVolume=23;
  need(!backend.save()&&read(ini)==beforeIni&&!fs::exists(legacyIni),"removed MK2 native installation cannot redirect cached preferences into legacy profile");
  Backend legacy(root);need(legacy.selectGame(1)&&legacy.save(),"legacy preferences fixture while native manifest absent");const auto beforeLegacy=read(legacyIni);
  fs::rename(hidden,manifest);legacy.config.gameVolume=41;
  need(!legacy.save()&&read(legacyIni)==beforeLegacy&&read(ini)==beforeIni,"new native installation cannot redirect cached legacy preferences into native profile");
  std::cout<<"PASS MK2 native-presence changes reject preference writes in both directions\n";
 }else throw std::runtime_error("unknown MK2 backend case");
 need(read(mk2::FactorySeedPath(source))==seed&&read(source/L"roms/mk2/uj12.l31")==even&&read(source/L"roms/mk2/ug12.l31")==odd,"MK2 source seed and both ROM lanes unchanged");
}
int wmain(int argc,wchar_t** argv){try{
 need(argc==4,"source project, isolated test root and case required");
 const auto source=fs::absolute(argv[1]).lexically_normal(),root=fs::absolute(argv[2]).lexically_normal();
 const auto scratchBase=(source/L"build/native/quality").lexically_normal();const auto relative=root.lexically_relative(scratchBase);
 need(root!=scratchBase&&!relative.empty()&&!relative.is_absolute()&&*relative.begin()!=L"..","fixture must stay inside project quality scratch");
 const std::wstring mode=argv[3];
 if(mode.find(L"mk2-")==0){mk2Case(source,root,argv[0],mode);return 0;}
 const auto verified=LoadMk5Program(source/L"roms/mk1");
 const auto roms=root/L"roms/mk";fs::create_directories(roms);
 fs::create_hard_link(verified.even_source,roms/L"verified-even.bin");fs::create_hard_link(verified.odd_source,roms/L"verified-odd.bin");
 // CMOS seed written by the setup (tools/setup/mk1.make_seed) for this program image.
 const auto seedPath=source/L"generated/mk1"/fs::path(verified.sha256)/L"factory-default-control-input.bin";const auto seed=read(seedPath);need(seed.size()==16384,"seed exact size");
 auto nativeRanking=seed;unsigned rankingSum=0;const size_t rankingTable=(0xffdf14c0u-0xff800000u)/8;
 for(unsigned record=0;record<15;++record){
  const size_t from=rankingTable+record*12,to=0x1800+record*18;
  for(unsigned n=0;n<3;++n)nativeRanking[to+n*2]=uint8_t((unsigned(verified.bytes.at(from+n*2))|(unsigned(verified.bytes.at(from+n*2+1))<<8))-65);
  for(unsigned n=0;n<6;++n)nativeRanking[to+6+n*2]=verified.bytes.at(from+6+n);
 }
 for(size_t n=0x1800;n<=0x190c;n+=2)rankingSum+=nativeRanking[n];
 nativeRanking[0x190e]=uint8_t(rankingSum);nativeRanking[0x1910]=uint8_t(rankingSum>>8);
 auto image=seed;for(size_t n=1;n<image.size();n+=2)image[n]=uint8_t(n*137+(n>>3));
 bool varied=false;for(unsigned mask=1;mask<256&&!varied;++mask){
  unsigned sum=0;for(size_t n=0x1800;n<=0x190c;n+=2){image[n]=uint8_t(nativeRanking[n]^mask);sum+=image[n];}
  image[0x190e]=uint8_t(sum);image[0x1910]=uint8_t(sum>>8);varied=image[0x190e]!=nativeRanking[0x190e]&&image[0x1910]!=nativeRanking[0x1910];
 }
 need(varied,"valid nondefault ranking fixture");
 const auto profile=root/L"build/native/manual-temporary-8-20261025/profile";fs::create_directories(profile);
 const auto cmos=profile/L"cmos.bin",ini=profile/L"launcher.ini";write(cmos,image);
 Backend backend(root);need(backend.load()&&backend.adjustmentsAvailable(),"real verified ROM and CMOS expose operator controls");
 need(backend.saveAll(backend.config,backend.adjustments),"initial preferences save");
 if(mode==L"core"){
  unsigned selections=0;
  for(int difficulty=1;difficulty<=5;++difficulty){
   for(int preset=1;preset<=58;++preset){
    auto wanted=backend.adjustments;wanted.difficulty=difficulty;wanted.coinage=preset;wanted.freePlay=false;wanted.customCoinage=false;
    const auto expected=expectedSave(read(cmos),verified.bytes,backend.adjustments,wanted);
    auto preferences=backend.config;preferences.gameVolume=(difficulty*17+preset)%101;preferences.blood=preset%2;preferences.violence=preset%3;
    if(!backend.saveAll(preferences,wanted)){const auto error=GetLastError();std::wcerr<<backend.status()<<L'\n';throw std::runtime_error("save native difficulty="+std::to_string(difficulty)+" pricing="+std::to_string(preset)+" last_error="+std::to_string(error));}
    need(read(cmos)==expected,"save changes only independently expected CMOS bytes");
    need(same(backend.adjustments,wanted),"saved in-memory adjustments match request");
    need(!backend.coinageLabel(wanted).empty()&&backend.coinageLabel(wanted).find(L"PRESET ")!=0,"pricing label comes from verified ROM");++selections;
   }
   Backend reopened(root);need(reopened.load()&&reopened.adjustmentsAvailable(),"new backend reloads real saved profile");
   need(same(reopened.adjustments,backend.adjustments)&&reopened.config.gameVolume==backend.config.gameVolume&&reopened.config.blood==backend.config.blood&&reopened.config.violence==backend.config.violence&&reopened.config.cmosCoinage,"saved settings survive backend recreation");
  }
  for(const bool freePlay:{true,false}){
   auto wanted=backend.adjustments;wanted.freePlay=freePlay;
   const auto expected=expectedSave(read(cmos),verified.bytes,backend.adjustments,wanted);
   need(backend.saveAll(backend.config,wanted)&&read(cmos)==expected,"native Free Play toggles with exact checksum-preserving bytes");
   need((backend.coinageLabel(wanted)==L"FREE PLAY")==freePlay,"Free Play label matches persisted flag");
  }
  const auto machine=read(cmos);
  for(const bool remastered:{true,false}){
   auto preferences=backend.config;preferences.remastered=remastered;
   need(backend.saveAll(preferences,backend.adjustments)&&read(cmos)==machine,"Original/Remastered share machine CMOS adjustments");
   Backend reopened(root);need(reopened.load()&&reopened.config.remastered==remastered&&same(reopened.adjustments,backend.adjustments),"version and machine settings reload together");
  }
  const auto before=read(cmos);auto expected=before;for(size_t n=0x1800;n<=0x1910;n+=2)expected[n]=nativeRanking[n];
  const auto preferences=read(ini);const auto adjustments=backend.adjustments;
  const bool reset=backend.resetHighScores();const auto resetImage=read(cmos);
  if(!reset)std::wcerr<<backend.status()<<L'\n';
  unsigned shown=0;for(size_t n=0;n<expected.size();++n)if(expected[n]!=resetImage[n]&&shown++<8)std::cerr<<"ranking difference offset="<<n<<" expected="<<unsigned(expected[n])<<" actual="<<unsigned(resetImage[n])<<'\n';
  need(reset&&resetImage==expected,"ranking reset matches factory bytes and preserves entire remaining CMOS");
  unsigned changed=0;for(size_t n=0;n<before.size();++n)if(before[n]!=expected[n])++changed;
  need(changed==137&&same(backend.adjustments,adjustments)&&read(ini)==preferences,"only137 native ranking low bytes change; settings/high bytes/INI preserved");
  need(backend.resetHighScores()&&read(cmos)==expected,"ranking reset idempotent");
  std::cout<<"PASS core: "<<selections<<" difficulty/pricing selections, Free Play, reload, shared versions and137-byte native ranking reset\n";
 }else if(mode==L"session-lock"){
  const auto before=read(cmos),preferences=read(ini);const auto original=backend.adjustments;
  auto config=backend.config;config.gameVolume=37;
  HeldFile session(profile/L"session.lock",GENERIC_READ|GENERIC_WRITE,0,OPEN_ALWAYS);
  auto wanted=original;wanted.difficulty=original.difficulty==5?1:5;
  need(!backend.saveAll(config,wanted),"active MK1 session must reject combined settings save");
  need(read(cmos)==before&&read(ini)==preferences,"session lock preserves full CMOS and preferences");
  need(!backend.saveAll(config,original),"active MK1 session must reject settings-only save even unchanged CMOS");
  need(read(cmos)==before&&read(ini)==preferences&&backend.config.gameVolume==100,"settings-only lock rejection preserves preferences/config");
  need(!backend.resetHighScores()&&read(cmos)==before,"active session rejects ranking reset");
  std::cout<<"PASS session lock: combined/settings-only/reset cannot replace profile or preferences\n";
 }else if(mode==L"rollback"){
  const auto before=read(cmos),preferences=read(ini);const auto original=backend.adjustments;
  auto wanted=original;wanted.difficulty=original.difficulty==5?1:5;
  auto config=backend.config;config.gameVolume=37;config.blood=false;config.violence=false;
  {
   HeldFile blocked(ini,GENERIC_READ,FILE_SHARE_READ,OPEN_EXISTING);
   need(!backend.saveAll(config,wanted),"INI replacement failure must reject transaction");
   need(read(cmos)==before&&read(ini)==preferences,"failed INI save rolls back full16KiB CMOS and leaves preferences exact");
   need(same(backend.adjustments,original)&&backend.config.gameVolume==100&&backend.config.blood&&backend.config.violence,"failed save restores in-memory configuration");
  }
  const auto expected=expectedSave(before,verified.bytes,original,wanted);
  need(backend.saveAll(config,wanted)&&read(cmos)==expected,"retry after rollback uses restored snapshot hash");
  for(const auto& entry:fs::directory_iterator(profile))need(entry.path().filename().native().find(L".tmp-")==std::wstring::npos&&entry.path().filename().native().find(L".cmos-pending-")==std::wstring::npos,"failed transaction temporaries cleaned");
  std::cout<<"PASS rollback: locked INI failure restores exact image/config and retry succeeds\n";
 }else if(mode==L"stale"){
  Backend resetter(root);need(resetter.load(),"independent stale ranking client");
  const auto preferences=read(ini);auto external=read(cmos);parameter(external,14,backend.adjustments.difficulty==1?2:1);checksum(external);write(cmos,external);
  auto wanted=backend.adjustments;wanted.difficulty=5;auto config=backend.config;config.gameVolume=37;
  need(!backend.saveAll(config,wanted)&&read(cmos)==external&&read(ini)==preferences,"stale CMOS rejects adjustment save and preserves newer image/INI");
  need(!resetter.resetHighScores()&&read(cmos)==external,"stale snapshot cannot clear newer ranking");
  need(backend.refreshAdjustments()&&backend.adjustments.difficulty==int((external[0x1070]<<24)|(external[0x1072]<<16)|(external[0x1074]<<8)|external[0x1076]),"refresh reads externally changed native setting");
  std::cout<<"PASS stale: concurrent full image survives rejected save/reset and refresh recovers\n";
 }else throw std::runtime_error("unknown backend case");
 need(read(seedPath)==seed&&LoadMk5Program(source/L"roms/mk1").sha256==verified.sha256,"source ROMs and factory seed unchanged");return 0;
}catch(const std::exception& error){std::cerr<<"FAIL: "<<error.what()<<'\n';return 1;}}
