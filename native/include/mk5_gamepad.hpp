#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <xinput.h>
#include <array>
#include <cstdint>
#include "mk5_machine.hpp"
namespace mk5pad {
struct Ports {
 std::array<int,2> slots{{-1,-1}};
 void update(const std::array<bool,4>& connected){
  for(auto& slot:slots)if(slot>=0&&!connected[unsigned(slot)])slot=-1;
  for(unsigned i=0;i<4;++i)if(connected[i]&&slots[0]!=int(i)&&slots[1]!=int(i)){
   for(auto& slot:slots)if(slot<0){slot=int(i);break;}
  }
 }
};
inline BootDiInputs map(const XINPUT_GAMEPAD& pad,unsigned player,BootDiInputs base){
 if(player>1)return base;
 const unsigned offset=player*8;
 auto press=[&](bool down,unsigned bit){if(down)base.in01&=~(uint32_t(1)<<bit);};
 const auto b=pad.wButtons;
 press((b&XINPUT_GAMEPAD_DPAD_UP)||pad.sThumbLY>16000,offset);
 press((b&XINPUT_GAMEPAD_DPAD_DOWN)||pad.sThumbLY<-16000,offset+1);
 press((b&XINPUT_GAMEPAD_DPAD_LEFT)||pad.sThumbLX<-16000,offset+2);
 press((b&XINPUT_GAMEPAD_DPAD_RIGHT)||pad.sThumbLX>16000,offset+3);
 press(b&XINPUT_GAMEPAD_X,offset+4); // high punch
 press((b&(XINPUT_GAMEPAD_LEFT_SHOULDER|XINPUT_GAMEPAD_RIGHT_SHOULDER))||pad.bLeftTrigger>=128||pad.bRightTrigger>=128,offset+5);
 press(b&XINPUT_GAMEPAD_Y,offset+6); // high kick
 press(b&XINPUT_GAMEPAD_A,player?25:28); // low punch
 press(b&XINPUT_GAMEPAD_B,player?26:29); // low kick
 press(b&XINPUT_GAMEPAD_BACK,16+player); // original coin
 press(b&XINPUT_GAMEPAD_START,player?21:18);
 return base;
}
// Dynamically resolve the OS driver: no vendor install and no dependency on a
// single XInput DLL version. Disconnected slots are retried without blocking UI.
class Devices {
 using GetState=DWORD(WINAPI*)(DWORD,XINPUT_STATE*);
 HMODULE dll=nullptr;GetState get=nullptr;ULONGLONG next=0;Ports ports;
 std::array<ULONGLONG,4> retry{};
public:
 std::array<XINPUT_STATE,4> states{};std::array<bool,4> connected{};
 Devices(){for(auto name:{L"xinput1_4.dll",L"xinput9_1_0.dll"}){dll=LoadLibraryExW(name,nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(dll){get=reinterpret_cast<GetState>(reinterpret_cast<void*>(GetProcAddress(dll,"XInputGetState")));if(get)break;FreeLibrary(dll);dll=nullptr;}}}
 ~Devices(){if(dll)FreeLibrary(dll);}
 Devices(const Devices&)=delete;Devices& operator=(const Devices&)=delete;
 void poll(){const auto now=GetTickCount64();if(now<next)return;next=now+4;
  for(unsigned i=0;i<4;++i){if(!connected[i]&&now<retry[i])continue;states[i]={};connected[i]=get&&get(i,&states[i])==ERROR_SUCCESS;if(!connected[i])retry[i]=now+250;}ports.update(connected);}
 BootDiInputs inputs(BootDiInputs base){poll();for(unsigned player=0;player<2;++player){const int slot=ports.slots[player];if(slot>=0&&connected[unsigned(slot)])base=map(states[unsigned(slot)].Gamepad,player,base);}return base;}
 unsigned count()const{unsigned n=0;for(bool c:connected)n+=c;return n;}
};
}
