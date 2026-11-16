#include "../launcher/launcher_main.cpp"
#include "mk5_operator_settings.hpp"
#include <iostream>
void need(bool value,const char* why){if(!value)throw std::runtime_error(why);}
std::vector<uint8_t> readImage(const fs::path& path){std::ifstream file(path,std::ios::binary);need(bool(file),"fixture read");return {std::istreambuf_iterator<char>(file),{}};}
void writeImage(const fs::path& path,const std::vector<uint8_t>& image){std::ofstream file(path,std::ios::binary);file.write(reinterpret_cast<const char*>(image.data()),std::streamsize(image.size()));need(bool(file),"fixture write");}
void realPricing(const fs::path& source,const fs::path& base){
 const auto program=LoadMk5Program(source/L"roms/mk1");const auto seedPath=source/L"generated/mk1"/fs::path(program.sha256)/L"factory-default-control-input.bin";const auto seed=readImage(seedPath);
 for(const auto* mode:{L"coinage",L"freeplay",L"cycle",L"confirm"}){
  const auto root=base/mode,roms=root/L"roms/mk";fs::create_directories(roms);
  fs::create_hard_link(program.even_source,roms/L"verified-even.bin");fs::create_hard_link(program.odd_source,roms/L"verified-odd.bin");
  auto image=seed;for(size_t n=1;n<image.size();n+=2)image[n]=uint8_t(n*97+(n>>3));
  const bool cycle=std::wstring(mode)==L"cycle";mkoperator::ApplyMk1Coinage(image,program.bytes,cycle?1:3,!cycle);
  mkoperator::WriteParameter(image,14,4);mkoperator::UpdateSettingsChecksum(image);
  const auto profile=root/L"build/native/manual-temporary-8-20261025/profile";fs::create_directories(profile);
  const auto cmos=profile/L"cmos.bin";writeImage(cmos,image);{std::ofstream ini(profile/L"launcher.ini");ini<<"[MK1]\nCmosCoinage=0\n";need(bool(ini),"fixture physical DIP preference");}
  App app(root);app.mk1Available=true;app.selectMachine(0);app.openSettings();app.act(224);
  need(app.settings&&app.backend.adjustmentsAvailable()&&!app.draft.cmosCoinage,"real profile opens with physical DIP coinage source");
  const auto shown=app.effectiveAdjustments();
  need(shown.coinage==1&&!shown.freePlay&&!shown.customCoinage&&shown.difficulty==4,"MK1 physical DIP displays effective USA1/freeoff while preserving native difficulty");
  need(app.draftAdjustments.coinage==(cycle?1:3)&&app.draftAdjustments.freePlay==!cycle,"display derivation cannot mutate raw CMOS draft");
  if(std::wstring(mode)==L"confirm"){
   app.act(225);app.act(271);need(app.resetScoresPending,"real ranking requests explicit confirmation");
   const auto actions=app.actions();const auto confirm=std::find(actions.begin(),actions.end(),272);need(confirm!=actions.end(),"confirmation is keyboard reachable");
   app.focus=int(confirm-actions.begin());app.key(VK_LEFT);app.key(VK_RIGHT);
   need(app.resetScoresPending&&readImage(cmos)==image,"arrows on Confirm cannot reset or silently accept destructive action");
   app.key(VK_RETURN);need(!app.resetScoresPending&&readImage(cmos)!=image,"Enter explicitly confirms real native ranking reset");
   const auto after=readImage(cmos);for(size_t n=0;n<after.size();++n)if(n%2||n<0x1800||n>0x1910)need(after[n]==image[n],"confirmed ranking reset preserves adjustments and opaque high bytes");
  }else{
   auto expected=image;
   if(std::wstring(mode)==L"coinage"){
    app.act(261);need(app.draftAdjustments.coinage==2&&!app.draftAdjustments.freePlay&&!app.draftAdjustments.customCoinage&&app.draft.cmosCoinage,"coinage editing starts from displayed USA1 and explicitly switches source to CMOS");
    mkoperator::ApplyMk1Coinage(expected,program.bytes,2,false);
   }else if(std::wstring(mode)==L"freeplay"){
    app.act(262);need(app.draftAdjustments.coinage==1&&app.draftAdjustments.freePlay&&app.draft.cmosCoinage,"Free Play click turns displayed off into on at displayed USA1");
    mkoperator::ApplyMk1Coinage(expected,program.bytes,1,true);
   }else{
    for(unsigned n=0;n<58;++n)app.act(261);
    need(app.draftAdjustments.coinage==1&&!app.draftAdjustments.freePlay&&app.draft.cmosCoinage,"full58-price cycle preserves explicit CMOS source choice even when values return to initial state");
   }
   app.act(210);need(app.backend.config.cmosCoinage&&readImage(cmos)==expected,"UI save persists effective pricing/source with exact CMOS byte preservation");
   Backend reloaded(root);need(reloaded.load()&&reloaded.config.cmosCoinage&&reloaded.adjustments.coinage==app.draftAdjustments.coinage&&reloaded.adjustments.freePlay==app.draftAdjustments.freePlay,"saved effective pricing survives a new backend");
  }
 }
 need(readImage(seedPath)==seed&&LoadMk5Program(source/L"roms/mk1").sha256==program.sha256,"ROM-backed UI contract preserves source program/seed");
 std::cout<<"PASS real MK1 effective DIP pricing display, first coinage/FreePlay edit, complete cycle/source persistence and explicit ranking confirmation\n";
}
void menuAudio(App& app){
 app.act(223);app.hitTargets();
 for(int id:{menuVolume,menuMute}){
  const auto control=std::find_if(app.controls.begin(),app.controls.end(),[&](const Control& value){return value.id==id;});
  need(control!=app.controls.end()&&control->enabled,"launcher tab must expose menu volume and mute");
 }
 need(app.menuMusicLevel()==100,"menu preserves default mix on legacy profiles");
 app.pressed=app.hit(menuVolumeBox.x+1,menuVolumeBox.y+1);
 app.mx=menuVolumeBox.x-10;app.dragSlider();need(app.menuMusicLevel()==0,"menu drag lower bound");
 app.mx=menuVolumeBox.x+menuVolumeBox.w+10;app.dragSlider();need(app.menuMusicLevel()==100,"menu drag upper bound");
 app.mx=menuVolumeBox.x+menuVolumeBox.w*.37f;app.dragSlider();app.pressed=-1;
 need(app.menuMusicLevel()==37,"menu volume previews every percentage");
 const auto actions=app.actions();
 app.focus=int(std::find(actions.begin(),actions.end(),menuVolume)-actions.begin());
 app.padActions(XINPUT_GAMEPAD_DPAD_LEFT);need(app.menuMusicLevel()==32,"menu volume works through gamepad");
 app.key(VK_DOWN);app.key(VK_RETURN);
 need(app.menuMusicLevel()==0&&app.draftLauncher.musicVolume==32&&app.launcher.musicVolume==100,
      "mute previews silence and retains volume before saving");
 app.act(210);app.act(212);
 need(app.menuMusicLevel()==0&&app.backend.config.gameVolume==32,"save affects the menu mix alone");

 App reopened(app.backend.root());reopened.mk2Available=true;reopened.selectMachine(1);reopened.openSettings();reopened.act(223);
 need(reopened.menuMusicLevel()==0&&reopened.draftLauncher.musicVolume==32&&reopened.backend.config.gameVolume==100,
      "saved mute and level survive restart and game selection");
 reopened.act(menuMute);need(reopened.menuMusicLevel()==32,"unmute restores the selected level");
 reopened.padActions(XINPUT_GAMEPAD_B);need(reopened.menuMusicLevel()==0,"cancel restores saved mute");
 reopened.openSettings();reopened.act(menuMute);reopened.act(210);
 const auto preferences=reopened.backend.loadLauncherPreferences(Config{});
 need(preferences.musicVolume==32&&!preferences.musicMuted,"save unmute from MK2 to the collection profile");
}
void launcherFromHome(const fs::path& root){
 App app(root);app.act(11);
 need(app.settings&&app.category==launcherTab&&app.chosen==-1&&!app.editingGame,
      "Home Settings opens the Launcher tab with no game selected");
 app.hitTargets();
 for(int id:{220,221,222,224,225}){
  const auto tab=std::find_if(app.controls.begin(),app.controls.end(),[&](const Control& value){return value.id==id;});
  need(tab!=app.controls.end()&&!tab->enabled,"game tabs disabled without a game");
 }
 app.act(220);app.key('2');app.padActions(XINPUT_GAMEPAD_RIGHT_SHOULDER);
 need(app.category==launcherTab,"mouse, keyboard and gamepad cannot switch to game tabs");
 for(int id:std::array<int,5>{202,203,204,206,menuMute})app.act(id);
 app.pressed=menuVolume;app.mx=menuVolumeBox.x+menuVolumeBox.w*.42f;app.dragSlider();app.pressed=-1;
 app.act(210);app.act(212);
 App reopened(root);reopened.key('S');
 need(reopened.settings&&reopened.category==launcherTab&&reopened.launcher.fps==120&&!reopened.launcher.vsync&&
      reopened.launcher.reducedMotion&&!reopened.launcher.fullscreen&&reopened.launcher.musicMuted&&reopened.launcher.musicVolume==42,
      "all collection preferences survive restart without a game");
 reopened.act(211);need(reopened.menuMusicLevel()==100&&reopened.draftLauncher.fps==60,"restore defaults previews only launcher values");
 reopened.act(212);need(reopened.menuMusicLevel()==0&&reopened.launcher.fps==120,"cancel keeps saved launcher settings");
 reopened.padActions(XINPUT_GAMEPAD_Y);need(reopened.settings&&reopened.category==launcherTab,"gamepad opens Home Settings");
 need(!fs::exists(root/L"build/native/manual-temporary-8-20261025/profile/launcher.ini")&&
      !fs::exists(root/L"build/native/mk2-arcade-v1/profile/launcher.ini"),"Home save does not create a game profile");

 const auto legacy=root/L"legacy";
 const auto ini=legacy/L"build/native/manual-temporary-8-20261025/profile/launcher.ini";
 const auto audio=legacy/L"build/native/launcher-profile/menu-audio.cfg";
 fs::create_directories(ini.parent_path());fs::create_directories(audio.parent_path());
 {std::ofstream(ini)<<"[Launcher]\nFPS=240\nVSync=0\nReducedMotion=1\nFullscreen=0\n[MK1]\nGameVolume=23\n";
  std::ofstream(audio)<<"Volume=27\nMuted=1\n";}
 const auto original=readImage(ini);
 App migrated(legacy);migrated.openSettings();
 need(migrated.launcher.fps==240&&!migrated.launcher.vsync&&migrated.launcher.reducedMotion&&
      !migrated.launcher.fullscreen&&migrated.launcher.musicVolume==27&&migrated.launcher.musicMuted,
      "existing launcher preferences and menu volume are carried forward");
 migrated.act(211);migrated.act(210);need(readImage(ini)==original,"launcher save leaves the legacy game profile byte-exact");
}
int wmain(int argc,wchar_t** argv){try{
 need(argc==2||argc==3,"isolated root and optional source project required");App app(argv[1]);
 launcherFromHome(app.backend.root()/L"home");
 app.mk1Available=true;app.selectMachine(0);app.openSettings();
 need(app.settings,"selected game opens settings");app.act(224);need(app.category==4,"game adjustments tab");
 app.hitTargets();for(int id:{260,261,262,263,264}){
  auto c=std::find_if(app.controls.begin(),app.controls.end(),[&](const Control& value){return value.id==id;});
  need(c!=app.controls.end()&&!c->enabled,"operator controls unavailable without real profile");
 }
 app.act(225);need(app.category==5,"utilities tab");app.setGameVolume(969);need(app.draft.gameVolume==0,"volume lower bound");
 app.setGameVolume(1229);need(app.draft.gameVolume==100,"volume upper bound");app.setGameVolume(1065);need(app.draft.gameVolume==37,"volume continuous percentage");
 auto actions=app.actions();app.focus=int(std::find(actions.begin(),actions.end(),270)-actions.begin());app.key(VK_LEFT);need(app.draft.gameVolume==32,"volume keyboard direction");
 app.focus=int(std::find(actions.begin(),actions.end(),210)-actions.begin());app.key(VK_RIGHT);need(app.backend.config.gameVolume==100,"arrows on Save must not commit");
 app.act(210);need(app.backend.config.gameVolume==32,"save game volume");
 app.setGameVolume(1229);app.act(212);need(app.backend.config.gameVolume==32&&app.draft.gameVolume==32,"cancel discards draft volume");
 app.selectMachine(1);need(app.backend.config.gameVolume==100,"MK2 independent volume");
 app.mk2Available=true;app.openSettings();app.act(225);app.hitTargets();
 const auto legacyVolume=std::find_if(app.controls.begin(),app.controls.end(),[](const Control& value){return value.id==270;});
 need(legacyVolume!=app.controls.end()&&!legacyVolume->enabled,"historical MK2 without native gain must disable software volume control");
 app.setGameVolume(969);need(app.draft.gameVolume==100,"disabled historical volume must reject pointer slider mutation");
 const auto legacyActions=app.actions();need(std::find(legacyActions.begin(),legacyActions.end(),270)==legacyActions.end(),"historical MK2 keyboard navigation must omit unavailable software volume");
 app.act(212);app.selectMachine(0);need(app.backend.config.gameVolume==32,"MK1 volume reload");
 app.openSettings();app.act(225);app.act(271);need(!app.resetScoresPending,"missing ranking cannot request destructive action");
 menuAudio(app);
 std::cout<<"PASS Home launcher settings, menu audio preview, save, restart, cancel, migration and game isolation\n";
 std::cout<<"PASS operator tabs, disabled missing profile, volume pointer/keyboard, save/cancel and per-game isolation\n";
 if(argc==3)realPricing(fs::absolute(argv[2]),fs::absolute(argv[1])/L"rom-backed");
 return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
