// Real-process integration: UI must not hide forever on failed boot or orphan a closing game.
#include "launcher_backend.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>
void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
bool waitDone(mklauncher::Backend& b,DWORD timeout){const auto start=GetTickCount64();while(b.running()&&GetTickCount64()-start<timeout){b.poll();Sleep(10);}return !b.running();}
int wmain(int argc,wchar_t** argv){
 if(argc!=3)return 2;
 mklauncher::Backend b(argv[1]);
 try{
  const std::wstring mode=argv[2];check(b.available(0),"installed MK1 detected");for(int i=1;i<=3;++i)check(!b.available(i),"sequels unavailable");
  const bool video=mode==L"video-original"||mode==L"video-remastered";
  if(video)check(b.load()&&b.config.remastered==(mode==L"video-remastered"),"load the chosen video profile");
  if(mode==L"failure"){
   b.config.video().cas=25;
   check(!b.launch(1)&&!b.running()&&b.exitCode()==ERROR_INVALID_DATA,"advanced settings require the newer package");
   b.config.video().cas=0;
  }
  check(b.launch(mode==L"short"||video?60:600),"start asynchronous real session");check(b.running(),"launch immediately returns while session runs");
  check(!b.launch(1),"reject concurrent second launch");
  bool window=false;
  if(mode==L"race")b.requestStop();
  if(mode==L"short"||mode==L"close"||mode==L"timeout"||video){
   const auto start=GetTickCount64();while(b.running()&&!b.gameWindow()&&GetTickCount64()-start<25000){b.poll();Sleep(10);}
   window=b.gameWindow()!=nullptr;check(window,"owned native game HWND detected");
   if(mode==L"close")b.requestStop();
   if(mode==L"timeout"){std::ofstream(std::filesystem::path(argv[1])/L"timeout-ready.txt")<<"owned game window observed";Sleep(30000);}
  }
  check(waitDone(b,30000),"session exit polled without blocking UI");
  check(b.gameWindow()==nullptr,"game HWND cleared on return");
  check(b.exitCode()==(mode==L"failure"?19UL:0UL),"session exit code propagated");
  check(!b.status().empty(),"result visible in UI status");
  std::cout<<"PASS: "<<std::string(mode.begin(),mode.end())<<", exit="<<b.exitCode()<<", real_window_seen="<<window<<'\n';return 0;
 }catch(const std::exception& e){b.requestStop();waitDone(b,30000);std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
