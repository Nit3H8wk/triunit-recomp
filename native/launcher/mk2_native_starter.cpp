#include "launcher_backend.hpp"
#include <shellapi.h>
#include <iostream>
#include <stdexcept>
#include <vector>
namespace {
struct CloseOwnedSession {
 mklauncher::Backend& backend;
 ~CloseOwnedSession(){
  while(backend.running()){
   try{backend.requestStop();backend.poll();}catch(...){}
   if(backend.running())Sleep(20);
  }
 }
};
}
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR,int){
 try{
  int count=0;auto* raw=CommandLineToArgvW(GetCommandLineW(),&count);if(!raw)throw std::runtime_error("starter command line");
  std::vector<std::wstring> args;for(int n=1;n<count;++n)args.emplace_back(raw[n]);LocalFree(raw);
  if((args.size()!=2&&args.size()!=4)||args[0]!=L"--native-experiment"||(args.size()==4&&args[2]!=L"--settings"))
   throw std::runtime_error("usage: mk2-native-starter --native-experiment MANIFEST [--settings INI]; experimental runtime, not qualified V1");
  const auto manifest=std::filesystem::absolute(args[1]);mklauncher::Backend backend(manifest.parent_path());CloseOwnedSession close{backend};
  if(!backend.launchNativeExperiment(manifest,args.size()==4?std::filesystem::path(args[3]):std::filesystem::path{})){
   std::wcerr<<backend.status()<<L'\n';return 1;
  }
  while(backend.running()){backend.poll();Sleep(20);}
  std::wcerr<<backend.status()<<L'\n';return int(backend.exitCode());
 }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
