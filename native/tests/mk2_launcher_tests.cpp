#include "launcher_backend.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>
namespace fs=std::filesystem;
void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
std::string read(const fs::path& p){std::ifstream f(p,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};}
int wmain(int argc,wchar_t** argv){
 if(argc!=2&&argc!=3)return 2;
 try{
  const fs::path root=argv[1];mklauncher::Backend b(root);
  if(argc==3){
   check(b.selectGame(1)&&b.available(1),"installed MK2 core/ROM aliases detected");
   check(b.launch(180),"launch actual MK2 session");check(!b.selectGame(0)&&!b.launch(1),"running session cannot switch or launch twice");
   const auto start=GetTickCount64();bool window=false;
   while(b.running()&&GetTickCount64()-start<20000){b.poll();if(b.gameWindow()){window=true;if(std::wstring(argv[2])==L"close")b.requestStop();}Sleep(10);}
   check(!b.running()&&window&&b.exitCode()==0,"owned MK2 window and clean exit observed");
   std::cout<<"PASS: actual MK2 available, audio/video window, lifecycle exit0\n";return 0;
  }
  check(b.load(),"default MK1 config");b.config.video().brightness=90;check(b.save(),"save MK1 fixture");
  const auto mk1=root/L"build/native/manual-temporary-8-20261025/profile/launcher.ini";const auto before=read(mk1);
  check(b.selectGame(1),"select MK2");check(b.config.video().brightness==100,"MK2 independent defaults");
  b.config.video().brightness=110;b.config.video().scanlines=7;b.config.video().highRefresh=true;b.config.video().sync=1;b.config.remastered=true;check(b.save(),"save MK2");
  check(read(mk1)==before,"MK1 profile untouched by MK2");
  check(b.selectGame(0)&&b.config.video().brightness==90,"restore MK1 preference");
  check(b.selectGame(1)&&b.config.video().brightness==110&&!b.config.remastered,"restore MK2; original audio only");
  check(b.config.video().scanlines==0&&!b.config.video().highRefresh&&b.config.video().sync==2,"unsupported MK1 presentation options cannot pretend to apply to MK2");
  check(!b.selectGame(3)&&b.config.video().brightness==110,"unsupported game cannot change current profile");
  check(!b.available(1)&&!b.launch()&&!b.running(),"missing MK2 core/package fails without orphan");
  check(fs::exists(root/L"build/native/mk2-arcade-v1/profile/launcher.ini"),"MK2 profile in its own directory");
  std::cout<<"PASS: isolated MK1/MK2 profiles, original mode and missing-core rejection\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
