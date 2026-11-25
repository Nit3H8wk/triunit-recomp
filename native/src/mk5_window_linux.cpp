// mk5_window_linux.cpp — Headless stubs for Phase 1.
// These satisfy the linker on Linux so the core game logic compiles cleanly.
// Phase 3 replaces these with real Vulkan 1.3 + SDL3 implementations.
#include "mk5_window.hpp"

BootDiInputs Mk5KeyboardInputs(const std::array<bool,256>&,BootDiInputs base){return base;}

struct Mk5Window::Impl { bool closed=false; };
Mk5Window::Mk5Window(bool,unsigned,unsigned):impl(new Impl()){}
Mk5Window::~Mk5Window()=default;
bool Mk5Window::Pump(){return impl->closed;}
std::vector<Mk5Window::StateRequest> Mk5Window::TakeStateRequests(){return {};}
BootDiInputs Mk5Window::Inputs(BootDiInputs base)const{return base;}
bool Mk5Window::RunAhead()const{return false;}
bool Mk5Window::Training()const{return false;}
void Mk5Window::Present(const std::vector<uint32_t>&,unsigned,unsigned,
                        const std::vector<uint32_t>&,
                        const mk5presentation::FighterFrame&,
                        const std::vector<mk5training::Box>&){}
void Mk5Window::Frontier(uint32_t){}
uint64_t Mk5Window::frames()const{return 0;}
uint64_t Mk5Window::input_events()const{return 0;}
bool Mk5Window::GraphicsValidationEnabled()const{return false;}
std::string Mk5Window::presentation_json()const{return "{}";}
