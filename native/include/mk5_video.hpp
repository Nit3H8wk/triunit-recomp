#pragma once
#include "mk5_crt.hpp"
#include <cstdint>
#include <string_view>

namespace mk5video {
enum class Sampling { nearest, linear, sharp_bilinear, bicubic };
inline constexpr std::array<std::string_view,4> sampling_names{"nearest","linear","sharp-bilinear","bicubic"};

inline mk5crt::Viewport scaled_viewport(mk5crt::Viewport bounds,mk5crt::Viewport fit,unsigned width,unsigned height,unsigned mode){
    if(!mode || !width || !height)return fit;
    const float pixel_width=mode==5?height*4.f/3:float(width);
    unsigned factor=unsigned(std::min(bounds.width/pixel_width,bounds.height/height));
    if(!factor)return fit;
    if(mode>=2 && mode<=4)factor=std::min(mode,factor);
    const float w=std::floor(pixel_width*factor+.5f),h=float(height*factor);
    return {std::floor(bounds.x+(bounds.width-w)/2),std::floor(bounds.y+(bounds.height-h)/2),w,h};
}

struct CubicAxis{int first;std::array<float,4> weights;};
inline CubicAxis cubic_axis(float uv,unsigned size){
    const float at=uv*size-.5f;
    const int cell=int(std::floor(at));
    const float t=at-cell;
    const auto kernel=[](float d){
        return d<=1?(1.5f*d-2.5f)*d*d+1:((-0.5f*d+2.5f)*d-4)*d+2;
    };
    return {cell-1,{kernel(1+t),kernel(t),kernel(1-t),kernel(2-t)}};
}
template<class Fetch>
std::array<float,3> cubic_axis_sample(const CubicAxis& axis,Fetch fetch){
    std::array<float,3> rgb{};
    for(int i=0;i<4;++i){
        const auto pixel=fetch(axis.first+i);
        for(unsigned c=0;c<3;++c)rgb[c]+=axis.weights[i]*pixel[c];
    }
    return rgb;
}

// Scalar oracle for the final DX12 sampling, with the same edge extension.
template<class Fetch>
std::array<float,3> reconstruct(Sampling filter,float u,float v,unsigned width,unsigned height,float out_width,float out_height,Fetch fetch){
    if(filter==Sampling::nearest)return fetch(mk5crt::sample_index(u*width),mk5crt::sample_index(v*height));
    if(filter==Sampling::bicubic){
        const auto x=cubic_axis(u,width),y=cubic_axis(v,height);
        auto rgb=cubic_axis_sample(y,[&](int sy){return cubic_axis_sample(x,[&](int sx){return fetch(sx,sy);});});
        for(float& value:rgb)value=std::clamp(value,0.f,1.f);
        return rgb;
    }
    auto position=[&](float uv,unsigned size,float output){
        float p=uv*size;
        if(filter==Sampling::sharp_bilinear){
            const float scale=std::max(1.f,std::floor(output/size));
            const float cell=std::floor(p),f=p-cell,edge=.5f/scale;
            p=cell+.5f+(f-std::clamp(f,edge,1-edge))*scale;
        }
        return p-.5f;
    };
    const float x=position(u,width,out_width),y=position(v,height,out_height);
    const int ix=int(std::floor(x)),iy=int(std::floor(y));
    const float tx=x-ix,ty=y-iy;
    std::array<float,3> rgb{};
    const auto a=fetch(ix,iy),b=fetch(ix+1,iy),c=fetch(ix,iy+1),d=fetch(ix+1,iy+1);
    for(unsigned k=0;k<3;++k)rgb[k]=(a[k]*(1-tx)+b[k]*tx)*(1-ty)+(c[k]*(1-tx)+d[k]*tx)*ty;
    return rgb;
}

inline void reference_prefilter(std::vector<uint32_t>& source,unsigned width,unsigned height,unsigned cas,unsigned bilateral){
    const bool sharpen=cas!=0;
    std::array<float,256> values{};
    for(unsigned i=0;i<values.size();++i)values[i]=sharpen?mk5crt::srgb_decode(i/255.f):i/255.f;
    auto fetch=[&](int x,int y){
        const auto rgb=source[size_t(std::clamp(y,0,int(height)-1))*width+std::clamp(x,0,int(width)-1)];
        return std::array<float,3>{values[rgb&255],values[(rgb>>8)&255],values[(rgb>>16)&255]};
    };
    const float strength=cas/100.f,peak=-strength/(8-3*strength);
    const float smooth=.65f*bilateral/100;
    std::vector<uint32_t> output(source.size());
    for(int y=0;y<int(height);++y)for(int x=0;x<int(width);++x){
        const auto center=fetch(x,y);
        auto rgb=center;
        if(sharpen){
            auto lo=center,hi=center,minimum=center,maximum=center;
            std::array<float,3> cross{};
            for(int j=-1;j<=1;++j)for(int i=-1;i<=1;++i){
                const auto tap=fetch(x+i,y+j);
                for(unsigned c=0;c<3;++c){
                    minimum[c]=std::min(minimum[c],tap[c]);maximum[c]=std::max(maximum[c],tap[c]);
                    if((i==0)!=(j==0)){
                        lo[c]=std::min(lo[c],tap[c]);hi[c]=std::max(hi[c],tap[c]);cross[c]+=tap[c];
                    }
                }
            }
            for(unsigned c=0;c<3;++c){
                const float dark=lo[c]+minimum[c],light=hi[c]+maximum[c];
                const float w=peak*std::sqrt(std::clamp(std::min(dark,2-light)/std::max(light,1e-7f),0.f,1.f));
                rgb[c]=mk5crt::srgb_encode(std::clamp((center[c]+w*cross[c])/(1+4*w),0.f,1.f));
            }
        }else{
            float weights=0;
            rgb={};
            for(int j=-1;j<=1;++j)for(int i=-1;i<=1;++i){
                const auto tap=fetch(x+i,y+j);
                float distance=0;
                for(unsigned c=0;c<3;++c)distance+=(tap[c]-center[c])*(tap[c]-center[c]);
                const float w=std::exp(-(i*i+j*j)/1.62f-distance/.0288f);
                for(unsigned c=0;c<3;++c)rgb[c]+=w*tap[c];
                weights+=w;
            }
            for(unsigned c=0;c<3;++c)rgb[c]=center[c]+smooth*(rgb[c]/weights-center[c]);
        }
        uint32_t pixel=0xff000000;
        for(unsigned c=0;c<3;++c)pixel|=uint32_t(std::lround(255*rgb[c]))<<(8*c);
        output[size_t(y)*width+x]=pixel;
    }
    source.swap(output);
}
}
