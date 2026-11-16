#define NOMINMAX
#include "mk5_smaa.hpp"
#include <algorithm>
#include <iostream>

using Microsoft::WRL::ComPtr;

int main() {
    try {
        ComPtr<ID3D12Device> device;
        mk5sfx::check(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)));
        ComPtr<ID3D12CommandQueue> queue;
        D3D12_COMMAND_QUEUE_DESC queue_desc{};
        mk5sfx::check(device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)));
        ComPtr<ID3D12CommandAllocator> allocator;
        mk5sfx::check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)));
        ComPtr<ID3D12GraphicsCommandList> commands;
        mk5sfx::check(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&commands)));
        mk5sfx::check(commands->Close());
        ComPtr<ID3D12Fence> fence;
        mk5sfx::check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
        UINT64 serial = 0;

        mk5smaa::Pipeline filter(device.Get());
        ComPtr<ID3D12Resource> source;
        auto run = [&](const std::vector<uint32_t>& pixels, unsigned w, unsigned h,
                       DXGI_FORMAT format = DXGI_FORMAT_B8G8R8A8_TYPELESS) {
            bool same_size = source && source->GetDesc().Width == w && source->GetDesc().Height == h;
            if (!same_size) {
                source = mk5sfx::texture(device.Get(), w, h, format,
                    D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST);
                filter.prepare(source.Get(), w, h);
            }
            const auto desc = source->GetDesc();
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT layout{};
            UINT64 bytes = 0;
            device->GetCopyableFootprints(&desc, 0, 1, 0, &layout, nullptr, nullptr, &bytes);
            auto upload = mk5sfx::buffer(device.Get(), bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
            void* mapped = nullptr;
            D3D12_RANGE none{};
            mk5sfx::check(upload->Map(0, &none, &mapped));
            for (unsigned y = 0; y < h; ++y) {
                std::memcpy(static_cast<unsigned char*>(mapped) + layout.Offset + size_t(y) * layout.Footprint.RowPitch,
                    pixels.data() + size_t(y) * w, size_t(w) * 4);
            }
            upload->Unmap(0, nullptr);

            mk5sfx::check(allocator->Reset());
            mk5sfx::check(commands->Reset(allocator.Get(), nullptr));
            if (same_size) {
                mk5sfx::barrier(commands.Get(), source.Get(), D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
            }
            D3D12_TEXTURE_COPY_LOCATION dest{}, src{};
            dest.pResource = source.Get();
            dest.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            src.pResource = upload.Get();
            src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            src.PlacedFootprint = layout;
            commands->CopyTextureRegion(&dest, 0, 0, 0, &src, nullptr);
            mk5sfx::barrier(commands.Get(), source.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
            filter.draw(commands.Get());
            auto capture = filter.capture(commands.Get());
            mk5sfx::check(commands->Close());
            ID3D12CommandList* list = commands.Get();
            queue->ExecuteCommandLists(1, &list);
            mk5sfx::check(queue->Signal(fence.Get(), ++serial));
            const auto timeout = GetTickCount64() + 5000;
            while (fence->GetCompletedValue() < serial && GetTickCount64() < timeout) Sleep(1);
            if (fence->GetCompletedValue() < serial) throw std::runtime_error("SMAA GPU timeout");
            return capture.pixels();
        };

        const unsigned w = 41, h = 29;
        std::vector<uint32_t> diagonal(w * h, 0xff000000);
        for (unsigned y = 0; y < h; ++y) {
            for (unsigned x = 0; x < w; ++x) {
                if (x <= 6 + y * 2 / 3) diagonal[y * w + x] = 0xffffffff;
            }
        }
        auto filtered = run(diagonal, w, h);
        const auto blended = std::count_if(filtered.begin(), filtered.end(), [](uint32_t pixel) {
            return pixel > 0xff000000 && pixel < 0xffffffff;
        });
        if (filtered.size() != diagonal.size() || !blended || filtered.front() != diagonal.front()
            || filtered.back() != diagonal.back()) throw std::runtime_error("SMAA diagonal or flat areas differ");

        std::vector<uint32_t> vertical(w * h, 0xff102030);
        for (unsigned y = 0; y < h; ++y) {
            std::fill_n(vertical.begin() + y * w, w / 2, 0xffd0b090);
        }
        if (run(vertical, w, h) != vertical) throw std::runtime_error("SMAA axis-aligned edge or previous-frame weights");

        const std::vector<uint32_t> flat{0xff215182};
        if (run(flat, 1, 1, DXGI_FORMAT_B8G8R8A8_UNORM) != flat) {
            throw std::runtime_error("SMAA resize, typed input or 1x1 clamp");
        }
        std::cout << "PASS SMAA 1x diagonal, axis-aligned edge, current frame and 1x1 resize; blended=" << blended << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
