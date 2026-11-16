#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#ifndef WINVER
#define WINVER 0x0A00
#endif
#include "launcher_renderer.hpp"
#include "launcher_backend.hpp"
#include "launcher_music.hpp"
#include "launcher_legal.hpp"
#include <shobjidl.h>
#include "../include/mk5_video_presets.hpp"
#include <windowsx.h>
#include <shellapi.h>
#include <mmsystem.h>
#include "../include/mk5_gamepad.hpp"
#include "../include/mk5_timing.hpp"
#include <array>
#include <algorithm>
#include <cmath>
#include <chrono>
#include <future>
#include <fstream>
#include <vector>
#include <sstream>
#include <stdexcept>
#include <cstring>

namespace fs=std::filesystem;
using namespace mklauncher;
namespace {
constexpr uint64_t ticksPerSecond=10000000;
uint64_t frameTicks(){
    using Tick=std::chrono::duration<uint64_t,std::ratio<1,ticksPerSecond>>;
    return std::chrono::duration_cast<Tick>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
bool frameDue(mk5timing::Cadence& cadence,uint64_t now,unsigned fps){
    const auto interval=(ticksPerSecond+fps-1)/fps;
    if(cadence.interval!=interval)cadence={0,interval};
    if(!cadence.due(now))return false;
    cadence.presented(now);
    return true;
}
struct FrameTimer {
    HANDLE handle=CreateWaitableTimerExW(nullptr,nullptr,0x00000002,TIMER_ALL_ACCESS);
    FrameTimer(){
        if(!handle)handle=CreateWaitableTimerW(nullptr,FALSE,nullptr);
        if(!handle)throw std::runtime_error("launcher frame timer");
    }
    ~FrameTimer(){CloseHandle(handle);}
    void arm(uint64_t ticks)const{
        LARGE_INTEGER due{};
        due.QuadPart=-static_cast<LONGLONG>(ticks);
        if(!SetWaitableTimer(handle,&due,0,nullptr,nullptr,FALSE))throw std::runtime_error("launcher frame timer deadline");
    }
};
constexpr Color red{1,.16f,.08f,1},gold{1,.66f,.24f,1},white{.88f,.91f,.97f,1},muted{.45f,.52f,.65f,1},blue{.10f,.43f,1,1};
const std::array<std::wstring,4> games={compatibleGames[0].name,compatibleGames[1].name,compatibleGames[2].name,compatibleGames[3].name};
constexpr std::array<Rect,4> positions={Rect{100,155,310,680},Rect{460,155,290,680},Rect{790,155,290,680},Rect{1110,155,325,680}};
constexpr std::array<float,4> wideCabinetShift{48,112,173,236};
std::wstring widen(const std::string& text){if(text.empty())return {};int n=MultiByteToWideChar(CP_UTF8,0,text.data(),int(text.size()),nullptr,0);std::wstring w(size_t(n),0);MultiByteToWideChar(CP_UTF8,0,text.data(),int(text.size()),w.data(),n);return w;}
void rejectLinks(fs::path path){while(!path.empty()){DWORD attr=GetFileAttributesW(path.c_str());if(attr!=INVALID_FILE_ATTRIBUTES&&(attr&FILE_ATTRIBUTE_REPARSE_POINT))throw std::runtime_error("launcher path uses a link/junction");auto parent=path.parent_path();if(parent==path)break;path=parent;}}
void eventLog(const fs::path& root,const std::string& value){
    auto path=root/L"logs/temporaria-8/ui-latest.log";rejectLinks(path);fs::create_directories(path.parent_path());
    if(fs::exists(path)&&fs::file_size(path)>65536){std::ofstream clear(path,std::ios::trunc);}
    std::ofstream out(path,std::ios::app);out<<GetTickCount64()<<" "<<value<<"\n";
}
std::wstring quote(const std::wstring& s){std::wstring o=L"\"";unsigned slashes=0;for(wchar_t c:s){if(c==L'\\'){++slashes;continue;}if(c==L'\"'){o.append(slashes*2+1,L'\\');o+=c;}else{o.append(slashes,L'\\');o+=c;}slashes=0;}o.append(slashes*2,L'\\');return o+L'\"';}
// Short metallic coin/chute sound, generated once and kept alive for async WinMM.
void coinSound(){
    static const auto wav=[](){
        constexpr unsigned rate=22050,count=rate*32/100;std::vector<unsigned char> bytes(44+count*2,0);
        auto word=[&](unsigned at,unsigned n,unsigned size){for(unsigned i=0;i<size;++i)bytes[at+i]=static_cast<unsigned char>(n>>(8*i));};
        std::memcpy(bytes.data(),"RIFF",4);word(4,unsigned(bytes.size()-8),4);std::memcpy(bytes.data()+8,"WAVEfmt ",8);
        word(16,16,4);word(20,1,2);word(22,1,2);word(24,rate,4);word(28,rate*2,4);word(32,2,2);word(34,16,2);std::memcpy(bytes.data()+36,"data",4);word(40,count*2,4);
        unsigned noise=17;for(unsigned i=0;i<count;++i){double t=double(i)/rate,value=0;
            for(double strike:{0.,.047,.129})if(t>=strike){double a=t-strike;noise=noise*1664525u+1013904223u;
                value+=.12*(std::sin(6.283185307*2180*a)+.7*std::sin(6.283185307*3517*a)+.4*std::sin(6.283185307*5273*a))*std::exp(-a*34);
                value+=(double(noise>>16)/32768-1)*.22*std::exp(-a*260);}
            word(44+i*2,unsigned(int(std::clamp(value,-1.,1.)*32767)),2);
        }return bytes;
    }();
    PlaySoundW(reinterpret_cast<LPCWSTR>(wav.data()),nullptr,SND_MEMORY|SND_ASYNC|SND_NODEFAULT);
}
struct Control{int id;Rect box;bool enabled;};
enum VideoControl {videoProfile=274,videoPage,videoScale,videoCas,videoSmaa,videoBilateral,videoFullscreen};
enum MenuAudioControl {menuVolume=281,menuMute};
constexpr int launcherTab=3;
constexpr Rect menuVolumeBox{969,700,166,54},menuMuteBox{1145,700,84,54};
struct App {
    HWND window=nullptr;Backend backend;std::unique_ptr<Renderer> graphics;
    std::unique_ptr<MenuMusic> menuMusic;
    std::vector<Control> controls;
    int selected=0,chosen=-1,hover=-1,pressed=-1,focus=0,category=0;bool settings=false,details=false,closing=false,active=true,fullscreen=false,restoring=false,padReady=false;
    mk5pad::Devices pads;ULONGLONG nextPadRepeat=0;WORD padDirections=0;
    Config draft{};GameAdjustments draftAdjustments{};
    LauncherPreferences launcher{},draftLauncher{};
    bool editingGame=false,resetScoresPending=false,videoRemastered=false;
    RECT placement{};std::wstring notice;
    std::array<float,4> glows{};float mx=-1,my=-1;const uint64_t started=frameTicks();bool receivedInput=false;
    WORD gamepadButtons=0;ULONGLONG nextPad=0,nextPoll=0,availabilityDue=0;
    bool mk1Available=false,mk2Available=false,mk3Available=false,musicAvailable=false,mk1Remastered=false,mk2Remastered=false;
    std::future<std::array<bool,3>> availability;
    int drawnFocus=-1;
    explicit App(fs::path root):backend(root){backend.load();draft=backend.config;launcher=draftLauncher=backend.loadLauncherPreferences(backend.config);notice=backend.status();mk1Available=backend.available(0);mk2Available=backend.available(1);mk3Available=backend.available(2);musicAvailable=backend.remasteredAvailable();mk1Remastered=backend.config.remastered;Backend mk2(root);mk2.selectGame(1);mk2Remastered=mk2.config.remastered;Backend mk3(root);mk3.selectGame(2);backend.setMk3Engine(mk3.mk3Engine());availabilityDue=GetTickCount64()+10000;}
    ~App() noexcept {
        menuMusic.reset();
        PlaySoundW(nullptr,nullptr,0);
        // Also runs during an exception: do not release the singleton while a
        // game/logger that we started is still writing its profile.
        if(backend.running()){
            try{eventLog(backend.root(),"exception-or-scope-shutdown");}catch(...){}
            while(backend.running()){
                try{backend.poll();}catch(...){/* Reap an exited session independently of a discovery failure. */}
                if(backend.running()){try{backend.requestStop();}catch(...){/* Retry graceful discovery on the next iteration. */}}
                if(backend.running())Sleep(100);
            }
        }
    }
    // ROM-folder selector: the setup verifies the user's files and generates the games on this machine.
    void chooseRomFolder(){
        if(backend.running()||backend.setupRunning())return;
        const HRESULT com=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
        struct Com{HRESULT hr;~Com(){if(SUCCEEDED(hr))CoUninitialize();}} comGuard{com};
        IFileOpenDialog* dialog=nullptr;
        if(FAILED(CoCreateInstance(CLSID_FileOpenDialog,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&dialog)))){notice=L"Seletor de pasta indisponivel.";return;}
        DWORD options=0;dialog->GetOptions(&options);dialog->SetOptions(options|FOS_PICKFOLDERS|FOS_FORCEFILESYSTEM|FOS_PATHMUSTEXIST);
        dialog->SetTitle(L"Pasta com as ROMs da sua placa");
        fs::path folder;
        if(SUCCEEDED(dialog->Show(window))){IShellItem* item=nullptr;if(SUCCEEDED(dialog->GetResult(&item))){PWSTR path=nullptr;if(SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH,&path))){folder=path;CoTaskMemFree(path);}item->Release();}}
        dialog->Release();
        if(folder.empty())return;
        backend.startSetup(folder);notice=backend.status();
    }
    bool settingsEnabled()const{return !closing&&!backend.running();}
    bool ready(int game)const{return game==0?mk1Available:game==1?mk2Available:game==2&&mk3Available;}
    // MK3 card: the two editions of the native package (Original / Remastered video layer); UMK3 is not integrated.
    const wchar_t* mk3Edition()const{return backend.mk3Engine()==2?L"NATIVO  /  REMASTERIZADA":L"NATIVO  /  ORIGINAL";}
    bool gameSelected()const{return settingsEnabled()&&chosen==selected&&ready(selected);}
    void rememberEdition(int game){if(game==0)mk1Remastered=backend.config.remastered;else if(game==1)mk2Remastered=backend.config.remastered;}
    bool tabEnabled(int tab)const{return tab==launcherTab||editingGame;}
    // MK1 package, native MK2 and the MK3 native package share the presenter options (filters, CRT, effects, sync, volume).
    bool nativeVideo()const{return selected==0||(selected==1&&backend.nativeMk2Installed())||selected==2;}
    VideoConfig& video(){return draft.video(videoRemastered);}
    const VideoConfig& video()const{return draft.video(videoRemastered);}
    bool scaleFxActive()const{return nativeVideo()&&video().scalefx;}
    bool gameVolumeEnabled()const{return nativeVideo();}
    int menuMusicLevel()const{
        const auto& preferences=settings&&category==launcherTab?draftLauncher:launcher;
        return preferences.musicMuted?0:preferences.musicVolume;
    }
    std::array<int,7> videoControls()const{
        return draft.videoEffects?std::array<int,7>{videoProfile,videoPage,255,256,videoCas,videoSmaa,videoBilateral}
                           :std::array<int,7>{videoProfile,videoPage,videoScale,201,200,207,208};
    }
    std::array<int,5> displayControls()const{return {videoProfile,250,251,209,videoFullscreen};}
    bool videoControlEnabled(int id)const{
        if(id==256)return scaleFxActive();
        if(id==videoProfile||id==videoPage||id==videoScale||id==255||id==videoCas||
           id==videoSmaa||id==videoBilateral||id==251||id==videoFullscreen)return nativeVideo();
        return true;
    }
    GameAdjustments effectiveAdjustments()const{
        auto value=draftAdjustments;
        // The legacy MK1 electrical DIP word selects USA 1; only blood/violence bits vary.
        if(selected==0&&!draft.cmosCoinage){value.coinage=1;value.freePlay=false;value.customCoinage=false;}
        return value;
    }
    void selectMachine(int index){
        if(backend.running()||settings||index<0||index>=int(games.size()))return;
        if(chosen==index&&selected==index&&index==2&&mk3Available){
            const int engine=3-backend.mk3Engine();
            if(!backend.chooseMk3Engine(engine)){notice=backend.status();return;}
            draft=backend.config;notice=std::wstring(mk3Edition())+L" selecionado. Use JOGAR para iniciar.";
            eventLog(backend.root(),"mk3-engine "+std::to_string(engine));return;
        }
        if(chosen==index&&selected==index&&index<3){
            if(!gameSelected()){notice=L"Jogo indisponivel: verifique produto, nucleo e ROMs.";return;}
            musicAvailable=backend.remasteredAvailable();
            if(!musicAvailable&&!backend.config.remastered){notice=L"Original Arcade: versao remasterizada indisponivel.";return;}
            const auto before=backend.config;backend.config.remastered=!before.remastered;
            if(!backend.save()){notice=backend.status();backend.config=before;return;}
            draft=backend.config;rememberEdition(index);
            notice=backend.config.remastered?L"Remasterizada selecionada. Use JOGAR para iniciar.":L"Original Arcade selecionado. Use JOGAR para iniciar.";
            eventLog(backend.root(),backend.config.remastered?"mode-remastered":"mode-original");return;
        }
        if(index<3){
            const auto before=backend.config;const int previous=chosen<3&&chosen>=0?chosen:0;
            if(!backend.selectGame(index)){notice=backend.status();backend.selectGame(previous);backend.config=before;return;}
            draft=backend.config;musicAvailable=backend.remasteredAvailable();rememberEdition(index);
        }
        selected=chosen=index;details=false;focus=index;
        if(gameSelected()){
            if(menuMusic)menuMusic->duck();
            coinSound();
        }
        notice=index<3?(gameSelected()?L"":L"Jogo indisponivel: verifique produto, nucleo e ROMs."):L"Este jogo ainda nao esta integrado.";
        eventLog(backend.root(),"game-select "+std::to_string(index));
    }
    void openDetails(){selectMachine(selected);}
    void invalidate(){receivedInput=true;}
    float layoutWidth()const{return graphics?graphics->layoutWidth():baseWidth;}
    float extraWidth()const{return layoutWidth()-baseWidth;}
    float cabinetShift(int i)const{return wideCabinetShift[size_t(i)]*extraWidth()/(wideWidth-baseWidth);}
    Rect rightAligned(Rect box)const{box.x+=extraWidth();return box;}
    void hitTargets(){
        // Input follows current state immediately, including multiple messages
        // delivered before the next GPU frame completes.
        controls.clear();
        if(!settings&&!details){for(int i=0;i<4;++i){auto r=positions[size_t(i)];controls.push_back({i+1,{r.x+cabinetShift(i),r.y+15,r.w,680},!backend.running()});}if(chosen>=0)controls.push_back({20,rightAligned({1229,942,260,48}),gameSelected()});}
        if(settings){
            for(int i=0;i<6;++i)controls.push_back({220+i,{300+float(i)*156,294,156,40},tabEnabled(i)});
            if(category==0){float y=350;for(int id:videoControls()){controls.push_back({id,{969,y,260,54},videoControlEnabled(id)});y+=60;}}
            if(category==1){controls.push_back({245,{969,350,260,54},musicAvailable||draft.remastered});controls.push_back({205,{969,420,260,54},true});controls.push_back({243,{969,490,260,54},false});controls.push_back({244,{969,560,260,54},false});controls.push_back({246,{969,630,260,54},false});}
            if(category==2){float y=350;for(int id:displayControls()){controls.push_back({id,{969,y,260,54},videoControlEnabled(id)});y+=70;}}
            if(category==4){for(int i=0;i<5;++i)controls.push_back({260+i,{969,350+float(i)*70,260,54},backend.adjustmentsAvailable()});}
            if(category==5){controls.push_back({270,{969,350,260,54},gameVolumeEnabled()});controls.push_back({271,{969,420,260,54},backend.adjustmentsAvailable()});if(resetScoresPending){controls.push_back({272,{969,520,125,54},true});controls.push_back({273,{1104,520,125,54},true});}}
            if(category==launcherTab){
                std::array<int,5> ids{202,203,204,206,230};
                for(int i=0;i<5;++i)controls.push_back({ids[size_t(i)],{969,350+float(i)*70,260,54},true});
                controls.push_back({menuVolume,menuVolumeBox,true});controls.push_back({menuMute,menuMuteBox,true});
            }
            controls.push_back({212,{300,810,190,50},true});controls.push_back({211,{510,810,240,50},true});controls.push_back({210,{1000,810,235,50},true});
            const float shift=extraWidth()/2;
            for(auto& control:controls)control.box.x+=shift;
        }
        controls.push_back({10,rightAligned({982,28,148,58}),true});controls.push_back({11,rightAligned({1155,28,190,58}),settingsEnabled()});controls.push_back({12,rightAligned({1418,10,48,46}),true});controls.push_back({13,rightAligned({1472,10,48,46}),true});
    }
    void openSettings(){
        if(!settingsEnabled())return;
        editingGame=gameSelected()&&backend.selectGame(selected);
        if(editingGame){
            backend.load();musicAvailable=backend.remasteredAvailable();
            draft=backend.config;draftAdjustments=backend.adjustments;videoRemastered=selected==2?draft.mk3Engine==2:draft.remastered;
        }else category=launcherTab;
        draftLauncher=launcher;
        resetScoresPending=false;settings=true;details=false;focus=0;notice.clear();
        eventLog(backend.root(),"settings-open");
    }
    void selectTab(int tab){
        if(!settings||!tabEnabled(tab))return;
        category=tab;resetScoresPending=false;focus=0;
    }
    void close(){if(backend.running()){closing=true;backend.requestStop();notice=L"Encerrando o jogo e salvando o perfil...";ShowWindow(window,SW_RESTORE);}else DestroyWindow(window);}
    void borderless(bool on){
        if(on==fullscreen)return;
        if(on){GetWindowRect(window,&placement);MONITORINFO m{};m.cbSize=sizeof(m);GetMonitorInfoW(MonitorFromWindow(window,MONITOR_DEFAULTTONEAREST),&m);SetWindowLongPtrW(window,GWL_STYLE,WS_POPUP|WS_VISIBLE);SetWindowPos(window,HWND_TOP,m.rcMonitor.left,m.rcMonitor.top,m.rcMonitor.right-m.rcMonitor.left,m.rcMonitor.bottom-m.rcMonitor.top,SWP_FRAMECHANGED);}
        else{SetWindowLongPtrW(window,GWL_STYLE,WS_POPUP|WS_THICKFRAME|WS_MINIMIZEBOX|WS_MAXIMIZEBOX|WS_SYSMENU|WS_VISIBLE);SetWindowPos(window,nullptr,placement.left,placement.top,placement.right-placement.left,placement.bottom-placement.top,SWP_FRAMECHANGED|SWP_NOZORDER);}
        fullscreen=on;
    }
    int hit(float x,float y)const{for(auto i=controls.rbegin();i!=controls.rend();++i)if(i->box.contains(x,y))return i->id;return -1;}
    void move(POINT point){if(!graphics)return;hitTargets();graphics->mouse(point,mx,my);int next=hit(mx,my);dragSlider();if(next!=hover){hover=next;auto c=std::find_if(controls.begin(),controls.end(),[&](const Control& v){return v.id==next;});SetCursor(LoadCursorW(nullptr,c!=controls.end()&&c->enabled?IDC_HAND:IDC_ARROW));}invalidate();}
    int sliderValue(float x,float width=260)const{return std::clamp(int(std::lround((x-969-extraWidth()/2)*100/width)),0,100);}
    void setScaleAmount(float x){video().scalefxAmount=sliderValue(x);}
    void setGameVolume(float x){if(gameVolumeEnabled())draft.gameVolume=sliderValue(x);}
    void dragSlider(){
        if(!settings)return;
        if(pressed==256&&category==0&&draft.videoEffects&&scaleFxActive())setScaleAmount(mx);
        if(pressed==270&&category==5)setGameVolume(mx);
        if(pressed==menuVolume&&category==launcherTab)draftLauncher.musicVolume=sliderValue(mx,menuVolumeBox.w);
    }
    void changeAdjustment(int id,int step){
        if(!backend.adjustmentsAvailable())return;
        if(id==261||id==262){draftAdjustments=effectiveAdjustments();draft.cmosCoinage=true;}
        if(id==260)draftAdjustments.difficulty=(draftAdjustments.difficulty-1+step+5)%5+1;
        if(id==261){draftAdjustments.coinage=(draftAdjustments.coinage-1+step+58)%58+1;draftAdjustments.customCoinage=false;}
        if(id==262)draftAdjustments.freePlay=!draftAdjustments.freePlay;
        if(id==263)draft.blood=!draft.blood;
        if(id==264)draft.violence=!draft.violence;
    }
    void act(int id){
        hitTargets();
        auto it=std::find_if(controls.begin(),controls.end(),[&](const Control& c){return c.id==id;});if(it!=controls.end()&&!it->enabled)return;
        invalidate();
        if(id>=1&&id<=4){selectMachine(id-1);return;}
        if(id==30){chooseRomFolder();return;}
        if(id==10){settings=details=false;draft=backend.config;focus=chosen>=0?chosen:0;notice.clear();}
        if(id==11)openSettings();
        if(id==12)ShowWindow(window,SW_MINIMIZE);
        if(id==13)close();
        if(id==20&&!settings&&gameSelected()){
            if(menuMusic)menuMusic->pause();
            PlaySoundW(nullptr,nullptr,0);
            if(backend.launch()){notice=backend.status();eventLog(backend.root(),"game-start "+std::to_string(selected));}
            else{notice=backend.status();if(selected==2)mk3Available=false;eventLog(backend.root(),"game-start-error");}
        }
        if(id==21||id==230){auto logs=backend.root()/(id==230?L"logs":selected==2?L"logs/mk3-native":selected==1?L"logs/mk2-v1":L"logs/temporaria-8");rejectLinks(logs);fs::create_directories(logs);auto result=ShellExecuteW(window,L"open",logs.c_str(),nullptr,nullptr,SW_SHOWNORMAL);if(INT_PTR(result)<=32)notice=L"Nao foi possivel abrir a pasta de logs.";}
        if(id==103){details=false;notice.clear();}
        if(nativeVideo()&&(id==videoProfile||id==videoPage)){
            if(pressed==256){pressed=-1;if(window&&GetCapture()==window)ReleaseCapture();}
            if(id==videoProfile)videoRemastered=!videoRemastered;
            else draft.videoEffects=!draft.videoEffects;
        }
        if(id==videoScale&&nativeVideo())video().scaleMode=(video().scaleMode+1)%6;
        if(id==200)video().scanlines=(video().scanlines+1)%(nativeVideo()?int(mk5video::presets.size()):4);
        if(id==201)video().filter=(video().filter+1)%(nativeVideo()?4:2);
        if(id==202)draftLauncher.fps=draftLauncher.fps==30?60:(draftLauncher.fps==60?120:(draftLauncher.fps==120?240:30));
        if(id==245)draft.remastered=!draft.remastered;
        if(id==205)draft.audioLatency=draft.audioLatency==1?2:1;
        if(id==207)video().color=(video().color+1)%3;
        if(id==208)video().brightness=video().brightness==120?80:video().brightness+10;
        if(id==209)video().bezel=!video().bezel;
        if(id==255&&nativeVideo())video().scalefx=!video().scalefx;
        if(id==videoCas&&nativeVideo())video().cas=video().cas>=100?0:std::min(video().cas+25,100);
        if(id==videoSmaa&&nativeVideo())video().smaa=!video().smaa;
        if(id==videoBilateral&&nativeVideo())video().bilateral=video().bilateral>=100?0:std::min(video().bilateral+25,100);
        if(id==250)video().sync=nativeVideo()?(video().sync+1)%3:(video().sync==0?2:0);
        if(id==251&&nativeVideo())video().highRefresh=!video().highRefresh;
        if(id==videoFullscreen&&nativeVideo())video().fullscreen=!video().fullscreen;
        if(id==203)draftLauncher.vsync=!draftLauncher.vsync;
        if(id==204)draftLauncher.reducedMotion=!draftLauncher.reducedMotion;
        if(id==206)draftLauncher.fullscreen=!draftLauncher.fullscreen;
        if(id==menuMute&&settings&&category==launcherTab)draftLauncher.musicMuted=!draftLauncher.musicMuted;
        if(id>=260&&id<=264&&settings&&category==4)changeAdjustment(id,1);
        if(id==271&&settings&&category==5&&backend.adjustmentsAvailable()){resetScoresPending=true;notice=L"Redefinir o ranking salvo? Esta acao e imediata e nao pode ser desfeita.";}
        if(id==272&&settings&&category==5&&resetScoresPending){backend.resetHighScores();resetScoresPending=false;notice=backend.status();}
        if(id==273){resetScoresPending=false;notice.clear();}
        if(id==210&&settings){
            if(category==launcherTab){
                if(backend.saveLauncherPreferences(draftLauncher)){
                    launcher=draftLauncher;borderless(launcher.fullscreen);
                    notice=L"Preferencias do launcher salvas.";
                    eventLog(backend.root(),"launcher-settings-saved");
                }else notice=L"Falha ao salvar as preferencias do launcher.";
            }else if(editingGame){
                if(backend.saveAll(draft,draftAdjustments)){
                    draft=backend.config;draftAdjustments=backend.adjustments;
                    rememberEdition(selected);
                    eventLog(backend.root(),"settings-saved");
                }
                notice=backend.status();
            }
        }
        if(id==211&&settings){
            if(category==launcherTab){
                draftLauncher={};
                notice=L"Padroes do launcher restaurados na tela. Use SALVAR para aplicar.";
            }else if(category==0||category==2){
                video()=selected==2&&videoRemastered?mklauncher::mk3RemasteredDefaults():VideoConfig{};if(!nativeVideo())video().sync=2;
                notice=L"Perfil de video restaurado na tela. Use SALVAR para aplicar.";
            }else{
                const auto videos=draft.videos;
                const bool videoEffects=draft.videoEffects;
                const int mk3Engine=draft.mk3Engine;
                draft=Config{};draft.videos=videos;draft.videoEffects=videoEffects;draft.mk3Engine=mk3Engine;
                draftAdjustments=backend.adjustmentsAvailable()?GameAdjustments{}:backend.adjustments;
                resetScoresPending=false;
                notice=L"Padroes restaurados na tela. Use SALVAR para aplicar.";
            }
        }
        if(id==212){settings=false;draft=backend.config;focus=chosen>=0?chosen:0;notice.clear();}
        if(id>=220&&id<=225)selectTab(id-220);
    }
    std::vector<int> actions()const{
        if(!settings)return {1,2,3,4,20,11};
        std::vector<int> a;
        if(category==0)for(int id:videoControls()){if(videoControlEnabled(id))a.push_back(id);}
        else if(category==2)for(int id:displayControls()){if(videoControlEnabled(id))a.push_back(id);}
        else if(category==1){if(musicAvailable||draft.remastered)a.push_back(245);a.push_back(205);}
        else if(category==4){if(backend.adjustmentsAvailable())a={260,261,262,263,264};}
        else if(category==5){
            if(gameVolumeEnabled())a.push_back(270);
            if(backend.adjustmentsAvailable())a.push_back(271);
            if(resetScoresPending){a.push_back(272);a.push_back(273);}
        }else a={202,203,204,206,230,menuVolume,menuMute};
        a.insert(a.end(),{210,211,212});return a;
    }
    void key(WPARAM key){
        invalidate();if(key==VK_F11){borderless(!fullscreen);return;}
        if(key==VK_ESCAPE){if(fullscreen){borderless(false);eventLog(backend.root(),"fullscreen-exit-escape");return;}if(details){details=false;notice.clear();}else if(settings){settings=false;draft=backend.config;focus=chosen>=0?chosen:0;notice.clear();}else close();return;}
        if(key==VK_TAB){auto a=actions();focus=(focus+1)%int(a.size());return;}
        if(!settings&&!details){
            if(key==VK_LEFT||key==VK_RIGHT){focus=focus<4?(focus+(key==VK_LEFT?3:1))%4:(focus==4?5:4);}
            if(key==VK_DOWN)focus=focus<4?4:(focus==4?5:4);
            if(key==VK_UP)focus=focus>=4?(chosen>=0?chosen:0):5;
            if(key==VK_RETURN||key==VK_SPACE){auto a=actions();act(a[size_t(std::clamp(focus,0,int(a.size())-1))]);}
            if(key=='S'){openSettings();}
            if(key=='L'){act(21);}
        }else{
            auto a=actions();if(key==VK_UP)focus=(focus+int(a.size())-1)%int(a.size());if(key==VK_DOWN)focus=(focus+1)%int(a.size());focus=std::min(focus,int(a.size())-1);
            if(settings&&a[size_t(focus)]==256&&(key==VK_LEFT||key==VK_RIGHT)){video().scalefxAmount=std::clamp(video().scalefxAmount+(key==VK_LEFT?-5:5),0,100);return;}
            if(settings&&a[size_t(focus)]==270&&(key==VK_LEFT||key==VK_RIGHT)){draft.gameVolume=std::clamp(draft.gameVolume+(key==VK_LEFT?-5:5),0,100);return;}
            if(settings&&a[size_t(focus)]==menuVolume&&(key==VK_LEFT||key==VK_RIGHT)){draftLauncher.musicVolume=std::clamp(draftLauncher.musicVolume+(key==VK_LEFT?-5:5),0,100);return;}
            if(settings&&category==4&&(key==VK_LEFT||key==VK_RIGHT)&&a[size_t(focus)]>=260&&a[size_t(focus)]<=264){changeAdjustment(a[size_t(focus)],key==VK_LEFT?-1:1);return;}
            if(details&&(key==VK_LEFT||key==VK_RIGHT)){focus=(focus+1)%int(a.size());}
            const int id=a[size_t(focus)];const bool editable=(id>=200&&id<=209)||id==245||id==250||id==251||id==255||(id>=videoProfile&&id<=videoFullscreen);
            if(key==VK_RETURN||key==VK_SPACE||((key==VK_LEFT||key==VK_RIGHT)&&editable))act(id);
            if(key>='1'&&key<='6')selectTab(int(key-'1'));
        }
    }
    WORD padEdges(WORD buttons){
        if(!active){padReady=false;gamepadButtons=padDirections=0;return 0;}
        // A button held in the game or another app is not a new launcher action.
        if(!padReady){gamepadButtons=buttons;padDirections=0;padReady=buttons==0;return 0;}
        const WORD edge=buttons&~gamepadButtons;gamepadButtons=buttons;return edge;
    }
    void padActions(WORD edge){
        if(edge&XINPUT_GAMEPAD_B){if(settings){settings=false;draft=backend.config;focus=chosen>=0?chosen:0;notice.clear();}else if(details){details=false;notice.clear();}return;}
        for(auto pair:{std::pair<WORD,int>{XINPUT_GAMEPAD_DPAD_LEFT,VK_LEFT},{XINPUT_GAMEPAD_DPAD_RIGHT,VK_RIGHT},{XINPUT_GAMEPAD_DPAD_UP,VK_UP},{XINPUT_GAMEPAD_DPAD_DOWN,VK_DOWN},{WORD(XINPUT_GAMEPAD_A|XINPUT_GAMEPAD_START),VK_RETURN},{XINPUT_GAMEPAD_Y,'S'}})if(edge&pair.first)key(WPARAM(pair.second));
        if(edge&(XINPUT_GAMEPAD_LEFT_SHOULDER|XINPUT_GAMEPAD_RIGHT_SHOULDER)){if(settings)selectTab((category+((edge&XINPUT_GAMEPAD_RIGHT_SHOULDER)?1:5))%6);else openSettings();}
    }
    void pad(){
        if(!active){padReady=false;gamepadButtons=0;return;}
        const auto now=GetTickCount64();if(now<nextPad)return;nextPad=now+4;pads.poll();XINPUT_STATE state{};bool found=false;
        for(unsigned i=0;i<4;++i)if(pads.connected[i]){state=pads.states[i];found=true;break;}
        if(!found){padReady=false;gamepadButtons=0;padDirections=0;return;}
        WORD buttons=state.Gamepad.wButtons;if(state.Gamepad.sThumbLX<-18000)buttons|=XINPUT_GAMEPAD_DPAD_LEFT;if(state.Gamepad.sThumbLX>18000)buttons|=XINPUT_GAMEPAD_DPAD_RIGHT;if(state.Gamepad.sThumbLY>18000)buttons|=XINPUT_GAMEPAD_DPAD_UP;if(state.Gamepad.sThumbLY<-18000)buttons|=XINPUT_GAMEPAD_DPAD_DOWN;
        WORD edge=padEdges(buttons);if(!padReady)return;
        const WORD direction=buttons&0x000f;if(direction!=padDirections){padDirections=direction;nextPadRepeat=now+350;}else if(direction&&now>=nextPadRepeat){edge|=direction;nextPadRepeat=now+90;}
        padActions(edge);
    }
    void poll(){
        const auto now=GetTickCount64();
        if(now<nextPoll)return;
        nextPoll=now+200;bool was=backend.running();backend.poll();
        if(availability.valid()&&availability.wait_for(std::chrono::seconds(0))==std::future_status::ready){
            const auto ready=availability.get();
            mk1Available=ready[0];mk2Available=ready[1];mk3Available=ready[2];
        }
        if(!backend.running()&&!availability.valid()&&now>=availabilityDue){
            // Native availability hashes the executable and ROMs.
            availability=std::async(std::launch::async,[root=backend.root()]{
                Backend probe(root);
                return std::array<bool,3>{probe.available(0),probe.available(1),probe.available(2)};
            });
            musicAvailable=backend.remasteredAvailable();
            availabilityDue=now+10000;
        }
        if(was&&!backend.running()){ShowWindow(window,SW_RESTORE);SetForegroundWindow(window);restoring=false;notice=backend.status();eventLog(backend.root(),"game-return exit="+std::to_string(backend.exitCode()));if(closing)DestroyWindow(window);}
        if(backend.running()&&backend.gameWindow()&&!restoring&&!closing){restoring=true;ShowWindow(window,SW_MINIMIZE);SetForegroundWindow(backend.gameWindow());}
        if(closing&&backend.running())backend.requestStop();
    }
    void center(const std::wstring& text,float x,float y,float size,Color color,float tracking=0){graphics->text(text,x-graphics->textWidth(text,size,tracking)/2,y,size,color,tracking);}
    void control(int id,Rect box,const std::wstring& label,bool enabled=true,bool chosen=false,float size=18){
        controls.push_back({id,box,enabled});bool over=hover==id,down=pressed==id,focused=drawnFocus==id;
        Color fill=chosen?Color{.22f,.025f,.025f,.95f}:Color{.018f,.028f,.048f,.95f};if((over||focused)&&enabled)fill={.19f,.038f,.035f,.96f};if(down&&enabled)fill={.36f,.06f,.035f,1};
        graphics->fill(box,fill);auto edge=enabled&&(chosen||over||focused)?red:Color{.15f,.20f,.29f,.85f};
        graphics->line(box.x,box.y+box.h,box.x+box.w,box.y+box.h,chosen||focused?2.f:1.f,edge);
        center(label,box.x+box.w/2,box.y+(box.h-size*1.15f)/2,size,enabled?white:muted,1.2f);
    }
    void icon(int which,float x,float y,Color c){
        auto& g=*graphics;
        if(which==0){g.triangle(x,y+11,x+12,y,x+24,y+11,c);g.fill({x+4,y+10,16,14},c);g.fill({x+10,y+15,5,9},{.04f,.01f,.01f,1});}
        if(which==1){for(int i=0;i<8;++i){float a=float(i)*3.14159265f/4;g.line(x+12+std::cos(a)*6,y+12+std::sin(a)*6,x+12+std::cos(a)*12,y+12+std::sin(a)*12,5,c);}g.fill({x+5,y+5,14,14},c);g.fill({x+9,y+9,6,6},{.015f,.02f,.035f,1});}
    }
    const wchar_t* missing(int game)const{return backend.setupFinished(game)?L"ARQUIVOS AUSENTES":L"SETUP PENDENTE";}
    static Rect cabinetScreen(Rect r){return {r.x+r.w*.14f,r.y+168,r.w*.72f,152};}
    // Start-screen background drawn in code: night gradient, floor and perspective lines.
    void backdrop(float width){
        auto& g=*graphics;
        for(int n=0;n<32;++n){const float k=float(n)/31;g.fill({0,float(n)*32,width,33},{.010f+.020f*k,.013f+.002f*k,.030f-.008f*k,1});}
        g.fill({0,700,width,324},{.010f,.009f,.016f,1});g.line(0,700,width,700,1,{.30f,.07f,.09f,.8f});
        for(int n=-6;n<=18;++n){const float x=width*float(n)/12;g.line(width/2,560,x,1024,1,{.12f,.16f,.30f,.25f});}
        for(int n=0;n<6;++n){const float y=700+float(n*n)*9;g.line(0,y,width,y,1,{.10f,.13f,.24f,.22f});}
    }
    // Arcade cabinet drawn in code: body, side trims, marquee with the game's name, screen bezel, panel and base.
    void cabinet(int i,Rect r,Color hue,float shade){
        auto& g=*graphics;auto tone=[&](float v){return Color{v*shade,v*shade*1.03f,v*shade*1.15f,1};};
        const float cx=r.x+r.w/2;
        g.fill({r.x+r.w*.06f,r.y+40,r.w*.88f,r.h-82},tone(.060f));
        g.fill({r.x+r.w*.02f,r.y+40,r.w*.05f,r.h-82},tone(.095f));g.fill({r.x+r.w*.93f,r.y+40,r.w*.05f,r.h-82},tone(.095f));
        const Rect marquee{r.x+r.w*.08f,r.y+52,r.w*.84f,72};
        g.fill(marquee,{hue.r*.28f*shade,hue.g*.28f*shade,hue.b*.28f*shade,1});
        g.line(marquee.x,marquee.y+marquee.h,marquee.x+marquee.w,marquee.y+marquee.h,2,{hue.r,hue.g,hue.b,.85f});
        const std::wstring name=compatibleGames[size_t(i)].name;
        const float size=std::min(17.f,marquee.w*.9f/std::max(1.f,g.textWidth(name,1,.6f)));
        center(name,cx,marquee.y+(marquee.h-size*1.15f)/2,size,white,.6f);
        g.fill({r.x+r.w*.10f,r.y+150,r.w*.80f,188},tone(.022f));
        const Rect panel{r.x+r.w*.03f,r.y+398,r.w*.94f,66};
        g.triangle(panel.x,panel.y+panel.h,panel.x+panel.w*.08f,panel.y,panel.x+panel.w*.92f,panel.y,tone(.11f));
        g.triangle(panel.x,panel.y+panel.h,panel.x+panel.w*.92f,panel.y,panel.x+panel.w,panel.y+panel.h,tone(.11f));
        for(int b=0;b<6;++b)g.fill({panel.x+panel.w*(.20f+.11f*float(b)),panel.y+28,10,10},{hue.r,hue.g,hue.b,.85f});
        g.fill({r.x+r.w*.08f,r.y+464,r.w*.84f,150},tone(.045f));
        g.fill({cx-26,r.y+512,52,34},tone(.018f));g.fill({cx-4,r.y+520,8,18},{hue.r*.6f,hue.g*.6f,hue.b*.6f,1});
        g.fill({r.x+r.w*.04f,r.y+614,r.w*.92f,18},tone(.03f));
    }
    void header(){
        auto& g=*graphics;Color metal{.004f,.007f,.018f,.985f};const float extra=extraWidth(),width=layoutWidth();
        g.fill({0,0,width,87},metal);g.fill({0,87,615,42},metal);g.triangle(615,87,660,87,615,129,metal);g.triangle(615,0,748,0,660,87,metal);
        g.line(0,129,615,129,1,{.37f,.05f,.07f,1});g.line(615,129,716,28,1,{.16f,.23f,.36f,1});g.line(716,28,1376+extra,28,1,{.12f,.17f,.27f,1});g.line(660,87,width,87,1,{.23f,.06f,.13f,1});
        g.text(productTitle,84,30,30,white,3);g.line(84,80,504,80,1,red);g.text(L"RECOMPILACAO LOCAL A PARTIR DAS SUAS ROMS",86,92,9,muted,1.2f);
        control(10,rightAligned({982,28,148,58}),L"HOME",true,!settings,18);icon(0,994+extra,45,!settings?red:muted);
        control(11,rightAligned({1155,28,190,58}),L"SETTINGS",settingsEnabled(),settings,18);icon(1,1174+extra,45,settings?red:muted);
        controls.push_back({12,rightAligned({1418,10,48,46}),true});controls.push_back({13,rightAligned({1472,10,48,46}),true});
        g.line(1437+extra,34,1454+extra,34,2,hover==12?white:muted);Color cross=hover==13?red:muted;g.line(1490+extra,27,1505+extra,42,2,cross);g.line(1505+extra,27,1490+extra,42,2,cross);
    }
    void scene(float dt,bool deterministic){
        auto& g=*graphics;float t=deterministic||launcher.reducedMotion?0:float(frameTicks()-started)/ticksPerSecond;
        const float width=layoutWidth();
        backdrop(width);
        if(!launcher.reducedMotion){
            for(float anchor:{-13.f,1035.f,1427.f,405.f}){float x=anchor*width/baseWidth,y=anchor==405||anchor==1035?250.f:365.f;g.quad(0,{x-35,y+10,150,220},{0,0,1,1},{1,.24f,.02f,.12f+.025f*std::sin(t*2+x)},5,t);g.quad(0,{x,y,95,140},{0,0,1,1},{1,1,1,.38f},1,t+x);}
            g.quad(0,{0,520,width,280},{0,0,1,1},{.17f,.18f,.45f,.18f},2,t);
            for(int i=0;i<22;++i){float x=std::fmod(float(i*173)+t*(3+i%4),width),y=790-std::fmod(float(i*47)+t*(12+i%9),550.f);float a=.12f+.13f*std::sin(float(i)+t);g.fill({x,y,1.5f,1.5f},{1,.35f,.09f,a});}
        }
        for(int i=0;i<4;++i){
            float target=!settings&&!details&&(chosen==i||hover==i+1||focus==i)?1.f:0.f;glows[size_t(i)]+=std::clamp(dt*7,0.f,1.f)*(target-glows[size_t(i)]);float glow=deterministic?0:glows[size_t(i)];
            Rect r=positions[size_t(i)];const float shift=cabinetShift(i);r.x+=shift;float lift=launcher.reducedMotion?0:glow*3;r.y-=lift;
            Color hue=i<2?red:(i==2?blue:Color{.7f,.12f,1,1});
            g.quad(0,{r.x-55,660,r.w+110,235},{0,0,1,1},{hue.r,hue.g,hue.b,.13f+glow*.12f},5,t);
            // Cabinet drawn in code (no image file): body, marquee with the game's name, screen, panel and base.
            float shade=i==0?1.f:.71f;shade+=glow*.17f;cabinet(i,r,hue,shade);
            if(i<3){
                Rect screen=cabinetScreen(r);g.fill(screen,{.012f,.018f,.03f,1});g.quad(0,screen,{0,0,1,1},{.5f,.7f,1,1},4,t);
                center(ready(i)?L"PRONTO PARA JOGAR":backend.setupFinished(i)?L"ARQUIVOS AUSENTES":L"SETUP PENDENTE",screen.x+screen.w/2,screen.y+screen.h/2-8,9,ready(i)?gold:muted,1.4f);
            }else{
                const Rect screen=cabinetScreen(r);g.fill(screen,{.012f,.018f,.03f,1});
                center(L"EM BREVE",screen.x+screen.w/2,screen.y+screen.h/2-20,16,{.45f,.46f,.55f,1},2.2f);center(L"JOGO INDISPONIVEL",screen.x+screen.w/2,screen.y+screen.h/2+7,8,muted,1);
            }
            if(glow>.01f){g.line(r.x+20,831-lift,r.x+r.w-15,831-lift,2,{hue.r,hue.g,hue.b,glow*.8f});}
            if(!settings&&!details){controls.push_back({i+1,{r.x,r.y+15,r.w,680},!backend.running()});if(chosen==i)g.line(r.x+20,831-lift,r.x+r.w-15,831-lift,3,gold);}
            Rect badge{r.x+30,848,r.w-60,28};g.fill(badge,{.006f,.009f,.022f,.85f});center(i==0?(mk1Available?(mk1Remastered?L"REMASTERIZADA  /  DISPONIVEL":L"ORIGINAL ARCADE  /  DISPONIVEL"):missing(0)):i==1?(mk2Available?(mk2Remastered?L"REMASTERIZADA  /  DISPONIVEL":L"ORIGINAL ARCADE  /  DISPONIVEL"):missing(1)):i==2?(ready(2)?mk3Edition():missing(2)):L"EM BREVE",badge.x+badge.w/2,badge.y+6,10,i<3?gold:muted,1.3f);
        }
        if(!deterministic&&!launcher.reducedMotion){float fade=1-t/.65f;if(fade>0&&!receivedInput)g.fill({0,130,width,790},{0,0,0,std::clamp(fade,0.f,1.f)});}
    }
    void footer(){
        auto& g=*graphics;const float width=layoutWidth(),extra=extraWidth();
        g.fill({0,919,width,105},{.003f,.006f,.015f,.99f});g.line(0,919,width,919,1,{.08f,.21f,.4f,1});
        g.line(0,939,393,939,1,{.13f,.22f,.37f,1});g.line(393,939,438,983,1,{.13f,.22f,.37f,1});g.line(438,983,1122+extra,983,1,{.13f,.22f,.37f,1});g.line(1122+extra,983,1188+extra,919,1,{.13f,.22f,.37f,1});
        g.text(productTitle,36,928,10,muted,1.2f);
        // Legal notice, always visible on the start screen (launcher_legal.hpp).
        for(size_t n=0;n<legalNotice.size();++n)g.text(legalNotice[n],36,947+float(n)*15,8,{.48f,.52f,.62f,1},.2f);
        if(!settings)control(30,{560,930,230,34},backend.setupRunning()?L"SETUP EM CURSO...":L"PASTA DE ROMS / SETUP",!backend.running()&&!backend.setupRunning(),false,11);
        center(L"SETAS / D-PAD: NAVEGAR   ENTER / A: SELECIONAR / ALTERNAR   BAIXO: JOGAR   S / Y: SETTINGS",width/2,1004,8,{.36f,.42f,.54f,1},.7f);
        if(!settings&&!details&&chosen>=0){
            center(chosen==2?mk3Edition():chosen<3?(backend.config.remastered?L"REMASTERIZADA":L"ORIGINAL ARCADE"):L"EM BREVE",1359+extra,925,10,gold,1);
            control(20,rightAligned({1229,942,260,48}),backend.running()?L"EM EXECUCAO":gameSelected()?L"JOGAR":L"INDISPONIVEL",gameSelected(),true,18);
        }
    }
    void row(int id,float y,const std::wstring& title,const std::wstring& description,const std::wstring& value,bool enabled=true){
        auto& g=*graphics;const float shift=extraWidth()/2;
        g.line(300+shift,y+65,1235+shift,y+65,1,{.10f,.14f,.22f,1});g.text(title,306+shift,y+5,18,enabled?white:muted,1);g.text(description,306+shift,y+32,12,muted,.4f);control(id,{969+shift,y,260,54},value,enabled,false,15);
    }
    void settingsPanel(){
        auto& g=*graphics;const float shift=extraWidth()/2;
        g.fill({0,130,layoutWidth(),789},{.003f,.005f,.013f,.70f});g.fill({240+shift,182,1056,701},{.007f,.012f,.024f,.97f});g.triangle(240+shift,182,290+shift,157,580+shift,182,{.10f,.016f,.025f,1});g.line(240+shift,182,1296+shift,182,2,red);g.line(240+shift,883,1296+shift,883,1,{.26f,.06f,.09f,1});
        const auto* videoEdition=videoRemastered?L"REMASTERIZADA":L"ORIGINAL ARCADE";
        const auto* headingEdition=category==0||category==2?videoEdition:(draft.remastered?L"REMASTERIZADA":L"ORIGINAL ARCADE");
        g.text(L"COLLECTION SETTINGS",300+shift,217,31,white,2);
        const std::wstring subtitle=category==launcherTab
            ?(editingGame?L"PREFERENCIAS DA COLECAO":L"PREFERENCIAS DA COLECAO  /  SELECIONE UM GABINETE PARA AJUSTAR UM JOGO")
            :selected==2?std::wstring(compatibleGames[2].name)+L"  /  "+mk3Edition()
            :std::wstring(compatibleGames[size_t(selected==1)].name)+L"  /  "+headingEdition;
        g.text(subtitle,302+shift,260,12,gold,2);
        for(int i=0;i<6;++i)control(220+i,{300+shift+float(i)*156,294,156,40},std::array<std::wstring,6>{L"VIDEO",L"AUDIO",L"DISPLAY",L"LAUNCHER",L"AJUSTES",L"UTILITARIOS"}[size_t(i)],tabEnabled(i),category==i,13);
        if(category==0){
            row(videoProfile,350,L"PERFIL DE VIDEO",selected==2?L"Escolhe qual perfil editar. A edicao do MK3 e escolhida no gabinete.":L"Escolhe qual perfil editar. A versao de jogo e definida na aba Audio.",videoEdition,nativeVideo());
            row(videoPage,410,L"CONTROLES DE VIDEO",L"Alterne entre escala e filtros adicionais.",draft.videoEffects?L"EFEITOS":L"ESCALA E CRT",nativeVideo());
            const auto& v=video();
            if(draft.videoEffects){
                row(255,470,L"SCALEFX",L"Reconstrucao de contornos em 3x.",v.scalefx?L"ATIVADO":L"DESATIVADO");
                g.text(L"INTENSIDADE SCALEFX",306+shift,535,18,scaleFxActive()?white:muted,1);
                g.text(std::to_wstring(v.scalefxAmount)+L"%",720+shift,535,18,scaleFxActive()?gold:muted,1);
                controls.push_back({256,{969+shift,530,260,54},scaleFxActive()});
                const bool focused=drawnFocus==256;
                const float amount=260.f*v.scalefxAmount/100;
                g.fill({969+shift,553,260,6},{.12f,.16f,.23f,1});
                g.fill({969+shift,553,amount,6},scaleFxActive()?red:muted);
                g.fill({965+shift+amount,545,8,22},scaleFxActive()?(focused?gold:white):muted);
                row(videoCas,590,L"NITIDEZ ADAPTATIVA CAS",L"Realca detalhes da imagem do jogo.",v.cas?std::to_wstring(v.cas)+L"%":L"DESATIVADO");
                row(videoSmaa,650,L"SMAA 1X",L"Suaviza diagonais e contornos de alto contraste.",v.smaa?L"ATIVADO":L"DESATIVADO");
                row(videoBilateral,710,L"FILTRO BILATERAL",L"Suaviza cores proximas no quadro, inclusive nos sprites.",v.bilateral?std::to_wstring(v.bilateral)+L"%":L"DESATIVADO");
            }else{
                constexpr std::array<const wchar_t*,6> scales{L"AJUSTAR 4:3",L"INTEIRA / AUTO",L"INTEIRA / 2X",L"INTEIRA / 3X",L"INTEIRA / 4X",L"LINHAS INTEIRAS 4:3"};
                constexpr std::array<const wchar_t*,4> filters{L"PIXELS NITIDOS",L"BILINEAR",L"BILINEAR NITIDO",L"BICUBICO"};
                row(videoScale,470,L"ESCALA DA IMAGEM",L"Escala inteira usa o maior fator disponivel se a escolha nao couber.",scales[size_t(v.scaleMode)],nativeVideo());
                row(201,530,L"FILTRO DE AMPLIACAO",L"Amostragem da imagem para a resolucao de saida.",filters[size_t(v.filter)]);
                row(200,590,L"CRT E SCANLINES",L"Escolha o feixe, a mascara e as linhas do monitor arcade.",mk5video::presets[size_t(v.scanlines)].label);
                row(207,650,L"CORES",L"Ajuste opcional de saida.",std::array<std::wstring,3>{L"ORIGINAL",L"VIVAS",L"QUENTE"}[size_t(v.color)]);
                row(208,710,L"BRILHO",L"100% usa o ganho original de saida.",std::to_wstring(v.brightness)+L"%");
            }
        }else if(category==1){
            // D7: the MK3 Remastered edition has no remastered music.
            if(selected==2)row(245,350,L"AUDIO DO MK3",L"Remasterizada: video remasterizado, audio original do arcade.",L"ORIGINAL ARCADE",false);
            else row(245,350,L"VERSAO PADRAO DO JOGO",L"Escolha e use SALVAR para iniciar sempre nesta versao.",draft.remastered?L"REMASTERIZADA":L"ORIGINAL ARCADE",musicAvailable||draft.remastered);
            row(205,420,L"FILA DE AUDIO",selected==2?L"Equilibrada: 80 ms nas duas edicoes. Segura: 140 ms.":L"Equilibrada: Original 80 ms / Remasterizada 140 ms. Segura: 140 ms.",std::array<std::wstring,3>{L"BAIXA / 40 ms",L"EQUILIBRADA",L"SEGURA / 140 ms"}[size_t(draft.audioLatency)]);
            row(243,490,L"VOZES E EFEITOS ARCADE",L"Vozes, golpes e efeitos preservados nas duas versoes.",L"ORIGINAIS",false);
            row(244,560,L"RESERVA DO AUDIO",L"Margem contra atrasos do sistema; nenhuma amostra e descartada.",draft.remastered||draft.audioLatency==2?L"140 ms":L"80 ms",false);
            row(246,630,L"ENHANCED AUDIO",L"Processamento adicional de audio nao integrado.",L"INDISPONIVEL",false);
            g.text(L"O volume do Windows continua controlando a saida do jogo.",306+shift,723,13,muted,.2f);
        }else if(category==2){
            const auto& v=video();
            row(videoProfile,350,L"PERFIL DE VIDEO",L"Escolhe qual perfil de exibicao editar.",videoEdition,nativeVideo());
            row(250,420,L"SINCRONIZACAO DO JOGO",L"VRR requer G-Sync / FreeSync ativo no monitor e no driver.",std::array<std::wstring,3>{L"V-SYNC",L"VRR / ADAPTATIVO",L"IMEDIATO"}[size_t(v.sync)]);
            row(251,490,L"ALTA FREQUENCIA",L"Reapresenta quadros originais na frequencia do desktop.",nativeVideo()?(v.highRefresh?L"ATIVADA":L"DESATIVADA"):L"INDISPONIVEL",nativeVideo());
            row(209,560,L"MOLDURA ARCADE",L"Moldura neon vermelha ao redor da imagem do jogo.",v.bezel?L"ATIVADA":L"DESATIVADA");
            row(videoFullscreen,630,L"TELA CHEIA DO JOGO",L"Define o modo da janela ao iniciar esta versao.",v.fullscreen?L"ATIVADA":L"JANELA",nativeVideo());
            g.text(L"XInput: "+std::to_wstring(pads.count())+L" conectado(s). Arcade: 54,7069 quadros por segundo.",306+shift,723,13,muted,.2f);
        }else if(category==4){
            const bool ready=backend.adjustmentsAvailable();const auto effective=effectiveAdjustments();auto priced=effective;priced.freePlay=false;
            row(260,350,L"COMPUTER DIFFICULTY",L"Nivel nativo da inteligencia artificial do arcade.",std::array<std::wstring,5>{L"VERY EASY",L"EASY",L"MEDIUM",L"HARD",L"VERY HARD"}[size_t(std::clamp(draftAdjustments.difficulty,1,5)-1)],ready);
            row(261,420,L"COINAGE",L"Preset / creditos para iniciar / continuar. Bonus e minimos originais.",backend.coinageLabel(priced),ready);
            row(262,490,L"FREE PLAY",L"Permite iniciar sem fichas pelo ajuste original do jogo.",effective.freePlay?L"ATIVADO":L"DESATIVADO",ready);
            row(263,560,L"BLOOD",L"DIP switch original de sangue do gabinete.",draft.blood?L"ATIVADO":L"DESATIVADO",ready);
            row(264,630,L"VIOLENCE",L"DIP switch original de violencia do gabinete.",draft.violence?L"ATIVADA":L"DESATIVADA",ready);
            g.text(ready?L"SALVAR aplica os ajustes ao proximo inicio deste jogo.":L"Inicie o jogo para criar o perfil; CMOS e ROMs precisam ser validos.",306+shift,723,13,muted,.2f);
        }else if(category==5){
            row(270,350,L"VOLUME ADJUST",gameVolumeEnabled()?L"Volume por software de musica, vozes e efeitos deste jogo.":L"Controle por jogo disponivel no motor nativo.",gameVolumeEnabled()?std::to_wstring(draft.gameVolume)+L"%":L"INDISPONIVEL",gameVolumeEnabled());
            g.fill({969+shift,408,260,4},{.12f,.16f,.23f,1});g.fill({969+shift,408,260.f*draft.gameVolume/100,4},red);
            row(271,420,L"RESET HIGH SCORES",L"Redefine os recordes pela rotina original; preserva os ajustes.",L"REDEFINIR RANKING",backend.adjustmentsAvailable());
            if(resetScoresPending){g.text(L"Apagar o ranking salvo deste jogo?",306+shift,535,16,gold,.2f);control(272,{969+shift,520,125,54},L"CONFIRMAR",true,false,12);control(273,{1104+shift,520,125,54},L"CANCELAR",true,false,12);}
            g.text(L"A limpeza do ranking e uma acao separada de SALVAR e RESTAURAR PADROES.",306+shift,723,13,muted,.2f);
        }else{
            row(202,350,L"LIMITE DE FPS DO LAUNCHER",L"Sem foco: 10 FPS. Minimizado: renderizacao suspensa.",std::to_wstring(draftLauncher.fps)+L" FPS");
            row(203,420,L"V-SYNC DO LAUNCHER",L"Sincroniza a apresentacao da colecao com o monitor.",draftLauncher.vsync?L"ATIVADO":L"DESATIVADO");
            row(204,490,L"REDUZIR MOVIMENTO",L"Desliga fogo, nevoa, particulas e abertura animada.",draftLauncher.reducedMotion?L"ATIVADO":L"DESATIVADO");
            row(206,560,L"TELA CHEIA DO LAUNCHER",L"Inicia em tela cheia. Esc volta a janela; F11 alterna.",draftLauncher.fullscreen?L"ATIVADA":L"JANELA");
            row(230,630,L"REGISTROS DE TESTE",L"Abre a pasta de logs da colecao.",L"ABRIR LOGS");
            g.text(L"VOLUME DA MUSICA DO MENU",306+shift,705,18,white,1);
            g.text(L"Ajuste apenas a trilha do launcher. Use SALVAR para manter.",306+shift,732,12,muted,.4f);
            auto volumeBox=menuVolumeBox,muteBox=menuMuteBox;volumeBox.x+=shift;muteBox.x+=shift;
            control(menuVolume,volumeBox,std::to_wstring(draftLauncher.musicVolume)+L"%",true,false,15);
            g.fill({volumeBox.x,746,volumeBox.w,4},{.12f,.16f,.23f,1});
            g.fill({volumeBox.x,746,volumeBox.w*draftLauncher.musicVolume/100,4},draftLauncher.musicMuted?muted:red);
            control(menuMute,muteBox,draftLauncher.musicMuted?L"REATIVAR":L"SILENCIAR",true,draftLauncher.musicMuted,12);
        }
        control(212,{300+shift,810,190,50},L"VOLTAR",true,false,14);control(211,{510+shift,810,240,50},L"RESTAURAR PADROES",true,false,13);control(210,{1000+shift,810,235,50},L"SALVAR",true,true,16);
        if(!notice.empty())g.text(notice.substr(0,105),306+shift,769,12,gold,.1f);
    }
    void draw(float dt,bool deterministic=false){
        const auto a=actions();
        drawnFocus=size_t(focus)<a.size()?a[size_t(focus)]:-1;
        controls.clear();graphics->bezel(settings?video().bezel:backend.config.video().bezel);graphics->begin();scene(dt,deterministic);footer();if(settings)settingsPanel();header();
        const float width=layoutWidth();
        if(!settings&&!details&&!notice.empty()){graphics->fill({(width-860)/2,883,860,30},{.006f,.01f,.02f,.93f});center(notice.substr(0,112),width/2,891,12,gold,.2f);}
        if(closing){graphics->fill({0,130,width,789},{0,0,0,.65f});center(L"ENCERRANDO O JOGO E SALVANDO O PERFIL...",width/2,480,22,white,1);}
        graphics->end(launcher.vsync);
    }
    static LRESULT CALLBACK procedure(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp){
        auto* self=reinterpret_cast<App*>(GetWindowLongPtrW(hwnd,GWLP_USERDATA));if(msg==WM_NCCREATE){self=static_cast<App*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);self->window=hwnd;SetWindowLongPtrW(hwnd,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(self));}
        if(!self)return DefWindowProcW(hwnd,msg,wp,lp);
        try{
            switch(msg){
            case WM_CLOSE:self->close();return 0;
            case WM_DESTROY:PostQuitMessage(0);return 0;
            case WM_ERASEBKGND:return 1;
            case WM_PAINT:{PAINTSTRUCT ps{};BeginPaint(hwnd,&ps);EndPaint(hwnd,&ps);return 0;}
            case WM_GETMINMAXINFO:{auto* m=reinterpret_cast<MINMAXINFO*>(lp);m->ptMinTrackSize={768,512};return 0;}
            case WM_ACTIVATEAPP:self->active=wp!=0;self->pressed=-1;self->gamepadButtons=0;self->padReady=false;return 0;
            case WM_CAPTURECHANGED:self->pressed=-1;return 0;
            case WM_KILLFOCUS:self->pressed=-1;self->gamepadButtons=0;self->padReady=false;return 0;
            case WM_DPICHANGED:{auto* r=reinterpret_cast<RECT*>(lp);SetWindowPos(hwnd,nullptr,r->left,r->top,r->right-r->left,r->bottom-r->top,SWP_NOZORDER|SWP_NOACTIVATE);return 0;}
            case WM_NCCALCSIZE:return 0;
            case WM_NCHITTEST:{LRESULT hit=DefWindowProcW(hwnd,msg,wp,lp);if(hit!=HTCLIENT)return hit;POINT pt{GET_X_LPARAM(lp),GET_Y_LPARAM(lp)};ScreenToClient(hwnd,&pt);if(!self->fullscreen){RECT r{};GetClientRect(hwnd,&r);int b=6;if(pt.x<b)return pt.y<b?HTTOPLEFT:(pt.y>=r.bottom-b?HTBOTTOMLEFT:HTLEFT);if(pt.x>=r.right-b)return pt.y<b?HTTOPRIGHT:(pt.y>=r.bottom-b?HTBOTTOMRIGHT:HTRIGHT);if(pt.y<b)return HTTOP;if(pt.y>=r.bottom-b)return HTBOTTOM;}
                if(self->graphics){float x=0,y=0;self->graphics->mouse(pt,x,y);if(y<87&&self->hit(x,y)<0)return HTCAPTION;}return HTCLIENT;}
            case WM_MOUSEMOVE:self->move({GET_X_LPARAM(lp),GET_Y_LPARAM(lp)});return 0;
            case WM_LBUTTONDOWN:self->move({GET_X_LPARAM(lp),GET_Y_LPARAM(lp)});self->pressed=self->hit(self->mx,self->my);self->dragSlider();SetCapture(hwnd);return 0;
            case WM_LBUTTONUP:{self->move({GET_X_LPARAM(lp),GET_Y_LPARAM(lp)});int action=self->hit(self->mx,self->my),down=self->pressed;self->pressed=-1;ReleaseCapture();if(action==down&&action>=0)self->act(action);return 0;}
            case WM_KEYDOWN:if(!(lp&(1LL<<30)))self->key(wp);return 0;
            case WM_SYSCOMMAND:if((wp&0xfff0)==SC_KEYMENU)return 0;break;
            }
        }catch(const std::exception& e){self->notice=L"Erro: "+widen(e.what());try{eventLog(self->backend.root(),"ui-error "+std::string(e.what()));}catch(...){}}
        return DefWindowProcW(hwnd,msg,wp,lp);
    }
};

int diagnostics(const fs::path& root,const std::vector<std::wstring>& args){
    wchar_t system[MAX_PATH];if(!GetSystemDirectoryW(system,MAX_PATH))throw std::runtime_error("system path");auto powershell=fs::path(system)/L"WindowsPowerShell/v1.0/powershell.exe";
    std::vector<std::wstring> command={powershell.wstring(),L"-NoLogo",L"-NoProfile",L"-NonInteractive",L"-ExecutionPolicy",L"Bypass",L"-WindowStyle",L"Hidden",L"-File",(root/L"build/native/manual-temporary-8-20261025/product/session.ps1").wstring(),L"-ProjectRoot",root.wstring()};
    fs::path log=root/L"logs/temporaria-8/launcher-diagnostic.log";
    for(size_t i=0;i<args.size();++i){std::wstring flag;if(args[i]==L"--game-mode")flag=L"-GameMode";else if(args[i]==L"--smoke-frames")flag=L"-WindowFrames";else if(args[i]==L"--data-root")flag=L"-DataRoot";else if(args[i]==L"--plan-output")flag=L"-PlanOutput";else if(args[i]==L"--visual-mode")flag=L"-VisualMode";else if(args[i]==L"--scanlines")flag=L"-Scanlines";else if(args[i]==L"--filter")flag=L"-Filter";else if(args[i]==L"--scalefx")flag=L"-ScaleFX";else if(args[i]==L"--scale-mode")flag=L"-ScaleMode";else if(args[i]==L"--cas")flag=L"-Cas";else if(args[i]==L"--bilateral")flag=L"-Bilateral";else if(args[i]==L"--smaa")flag=L"-Smaa";else if(args[i]==L"--game-fullscreen")flag=L"-GameFullscreen";else if(args[i]==L"--crt-preset")flag=L"-CrtPreset";else if(args[i]==L"--sync")flag=L"-SyncMode";else if(args[i]==L"--color")flag=L"-ColorMode";else if(args[i]==L"--brightness")flag=L"-Brightness";else if(args[i]==L"--bezel")flag=L"-Bezel";else if(args[i]==L"--high-refresh")flag=L"-HighRefresh";else if(args[i]==L"--audio-latency")flag=L"-AudioLatency";else throw std::runtime_error("unknown diagnostic argument");if(i+1>=args.size())throw std::runtime_error("missing diagnostic argument");command.push_back(flag);command.push_back(args[++i]);if(flag==L"-PlanOutput")log=args[i]+L".launcher.log";}
    std::wstring line;for(auto& s:command){if(!line.empty())line+=L' ';line+=quote(s);}rejectLinks(log);fs::create_directories(log.parent_path());SECURITY_ATTRIBUTES sa{sizeof(sa),nullptr,TRUE};HANDLE output=CreateFileW(log.c_str(),GENERIC_WRITE,FILE_SHARE_READ,&sa,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);HANDLE input=CreateFileW(L"NUL",GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,&sa,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);if(output==INVALID_HANDLE_VALUE||input==INVALID_HANDLE_VALUE){if(output!=INVALID_HANDLE_VALUE)CloseHandle(output);if(input!=INVALID_HANDLE_VALUE)CloseHandle(input);throw std::runtime_error("diagnostic log");}
    STARTUPINFOW startup{};startup.cb=sizeof(startup);startup.dwFlags=STARTF_USESHOWWINDOW|STARTF_USESTDHANDLES;startup.wShowWindow=SW_HIDE;startup.hStdInput=input;startup.hStdOutput=output;startup.hStdError=output;PROCESS_INFORMATION info{};BOOL ok=CreateProcessW(powershell.c_str(),line.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW,nullptr,root.c_str(),&startup,&info);CloseHandle(input);CloseHandle(output);if(!ok)throw std::runtime_error("diagnostic process");CloseHandle(info.hThread);WaitForSingleObject(info.hProcess,INFINITE);DWORD code=4;GetExitCodeProcess(info.hProcess,&code);CloseHandle(info.hProcess);return int(code);
}
}

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE,PWSTR,int){
    fs::path root;bool unattended=false;
    try{
        std::vector<wchar_t> filename(32768);DWORD n=GetModuleFileNameW(nullptr,filename.data(),DWORD(filename.size()));if(!n||n>=filename.size())throw std::runtime_error("launcher executable path");root=fs::path(filename.data()).parent_path();
        int count=0;auto raw=CommandLineToArgvW(GetCommandLineW(),&count);if(!raw)throw std::runtime_error("launcher arguments");std::vector<std::wstring> args;for(int i=1;i<count;++i)args.emplace_back(raw[i]);LocalFree(raw);
        fs::path capture;bool captureSettings=false;
        if(!args.empty()){unattended=true;if((args[0]==L"--ui-capture"||args[0]==L"--settings-capture")&&args.size()==2){capture=args[1];captureSettings=args[0]==L"--settings-capture";rejectLinks(capture);}
            else return diagnostics(root,args);}
        HANDLE singleton=nullptr;if(capture.empty()){singleton=CreateMutexW(nullptr,TRUE,L"Local\\TriUnitRecompLauncher");if(!singleton)throw std::runtime_error("launcher mutex");if(GetLastError()==ERROR_ALREADY_EXISTS){CloseHandle(singleton);auto existing=FindWindowW(L"MkArcadeCollection",nullptr);if(existing){ShowWindow(existing,SW_RESTORE);SetForegroundWindow(existing);}return 0;}}
        struct MutexGuard{HANDLE h;~MutexGuard(){if(h){ReleaseMutex(h);CloseHandle(h);}}} mutexGuard{singleton};
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);HRESULT com=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);if(FAILED(com))throw std::runtime_error("launcher COM");struct ComGuard{~ComGuard(){CoUninitialize();}} comGuard;
        App app(root);WNDCLASSW cls{};cls.lpfnWndProc=App::procedure;cls.hInstance=instance;cls.lpszClassName=L"MkArcadeCollection";cls.hCursor=LoadCursorW(nullptr,IDC_ARROW);cls.hIcon=LoadIconW(nullptr,IDI_APPLICATION);if(!RegisterClassW(&cls)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)throw std::runtime_error("launcher class");
        RECT work{};SystemParametersInfoW(SPI_GETWORKAREA,0,&work,0);int w=capture.empty()?std::min(1382,int(work.right-work.left-60)):1536,h=capture.empty()?std::min(922,int(work.bottom-work.top-60)):1024;
        HWND window=CreateWindowExW(WS_EX_APPWINDOW,cls.lpszClassName,productName,WS_POPUP|WS_THICKFRAME|WS_MINIMIZEBOX|WS_MAXIMIZEBOX|WS_SYSMENU,(work.right-w)/2,(work.bottom-h)/2,w,h,nullptr,nullptr,instance,&app);if(!window)throw std::runtime_error("launcher window");
        struct WindowGuard{HWND h;~WindowGuard(){if(IsWindow(h))DestroyWindow(h);}} windowGuard{window};
        app.graphics=std::make_unique<Renderer>(window);// Art is drawn in code; the launcher reads no image file.
        if(!capture.empty()){
            SetWindowPos(window,nullptr,0,0,1536,1024,SWP_NOZORDER|SWP_NOACTIVATE);app.launcher.reducedMotion=true;app.settings=captureSettings;app.category=launcherTab;app.notice.clear();app.draw(1,true);app.graphics->saveCapture(capture);return 0;
        }
        eventLog(root,"launcher-start DX12");app.borderless(app.launcher.fullscreen);ShowWindow(window,SW_SHOW);UpdateWindow(window);
        try{
            const auto track=root/L"custom_audio/launcher/menu.wav";rejectLinks(track); // optional user file; silence without it
            app.menuMusic=std::make_unique<MenuMusic>(track);
        }catch(const std::exception& e){eventLog(root,"menu-music unavailable: "+std::string(e.what()));}
        FrameTimer frameTimer;
        mk5timing::Cadence cadence;
        bool quit=false;uint64_t last=frameTicks();
        while(!quit){
            MSG msg{};while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)){if(msg.message==WM_QUIT){quit=true;break;}TranslateMessage(&msg);DispatchMessageW(&msg);}if(quit)break;
            app.poll();if(!IsWindow(window))break;app.pad();
            const bool minimized=IsIconic(window);
            const bool inLauncher=!app.backend.running()&&!app.closing&&!minimized&&GetForegroundWindow()==window;
            const bool fadingMusic=app.menuMusic&&app.menuMusic->update(inLauncher?app.menuMusicLevel():0);
            const auto now=frameTicks();
            if(minimized)cadence.next=0;
            else if(frameDue(cadence,now,app.active?app.launcher.fps:10)){
                app.draw(std::min(.1f,float(now-last)/ticksPerSecond));
                last=now;
            }
            // Input may wake this wait without forcing another GPU frame.
            const auto after=frameTicks();
            if(!minimized){
                if(cadence.due(after))continue;
                frameTimer.arm(cadence.next-after);
            }
            const DWORD delay=fadingMusic||(!minimized&&app.active)?4:(minimized?200:100);
            if(MsgWaitForMultipleObjectsEx(minimized?0:1,&frameTimer.handle,delay,QS_ALLINPUT,MWMO_INPUTAVAILABLE)==WAIT_FAILED)
                throw std::runtime_error("launcher message wait");
        }
        eventLog(root,"launcher-close frames="+std::to_string(app.graphics->frames()));return 0;
    }catch(const std::exception& e){try{if(!root.empty())eventLog(root,"fatal "+std::string(e.what()));}catch(...){}if(!unattended)MessageBoxW(nullptr,(L"Nao foi possivel abrir o launcher.\n\n"+widen(e.what())+L"\n\nMantenha o EXE na raiz do projeto, junto de native, build e roms.").c_str(),productName,MB_OK|MB_ICONERROR);return 4;}
}
