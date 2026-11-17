// Setup queue of the launcher against a stub tools/setup/setup.py (no ROM): Python lookup through --requirements,
// per-game progress, verify report, failure, Cancel of the whole process tree and the saved ROM folders.
#include "launcher_backend.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>
namespace fs=std::filesystem;
void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
const char* stub=R"(import json,os,sys,time
a=sys.argv[1:]
if '--requirements' in a:print(json.dumps(dict(windows_64bit=True,python='3.test',ok=False,compiler=dict(version=None,validated='16.1.0'))));sys.exit(1)
game=a[a.index('--game')+1];progress=a[a.index('--progress')+1];verify='--verify-only' in a
def put(**s):
    s.update(game=game,mode='verify' if verify else 'setup',elapsed=1.5)
    open(progress+'.partial','w').write(json.dumps(s));os.replace(progress+'.partial',progress)
if game=='mk1':
    put(step='verify',state='done',report=dict(ok=True,program='ok',checks=['size','sha256'],files=[dict(name='a.rom',status='ok'),dict(name='b.rom',status='ok')]))
elif game=='mk2':
    put(step='accept',state='failed',message='stub failure');sys.exit(1)
else:
    put(step='compile',state='running',units=dict(done=3,total=28))
    child=__import__('subprocess').Popen([sys.executable,'-c','import time;time.sleep(120)'])
    open(os.path.join(os.path.dirname(progress),'child.pid'),'w').write(str(child.pid));time.sleep(120)
)";
template<class F> bool waitFor(F done,int seconds){
 for(auto end=std::chrono::steady_clock::now()+std::chrono::seconds(seconds);std::chrono::steady_clock::now()<end;
     std::this_thread::sleep_for(std::chrono::milliseconds(50)))if(done())return true;
 return false;
}
bool alive(DWORD pid){
 HANDLE p=OpenProcess(SYNCHRONIZE,FALSE,pid);if(!p)return false;
 const bool running=WaitForSingleObject(p,0)==WAIT_TIMEOUT;CloseHandle(p);return running;
}
int wmain(int argc,wchar_t** argv){
 try{
  check(argc==2,"test root argument");const fs::path root=argv[1];
  fs::create_directories(root/L"tools/setup");fs::create_directories(root/L"roms");
  {std::ofstream f(root/L"tools/setup/setup.py",std::ios::binary);f<<stub;}
  {
   mklauncher::Backend b(root);
   check(!b.queueSetup(0,true),"no folder: setup refused");
   check(!b.setRomFolder(0,root/L"absent"),"missing folder refused");
   for(int i=0;i<3;++i)check(b.setRomFolder(i,root/L"roms"),"folder accepted");
   check(!b.romsAcknowledged()&&!b.queueSetup(0,true)&&!b.startSetup(root/L"roms"),"no verify or build before the ROM ownership confirmation");
   check(b.acknowledgeRoms(true),"confirmation saved");
  }
  mklauncher::Backend b(root);
  check(b.setupGame(2).folder==fs::absolute(root/L"roms").lexically_normal()&&b.romsAcknowledged(),"folders and confirmation persist in setup.cfg");
  check(b.queueSetup(0,true)&&b.setupGame(0).queued,"verify queued");
  check(!b.queueSetup(0,false),"one job per game at a time");
  check(waitFor([&]{return !b.setupRunning();},60),"verify finishes");
  const auto& r=b.setupRequirements();
  check(r.checked&&r.python=="3.test"&&r.windows64&&!r.ok&&r.validated=="16.1.0"&&r.compiler.empty(),"requirements parsed before the first job");
  const auto& verified=b.setupGame(0);
  check(verified.state=="done"&&verified.mode=="verify"&&verified.verified&&verified.program=="ok","verify report done");
  check(verified.files.size()==2&&verified.files[1].first=="b.rom"&&verified.files[1].second=="ok"&&verified.checks.size()==2,"per-file report");
  check(b.queueSetup(1,false)&&waitFor([&]{return !b.setupRunning();},60),"failing setup finishes");
  check(b.setupGame(1).state=="failed"&&b.setupGame(1).message=="stub failure"&&b.setupGame(1).step=="accept"&&!b.setupGame(1).verified,"failure keeps step and message");
  check(b.queueSetup(2,false),"long setup queued");
  check(b.queueSetup(0,false),"second job queued behind the first");
  const auto pidFile=root/L"logs/child.pid";
  check(waitFor([&]{b.setupRunning();return fs::exists(pidFile)&&b.setupGame(2).unitsTotal==28;},60),"running units read");
  check(b.setupGame(2).active&&b.setupGame(2).step=="compile"&&b.setupGame(2).unitsDone==3,"progress while running");
  DWORD child=0;{std::ifstream f(pidFile);f>>child;}check(child&&alive(child),"grandchild started");
  check(!b.launch(),"no game launch while the setup runs");
  b.cancelSetup();
  check(waitFor([&]{return !b.setupRunning();},10),"cancel stops the queue");
  check(b.setupGame(2).state=="cancelled"&&!b.setupGame(2).active,"cancelled game");
  check(b.setupGame(0).state=="cancelled"&&!b.setupGame(0).queued,"queued game cancelled too");
  check(waitFor([&]{return !alive(child);},10),"Job Object ends the whole tree");
  check(fs::exists(b.setupLog(2))&&b.setupOutput(2).empty(),"log kept, no output without a record");
  std::cout<<"setup queue tests passed\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
}
