#pragma once
#include "mk2_board.hpp"
#include "mk2_program.hpp"
#include "mk2_widescreen.hpp"
#include "../include/mk5_fighter_video.hpp"
#include "../include/mk5_blood_shade.hpp"
#include <algorithm>
#include <map>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

namespace mk2 {
inline uint32_t ExpandRgb555(uint16_t color) {
    const auto expand=[](unsigned value){return (value<<3)|(value>>2);};
    return 0xff000000|(expand((color>>10)&31)<<16)|(expand((color>>5)&31)<<8)|expand(color&31);
}
struct BootVideo {
    std::vector<uint16_t> palette_ram = std::vector<uint16_t>(32768);
    std::vector<uint16_t> vram = std::vector<uint16_t>(524288);
    std::array<uint16_t, 4096> shift_register{};
    uint16_t dma_palette = 0;
    std::array<uint16_t, 18> dma_registers{};
    static constexpr uint16_t backdrop_owner=0x8000;
    void EnableBackdrop(){backdrop.resize(vram.size());}
    void EnableFighters(){fighters_enabled=true;}
    bool FightersEnabled()const{return fighters_enabled;}
    const mk5presentation::FighterSurface& FighterVideo()const{return fighters;}
    uint64_t FighterGeneration(uint32_t object)const{return fighter_objects.Generation(object);}
    void BindFighter(uint32_t object){
        if(fighters_enabled && object>=0x0102d6f0 && object<0x0105b950 &&
           (object-0x0102d6f0)%0x210==0)fighter_objects.Bind(object);
    }
    void ForgetFighter(uint32_t object){fighter_objects.Forget(object);}
    void ResetFighters(){fighter_objects.Clear();}
    bool BackdropEnabled()const{return !backdrop.empty();}
    uint16_t BackdropPixel(size_t index)const{return backdrop[index];}
    bool backdrop_list=false,world_object_list=false;
    struct DrawOwner {bool scenery=false;uint64_t fighter=0;
        template<class A> friend void Fields(A& a,DrawOwner& o){a(o.scenery,o.fighter);}};
    void StageDraw(uint32_t cursor,DrawOwner owner){
        if(owner.scenery || owner.fighter)draw_queue[cursor]=owner;
        else draw_queue.erase(cursor);
    }
    DrawOwner TakeDraw(uint32_t cursor){
        auto node=draw_queue.extract(cursor);
        return node.empty()?DrawOwner{}:node.mapped();
    }
    void ResetDrawQueue(){draw_queue.clear();}
    void CopyBackdrop(size_t index,size_t count,bool scenery){
        fighters.ClearWith(index,count,[this,index,scenery](size_t x){
            return uint16_t((vram[index+x]&0x7fff)|(scenery?backdrop_owner:0));
        });
        if(!BackdropEnabled())return;
        std::transform(vram.begin()+index,vram.begin()+index+count,backdrop.begin()+index,
            [scenery](uint16_t pen){return uint16_t((pen&0x7fff)|(scenery?backdrop_owner:0));});
    }
    void EnableBlood(const Program& program) {
        const auto word=[&](uint32_t bit) {
            const size_t index=(bit-0xff800000u)/8;
            return uint16_t(program.bytes.at(index)|(unsigned(program.bytes.at(index+1))<<8));
        };
        constexpr uint32_t frame=0xffbecd10;
        const auto width=word(frame), height=word(frame+16);
        if(width!=35 || height!=11)throw std::runtime_error("MK2 invalid original floor splash");
        // Use the board's compressed-row DMA with the final frame's exact command and source.
        BootVideo decoded;
        BoardBootControls board;
        auto& r=decoded.dma_registers;
        r[2]=word(frame+64); r[3]=word(frame+80);
        r[6]=width; r[7]=height; r[13]=height-1; r[17]=width-1;
        decoded.StartDma(word(frame+96)|0x8002,board,program.graphics);
        for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x) {
            const auto pixel=decoded.vram[y*512+x];
            if(pixel>=BloodPalette{}.size())throw std::runtime_error("MK2 invalid floor splash palette index");
            blood_pixels[y*width+x]=uint8_t(pixel);
        }
        blood_layer.resize(vram.size());
        blood_pen.resize(vram.size());
        blood_floor.resize(vram.size());
    }
    bool BloodEnabled()const { return !blood_layer.empty(); }
    void ClearBlood() {
        blood_stains.clear();
        std::fill(blood_layer.begin(),blood_layer.end(),0);
        std::fill(blood_pen.begin(),blood_pen.end(),0);
        std::fill(blood_floor.begin(),blood_floor.end(),0);
        std::fill(wide_blood_.begin(),wide_blood_.end(),0);
        blood_draw.cursor=0;
    }
    void KeepBlood(int16_t x,int16_t y,bool flip,uint16_t palette) {
        if(!BloodEnabled())return;
        // The next object can reuse this slot as soon as the original removes the splash.
        auto& colors=blood_stains[{x,y,flip}].colors;
        std::copy_n(palette_ram.begin()+(palette&0x7f00),colors.size(),colors.begin());
    }
    // The palette fades of the program dim the stains in the scanout (mk5_blood_shade.hpp): each stain pixel keeps the
    // pen of the word it first covers here and that pen's brightness through the palette of this draw.
    void DrawBlood(uint32_t page,uint32_t camera,uint32_t clip_start,uint32_t clip_end,bool visible=true) {
        if(blood_stains.empty())return;
        const unsigned page_x=uint16_t(page), page_y=page>>16;
        if(page_y!=0 && page_y!=256)return;
        std::fill_n(blood_layer.begin()+page_y*512,256*512,0);
        // Widescreen: the stains over the wide window too (screen x -56+d .. 456+d, layer column page_x+x-d), into the wide
        // blood layer; the stains' own state (the pen they first cover) stays the arcade's.
        const bool wide=!wide_.empty();
        if(wide){wide_blood_.resize(vram.size());std::fill_n(wide_blood_.begin()+page_y*512,256*512,0);}
        if(!visible)return;
        const int camera_x=int16_t(camera),camera_y=int16_t(camera>>16);
        const int left=uint16_t(clip_start),top=clip_start>>16;
        const int right=uint16_t(clip_end),bottom=clip_end>>16;
        for(auto& [pose,stain]:blood_stains) {
            const auto [origin_x,origin_y,flip]=pose;
            for(int dy=0;dy<11;++dy) {
                const int y=origin_y-camera_y+dy;
                if(y<top || y>=bottom || y>=256)continue;
                for(int dx=0;dx<35;++dx) {
                    const int x=origin_x-camera_x+dx;
                    const size_t k=size_t(dy*35+(flip?34-dx:dx));
                    const auto shade=blood_pixels[k];
                    if(!shade)continue;
                    if(wide){
                        const int column=int(page_x)+x-wide_shift;
                        if(column>=0 && column<512 && x>=wide_shift-mk2::wide::kMargin && x<400+mk2::wide::kMargin+wide_shift)
                            wide_blood_[(page_y+y)*512+size_t(column)]=uint16_t(stain.colors[shade]|0x8000);
                    }
                    if(x<left || x>=right || x+int(page_x)>=512)continue;
                    const size_t i=(page_y+y)*512+page_x+x;
                    if(!stain.pen[k]){
                        stain.pen[k]=uint16_t(vram[i]|mk5blood::kTaken);
                        stain.floor[k]=uint8_t(mk5blood::Sum(palette_ram[vram[i]&0x7fff]));
                    }
                    blood_layer[i]=stain.colors[shade]|0x8000;
                    blood_pen[i]=stain.pen[k];
                    blood_floor[i]=stain.floor[k];
                }
            }
        }
    }
    uint32_t BloodPixel(size_t index)const {
        const auto pixel=BloodEnabled()?blood_layer[index]:0;
        return pixel?ExpandRgb555(uint16_t(pixel)):0;
    }
    // The floor of the stain word at `index` (meaningful where BloodPixel is not 0): pen | kTaken and its brightness then.
    uint16_t BloodPen(size_t index)const { return blood_pen.empty()?0:blood_pen[index]; }
    uint8_t BloodFloor(size_t index)const { return blood_floor.empty()?0:blood_floor[index]; }
    void MaskBlood(size_t index,size_t count=1) {
        if(BloodEnabled())std::fill_n(blood_layer.begin()+index,count,0);
    }
    void QueueBloodDraw(uint32_t cursor,uint32_t page,uint32_t camera,
                        uint32_t clip_start,uint32_t clip_end,bool visible) {
        if(!blood_stains.empty())blood_draw={cursor,page,camera,clip_start,clip_end,visible};
    }
    void DrawQueuedBlood(uint32_t cursor) {
        if(!blood_draw.cursor || blood_draw.cursor!=cursor)return;
        DrawBlood(blood_draw.page,blood_draw.camera,blood_draw.clip_start,blood_draw.clip_end,blood_draw.visible);
        blood_draw.cursor=0;
    }
    void WriteDma(unsigned offset, uint16_t data, BoardBootControls& board, uint16_t mask = 0xffff) {
        if (offset == 1) board.WriteDmaCommand(data, mask);
        else if (offset == 8)
            dma_palette = uint16_t((dma_palette & uint16_t(~mask)) | (data & mask));
        else if (offset == 12 || offset == 13 || offset == 15) {
            const unsigned physical = offset != 15 && !(dma_registers[15] & 0x20) ? offset + 4 : offset;
            auto& word = dma_registers[physical];
            word = uint16_t((word & uint16_t(~mask)) | (data & mask));
        }
        else if (offset <= 11 || offset == 14) {
            auto& word = dma_registers[offset];
            word = uint16_t((word & uint16_t(~mask)) | (data & mask));
        } else throw std::runtime_error("MK2 DMA register outside qualified video initialization");
    }
    uint16_t ReadDma(unsigned offset, const BoardBootControls& board) const {
        if (offset == 0 || offset == 1) return board.dma_command;
        if (offset == 8) return dma_palette;
        if (offset <= 15) return dma_registers[offset];
        throw std::runtime_error("MK2 DMA register outside qualified video initialization");
    }
    // The board's DMA over registers r (the destination clip in r12/r13 and r16/r17) and the palette register: every pixel
    // goes to put(index, pen, write), first with write false (the whole draw is validated before any change), then true;
    // between() runs between the passes. Returns the pixels the DMA timing charges.
    template<class Put,class Between>
    static unsigned Render(uint16_t command,const std::array<uint16_t,18>& r,uint16_t palette_register,
                           const std::vector<uint8_t>& graphics,Put&& put,Between&& between) {
        // Measured commands plus the pinned finite unscaled sets below.
        // Validate the whole draw before framebuffer mutation.
        const bool fill=(command&15)==12;
        const bool opaque_copy=command==0x8423;
        bool known=opaque_copy;
        for(auto value : {0x9008,0xe002,0xe482,0xef82,0xe082,0xe282,0xd782,0xd182,0xd382,
                          0xec82,0xe882,0xee92,0xe192,0xe182,0xeb92,0xeb82,0xe012,0xe292,0xee82,0xc382,0xe092,
                          0xb002,0xc002,0xc012,0xe582,0xf002,0x900c,0xe982,0xf00c,
                          0xa00c,0xb082,0xb182,0xb582,0xd002,0xd082,0xd192,0xd282,0xd582,0xd682,0xd882,0xe098,0xe198,0xe382,0xe488,0xe492,0xe498,0xe588,0xe592,0xe598,0xe682,0xe692,0xe698,0xe782,0xe892,0xea82,0xea92,0xea98,0xed92,0xed98,
                          0xe088,0xe188,0xe792,0xd692,0xe008,0xe898,0xe992,0xe998,0xd592,0xe5b2,0xe888,0xa002,0xc082,0xc092,0xc192,0xc482,0xc582,0xc592,0xc692,0xd092,0xed82,0xe018,0xe988,0xe688,0xea88,0xc182,0xc492,0xca92,0xd012,0xd492})
            if(command==value) known=true;
        // Pinned unscaled 1..8bpp skip/copy: all16 pre/post pairs and both X directions tested.
        for(unsigned base : {0x8082u,0x9082u,0xa082u,0xb082u,0xc082u,0xd082u,0xe082u,0xf082u})
            for(unsigned pair=0;pair<16;++pair)
                for(unsigned flip : {0u,0x10u})
                    if(command==(base|(pair<<8)|flip))known=true;
        // Pinned uncompressed copy: both X directions and start/end skip encodings.
        for(unsigned base : {0x8002u,0x9002u,0xa002u,0xb002u,0xc002u,0xd002u,0xe002u,0xf002u})
            for(unsigned flags : {0u,0x10u,0x40u,0x50u})
                if(command==(base|flags))known=true;
        // Pinned 1..8bpp Y flip, all row-header pairs, both X directions and skip encodings.
        for(unsigned base : {0x80a2u,0x90a2u,0xa0a2u,0xb0a2u,0xc0a2u,0xd0a2u,0xe0a2u,0xf0a2u})
            for(unsigned pair=0;pair<16;++pair)
                for(unsigned flip : {0u,0x10u})
                    if(command==(base|(pair<<8)|flip))known=true;
        for(unsigned base : {0x8002u,0x9002u,0xa002u,0xb002u,0xc002u,0xd002u,0xe002u,0xf002u})
            for(unsigned flags : {0x20u,0x30u,0x60u,0x70u})
                if(command==(base|flags))known=true;
        // Pinned 6bpp skip/color: all pre/post pairs and independent X/Y flips.
        for(unsigned pair=0;pair<16;++pair)
            for(unsigned flips : {0u,0x10u,0x20u,0x30u})
                if(command==(0xe088u|(pair<<8)|flips))known=true;
        // Pinned non-skipping unscaled fill: all BPP encodings and independent X/Y flips.
        for(unsigned base : {0x800cu,0x900cu,0xa00cu,0xb00cu,0xc00cu,0xd00cu,0xe00cu,0xf00cu})
            for(unsigned flips : {0u,0x10u,0x20u,0x30u})
                if(command==(base|flips))known=true;
        // Pinned uncompressed nonzero-color: 1..8bpp, X/Y flips and both edge-skip encodings.
        for(unsigned base : {0x8008u,0x9008u,0xa008u,0xb008u,0xc008u,0xd008u,0xe008u,0xf008u})
            for(unsigned flags : {0u,0x10u,0x20u,0x30u,0x40u,0x50u,0x60u,0x70u})
                if(command==(base|flags))known=true;
        const unsigned xstep=r[10]?r[10]:0x100,ystep=r[11]?r[11]:0x100;
        const bool scaled=xstep!=0x100 || ystep!=0x100;
        // The secret-fighter route's D002 zoom reaches step 0x40. E002 uses the qualified shrink path.
        const bool scaled_copy=(command==0xd002 && xstep>=0x40) || (command==0xe002 && xstep>=0x100);
        if(!known || (scaled && (!scaled_copy || xstep!=ystep)) ||
           (!fill && graphics.empty()))
            throw std::runtime_error("MK2 pair DMA outside measured unscaled commands; command " +
                std::to_string(command) + "; xstep " + std::to_string(xstep) +
                "; ystep " + std::to_string(ystep));
        const unsigned encoded_bpp=(command>>12)&7;
        const unsigned bpp=encoded_bpp?encoded_bpp:8, mask=(1u<<bpp)-1;
        const bool skip=command&0x80, flip=command&0x10;
        const unsigned width=r[6]&0x3ff,height=r[7]&0x3ff;
        const unsigned startskip=command&0x40?r[0]&0xff:0, endskip=command&0x40?r[0]>>8:r[0];
        const unsigned palette=palette_register&0x7f00;
        uint32_t source=fill?0:r[2]|(uint32_t(r[3])<<16);
        if(source>=0xf8000000) source-=0xf8000000;
        if(source>=0x10000000) throw std::runtime_error("MK2 pair DMA source outside graphics mapping");
        auto extract=[&](uint32_t bit,unsigned bits) {
            return ((unsigned(graphics.at(bit/8))|(unsigned(graphics.at(bit/8+1))<<8))>>(bit&7))&bits;
        };
        if(scaled) {
            // D002 and E002 share the uncompressed scaler for nonzero pixels.
            auto render_scaled=[&](bool write) {
                unsigned sy=r[5]&0x1ff;
                const int end=(int(width)-int(endskip))*256;
                for(unsigned iy=0;iy<(height<<8);iy+=ystep,sy=(sy+1)&0x1ff) {
                    if(sy<(r[12]&0x1ff) || sy>(r[13]&0x1ff)) continue;
                    const uint32_t row_bit=source+(iy>>8)*width*bpp;
                    unsigned sx=r[4]&0x3ff;
                    for(int ix=0;ix<end;ix+=int(xstep),sx=(sx+1)&0x3ff) {
                        if(sx<(r[16]&0x3ff) || sx>(r[17]&0x3ff)) continue;
                        const auto pixel=extract(row_bit+unsigned(ix>>8)*bpp,mask);
                        if(pixel)put(size_t(sy)*512+sx,uint16_t(palette|pixel),write);
                    }
                }
            };
            render_scaled(false);
            between();
            render_scaled(true);
            return ((width<<8)/xstep)*((height<<8)/ystep);
        }
        auto render=[&](bool write) {
            uint32_t offset=source;
            unsigned sy=r[5]&0x1ff;
            for(unsigned y=0;y<height;++y,sy=(command&0x20?sy-1:sy+1)&0x1ff) {
                unsigned sx=r[4]&0x3ff, pre=0,post=0,ix=0;
                uint32_t bit=offset;
                int end=int(width);
                if(skip) {
                    const unsigned packed=extract(bit,0xff); bit+=8;
                    pre=(packed&15)<<((command>>8)&3); post=(packed>>4)<<((command>>10)&3);
                    sx=(flip?sx-pre:sx+pre)&0x3ff; ix=pre; end-=int(post);
                }
                if(sy>=(r[12]&0x1ff) && sy<=(r[13]&0x1ff)) {
                    if(ix<startskip) {bit+=(startskip-ix)*bpp; ix=startskip;}
                    if(end>int(width)-int(endskip)) end=int(width)-int(endskip);
                    for(;int(ix)<end;++ix,sx=(flip?sx-1:sx+1)&0x3ff,bit+=bpp) {
                        if(sx<(r[16]&0x3ff) || sx>(r[17]&0x3ff)) continue;
                        const auto pixel=fill?0u:extract(bit,mask);
                        if(fill || opaque_copy || pixel)
                            put(size_t(sy)*512+sx,uint16_t(palette|(fill || (command&15)==8?r[9]&0xff:pixel)),write);
                    }
                }
                if(skip) {
                    offset+=8;
                    if(width>pre+post) offset+=(width-pre-post)*bpp;
                } else offset+=width*bpp;
            }
        };
        render(false);
        between();
        render(true);
        return width*height;
    }

    unsigned StartDma(uint16_t command, BoardBootControls& board, const std::vector<uint8_t>& graphics,
                      bool scenery=false,uint64_t fighter=0) {
        auto draw=fighters.Draw(fighter);
        const auto prepare_fighter_surface=[&]{
            if(!fighter || !fighters_enabled || fighters.enabled())return;
            fighters=mk5presentation::FighterSurface(vram.size());
            fighters.ClearWith(0,vram.size(),[this](size_t pixel){
                const auto tag=BackdropEnabled()?backdrop[pixel]&backdrop_owner:0;
                return uint16_t((vram[pixel]&0x7fff)|tag);
            });
        };
        const auto present_pixel=[&](size_t index){
            fighters.Write(draw,index,uint16_t(vram[index]|(scenery?backdrop_owner:0)),
                           fighter?BloodPixel(index):0);
            MaskBlood(index);
            UpdateBackdrop(index,scenery);
        };
        const auto pixels=Render(command,dma_registers,dma_palette,graphics,[&](size_t index,uint16_t pen,bool write){
            auto& dest=vram.at(index);
            if(write){dest=pen;present_pixel(index);
                if(wide_mirror){const int x=int(index&511)-(wide_mirror_world?wide_page_shift[(index>>17)&1]:0);if(x>=0&&x<512)WideWrite((index&~size_t(511))+size_t(x),pen,!wide_mirror_world);}}
        },[&]{prepare_fighter_surface();});
        board.dma_command=command; board.io[18]&=uint16_t(~2);
        return pixels;
    }
    // Widescreen (mk2_task_batch.cpp): the frame as the shadow pass composes it over all 512 VRAM columns. Each frame starts
    // from its page as VRAM holds it at the queue reset (after the page clear); the shadow walk draws its entries with the
    // wide clip; every other draw of the frame (DMAs not staged by the walk, the page clear, CPU writes) is mirrored as it
    // happens. Not in save states (shortcut, until W4).
    bool margin_streamer=false,margin_streaming=false;   // the scenery streamer has run since the pool reset / is running
    uint32_t margin_fault_pc=0;   // the last fault's PC (bit 0: in the walk, bit 1: an exception)
    uint64_t margin_streamer_skips=0;   // frames whose shadow walk ran without the streamer
    uint64_t margin_faults=0;   // shadow passes left incomplete (an outside PC, a refused access, a refused DMA)
    bool wide_walk_drawn=false;   // this frame's walk entries are in the layer: their real DMAs are not mirrored
    bool wide_mirror=false;       // set around a real DMA that the layer takes too
    // The window offset of this frame (mk2::wide::WindowShift): the layer holds screen x -56+d .. 456+d; scenery draws move
    // by -d, screen-fixed ones (the HUD list, wide_hud, and the real drain's own entries) keep their place.
    int wide_shift=0;bool wide_hud=false,wide_mirror_world=false;   // a mirrored real DMA of scenery moves with its page
    std::array<int,2> wide_held{};     // the last shifting frame's camera x and offset (mode 5 keeps it)
    std::array<int,3> wide_limits{};   // the arena's last usable camera limits (min, max, valid)
    std::array<int,2> wide_page_shift{};unsigned wide_page=0;   // the offset each VRAM page was composed with
    int WideShiftOfRow(unsigned vram_row)const{return wide_page_shift[(vram_row>>8)&1];}
    unsigned WideFittedOfRow(unsigned vram_row)const{return wide_page_fitted[(vram_row>>8)&1];}
    // A page composed with an offset and not cleared since keeps its last composition, moved by the change of offset.
    void SetWideShift(int d){
        int& page_shift=wide_page_shift[wide_page];wide_shift=d;wide_kept=false;   // the shadow composes this build
        if(page_shift==d||wide_.empty()){page_shift=d;return;}
        const int move=d-page_shift;page_shift=d;   // the new column c shows the old column c+move
        const auto shift_rows=[&](auto& layer){
            if(!layer.empty())for(size_t y=size_t(wide_page)*256;y<size_t(wide_page)*256+256;++y){
                auto* row=layer.data()+y*512;
                if(move>0)std::copy(row+move,row+512,row);else std::copy_backward(row,row+512+move,row+512);
            }};
        shift_rows(wide_);shift_rows(wide_blood_);shift_rows(wide_fixed_);
    }
    std::array<bool,2> wide_cleared{{true,true}};   // the page clear ran on the page since its last build
    void MarkCleared(size_t index){if(!wide_.empty())wide_cleared[(index>>17)&1]=true;}
    // A frame with no build (the game drawing straight onto its pages, after a match): at the next display interrupt each
    // page composed with an offset turns back into its plain VRAM, offset 0 (EndUnbuiltFrame, at a frame boundary).
    bool wide_frame_started=false;
    // A build that kept a page's composition without the shadow composing it (a round's start: queue reset, no walk) also
    // turns that page back into its plain VRAM.
    bool wide_kept=false;
    void PlainPage(unsigned page){
        std::copy_n(vram.begin()+size_t(page)*256*512,256*512,wide_.begin()+size_t(page)*256*512);wide_page_shift[page]=0;wide_page_fitted[page]=0;
        if(!wide_blood_.empty())std::copy_n(blood_layer.begin()+size_t(page)*256*512,256*512,wide_blood_.begin()+size_t(page)*256*512);
        std::fill_n(wide_fixed_.begin()+size_t(page)*256*512,256*512,uint8_t(0));
    }
    void EndUnbuiltFrame(){
        if(wide_.empty())return;
        if(wide_kept){PlainPage(wide_page);wide_kept=false;}
        if(!wide_frame_started)for(unsigned page=0;page<2;++page)if(wide_page_shift[page])PlainPage(page);
    }
    std::vector<uint32_t> wide_walk_entries;   // queue cursors of the walk's entries this frame (real staging)
    // The table's marker: the shadow's entries after it wait (wide_pending) until the drain reaches the real entries after
    // it (from wide_post_key on), so the floor shadows drawn at the marker stay under the world objects, as in VRAM.
    bool wide_shadow_post=false,wide_real_post=false;uint32_t wide_post_key=0;bool wide_post_keyed=false;
    // How an entry reaches the layer: x moved by shift columns and, when width < 512, the columns [0, width) stretched to
    // the 512 (the per-plane fit, WidePlane).
    struct WideDraw{std::array<uint16_t,12> entry;int shift,width;bool fixed;};   // fixed: a screen-fixed (HUD) draw
    std::vector<WideDraw> wide_pending;
    // Per-plane fit: the entries of a far plane's list (mk2::wide::FitCamera) wait in wide_plane until the list ends
    // (WidePlane), so the plane is placed as a whole.
    struct WideStaged{std::array<uint16_t,12> entry;bool fresh;};
    bool wide_fit=false;std::vector<WideStaged> wide_plane;
    // The objects on the pool's free list when the shadow pass starts (sorted): one the shadow walk stages was built by the
    // shadow's own streamer run. The real streamer builds only every 8 frames, so such an object that reaches the arcade's
    // columns is not on the arcade screen yet (a fast plane pops in at the edge): it is left out, unless its plane is fitted.
    std::vector<uint32_t> wide_free;
    bool WideFresh(uint32_t object)const{return std::binary_search(wide_free.begin(),wide_free.end(),object);}
    // An entry's columns in the layer [first, last) from its x (10-bit DMA x read as -256..767), width, X step and flip.
    static std::pair<int,int> WideSpan(const std::array<uint16_t,12>& e){
        int x=e[4]&0x3ff;if(x>=768)x-=1024;
        const unsigned xstep=e[10]?e[10]:0x100;const int w=int(((e[6]&0x3ffu)<<8)/xstep),lo=e[1]&0x10?x-w+1:x;
        return {lo,lo+w};
    }
    bool WideOnArcade(const std::array<uint16_t,12>& e)const{
        const auto [lo,hi]=WideSpan(e);const int arcade=mk2::wide::kMargin-wide_shift;return hi>arcade&&lo<arcade+400;
    }
    std::array<unsigned,2> wide_page_fitted{};   // the planes fitted in each page's composition
    // Each far camera's ratio in this arena: its velocity and the world's in a frame where the world moved.
    int wide_world=0;   // this build's world camera x (mk2_task_batch.cpp)
    struct WideRatio{int64_t plane,world;};std::array<std::optional<WideRatio>,8> wide_ratio{};
    std::array<int,2> wide_ratio_limits{};const std::optional<WideRatio>* wide_plane_ratio=nullptr;
    void EnableWide(){wide_=vram;wide_fixed_.assign(vram.size(),0);}   // from what VRAM already holds
    bool WideEnabled()const{return !wide_.empty();}
    uint16_t WidePixel(size_t index)const{return wide_[index];}
    void StartWideFrame(unsigned page_row){
        wide_page=(page_row>>8)&1;
        // The frame starts from the VRAM page, offset 0, unless the page was composed with an offset and not cleared since:
        // then what the game left on it is that composition (VRAM holds it unshifted).
        wide_kept=!wide_cleared[wide_page]&&wide_page_shift[wide_page];   // valid only if the shadow composes this build
        if(!wide_kept)PlainPage(wide_page);
        wide_cleared[wide_page]=false;wide_shift=wide_page_shift[wide_page];wide_frame_started=true;
        wide_walk_entries.clear();wide_walk_drawn=false;wide_shadow_post=wide_real_post=wide_post_keyed=false;wide_pending.clear();
        wide_plane.clear();wide_fit=false;wide_page_fitted[wide_page]=0;
    }
    void MirrorWide(size_t start,size_t count){
        if(wide_.empty())return;
        std::copy_n(vram.begin()+start,count,wide_.begin()+start);
        if(!wide_blood_.empty())std::fill_n(wide_blood_.begin()+start,count,0);
        std::fill_n(wide_fixed_.begin()+start,count,uint8_t(0));
    }
    // A draw on the wide layer covers the floor stains there, as MaskBlood does in VRAM.
    // fixed: the pixel belongs to a screen-fixed (HUD) draw, which the window offset does not move (WideFixed).
    void WideWrite(size_t index,uint16_t pen,bool fixed=false){wide_[index]=pen;wide_fixed_[index]=fixed;if(!wide_blood_.empty())wide_blood_[index]=0;}
    bool WideFixed(size_t index)const{return wide_fixed_[index]!=0;}
    uint32_t WideBloodPixel(size_t index)const{const auto pixel=wide_blood_.empty()?0:wide_blood_[index];return pixel?ExpandRgb555(pixel):0;}
    // One entry staged by the shadow walk (r0..r11 as the queue holds them) with the board's current clip; false when the
    // board's DMA would refuse it (it then draws nothing).
    bool WideEntry(const std::array<uint16_t,12>& entry,const std::vector<uint8_t>& graphics,bool fresh=false){
        auto moved=entry;if(!wide_hud)moved[4]=uint16_t(moved[4]-wide_shift);
        if(wide_fit){wide_plane.push_back({moved,fresh});return true;}
        if(fresh&&WideOnArcade(moved))return true;
        return WidePlace({moved,0,512,wide_hud},graphics);
    }
    bool WidePlace(const WideDraw& draw,const std::vector<uint8_t>& graphics){
        if(wide_shadow_post){wide_pending.push_back(draw);return true;}
        return DrawWide(draw,graphics);
    }
    void FlushWide(const std::vector<uint8_t>& graphics){for(const auto& e:wide_pending)DrawWide(e,graphics);wide_pending.clear();}
    // A list or callback starts in the shadow walk: the waiting plane is placed. A far plane's list brings the address of its
    // camera word, its velocity and the world's (mk2::wide::kVelocityGap).
    bool WideList(bool fit,uint32_t camera,int32_t velocity,int32_t world_velocity,const std::vector<uint8_t>& graphics){
        const bool placed=WidePlane(graphics);wide_fit=fit;
        if(fit){
            if(wide_ratio_limits[0]!=wide_limits[0]||wide_ratio_limits[1]!=wide_limits[1]){   // another arena
                wide_ratio={};wide_ratio_limits={wide_limits[0],wide_limits[1]};}
            auto& ratio=wide_ratio[((camera-mk2::wide::kScrollFirst)/0x20)&7];wide_plane_ratio=&ratio;
            if(world_velocity)ratio=world_velocity>0?WideRatio{velocity,world_velocity}:WideRatio{-int64_t(velocity),-int64_t(world_velocity)};
        }
        return placed;
    }
    // Whether the arcade screen itself shows this end of the plane's art (layer column end, a left or right end) at some
    // camera position within the arena's limits, its scroll moving by its ratio. Unknown (the world has not moved in this
    // arena yet, or no limits): not shown.
    bool WideEndShown(int end,bool left_end)const{
        if(!wide_limits[2]||!wide_plane_ratio||!*wide_plane_ratio)return false;
        const auto& r=**wide_plane_ratio;
        const int64_t camera=std::clamp(wide_world,wide_limits[0],wide_limits[1]),screen=end-mk2::wide::kMargin+wide_shift;
        return left_end?screen*r.world+r.plane*(camera-wide_limits[0])>mk2::wide::kEndSlack*r.world
                       :screen*r.world-r.plane*(wide_limits[1]-camera)<(400-mk2::wide::kEndSlack)*r.world;
    }
    // The waiting plane: the hull of its art in layer columns, from what its entries draw inside the layer and from their
    // spans beyond it (the shadow reaches mk2::wide::kReach + 48 px past the window). A band (a plane that draws in every
    // column of the arcade's 400) whose art ends inside the layer, at an end the arcade screen never shows (WideEndShown),
    // is moved inside its art; only if the art is narrower than the 512 columns is it stretched to them. Any other plane
    // (sparse pieces, an end that belongs to the arena) is drawn as it is.
    bool WidePlane(const std::vector<uint8_t>& graphics){
        if(!wide_fit||wide_plane.empty()){wide_plane.clear();return true;}
        int hull_left=1<<20,hull_right=-(1<<20),drawn_left=512,drawn_right=0;std::array<bool,512> drawn{};
        for(const auto& [e,fresh]:wide_plane){
            const auto [lo,hi]=WideSpan(e);hull_left=std::min(hull_left,lo);hull_right=std::max(hull_right,hi);
            auto r=dma_registers;std::copy(e.begin(),e.end(),r.begin());
            try{Render(e[1],r,e[8],graphics,[&](size_t index,uint16_t,bool write){
                    if(write)return;
                    const int c=int(index&511);drawn[c]=true;drawn_left=std::min(drawn_left,c);drawn_right=std::max(drawn_right,c+1);},[]{});}
            catch(const std::runtime_error&){wide_plane.clear();return false;}
        }
        const int left=drawn_left>0?drawn_left:std::min(hull_left,0),right=drawn_right<512?drawn_right:std::max(hull_right,512);
        const int arcade=mk2::wide::kMargin-wide_shift;   // the arcade's first column in the layer
        const bool band=std::all_of(drawn.begin()+std::max(arcade,0),drawn.begin()+std::min(arcade+400,512),[](bool c){return c;});
        int shift=0,width=512;
        if(band&&left<=arcade&&right>=arcade+400&&(left>0||right<512)&&
           !(left>0&&WideEndShown(left,true))&&!(right<512&&WideEndShown(right,false))){
            if(right-left>=512)shift=left>0?-left:512-right;
            else{shift=-left;width=right-left;}
        }
        if(shift||width<512)++wide_page_fitted[wide_page];
        bool placed=true;
        for(const auto& [e,fresh]:wide_plane)if(shift||width<512||!fresh||!WideOnArcade(e))placed&=WidePlace({e,shift,width,false},graphics);
        wide_plane.clear();return placed;
    }
    bool DrawWide(const WideDraw& draw,const std::vector<uint8_t>& graphics){
        auto r=dma_registers;std::copy(draw.entry.begin(),draw.entry.end(),r.begin());r[4]=uint16_t(r[4]+draw.shift);
        try{
            Render(r[1],r,r[8],graphics,[&](size_t index,uint16_t pen,bool write){
                if(!write||index>=wide_.size())return;
                if(draw.width>=512){WideWrite(index,pen,draw.fixed);return;}
                const size_t row=index&~size_t(511),c=index&511;   // column c of the plane's art covers [c, c+1) * 512 / width
                for(size_t x=c*512/size_t(draw.width);x<(c+1)*512/size_t(draw.width)&&x<512;++x)WideWrite(row+x,pen);
            },[]{});
        }catch(const std::runtime_error&){return false;}
        return true;
    }
    std::array<uint16_t, 18> DmaRegisters(const BoardBootControls& board) const {
        auto result = dma_registers;
        result[1] = board.dma_command;
        result[8] = dma_palette;
        return result;
    }
    void WritePalette(uint32_t address, uint16_t data, uint16_t mask = 0xffff) {
        auto& word = palette_ram.at(PaletteOffset(address));
        word = uint16_t((word & uint16_t(~mask)) | (data & mask));
    }
    uint16_t ReadPalette(uint32_t address) const { return palette_ram.at(PaletteOffset(address)); }
    void WriteVram(uint32_t address, uint16_t data, const BoardBootControls& board,
                   uint16_t mask = 0xffff) {
        const unsigned offset = VramOffset(address);
        if (board.VideoBank()) {
            if (mask & 0x00ff) vram[offset] = uint16_t((data & 0xff) | ((dma_palette & 0xff) << 8));
            if (mask & 0xff00) vram[offset + 1] = uint16_t((data >> 8) | (dma_palette & 0xff00));
        } else {
            if (mask & 0x00ff) vram[offset] = uint16_t((vram[offset] & 0xff) | ((data & 0xff) << 8));
            if (mask & 0xff00) vram[offset + 1] = uint16_t((vram[offset + 1] & 0xff) | (data & 0xff00));
        }
        if (mask & 0x00ff) { fighters.Clear(offset,1,vram[offset]&0x7fff);MaskBlood(offset);UpdateBackdrop(offset,false); }
        if (mask & 0xff00) { fighters.Clear(offset+1,1,vram[offset+1]&0x7fff);MaskBlood(offset+1);UpdateBackdrop(offset+1,false); }
        if (mask & 0x00ff) MirrorWide(offset,1);
        if (mask & 0xff00) MirrorWide(offset+1,1);
    }
    uint16_t ReadVram(uint32_t address, const BoardBootControls& board) const {
        const unsigned offset = VramOffset(address);
        return board.VideoBank()
            ? uint16_t((vram[offset] & 0xff) | (vram[offset + 1] << 8))
            : uint16_t((vram[offset] >> 8) | (vram[offset + 1] & 0xff00));
    }
private:
    std::vector<uint16_t> backdrop,wide_,wide_blood_;   // wide_blood_: the floor stains over the wide layer
    std::vector<uint8_t> wide_fixed_;   // the wide layer's pixels a screen-fixed draw left
    bool fighters_enabled=false;
    mk5presentation::FighterSurface fighters;
    mk5presentation::FighterSlots fighter_objects;
    std::map<uint32_t,DrawOwner> draw_queue;
    void UpdateBackdrop(size_t index,bool scenery){
        if(!BackdropEnabled())return;
        if(scenery)backdrop[index]=vram[index]|backdrop_owner;
        else backdrop[index]&=~backdrop_owner;
    }
    struct BloodDraw { uint32_t cursor,page,camera,clip_start,clip_end; bool visible;
        template<class A> friend void Fields(A& a,BloodDraw& d){a(d.cursor,d.page,d.camera,d.clip_start,d.clip_end,d.visible);}
    } blood_draw{};
    using BloodPalette=std::array<uint16_t,12>;
    // The kept colours and, per splash pixel, the floor it first covered: pen | kTaken (0 = not drawn yet), Sum then.
    struct BloodStain { BloodPalette colors{}; std::array<uint16_t,35*11> pen{}; std::array<uint8_t,35*11> floor{};
        template<class A> friend void Fields(A& a,BloodStain& s){a(s.colors,s.pen,s.floor);} };
    std::array<uint8_t,35*11> blood_pixels{};
    std::map<std::tuple<int16_t,int16_t,bool>,BloodStain> blood_stains;
    std::vector<uint16_t> blood_layer;
    std::vector<uint16_t> blood_pen;    // per video RAM word under a stain: the floor of its splash pixel
    std::vector<uint8_t> blood_floor;
    // Save-state value fields (mk2_save_state.hpp). Which layers exist is the edition, checked by the file header;
    // blood_pixels is decoded from the program ROM by EnableBlood and stays with the live session.
    template<class A> friend void Fields(A& a,BootVideo& v){
        a(v.palette_ram,v.vram,v.shift_register,v.dma_palette,v.dma_registers,v.backdrop_list,v.world_object_list,
          v.backdrop,v.fighters,v.fighter_objects,v.draw_queue,v.blood_draw,v.blood_stains,v.blood_layer,v.blood_pen,v.blood_floor);
    }
    static unsigned PaletteOffset(uint32_t address) {
        if (address < 0x01800000 || address > 0x0187fff0 || (address & 15))
            throw std::runtime_error("MK2 palette access outside aligned mapped words");
        return (address - 0x01800000) / 16;
    }
    static unsigned VramOffset(uint32_t address) {
        if (address > 0x003ffff0 || (address & 15))
            throw std::runtime_error("MK2 VRAM access outside aligned mapped words");
        return address / 8;
    }
};
}
