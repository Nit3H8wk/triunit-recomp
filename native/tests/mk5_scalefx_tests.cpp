#define NOMINMAX
#include "mk5_scalefx.hpp"
#include <iostream>
#include <stdexcept>
using Microsoft::WRL::ComPtr;
void need(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(){try{
 ComPtr<ID3D12Device> device;mk5sfx::check(D3D12CreateDevice(nullptr,D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)));
 ComPtr<ID3D12CommandQueue> queue;D3D12_COMMAND_QUEUE_DESC q{};mk5sfx::check(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)));
 ComPtr<ID3D12CommandAllocator> allocator;mk5sfx::check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)));
 ComPtr<ID3D12GraphicsCommandList> commands;mk5sfx::check(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&commands)));commands->Close();
 ComPtr<ID3D12Fence> fence;mk5sfx::check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));UINT64 serial=0;
 auto run=[&](const std::vector<uint32_t>& pixels,unsigned w,unsigned h,unsigned amount){
  mk5sfx::Pipeline filter(device.Get());auto source=mk5sfx::texture(device.Get(),w,h,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_NONE,D3D12_RESOURCE_STATE_COPY_DEST);
  auto desc=source->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT layout{};UINT64 bytes=0;device->GetCopyableFootprints(&desc,0,1,0,&layout,nullptr,nullptr,&bytes);
  auto upload=mk5sfx::buffer(device.Get(),bytes,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);void* mapped=nullptr;D3D12_RANGE none{};mk5sfx::check(upload->Map(0,&none,&mapped));
  for(unsigned y=0;y<h;++y)std::memcpy(static_cast<unsigned char*>(mapped)+layout.Offset+size_t(y)*layout.Footprint.RowPitch,pixels.data()+size_t(y)*w,w*4);
  upload->Unmap(0,nullptr);
  mk5sfx::check(allocator->Reset());mk5sfx::check(commands->Reset(allocator.Get(),nullptr));D3D12_TEXTURE_COPY_LOCATION dest{},src{};dest.pResource=source.Get();dest.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;src.pResource=upload.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=layout;
  commands->CopyTextureRegion(&dest,0,0,0,&src,nullptr);mk5sfx::barrier(commands.Get(),source.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
  filter.prepare(source.Get(),w,h);filter.draw(commands.Get(),amount);auto capture=filter.capture(commands.Get());mk5sfx::check(commands->Close());ID3D12CommandList* list=commands.Get();queue->ExecuteCommandLists(1,&list);mk5sfx::check(queue->Signal(fence.Get(),++serial));
  auto until=GetTickCount64()+5000;while(fence->GetCompletedValue()<serial&&GetTickCount64()<until)Sleep(1);need(fence->GetCompletedValue()>=serial,"GPU timeout");return capture.pixels();
 };
 auto flat=run({0xff205080},1,1,100);need(flat==std::vector<uint32_t>(9,0xff205080),"1x1 clamp/flat preservation");
 std::vector<uint32_t> diagonal(7*7,0xff000000);for(unsigned y=0;y<7;++y)for(unsigned x=0;x<7;++x)if(x<=y)diagonal[y*7+x]=0xffffffff;
 const auto original=diagonal;auto full=run(diagonal,7,7,100),zero=run(diagonal,7,7,0),quarter=run(diagonal,7,7,25);unsigned changed=0;
 for(unsigned y=0;y<21;++y)for(unsigned x=0;x<21;++x){auto at=y*21+x;need(zero[at]==diagonal[(y/3)*7+x/3],"0% must preserve every original pixel");need(full[at]==0xff000000||full[at]==0xffffffff,"100% must use source palette");changed+=full[at]!=zero[at];
  for(unsigned c=0;c<24;c+=8){int expected=int(std::lround(((zero[at]>>c)&255)*.75+((full[at]>>c)&255)*.25));need(std::abs(int((quarter[at]>>c)&255)-expected)<=1,"25% blend at every output channel");}}
 need(changed>0,"ScaleFX must reconstruct diagonal subpixels");need(diagonal==original,"source raster unchanged");
 auto solid=run(std::vector<uint32_t>(35,0xff102030),5,7,100);need(solid==std::vector<uint32_t>(35*9,0xff102030),"non-square flat and borders");
 std::cout<<"PASS ScaleFX five GPU passes: flat, borders, diagonal, original palette, 0/25/100%, source intact; changed="<<changed<<"\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
