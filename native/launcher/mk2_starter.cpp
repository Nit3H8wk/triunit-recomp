#include "launcher_backend.hpp"
#include "launcher_legal.hpp"
#include <vector>
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR,int){
 std::vector<wchar_t> path(32768);const auto n=GetModuleFileNameW(nullptr,path.data(),DWORD(path.size()));
 if(!n||n>=path.size())return 2;
 mklauncher::Backend backend(std::filesystem::path(path.data()).parent_path());
 if(!backend.selectGame(1)||!backend.launch()){
  MessageBoxW(nullptr,backend.status().c_str(),mklauncher::productName,MB_OK|MB_ICONERROR);return 1;
 }
 while(backend.running()){backend.poll();Sleep(20);}
 if(backend.exitCode())MessageBoxW(nullptr,L"The game closed with an error; see logs/mk2-v1/launcher-latest.log.",mklauncher::productName,MB_OK|MB_ICONERROR);
 return int(backend.exitCode());
}
