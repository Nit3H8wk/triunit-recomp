#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
// HDR10 output: the SDR frame (sRGB, as Windows shows SDR content) at paper white, optional highlight expansion up to the
// peak, BT.709 -> BT.2020, PQ (SMPTE ST 2084). With highlights 0 the HDR image is the SDR image at paper white.
namespace mk5hdr {
struct Settings {float paper=203,peak=1000,highlights=0;};
inline float srgb_linear(float c){return c<=.04045f?c/12.92f:std::pow((c+.055f)/1.055f,2.4f);}
inline float pq(float nits){
 const float y=std::pow(std::clamp(nits,0.f,10000.f)/10000,.1593017578125f);
 return std::pow((.8359375f+18.8515625f*y)/(1+18.6875f*y),78.84375f);
}
constexpr float bt2020[3][3]={{.6274040f,.3292820f,.0433136f},{.0690970f,.9195400f,.0113612f},{.0163916f,.0880132f,.8955950f}};
// Highlight gain: 1 for dark and mid tones, rising with the brightest channel until SDR white reaches the peak.
inline float expansion(float maximum,const Settings& s){
 return 1+s.highlights*std::max(0.f,s.peak/s.paper-1)*maximum*maximum*maximum*maximum;
}
// CPU reference of the shader: 0x00RRGGBB -> R10G10B10A2 (red in the low bits, as DXGI lays it out).
inline uint32_t encode(uint32_t rgb,const Settings& s){
 const std::array<float,3> c{srgb_linear(float((rgb>>16)&255)/255),srgb_linear(float((rgb>>8)&255)/255),srgb_linear(float(rgb&255)/255)};
 const float gain=s.paper*expansion(std::max({c[0],c[1],c[2]}),s);
 uint32_t out=3u<<30;
 for(int i=0;i<3;++i){
  const float nits=std::min((bt2020[i][0]*c[0]+bt2020[i][1]*c[1]+bt2020[i][2]*c[2])*gain,std::max(s.peak,s.paper));
  out|=uint32_t(std::lround(pq(nits)*1023))<<(10*i);
 }
 return out;
}
constexpr char shader[]=R"HLSL(
Texture2D scene : register(t0);
cbuffer Hdr : register(b0) {float paper, peak, highlights;};
float srgbLinear(float c){return c<=.04045?c/12.92:pow((c+.055)/1.055,2.4);}
float3 pq(float3 nits){float3 y=pow(clamp(nits,0,10000)/10000,.1593017578125);return pow((.8359375+18.8515625*y)/(1+18.6875*y),78.84375);}
float4 ps(float4 position:SV_Position):SV_Target {
    float3 rgb=scene.Load(int3(position.xy,0)).rgb;
    float3 c=float3(srgbLinear(rgb.r),srgbLinear(rgb.g),srgbLinear(rgb.b));
    float m=max(c.r,max(c.g,c.b));
    float gain=paper*(1+highlights*max(0,peak/paper-1)*m*m*m*m);
    float3 wide=mul(float3x3(.6274040,.3292820,.0433136,.0690970,.9195400,.0113612,.0163916,.0880132,.8955950),c);
    return float4(pq(min(wide*gain,max(peak,paper))),1);
}
)HLSL";
}
