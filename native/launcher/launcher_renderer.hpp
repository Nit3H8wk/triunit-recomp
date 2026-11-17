#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>
#include <cstdint>

namespace mklauncher {
constexpr float baseWidth=1536.f, layoutHeight=1024.f, wideWidth=layoutHeight*16/9;
struct Rect { float x=0,y=0,w=0,h=0; bool contains(float px,float py)const{return px>=x&&py>=y&&px<x+w&&py<y+h;} };
struct Color {float r=1,g=1,b=1,a=1;};
constexpr uint32_t offMonitor=0xff0a0b0d;   // BGRA of Renderer::texture(path) when the file is missing or undecodable
class Renderer {
    struct Impl;std::unique_ptr<Impl> p;
public:
    explicit Renderer(HWND window);
    ~Renderer();
    Renderer(const Renderer&)=delete;Renderer& operator=(const Renderer&)=delete;
    int texture(const std::filesystem::path& path);
    int texture(unsigned w,unsigned h,const std::vector<uint32_t>& bgra);
    void begin();
    void bezel(bool enabled);
    void quad(int texture,Rect destination,Rect uv={0,0,1,1},Color tint={},int effect=0,float time=0);
    void fill(Rect rectangle,Color color);
    // Rounded rectangle (signed distance, antialiased): filled, or an outline `border` layout pixels wide.
    void rounded(Rect rectangle,float radius,Color color,float border=0);
    void triangle(float ax,float ay,float bx,float by,float cx,float cy,Color color);
    void line(float ax,float ay,float bx,float by,float thickness,Color color);
    void text(const std::wstring& value,float x,float y,float size,Color color={},float tracking=0);
    float textWidth(const std::wstring& value,float size,float tracking=0)const;
    void end(bool vsync=true);
    std::vector<uint32_t> capture(unsigned& width,unsigned& height);
    void saveCapture(const std::filesystem::path& path);
    void mouse(POINT client,float& x,float& y)const;
    uint64_t frames()const;
    float layoutWidth()const;
    unsigned width()const;unsigned height()const;
};
}
