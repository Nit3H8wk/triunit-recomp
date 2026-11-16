#include "mk2_profile.hpp"
#include "mk5_program.hpp"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace fs=std::filesystem;
namespace {
fs::path target,lockPath;
mk2::CmosLock lockMode=mk2::CmosLock::Mk1Session;
std::vector<uint8_t> beforeRename;
std::vector<DWORD> waits;
DWORD injectedError=ERROR_SUCCESS;
unsigned failuresLeft=0,attempts=0,targetChecks=0;
HANDLE pendingHandle=INVALID_HANDLE_VALUE;
bool permanent=false,reparseAfterFailure=false,missingAfterFailure=false;
void need(bool value,const char* why){if(!value)throw std::runtime_error(why);}
std::vector<uint8_t> bytes(const fs::path& path){std::ifstream input(path,std::ios::binary);need(bool(input),"fixture read");return {std::istreambuf_iterator<char>(input),{}};}
void write(const fs::path& path,const std::vector<uint8_t>& image){std::ofstream output(path,std::ios::binary);output.write(reinterpret_cast<const char*>(image.data()),std::streamsize(image.size()));need(bool(output),"fixture write");}
void needLockHeld(){
 const auto competing=CreateFileW(lockPath.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,
     lockMode==mk2::CmosLock::Mk1Session?OPEN_ALWAYS:CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
 if(competing!=INVALID_HANDLE_VALUE)CloseHandle(competing);
 need(competing==INVALID_HANDLE_VALUE,"rename and retries must retain the same game writer lock");
}
void fault(DWORD error,unsigned failures,bool forever=false){
 injectedError=error;failuresLeft=failures;permanent=forever;attempts=targetChecks=0;
 pendingHandle=INVALID_HANDLE_VALUE;waits.clear();reparseAfterFailure=missingAfterFailure=false;beforeRename=bytes(target);
}
DWORD readAttributes(LPCWSTR path){
 if(!target.empty()&&fs::path(path).lexically_normal()==target.lexically_normal()){
  ++targetChecks;
  if(attempts&&reparseAfterFailure)return FILE_ATTRIBUTE_REPARSE_POINT;
  if(attempts&&missingAfterFailure){SetLastError(ERROR_FILE_NOT_FOUND);return INVALID_FILE_ATTRIBUTES;}
 }
 return GetFileAttributesW(path);
}
BOOL setInformation(HANDLE file,FILE_INFO_BY_HANDLE_CLASS kind,LPVOID information,DWORD size){
 if(kind==FileRenameInfo){
  ++attempts;needLockHeld();
  if(pendingHandle==INVALID_HANDLE_VALUE)pendingHandle=file;
  need(pendingHandle==file,"retry must reuse the original owned pending handle");
  if(permanent||failuresLeft){
   if(failuresLeft)--failuresLeft;
   need(bytes(target)==beforeRename,"denied rename must leave every original target byte unchanged");
   SetLastError(injectedError);return FALSE;
  }
 }
 return SetFileInformationByHandle(file,kind,information,size);
}
[[maybe_unused]] void retrySleep(DWORD milliseconds){needLockHeld();waits.push_back(milliseconds);Sleep(milliseconds);}
template<class F>void rejects(F action,const char* why){bool failed=false;try{action();}catch(const std::exception&){failed=true;}need(failed,why);}
void clean(){
 for(const auto& entry:fs::directory_iterator(target.parent_path()))need(entry.path().filename().native().find(L".cmos-pending-")!=0,"owned pending image must be removed after success/failure");
 if(lockMode==mk2::CmosLock::Mk2Profile)need(!fs::exists(lockPath),"owned MK2 writer lock must be removed after success/failure");
}
}
#define GetFileAttributesW readAttributes
#define SetFileInformationByHandle setInformation
#define Sleep retrySleep
#include "../mk2/mk2_profile.cpp"

int wmain(int argc,wchar_t** argv){try{
 need(argc==2,"isolated fixture root required");const auto root=fs::absolute(argv[1]);unsigned cases=0,sequence=0;
 std::vector<uint8_t> original(16384);for(size_t n=0;n<original.size();++n)original[n]=uint8_t(n*131+(n>>2));
 auto changed=original;changed[0x1076]^=0x37;changed[0x1171]^=0x81;const auto oldSha=Sha256(original),newSha=Sha256(changed);
 for(const auto mode:{mk2::CmosLock::Mk1Session,mk2::CmosLock::Mk2Profile}){
  lockMode=mode;
  auto fixture=[&]{const auto directory=root/std::to_wstring(++sequence);fs::create_directories(directory);target=directory/L"cmos.bin";lockPath=directory/(mode==mk2::CmosLock::Mk1Session?L"session.lock":L".cmos.lock");write(target,original);};
  for(const DWORD error:{DWORD(ERROR_ACCESS_DENIED),DWORD(ERROR_SHARING_VIOLATION),DWORD(ERROR_LOCK_VIOLATION)}){
   fixture();fault(error,2);unsigned commits=0;
   const auto sha=mk2::CompareAndSwapCmosFile(target,changed,oldSha,mode,[&]{needLockHeld();need(bytes(target)==changed,"commit sees complete retried image");++commits;});
   need(sha==newSha&&bytes(target)==changed&&commits==1,"two transient failures recover without repeating commit or changing unrelated image bytes");
   need(attempts==3&&targetChecks==3&&waits==std::vector<DWORD>({10,10}),"transient retry count, target revalidation and10ms waits");clean();++cases;
   fixture();fault(error,0,true);commits=0;
   rejects([&]{mk2::CompareAndSwapCmosFile(target,changed,oldSha,mode,[&]{++commits;});},"persistent rename denial must reject");
   need(attempts==10&&targetChecks==10&&waits==std::vector<DWORD>(9,10),"persistent denial is bounded to10 attempts and90ms requested waiting");
   need(bytes(target)==original&&commits==0,"persistent denial preserves full original and never commits");clean();
   fault(ERROR_SUCCESS,0);need(mk2::CompareAndSwapCmosFile(target,changed,oldSha,mode)==newSha,"writer/pending handles released after exhausted retries");clean();++cases;
  }
  fixture();fault(ERROR_INVALID_PARAMETER,0,true);
  rejects([&]{mk2::CompareAndSwapCmosFile(target,changed,oldSha,mode);},"unrelated error must reject immediately");
  need(attempts==1&&targetChecks==1&&waits.empty()&&bytes(target)==original,"unrelated errors cannot be blindly retried or mutate image");clean();++cases;
  for(const bool reparse:{true,false}){
   fixture();fault(ERROR_ACCESS_DENIED,2);reparseAfterFailure=reparse;missingAfterFailure=!reparse;
   rejects([&]{mk2::CompareAndSwapCmosFile(target,changed,oldSha,mode);},"changed target identity/existence must reject retry");
   need(attempts==1&&targetChecks==2&&waits==std::vector<DWORD>({10})&&bytes(target)==original,"every retry must revalidate target before attempting rename");
   reparseAfterFailure=missingAfterFailure=false;clean();++cases;
  }
  fixture();fault(ERROR_SUCCESS,0);unsigned commits=0;
  rejects([&]{mk2::CompareAndSwapCmosFile(target,changed,oldSha,mode,[&]{
   needLockHeld();++commits;fault(ERROR_SHARING_VIOLATION,2);throw std::runtime_error("simulated preferences commit failure");
  });},"failed callback must report failure after rollback");
  need(attempts==3&&targetChecks==3&&waits==std::vector<DWORD>({10,10})&&commits==1&&bytes(target)==original,"rollback retries under same lock and restores all original bytes");clean();++cases;
 }
 std::cout<<"PASS "<<cases<<" raw CMOS rename boundary cases: transient recovery, bounded permanent rejection, target revalidation and locked rollback\n";return 0;
}catch(const std::exception& error){std::cerr<<"FAIL: "<<error.what()<<'\n';return 1;}}
