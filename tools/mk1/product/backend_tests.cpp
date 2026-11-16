// Consumer tests: missing persistence, permissive parsing, or enabled sequels must fail.
#include "launcher_backend.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>
namespace fs=std::filesystem;
void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int wmain(int argc,wchar_t** argv){
 try{
  check(argc==2||argc==3,"test root argument");fs::path root=argv[1];
  if(argc==3){mklauncher::Backend linked(root);check(!linked.load(),"linked profile load refused");linked.config.uiVolume=1;check(!linked.save(),"linked profile save refused");check(!linked.launch(),"linked/missing product launch refused");std::cout<<"PASS: profile junction refused for reads, writes and launch\n";return 0;}
  const auto ini=root/L"build/native/manual-temporary-8-20261025/profile/launcher.ini";
  mklauncher::Backend b(root);check(b.load(),"missing config must safely load defaults");
  check(!b.config.remastered&&b.config.fps==60&&b.config.vsync&&b.config.uiVolume==0,"boot defaults");
  fs::create_directories(ini.parent_path());
  {std::ofstream f(ini);f<<"[Launcher]\nFullscreen=0\n[MK1]\nScanlines=4\nScaleFX=1\nScaleFXAmount=37\nFilter=1\nBezel=0\nSync=2\nRemastered=1\n";}
  check(b.load()&&b.config.remastered&&!b.config.fullscreen,"legacy edition and launcher fullscreen retained");
  for(const auto& video:b.config.videos)
   check(video.scanlines==4&&video.scalefx&&video.scalefxAmount==37&&video.filter==1&&!video.bezel&&video.sync==2&&video.fullscreen,"legacy MK1 presentation cloned into both profiles");
  {std::ofstream f(ini);f<<"[Video.Remastered]\nScanlines=9\nFilter=3\nBrightness=120\nScaleMode=5\nCAS=40\nBilateral=70\nSMAA=1\nFullscreen=0\n[MK1]\nScanlines=4\nFilter=1\nSync=2\nColor=1\nScaleFX=1\nScaleFXAmount=37\nBezel=0\nHighRefresh=1\nRemastered=0\n[Video.Original]\nFilter=2\n";}
  check(b.load()&&!b.config.remastered&&b.config.video().filter==2,"edition selection uses Original despite Remastered section first");
  check(b.config.video(false).scanlines==4&&b.config.video(true).scanlines==9&&b.config.video(true).sync==2,"edition-specific keys overlay legacy values in either order");
  b.config.remastered=true;b.config.gameVolume=37;b.config.audioLatency=2;b.config.fps=30;b.config.uiVolume=72;
  b.config.reducedMotion=true;b.config.vsync=false;b.config.fullscreen=true;
  check(b.save(),"settings must persist atomically");
  {std::ifstream f(ini,std::ios::binary);const std::string saved(std::istreambuf_iterator<char>(f),{});
   check(saved.find("[Video.Original]")!=std::string::npos&&saved.find("[Video.Remastered]")!=std::string::npos,"both video profiles persist in the same preferences file");}
  mklauncher::Backend again(root);check(again.load(),"saved config readable");
  check(again.config.remastered&&again.config.audioLatency==2&&again.config.gameVolume==37&&again.config.fps==30&&again.config.uiVolume==0&&again.config.reducedMotion&&!again.config.vsync&&again.config.fullscreen,"shared preferences and launch default survive restart");
  const auto& remastered=again.config.video();const auto& original=again.config.video(false);
  check(remastered.scalefx&&remastered.scalefxAmount==37&&remastered.sync==2&&remastered.color==1&&remastered.brightness==120&&!remastered.bezel&&remastered.highRefresh&&remastered.scanlines==9&&remastered.filter==3&&remastered.scaleMode==5&&remastered.cas==40&&remastered.bilateral==70&&remastered.smaa&&!remastered.fullscreen,"Remastered video survives restart");
  check(original.scanlines==4&&original.filter==2&&original.brightness==100&&original.scaleMode==0&&original.cas==0&&original.bilateral==0&&!original.smaa&&original.fullscreen,"Original video remains independent");
  {std::ofstream f(ini);f<<"[Launcher]\nFPS=31\nVSync=9\nUIVolume=-1\nReducedMotion=perhaps\nFullscreen=1garbage\n[MK1]\nScanlines=10\nGameVolume=101\nFilter=4\n[Video.Remastered]\nScaleMode=6\nCAS=-1\nBilateral=101\nSMAA=2\nFullscreen=2\n";}
  check(!again.load(),"invalid values reported");
  check(again.config.fps==60&&again.config.vsync&&again.config.uiVolume==0&&!again.config.reducedMotion&&again.config.fullscreen&&original.scanlines==0&&again.config.gameVolume==100&&original.filter==0&&remastered.scaleMode==0&&remastered.cas==0&&remastered.bilateral==0&&!remastered.smaa&&remastered.fullscreen,"invalid ranges fall back safely");
  {std::ofstream f(ini,std::ios::binary);f<<"[Launcher]\nFPS=30\n";f.put('\0');f<<"garbage";}
  check(!again.load()&&again.config.fps==60,"binary corruption resets config");
  {std::ofstream f(ini);f<<"[Launcher]\nFPS=30\nFPS=60\n";}
  check(!again.load()&&again.config.fps==60,"duplicate keys are corruption");
  {std::ofstream f(ini);f<<std::string(9000,'x');}
  check(!again.load()&&again.config.fps==60,"oversized corruption bounded");
  again.config.audioLatency=0;again.config.video().scanlines=-2;again.config.video().filter=8;again.config.video(true).cas=101;again.config.fps=0;again.config.uiVolume=101;
  check(again.save(),"invalid in-memory settings save safe defaults");
  mklauncher::Backend normalized(root);check(normalized.load()&&normalized.config.audioLatency==1&&normalized.config.video().scanlines==0&&normalized.config.video().filter==0&&normalized.config.video(true).cas==0&&normalized.config.fps==60&&normalized.config.uiVolume==0,"save validates both profiles");
  normalized.config.video(false).brightness=90;normalized.config.video(true).brightness=120;check(normalized.save(),"custom profiles before reset");
  normalized.reset();mklauncher::Backend reset(root);check(reset.load()&&reset.config.uiVolume==0&&reset.config.video(false).brightness==100&&reset.config.video(true).brightness==100,"reset persists defaults for both profiles");
  HANDLE locked=CreateFileW(ini.c_str(),GENERIC_READ,0,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);check(locked!=INVALID_HANDLE_VALUE,"lock test fixture");
  reset.config.uiVolume=12;const bool savedLocked=reset.save();CloseHandle(locked);check(!savedLocked,"locked target save must fail without replacement");
  check(reset.load()&&reset.config.uiVolume==0,"failed atomic save preserves original settings");
  for(const auto& item:fs::directory_iterator(ini.parent_path()))check(item.path().extension()==L".ini","no pending temporary setting files retained");
  for(int i=-1;i<6;++i)check(!b.available(i),"uninstalled games cannot be available");
  check(!b.launch(),"missing installed game rejects launch");check(!b.running()&&!b.status().empty(),"failure remains visible and non-running");
  check(!b.launch(500001),"out of bounds test duration rejected");
  b.poll();b.requestStop();check(!b.running(),"idle stop safe");
  mklauncher::Backend changed(root/L"installation-change");check(changed.selectGame(1)&&changed.save(),"legacy profile selection fixture");
  const auto legacy=root/L"installation-change/build/native/mk2-arcade-v1/profile/launcher.ini";const auto legacyBefore=[&]{std::ifstream f(legacy,std::ios::binary);return std::string(std::istreambuf_iterator<char>(f),{});}();
  const auto newManifest=root/L"installation-change/build/native/mk2-native-v1/product/native-package.ini";fs::create_directories(newManifest.parent_path());{std::ofstream f(newManifest);f<<"invalid package";}
  changed.config.gameVolume=37;check(!changed.save(),"installation change while selected must reject save");
  check(!fs::exists(newManifest.parent_path().parent_path()/L"profile/launcher.ini"),"stale selection must not create preferences for another installation");
  {std::ifstream f(legacy,std::ios::binary);check(std::string(std::istreambuf_iterator<char>(f),{})==legacyBefore,"legacy profile preserved after installation change");}
  std::cout<<"PASS: defaults, persistence, ranges, binary corruption, duplicates, size limit, reset, disabled games, missing product, frame bounds, idle stop\n";return 0;
 }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
