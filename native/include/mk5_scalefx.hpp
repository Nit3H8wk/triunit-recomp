#pragma once
#include "mk5_scalefx_shader.hpp"
#include <windows.h>
#include <d3d12.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <array>
#include <vector>
#include <string>
#include <stdexcept>
#include <cstring>
#include <cmath>
#include <cstdint>
namespace mk5sfx {
using Microsoft::WRL::ComPtr;
inline void check(HRESULT hr){if(FAILED(hr))throw std::runtime_error("ScaleFX DX12 failure: "+std::to_string(uint32_t(hr)));}
inline void barrier(ID3D12GraphicsCommandList* cmd,ID3D12Resource* resource,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after){
 D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;b.Transition={resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};cmd->ResourceBarrier(1,&b);
}
inline ComPtr<ID3D12Resource> resource(ID3D12Device* device,const D3D12_RESOURCE_DESC& desc,D3D12_HEAP_TYPE heap,D3D12_RESOURCE_STATES state){
 D3D12_HEAP_PROPERTIES props{};props.Type=heap;ComPtr<ID3D12Resource> result;check(device->CreateCommittedResource(&props,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&result)));return result;
}
inline ComPtr<ID3D12Resource> texture(ID3D12Device* device,unsigned w,unsigned h,DXGI_FORMAT format,D3D12_RESOURCE_FLAGS flags,D3D12_RESOURCE_STATES state){
 D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=w;d.Height=h;d.DepthOrArraySize=1;d.MipLevels=1;d.Format=format;d.SampleDesc.Count=1;d.Flags=flags;return resource(device,d,D3D12_HEAP_TYPE_DEFAULT,state);
}
inline ComPtr<ID3D12Resource> buffer(ID3D12Device* device,UINT64 bytes,D3D12_HEAP_TYPE heap,D3D12_RESOURCE_STATES state){
 D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;d.Width=bytes;d.Height=1;d.DepthOrArraySize=1;d.MipLevels=1;d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;return resource(device,d,heap,state);
}
struct Capture {
 ComPtr<ID3D12Resource> memory;D3D12_PLACED_SUBRESOURCE_FOOTPRINT layout{};unsigned width=0,height=0;
 std::vector<uint32_t> pixels(){
  void* ptr=nullptr;D3D12_RANGE read{0,size_t(memory->GetDesc().Width)};check(memory->Map(0,&read,&ptr));std::vector<uint32_t> out(size_t(width)*height);
  for(unsigned y=0;y<height;++y)std::memcpy(out.data()+size_t(y)*width,static_cast<unsigned char*>(ptr)+layout.Offset+size_t(y)*layout.Footprint.RowPitch,width*4);
  D3D12_RANGE none{};memory->Unmap(0,&none);return out;
 }
};
class Pipeline {
 ID3D12Device* device_;unsigned width_=0,height_=0;UINT srv_stride_=0,rtv_stride_=0;
 ComPtr<ID3D12DescriptorHeap> srv_,rtv_;ComPtr<ID3D12RootSignature> root_;
 std::array<ComPtr<ID3D12PipelineState>,5> pipelines_;
 std::array<ComPtr<ID3D12Resource>,5> images_;
public:
 explicit Pipeline(ID3D12Device* device):device_(device){
  D3D12_DESCRIPTOR_HEAP_DESC h{};h.NumDescriptors=6;h.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;h.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;check(device->CreateDescriptorHeap(&h,IID_PPV_ARGS(&srv_)));
  h.NumDescriptors=5;h.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;h.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_NONE;check(device->CreateDescriptorHeap(&h,IID_PPV_ARGS(&rtv_)));
  srv_stride_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);rtv_stride_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
  D3D12_DESCRIPTOR_RANGE range{};range.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_SRV;range.NumDescriptors=5;
  D3D12_ROOT_PARAMETER p[2]{};p[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;p[0].DescriptorTable={1,&range};p[0].ShaderVisibility=D3D12_SHADER_VISIBILITY_PIXEL;p[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;p[1].Constants.Num32BitValues=4;p[1].ShaderVisibility=D3D12_SHADER_VISIBILITY_PIXEL;
  D3D12_STATIC_SAMPLER_DESC sampler{};sampler.Filter=D3D12_FILTER_MIN_MAG_MIP_POINT;sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D12_TEXTURE_ADDRESS_MODE_CLAMP;sampler.MaxLOD=D3D12_FLOAT32_MAX;sampler.ShaderVisibility=D3D12_SHADER_VISIBILITY_PIXEL;
  D3D12_ROOT_SIGNATURE_DESC desc{};desc.NumParameters=2;desc.pParameters=p;desc.NumStaticSamplers=1;desc.pStaticSamplers=&sampler;ComPtr<ID3DBlob> data,error;
  check(D3D12SerializeRootSignature(&desc,D3D_ROOT_SIGNATURE_VERSION_1,&data,&error));check(device->CreateRootSignature(0,data->GetBufferPointer(),data->GetBufferSize(),IID_PPV_ARGS(&root_)));
  ComPtr<ID3DBlob> vs;auto compiled=D3DCompile(shader,sizeof(shader),nullptr,nullptr,nullptr,"vs","vs_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&vs,&error);
  if(FAILED(compiled))throw std::runtime_error(error?std::string(static_cast<const char*>(error->GetBufferPointer()),error->GetBufferSize()):"ScaleFX vertex compilation");
  for(unsigned pass=0;pass<5;++pass){ComPtr<ID3DBlob> ps;auto entry="ps"+std::to_string(pass);auto hr=D3DCompile(shader,sizeof(shader),nullptr,nullptr,nullptr,entry.c_str(),"ps_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&ps,&error);
   if(FAILED(hr))throw std::runtime_error("ScaleFX "+entry+": "+(error?std::string(static_cast<const char*>(error->GetBufferPointer()),error->GetBufferSize()):"compile failure"));
   D3D12_GRAPHICS_PIPELINE_STATE_DESC state{};state.pRootSignature=root_.Get();state.VS={vs->GetBufferPointer(),vs->GetBufferSize()};state.PS={ps->GetBufferPointer(),ps->GetBufferSize()};state.BlendState.RenderTarget[0].RenderTargetWriteMask=D3D12_COLOR_WRITE_ENABLE_ALL;state.SampleMask=UINT_MAX;state.RasterizerState.FillMode=D3D12_FILL_MODE_SOLID;state.RasterizerState.CullMode=D3D12_CULL_MODE_NONE;state.RasterizerState.DepthClipEnable=TRUE;state.PrimitiveTopologyType=D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;state.NumRenderTargets=1;state.RTVFormats[0]=pass==4?DXGI_FORMAT_B8G8R8A8_UNORM:DXGI_FORMAT_R32G32B32A32_FLOAT;state.SampleDesc.Count=1;
   check(device->CreateGraphicsPipelineState(&state,IID_PPV_ARGS(&pipelines_[pass])));
  }
 }
 void prepare(ID3D12Resource* source,unsigned w,unsigned h){
  // Caller retires its previous submission before changing descriptors/resources.
  if(w!=width_||h!=height_){width_=w;height_=h;for(unsigned i=0;i<5;++i){unsigned scale=i==4?3:1;auto format=i==4?DXGI_FORMAT_B8G8R8A8_UNORM:DXGI_FORMAT_R32G32B32A32_FLOAT;
    images_[i]=texture(device_,w*scale,h*scale,format,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
    auto rtv=rtv_->GetCPUDescriptorHandleForHeapStart();rtv.ptr+=size_t(i)*rtv_stride_;device_->CreateRenderTargetView(images_[i].Get(),nullptr,rtv);
  }}
  for(unsigned i=0;i<6;++i){auto* image=i?images_[i-1].Get():source;D3D12_SHADER_RESOURCE_VIEW_DESC view{};view.Format=image->GetDesc().Format;view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;view.Texture2D.MipLevels=1;auto at=srv_->GetCPUDescriptorHandleForHeapStart();at.ptr+=size_t(i)*srv_stride_;device_->CreateShaderResourceView(image,&view,at);}
 }
 void draw(ID3D12GraphicsCommandList* cmd,unsigned amount){
  cmd->SetGraphicsRootSignature(root_.Get());auto* heap=srv_.Get();cmd->SetDescriptorHeaps(1,&heap);cmd->SetGraphicsRootDescriptorTable(0,srv_->GetGPUDescriptorHandleForHeapStart());const float settings[4]={float(width_),float(height_),float(amount),0};cmd->SetGraphicsRoot32BitConstants(1,4,settings,0);cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
  for(unsigned i=0;i<5;++i){auto* image=images_[i].Get();barrier(cmd,image,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);auto rtv=rtv_->GetCPUDescriptorHandleForHeapStart();rtv.ptr+=size_t(i)*rtv_stride_;cmd->OMSetRenderTargets(1,&rtv,FALSE,nullptr);
   const unsigned scale=i==4?3:1;D3D12_VIEWPORT v{0,0,float(width_*scale),float(height_*scale),0,1};D3D12_RECT clip{0,0,LONG(width_*scale),LONG(height_*scale)};cmd->RSSetViewports(1,&v);cmd->RSSetScissorRects(1,&clip);cmd->SetPipelineState(pipelines_[i].Get());cmd->DrawInstanced(3,1,0,0);barrier(cmd,image,D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
  }
 }
 Capture capture(ID3D12GraphicsCommandList* cmd){
  Capture c;c.width=width_*3;c.height=height_*3;auto* image=images_[4].Get();auto desc=image->GetDesc();UINT64 bytes=0;device_->GetCopyableFootprints(&desc,0,1,0,&c.layout,nullptr,nullptr,&bytes);c.memory=buffer(device_,bytes,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
  barrier(cmd,image,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE);D3D12_TEXTURE_COPY_LOCATION source{},dest{};source.pResource=image;source.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;dest.pResource=c.memory.Get();dest.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dest.PlacedFootprint=c.layout;cmd->CopyTextureRegion(&dest,0,0,0,&source,nullptr);barrier(cmd,image,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);return c;
 }
 ID3D12Resource* resource_output()const{return images_.back().Get();}
 ID3D12DescriptorHeap* heap()const{return srv_.Get();}
 D3D12_GPU_DESCRIPTOR_HANDLE output()const{auto h=srv_->GetGPUDescriptorHandleForHeapStart();h.ptr+=size_t(5)*srv_stride_;return h;}
};
}
