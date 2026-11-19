#pragma once
#include "mk5_fighter_bicubic.hpp"
#include <map>
#include <utility>

namespace mk5presentation {
class FighterSlots {
    uint64_t next_=0;
    std::map<uint32_t,uint64_t> live_;
    template<class A> friend void Fields(A& a,FighterSlots& s){a(s.next_,s.live_);}
public:
    void Bind(uint32_t slot){
        if(live_.try_emplace(slot,next_+1).second)++next_;
    }
    void Forget(uint32_t slot){live_.erase(slot);}
    void Clear(){live_.clear();}
    uint64_t Generation(uint32_t slot)const{
        const auto found=live_.find(slot);
        return found==live_.end()?0:found->second;
    }
    const auto& Live()const{return live_;}
};

// Each pixel only needs its latest opaque writer to test which fighter layers
// can contribute. Fighter texels behind that writer still feed neighboring taps.
class FighterSurface {
    friend class FighterCapture;
    static constexpr unsigned stride=512;
    static constexpr size_t row_limit=stride*16;
    struct Opaque { uint64_t order=0; uint32_t blood=0; uint16_t pen=0;
        template<class A> friend void Fields(A& a,Opaque& o){a(o.order,o.blood,o.pen);} };
    struct Texel { uint64_t order; uint16_t x,pen;
        template<class A> friend void Fields(A& a,Texel& t){a(t.order,t.x,t.pen);} };
    struct Row { std::vector<Texel> texels; bool overflow=false;
        template<class A> friend void Fields(A& a,Row& r){a(r.texels,r.overflow);} };
    std::vector<Opaque> opaque_;
    std::vector<Row> rows_;
    uint64_t order_=0,owner_=0;
    // Save-state value fields (native/mk2/mk2_save_state.hpp); presence (enabled) is part of the state.
    template<class A> friend void Fields(A& a,FighterSurface& s){a(s.opaque_,s.rows_,s.order_,s.owner_);}
public:
    struct DrawToken { uint64_t owner,order=0; };
    explicit FighterSurface(size_t pixels=0):opaque_(pixels),rows_(pixels/stride){}
    bool enabled() const {return !rows_.empty();}
    DrawToken Draw(uint64_t owner) const {return {owner};}
    // The floor blood an actor draw covered at `pixel` (its underlay where a texel covers it), 0 = none.
    uint32_t Blood(size_t pixel) const {return enabled()?opaque_[pixel].blood:0;}

    // Opaque pens use bit 15 for scenery; actor pens use the native palette index.
    void Write(DrawToken& draw,size_t pixel,uint16_t pen,uint32_t covered_blood=0){
        if(!enabled())return;
        if(!draw.order){
            if(!order_ || owner_!=draw.owner)++order_;
            owner_=draw.owner;
            draw.order=order_;
        }
        auto& base=opaque_[pixel];
        if(!draw.owner){
            base={draw.order,0,pen};
            return;
        }
        if(covered_blood)base.blood=covered_blood;
        auto& row=rows_[pixel/stride];
        if(row.texels.size()==row_limit)row.overflow=true;
        if(!row.overflow)row.texels.push_back({draw.order,uint16_t(pixel%stride),uint16_t(pen&0x7fff)});
    }

    template<class Pen>
    void ClearWith(size_t begin,size_t count,Pen pen){
        if(!enabled() || !count)return;
        ++order_;owner_=0;
        for(size_t first=begin;first<begin+count;){
            const size_t last=std::min((first/stride+1)*stride,begin+count);
            auto& row=rows_[first/stride];
            const auto from=first%stride,to=from+last-first;
            if(from==0 && to==stride){
                row.texels.clear();
                row.overflow=false;
            }else{
                auto& texels=row.texels;
                texels.erase(std::remove_if(texels.begin(),texels.end(),
                    [from,to](const Texel& p){return p.x>=from && p.x<to;}),texels.end());
            }
            for(size_t i=first;i<last;++i)opaque_[i]={order_,0,pen(i-begin)};
            first=last;
        }
    }
    void Clear(size_t begin,size_t count,uint16_t pen){
        ClearWith(begin,count,[pen](size_t){return pen;});
    }
};

class FighterCapture {
    struct Sample {int x;unsigned y;uint32_t rgb;};
    struct Layer {
        int left,right;
        unsigned top,bottom;
        std::vector<Sample> samples;
        template<class A> friend void Fields(A& a,Layer& l){a(l.left,l.right,l.top,l.bottom,l.samples);}
    };
    unsigned width_=0,height_=0,rows_=0;
    bool valid_=false;
    FighterFrame frame_; // After Complete it holds the swapped-out frame, whose buffers the next Begin reuses.
    std::map<uint64_t,Layer> layers_;
    template<class A> friend void Fields(A& a,FighterCapture& c){a(c.width_,c.height_,c.rows_,c.valid_,c.frame_,c.layers_);}

    bool CanContribute(const Layer& layer,uint64_t order)const{
        const int left=std::max(0,layer.left-fighter_margin);
        const int right=std::min(int(width_),layer.right+fighter_margin);
        const int top=std::max(0,int(layer.top)-fighter_margin);
        const int bottom=std::min(int(height_),int(layer.bottom)+fighter_margin);
        for(int y=top;y<bottom;++y){
            const auto* row=frame_.opaque_order.data()+size_t(y)*width_;
            if(std::any_of(row+left,row+right,[order](uint64_t opaque){return opaque<order;}))
                return true;
        }
        return false;
    }
public:
    void Begin(unsigned width,unsigned height){
        width_=width;height_=height;rows_=0;valid_=true;
        const auto area=size_t(width)*height;
        frame_.layers.clear();
        frame_.underlay.resize(area);
        frame_.backdrop.resize(area);
        frame_.opaque_order.resize(area);
        frame_.covered.assign(area,0);
        layers_.clear();
    }

    template<class Palette>
    void Line(const FighterSurface& surface,unsigned y,size_t row,unsigned column,
              const uint32_t* presented,const uint32_t* backdrop,Palette rgb,bool enabled=true){
        if(!valid_)return;
        constexpr unsigned stride=FighterSurface::stride;
        if(y!=rows_ || y>=height_ || row%stride || width_>stride || row/stride>=surface.rows_.size()){
            valid_=false;
            return;
        }
        ++rows_;
        const auto& layer_row=surface.rows_[row/stride];
        if(enabled && layer_row.overflow){valid_=false;return;}
        const size_t dest=size_t(y)*width_;
        column%=stride;
        for(unsigned x=0;x<width_;++x){
            const auto index=row+(column+x)%stride;
            frame_.underlay[dest+x]=presented[x]&0xffffff;
            frame_.backdrop[dest+x]=backdrop?backdrop[x]:0;
            frame_.opaque_order[dest+x]=enabled?surface.opaque_[index].order:UINT64_MAX;
        }
        if(!enabled)return;
        for(const auto& texel:layer_row.texels){
            int x=int((texel.x+stride-column)%stride);
            if(x>=int(stride)-fighter_margin)x-=int(stride);
            if(x>=int(width_)+fighter_margin)continue;
            auto& layer=layers_.try_emplace(texel.order,Layer{x,x+1,y,y+1,{}}).first->second;
            layer.left=std::min(layer.left,x);layer.right=std::max(layer.right,x+1);
            layer.bottom=y+1;
            layer.samples.push_back({x,y,0xff000000|(rgb(texel.pen)&0xffffff)});
            if(x<0 || x>=int(width_))continue;
            if(texel.order<=frame_.opaque_order[dest+x] || frame_.covered[dest+x])continue;
            const auto& base=surface.opaque_[row+texel.x];
            const auto color=base.blood?base.blood:rgb(base.pen&0x7fff);
            frame_.covered[dest+x]=1;
            frame_.underlay[dest+x]=color&0xffffff;
            if(base.blood)frame_.backdrop[dest+x]&=~mk5stage::scenery;
            else if(base.pen&0x8000)frame_.backdrop[dest+x]=(color&0xffffff)|mk5stage::scenery;
        }
    }

    void Complete(uint64_t serial,FighterFrame& output){
        if(!valid_ || rows_!=height_ || layers_.empty()){
            output.serial=0;
            output.layers.clear();
            return;
        }
        frame_.serial=serial;
        for(const auto& [order,layer]:layers_){
            if(!CanContribute(layer,order))continue;
            const unsigned width=unsigned(layer.right-layer.left),height=layer.bottom-layer.top;
            FighterLayer pose{layer.left,int(layer.top),width,height,true,
                              std::vector<uint32_t>(size_t(width)*height),order};
            for(const auto& p:layer.samples)
                pose.pixels[size_t(p.y-layer.top)*width+unsigned(p.x-layer.left)]=p.rgb;
            frame_.layers.push_back(std::move(pose));
        }
        if(frame_.layers.empty()){
            output.serial=0;
            output.layers.clear();
            return;
        }
        if(std::none_of(frame_.backdrop.begin(),frame_.backdrop.end(),
                        [](uint32_t pixel){return pixel&mk5stage::scenery;}))
            frame_.backdrop.clear();
        std::swap(frame_,output);
    }
};
}
