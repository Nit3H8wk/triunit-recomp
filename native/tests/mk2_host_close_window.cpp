// Test-only window substitute. CPU/DSP/CMOS remain the real native implementation; GPU/audio are unqualified.
#include "mk5_window.hpp"
#include <cstdlib>
#include <stdexcept>
struct Mk5Window::Impl {
    bool closed=false;unsigned pumps=0,samples=0,presentations=0;
    unsigned close_after=unsigned(std::stoul(std::getenv("MK2_TEST_CLOSE_AFTER_SAMPLES")?std::getenv("MK2_TEST_CLOSE_AFTER_SAMPLES"):"1"));
    uint32_t input=uint32_t(std::stoul(std::getenv("MK2_TEST_INPUT")?std::getenv("MK2_TEST_INPUT"):"ffffffef",nullptr,16));
};
Mk5Window::Mk5Window(bool):impl(std::make_unique<Impl>()){}
Mk5Window::~Mk5Window()=default;
bool Mk5Window::Pump(){
    if(impl->closed && std::getenv("MK2_TEST_FAILURE_AFTER_FALSE"))throw std::runtime_error("published fake GPU driver failure");
    ++impl->pumps;
    if(impl->samples>=impl->close_after)impl->closed=true;
    return !impl->closed;
}
BootDiInputs Mk5Window::Inputs(BootDiInputs base)const{
    if(impl->closed)throw std::runtime_error("input queried after window close");
    ++impl->samples;base.in01=impl->input;return base;
}
void Mk5Window::Present(const std::vector<uint32_t>&,unsigned,unsigned,
                        const std::vector<uint32_t>&,const mk5presentation::FighterFrame&){
    if(impl->closed)throw std::runtime_error("presentation submitted after window close");
    ++impl->presentations;
}
void Mk5Window::Frontier(uint32_t){if(impl->closed)throw std::runtime_error("frontier submitted after window close");}
uint64_t Mk5Window::frames()const{return impl->presentations;}
uint64_t Mk5Window::input_events()const{return impl->samples;}
bool Mk5Window::GraphicsValidationEnabled()const{return false;}
std::string Mk5Window::presentation_json()const{
    return "{\"test_double\":true,\"closed\":"+std::string(impl->closed?"true":"false")+
        ",\"host_samples\":"+std::to_string(impl->samples)+",\"presentations\":"+std::to_string(impl->presentations)+"}";
}
