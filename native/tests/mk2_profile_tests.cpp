#include "native/mk2/mk2_profile.hpp"
#include "mk5_program.hpp"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>

std::vector<uint8_t> read(const std::filesystem::path& p) {
 std::ifstream f(p,std::ios::binary);if(!f)throw std::runtime_error("test input unavailable");
 return {std::istreambuf_iterator<char>(f),{}};
}
int wmain(int argc,wchar_t** argv){try {
 if(argc<3)throw std::runtime_error("operation and directory required");
 const std::wstring op=argv[1];const std::filesystem::path directory=argv[2];
 if(op==L"prepare") {if(argc!=4)throw std::runtime_error("seed required");std::cout<<mk2::PrepareCmosProfile(directory,std::filesystem::path(argv[3])).sha256;}
 else if(op==L"load") {const auto snapshot=mk2::LoadCmosProfile(directory);if(argc==4){std::ofstream f(std::filesystem::path(argv[3]),std::ios::binary);f.write(reinterpret_cast<const char*>(snapshot.image.data()),snapshot.image.size());if(!f)throw std::runtime_error("test output failed");}std::cout<<snapshot.sha256;}
 else if(op==L"save") {if(argc!=5)throw std::runtime_error("data and expected required");std::cout<<mk2::CompareAndSwapCmosProfile(directory,read(argv[3]),std::filesystem::path(argv[4]).string());}
 else if(op==L"unit") {
  if(argc!=4)throw std::runtime_error("seed required");
  const auto before=mk2::PrepareCmosProfile(directory,argv[3]);
  if(before.image.size()!=16384 || before.sha256!=Sha256(before.image) || mk2::LoadCmosProfile(directory).image!=before.image)
   throw std::runtime_error("prepare/load exact image failed");
  auto changed=before.image;for(size_t i=0;i<changed.size();++i)changed[i]=uint8_t((i*131u+(i>>3)*17u)^0xa5u);
  if(mk2::CompareAndSwapCmosProfile(directory,changed,before.sha256)!=Sha256(changed) || mk2::LoadCmosProfile(directory).image!=changed)
   throw std::runtime_error("opaque all-byte CAS failed");
  bool stale=false,size=false;
  try{mk2::CompareAndSwapCmosProfile(directory,before.image,before.sha256);}catch(const std::exception&){stale=true;}
  changed.pop_back();try{mk2::CompareAndSwapCmosProfile(directory,changed,Sha256(changed));}catch(const std::exception&){size=true;}
  if(!stale||!size||read(directory/"factory-seed.bin")!=before.image||mk2::PrepareCmosProfile(directory,argv[3]).image!=mk2::LoadCmosProfile(directory).image)
   throw std::runtime_error("CAS conflict, size or seed immutability failed");
  std::cout<<"unit exact_bytes stale size immutable_seed idempotent: PASS";
 }else if(op==L"hold") {
  const auto lock=directory/".cmos.lock";
  HANDLE file=CreateFileW(lock.c_str(),GENERIC_WRITE|DELETE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
  if(file==INVALID_HANDLE_VALUE)throw std::runtime_error("exclusive C++ test writer busy");
  std::cout<<"LOCKED"<<std::endl;std::cin.get();
  FILE_DISPOSITION_INFO disposition{TRUE};const bool removed=SetFileInformationByHandle(file,FileDispositionInfo,&disposition,sizeof(disposition))!=0;
  CloseHandle(file);if(!removed)throw std::runtime_error("test own lock cleanup failed");
 }else throw std::runtime_error("unknown operation");
 std::cout<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
