#include "mk5_stage_bicubic.hpp"
#include <iostream>
#include <stdexcept>

int main(){try{
    constexpr unsigned width=9,height=7;
    std::vector<uint32_t> original,backdrop;
    for(unsigned i=0;i<width*height;++i){
        const uint32_t rgb=(((i*173+33)&255)<<16)|(((i*i*19+97)&255)<<8)|((i*53+9)&255);
        const bool scenery=(i%width+3*(i/width))%5!=2;
        original.push_back(0xff000000|(scenery?rgb:0x12cf34));
        backdrop.push_back(rgb|(scenery?mk5stage::scenery:0));
    }
    const auto composed=mk5stage::Bicubic4x(original,backdrop,width,height);
    if(composed.size()!=width*height*16)throw std::runtime_error("4x output geometry");
    uint64_t hash=14695981039346656037ull;
    for(unsigned y=0;y<height*4;++y)for(unsigned x=0;x<width*4;++x){
        const auto rgb=composed[y*width*4+x];
        const auto source=y/4*width+x/4;
        if(!(backdrop[source]&mk5stage::scenery) && rgb!=(original[source]&0xffffff))
            throw std::runtime_error("foreground texel changed");
        if((rgb&mk5stage::scenery)!=(backdrop[source]&mk5stage::scenery))
            throw std::runtime_error("scenery ownership changed");
        hash=(hash^(rgb&0xffffff))*1099511628211ull;
    }
    // Pillow BICUBIC RGB reference with the original foreground pasted at 4x.
    if(hash!=0x0715f4364935f689ull)throw std::runtime_error("bicubic reference mismatch");
    std::cout<<"PASS bicubic scenery, edge taps and foreground ownership\n";
    return 0;
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
