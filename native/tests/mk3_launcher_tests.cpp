#include "launcher_backend.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
namespace fs=std::filesystem;
void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
std::string read(const fs::path& p){std::ifstream f(p,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};}
int wmain(int argc,wchar_t** argv){
 if(argc!=2&&!(argc==3&&std::wstring(argv[2])==L"native"))return 2;
 try{
  const fs::path root=argv[1];mklauncher::Backend b(root);
  if(argc==3){
   // MK3 native package: both editions launch, own window, clean exit, own CMOS profile and log.
   // Editions are picked for this session only (setMk3Engine): the saved card choice and the MK3 profile are not written.
   check(b.selectGame(2),"select MK3");const int saved=b.mk3Engine();const auto dips=b.config;
   check(b.available(2),"installed MK3 native package verified");
   for(int engine:{1,2}){
    check(b.setMk3Engine(engine)&&b.mk3Engine()==engine,"select the native edition");
    // The cabinet's DSW reaches mk3.exe: the default switches in the Original, Blood off in the Remastered (not saved).
    b.config.blood=engine==1;b.config.violence=true;const auto dsw=mklauncher::mk3DswWord(b.config);
    check(!b.launch(1),"MK3 rejects a frame-limited diagnostic launch");
    check(b.launch(),"launch the MK3 native edition");check(!b.setMk3Engine(3-engine)&&!b.selectGame(1),"running MK3 cannot switch");
    const auto start=GetTickCount64();bool window=false;ULONGLONG seen=0;
    while(b.running()&&GetTickCount64()-start<60000){b.poll();if(b.gameWindow()&&!window){window=true;seen=GetTickCount64();}if(window&&GetTickCount64()-seen>4000)b.requestStop();Sleep(10);}
    check(!b.running()&&window&&b.exitCode()==0,"owned MK3 window and clean exit observed");
    const auto cmos=root/L"build/native/mk3-native/product/profiles/player/cmos.bin";
    check(fs::exists(cmos)&&fs::file_size(cmos)==49152,"MK3 CMOS saved in its own profile");
    check(fs::exists(root/L"logs/mk3-native/launcher-latest.log"),"MK3 log in its own directory");
    const auto log=read(root/L"logs/mk3-native/launcher-latest.log");
    check(log.find("\"dsw\":"+std::to_string(dsw)+",")!=std::string::npos,"mk3.exe reports the launcher's DSW");
    check(log.find("\"dsw\":"+std::to_string(dsw^0x4000)+",")==std::string::npos,"mk3.exe does not report the other Blood switch");
   }
   b.config=dips;
   check(!b.setMk3Engine(0)&&!b.setMk3Engine(3)&&b.setMk3Engine(saved),"only the two native editions exist");
   std::cout<<"PASS: MK3 native Original and Remastered, lifecycle exit0, own CMOS/log, DSW reaches mk3.exe\n";return 0;
  }
  check(b.load(),"default MK1 config");b.config.video().brightness=90;check(b.save(),"save MK1 fixture");
  check(b.selectGame(1),"select MK2");b.config.video().brightness=110;check(b.save(),"save MK2 fixture");
  const auto mk1=root/L"build/native/manual-temporary-8-20261025/profile/launcher.ini",mk2=root/L"build/native/mk2-arcade-v1/profile/launcher.ini";
  const auto before1=read(mk1),before2=read(mk2);
  check(b.selectGame(2),"select MK3");check(b.config.video().brightness==100,"MK3 independent defaults");
  // Edition defaults: the Original without effect, the Remastered on BVM / 1080p (preset 4) and ScaleFX 100.
  const auto& o=b.config.video(false);const auto& r=b.config.video(true);
  check(o.scanlines==0&&!o.scalefx&&o.filter==0&&!o.cas&&!o.bilateral&&!o.smaa&&o.color==0&&o.sync==1&&o.bezel&&o.fullscreen,"MK3 Original without effect");
  check(r.scanlines==4&&r.scalefx&&r.scalefxAmount==100&&r.filter==0&&r.sync==1,"MK3 Remastered BVM and ScaleFX 100");
  b.config.video().brightness=120;b.config.video().scanlines=7;b.config.video().highRefresh=true;b.config.video().sync=1;b.config.video().filter=3;
  b.config.video(true).cas=50;b.config.gameVolume=40;b.config.audioLatency=2;b.config.remastered=true;check(b.save(),"save MK3");
  check(read(mk1)==before1&&read(mk2)==before2,"MK1/MK2 profiles untouched by MK3");
  check(read(root/L"build/native/mk3-native/profile/launcher.ini").find("[MK3]")!=std::string::npos,"MK3 section in its own profile");
  check(b.selectGame(1)&&b.config.video().brightness==110,"restore MK2 preference");
  check(b.selectGame(2)&&b.config.video().brightness==120&&!b.config.remastered,"restore MK3; no remastered music (D7)");
  check(b.config.video().scanlines==7&&b.config.video().highRefresh&&b.config.video().sync==1&&b.config.video().filter==3&&b.config.video(true).cas==50&&
        b.config.gameVolume==40&&b.config.audioLatency==2,"MK3 keeps the native MK2 option set, volume and audio queue");
  check(!b.remasteredAvailable(),"no MK3 remastered music is claimed");
  // Blood/Violence for MK3: the cabinet's DIP switches, offered without a CMOS profile and passed to mk3.exe as its DSW
  // (INPUT_PORTS(mk3): default FD7Dh, Blood 4000h, Violence 8000h). Negative: the default switches pass no --dsw-word.
  const auto dswArgument=[](const mklauncher::Config& c){
   const auto args=mklauncher::mk3Arguments(L"x:/mk3.exe",L"x:/roms",L"x:/seed.bin",L"x:/graphics.txt",L"x:/profile",true,c);
   check(std::count(args.begin(),args.end(),std::wstring(L"--dsw-word"))<=1,"one MK3 DSW argument at most");
   const auto at=std::find(args.begin(),args.end(),std::wstring(L"--dsw-word"));
   return at==args.end()?std::wstring():at+1==args.end()?std::wstring(L"missing"):*(at+1);
  };
  check(b.dipSwitchesAvailable(),"MK3 offers its blood and violence switches without a CMOS profile");
  check(b.config.blood&&b.config.violence&&mklauncher::mk3DswWord(b.config)==0xfd7d&&dswArgument(b.config).empty(),"MK3 default DSW passes no --dsw-word");
  b.config.blood=false;check(b.save(),"save MK3 with Blood off");
  check(read(root/L"build/native/mk3-native/profile/launcher.ini").find("Blood=0\r\n")!=std::string::npos,"MK3 Blood switch saved in its own profile");
  check(read(mk1)==before1&&read(mk2)==before2,"MK1/MK2 profiles untouched by the MK3 switch");
  check(b.selectGame(1)&&b.config.blood&&!b.dipSwitchesAvailable(),"MK2 keeps its Blood and offers no switch without its CMOS profile");
  check(b.selectGame(2)&&!b.config.blood&&b.config.violence,"MK3 Blood off restored");
  check(mklauncher::mk3DswWord(b.config)==0xbd7d&&dswArgument(b.config)==L"48509","MK3 Blood off reaches the command line as BD7Dh");
  b.config.violence=false;check(dswArgument(b.config)==L"15741","MK3 Blood and Violence off: 3D7Dh");
  b.config.blood=true;check(mklauncher::mk3DswWord(b.config)==0x7d7d&&dswArgument(b.config)==L"32125","MK3 Violence off alone: 7D7Dh");
  b.config.violence=true;check(dswArgument(b.config).empty(),"MK3 switches back on: no --dsw-word");
  check(!b.selectGame(3)&&b.config.video().brightness==120,"UMK3 is not integrated and cannot change the profile");
  b.reset();check(b.config.video(true).scanlines==4&&b.config.video(true).scalefx&&b.config.video(false).scanlines==0,"reset restores the MK3 edition defaults");
  check(!b.available(2)&&!b.launch()&&!b.running(),"missing MK3 package fails without orphan");
  std::cout<<"PASS: isolated MK1/MK2/MK3 profiles, MK3 edition defaults and native option set, MK3 blood/violence DSW, missing-package rejection\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
