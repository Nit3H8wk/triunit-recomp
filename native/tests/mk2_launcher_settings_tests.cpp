#include "../launcher/launcher_main.cpp"
#include <iostream>
int wmain(int argc,wchar_t** argv){
 try{
  if(argc!=2)throw std::runtime_error("isolated root required");
  App app(fs::absolute(argv[1]));
  app.hitTargets();
  auto enabled=[&](){app.hitTargets();return std::find_if(app.controls.begin(),app.controls.end(),[](const Control& c){return c.id==11;})->enabled;};
  if(!enabled())throw std::runtime_error("launcher Settings must be enabled without explicit selection");
  app.key('S');if(!app.settings||app.category!=launcherTab||app.editingGame)throw std::runtime_error("shortcut opens collection Settings only");
  app.act(212);
  app.selected=1;app.mk2Available=true;
  if(app.gameSelected())throw std::runtime_error("hover is not explicit selection");
  app.openDetails();app.details=false;
  if(!enabled())throw std::runtime_error("available selected machine must enable settings");
  app.openSettings();
  if(!app.settings||app.draft.video().sync!=2)throw std::runtime_error("MK2 settings defaults");
  app.act(220);
  app.draft.video().scalefx=true;app.setScaleAmount(969);if(app.draft.video().scalefxAmount!=0)throw std::runtime_error("slider zero");
  app.setScaleAmount(1229);if(app.draft.video().scalefxAmount!=100)throw std::runtime_error("slider full");
  app.setScaleAmount(1065);if(app.draft.video().scalefxAmount!=37)throw std::runtime_error("slider continuous percentage");
  app.selected=0;app.act(videoPage);auto a=app.actions();app.focus=int(std::find(a.begin(),a.end(),256)-a.begin());app.key(VK_LEFT);
  if(app.draft.video().scalefxAmount!=32)throw std::runtime_error("slider keyboard direction");
  app.act(255);app.selected=1;if(app.draft.video().scalefx||app.draft.video().scalefxAmount!=32)throw std::runtime_error("toggle preserves amount");
  app.setScaleAmount(-100);if(app.draft.video().scalefxAmount!=0)throw std::runtime_error("slider lower bound");
  app.setScaleAmount(2000);if(app.draft.video().scalefxAmount!=100)throw std::runtime_error("slider upper bound");
  app.draft.video().scanlines=3;app.draft.video().filter=1;app.act(211);
  if(app.draft.video().sync!=2||app.draft.video().scanlines!=0||app.draft.video().filter!=0||app.draft.video().highRefresh||app.draft.remastered||app.draft.video().scalefx||app.draft.video().scalefxAmount!=100)
   throw std::runtime_error("MK2 restore shows unsupported VRR or non-default capabilities");
  if(fs::exists(app.backend.root()/L"build/native/mk2-arcade-v1/profile/launcher.ini"))throw std::runtime_error("restore persisted without save");
  app.backend.config=app.draft;if(!app.backend.save())throw std::runtime_error("MK2 settings save");
  if(!app.backend.selectGame(0)||app.backend.config.video().sync!=1)throw std::runtime_error("MK1 isolated defaults");
  if(!app.backend.selectGame(1)||app.backend.config.video().sync!=2)throw std::runtime_error("MK2 isolated settings reload");
  app.settings=false;app.selected=2;app.openDetails();app.openSettings();
  if(!enabled()||app.category!=launcherTab||app.editingGame)throw std::runtime_error("unavailable selection keeps collection Settings only");
  std::cout<<"PASS: MK2 draft reset capabilities, explicit save and MK1/MK2 profile isolation\n";return 0;
 }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
