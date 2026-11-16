#pragma once
#include <array>
#include <algorithm>
namespace mk5color {
inline std::array<float,3> apply(std::array<float,3> rgb,int mode,float brightness){
 if(mode==1){const float y=rgb[0]*.2126f+rgb[1]*.7152f+rgb[2]*.0722f;for(auto& c:rgb)c=(y+(c-y)*1.15f-.5f)*1.05f+.5f;}
 if(mode==2){rgb[0]*=1.025f;rgb[2]*=.94f;}
 for(auto& c:rgb)c=std::clamp(c*brightness,0.f,1.f);
 return rgb;
}
}
