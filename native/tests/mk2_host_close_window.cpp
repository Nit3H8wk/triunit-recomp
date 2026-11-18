// Test-only window substitute. CPU/DSP/CMOS remain the real native implementation; GPU/audio are unqualified.
#include "mk5_window.hpp"
#include <cstdlib>
#include <stdexcept>
struct Mk5Window::Impl {
    bool closed=false;unsigned pumps=0,samples=0,presentations=0,state_done=0;
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
// MK2_TEST_STATE="save@N,load@M": F5/F7 as the real window queues them, once the host sampled the input N (M) times.
std::vector<Mk5Window::StateRequest> Mk5Window::TakeStateRequests(){
    std::vector<StateRequest> out;const char* plan=std::getenv("MK2_TEST_STATE");if(!plan)return out;
    std::string text=plan;size_t at=0;unsigned index=0;
    while(at<text.size()){
        const auto end=std::min(text.find(',',at),text.size());const auto item=text.substr(at,end-at);at=end+1;
        const auto mark=item.find('@');if(mark==std::string::npos)throw std::runtime_error("MK2_TEST_STATE item");
        const unsigned when=unsigned(std::stoul(item.substr(mark+1)));const bool done=impl->state_done>>index&1;
        if(!done && impl->samples>=when){impl->state_done|=1u<<index;out.push_back(item.compare(0,mark,"save")==0?StateRequest::Save:StateRequest::Load);}
        ++index;
    }
    return out;
}
uint64_t Mk5Window::frames()const{return impl->presentations;}
uint64_t Mk5Window::input_events()const{return impl->samples;}
bool Mk5Window::GraphicsValidationEnabled()const{return false;}
std::string Mk5Window::presentation_json()const{
    return "{\"test_double\":true,\"closed\":"+std::string(impl->closed?"true":"false")+
        ",\"host_samples\":"+std::to_string(impl->samples)+",\"presentations\":"+std::to_string(impl->presentations)+"}";
}
