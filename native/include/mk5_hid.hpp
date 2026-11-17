#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <winternl.h>
#include <hidusage.h>
#include <hidpi.h>
#include <algorithm>
#include <cstdint>
#include <cwchar>
#include <map>
#include <mutex>
#include <vector>
#include "mk5_controls.hpp"
// Raw Input game controllers that are not XInput (DirectInput arcade sticks and pads). One reader per process, fed by the
// WM_INPUT of the window that registered it; hid.dll is resolved at run time like XInput. XInput devices ("IG_" in the
// device name) are left to XInput.
namespace mk5hid {
struct Pad {uint32_t buttons=0;unsigned directions=0;}; // buttons: mk5controls mask; directions: bits Up Down Left Right
class Reader {
    using Caps=NTSTATUS(NTAPI*)(PHIDP_PREPARSED_DATA,PHIDP_CAPS);
    using ValueCaps=NTSTATUS(NTAPI*)(HIDP_REPORT_TYPE,PHIDP_VALUE_CAPS,PUSHORT,PHIDP_PREPARSED_DATA);
    using Usages=NTSTATUS(NTAPI*)(HIDP_REPORT_TYPE,USAGE,USHORT,PUSAGE,PULONG,PHIDP_PREPARSED_DATA,PCHAR,ULONG);
    using UsageValue=NTSTATUS(NTAPI*)(HIDP_REPORT_TYPE,USAGE,USHORT,USAGE,PULONG,PHIDP_PREPARSED_DATA,PCHAR,ULONG);
    struct Axis {USAGE usage;long low,high;};
    struct Device {std::vector<BYTE> preparsed;std::vector<Axis> axes;Pad pad;uint64_t order;};
    HMODULE dll=nullptr;Caps caps=nullptr;ValueCaps valueCaps=nullptr;Usages usages=nullptr;UsageValue usageValue=nullptr;
    std::mutex lock;std::map<HANDLE,Device> devices;std::map<HANDLE,bool> ignored;uint64_t arrivals=0;
    template<class T>static T resolve(HMODULE m,const char* name){return reinterpret_cast<T>(reinterpret_cast<void*>(GetProcAddress(m,name)));}
    bool open(HANDLE handle,Device& d){
        UINT size=0;GetRawInputDeviceInfoW(handle,RIDI_DEVICENAME,nullptr,&size);std::wstring name(size,L'\0');
        if(!size||GetRawInputDeviceInfoW(handle,RIDI_DEVICENAME,name.data(),&size)==UINT(-1)||name.find(L"IG_")!=std::wstring::npos)return false;
        size=0;GetRawInputDeviceInfoW(handle,RIDI_PREPARSEDDATA,nullptr,&size);d.preparsed.resize(size);
        if(!size||GetRawInputDeviceInfoW(handle,RIDI_PREPARSEDDATA,d.preparsed.data(),&size)==UINT(-1))return false;
        const auto data=reinterpret_cast<PHIDP_PREPARSED_DATA>(d.preparsed.data());HIDP_CAPS c{};
        if(caps(data,&c)!=HIDP_STATUS_SUCCESS)return false;
        std::vector<HIDP_VALUE_CAPS> values(c.NumberInputValueCaps);USHORT n=c.NumberInputValueCaps;
        if(n&&valueCaps(HidP_Input,values.data(),&n,data)!=HIDP_STATUS_SUCCESS)return false;
        for(USHORT i=0;i<n;++i){const auto& v=values[i];const USAGE u=v.IsRange?v.Range.UsageMin:v.NotRange.Usage;
            if(v.UsagePage==1&&(u==0x30||u==0x31||u==0x39))d.axes.push_back({u,v.LogicalMin,v.LogicalMax});}
        d.order=arrivals++;return true;
    }
public:
    Reader(){dll=LoadLibraryExW(L"hid.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(!dll)return;
        caps=resolve<Caps>(dll,"HidP_GetCaps");valueCaps=resolve<ValueCaps>(dll,"HidP_GetValueCaps");
        usages=resolve<Usages>(dll,"HidP_GetUsages");usageValue=resolve<UsageValue>(dll,"HidP_GetUsageValue");
        if(!caps||!valueCaps||!usages||!usageValue){FreeLibrary(dll);dll=nullptr;}}
    ~Reader(){if(dll)FreeLibrary(dll);}
    Reader(const Reader&)=delete;Reader& operator=(const Reader&)=delete;
    // Joysticks and gamepads (generic desktop 4 and 5) for `window`, with arrival and removal notices.
    void listen(HWND window){
        if(!dll)return;
        const RAWINPUTDEVICE wanted[2]={{1,4,RIDEV_DEVNOTIFY,window},{1,5,RIDEV_DEVNOTIFY,window}};
        RegisterRawInputDevices(wanted,2,sizeof(RAWINPUTDEVICE));
    }
    void removed(HANDLE handle){std::lock_guard<std::mutex> guard(lock);devices.erase(handle);ignored.erase(handle);}
    void input(LPARAM raw){
        if(!dll)return;
        UINT size=0;GetRawInputData(reinterpret_cast<HRAWINPUT>(raw),RID_INPUT,nullptr,&size,sizeof(RAWINPUTHEADER));
        std::vector<BYTE> buffer(size);
        if(!size||GetRawInputData(reinterpret_cast<HRAWINPUT>(raw),RID_INPUT,buffer.data(),&size,sizeof(RAWINPUTHEADER))!=size)return;
        const auto* in=reinterpret_cast<const RAWINPUT*>(buffer.data());
        if(in->header.dwType!=RIM_TYPEHID||!in->data.hid.dwCount)return;
        std::lock_guard<std::mutex> guard(lock);
        if(ignored.count(in->header.hDevice))return;
        auto found=devices.find(in->header.hDevice);
        if(found==devices.end()){Device d;if(!open(in->header.hDevice,d)){ignored[in->header.hDevice]=true;return;}found=devices.emplace(in->header.hDevice,std::move(d)).first;}
        auto& d=found->second;const auto data=reinterpret_cast<PHIDP_PREPARSED_DATA>(d.preparsed.data());
        // The last report of the batch is the current state.
        const auto report=reinterpret_cast<PCHAR>(const_cast<BYTE*>(in->data.hid.bRawData+size_t(in->data.hid.dwCount-1)*in->data.hid.dwSizeHid));
        const ULONG length=in->data.hid.dwSizeHid;
        Pad pad;USAGE pressed[64];ULONG count=64;
        if(usages(HidP_Input,9,0,pressed,&count,data,report,length)==HIDP_STATUS_SUCCESS)
            for(ULONG i=0;i<count;++i)pad.buttons|=mk5controls::hid_button(pressed[i]);
        for(const auto& axis:d.axes){ULONG value=0;
            if(usageValue(HidP_Input,1,0,axis.usage,&value,data,report,length)!=HIDP_STATUS_SUCCESS||axis.high<=axis.low)continue;
            const long v=long(value);
            if(axis.usage==0x39){ // hat: 0 up, clockwise in eighths; out of range is centred
                const long step=v-axis.low;if(step<0||step>7)continue;
                constexpr unsigned hat[8]={1,1|8,8,2|8,2,2|4,4,1|4};pad.directions|=hat[step];
            }else{const double t=double(v-axis.low)/double(axis.high-axis.low);
                if(t<.25)pad.directions|=axis.usage==0x30?4u:1u;
                if(t>.75)pad.directions|=axis.usage==0x30?8u:2u;}
        }
        d.pad=pad;
    }
    // Connected controllers in arrival order.
    std::vector<Pad> pads(){
        std::lock_guard<std::mutex> guard(lock);std::vector<std::pair<uint64_t,Pad>> list;
        for(const auto& [handle,d]:devices)list.push_back({d.order,d.pad});
        std::sort(list.begin(),list.end(),[](const auto& a,const auto& b){return a.first<b.first;});
        std::vector<Pad> out;for(const auto& item:list)out.push_back(item.second);return out;
    }
};
inline Reader& shared(){static Reader reader;return reader;}
}
