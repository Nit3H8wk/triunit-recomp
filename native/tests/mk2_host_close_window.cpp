// Test-only window substitute. CPU/DSP/CMOS remain the real native implementation; GPU/audio are unqualified.
#include "mk5_window.hpp"
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
struct Mk5Window::Impl {
    bool closed=false;unsigned pumps=0,samples=0,presentations=0,state_done=0;
    unsigned close_after=unsigned(std::stoul(std::getenv("MK2_TEST_CLOSE_AFTER_SAMPLES")?std::getenv("MK2_TEST_CLOSE_AFTER_SAMPLES"):"1"));
    uint32_t input=uint32_t(std::stoul(std::getenv("MK2_TEST_INPUT")?std::getenv("MK2_TEST_INPUT"):"ffffffef",nullptr,16));
};
Mk5Window::Mk5Window(bool,unsigned,unsigned):impl(std::make_unique<Impl>()){}
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
// MK2_TEST_PRESENT_HASHES: one line per presented frame with the FNV-1a of its pixels and backdrop (run-ahead tests) over
// the 400 columns at its centre (a widescreen frame's arcade columns when its window is centred), and its width.
void Mk5Window::Present(const std::vector<uint32_t>& pixels,unsigned width,unsigned height,
                        const std::vector<uint32_t>& backdrop,const mk5presentation::FighterFrame&,
                        const std::vector<mk5training::Box>& boxes){
    if(impl->closed)throw std::runtime_error("presentation submitted after window close");
    ++impl->presentations;
    if(!std::getenv("MK2_TEST_PRESENT_HASHES"))return;
    uint64_t hash=0xcbf29ce484222325ull;
    const unsigned margin=width>400?(width-400)/2:0;
    for(const auto* frame:{&pixels,&backdrop})if(frame->size()==size_t(width)*height)
        for(unsigned y=0;y<height;++y)for(unsigned x=margin;x<width-margin;++x)hash=(hash^(*frame)[size_t(y)*width+x])*0x100000001b3ull;
    std::printf("{\"present\":\"%016llx\",\"width\":%u,\"boxes\":[",(unsigned long long)hash,width);
    for(size_t i=0;i<boxes.size();++i)std::printf("%s[%d,%d,%d,%d,%d]",i?",":"",boxes[i].x,boxes[i].y,boxes[i].w,boxes[i].h,int(boxes[i].kind));
    std::printf("]}\n");
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
bool Mk5Window::RunAhead()const{return std::getenv("MK2_TEST_RUN_AHEAD")!=nullptr;}
bool Mk5Window::Training()const{return std::getenv("MK2_TEST_TRAINING")!=nullptr;}
uint64_t Mk5Window::frames()const{return impl->presentations;}
uint64_t Mk5Window::input_events()const{return impl->samples;}
bool Mk5Window::GraphicsValidationEnabled()const{return false;}
std::string Mk5Window::presentation_json()const{
    return "{\"test_double\":true,\"closed\":"+std::string(impl->closed?"true":"false")+
        ",\"host_samples\":"+std::to_string(impl->samples)+",\"presentations\":"+std::to_string(impl->presentations)+"}";
}
