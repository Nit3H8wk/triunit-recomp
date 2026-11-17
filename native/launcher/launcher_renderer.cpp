#include "launcher_renderer.hpp"
#include "../include/mk5_bezel.hpp"
#include <d3d12.h>
#include <dxgi1_4.h>
#include <d3dcompiler.h>
#include <wincodec.h>
#include <wrl/client.h>
#include <array>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <stdexcept>
#include <limits>

using Microsoft::WRL::ComPtr;
namespace mklauncher {
namespace {
void check(HRESULT hr,const char* action){if(FAILED(hr))throw std::runtime_error(std::string(action)+" HRESULT="+std::to_string(uint32_t(hr)));}
D3D12_RESOURCE_DESC buffer(UINT64 size){D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;d.Width=size;d.Height=1;d.DepthOrArraySize=1;d.MipLevels=1;d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;return d;}
constexpr const char* shader=R"(
cbuffer Draw:register(b0){float4 rect;float4 texrect;float4 tint;float4 params;};
struct V{float4 pos:SV_Position;float2 uv:TEXCOORD0;float2 local:TEXCOORD1;};
V vs(uint id:SV_VertexID){
    V o;float2 coords[6]={float2(0,0),float2(1,0),float2(0,1),float2(0,1),float2(1,0),float2(1,1)};
    float2 q=coords[id];float2 p=rect.xy+q*rect.zw;
    if(params.w==10){p=id==0?rect.xy:(id==1?rect.zw:texrect.xy);q=0.5;}
    o.pos=float4(p/params.xy*float2(2,-2)+float2(-1,1),0,1);o.uv=texrect.xy+q*texrect.zw;o.local=q;return o;
}
Texture2D image:register(t0);SamplerState imageSampler:register(s0);
float hash(float2 v){return frac(sin(dot(v,float2(127.1,311.7)))*43758.5453);}
float noise(float2 p){float2 i=floor(p),f=frac(p);f=f*f*(3-2*f);return lerp(lerp(hash(i),hash(i+float2(1,0)),f.x),lerp(hash(i+float2(0,1)),hash(i+1),f.x),f.y);}
float4 ps(V v):SV_Target {
    float t=params.z;float2 q=v.local;float4 c=image.Sample(imageSampler,v.uv)*tint;
    if(params.w==1){
        float x=(q.x-.5)*2;float y=q.y;
        float wobble=.15*sin(y*16-t*4)+.10*sin(y*31+t*5);
        float n=noise(float2(q.x*7,y*8+t*2));
        float fire=saturate((1-abs(x+wobble))*(y+.1)*2.2-(1-y)*.9+n*.4);
        float a=smoothstep(.25,.8,fire)*smoothstep(0,.16,y)*(1-smoothstep(.88,1,y));
        return float4(lerp(float3(1,.09,.005),float3(1,.8,.2),fire),a*tint.a);
    }
    if(params.w==2){float n=noise(float2(q.x*5+t*.02,q.y*3+t*.04));float a=n*n*smoothstep(0,.3,q.y)*(1-smoothstep(.5,1,q.y));return float4(tint.rgb,a*tint.a);}
    if(params.w==3){c.a*=pow(saturate(1-q.y),2)*.32;}
    if(params.w==4){c.rgb*=.78+.22*sin(q.y*320+sin(t*.4)*.5);c.a*=.14;}
    if(params.w==5){float d=length((q-.5)*2);return float4(tint.rgb,pow(saturate(1-d),2)*tint.a);}
    if(params.w==6){
        float2 s=rect.zw,p=(q-.5)*s;float r=min(texrect.x,min(s.x,s.y)*.5);float2 d=abs(p)-(s*.5-r);
        float dist=length(max(d,0))+min(max(d.x,d.y),0)-r;float a=saturate(.5-dist);
        if(texrect.y>0)a*=saturate(dist+texrect.y+.5);
        return float4(tint.rgb,a*tint.a);
    }
    return c;
}
)";
}

struct Renderer::Impl {
    HWND window;unsigned w=0,h=0;float layout_width=baseWidth,scale=1,ox=0,oy=0;uint64_t count=0;
    ComPtr<ID3D12Device> device;ComPtr<ID3D12CommandQueue> queue;ComPtr<IDXGISwapChain3> swap;
    ComPtr<ID3D12DescriptorHeap> rtvs,srvs;ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;ComPtr<ID3D12RootSignature> root;ComPtr<ID3D12PipelineState> pipeline;
    ComPtr<ID3D12Fence> fence;HANDLE event=nullptr;UINT64 serial=0;UINT stride=0,srvStride=0,last=0;
    std::array<ComPtr<ID3D12Resource>,2> targets;std::vector<ComPtr<ID3D12Resource>> textures;
    int white=0,font=0;std::array<float,256> advances{};
    bool recording=false,bezel_enabled=true;
    explicit Impl(HWND hwnd):window(hwnd){
        try{init();atlas();}catch(...){if(event)CloseHandle(event);event=nullptr;throw;}
    }
    ~Impl(){try{wait();}catch(...){/* Device loss is reported by the calling frame. */}if(event)CloseHandle(event);}
    void wait(){
        if(!serial||fence->GetCompletedValue()>=serial)return;
        check(fence->SetEventOnCompletion(serial,event),"launcher fence event");
        if(WaitForSingleObject(event,5000)!=WAIT_OBJECT_0){check(device->GetDeviceRemovedReason(),"launcher device removed");throw std::runtime_error("launcher GPU fence timeout");}
        check(device->GetDeviceRemovedReason(),"launcher device status");
    }
    void execute(bool synchronous=true){check(list->Close(),"launcher command close");ID3D12CommandList* commands=list.Get();queue->ExecuteCommandLists(1,&commands);check(queue->Signal(fence.Get(),++serial),"launcher fence signal");if(synchronous)wait();}
    void reset(){wait();check(allocator->Reset(),"launcher allocator reset");check(list->Reset(allocator.Get(),pipeline.Get()),"launcher commands reset");}
    ComPtr<ID3D12Resource> resource(D3D12_HEAP_TYPE type,D3D12_RESOURCE_DESC desc,D3D12_RESOURCE_STATES state){
        D3D12_HEAP_PROPERTIES props{};props.Type=type;props.CreationNodeMask=props.VisibleNodeMask=1;ComPtr<ID3D12Resource> r;
        check(device->CreateCommittedResource(&props,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&r)),"launcher resource");return r;
    }
    void barrier(ID3D12Resource* r,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after){D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;b.Transition.pResource=r;b.Transition.StateBefore=before;b.Transition.StateAfter=after;b.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;list->ResourceBarrier(1,&b);}
    void init(){
        ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"launcher DXGI factory");
        check(D3D12CreateDevice(nullptr,D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)),"launcher D3D12 hardware device");
        D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;check(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"launcher direct queue");
        check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"launcher fence");event=CreateEventW(nullptr,FALSE,FALSE,nullptr);if(!event)throw std::runtime_error("launcher fence event");
        check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)),"launcher allocator");
        check(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)),"launcher list");check(list->Close(),"launcher list initial close");
        DXGI_SWAP_CHAIN_DESC1 d{};d.Format=DXGI_FORMAT_B8G8R8A8_UNORM;d.SampleDesc.Count=1;d.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;d.BufferCount=2;d.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD;d.Scaling=DXGI_SCALING_STRETCH;d.Flags=DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT;
        ComPtr<IDXGISwapChain1> created;check(factory->CreateSwapChainForHwnd(queue.Get(),window,&d,nullptr,nullptr,&created),"launcher flip swapchain");check(created.As(&swap),"launcher swapchain3");check(swap->SetMaximumFrameLatency(1),"launcher latency");
        check(factory->MakeWindowAssociation(window,DXGI_MWA_NO_ALT_ENTER|DXGI_MWA_NO_WINDOW_CHANGES),"launcher window association");
        D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;hd.NumDescriptors=2;check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&rtvs)),"launcher RTV heap");stride=device->GetDescriptorHandleIncrementSize(hd.Type);
        hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=32;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&srvs)),"launcher SRV heap");srvStride=device->GetDescriptorHandleIncrementSize(hd.Type);
        D3D12_DESCRIPTOR_RANGE range{};range.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_SRV;range.NumDescriptors=1;
        D3D12_ROOT_PARAMETER parameters[2]{};parameters[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;parameters[0].DescriptorTable.NumDescriptorRanges=1;parameters[0].DescriptorTable.pDescriptorRanges=&range;parameters[0].ShaderVisibility=D3D12_SHADER_VISIBILITY_PIXEL;
        parameters[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;parameters[1].Constants.Num32BitValues=16;parameters[1].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
        D3D12_STATIC_SAMPLER_DESC s{};s.Filter=D3D12_FILTER_MIN_MAG_MIP_LINEAR;s.AddressU=s.AddressV=s.AddressW=D3D12_TEXTURE_ADDRESS_MODE_CLAMP;s.ComparisonFunc=D3D12_COMPARISON_FUNC_ALWAYS;s.MaxLOD=D3D12_FLOAT32_MAX;s.ShaderVisibility=D3D12_SHADER_VISIBILITY_PIXEL;
        D3D12_ROOT_SIGNATURE_DESC signature{};signature.NumParameters=2;signature.pParameters=parameters;signature.NumStaticSamplers=1;signature.pStaticSamplers=&s;
        ComPtr<ID3DBlob> compiled,errors;check(D3D12SerializeRootSignature(&signature,D3D_ROOT_SIGNATURE_VERSION_1,&compiled,&errors),"launcher root serialize");check(device->CreateRootSignature(0,compiled->GetBufferPointer(),compiled->GetBufferSize(),IID_PPV_ARGS(&root)),"launcher root");
        ComPtr<ID3DBlob> vs,ps;
        auto compile=[&](const char* entry,const char* model,ComPtr<ID3DBlob>& out){HRESULT hr=D3DCompile(shader,std::strlen(shader),"launcher_layers.hlsl",nullptr,nullptr,entry,model,D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&out,&errors);if(FAILED(hr)&&errors)throw std::runtime_error(std::string(static_cast<const char*>(errors->GetBufferPointer()),errors->GetBufferSize()));check(hr,"launcher HLSL");};
        compile("vs","vs_5_0",vs);compile("ps","ps_5_0",ps);
        D3D12_GRAPHICS_PIPELINE_STATE_DESC state{};state.pRootSignature=root.Get();state.VS={vs->GetBufferPointer(),vs->GetBufferSize()};state.PS={ps->GetBufferPointer(),ps->GetBufferSize()};
        auto& blend=state.BlendState.RenderTarget[0];blend.BlendEnable=TRUE;blend.SrcBlend=D3D12_BLEND_SRC_ALPHA;blend.DestBlend=D3D12_BLEND_INV_SRC_ALPHA;blend.BlendOp=D3D12_BLEND_OP_ADD;blend.SrcBlendAlpha=D3D12_BLEND_ONE;blend.DestBlendAlpha=D3D12_BLEND_INV_SRC_ALPHA;blend.BlendOpAlpha=D3D12_BLEND_OP_ADD;blend.RenderTargetWriteMask=D3D12_COLOR_WRITE_ENABLE_ALL;
        state.SampleMask=UINT_MAX;state.RasterizerState.FillMode=D3D12_FILL_MODE_SOLID;state.RasterizerState.CullMode=D3D12_CULL_MODE_NONE;state.RasterizerState.DepthClipEnable=TRUE;state.DepthStencilState.DepthFunc=D3D12_COMPARISON_FUNC_ALWAYS;state.PrimitiveTopologyType=D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;state.NumRenderTargets=1;state.RTVFormats[0]=d.Format;state.SampleDesc.Count=1;
        check(device->CreateGraphicsPipelineState(&state,IID_PPV_ARGS(&pipeline)),"launcher blend pipeline");
        white=add(1,1,{0xffffffff});resize();
    }
    void resize(){
        RECT rect{};GetClientRect(window,&rect);unsigned nw=std::max(1L,rect.right),nh=std::max(1L,rect.bottom);if(nw==w&&nh==h)return;
        wait();for(auto& target:targets)target.Reset();check(swap->ResizeBuffers(0,nw,nh,DXGI_FORMAT_UNKNOWN,DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT),"launcher resize");w=nw;h=nh;
        auto handle=rtvs->GetCPUDescriptorHandleForHeapStart();for(unsigned i=0;i<2;++i){check(swap->GetBuffer(i,IID_PPV_ARGS(&targets[i])),"launcher buffer");device->CreateRenderTargetView(targets[i].Get(),nullptr,handle);handle.ptr+=stride;}
        layout_width=std::clamp(float(w)*layoutHeight/h,baseWidth,wideWidth);
        scale=std::min(w/layout_width,h/layoutHeight);
        ox=(w-layout_width*scale)/2;oy=(h-layoutHeight*scale)/2;
    }
    int add(unsigned tw,unsigned th,const std::vector<uint32_t>& pixels){
        if(recording||textures.size()>=32||tw==0||th==0||pixels.size()!=size_t(tw)*th)throw std::runtime_error("launcher invalid texture upload");
        D3D12_RESOURCE_DESC td{};td.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;td.Width=tw;td.Height=th;td.DepthOrArraySize=1;td.MipLevels=1;td.Format=DXGI_FORMAT_B8G8R8A8_UNORM;td.SampleDesc.Count=1;
        auto image=resource(D3D12_HEAP_TYPE_DEFAULT,td,D3D12_RESOURCE_STATE_COPY_DEST);D3D12_PLACED_SUBRESOURCE_FOOTPRINT layout{};UINT64 bytes=0;device->GetCopyableFootprints(&td,0,1,0,&layout,nullptr,nullptr,&bytes);
        auto upload=resource(D3D12_HEAP_TYPE_UPLOAD,buffer(bytes),D3D12_RESOURCE_STATE_GENERIC_READ);void* mapped=nullptr;D3D12_RANGE noRead{0,0};check(upload->Map(0,&noRead,&mapped),"launcher map texture");
        for(unsigned y=0;y<th;++y){std::memcpy(static_cast<char*>(mapped)+layout.Offset+size_t(y)*layout.Footprint.RowPitch,pixels.data()+size_t(y)*tw,size_t(tw)*4);}
        upload->Unmap(0,nullptr);
        reset();D3D12_TEXTURE_COPY_LOCATION dest{};dest.pResource=image.Get();dest.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=upload.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=layout;
        list->CopyTextureRegion(&dest,0,0,0,&src,nullptr);barrier(image.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);execute();
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=td.Format;srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;srv.Texture2D.MipLevels=1;
        int id=int(textures.size());auto handle=srvs->GetCPUDescriptorHandleForHeapStart();handle.ptr+=size_t(id)*srvStride;device->CreateShaderResourceView(image.Get(),&srv,handle);textures.push_back(image);return id;
    }
    void atlas(){
        HDC dc=CreateCompatibleDC(nullptr);if(!dc)throw std::runtime_error("launcher font DC");
        BITMAPINFO info{};info.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);info.bmiHeader.biWidth=1024;info.bmiHeader.biHeight=-1024;info.bmiHeader.biPlanes=1;info.bmiHeader.biBitCount=32;info.bmiHeader.biCompression=BI_RGB;
        void* pixels=nullptr;HBITMAP bitmap=CreateDIBSection(dc,&info,DIB_RGB_COLORS,&pixels,nullptr,0);HFONT face=CreateFontW(-46,0,0,0,FW_MEDIUM,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,ANTIALIASED_QUALITY,DEFAULT_PITCH,L"Bahnschrift");
        if(!bitmap||!face){if(bitmap)DeleteObject(bitmap);if(face)DeleteObject(face);DeleteDC(dc);throw std::runtime_error("launcher font atlas");}
        auto oldBitmap=SelectObject(dc,bitmap),oldFont=SelectObject(dc,face);std::memset(pixels,0,1024*1024*4);SetTextColor(dc,RGB(255,255,255));SetBkMode(dc,TRANSPARENT);
        for(int c=32;c<256;++c){wchar_t ch=wchar_t(c);SIZE extent{};GetTextExtentPoint32W(dc,&ch,1,&extent);advances[c]=float(extent.cx);TextOutW(dc,(c%16)*64+2,(c/16)*64+2,&ch,1);}
        GdiFlush();std::vector<uint32_t> data(1024*1024);const auto* src=static_cast<uint32_t*>(pixels);
        for(size_t i=0;i<data.size();++i){uint32_t v=src[i];uint32_t a=std::max({v&255,(v>>8)&255,(v>>16)&255});data[i]=(a<<24)|0xffffff;}
        SelectObject(dc,oldBitmap);SelectObject(dc,oldFont);DeleteObject(bitmap);DeleteObject(face);DeleteDC(dc);font=add(1024,1024,data);
    }
    void draw(int id,Rect r,Rect uv,Color c,int effect,float time){
        if(!recording||id<0||size_t(id)>=textures.size())throw std::runtime_error("launcher invalid draw");
        const float constants[16]={r.x,r.y,r.w,r.h,uv.x,uv.y,uv.w,uv.h,c.r,c.g,c.b,c.a,float(w),float(h),time,float(effect)};
        auto handle=srvs->GetGPUDescriptorHandleForHeapStart();handle.ptr+=size_t(id)*srvStride;list->SetGraphicsRootDescriptorTable(0,handle);list->SetGraphicsRoot32BitConstants(1,16,constants,0);list->DrawInstanced(effect==10?3:6,1,0,0);
    }
};

Renderer::Renderer(HWND window):p(std::make_unique<Impl>(window)){}
Renderer::~Renderer()=default;
int Renderer::texture(unsigned w,unsigned h,const std::vector<uint32_t>& pixels){return p->add(w,h,pixels);}
int Renderer::texture(const std::filesystem::path& path){
    ComPtr<IWICImagingFactory> factory;check(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&factory)),"launcher WIC");
    ComPtr<IWICBitmapDecoder> decoder;HRESULT decoded=factory->CreateDecoderFromFilename(path.c_str(),nullptr,GENERIC_READ,WICDecodeMetadataCacheOnDemand,&decoder);if(FAILED(decoded))return p->add(1,1,{offMonitor});   // missing/undecodable asset: a powered-off screen, not a crash
    ComPtr<IWICBitmapFrameDecode> frame;check(decoder->GetFrame(0,&frame),"launcher WIC frame");UINT w=0,h=0;check(frame->GetSize(&w,&h),"launcher image dimensions");if(w==0||h==0||w>8192||h>8192)throw std::runtime_error("launcher asset dimensions");
    ComPtr<IWICFormatConverter> convert;check(factory->CreateFormatConverter(&convert),"launcher WIC converter");check(convert->Initialize(frame.Get(),GUID_WICPixelFormat32bppBGRA,WICBitmapDitherTypeNone,nullptr,0,WICBitmapPaletteTypeCustom),"launcher WIC BGRA");
    std::vector<uint32_t> data(size_t(w)*h);check(convert->CopyPixels(nullptr,w*4,UINT(data.size()*4),reinterpret_cast<BYTE*>(data.data())),"launcher WIC pixels");return p->add(w,h,data);
}
void Renderer::begin(){
    p->resize();p->reset();auto* target=p->targets[p->swap->GetCurrentBackBufferIndex()].Get();p->barrier(target,D3D12_RESOURCE_STATE_PRESENT,D3D12_RESOURCE_STATE_RENDER_TARGET);
    auto rtv=p->rtvs->GetCPUDescriptorHandleForHeapStart();rtv.ptr+=size_t(p->swap->GetCurrentBackBufferIndex())*p->stride;const float black[4]={.002f,.003f,.008f,1};p->list->OMSetRenderTargets(1,&rtv,FALSE,nullptr);p->list->ClearRenderTargetView(rtv,black,0,nullptr);
    if(p->bezel_enabled)mk5bezel::draw(int(p->w),int(p->h),int(std::floor(p->ox)),int(std::floor(p->oy)),int(std::floor(p->ox+p->layout_width*p->scale)),int(std::floor(p->oy+layoutHeight*p->scale)),[&](int l,int t,int r,int b,float red,float green,float blue){const D3D12_RECT rect{l,t,r,b};const float color[4]={red,green,blue,1};p->list->ClearRenderTargetView(rtv,color,1,&rect);});
    D3D12_VIEWPORT viewport{0,0,float(p->w),float(p->h),0,1};D3D12_RECT scissor{0,0,LONG(p->w),LONG(p->h)};p->list->RSSetViewports(1,&viewport);p->list->RSSetScissorRects(1,&scissor);p->list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);p->list->SetGraphicsRootSignature(p->root.Get());auto* heap=p->srvs.Get();p->list->SetDescriptorHeaps(1,&heap);p->recording=true;
}
void Renderer::bezel(bool enabled){p->bezel_enabled=enabled;}
void Renderer::quad(int id,Rect r,Rect uv,Color c,int effect,float time){r={r.x*p->scale+p->ox,r.y*p->scale+p->oy,r.w*p->scale,r.h*p->scale};p->draw(id,r,uv,c,effect,time);}
void Renderer::fill(Rect r,Color c){quad(p->white,r,{0,0,1,1},c);}
void Renderer::rounded(Rect r,float radius,Color c,float border){quad(p->white,r,{radius*p->scale,border*p->scale,0,0},c,6);}
void Renderer::triangle(float ax,float ay,float bx,float by,float cx,float cy,Color c){p->draw(p->white,{ax*p->scale+p->ox,ay*p->scale+p->oy,bx*p->scale+p->ox,by*p->scale+p->oy},{cx*p->scale+p->ox,cy*p->scale+p->oy,0,0},c,10,0);}
void Renderer::line(float ax,float ay,float bx,float by,float t,Color c){float d=std::hypot(bx-ax,by-ay);if(d<.001f)return;float dx=-(by-ay)/d*t*.5f,dy=(bx-ax)/d*t*.5f;triangle(ax+dx,ay+dy,bx+dx,by+dy,ax-dx,ay-dy,c);triangle(ax-dx,ay-dy,bx+dx,by+dy,bx-dx,by-dy,c);}
void Renderer::text(const std::wstring& value,float x,float y,float size,Color c,float tracking){
    float origin=x;for(wchar_t ch:value){if(ch==L'\n'){x=origin;y+=size*1.45f;continue;}unsigned i=unsigned(ch)<256?unsigned(ch):unsigned('?');if(i>=32){float width=std::min(62.f,p->advances[i]+4);quad(p->font,{x,y,width/46*size,64.f/46*size},{float(i%16*64)/1024,float(i/16*64)/1024,width/1024,64.f/1024},c);}x+=p->advances[i]/46*size+tracking;}
}
float Renderer::textWidth(const std::wstring& value,float size,float tracking)const{float x=0,max=0;for(wchar_t ch:value){if(ch=='\n'){max=std::max(max,x);x=0;continue;}x+=p->advances[unsigned(ch)<256?unsigned(ch):unsigned('?')]/46*size+tracking;}return std::max(max,x);}
void Renderer::end(bool vsync){
    p->last=p->swap->GetCurrentBackBufferIndex();p->barrier(p->targets[p->last].Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_PRESENT);p->execute(false);p->recording=false;HRESULT result=p->swap->Present(vsync?1:0,0);if(result!=DXGI_STATUS_OCCLUDED)check(result,"launcher Present");++p->count;
}
std::vector<uint32_t> Renderer::capture(unsigned& width,unsigned& height){
    if(p->recording){throw std::runtime_error("launcher capture during frame");}
    p->wait();auto* target=p->targets[p->last].Get();auto d=target->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT layout{};UINT64 bytes=0;p->device->GetCopyableFootprints(&d,0,1,0,&layout,nullptr,nullptr,&bytes);auto read=p->resource(D3D12_HEAP_TYPE_READBACK,buffer(bytes),D3D12_RESOURCE_STATE_COPY_DEST);
    p->reset();p->barrier(target,D3D12_RESOURCE_STATE_PRESENT,D3D12_RESOURCE_STATE_COPY_SOURCE);D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=target;src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;D3D12_TEXTURE_COPY_LOCATION dest{};dest.pResource=read.Get();dest.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dest.PlacedFootprint=layout;p->list->CopyTextureRegion(&dest,0,0,0,&src,nullptr);p->barrier(target,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_PRESENT);p->execute();
    width=unsigned(d.Width);height=d.Height;std::vector<uint32_t> pixels(size_t(width)*height);void* data=nullptr;D3D12_RANGE range{0,SIZE_T(bytes)};check(read->Map(0,&range,&data),"launcher readback map");for(unsigned y=0;y<height;++y)std::memcpy(pixels.data()+size_t(y)*width,static_cast<char*>(data)+layout.Offset+size_t(y)*layout.Footprint.RowPitch,size_t(width)*4);D3D12_RANGE none{0,0};read->Unmap(0,&none);return pixels;
}
void Renderer::saveCapture(const std::filesystem::path& path){
    unsigned w=0,h=0;auto pixels=capture(w,h);ComPtr<IWICImagingFactory> factory;check(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&factory)),"launcher WIC capture");ComPtr<IWICStream> stream;check(factory->CreateStream(&stream),"launcher capture stream");check(stream->InitializeFromFilename(path.c_str(),GENERIC_WRITE),"launcher capture output");ComPtr<IWICBitmapEncoder> encoder;check(factory->CreateEncoder(GUID_ContainerFormatPng,nullptr,&encoder),"launcher PNG encoder");check(encoder->Initialize(stream.Get(),WICBitmapEncoderNoCache),"launcher PNG init");ComPtr<IWICBitmapFrameEncode> frame;ComPtr<IPropertyBag2> properties;check(encoder->CreateNewFrame(&frame,&properties),"launcher PNG frame");check(frame->Initialize(properties.Get()),"launcher PNG frame init");check(frame->SetSize(w,h),"launcher PNG size");auto format=GUID_WICPixelFormat32bppBGRA;check(frame->SetPixelFormat(&format),"launcher PNG pixel format");check(frame->WritePixels(h,w*4,UINT(pixels.size()*4),reinterpret_cast<BYTE*>(pixels.data())),"launcher PNG pixels");check(frame->Commit(),"launcher PNG frame commit");check(encoder->Commit(),"launcher PNG commit");
}
void Renderer::mouse(POINT pt,float& x,float& y)const{x=(pt.x-p->ox)/p->scale;y=(pt.y-p->oy)/p->scale;}
uint64_t Renderer::frames()const{return p->count;}
unsigned Renderer::width()const{return p->w;}
unsigned Renderer::height()const{return p->h;}
float Renderer::layoutWidth()const{return p->layout_width;}
}
