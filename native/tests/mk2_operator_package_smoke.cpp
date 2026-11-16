#include "../launcher/launcher_main.cpp"
#include "mk2_profile.hpp"
#include "mk2_program.hpp"
#include "mk5_operator_settings.hpp"
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>

namespace fs=std::filesystem;
namespace {
void need(bool value,const char* why){if(!value)throw std::runtime_error(why);}
std::vector<uint8_t> read(const fs::path& path){std::ifstream file(path,std::ios::binary);need(bool(file),"smoke input unavailable");return {std::istreambuf_iterator<char>(file),{}};}
struct Session {
 mklauncher::Backend backend;
 explicit Session(const fs::path& root):backend(root){}
 bool stop(){
  backend.requestStop();const auto deadline=GetTickCount64()+20000;
  while(backend.running()&&GetTickCount64()<deadline){backend.poll();if(backend.running())Sleep(20);}
  return !backend.running();
 }
 ~Session(){if(backend.running())stop();}
};
}
int wmain(int argc,wchar_t** argv){try{
 need(argc>=3&&argc<=5,"project root and isolated smoke root required");
 bool remastered=false,savedCredits=false,phosphor=false;
 for(int n=3;n<argc;++n){const std::wstring flag=argv[n];if(flag==L"--remastered")remastered=true;else if(flag==L"--saved-credits")savedCredits=true;else if(flag==L"--phosphor")phosphor=true;else throw std::runtime_error("unknown smoke option");}
 need(!savedCredits||!phosphor,"choose one presentation smoke");
 const auto source=fs::absolute(argv[1]).lexically_normal(),root=fs::absolute(argv[2]).lexically_normal();
 const auto relative=root.lexically_relative((source/L"build/native/quality").lexically_normal());
 need(!relative.empty()&&!relative.is_absolute()&&*relative.begin()!=L"..","smoke must use project quality scratch");
 const auto published=source/L"build/native/mk2-native-v1/product",publishedManifest=published/L"native-package.ini";
 const auto originalManifest=read(publishedManifest);need(originalManifest.size()<=8192,"published manifest size bound");
 std::map<std::string,std::string> fields;std::istringstream lines(std::string(originalManifest.begin(),originalManifest.end()));std::string line;
 while(std::getline(lines,line)){
  if(!line.empty()&&line.back()=='\r')line.pop_back();
  const auto equals=line.find('=');if(equals!=std::string::npos)fields.emplace(line.substr(0,equals),line.substr(equals+1));
 }
 auto path=[&](const char* key){const auto value=fs::u8path(fields.at(key));return (value.is_absolute()?value:published/value).lexically_normal();};
 const auto executable=path("executable"),roms=path("rom_directory"),factorySeed=path("factory_seed");
 const auto userCmos=path("profile_directory")/L"cmos.bin";const bool userExisted=fs::exists(userCmos);
 const auto originalUser=userExisted?read(userCmos):std::vector<uint8_t>{};
 const auto originalSeed=read(factorySeed);need(originalSeed.size()==16384,"published seed exact size");
 need(Sha256(read(executable))==fields.at("executable_sha256"),"published executable hash must match published manifest");
 const auto even=read(roms/L"uj12.l31"),odd=read(roms/L"ug12.l31");mk2::VerifyProgramLanes(even,odd);
 const auto localRoms=root/L"roms/mk2";fs::create_directories(localRoms);
 fs::create_hard_link(roms/L"uj12.l31",localRoms/L"uj12.l31");fs::create_hard_link(roms/L"ug12.l31",localRoms/L"ug12.l31");
 const auto product=root/L"build/native/mk2-native-v1/product",profile=product/L"profiles/player";
 fs::create_directories(product);mk2::PrepareCmosProfile(profile,factorySeed);
 if(savedCredits){
  need(originalUser.size()==16384&&originalUser[540]>0,"saved-credit smoke requires actual persisted credits");
  mk2::CompareAndSwapCmosProfile(profile,originalUser,mk2::LoadCmosProfile(profile).sha256);
 }
 fields["executable"]=executable.u8string();fields["rom_directory"]=roms.u8string();fields["factory_seed"]=factorySeed.u8string();fields["profile_directory"]="profiles/player";
 {std::ofstream manifest(product/L"native-package.ini",std::ios::binary);for(const auto& field:fields)manifest<<field.first<<'='<<field.second<<'\n';need(bool(manifest),"isolated manifest write");}
 if(phosphor){
  App app(root);app.selectMachine(1);app.openSettings();
  need(app.settings,"native MK2 video Settings must open");
  app.video().scalefx=true;
  for(size_t n=0;n<mk5video::presets.size()&&app.video().scanlines!=mk5video::phosphor_index;++n)app.act(200);
  need(app.video().scanlines==mk5video::phosphor_index&&app.scaleFxActive(),"CRT / Fosforo is compatible with ScaleFX");
  app.act(videoPage);app.act(255);
  need(!app.scaleFxActive(),"ScaleFX remains editable in the CRT profile");
 }
 if(remastered){
  App app(root);app.selectMachine(1);
  need(app.chosen==1&&app.musicAvailable&&!app.backend.config.remastered,"first MK2 cabinet activation preserves original");
  app.selectMachine(1);need(app.backend.config.remastered&&app.mk2Remastered,"second MK2 activation selects remastered and updates badge");
  app.openSettings();need(app.settings&&app.draft.remastered,"Audio Settings loads selected MK2 version");
  app.draft.remastered=false;app.act(210);
  need(!app.backend.config.remastered&&!app.mk2Remastered,"Audio Settings saves Original and updates badge");
  app.settings=false;app.selectMachine(1);
  need(app.backend.config.remastered&&app.mk2Remastered,"cabinet can select Remastered after Settings save");
  App reopened(root);reopened.selectMachine(1);
  need(reopened.backend.config.remastered&&reopened.mk2Remastered,"reopened launcher restores selected MK2 version and badge");
 }
 Session session(root);auto& backend=session.backend;
 need(backend.selectGame(1)&&backend.adjustmentsAvailable(),"published native package must expose cloned operator profile");
 auto wanted=backend.adjustments;wanted.difficulty=5;wanted.coinage=3;wanted.freePlay=true;wanted.customCoinage=false;
 auto preferences=backend.config;preferences.gameVolume=0;preferences.blood=false;preferences.violence=false;preferences.cmosCoinage=true;
 preferences.remastered=remastered;preferences.audioLatency=2;
 auto& video=preferences.video();
 video.scanlines=phosphor?mk5video::phosphor_index:8;video.fullscreen=phosphor;video.scalefx=phosphor;
 if(phosphor){video.scaleMode=5;video.filter=2;video.cas=25;video.smaa=true;video.bilateral=25;}
 if(savedCredits){
  preferences.blood=true;preferences.violence=true;preferences.cmosCoinage=false;preferences.video().scanlines=4;
  video.scalefx=true;video.scalefxAmount=40;video.fullscreen=true;preferences.audioLatency=1;
  backend.config=preferences;need(backend.save(),"save isolated BVM1080 preferences");
 }else need(backend.saveAll(preferences,wanted),"save real operator settings before native launch");
 {mklauncher::Backend reopened(root);need(reopened.selectGame(1)&&reopened.config.remastered==remastered&&reopened.config.video().scanlines==preferences.video().scanlines&&reopened.config.video().scalefx==preferences.video().scalefx,"MK2 preferences survive launcher reopening");}
 const auto before=mk2::LoadCmosProfile(profile);
 const auto ini=root/L"build/native/mk2-native-v1/profile/launcher.ini";const auto preferencesBefore=read(ini);
 if(savedCredits)need(before.image==originalUser,"saved-credit smoke must start with exact user CMOS");
 else need(mkoperator::ReadParameter(before.image,14)==5&&mkoperator::ReadParameter(before.image,1)==3&&mkoperator::ReadParameter(before.image,18)==1&&mkoperator::SettingsChecksumValid(before.image),"native operator settings serialized before launch");
 if(!backend.launchNativeExperiment(product/L"native-package.ini")){std::wcerr<<backend.status()<<L'\n';throw std::runtime_error("published native session launch rejected");}
 const auto windowDeadline=GetTickCount64()+20000;
 while(backend.running()&&!backend.gameWindow()&&GetTickCount64()<windowDeadline){backend.poll();Sleep(20);}
 need(backend.running()&&backend.gameWindow()!=nullptr,"real owned native game window must appear");
 DWORD pid=0;GetWindowThreadProcessId(backend.gameWindow(),&pid);need(pid!=0,"native window PID");
 // Window creation precedes guest boot and the live input handoff.
 const auto progressDeadline=GetTickCount64()+8000;
 while(backend.running()&&GetTickCount64()<progressDeadline){backend.poll();Sleep(20);}
 need(backend.running(),"native game must remain running during bounded progress observation");
 need(session.stop()&&backend.exitCode()==0,"native session must stop gracefully and commit successfully");
 const auto saved=mk2::LoadCmosProfile(profile);
 for(size_t n=0;n<saved.image.size();++n)if(n%2||(n>=0x1000&&n<=0x1153))need(saved.image[n]==before.image[n],"native session preserves operator bank and every opaque high byte");
 if(savedCredits)need(saved.image[540]==before.image[540],"released-input startup must preserve saved credits");
 else need(mkoperator::ReadParameter(saved.image,14)==5&&mkoperator::ReadParameter(saved.image,1)==3&&mkoperator::ReadParameter(saved.image,18)==1&&mkoperator::SettingsChecksumValid(saved.image),"saved native session retains requested difficulty/pricing/Free Play");
 need(read(ini)==preferencesBefore&&read(profile/L"factory-seed.bin")==originalSeed,"native session preserves launcher preferences and cloned immutable seed");
 need(read(factorySeed)==originalSeed&&read(publishedManifest)==originalManifest&&fs::exists(userCmos)==userExisted&&(!userExisted||read(userCmos)==originalUser),"published seed/manifest and actual user CMOS must remain unchanged");
 need(read(roms/L"uj12.l31")==even&&read(roms/L"ug12.l31")==odd&&Sha256(read(executable))==fields.at("executable_sha256"),"published executable and program ROMs remain unchanged");
 std::cout<<"{\"scope\":\"mk2-operator-package-smoke\",\"owned_window\":true,\"owned_window_pid\":"<<pid
          <<",\"exit_code\":0,\"loaded_cmos_sha256\":\""<<before.sha256<<"\",\"saved_cmos_sha256\":\""<<saved.sha256
          <<"\",\"operator_bank_preserved\":true,\"opaque_high_bytes_preserved\":true,\"published_inputs_preserved\":true,\"volume_percent_configured\":0,\"scanlines_configured\":"<<video.scanlines<<",\"fullscreen_configured\":"<<(video.fullscreen?"true":"false")<<"}\n";
 return 0;
}catch(const std::exception& error){std::cerr<<"FAIL: "<<error.what()<<'\n';return 1;}}
