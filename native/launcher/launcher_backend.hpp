#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <array>
#include <filesystem>
#include <string>
#include <vector>
namespace mklauncher {
struct VideoConfig {
 int scanlines=0,filter=0,sync=1,color=0,brightness=100,scalefxAmount=100,scaleMode=0,cas=0,bilateral=0;
 bool scalefx=false,bezel=true,highRefresh=false,smaa=false,fullscreen=true;
};
// MK3 native Remastered defaults ([Video.Remastered] of the MK3 profile): BVM / 1080p (preset 4) and ScaleFX 100. The MK3
// Original defaults are VideoConfig{}: no effect, the arcade image.
constexpr VideoConfig mk3RemasteredDefaults(){VideoConfig v;v.scanlines=4;v.scalefx=true;v.scalefxAmount=100;return v;}
struct Config {
 int fps=60,uiVolume=0,gameVolume=100,audioLatency=1;
 int mk3Engine=1; // [MK3] Engine: saved MK3 card choice (see Backend::mk3Engine); absent, 0 or invalid -> 1, native Original
 bool blood=true,violence=true,cmosCoinage=false,remastered=false,reducedMotion=false,vsync=true,fullscreen=true,videoEffects=false;
 std::array<VideoConfig,2> videos{}; // [Video.Original] / [Video.Remastered]; for MK3 the profile of each edition (mk3Engine 1 / 2)
 VideoConfig& video(bool remastered){return videos[remastered];}
 const VideoConfig& video(bool remastered)const{return videos[remastered];}
 VideoConfig& video(){return video(remastered);}
 const VideoConfig& video()const{return video(remastered);}
};
struct GameAdjustments {int difficulty=3,coinage=1;bool freePlay=false,customCoinage=false;};
struct LauncherPreferences {
 int fps=60,musicVolume=100;
 bool vsync=true,reducedMotion=false,fullscreen=true,musicMuted=false;
};
class Backend {
public:
 explicit Backend(const std::filesystem::path& root);
 ~Backend();
 Backend(const Backend&)=delete;
 Backend& operator=(const Backend&)=delete;
 Config config;
 bool load();bool save();void reset();
 LauncherPreferences loadLauncherPreferences(const Config& legacy)const;
 bool saveLauncherPreferences(const LauncherPreferences&)const;
 GameAdjustments adjustments;
 bool refreshAdjustments();bool adjustmentsAvailable()const;
 std::wstring coinageLabel(const GameAdjustments&)const;
 bool saveAll(const Config&,const GameAdjustments&);bool resetHighScores();
 bool selectGame(int index);
 bool available(int index) const;
 bool nativeMk2Installed() const;
 // MK3 edition of the native package (D1, 14/11/2026: no temporary core): 1 native Original, 2 native Remastered (video layers
 // 1 and 2; arcade audio in both, D7). chooseMk3Engine saves the choice as [MK3] Engine and load() restores it; available(2) is
 // the native package. A refused launch (manifest, executable or ROM check) reports the error and leaves MK3 unavailable;
 // nothing else is started. The launch passes the edition's video profile, GameVolume and AudioLatency as native MK2 does.
 int mk3Engine() const{return mk3Engine_;}
 bool setMk3Engine(int engine); // effective engine of this session only
 bool chooseMk3Engine(int engine);
 bool remasteredAvailable() const;
 // Local setup (tools/setup/setup.py): a game is offered only after its record in generated/<game>/<sha>/ exists.
 bool setupFinished(int index) const;
 bool startSetup(const std::filesystem::path& roms);
 bool setupRunning();
 bool launchNativeExperiment(const std::filesystem::path& manifest,const std::filesystem::path& settings={});
 bool launch(unsigned frames=0);void poll();bool running() const;
 void requestStop();
 const std::wstring& status() const;const std::filesystem::path& root() const;DWORD exitCode() const;
 HWND gameWindow() const;
private:
 bool launchNative(const std::filesystem::path& manifest,const std::filesystem::path& settings,bool diagnostics);
 bool launchMk3();
 int mk3Engine_=1;bool mk3Native_=false;
 std::filesystem::path root_;
 std::filesystem::path gameExecutable_;
 std::wstring status_;
 HANDLE process_=nullptr,setupProcess_=nullptr;
 DWORD processId_=0,exitCode_=0,gamePid_=0;
 ULONGLONG nextDiscovery_=0;
 bool stopping_=false,nativeExperiment_=false,nativeLiveExperiment_=false,nativePlayable_=false;
 int gameIndex_=0;
 bool adjustmentsAvailable_=false,selectedNative_=false;
 std::filesystem::path adjustmentsPath_;
 std::vector<uint8_t> adjustmentsImage_,adjustmentsProgram_;
 std::vector<std::wstring> coinageLabels_;
 std::string adjustmentsSha_;
 HWND gameWindow_=nullptr;
 bool readSettings(const std::filesystem::path&,const std::string& section,int capabilities,bool mk3Legacy=false);
 std::filesystem::path operatorPath(bool verifyPayload=true)const;
 std::filesystem::path operatorRoms()const;
 void inspectGame();
};
}
