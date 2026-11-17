#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <xinput.h>
#include <array>
#include <cstdint>
#include "mk5_machine.hpp"
#include "mk5_controls.hpp"
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
// Directions of a pad: D-pad or left stick past its deadzone (bits Up Down Left Right of mk5controls).
inline unsigned directions(const XINPUT_GAMEPAD& pad){
 const auto b=pad.wButtons;
 return unsigned((b&XINPUT_GAMEPAD_DPAD_UP)||pad.sThumbLY>16000)|unsigned((b&XINPUT_GAMEPAD_DPAD_DOWN)||pad.sThumbLY<-16000)<<1|
        unsigned((b&XINPUT_GAMEPAD_DPAD_LEFT)||pad.sThumbLX<-16000)<<2|unsigned((b&XINPUT_GAMEPAD_DPAD_RIGHT)||pad.sThumbLX>16000)<<3;
}
inline uint32_t buttons(const XINPUT_GAMEPAD& pad){
 return pad.wButtons|(pad.bLeftTrigger>=128?mk5controls::LT:0)|(pad.bRightTrigger>=128?mk5controls::RT:0);
}
// One pad on the shared MK1/MK2 word with the given controls (default: the original layout).
inline BootDiInputs map(const XINPUT_GAMEPAD& pad,unsigned player,BootDiInputs base,const mk5controls::Config& controls={}){
 if(player>1)return base;
 const uint32_t held=mk5controls::from_pad(controls,player,buttons(pad),directions(pad));
 base.in01=mk5controls::shared(player?0:held,player?held:0,base.in01,true);
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
 // The pad of a player, or nullptr (the shared P1/P2 slot assignment).
 const XINPUT_GAMEPAD* player(unsigned p)const{const int slot=ports.slots[p];return slot>=0&&connected[unsigned(slot)]?&states[unsigned(slot)].Gamepad:nullptr;}
 unsigned count()const{unsigned n=0;for(bool c:connected)n+=c;return n;}
};
}
