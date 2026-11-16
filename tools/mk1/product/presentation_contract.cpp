#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <dxgi.h>
#include "mk5_window.hpp"
#include "mk5_audio_link.hpp"
#include <iostream>
#include <stdexcept>
static HWND owned_window(){
 HWND hwnd=nullptr;
 EnumWindows([](HWND h,LPARAM p)->BOOL{DWORD pid=0;GetWindowThreadProcessId(h,&pid);wchar_t n[64]{};GetClassNameW(h,n,64);if(pid==GetCurrentProcessId()&&std::wstring(n)==L"Mk5TemporalScanout"){*reinterpret_cast<HWND*>(p)=h;return FALSE;}return TRUE;},reinterpret_cast<LPARAM>(&hwnd));
 if(!hwnd)throw std::runtime_error("owned game window missing");
 return hwnd;
}
static uint64_t metric(const std::string& report,const char* name){
 const std::string key=std::string("\"")+name+"\":";
 const auto at=report.find(key);
 if(at==std::string::npos)throw std::runtime_error("missing presentation metric: "+std::string(name));
 return std::stoull(report.substr(at+key.size()));
}
// Run on an inactive desktop where DXGI returns DXGI_STATUS_OCCLUDED.
static int verify_occlusion(){
 SetEnvironmentVariableA("MK1_FULLSCREEN","0");SetEnvironmentVariableA("MK1_BEZEL","0");
 SetEnvironmentVariableA("MK1_SYNC","immediate");SetEnvironmentVariableA("MK1_GRAPHICS_VALIDATE","1");
 bool bounded=true;
 for(bool high_refresh:{false,true}){
  SetEnvironmentVariableA("MK1_HIGH_REFRESH",high_refresh?"1":"0");
  Mk5Window window;
  window.Present(std::vector<uint32_t>(400*254,0x102030),400,254);
  std::string report;
  uint64_t before=0;
  const auto until=GetTickCount64()+4000;
  while(GetTickCount64()<until){
   window.Pump();
   report=window.presentation_json();
   before=metric(report,"occluded_present_attempts");
   if(before)break;
   Sleep(5);
  }
  if(!before || metric(report,"last_present_hresult")!=DXGI_STATUS_OCCLUDED ||
     metric(report,"displayed_frames")!=0 || metric(report,"gpu_validation_frames")!=1 ||
     metric(report,"gpu_validation_mismatches")!=0)
   throw std::runtime_error("private desktop did not produce the expected occluded DXGI readback: "+report);
  const auto start=GetTickCount64();
  Sleep(350);window.Pump();report=window.presentation_json();
  const auto elapsed=GetTickCount64()-start;
  const auto attempts=metric(report,"occluded_present_attempts")-before;
  bounded&=attempts>=2&&attempts<=elapsed/100+2;
  std::cout<<"occluded HRESULT=0x"<<std::hex<<DXGI_STATUS_OCCLUDED<<std::dec
           <<" high_refresh="<<high_refresh<<" attempts="<<attempts<<" in "<<elapsed<<" ms"<<std::endl;
  const HWND hwnd=owned_window();
  RECT outer{};
  const auto width=metric(report,"viewport_width");
  if(!GetWindowRect(hwnd,&outer)||!SetWindowPos(hwnd,nullptr,0,0,outer.right-outer.left+96,
     outer.bottom-outer.top+96,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE))
   throw std::runtime_error("occluded window resize failed");
  const auto resize_until=GetTickCount64()+400;
  while(GetTickCount64()<resize_until&&metric(report,"viewport_width")==width){
   window.Pump();Sleep(5);report=window.presentation_json();
  }
  if(metric(report,"viewport_width")<=width)throw std::runtime_error("occluded window resize was not serviced");
  if(!PostMessageW(hwnd,WM_CLOSE,0,0))throw std::runtime_error("occluded window close failed");
  const auto close_until=GetTickCount64()+400;
  while(window.Pump()&&GetTickCount64()<close_until)Sleep(5);
  if(window.Pump())throw std::runtime_error("occluded window close was not serviced");
 }
 if(!bounded)throw std::runtime_error("occluded Present retries must be bounded with or without High Refresh");
 return 0;
}
int main(int argc,char** argv){try{
 if(argc==2&&std::string(argv[1])=="--occluded")return verify_occlusion();
 mk5audio::detail::hooks.output_clock=true;
 SetEnvironmentVariableA("MK1_SYNC","immediate");SetEnvironmentVariableA("MK1_GRAPHICS_VALIDATE","0");SetEnvironmentVariableA("MK1_HIGH_REFRESH","0");
 Mk5Window window(/*immediate_headroom=*/true);const HWND hwnd=owned_window();
 RECT client{};GetClientRect(hwnd,&client);MONITORINFO monitor{};monitor.cbSize=sizeof(monitor);GetMonitorInfoW(MonitorFromWindow(hwnd,MONITOR_DEFAULTTONEAREST),&monitor);
 if(client.right!=monitor.rcMonitor.right-monitor.rcMonitor.left||client.bottom!=monitor.rcMonitor.bottom-monitor.rcMonitor.top)throw std::runtime_error("game must start fullscreen at desktop resolution");
 const auto report=window.presentation_json();
 if(report.find("\"exclusive\":false")==std::string::npos)throw std::runtime_error("borderless fullscreen required for VRR");
 const auto queue_limit=report.find("\"tearing_supported\":true")!=std::string::npos?2u:1u;
 if(metric(report,"frame_queue_limit")!=queue_limit)throw std::runtime_error("immediate queue headroom requires tearing support");
 Sleep(100);window.Present(std::vector<uint32_t>(400*254,0x102030),400,254);
 const auto until=GetTickCount64()+800;bool visible=false;
 while(GetTickCount64()<until){window.Pump();if(window.presentation_json().find("\"displayed_frames\":0")==std::string::npos){visible=true;break;}Sleep(5);}
 if(!visible)throw std::runtime_error("initial waitable slot must survive until first real source frame");
 if(!SetWindowPos(hwnd,nullptr,monitor.rcMonitor.left,monitor.rcMonitor.top,800,508,SWP_NOZORDER|SWP_NOACTIVATE))throw std::runtime_error("contract window resize failed");
 PostMessageW(hwnd,WM_DISPLAYCHANGE,32,MAKELPARAM(monitor.rcMonitor.right-monitor.rcMonitor.left,monitor.rcMonitor.bottom-monitor.rcMonitor.top));
 const auto resizedUntil=GetTickCount64()+1000;bool fitted=false;
 while(GetTickCount64()<resizedUntil){
  window.Pump();GetClientRect(hwnd,&client);GetMonitorInfoW(MonitorFromWindow(hwnd,MONITOR_DEFAULTTONEAREST),&monitor);
  if(client.right==monitor.rcMonitor.right-monitor.rcMonitor.left && client.bottom==monitor.rcMonitor.bottom-monitor.rcMonitor.top){fitted=true;break;}Sleep(5);
 }
 if(!fitted)throw std::runtime_error("borderless must follow current monitor geometry after display change");
 std::cout<<report<<'\n';
 std::cout<<"PASS fullscreen startup and display-change resize at desktop resolution\n";return 0;
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
