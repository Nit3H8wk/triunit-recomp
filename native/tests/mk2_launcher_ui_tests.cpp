#include "../launcher/launcher_main.cpp"
#include <iostream>
void verify(bool value,const char* why){if(!value)throw std::runtime_error(why);}
int wmain(int argc,wchar_t** argv){
 if(argc!=2)return 2;
 try{
  App app(argv[1]);app.selected=1;app.openDetails();app.details=false;
  verify(app.backend.launch(180),"start actual MK2");
  app.selected=0;app.openDetails();verify(!app.details,"running MK2 must not open MK1 details with a stale backend");
  app.backend.requestStop();const auto start=GetTickCount64();while(app.backend.running()&&GetTickCount64()-start<20000){app.backend.poll();app.backend.requestStop();Sleep(10);}
  verify(!app.backend.running(),"owned session closed");
  app.selected=3;app.openSettings();verify(app.settings&&app.category==launcherTab&&!app.editingGame,"unsupported card opens collection Settings only");
  std::cout<<"PASS: running game selection and unsupported settings cannot mislabel profiles\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
