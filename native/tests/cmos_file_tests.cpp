#include "mk2_profile.hpp"
#include "mk5_program.hpp"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace fs=std::filesystem;
void verify(bool value,const char* why){if(!value)throw std::runtime_error(why);}
template<class F> void rejects(F operation,const char* why){bool failed=false;try{operation();}catch(const std::exception&){failed=true;}verify(failed,why);}
void write(const fs::path& p,const std::vector<uint8_t>& bytes){std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(bytes.data()),std::streamsize(bytes.size()));verify(bool(f),"fixture write");}
int wmain(int argc,wchar_t** argv){try{
 if(argc==4&&std::wstring(argv[1])==L"reject-link"){
  const auto linked=fs::path(argv[2]),ordinary=fs::path(argv[3]);const auto before=mk2::LoadCmosFile(ordinary);
  rejects([&]{mk2::LoadCmosFile(linked);},"raw load must reject junction traversal");
  auto changed=before.image;changed[0]^=0xff;
  for(const auto mode:{mk2::CmosLock::Mk1Session,mk2::CmosLock::Mk2Profile})
   rejects([&]{mk2::CompareAndSwapCmosFile(linked,changed,before.sha256,mode);},"raw CAS must reject junction traversal");
  verify(mk2::LoadCmosFile(ordinary).image==before.image,"junction target bytes unchanged");
  std::cout<<"PASS: junction read/write rejection with unchanged target\n";return 0;
 }
 if(argc!=2)throw std::runtime_error("isolated root required");
 const auto root=fs::absolute(argv[1]);fs::create_directories(root);
 for(const auto mode:{mk2::CmosLock::Mk1Session,mk2::CmosLock::Mk2Profile}){
  const auto directory=root/(mode==mk2::CmosLock::Mk1Session?L"mk1":L"mk2");fs::create_directory(directory);
  const auto target=directory/L"cmos.bin";
  std::vector<uint8_t> initial(16384);for(size_t i=0;i<initial.size();++i)initial[i]=uint8_t(i*137u+(i>>1));
  write(target,initial);const auto before=mk2::LoadCmosFile(target);
  verify(before.image==initial&&before.sha256==Sha256(initial),"raw load must preserve all 16384 bytes without seed authentication");
  auto changed=initial;for(auto& byte:changed)byte^=0xa5;
  const auto changed_sha=mk2::CompareAndSwapCmosFile(target,changed,before.sha256,mode);
  verify(changed_sha==Sha256(changed)&&mk2::LoadCmosFile(target).image==changed,"raw CAS full byte roundtrip including high bytes");
  rejects([&]{mk2::CompareAndSwapCmosFile(target,initial,before.sha256,mode);},"stale snapshot must reject");
  rejects([&]{mk2::CompareAndSwapCmosFile(target,std::vector<uint8_t>(16383),changed_sha,mode);},"short payload must reject");
  rejects([&]{mk2::CompareAndSwapCmosFile(target,std::vector<uint8_t>(16385),changed_sha,mode);},"long payload must reject");
  verify(mk2::LoadCmosFile(target).image==changed,"rejected writes must preserve exact existing bytes");
  verify(mk2::CompareAndSwapCmosFile(target,initial,changed_sha,mode)==before.sha256&&mk2::LoadCmosFile(target).image==initial,"transaction rollback uses current hash and restores all original bytes");
  unsigned commits=0;
  auto locked_commit=[&]{
   ++commits;const auto path=directory/(mode==mk2::CmosLock::Mk1Session?L"session.lock":L".cmos.lock");
   const auto competing=CreateFileW(path.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,
       mode==mk2::CmosLock::Mk1Session?OPEN_ALWAYS:CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
   if(competing!=INVALID_HANDLE_VALUE)CloseHandle(competing);
   verify(competing==INVALID_HANDLE_VALUE,"commit callback must run under the same session/writer lock");
  };
  mk2::CompareAndSwapCmosFile(target,initial,before.sha256,mode,locked_commit);
  verify(commits==1&&mk2::LoadCmosFile(target).image==initial,"identical image still commits under writer lock");
  rejects([&]{mk2::CompareAndSwapCmosFile(target,changed,before.sha256,mode,[&]{
   locked_commit();verify(mk2::LoadCmosFile(target).image==changed,"callback observes tentative complete image");
   throw std::runtime_error("simulated preferences commit failure");
  });},"failed commit must report failure");
  verify(commits==2&&mk2::LoadCmosFile(target).image==initial,"failed callback restores every prior image byte under writer lock");
  rejects([&]{mk2::CompareAndSwapCmosFile(target,changed,changed_sha,mode,locked_commit);},"stale callback transaction rejected");
  verify(commits==2,"stale transaction cannot call commit");
  const auto lock=directory/(mode==mk2::CmosLock::Mk1Session?L"session.lock":L".cmos.lock");
  const HANDLE held=CreateFileW(lock.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
  verify(held!=INVALID_HANDLE_VALUE,"acquire simulated session/writer lock");
  rejects([&]{mk2::CompareAndSwapCmosFile(target,changed,before.sha256,mode);},"active session/writer lock must reject CAS");
  rejects([&]{mk2::CompareAndSwapCmosFile(target,initial,before.sha256,mode,locked_commit);},"even identical image cannot commit under foreign session lock");
  verify(commits==2,"locked transaction cannot call commit");
  verify(mk2::LoadCmosFile(target).image==initial,"locked writes must preserve image");
  CloseHandle(held);
  if(mode==mk2::CmosLock::Mk2Profile){
   write(lock,{0x7a,0x81});
   rejects([&]{mk2::CompareAndSwapCmosFile(target,changed,before.sha256,mode);},"foreign stale MK2 lock must remain authoritative");
   verify(fs::file_size(lock)==2,"foreign lock must not be deleted");fs::remove(lock);
  }
  verify(mk2::CompareAndSwapCmosFile(target,changed,before.sha256,mode)==changed_sha,"retry after lock release");
  verify(fs::exists(lock)==(mode==mk2::CmosLock::Mk1Session),"MK1 persistent session lock or MK2 owned lock lifecycle");
  const auto seed=directory/L"factory-seed.bin";write(seed,initial);
  rejects([&]{mk2::CompareAndSwapCmosFile(seed,changed,before.sha256,mode);},"raw CAS must not replace a factory seed");
  verify(mk2::LoadCmosFile(seed).image==initial,"factory seed unchanged");
  fs::remove(target);
  rejects([&]{mk2::CompareAndSwapCmosFile(target,changed,changed_sha,mode);},"CAS cannot create missing target");
  verify(!fs::exists(target),"missing target remains missing");
  for(const size_t size:{size_t(16383),size_t(16385)}){
   write(target,std::vector<uint8_t>(size,0x81));
   rejects([&]{mk2::LoadCmosFile(target);},"invalid existing size rejected on read");
   rejects([&]{mk2::CompareAndSwapCmosFile(target,initial,before.sha256,mode);},"invalid existing size rejected on CAS");
   verify(fs::file_size(target)==size,"invalid existing image remains unchanged");
  }
  for(const auto& entry:fs::directory_iterator(directory))verify(entry.path().filename().native().find(L".cmos-pending-")!=0,"owned temporaries removed");
 }
 std::cout<<"PASS: raw CMOS exact bytes, CAS rollback/conflicts, MK1/MK2 writer locks, seed/size/missing protection and temporary cleanup\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
