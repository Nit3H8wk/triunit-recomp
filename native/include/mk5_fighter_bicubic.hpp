#pragma once
#include "mk5_stage_bicubic.hpp"

namespace mk5presentation {
struct FighterLayer {
    int x=0,y=0;
    unsigned width=0,height=0;
    bool smooth=false;
    std::vector<uint32_t> pixels;
    uint64_t order=0;
    template<class A> friend void Fields(A& a,FighterLayer& l){a(l.x,l.y,l.width,l.height,l.smooth,l.pixels,l.order);}
};

struct FighterFrame {
    uint64_t serial=0;
    std::vector<uint32_t> underlay,backdrop;
    std::vector<uint64_t> opaque_order;
    std::vector<uint8_t> covered;
    std::vector<FighterLayer> layers;
    template<class A> friend void Fields(A& a,FighterFrame& f){a(f.serial,f.underlay,f.backdrop,f.opaque_order,f.covered,f.layers);}
};

inline constexpr int fighter_margin=2;

inline std::vector<uint32_t> ScaleFighter4x(const FighterLayer& pose){
    if(!pose.width || !pose.height || pose.pixels.size()!=size_t(pose.width)*pose.height)
        throw std::logic_error("MK5 fighter pose geometry");
    constexpr unsigned scale=mk5stage::scale;
    const auto w=pose.width+2*fighter_margin,h=pose.height+2*fighter_margin;
    const auto stride=w*scale;
    const auto xtaps=mk5stage::BicubicAxis(w),ytaps=mk5stage::BicubicAxis(h);
    std::vector<uint32_t> horizontal(size_t(stride)*h);
    std::vector<uint32_t> row(w);
    for(unsigned y=0;y<pose.height;++y){
        for(unsigned x=0;x<pose.width;++x){
            const auto pixel=pose.pixels[size_t(y)*pose.width+x];
            const auto alpha=pixel>>24;
            if(alpha==0 || alpha==255){
                row[x+fighter_margin]=alpha?pixel:0;
                continue;
            }
            uint32_t premultiplied=alpha<<24;
            for(unsigned shift=0;shift<24;shift+=8)
                premultiplied|=((((pixel>>shift)&255)*alpha+127)/255)<<shift;
            row[x+fighter_margin]=premultiplied;
        }
        auto* output=horizontal.data()+size_t(y+fighter_margin)*stride;
        for(unsigned x=0;x<stride;++x){
            const auto& t=xtaps[x];
            output[x]=mk5stage::BicubicPixel<4>(row[t.index[0]],row[t.index[1]],
                                               row[t.index[2]],row[t.index[3]],t);
        }
    }
    std::vector<uint32_t> result(size_t(stride)*h*scale);
    mk5stage::ForRows(h*scale,[&](unsigned y){
        const auto& t=ytaps[y];
        const auto* a=horizontal.data()+size_t(t.index[0])*stride;
        const auto* b=horizontal.data()+size_t(t.index[1])*stride;
        const auto* c=horizontal.data()+size_t(t.index[2])*stride;
        const auto* d=horizontal.data()+size_t(t.index[3])*stride;
        auto* output=result.data()+size_t(y)*stride;
        for(unsigned x=0;x<stride;x+=scale)
            _mm_storeu_si128(reinterpret_cast<__m128i*>(output+x),mk5stage::BicubicTile<4>(a+x,b+x,c+x,d+x,t));
        for(unsigned x=0;x<stride;++x){
            const auto pixel=output[x];
            const auto alpha=pixel>>24;
            if(alpha && alpha!=255){
                uint32_t straight=alpha<<24;
                for(unsigned shift=0;shift<24;shift+=8)
                    straight|=std::min(255u,255*((pixel>>shift)&255)/alpha)<<shift;
                output[x]=straight;
            }
        }
    });
    return result;
}

inline void ComposeFighters4x(std::vector<uint32_t>& image,unsigned width,unsigned height,
                              const std::vector<FighterLayer>& layers,
                              const std::vector<uint64_t>& opaque_order={}){
    constexpr int scale=mk5stage::scale;
    const int w=int(width)*scale,h=int(height)*scale;
    if(!width || !height || image.size()!=size_t(w)*h ||
       (!opaque_order.empty() && opaque_order.size()!=size_t(width)*height))
        throw std::logic_error("MK5 fighter frame geometry");
    for(const auto& layer:layers){
        if(!layer.width || !layer.height || layer.pixels.size()!=size_t(layer.width)*layer.height)
            throw std::logic_error("MK5 fighter layer geometry");
        const int margin=layer.smooth?fighter_margin:0;
        const int left=(layer.x-margin)*scale,top=(layer.y-margin)*scale;
        const int stride=(int(layer.width)+2*margin)*scale;
        const int bottom=top+(int(layer.height)+2*margin)*scale;
        const auto scaled=layer.smooth?ScaleFighter4x(layer):std::vector<uint32_t>{};
        const int first=std::max(0,top),last=std::min(h,bottom);
        if(first<last)mk5stage::ForRows(unsigned(last-first),[&](unsigned row){const int y=first+int(row);
            for(int x=std::max(0,left);x<std::min(w,left+stride);++x){
                const auto source=layer.smooth?scaled[size_t(y-top)*stride+x-left]:
                    layer.pixels[size_t((y-top)/scale)*layer.width+(x-left)/scale];
                const auto alpha=source>>24;
                if(!alpha)continue;
                if(!opaque_order.empty() && opaque_order[size_t(y/scale)*width+x/scale]>=layer.order)
                    continue;
                auto& dest=image[size_t(y)*w+x];
                if(alpha==255){dest=source;continue;}
                uint32_t result=0xff000000;
                for(unsigned shift=0;shift<24;shift+=8){
                    const auto from=(source>>shift)&255,over=(dest>>shift)&255;
                    result|=((from*alpha+over*(255-alpha)+127)/255)<<shift;
                }
                dest=result;
            }
        });
    }
}

// Into result (every pixel written; mk5stage::Bicubic4x keeps a same-sized result's memory).
inline void ComposeFighterFrame4x(const FighterFrame& frame,unsigned width,unsigned height,std::vector<uint32_t>& result){
    constexpr unsigned scale=mk5stage::scale;
    const size_t area=size_t(width)*height;
    if(!frame.serial || frame.underlay.size()!=area || frame.covered.size()!=area ||
       frame.opaque_order.size()!=area || frame.layers.empty())
        throw std::logic_error("MK5 incomplete fighter frame");
    if(frame.backdrop.empty())result.resize(area*scale*scale);
    else mk5stage::Bicubic4x(frame.underlay,frame.backdrop,width,height,result);
    mk5stage::ForRows(height*scale,[&](unsigned y){
        for(unsigned x=0;x<width;++x){
            const auto pixel=size_t(y/scale)*width+x;
            auto* tile=result.data()+size_t(y)*width*scale+x*scale;
            if(frame.backdrop.empty())std::fill_n(tile,scale,frame.underlay[pixel]&0xffffff);
            if(frame.covered[pixel])
                for(unsigned dx=0;dx<scale;++dx)tile[dx]|=0xff000000;
        }
    });
    ComposeFighters4x(result,width,height,frame.layers,frame.opaque_order);
}
inline std::vector<uint32_t> ComposeFighterFrame4x(const FighterFrame& frame,unsigned width,unsigned height){
    std::vector<uint32_t> result;ComposeFighterFrame4x(frame,width,height,result);return result;
}
}
