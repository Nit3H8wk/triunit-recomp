#pragma once
// renderer_hal.h — Graphics / Presentation abstraction for TriUnit Recomp.
// Decouples the core game logic from D3D12/DXGI so a Vulkan 1.3 backend can run
// on Linux. On Windows these map to the existing D3D12 implementations; on
// Linux they are satisfied by headless stubs (Phase 1) and real Vulkan/SDL3
// (Phase 3).
#include "platform_hal.h"
#include <cstdint>
#include <memory>
#include <vector>

namespace triunit::gfx {

struct WindowConfig {
    const char* title = "";
    int width = 640, height = 480;
    bool fullscreen = false;
    bool vsync = true;
    bool vrr = false; // G-Sync / FreeSync
};

struct TextureConfig {
    int width = 1, height = 1;
    bool srgb = false;
    bool is_depth = false;
};

struct RenderPassDesc {
    const void* spirv = nullptr; // SPIR-V binary (replaces ID3DBlob DXIL)
    size_t spirv_size = 0;
    const char* entry_point = "main";
    int bind_count = 0;          // number of bound textures
};

class Renderer {
    struct Impl; std::unique_ptr<Impl> impl;
    explicit Renderer();
public:
    static Renderer create(const WindowConfig& cfg);
    ~Renderer();
    Renderer(const Renderer&) = delete;
    Renderer(Renderer&& other) noexcept;
    Renderer& operator=(const Renderer&) = delete;
    Renderer& operator=(Renderer&& other) noexcept;

    // Surface / Swapchain
    void resize(int width, int height);
    void present(); // vkQueuePresentKHR with VRR support

    // Resources
    uint32_t create_texture(const TextureConfig& cfg);
    void destroy_texture(uint32_t tex);
    void upload_texture(uint32_t tex, const uint8_t* data, size_t size);

    // Pipeline / Shaders
    uint32_t create_pipeline(const RenderPassDesc& desc);
    void destroy_pipeline(uint32_t pipe);

    // Frame rendering
    void begin_frame();
    void bind_pipeline(uint32_t pipe);
    void bind_texture(int slot, uint32_t tex);
    void set_uniforms(const float* data, size_t floats);
    void draw_fullscreen_quad();
    void end_frame();

    // HDR / Color
    void set_hdr_metadata(float paper_white, float peak_nits);
    void set_srgb_output(bool enabled);

    // Window integration (SDL3)
    void set_window(void* sdl_window); // SDL_Window*
    bool should_close();
    bool valid() const;
};

} // namespace triunit::gfx
