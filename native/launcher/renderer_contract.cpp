#include "launcher_renderer.hpp"
#include <cassert>
#include <iostream>
#include <cmath>
using namespace mklauncher;
int main(){
    CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
    auto window=CreateWindowExW(0,L"STATIC",L"DX12 launcher contract",WS_POPUP,0,0,1536,1024,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    assert(window);
    {
        Renderer r(window);
        int white=r.texture(1,1,{0xffffffff});
        r.begin();r.fill({0,0,1536,1024},{0,0,0,1});r.quad(white,{100,100,100,100},{0,0,1,1},{1,0,0,1});
        r.fill({150,100,100,100},{0,0,1,0.5f});r.end(false);
        unsigned w=0,h=0;auto pixels=r.capture(w,h);assert(w==1536&&h==1024&&pixels.size()==size_t(w)*h);
        auto at=[&](int x,int y){return pixels[size_t(y)*w+x];};
        assert((at(120,120)&0xffffff)==0xff0000);
        auto mixed=at(170,120);assert(std::abs(int((mixed>>16)&255)-127)<=1&&std::abs(int(mixed&255)-128)<=1);
        assert((at(300,120)&0xffffff)==0);
        // Asset load: a valid PNG comes back unchanged; a missing one is a powered-off screen, not an exception.
        auto png=std::filesystem::temp_directory_path()/L"renderer-contract-roundtrip.png";r.saveCapture(png);
        int loaded=r.texture(png),off=r.texture(png.parent_path()/L"renderer-contract-missing.png");std::filesystem::remove(png);
        r.begin();r.quad(loaded,{0,0,1536,1024});r.quad(off,{600,600,50,50});r.end(false);
        auto again=r.capture(w,h);size_t changed=0;
        for(size_t i=0;i<again.size();++i){unsigned x=unsigned(i%w),y=unsigned(i/w);if(x<600||x>=650||y<600||y>=650)changed+=(again[i]&0xffffff)!=(pixels[i]&0xffffff);}
        assert(changed==0&&(again[620*w+620]&0xffffff)==(offMonitor&0xffffff));
        SetWindowPos(window,nullptr,0,0,768,512,SWP_NOZORDER);
        r.begin();r.fill({0,0,1536,1024},{0,1,0,1});r.text(L"HOME SETTINGS",20,20,20);r.end(false);
        pixels=r.capture(w,h);assert(w==768&&h==512);assert((pixels[400*w+400]&0xffffff)==0x00ff00);
        assert(r.textWidth(L"WWW",20)>r.textWidth(L"iii",20));
        SetWindowPos(window,nullptr,0,0,1280,720,SWP_NOZORDER);
        r.begin();r.fill({0,0,1024.f*16/9,1024},{0,1,0,1});r.end(false);
        pixels=r.capture(w,h);assert(w==1280&&h==720);
        assert((at(0,360)&0xffffff)==0x00ff00&&(at(1279,360)&0xffffff)==0x00ff00);
        float x=0,y=0;r.mouse({640,360},x,y);
        assert(std::abs(x-512.f*16/9)<.01f&&std::abs(y-512)<.01f);
        std::cout<<"{\"passed\":true,\"dx12_readback\":true,\"alpha_blend\":true,\"resize\":true,\"asset_roundtrip\":true,\"missing_asset_off_monitor\":true,\"frames\":"<<r.frames()<<"}\n";
    }
    DestroyWindow(window);CoUninitialize();
}
