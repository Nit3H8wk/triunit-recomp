#pragma once
#include "mk5_scalefx.hpp"
#include "mk5_smaa_shader.hpp"

namespace mk5smaa {
using Microsoft::WRL::ComPtr;
using mk5sfx::barrier;
using mk5sfx::buffer;
using mk5sfx::texture;

inline void check(HRESULT hr) {
    if (FAILED(hr)) throw std::runtime_error("SMAA DX12 failure: " + std::to_string(uint32_t(hr)));
}

class Pipeline {
    static constexpr unsigned pass_count = 3, descriptors_per_pass = 3;
    static constexpr unsigned output_slot = pass_count * descriptors_per_pass;
    static constexpr DXGI_FORMAT formats[pass_count] = {
        DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_FORMAT_B8G8R8A8_UNORM
    };
    struct Lookup {
        ComPtr<ID3D12Resource> image;
        ComPtr<ID3D12Resource> upload;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT layout{};
    };

    ID3D12Device* device_;
    UINT srv_stride_, rtv_stride_;
    unsigned width_ = 0, height_ = 0;
    ComPtr<ID3D12DescriptorHeap> srv_, rtv_;
    ComPtr<ID3D12RootSignature> root_;
    std::array<ComPtr<ID3D12PipelineState>, pass_count> pipelines_;
    std::array<ComPtr<ID3D12Resource>, pass_count> images_;
    Lookup area_, search_;
    bool lookups_ready_ = false;

    D3D12_CPU_DESCRIPTOR_HANDLE render_target(unsigned index) const {
        auto at = rtv_->GetCPUDescriptorHandleForHeapStart();
        at.ptr += size_t(index) * rtv_stride_;
        return at;
    }
    D3D12_GPU_DESCRIPTOR_HANDLE shader_resource(unsigned index) const {
        auto at = srv_->GetGPUDescriptorHandleForHeapStart();
        at.ptr += size_t(index) * srv_stride_;
        return at;
    }
    void create_view(unsigned index, ID3D12Resource* image, DXGI_FORMAT format) {
        D3D12_SHADER_RESOURCE_VIEW_DESC view{};
        view.Format = format;
        view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
        view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        view.Texture2D.MipLevels = 1;
        auto at = srv_->GetCPUDescriptorHandleForHeapStart();
        at.ptr += size_t(index) * srv_stride_;
        device_->CreateShaderResourceView(image, &view, at);
    }
    Lookup make_lookup(unsigned w, unsigned h, unsigned pitch, DXGI_FORMAT format, const unsigned char* data) {
        Lookup lookup;
        lookup.image = texture(device_, w, h, format, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST);
        const auto desc = lookup.image->GetDesc();
        UINT64 bytes = 0;
        device_->GetCopyableFootprints(&desc, 0, 1, 0, &lookup.layout, nullptr, nullptr, &bytes);
        lookup.upload = buffer(device_, bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
        void* mapped = nullptr;
        D3D12_RANGE none{};
        check(lookup.upload->Map(0, &none, &mapped));
        for (unsigned y = 0; y < h; ++y) {
            std::memcpy(static_cast<unsigned char*>(mapped) + lookup.layout.Offset + size_t(y) * lookup.layout.Footprint.RowPitch,
                data + size_t(y) * pitch, pitch);
        }
        lookup.upload->Unmap(0, nullptr);
        return lookup;
    }
    static void upload_lookup(ID3D12GraphicsCommandList* cmd, const Lookup& lookup) {
        D3D12_TEXTURE_COPY_LOCATION dest{}, source{};
        dest.pResource = lookup.image.Get();
        dest.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        source.pResource = lookup.upload.Get();
        source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        source.PlacedFootprint = lookup.layout;
        cmd->CopyTextureRegion(&dest, 0, 0, 0, &source, nullptr);
        barrier(cmd, lookup.image.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
    }
    static ComPtr<ID3DBlob> compile(const char* entry, const char* target) {
        ComPtr<ID3DBlob> code, error;
        const auto hr = D3DCompile(shader, sizeof(shader) - 1, "SMAA", nullptr, nullptr, entry, target,
            D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &code, &error);
        if (FAILED(hr)) {
            throw std::runtime_error(std::string("SMAA ") + entry + ": "
                + (error ? std::string(static_cast<const char*>(error->GetBufferPointer()), error->GetBufferSize()) : "compile failure"));
        }
        return code;
    }

public:
    explicit Pipeline(ID3D12Device* device)
        : device_(device), srv_stride_(device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV)),
          rtv_stride_(device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV)) {
        D3D12_DESCRIPTOR_HEAP_DESC heap{};
        heap.NumDescriptors = output_slot + 1;
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        check(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&srv_)));
        heap.NumDescriptors = pass_count;
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        check(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&rtv_)));

        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = descriptors_per_pass;
        D3D12_ROOT_PARAMETER params[2]{};
        params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        params[0].DescriptorTable = {1, &range};
        params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
        params[1].Constants.Num32BitValues = 4;
        D3D12_STATIC_SAMPLER_DESC samplers[2]{};
        for (unsigned i = 0; i < 2; ++i) {
            auto& sampler = samplers[i];
            sampler.Filter = i ? D3D12_FILTER_MIN_MAG_MIP_POINT : D3D12_FILTER_MIN_MAG_LINEAR_MIP_POINT;
            sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
            sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_NEVER;
            sampler.MaxLOD = D3D12_FLOAT32_MAX;
            sampler.ShaderRegister = i;
            sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        }
        D3D12_ROOT_SIGNATURE_DESC root_desc{};
        root_desc.NumParameters = 2;
        root_desc.pParameters = params;
        root_desc.NumStaticSamplers = 2;
        root_desc.pStaticSamplers = samplers;
        ComPtr<ID3DBlob> root;
        check(D3D12SerializeRootSignature(&root_desc, D3D_ROOT_SIGNATURE_VERSION_1, &root, nullptr));
        check(device->CreateRootSignature(0, root->GetBufferPointer(), root->GetBufferSize(), IID_PPV_ARGS(&root_)));

        const char* vertex[] = {"edgeVS", "weightsVS", "neighborhoodVS"};
        const char* pixel[] = {"edgePS", "weightsPS", "neighborhoodPS"};
        for (unsigned i = 0; i < pass_count; ++i) {
            const auto vs = compile(vertex[i], "vs_5_0");
            const auto ps = compile(pixel[i], "ps_5_0");
            D3D12_GRAPHICS_PIPELINE_STATE_DESC state{};
            state.pRootSignature = root_.Get();
            state.VS = {vs->GetBufferPointer(), vs->GetBufferSize()};
            state.PS = {ps->GetBufferPointer(), ps->GetBufferSize()};
            state.BlendState.RenderTarget[0].RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
            state.SampleMask = UINT_MAX;
            state.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
            state.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
            state.RasterizerState.DepthClipEnable = TRUE;
            state.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
            state.NumRenderTargets = 1;
            state.RTVFormats[0] = formats[i];
            state.SampleDesc.Count = 1;
            check(device->CreateGraphicsPipelineState(&state, IID_PPV_ARGS(&pipelines_[i])));
        }
        area_ = make_lookup(upstream::area_width, upstream::area_height, upstream::area_pitch, DXGI_FORMAT_R8G8_UNORM, upstream::areaTexBytes);
        search_ = make_lookup(upstream::search_width, upstream::search_height, upstream::search_pitch, DXGI_FORMAT_R8_UNORM, upstream::searchTexBytes);
        create_view(4, area_.image.Get(), DXGI_FORMAT_R8G8_UNORM);
        create_view(5, search_.image.Get(), DXGI_FORMAT_R8_UNORM);
    }

    void prepare(ID3D12Resource* source, unsigned w, unsigned h) {
        // The caller retires earlier submissions before replacing resources or descriptors.
        if (w != width_ || h != height_) {
            for (unsigned i = 0; i < pass_count; ++i) {
                images_[i] = texture(device_, w, h, formats[i], D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET,
                    D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
                device_->CreateRenderTargetView(images_[i].Get(), nullptr, render_target(i));
            }
            width_ = w;
            height_ = h;
            create_view(3, images_[0].Get(), formats[0]);
            create_view(7, images_[1].Get(), formats[1]);
            create_view(output_slot, resource_output(), formats[2]);
        }
        create_view(0, source, DXGI_FORMAT_B8G8R8A8_UNORM);
        create_view(1, source, DXGI_FORMAT_B8G8R8A8_UNORM);
        create_view(2, source, DXGI_FORMAT_B8G8R8A8_UNORM);
        create_view(6, source, DXGI_FORMAT_B8G8R8A8_UNORM);
        create_view(8, source, DXGI_FORMAT_B8G8R8A8_UNORM);
    }

    void draw(ID3D12GraphicsCommandList* cmd) {
        if (!lookups_ready_) {
            upload_lookup(cmd, area_);
            upload_lookup(cmd, search_);
            lookups_ready_ = true;
        }
        auto* descriptors = srv_.Get();
        cmd->SetDescriptorHeaps(1, &descriptors);
        cmd->SetGraphicsRootSignature(root_.Get());
        const float metrics[4] = {1.f / width_, 1.f / height_, float(width_), float(height_)};
        cmd->SetGraphicsRoot32BitConstants(1, 4, metrics, 0);
        cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        D3D12_VIEWPORT view{0, 0, float(width_), float(height_), 0, 1};
        D3D12_RECT clip{0, 0, LONG(width_), LONG(height_)};
        cmd->RSSetViewports(1, &view);
        cmd->RSSetScissorRects(1, &clip);
        const float clear[4]{};
        for (unsigned i = 0; i < pass_count; ++i) {
            auto* image = images_[i].Get();
            barrier(cmd, image, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
            auto rtv = render_target(i);
            cmd->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
            if (i < 2) cmd->ClearRenderTargetView(rtv, clear, 0, nullptr);
            cmd->SetGraphicsRootDescriptorTable(0, shader_resource(i * descriptors_per_pass));
            cmd->SetPipelineState(pipelines_[i].Get());
            cmd->DrawInstanced(3, 1, 0, 0);
            barrier(cmd, image, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        }
    }

    mk5sfx::Capture capture(ID3D12GraphicsCommandList* cmd) {
        mk5sfx::Capture capture;
        capture.width = width_;
        capture.height = height_;
        auto* image = resource_output();
        const auto desc = image->GetDesc();
        UINT64 bytes = 0;
        device_->GetCopyableFootprints(&desc, 0, 1, 0, &capture.layout, nullptr, nullptr, &bytes);
        capture.memory = buffer(device_, bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION dest{}, source{};
        dest.pResource = capture.memory.Get();
        dest.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dest.PlacedFootprint = capture.layout;
        source.pResource = image;
        source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        barrier(cmd, image, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_SOURCE);
        cmd->CopyTextureRegion(&dest, 0, 0, 0, &source, nullptr);
        barrier(cmd, image, D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        return capture;
    }

    ID3D12Resource* resource_output() const { return images_.back().Get(); }
    ID3D12DescriptorHeap* heap() const { return srv_.Get(); }
    D3D12_GPU_DESCRIPTOR_HANDLE output() const { return shader_resource(output_slot); }
};
}
